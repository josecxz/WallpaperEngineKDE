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

* **La frecuencia de la integrada** (`gt_act_freq_mhz`) y su reposo (RC6), al
  lado de su %: `fdinfo` da tiempo ocupado, no trabajo, y con el tope de 60
  la integrada pasa de 570 a 870 MHz entre una medida y otra.

**Comparar se hace intercalando**: tres medidas del antes y tres del despues,
alternadas en la misma sesion (A, B, A, B, A, B), no contra un JSON de otro
dia. Comparar contra una sola linea de base fabrico una subida de la
integrada que no existia (NOTAS, "Los 2,5 puntos de la integrada").

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


def _pmon(pids: list[int], segundos: int, salida: dict[int, list[float]]) -> None:
    """% de SM de la NVIDIA para cada pid, una muestra por segundo."""
    try:
        r = subprocess.run(["nvidia-smi", "pmon", "-s", "u", "-d", "1", "-c", str(segundos)],
                           capture_output=True, text=True, timeout=segundos + 15)
    except (OSError, subprocess.SubprocessError):
        return
    for linea in r.stdout.splitlines():
        c = linea.split()
        if len(c) > 3 and c[1].isdigit() and int(c[1]) in pids:
            salida.setdefault(int(c[1]), []).append(
                float(c[3]) if c[3] not in ("-", "") else 0.0)


def _potencia(segundos: int, salida: list[tuple[float, float, float]]) -> None:
    """Vatios y MHz de la NVIDIA ENTERA, dos muestras por segundo.

    Es de toda la tarjeta, no de este proceso ---Hyprland tambien compone en
    ella---, pero es lo que cuenta para la bateria, y no engaña como el % de
    ocupacion: con menos carga la tarjeta baja de frecuencia y cada fotograma
    tarda mas, asi que "% ocupada" puede no bajar aunque se gaste menos.
    """
    try:
        p = subprocess.Popen(["nvidia-smi", "--query-gpu=power.draw,clocks.gr,memory.used",
                              "--format=csv,noheader,nounits", "-lms", "500"],
                             stdout=subprocess.PIPE, text=True)
    except OSError:
        return
    fin = time.monotonic() + segundos
    try:
        for linea in p.stdout:
            try:
                w, mhz, mib = (float(x) for x in linea.split(","))
                salida.append((w, mhz, mib))
            except ValueError:
                pass
            if time.monotonic() >= fin:
                break
    finally:
        p.kill()
        p.wait()


def _intel_gt() -> Path | None:
    """sysfs de la GPU Intel (vendor 0x8086), si la hay."""
    for c in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        try:
            if (c / "device" / "vendor").read_text().strip() == "0x8086" \
                    and (c / "gt_act_freq_mhz").exists():
                return c
        except OSError:
            pass
    return None


def _intel(segundos: int, salida: list[float]) -> None:
    """MHz reales de la integrada, dos muestras por segundo.

    `fdinfo` da tiempo OCUPADO, no trabajo: si la integrada baja de
    frecuencia, el mismo trabajo ocupa mas tiempo y el % sube sin que se haga
    nada mas. Sin la frecuencia al lado, el % de la integrada no se entiende.
    """
    gt = _intel_gt()
    if not gt:
        return
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        try:
            salida.append(float((gt / "gt_act_freq_mhz").read_text()))
        except (OSError, ValueError):
            pass
        time.sleep(0.5)


def _rc6_ms() -> float | None:
    gt = _intel_gt()
    try:
        return float((gt / "gt" / "gt0" / "rc6_residency_ms").read_text()) if gt else None
    except (OSError, ValueError):
        return None


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
            "particulas_ms": round(pond("particulas_ms", "fotogramas"), 3)
                             if all("particulas_ms" in l for l in ls) else None,
            "particulas_subir_ms": round(pond("particulas_subir_ms", "fotogramas"), 3)
                                   if all("particulas_subir_ms" in l for l in ls) else None,
            **{k: round(pond(k, "fotogramas"), 3) for k in ("render_ms", "previo_ms", "objetos_ms")
               if all(k in l for l in ls)},
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
              f"copia leer {v['leer_ms']} subir {v['subir_ms']} ms   "
              f"particulas {v.get('particulas_ms')} ms (subir {v.get('particulas_subir_ms')})"
              + (f"\n             render {v['render_ms']} ms = previo {v['previo_ms']}"
                 f" + objetos {v['objetos_ms']} + pases y particulas"
                 if "render_ms" in v else ""))
    pr = r["proceso"]
    print(f"  proceso    cpu {pr['cpu_pct']:.1f} % de un nucleo   rss {pr['rss_mb']:.0f} MB")
    co = r.get("compositor") or {}
    if co.get("cpu_pct") is not None:
        print(f"  Hyprland   cpu {co['cpu_pct']:.1f} %   "
              + "   ".join(f"{k} {v:.1f} %" for k, v in co["motores_pct"].items())
              + (f"   nvidia sm {co['nvidia_sm_pct']} %" if co.get("nvidia_sm_pct") is not None else ""))
    for k, v in pr["motores_pct"].items():
        print(f"             {k}: {v:.1f} %")
    if pr.get("nvidia_sm_pct") is not None:
        print(f"             nvidia sm (pmon, grueso): {pr['nvidia_sm_pct']:.1f} %")
    if pr.get("intel_mhz") is not None:
        print(f"             intel: {pr['intel_mhz']} MHz de media, "
              f"{pr['intel_rc6_pct']} % del tiempo en reposo (todo el sistema)")
    if pr.get("nvidia_w") is not None:
        print(f"             nvidia tarjeta entera: {pr['nvidia_w']:.2f} W a {pr['nvidia_mhz']} MHz, "
              f"{pr.get('nvidia_mib')} MiB usados")


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
        for k in ("fps", "cpu_ms", "gpu_ms", "gpu_ocupada_pct", "leer_ms", "subir_ms",
                  "particulas_ms", "render_ms", "objetos_ms"):
            fila(f"{p} {k}", a.get(k), b.get(k))
    fila("proceso cpu_pct", antes["proceso"]["cpu_pct"], ahora["proceso"]["cpu_pct"])
    fila("proceso rss_mb", antes["proceso"]["rss_mb"], ahora["proceso"]["rss_mb"])
    fila("intel MHz", antes["proceso"].get("intel_mhz"), ahora["proceso"].get("intel_mhz"))
    fila("intel reposo %", antes["proceso"].get("intel_rc6_pct"),
         ahora["proceso"].get("intel_rc6_pct"))
    fila("nvidia MiB (tarjeta)", antes["proceso"].get("nvidia_mib"),
         ahora["proceso"].get("nvidia_mib"))
    ac, bc = antes.get("compositor") or {}, ahora.get("compositor") or {}
    fila("Hyprland cpu_pct", ac.get("cpu_pct"), bc.get("cpu_pct"))
    for k, v in (bc.get("motores_pct") or {}).items():
        fila(f"Hyprland {k}", (ac.get("motores_pct") or {}).get(k), v)
    fila("nvidia W (tarjeta)", antes["proceso"].get("nvidia_w"), ahora["proceso"].get("nvidia_w"))
    for k, v in ahora["proceso"]["motores_pct"].items():
        fila(f"proceso {k}", antes["proceso"]["motores_pct"].get(k), v)


def _compositor() -> int | None:
    r = subprocess.run(["pgrep", "-x", "Hyprland"], capture_output=True, text=True)
    pids = [int(x) for x in r.stdout.split()]
    return pids[0] if pids else None


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
    ap.add_argument("--sin-fondo", action="store_true",
                    help="mide el sistema SIN fondo (compositor y NVIDIA), como "
                         "referencia de lo que cuesta no tener nada")
    ap.add_argument("extra", nargs="*", help="opciones del anfitrion, tras --")
    args = ap.parse_args()

    if not wectl.en_hyprland():
        raise SystemExit("solo en Hyprland: en Plasma no se reinicia plasmashell para medir")
    if args.wallpaper and not args.sin_fondo:
        ruta, titulo = wectl.resolver(args.wallpaper)
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        args.plan = cache / "wallpaperengine" / "medida" / ruta.name
        # Siempre de nuevo: el plan depende de la version del codigo, y medir
        # un plan viejo con un motor nuevo no compara nada.
        print(f"preparando {titulo} ({ruta.name}) en {args.plan}", flush=True)
        wectl.preparar(ruta, args.plan)
    if not args.sin_fondo and not (args.plan / "plan.txt").is_file():
        raise SystemExit(f"no hay plan en {args.plan}")

    # La rotacion (`wectl shuffle` cada x minutos) arranca el fondo normal si
    # lo encuentra parado, y en medio de una medida eso son DOS fondos
    # dibujando a la vez: pasaba, y una medida salio con 97 % de CPU en vez de
    # 83. Se para el temporizador mientras se mide y se deja como estaba.
    temporizador = f"{wectl.UNIDAD}.timer"
    habia_rotacion = subprocess.run(["systemctl", "--user", "is-active", "--quiet",
                                     temporizador]).returncode == 0
    if habia_rotacion:
        subprocess.run(["systemctl", "--user", "stop", temporizador], capture_output=True)
    habia_fondo = wectl.fondo_hyprland()
    if habia_fondo:
        wectl.hyprland_parar()
    comp = _compositor()
    try:
        pid = None if args.sin_fondo else _arrancar(args.plan, args.extra)
        time.sleep(args.calentar)
        desde = REGISTRO.stat().st_size if REGISTRO.exists() else 0
        pm: dict[int, list[float]] = {}
        pot: list[tuple[float, float, float]] = []
        intel: list[float] = []
        hilos = [threading.Thread(target=_intel, args=(args.segundos, intel))]
        if not args.sin_pmon:
            hilos += [threading.Thread(target=_pmon, args=([p for p in (pid, comp) if p],
                                                           args.segundos, pm)),
                      threading.Thread(target=_potencia, args=(args.segundos, pot))]
        for h in hilos:
            h.start()
        cpu = lambda p: _cpu_s(p) if p else 0.0
        drm = lambda p: _motores_drm(p) if p else {}
        t0, c0, m0, r0 = time.monotonic(), cpu(pid), drm(pid), _rc6_ms()
        k0, km0 = cpu(comp), drm(comp)
        time.sleep(args.segundos)
        t1, c1, m1, r1 = time.monotonic(), cpu(pid), drm(pid), _rc6_ms()
        k1, km1 = cpu(comp), drm(comp)
        rss = _rss_mb(pid) if pid else 0.0
        for h in hilos:
            h.join()
        lineas = _lineas_motor(desde)
    finally:
        _parar()
        if habia_fondo:
            wectl.hyprland_arrancar()
        if habia_rotacion:
            subprocess.run(["systemctl", "--user", "start", temporizador],
                           capture_output=True)

    dur = t1 - t0
    pct = lambda a, b: {k: round((b[k] - a.get(k, 0)) / (dur * 1e9) * 100, 1)
                        for k in b if b[k] - a.get(k, 0) > 0}
    media = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    resultado = {
        "contexto": _contexto(args.plan),
        "segundos": args.segundos,
        "calentar": args.calentar,
        "extra": args.extra,
        "pantallas": _por_pantalla(lineas),
        "proceso": {
            "cpu_pct": round((c1 - c0) / dur * 100, 1),
            "rss_mb": round(rss, 1),
            "motores_pct": pct(m0, m1),
            "nvidia_sm_pct": media(pm.get(pid, [])) if pid else None,
            "intel_mhz": round(sum(intel) / len(intel)) if intel else None,
            # Tiempo de la integrada en reposo (RC6), de TODO el sistema.
            "intel_rc6_pct": round((r1 - r0) / (dur * 1000) * 100, 1)
                             if r0 is not None and r1 is not None else None,
            "nvidia_w": round(sum(p[0] for p in pot) / len(pot), 2) if pot else None,
            "nvidia_mhz": round(sum(p[1] for p in pot) / len(pot)) if pot else None,
            "nvidia_mib": round(sum(p[2] for p in pot) / len(pot)) if pot else None,
        },
        # Lo que el fondo le cuesta al compositor: cada fotograma nuevo del
        # fondo le obliga a recomponer esa pantalla.
        "compositor": {
            "cpu_pct": round((k1 - k0) / dur * 100, 1) if comp else None,
            "motores_pct": pct(km0, km1) if comp else {},
            "nvidia_sm_pct": media(pm.get(comp, [])) if comp else None,
        },
    }
    if args.sin_fondo:
        resultado["contexto"]["plan"] = "(sin fondo)"
    elif not resultado["pantallas"]:
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
