#!/usr/bin/env python3
"""Comprueba el contrato entre `weparticles.py` y `src/weparticles.c`.

El fichero `.psys` es una lista de numeros SIN NOMBRES: quien escribe y quien
lee tienen que estar de acuerdo en cuantos floats lleva cada pieza y en que
orden. Si dejan de estarlo, el lado C no falla --- se limita a leer menos
numeros de los que hay, o a rellenar con ceros --- y el sistema simula algo
parecido pero equivocado. Es justo el tipo de error que no se ve hasta que
alguien mira una escena concreta y le extrana el resultado.

Asi que aqui no se opina: se leen las tablas del propio .c y se comparan con lo
que el .py emite, para cada sistema del corpus. Es la misma leccion que la
inferencia de anchos --- validar contra un oraculo antes de conectar --- con el
oraculo siendo esta vez la otra mitad de la implementacion.

Se comprueban tres cosas:

  1. Los dos lados conocen exactamente los mismos nombres.
  2. Cada pieza emitida trae los floats que el lector espera.
  3. Los `.psys` del corpus entero se escriben sin excepciones, y las piezas
     que quedan fuera son solo las declaradas como no soportadas.

Uso:
    python3 tools/test_weparticles.py [--limit N]
"""

from __future__ import annotations

import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import weparticles
import wepaths
from wescene import AssetResolver

FUENTE_C = Path(__file__).resolve().parent.parent / "src" / "weparticles.c"

# {"nombre", CODIGO, N},  dentro de las tablas INICIALIZADORES y OPERADORES.
ENTRADA_RE = re.compile(r'\{"(\w+)",\s*(\w+),\s*(\d+)\}')


def tablas_del_c() -> tuple[dict[str, int], dict[str, int]]:
    """`(inicializadores, operadores)` -> nombre: numero de floats."""
    texto = FUENTE_C.read_text()
    def bloque(nombre: str) -> dict[str, int]:
        i = texto.index(f"{nombre}[] = {{")
        j = texto.index("};", i)
        return {m.group(1): int(m.group(3))
                for m in ENTRADA_RE.finditer(texto[i:j])}
    return bloque("INICIALIZADORES"), bloque("OPERADORES")


def main() -> int:
    limite = None
    if "--limit" in sys.argv:
        limite = int(sys.argv[sys.argv.index("--limit") + 1])

    init_c, oper_c = tablas_del_c()
    fallos: list[str] = []

    # ── 1. mismo vocabulario en los dos lados ──
    for etq, py, c in (("inicializador", set(weparticles.INICIALIZADORES), set(init_c)),
                       ("operador", set(weparticles.OPERADORES), set(oper_c))):
        for n in sorted(py - c):
            fallos.append(f"{etq} {n!r}: lo emite Python y el C no lo lee")
        for n in sorted(c - py):
            fallos.append(f"{etq} {n!r}: lo lee el C y Python no lo emite")

    print("── vocabulario ──")
    print(f"  inicializadores  {len(init_c):3} en C, {len(weparticles.INICIALIZADORES):3} en Python")
    print(f"  operadores       {len(oper_c):3} en C, {len(weparticles.OPERADORES):3} en Python")

    # ── 2 y 3. el corpus entero ──
    we = wepaths.we_assets()
    dirs = sorted(d for d in wepaths.we_workshop().iterdir()
                  if (d / "scene.pkg").is_file())
    if limite:
        dirs = dirs[:limite]

    tmp = Path(tempfile.mkdtemp(prefix="wepsys-"))
    st = Counter()
    fuera = Counter()
    for d in dirs:
        try:
            res = AssetResolver.for_wallpaper(d, we)
            escena = res.read_json("scene.json")
        except Exception:
            st["escena_err"] += 1
            continue
        for o in escena.get("objects", []):
            if not o.get("particle"):
                continue
            st["sistemas"] += 1
            try:
                s = weparticles.cargar(res, o["particle"],
                                       o.get("instanceoverride"))
            except Exception as e:
                st["error"] += 1
                fallos.append(f"{d.name} {o.get('name')!r}: {type(e).__name__}: {e}")
                continue

            for nombre, vals in s.inits:
                st["piezas"] += 1
                if len(vals) != init_c.get(nombre, -1):
                    fallos.append(f"{d.name}: init {nombre} emite {len(vals)} "
                                  f"floats, el C espera {init_c.get(nombre)}")
            for nombre, vals in s.opers:
                st["piezas"] += 1
                if len(vals) != oper_c.get(nombre, -1):
                    fallos.append(f"{d.name}: oper {nombre} emite {len(vals)} "
                                  f"floats, el C espera {oper_c.get(nombre)}")
            # El emisor son 18 floats fijos; ver `we_psys_load`.
            if s.emisor and len(s.emit) != 18:
                fallos.append(f"{d.name}: emit emite {len(s.emit)} floats, "
                              f"el C espera 18")

            for x in s.sin_soporte:
                fuera[x] += 1
            for x in s.sin_cursor:
                fuera[f"sin cursor: {x}"] += 1
            if s.dibujable:
                st["dibujables"] += 1
                weparticles.escribir(s, tmp / "x.psys", 1)

    print("\n── corpus ──")
    for k in ("sistemas", "dibujables", "piezas", "error", "escena_err"):
        print(f"  {k:<12} {st[k]}")
    print("\n── piezas fuera de la simulacion ──")
    for k, v in fuera.most_common():
        print(f"  {k:<52} {v}")

    if fallos:
        print(f"\nFALLO: {len(fallos)} discrepancias")
        for f in fallos[:20]:
            print(f"  {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
