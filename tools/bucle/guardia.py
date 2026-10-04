#!/usr/bin/env python3
"""Hook `PreToolUse` de las sesiones del bucle autónomo.

Solo lo cargan las sesiones que lanza `orquestador.py` (vía `--settings
tools/bucle/ajustes.json`); una sesión interactiva no lo ve. Sin un humano
delante, esto es lo único que hace cumplir las reglas que en CLAUDE.md se
cumplen por disciplina:

  * regla 3: nada de plasmashell en vivo  -> ni `make reload`/`install`,
    ni `systemctl`, ni `kquitapp`/`plasmashell`
  * regla 7: nada de `cp` sobre un `.so`
  * regla 8: `tools/wectl.py` no se toca
  * el propio bucle no se toca: `.claude/` y `tools/bucle/` son quien le
    revisa, y un implementador que pudiera editarlos se aprobaría solo
  * git es del orquestador: el implementador edita, no confirma ni mezcla
  * fuera de su worktree no escribe (salvo temporales)

Protocolo de Claude Code: JSON por stdin; salir con 2 bloquea la llamada y lo
que va a stderr se le devuelve al modelo como motivo.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BASH_PROHIBIDO = [
    (r"\bmake\b[^|;&]*\b(reload|install)\b",
     "make reload/install toca el escritorio en vivo (regla 3); "
     "se itera con werender.py/glexec"),
    (r"\bsystemctl\b", "systemctl no se usa desde el bucle (regla 3)"),
    (r"\b(plasmashell|kquitapp6?|kstart6?|qdbus6?|dbus-send)\b",
     "plasmashell y su bus no se tocan desde el bucle (regla 3)"),
    (r"\bcp\b[^|;&]*\.so\b",
     "cp sobre un .so mata a plasmashell con SIGBUS (regla 7)"),
    (r"\bgit\s+(commit|push|merge|rebase|reset|checkout|switch|branch|"
     r"worktree|stash|tag|cherry-pick|revert|clean|update-ref|am)\b",
     "git lo maneja el orquestador: edita los ficheros y termina"),
    (r"(^|[\s/])wectl(\.py)?\s+(set|shuffle|start|stop)\b",
     "wectl set/shuffle/start/stop cambian el escritorio (regla 3)"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+(/|~|\$HOME)(\s|$)",
     "borrado recursivo de la raíz o del home"),
]

RUTAS_PROHIBIDAS = [
    ("tools/wectl.py", "wectl no crece por iniciativa propia (regla 8)"),
    (".claude/", "la configuración de agentes es del bucle, no de la tarea"),
    ("tools/bucle/", "el bucle no se revisa a sí mismo"),
]


def bloquear(motivo: str) -> None:
    print(f"BLOQUEADO por la guardia del bucle: {motivo}", file=sys.stderr)
    sys.exit(2)


def ruta_permitida(p: Path, raiz: Path) -> bool:
    tmp = ("/tmp/", str(Path.home() / ".cache") + "/")
    s = str(p)
    return s.startswith(str(raiz) + "/") or s.startswith(tmp)


def main() -> None:
    try:
        ev = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    herramienta = ev.get("tool_name", "")
    entrada = ev.get("tool_input") or {}
    raiz = Path(os.environ.get("WE_BUCLE_RAIZ") or ev.get("cwd") or ".").resolve()

    if herramienta == "Bash":
        orden = entrada.get("command", "")
        for patron, motivo in BASH_PROHIBIDO:
            if re.search(patron, orden):
                bloquear(motivo)
        # La edición «por la puerta de atrás»: sed -i / redirección a un fichero
        # vigilado.
        for rel, motivo in RUTAS_PROHIBIDAS:
            if rel in orden and re.search(r"(>|\bsed\s+-i|\btee\b|\bmv\b|\bcp\b|\brm\b)", orden):
                bloquear(motivo)
        return

    if herramienta in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        ruta = entrada.get("file_path") or entrada.get("notebook_path") or ""
        if not ruta:
            return
        p = Path(ruta).resolve()
        if not ruta_permitida(p, raiz):
            bloquear(f"{p} está fuera del worktree de la tarea ({raiz})")
        try:
            rel = str(p.relative_to(raiz))
        except ValueError:
            return
        for prohibida, motivo in RUTAS_PROHIBIDAS:
            if rel == prohibida or rel.startswith(prohibida):
                bloquear(motivo)


if __name__ == "__main__":
    main()
