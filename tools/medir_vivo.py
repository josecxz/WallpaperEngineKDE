#!/usr/bin/env python3
"""Mide lo que cuesta el fondo EN VIVO, siempre de la misma manera.

Es la vara de medir de la auditoria de rendimiento: cada cambio se mide con
esto antes y despues, con la misma escena, el mismo tiempo y el mismo estado,
y se comparan los dos JSON. Por que estos instrumentos y no otros (NOTAS,
"La vara de medir del rendimiento"):

* **Fotogramas ejecutados, CPU y GPU por fotograma, copia entre GPUs**: los
  cuenta el propio motor con `WE_MEDIDAS=1` (src/sceneview.cpp, una linea
  `SceneView: medida` por pantalla y segundo). La GPU sale de `GL_TIME_ELAPSED`
  leido sin esperar, que es lo unico que mide la GPU de verdad: el fps del HUD
  sale del reloj de QML y llego a decir 166 con la GPU al 98 % (NOTAS:2197).
* **La integrada** (donde Qt compone y se sube la copia): `/proc/<pid>/fdinfo`
  del i915, sumando por cliente DRM y no por descriptor (NOTAS:1375).
* **La NVIDIA** no publica `fdinfo` por cliente con el driver propietario; de
  ella hay el cronometro del motor (preciso) y `nvidia-smi pmon` (grueso, por
  muestreo, solo como contraste). `pmon` despierta la dedicada si dormia: aqui
  no duerme nunca, pero por eso se puede quitar con `--sin-pmon`.
* **CPU y memoria del proceso**: `/proc/<pid>/stat` y `status`.

Para que la medida no dependa de que haya ventanas encima, el fondo se lanza
aparte (`wallpaperengine-medida`), **sin pausa** y con un solo plan para todas
las pantallas; el fondo normal se para mientras tanto y se vuelve a poner al
acabar. Solo Hyprland: en Plasma el fondo vive dentro de plasmashell, que no
se reinicia para medir (CLAUDE.md, regla 3).

Uso:
    python3 tools/medir_vivo.py [--wallpaper ID | --plan DIR]
                                [--segundos 20] [--calentar 5]
                                [--guardar a.json] [--comparar b.json]
                                [-- opciones del anfitrion: --encaje 1 ...]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wectl  # noqa: E402

UNIDAD = "wallpaperengine-medida"
REGISTRO = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "wallpaperengine-medida.log"
LINEA = re.compile(r"SceneView: medida (.*)$")


# ── muestras del proceso ────────────────────────────────────────────────────

def _cpu_s(pid: int) -> float:
    campos = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    # Tras el nombre: estado es el campo 3, utime el 14 y stime el 15.
    return (int(campos[11]) + int(campos[12])) / os.sysconf("SC_CLK_TCK")


def _rss_mb(pid: int) -> float:
    for linea in Path(f"/proc/{pid}/status").read_text().splitlines():
        if linea.startswith("VmRSS:"):
            return int(linea.split()[1]) / 1024
    return 0.0


def _motores_drm(pid: int) -> dict[str, int]:
    """ns acumulados por motor, sumando cada cliente DRM UNA vez."""
    clientes: dict[tuple[str, str], dict[str, int]] = {}
    for f in Path(f"/proc/{pid}/fdinfo").iterdir():
        try:
            texto = f.read_text()
        except OSError:
            continue
        if "drm-client-id" not in texto:
            continue
        campos = dict(l.split(":", 1) for l in texto.splitlines() if ":" in l)
        clave = (campos.get("drm-pdev", "").strip(), campos["drm-client-id"].strip())
        if clave in clientes:
            continue
        motores = {}
        for k, v in campos.items():
            if k.startswith("drm-engine-") and not k.startswith("drm-engine-capacity"):
                v = v.strip()
                if v.endswith(" ns"):
                    nombre = campos.get("drm-driver", "?").strip() + ":" + k[11:]
                    motores[nombre] = int(v[:-3])
        clientes[clave] = motores
    total: dict[str, int] = {}
    for motores in clientes.values():
        for k, v in motores.items():
            total[k] = total.get(k, 0) + v
    return total


def _pmon(pid: int, segundos: int, salida: list[float]) -> None:
    """% de SM de la NVIDIA para `pid`, una muestra por segundo."""
    try:
        r = subprocess.run(["nvidia-smi", "pmon", "-s", "u", "-d", "1", "-c", str(segundos)],
                           capture_output=True, text=True, timeout=segundos + 15)
    except (OSError, subprocess.SubprocessError):
        return
    for linea in r.stdout.splitlines():
        c = linea.split()
        if len(c) > 3 and c[1] == str(pid):
            salida.append(float(c[3]) if c[3] not in ("-", "") else 0.0)


# ── el fondo de medida ──────────────────────────────────────────────────────

def _arrancar(plan: Path, extra: list[str]) -> int:
    cfg = wectl._config_hyprland()
    gpu = "integrada" if cfg.get("gpu") == "integrada" else "dedicada"
    entorno = {"QT_FORCE_STDERR_LOGGING": "1", "WE_MEDIDAS": "1",
               "QML_IMPORT_PATH": str(wectl.MODULOS_QML)}
    for var in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
                "XDG_CURRENT_DESKTOP", "XDG_RUNTIME_DIR"):
        if os.environ.get(var):
            entorno[var] = os.environ[var]
    subprocess.run(["systemctl", "--user", "reset-failed", UNIDAD], capture_output=True)
    r = subprocess.run(
        ["systemd-run", "--user", "--quiet", "--collect", f"--unit={UNIDAD}",
         "-p", f"StandardOutput=truncate:{REGISTRO}", "-p", "StandardError=inherit",
         *[f"--setenv={k}={v}" for k, v in entorno.items()],
         str(wectl.QML), str(wectl.ANFITRION), "--",
         "--plan", str(plan / "plan.txt"), "--gpu", gpu, "--pausa", "0", *extra],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"no arranco el fondo de medida: {r.stderr.strip()}")
    for _ in range(50):
        pid = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value",
                              UNIDAD], capture_output=True, text=True).stdout.strip()
        if pid and pid != "0":
            return int(pid)
        time.sleep(0.1)
    raise SystemExit("el fondo de medida no dio pid")


def _parar() -> None:
    subprocess.run(["systemctl", "--user", "stop", UNIDAD], capture_output=True)
    subprocess.run(["systemctl", "--user", "reset-failed", UNIDAD], capture_output=True)


def _lineas_motor(desde: int) -> list[dict]:
    try:
        with open(REGISTRO, "rb") as f:
            f.seek(desde)
            texto = f.read().decode(errors="replace")
    except OSError:
        return []
    salida = []
    for linea in texto.splitlines():
        m = LINEA.search(linea)
        if m:
            d = dict(kv.split("=", 1) for kv in m.group(1).split())
            salida.append({k: (v if k == "pantalla" else float(v)) for k, v in d.items()})
    return salida


def _por_pantalla(lineas: list[dict]) -> dict[str, dict]:
    salida = {}
    for p in sorted({l["pantalla"] for l in lineas}):
        ls = [l for l in lineas if l["pantalla"] == p]
        seg = sum(l["seg"] for l in ls)
        fotos = sum(l["fotogramas"] for l in ls)
        gpu_n = sum(l["gpu_muestras"] for l in ls)
        copias = sum(l["copias"] for l in ls)
        pond = lambda k, peso: (sum(l[k] * l[peso] for l in ls) / max(1, sum(l[peso] for l in ls)))
        gpu_ms = (sum(l["gpu_ms"] * l["gpu_muestras"] for l in ls if l["gpu_ms"] >= 0)
                  / gpu_n) if gpu_n else None
        fps = fotos / seg if seg else 0.0
        salida[p] = {
            "fps": round(fps, 2),
            "cpu_ms": round(pond("cpu_ms", "fotogramas"), 3),
            "cpu_max_ms": round(max(l["cpu_max"] for l in ls), 3),
            "gpu_ms": round(gpu_ms, 3) if gpu_ms is not None else None,
            "gpu_max_ms": round(max(l["gpu_max"] for l in ls), 3),
            # Fraccion del tiempo que la GPU del plan pasa con ESTE fondo.
            "gpu_ocupada_pct": round(fps * gpu_ms / 10, 1) if gpu_ms is not None else None,
            "leer_ms": round(pond("leer_ms", "copias"), 3) if copias else None,
            "subir_ms": round(pond("subir_ms", "copias"), 3) if copias else None,
            "intervalos": len(ls),
        }
    return salida


def _contexto(plan: Path) -> dict:
    git = subprocess.run(["git", "-C", str(wectl.RAIZ), "describe", "--always", "--dirty"],
                         capture_output=True, text=True).stdout.strip()
    nv = ""
    try:
        nv = Path("/proc/driver/nvidia/version").read_text().split("Module", 1)[1].split()[1]
    except (OSError, IndexError):
        pass
    return {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "git": git,
        "plan": wectl._titulo_del_plan(plan / "plan.txt"),
        "monitores": [f"{n} {w}x{h}" for n, w, h in wectl.monitores_hyprland()],
        "gpu_config": wectl._config_hyprland().get("gpu", "dedicada"),
        "nvidia": nv,
    }


# ── informe ─────────────────────────────────────────────────────────────────

def _imprimir(r: dict) -> None:
    c = r["contexto"]
    print(f"escena   : {c['plan']}")
    print(f"monitores: {', '.join(c['monitores'])}   git {c['git']}   gpu {c['gpu_config']}")
    print(f"medido   : {r['segundos']} s tras {r['calentar']} s de calentamiento")
    for p, v in r["pantallas"].items():
        print(f"  {p:10s} {v['fps']:7.2f} fps   cpu {v['cpu_ms']:.2f} ms "
              f"(max {v['cpu_max_ms']:.1f})   gpu {v['gpu_ms']} ms "
              f"(max {v['gpu_max_ms']:.1f}) = {v['gpu_ocupada_pct']} % ocupada   "
              f"copia leer {v['leer_ms']} subir {v['subir_ms']} ms")
    pr = r["proceso"]
    print(f"  proceso    cpu {pr['cpu_pct']:.1f} % de un nucleo   rss {pr['rss_mb']:.0f} MB")
    for k, v in pr["motores_pct"].items():
        print(f"             {k}: {v:.1f} %")
    if pr.get("nvidia_sm_pct") is not None:
        print(f"             nvidia sm (pmon, grueso): {pr['nvidia_sm_pct']:.1f} %")


def _comparar(antes: dict, ahora: dict) -> None:
    print("\ncomparado con", antes["contexto"]["git"], antes["contexto"]["fecha"])
    if antes["contexto"]["plan"] != ahora["contexto"]["plan"]:
        print("  OJO: no es la misma escena; la comparacion no vale")

    def fila(nombre, a, b):
        if a is None or b is None:
            return
        cambio = f"{(b - a) / a * 100:+.1f} %" if a else ""
        print(f"  {nombre:28s} {a:10.2f} -> {b:10.2f}  {cambio}")
    for p in ahora["pantallas"]:
        if p not in antes["pantallas"]:
            continue
        a, b = antes["pantallas"][p], ahora["pantallas"][p]
        for k in ("fps", "cpu_ms", "gpu_ms", "gpu_ocupada_pct", "leer_ms", "subir_ms"):
            fila(f"{p} {k}", a.get(k), b.get(k))
    fila("proceso cpu_pct", antes["proceso"]["cpu_pct"], ahora["proceso"]["cpu_pct"])
    fila("proceso rss_mb", antes["proceso"]["rss_mb"], ahora["proceso"]["rss_mb"])
    for k, v in ahora["proceso"]["motores_pct"].items():
        fila(f"proceso {k}", antes["proceso"]["motores_pct"].get(k), v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", type=Path, default=wectl.ESCENA,
                    help="directorio con plan.txt (por defecto, el compartido)")
    ap.add_argument("--wallpaper", metavar="ID",
                    help="prepara ese wallpaper aparte (en la cache) y mide con el; "
                         "es lo que hace comparables dos medidas")
    ap.add_argument("--segundos", type=int, default=20)
    ap.add_argument("--calentar", type=int, default=5)
    ap.add_argument("--guardar", type=Path)
    ap.add_argument("--comparar", type=Path)
    ap.add_argument("--sin-pmon", action="store_true")
    ap.add_argument("extra", nargs="*", help="opciones del anfitrion, tras --")
    args = ap.parse_args()

    if not wectl.en_hyprland():
        raise SystemExit("solo en Hyprland: en Plasma no se reinicia plasmashell para medir")
    if args.wallpaper:
        ruta, titulo = wectl.resolver(args.wallpaper)
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        args.plan = cache / "wallpaperengine" / "medida" / ruta.name
        # Siempre de nuevo: el plan depende de la version del codigo, y medir
        # un plan viejo con un motor nuevo no compara nada.
        print(f"preparando {titulo} ({ruta.name}) en {args.plan}", flush=True)
        wectl.preparar(ruta, args.plan)
    if not (args.plan / "plan.txt").is_file():
        raise SystemExit(f"no hay plan en {args.plan}")

    habia_fondo = wectl.fondo_hyprland()
    if habia_fondo:
        wectl.hyprland_parar()
    try:
        pid = _arrancar(args.plan, args.extra)
        time.sleep(args.calentar)
        desde = REGISTRO.stat().st_size if REGISTRO.exists() else 0
        pm: list[float] = []
        hilo = None
        if not args.sin_pmon:
            hilo = threading.Thread(target=_pmon, args=(pid, args.segundos, pm))
            hilo.start()
        t0, c0, m0 = time.monotonic(), _cpu_s(pid), _motores_drm(pid)
        time.sleep(args.segundos)
        t1, c1, m1 = time.monotonic(), _cpu_s(pid), _motores_drm(pid)
        rss = _rss_mb(pid)
        if hilo:
            hilo.join()
        lineas = _lineas_motor(desde)
    finally:
        _parar()
        if habia_fondo:
            wectl.hyprland_arrancar()

    dur = t1 - t0
    resultado = {
        "contexto": _contexto(args.plan),
        "segundos": args.segundos,
        "calentar": args.calentar,
        "extra": args.extra,
        "pantallas": _por_pantalla(lineas),
        "proceso": {
            "cpu_pct": round((c1 - c0) / dur * 100, 1),
            "rss_mb": round(rss, 1),
            "motores_pct": {k: round((m1[k] - m0.get(k, 0)) / (dur * 1e9) * 100, 1)
                            for k in m1 if m1[k] - m0.get(k, 0) > 0},
            "nvidia_sm_pct": round(sum(pm) / len(pm), 1) if pm else None,
        },
    }
    if not resultado["pantallas"]:
        raise SystemExit(f"el motor no dio ninguna linea de medida; mira {REGISTRO}")
    _imprimir(resultado)
    if args.guardar:
        args.guardar.write_text(json.dumps(resultado, indent=2, ensure_ascii=False) + "\n")
        print(f"\nguardado en {args.guardar}")
    if args.comparar:
        _comparar(json.loads(args.comparar.read_text()), resultado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
