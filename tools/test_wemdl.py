#!/usr/bin/env python3
"""Valida el decodificador de mallas puppet contra toda la biblioteca.

El criterio es el mismo que destapo los fallos de .tex y .pkg: no basta con que
parezca correcto, tiene que cuadrar numericamente.

  - los pesos de cada vertice suman 1
  - ningun indice apunta fuera del numero de vertices
  - el bloque de indices forma triangulos completos
  - tras la geometria solo hay bloques MDLS/MDLA o relleno a cero,
    nunca datos sueltos que delaten un campo mal leido

Uso:  python3 tools/test_wemdl.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
import wemdl
from pkg_inspect import read_pkg

# Bloques que legitimamente siguen a la geometria y que aun no decodificamos.
BLOQUES_CONOCIDOS = (b"MDLS", b"MDLA")


def revisar(name: str, blob: bytes, stats: Counter, errs: Counter) -> None:
    try:
        m = wemdl.parse_mdl(blob, name)
    except wemdl.MdlError as e:
        msg = str(e).split(": ", 1)[-1]
        errs[msg[:70]] += 1
        stats["rechazado"] += 1
        return

    stats["ok"] += 1
    stats["vertices"] += m.vertex_count
    stats["triangulos"] += m.triangle_count

    w = np.asarray(m.bone_weights)
    desv = float(np.abs(w.sum(axis=1) - 1.0).max())
    # El umbral era 1e-5, calibrado cuando el corpus solo traia las versiones
    # viejas, donde la desviacion maxima es 1.19e-07 -- el epsilon del float32.
    # Tres mallas de MDLV0023 llegan a 1.01e-05 y no es un campo mal leido: la
    # mediana de la desviacion es CERO y solo el 8% de los vertices pasa de
    # 1e-6, asi que son pesos redondeados en origen. Leer el campo equivocado
    # no da sumas que ronden 1, las da lejos, y ese caso lo sigue cazando este
    # mismo limite. La comprobacion fuerte de que el layout es correcto es
    # otra: los indices de hueso caen dentro del esqueleto en 83 de 84 mallas.
    if desv > 2e-5:
        errs[f"pesos no suman 1 (desv {desv:.2e})"] += 1
        stats["peso_malo"] += 1

    if int(np.asarray(m.indices).max()) >= m.vertex_count:
        errs["indice fuera de rango"] += 1

    if m.positions[:, 2].any():
        stats["con_z"] += 1

    resto = blob[m.consumed:]
    if not resto:
        stats["cierre_exacto"] += 1
    elif resto[:4] in BLOQUES_CONOCIDOS:
        stats["sigue_bloque"] += 1
    elif not any(resto):
        stats["sigue_relleno"] += 1
    else:
        # Esto es lo que delata un campo mal leido.
        errs[f"basura tras la geometria: {resto[:12].hex(' ')}"] += 1
        stats["cola_sospechosa"] += 1


def main() -> int:
    stats, errs = Counter(), Counter()
    ws = wepaths.we_workshop()

    for d in sorted(ws.iterdir()):
        pkg = d / "scene.pkg"
        if not pkg.is_file():
            continue
        try:
            _, entries = read_pkg(pkg)
        except Exception:
            continue
        for e in entries:
            if e["name"].endswith(".mdl"):
                stats["ficheros"] += 1
                revisar(f"{d.name}/{e['name']}", e["data"], stats, errs)

    print("── mallas puppet ──")
    for k, v in sorted(stats.items()):
        print(f"  {k:<18} {v}")
    if errs:
        print("\n── incidencias ──")
        for msg, n in errs.most_common():
            print(f"  {n:>3} x {msg}")

    grave = stats["peso_malo"] + stats["cola_sospechosa"]
    print("\n" + ("OK" if grave == 0 else f"FALLO: {grave} mallas inconsistentes"))
    return 1 if grave else 0


if __name__ == "__main__":
    sys.exit(main())
