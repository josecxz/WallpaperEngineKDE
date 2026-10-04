#!/usr/bin/env python3
"""Panel del bucle autónomo: qué se está ejecutando y en qué etapa.

Un servidor local (solo 127.0.0.1) que sirve `panel.html` y una API que la
página consulta cada dos segundos. No le pide nada al orquestador: lee lo que
este ya deja escrito, así que vale para una ejecución que ya estaba en marcha.

  ~/.local/state/wallpaperengine-bucle/ejecuciones/<id>/bucle.log   las etapas
  …/<id>/{triador,implementador-N,revisor-N}.json                    su resultado
  …/<id>/compuertas-N.txt                                            por qué falló
  ~/.local/state/wallpaperengine-bucle/estado.json                   el historial
  ~/.claude/projects/<cwd de la sesión>/*.jsonl                      la sesión EN VIVO

Las etapas salen de las líneas de `bucle.log`: si se cambia el texto de un
`reg(...)` en orquestador.py que empiece por «→», «←», «intento», «tarea:»,
«compuertas:», «revisor:», «luz del corpus», «MEZCLADA», «ERROR» o «fin;»,
hay que mirar `etapas()` aquí.

Uso:
    python3 tools/bucle/panel.py            # http://127.0.0.1:8765
    python3 tools/bucle/panel.py --puerto 9000
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

AQUI = Path(__file__).resolve().parent
ESTADO_DIR = Path.home() / ".local/state/wallpaperengine-bucle"
EJECUCIONES = ESTADO_DIR / "ejecuciones"
CERROJO = Path.home() / ".cache/wallpaperengine/bucle/orquestador.lock"
WT = Path.home() / ".cache/wallpaperengine/bucle/wt"
PROYECTOS = Path.home() / ".claude/projects"

LINEA = re.compile(r"^\[(\d\d:\d\d:\d\d)\] ?(.*)$")
ETAPAS = ["triaje", "implementacion", "compuertas", "revision", "mezcla"]


def en_marcha() -> bool:
    """¿Hay un orquestador vivo? Su cerrojo exclusivo lo dice sin pgrep."""
    if not CERROJO.exists():
        return False
    with open(CERROJO) as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def entradas(log: Path) -> list[tuple[str, str]]:
    """(hora, texto) por entrada; las líneas sin hora continúan la anterior."""
    out: list[tuple[str, str]] = []
    for linea in log.read_text(errors="replace").splitlines():
        m = LINEA.match(linea)
        if m:
            out.append((m.group(1), m.group(2).strip()))
        elif out:
            out[-1] = (out[-1][0], out[-1][1] + "\n" + linea)
    return out


def lee_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def stats(texto: str) -> dict:
    m = re.search(r"en (\d+)s, (\S+) turnos, (\d+) bloqueos, \$([\d.]+)", texto)
    if not m:
        return {}
    return {"segundos": int(m.group(1)), "turnos": m.group(2),
            "bloqueos": int(m.group(3)), "coste": float(m.group(4))}


def etapas(dir_: Path, fecha: str) -> dict:
    """Reconstruye la ejecución a partir de su bucle.log."""
    def ts_local(hora: str) -> float:
        t = datetime.strptime(f"{fecha} {hora}", "%Y%m%d %H:%M:%S").timestamp()
        # Pasada la medianoche la hora vuelve a empezar.
        while ts_local.ultimo and t < ts_local.ultimo - 3600:
            t += 86400
        ts_local.ultimo = t
        return t

    # El log solo guarda la hora de pared, en la zona horaria que tuviera el
    # orquestador al arrancar; si la del sistema cambia luego, las horas
    # leídas aquí salen corridas (pasó: 7 h). Se ancla al reloj real: la
    # última entrada se escribió cuando se modificó el fichero por última vez.
    # Las zonas van de 15 en 15 minutos, así que el desfase se redondea a eso.
    lista = entradas(dir_ / "bucle.log")
    ts_local.ultimo = 0.0
    horas = [ts_local(h) for h, _ in lista]
    desfase = 0.0
    if horas:
        bruto = (dir_ / "bucle.log").stat().st_mtime - horas[-1]
        desfase = round(bruto / 900) * 900
    ts_local.ultimo = 0.0

    def ts(hora: str) -> float:
        return ts_local(hora) + desfase

    ej = {"id": dir_.name, "tarea": None, "rama": None, "base": None,
          "inicio": None, "fin": None, "resultado": None, "coste": 0.0,
          "triaje": None, "intentos": [], "mezcla": None, "error": None,
          "activo": None, "clon": None, "registro": []}
    actual = None          # el intento en curso
    paso = None            # el sub-paso de compuertas en curso

    def cierra_paso(t):
        nonlocal paso
        if paso and paso["fin"] is None:
            paso["fin"] = t
        paso = None

    for hora, txt in lista:
        t = ts(hora)
        ej["registro"].append({"t": t, "texto": txt})
        if txt.startswith("bucle sobre"):
            ej["inicio"] = t
            m = re.match(r"bucle sobre (\S+) \((\w+)\)", txt)
            if m:
                ej["base"] = f"{m.group(1)} ({m.group(2)})"
        elif txt.startswith("→ "):
            m = re.match(r"→ (\S+) \(cwd (\S+)\)", txt)
            nombre = m.group(1) if m else txt[2:]
            if m:
                ej["clon"] = m.group(2)
            ses = {"nombre": nombre, "inicio": t, "fin": None, "stats": {}}
            ej["activo"] = nombre
            if nombre.startswith("triador"):
                ej["triaje"] = ses
            elif actual is not None:
                clave = "revision" if nombre.startswith("revisor") else "implementacion"
                if actual.get(clave) and nombre.endswith("-json"):
                    continue
                actual[clave] = ses
        elif txt.startswith("← "):
            m = re.match(r"← (\S+): (\S+)", txt)
            nombre = m.group(1) if m else ""
            base = nombre.removesuffix("-json")
            st = stats(txt)
            ej["coste"] += st.get("coste", 0)
            ej["activo"] = None
            for ses in ([ej["triaje"]] + [i.get(k) for i in ej["intentos"]
                                          for k in ("implementacion", "revision")]):
                if ses and ses["nombre"] == base:
                    ses["fin"] = t
                    ses["stats"] = st
        elif txt.startswith("tarea:"):
            m = re.match(r"tarea: (.*)\s+\[(\S+)\]$", txt, re.S)
            ej["tarea"], ej["rama"] = (m.group(1), m.group(2)) if m else (txt[6:], None)
        elif txt.startswith("intento "):
            m = re.match(r"intento (\d+)/(\d+)", txt)
            actual = {"n": int(m.group(1)), "de": int(m.group(2)),
                      "implementacion": None, "compuertas": None,
                      "revision": None, "veredicto": None, "motivos": []}
            ej["intentos"].append(actual)
        elif txt.startswith("compuertas:") and actual is not None:
            if "ficheros cambiados" in txt:
                actual["compuertas"] = {"inicio": t, "fin": None, "estado": None,
                                        "detalle": txt.split(":", 1)[1].strip(),
                                        "pasos": []}
            else:
                cierra_paso(t)
                if actual["compuertas"]:
                    actual["compuertas"]["fin"] = t
                    actual["compuertas"]["estado"] = "OK" if "OK" in txt else "FALLO"
        elif (actual is not None and actual.get("compuertas")
              and actual["compuertas"]["fin"] is None
              and (re.match(r"test_\w+ …", txt) or txt.startswith(("medida declarada",
                                                                    "luz del corpus",
                                                                    "no hay referencia")))):
            cierra_paso(t)
            if txt.startswith("luz del corpus en _base"):
                nombre = "luz de la base (129 escenas)"
            elif txt.startswith("luz del corpus"):
                nombre = "luz del candidato (129 escenas)"
            elif txt.startswith("medida declarada"):
                nombre = "medida: " + txt.split(":", 1)[1].strip()
            elif txt.startswith("no hay referencia"):
                continue
            else:
                nombre = txt.rstrip(" …")
            paso = {"nombre": nombre, "inicio": t, "fin": None}
            actual["compuertas"]["pasos"].append(paso)
        elif txt.startswith("revisor:") and actual is not None:
            actual["veredicto"] = txt.split(":", 1)[1].strip()
        elif txt.startswith("MEZCLADA"):
            ej["mezcla"] = {"t": t, "estado": "OK", "texto": txt}
            ej["resultado"] = "hecha"
        elif txt.startswith("aprobada"):
            ej["mezcla"] = {"t": t, "estado": "PENDIENTE", "texto": txt}
            ej["resultado"] = "aprobada sin mezclar"
        elif txt.startswith("bloqueada"):
            ej["resultado"] = "bloqueada"
        elif txt.startswith("el implementador no lo resuelve"):
            ej["resultado"] = "no resuelta"
        elif txt.startswith("el triador no encuentra"):
            ej["resultado"] = "sin tarea"
        elif txt.startswith("ERROR"):
            ej["error"] = txt
            ej["resultado"] = "error"
        elif txt.startswith("fin;"):
            ej["fin"] = t
            cierra_paso(t)
            m = re.search(r"\$([\d.]+)", txt)
            if m:
                ej["coste"] = float(m.group(1))

    # Lo que no está en el log: los motivos de cada rechazo.
    for i in ej["intentos"]:
        rev = lee_json(dir_ / f"revisor-{i['n']}.json")
        if rev and isinstance(rev.get("structured_output"), dict):
            i["motivos"] = rev["structured_output"].get("motivos", [])
        comp = dir_ / f"compuertas-{i['n']}.txt"
        if comp.exists() and (i.get("compuertas") or {}).get("estado") == "FALLO":
            fallo = [l for l in comp.read_text().split("\n\n") if l.startswith("FALLO")]
            i["motivos"] = fallo or i["motivos"]
    tri = lee_json(dir_ / "triador.json")
    if tri and isinstance(tri.get("structured_output"), dict):
        ej["ficha"] = tri["structured_output"]
    ej["etapa"] = etapa_actual(ej)
    return ej


def etapa_actual(ej: dict) -> str | None:
    if ej["fin"]:
        return None
    if ej["mezcla"]:
        return "mezcla"
    if not ej["intentos"]:
        return "triaje"
    i = ej["intentos"][-1]
    if i["revision"]:
        return "revision" if i["veredicto"] is None else "mezcla"
    if i["compuertas"]:
        return "compuertas"
    return "implementacion"


def sesion_en_vivo(clon: str | None, n: int = 40) -> dict | None:
    """Las últimas acciones de la sesión de Claude más reciente de ese clon."""
    if not clon:
        return None
    carpeta = PROYECTOS / re.sub(r"[^A-Za-z0-9]", "-", str(WT / clon))
    try:
        f = max(carpeta.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    except (ValueError, OSError):
        return None
    tam = f.stat().st_size
    with open(f, "rb") as fh:
        fh.seek(max(0, tam - 600_000))
        crudo = fh.read().decode(errors="replace").splitlines()
    acciones = []
    for linea in crudo[1:] if tam > 600_000 else crudo:
        try:
            e = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "assistant":
            continue
        for c in e.get("message", {}).get("content", []) or []:
            if c.get("type") == "text" and c.get("text", "").strip():
                acciones.append({"tipo": "texto", "t": e.get("timestamp"),
                                 "texto": c["text"].strip()[:600]})
            elif c.get("type") == "tool_use":
                i = c.get("input") or {}
                det = (i.get("description") or i.get("command") or i.get("file_path")
                       or i.get("pattern") or "")
                acciones.append({"tipo": "herramienta", "t": e.get("timestamp"),
                                 "nombre": c.get("name"), "texto": str(det)[:300]})
    return {"fichero": str(f), "modificado": f.stat().st_mtime,
            "acciones": acciones[-n:]}


def api_estado(run: str | None) -> dict:
    dirs = sorted((d for d in EJECUCIONES.glob("*") if (d / "bucle.log").exists()),
                  reverse=True) if EJECUCIONES.exists() else []
    vivo = en_marcha()
    elegido = next((d for d in dirs if d.name == run), dirs[0] if dirs else None)
    ej = etapas(elegido, elegido.name[:8]) if elegido else None
    if ej and not vivo and not ej["fin"]:
        ej["resultado"] = ej["resultado"] or "interrumpida"
        ej["etapa"] = None
    vivo_aqui = bool(ej and vivo and elegido == (dirs[0] if dirs else None) and not ej["fin"])
    historial = (lee_json(ESTADO_DIR / "estado.json") or {}).get("tareas", [])
    return {
        "ahora": time.time(),
        "orquestador_en_marcha": vivo,
        "en_vivo": vivo_aqui,
        "ejecucion": ej,
        "sesion": sesion_en_vivo(ej["clon"]) if ej and vivo_aqui else None,
        "ejecuciones": [{"id": d.name} for d in dirs[:30]],
        "historial": historial[-30:][::-1],
        "etapas": ETAPAS,
    }


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _envia(self, cuerpo: bytes, tipo: str, codigo: int = 200):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._envia((AQUI / "panel.html").read_bytes(), "text/html; charset=utf-8")
        elif u.path == "/api/estado":
            run = parse_qs(u.query).get("run", [None])[0]
            try:
                datos = api_estado(run)
            except Exception as e:                           # noqa: BLE001
                datos = {"fallo": f"{type(e).__name__}: {e}"}
            self._envia(json.dumps(datos, ensure_ascii=False).encode(),
                        "application/json; charset=utf-8")
        else:
            self._envia(b"no existe", "text/plain", 404)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--puerto", type=int, default=8765)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.puerto), Manejador)
    print(f"panel del bucle en http://127.0.0.1:{a.puerto}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
