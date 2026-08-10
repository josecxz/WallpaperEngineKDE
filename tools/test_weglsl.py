#!/usr/bin/env python3
"""Valida la inferencia de ancho contra el corpus, SIN tocar el traductor.

El criterio no es una opinion: en un shader que **ya compila**, GLSL ha
verificado los tipos por nosotros. Ahi el ancho inferido del inicializador
tiene que coincidir EXACTAMENTE con el del tipo declarado. Cualquier
discrepancia es un fallo de la inferencia, no del shader.

Es la comprobacion que faltaba la primera vez: una inferencia por barrido de
identificadores se conecto directamente al traductor y rompio 124 variantes que
ya compilaban.

Uso:
    python3 tools/test_wescene.py /tmp/glslcheck     # deja las variantes en /tmp
    python3 tools/test_weglsl.py /tmp/wescene-XXXX /tmp/glslcheck
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from weglsl import (ANCHO_TIPO, BASE_TIPO, ancho, tabla_de_funciones,
                    tabla_global)

MESA_ENV = {"__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json"}

DECL_RE = re.compile(
    r"^[ \t]*(?:(?:const|highp|mediump|lowp)[ \t]+)*"
    r"(float|int|uint|bool|[iub]?vec[234])[ \t]+(\w+)[ \t]*=[ \t]*(.+);[ \t]*$")
FUNC_RE = re.compile(r"^[ \t]*(\w+)[ \t]+(\w+)[ \t]*\(([^)]*)\)[ \t]*\{")
PARAM_RE = re.compile(r"(?:in|out|inout)?[ \t]*(\w+)[ \t]+(\w+)")


def declaraciones(body: str):
    """(tipo declarado, expresion, tabla visible) de cada declaracion local.

    Las tablas se construyen por ambito: globales, mas los parametros de la
    funcion en curso, mas las locales ya declaradas. GLSL exige declarar antes
    de usar, asi que un barrido lineal basta.
    """
    glob = tabla_global(body)
    funcs = tabla_de_funciones(body)
    local: dict[str, int] = {}
    prof = 0
    for linea in body.splitlines():
        if prof == 0:
            m = FUNC_RE.match(linea)
            if m:
                local = {}
                for pm in PARAM_RE.finditer(m.group(3)):
                    if pm.group(1) in ANCHO_TIPO:
                        local[pm.group(2)] = (BASE_TIPO[pm.group(1)],
                                              ANCHO_TIPO[pm.group(1)])
        m = DECL_RE.match(linea)
        if m and prof > 0:
            tipo, nombre, expr = m.groups()
            yield tipo, expr, {**glob, **local}, funcs, linea.strip()
            local[nombre] = (BASE_TIPO[tipo], ANCHO_TIPO[tipo])
        prof += linea.count("{") - linea.count("}")
        prof = max(prof, 0)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    d = Path(sys.argv[1])
    check = sys.argv[2]
    ficheros = sorted(f for f in os.listdir(d) if f.endswith((".frag", ".vert")))

    # Solo valen las que compilan: son las que GLSL ya ha verificado.
    compilan: set[str] = set()
    for i in range(0, len(ficheros), 150):
        p = subprocess.run([check, "--desktop", *ficheros[i:i + 150]],
                           capture_output=True, text=True, cwd=d,
                           env={**os.environ, **MESA_ENV})
        compilan |= {l[3:].strip() for l in p.stdout.splitlines() if l.startswith("OK ")}

    stats = Counter()
    fallos: list[tuple[str, str, int, int]] = []
    for f in ficheros:
        if f not in compilan:
            continue
        stats["variantes"] += 1
        body = (d / f).read_text(errors="replace")
        for tipo, expr, tabla, funcs, linea in declaraciones(body):
            esperado = ANCHO_TIPO[tipo]
            got = ancho(expr, tabla, funcs)
            if got is None:
                stats["sin_determinar"] += 1
            elif got == esperado:
                stats["correcto"] += 1
            else:
                stats["INCORRECTO"] += 1
                if len(fallos) < 12:
                    fallos.append((f, linea, esperado, got))

    print("── inferencia de ancho sobre las variantes que compilan ──")
    tot = stats["correcto"] + stats["sin_determinar"] + stats["INCORRECTO"]
    for k in ("variantes", "correcto", "sin_determinar", "INCORRECTO"):
        pct = f"  ({100.0 * stats[k] / tot:.1f}%)" if tot and k != "variantes" else ""
        print(f"  {k:<16} {stats[k]:6}{pct}")

    if fallos:
        print("\n── discrepancias: la inferencia se equivoca ──")
        for f, linea, esp, got in fallos:
            print(f"  {f.split('_', 1)[-1][:34]:36} declarado {esp}, inferido {got}")
            print(f"      {linea[:88]}")

    # Solo las discrepancias son un fallo. `sin_determinar` es el resultado
    # deseado ante la duda: significa que la transformacion no tocaria nada.
    if stats["INCORRECTO"]:
        print(f"\nFALLO: {stats['INCORRECTO']} inferencias incorrectas")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
