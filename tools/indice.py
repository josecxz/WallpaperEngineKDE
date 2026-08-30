#!/usr/bin/env python3
"""Reescribe los numeros de linea de NOTAS-INDICE.md desde NOTAS.md.

El indice se escribe a mano --la glosa de cada seccion es criterio, no algo
que se pueda derivar del texto-- pero los numeros de linea se mueven en cuanto
alguien edita NOTAS.md, y un numero que miente es peor que no tenerlo: manda a
leer el trozo equivocado sin avisar.

Casa por TITULO, que es lo estable. Cuando el mismo titulo se repite --"Lo que
se ve" sale cuatro veces-- elige la cabecera mas cercana al numero que ya
tenia, que sobrevive a cualquier desplazamiento razonable.

Uso:
    python3 tools/indice.py            # comprueba y avisa; no toca nada
    python3 tools/indice.py --escribir # actualiza NOTAS-INDICE.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NOTAS = RAIZ / "NOTAS.md"
INDICE = RAIZ / "NOTAS-INDICE.md"

CABECERA = re.compile(r"^#{2,3} (.+?)\s*$")
ENTRADA = re.compile(r"^(- )`(\d+)`( \*\*)(.+?)(\*\*)")


def main() -> int:
    escribir = "--escribir" in sys.argv

    # titulo -> [lineas donde aparece], en orden
    cabeceras: dict[str, list[int]] = {}
    for n, linea in enumerate(NOTAS.read_text(encoding="utf-8").splitlines(), 1):
        m = CABECERA.match(linea)
        if m:
            cabeceras.setdefault(m.group(1), []).append(n)

    salida, movidas, perdidas, vistas = [], [], [], 0
    for linea in INDICE.read_text(encoding="utf-8").splitlines():
        m = ENTRADA.match(linea)
        if not m:
            salida.append(linea)
            continue
        vistas += 1
        viejo, titulo = int(m.group(2)), m.group(4)
        candidatas = cabeceras.get(titulo)
        if not candidatas:
            perdidas.append((viejo, titulo))
            salida.append(linea)
            continue
        nuevo = min(candidatas, key=lambda c: abs(c - viejo))
        if nuevo != viejo:
            movidas.append((viejo, nuevo, titulo))
        salida.append(ENTRADA.sub(rf"\g<1>`{nuevo}`\g<3>\g<4>\g<5>", linea, count=1))

    total = sum(len(v) for v in cabeceras.values())
    sin_indexar = [
        (n, t) for t, ns in cabeceras.items() for n in ns
        if not any(ENTRADA.match(l) and ENTRADA.match(l).group(4) == t
                   for l in salida)
    ]

    for viejo, nuevo, titulo in movidas:
        print(f"  {viejo} -> {nuevo}  {titulo}")
    for viejo, titulo in perdidas:
        print(f"  !! ya no existe en NOTAS.md (linea {viejo}): {titulo}")
    for n, titulo in sorted(sin_indexar):
        print(f"  !! seccion sin entrada en el indice (linea {n}): {titulo}")

    print(f"{vistas} entradas, {total} cabeceras en NOTAS.md, "
          f"{len(movidas)} movidas, {len(perdidas) + len(sin_indexar)} sin casar")

    if escribir and movidas:
        INDICE.write_text("\n".join(salida) + "\n", encoding="utf-8")
        print(f"escrito: {INDICE.name}")
    elif movidas:
        print("(usa --escribir para actualizarlo)")

    return 1 if perdidas or sin_indexar else 0


if __name__ == "__main__":
    raise SystemExit(main())
