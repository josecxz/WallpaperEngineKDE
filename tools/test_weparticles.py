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

Se comprueban cuatro cosas:

  1. Los dos lados conocen exactamente los mismos nombres.
  2. Cada pieza emitida trae los floats que el lector espera.
  3. Los `.psys` del corpus entero se escriben sin excepciones, y las piezas
     que quedan fuera son solo las declaradas como no soportadas.
  4. El lector en C entiende los decimales con la locale del escritorio puesta.

Uso:
    python3 tools/test_weparticles.py [--limit N]
"""

from __future__ import annotations

import math
import os
import re
import subprocess
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


"""Fichero de prueba para el lector en C: todas las piezas llevan decimales."""
PSYS_DECIMALES = """\
maxcount 10
starttime 0.5
anim 0 1.5
emit sphererandom 20.5 0 0 0 750.25 750.25 750.25 1 0.1 1 350.5 750.5 0 0 0 0 0 0
init lifetimerandom 16.5 20.5
init alpharandom 0.25 0.75
oper alphafade 0.1 0.9
oper movement 0.5 0.25 0.125 0.0625
"""
PIEZAS_DECIMALES = 4          # 2 init + 2 oper; ninguna puede quedar fuera

ARNES_C = r"""
#include <locale.h>
#include <stdio.h>
#include "weparticles.h"
/* Qt adopta la locale del entorno al arrancar; sin esto la prueba no prueba
 * nada, porque un binario en C se queda en la locale "C" por defecto. */
int main(int argc, char **argv)
{
    setlocale(LC_ALL, "");
    int desconocidas = -1;
    WeParticleSystem *s = we_psys_load(argv[1], &desconocidas);
    printf("%d\n", s ? desconocidas : -1);
    return 0;
}
"""


def locale_con_coma() -> str | None:
    """Primera locale instalada cuyo separador decimal NO sea el punto."""
    try:
        salida = subprocess.run(["locale", "-a"], capture_output=True,
                                text=True, check=True).stdout.split()
    except Exception:
        return None
    disponibles = {n.lower() for n in salida}
    for cand in ("es_es.utf8", "es_es.utf-8", "de_de.utf8", "fr_fr.utf8",
                 "it_it.utf8", "pt_br.utf8"):
        if cand in disponibles:
            return next(n for n in salida if n.lower() == cand)
    return None


def prueba_locale(tmp: Path) -> list[str]:
    """El punto decimal del `.psys` contra `LC_NUMERIC` del escritorio.

    `strtof` mira `LC_NUMERIC`. Dentro de plasmashell la locale es la del
    usuario, y con una de coma "0.88235" se lee como 0: la pieza se queda corta
    de floats y `we_psys_load` la descarta como si no estuviera soportada. El
    renderizador offline no lo ve --- nunca llama a `setlocale` --- asi que el
    fallo solo aparecia en el escritorio, y como piezas "sin soporte", que es
    justo lo que uno no va a mirar dos veces.
    """
    loc = locale_con_coma()
    if loc is None:
        print("  (sin locale de coma instalada, prueba omitida)")
        return []

    psys = tmp / "decimales.psys"
    psys.write_text(PSYS_DECIMALES)
    fuente, binario = tmp / "arnes.c", tmp / "arnes"
    fuente.write_text(ARNES_C)
    raiz = FUENTE_C.parent
    try:
        subprocess.run(["cc", "-O0", "-std=c11", f"-I{raiz}", "-o", str(binario),
                        str(fuente), str(FUENTE_C), "-lm"], check=True,
                       capture_output=True)
    except Exception as e:
        print(f"  (no se pudo compilar el arnes: {e}, prueba omitida)")
        return []

    fallos = []
    for etq, entorno in (("C", "C"), (loc, loc)):
        env = dict(os.environ, LC_ALL=entorno)
        r = subprocess.run([str(binario), str(psys)], capture_output=True,
                           text=True, env=env)
        n = int(r.stdout.strip() or -1)
        print(f"  LC_ALL={etq:<12} piezas sin soporte: {n}")
        if n != 0:
            fallos.append(f"con LC_ALL={etq} el lector en C descarta {n} de "
                          f"{PIEZAS_DECIMALES} piezas: los decimales no se leen")
    return fallos


# Largo maximo tolerable de una estela, en ANCHOS DE SPRITE --- que es la unidad
# en la que trabaja `ComputeParticleTrailTangents`. El `maxlength` mas grande que
# declara el corpus es 100, asi que nada deberia pasar de ahi por su cuenta.
TOPE_ESTELA = 100.0


def _largo_estela(s) -> float | None:
    """Largo de la estela del sistema, en anchos de sprite.

    Es la cuenta del shader ---  `max(min, min(|v| * length, max))` --- con la
    velocidad inicial mas rapida que declara `velocityrandom`. `None` si el
    sistema no lo declara: entonces la velocidad se la dan la turbulencia o los
    operadores, y de ahi no sale una cota fiable.

    Existe porque un valor por defecto mal elegido no falla: dibuja. Con
    `maxlength` sin tope, los copos de 16 px de `2868108515` salian con rastros
    de 4092 px y el render terminaba sin un solo aviso.
    """
    v = dict(s.inits).get("velocityrandom")
    if not v or len(v) < 6:
        return None
    largo, tope, suelo = s.estela
    rapidez = max(math.dist(v[0:3], (0, 0, 0)), math.dist(v[3:6], (0, 0, 0)))
    return max(suelo, min(rapidez * largo, tope))


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

    # ── 4. el lector en C con la locale del escritorio ──
    print("\n── locale del lector en C ──")
    fallos += prueba_locale(tmp)

    st = Counter()
    fuera = Counter()
    largos: list[tuple[float, str]] = []
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

            if s.estela:
                st["estelas"] += 1
                largo = _largo_estela(s)
                if largo is None:
                    st["estelas_sin_cota"] += 1
                else:
                    largos.append(largo)

            for x in s.sin_soporte:
                fuera[x] += 1
            for x in s.sin_cursor:
                fuera[f"sin cursor: {x}"] += 1
            if s.dibujable:
                st["dibujables"] += 1
                weparticles.escribir(s, tmp / "x.psys", 1)

    print("\n── corpus ──")
    for k in ("sistemas", "dibujables", "piezas", "estelas", "error", "escena_err"):
        print(f"  {k:<12} {st[k]}")

    if largos:
        v = sorted(largos)
        print("\n── estelas (largo en anchos de sprite) ──")
        print(f"  acotadas {len(v)}, sin cota {st['estelas_sin_cota']}")
        print(f"  min {v[0]:g}   mediana {v[len(v)//2]:g}   max {v[-1]:g}")
        for largo in largos:
            if largo > TOPE_ESTELA:
                fallos.append(f"estela de {largo:g} anchos de sprite, por encima "
                              f"del tope de {TOPE_ESTELA:g}: revisa los valores "
                              f"por defecto de `_estela`")
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
