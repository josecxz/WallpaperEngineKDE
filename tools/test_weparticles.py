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

Se comprueban cinco cosas:

  1. Los dos lados conocen exactamente los mismos nombres.
  2. Cada pieza emitida trae los floats que el lector espera.
  3. Los `.psys` del corpus entero se escriben sin excepciones, y las piezas
     que quedan fuera son solo las declaradas como no soportadas.
  4. El lector en C entiende los decimales con la locale del escritorio puesta.
  5. La marca del cursor viaja: un punto de control con la marca puesta lo
     mueve `we_psys_puntero`, y sin puntero el operador que tira de el no
     actua.

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
emit sphererandom 20.5 0 0 0 750.25 750.25 750.25 1 0.1 1 350.5 750.5 0 0 0 0 0 0 12.5 34.5
init lifetimerandom 16.5 20.5 2.5
init alpharandom 0.25 0.75 1.5
oper alphafade 0.1 0.9
oper movement 0.5 0.25 0.125 0.0625
"""
PIEZAS_DECIMALES = 4          # 2 init + 2 oper; ninguna puede quedar fuera

ARNES_C = r"""
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include "weparticles.h"
/* Qt adopta la locale del entorno al arrancar; sin esto la prueba no prueba
 * nada, porque un binario en C se queda en la locale "C" por defecto.
 *
 * Con `<psys> <segundos>` simula y escribe el centro de la nube; con tres
 * numeros mas, lo mismo pero con el puntero ahi. Es lo que hace
 * `tools/psysprobe.c`, repetido aqui para que la prueba no dependa de otro
 * target del Makefile. */
int main(int argc, char **argv)
{
    setlocale(LC_ALL, "");
    int desconocidas = -1;
    WeParticleSystem *s = we_psys_load(argv[1], &desconocidas);
    if (!s) { printf("-1\n"); return 0; }
    if (argc < 3) { printf("%d\n", desconocidas); return 0; }

    if (argc >= 6) {
        const float p[3] = {(float)atof(argv[3]), (float)atof(argv[4]),
                            (float)atof(argv[5])};
        we_psys_puntero(s, p);
    }
    int nv = we_psys_update(s, (float)atof(argv[2]));
    const float *v = we_psys_vertices(s);
    int paso = we_psys_floats_por_vertice(s);
    double cx = 0, cy = 0;
    int n = 0;
    for (int i = 0; i < nv; i += WE_PSYS_VERTICES_POR_PARTICULA) {
        cx += v[(size_t)i * paso];
        cy += v[(size_t)i * paso + 1];
        n++;
    }
    /* Se ha simulado con la locale del escritorio ---que es de lo que va la
     * prueba de al lado--- pero los numeros hay que ESCRIBIRLOS con punto o
     * no los lee quien llama. */
    setlocale(LC_NUMERIC, "C");
    printf("%d %d %.1f %.1f\n", desconocidas, we_psys_cursor(s),
           n ? cx / n : 0.0, n ? cy / n : 0.0);
    return 0;
}
"""

"""Un sistema con un punto de control atado al cursor y un operador que tira
de el. Los numeros son los del preset `fireflies` de WE, que es el origen de
111 de los 136 `controlpointattract` del corpus."""
PSYS_CURSOR = """\
maxcount 64
starttime 0
seed 7
anim 0 1
emit sphererandom 20 0 0 0 512 512 0 1 1 1 0 0 0 0 0 0 0 0 0 0
cp 0 0 0 0 0
cp 1 0 0 0 1
init lifetimerandom 30 30 1
oper movement 0 0 0 2.5
oper controlpointattract 1 -500 64 0 0 0
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


def compila_arnes(tmp: Path) -> Path | None:
    """Compila `ARNES_C` contra el simulador de verdad. `None` si no se puede."""
    fuente, binario = tmp / "arnes.c", tmp / "arnes"
    if binario.is_file():
        return binario
    fuente.write_text(ARNES_C)
    try:
        subprocess.run(["cc", "-O0", "-std=c11", f"-I{FUENTE_C.parent}",
                        "-o", str(binario), str(fuente), str(FUENTE_C), "-lm"],
                       check=True, capture_output=True)
    except Exception as e:
        print(f"  (no se pudo compilar el arnes: {e}, prueba omitida)")
        return None
    return binario


def prueba_cursor(tmp: Path) -> list[str]:
    """La marca del cursor, de `weparticles.py` a `we_psys_puntero`.

    Es un contrato de dos piezas y ninguna falla sola. Si la marca no viaja en
    la linea `cp`, el punto se queda en el origen del sistema y el operador
    ---que en el corpus es siempre `controlpointattract` con `scale` negativa---
    se convierte en un sumidero que apelotona la nube en el centro. Si viaja
    pero el simulador no la mira, pasa lo mismo. Las dos averias se ven igual
    en un PNG: una nube mas pequena de lo que deberia.

    Asi que se mide donde acaba la nube: sin puntero tiene que quedarse
    alrededor del origen ---la emite una esfera de 512 px--- y con puntero
    tiene que irse a el.
    """
    binario = compila_arnes(tmp)
    if binario is None:
        return []

    psys = tmp / "cursor.psys"
    psys.write_text(PSYS_CURSOR)
    destino = (400.0, -300.0)

    def centro(*extra: str) -> tuple[int, float, float] | None:
        r = subprocess.run([str(binario), str(psys), "10", *extra],
                           capture_output=True, text=True)
        campos = r.stdout.split()
        if len(campos) != 4:
            return None
        return int(campos[1]), float(campos[2]), float(campos[3])

    fallos = []
    sin = centro()
    con = centro(f"{destino[0]}", f"{destino[1]}", "0")
    if sin is None or con is None:
        return ["el arnes no devolvio el centro de la nube"]

    if not sin[0]:
        fallos.append("la marca del cursor no llega al C: `we_psys_cursor` "
                      "dice que no hay ningun punto atado al puntero")
    dist_sin = math.dist(sin[1:], destino)
    dist_con = math.dist(con[1:], destino)
    print(f"  sin puntero  centro ({sin[1]:.0f}, {sin[2]:.0f})   "
          f"a {dist_sin:.0f} px del destino")
    print(f"  con puntero  centro ({con[1]:.0f}, {con[2]:.0f})   "
          f"a {dist_con:.0f} px del destino")
    # La nube no colapsa en un punto ---el `threshold` de 64 px la suelta antes
    # de llegar, y la emision sigue soltando particulas nuevas en la esfera de
    # 512--- asi que lo que se exige es que se haya ido A el, no que este clavada.
    if dist_con > 150.0:
        fallos.append(f"con el puntero en {destino} la nube se queda a "
                      f"{dist_con:.0f} px: el punto de control no lo sigue")
    if math.dist(sin[1:], (0.0, 0.0)) > 150.0:
        fallos.append("sin puntero la nube no se queda alrededor del origen: "
                      "el operador del cursor esta actuando cuando no debe")
    return fallos


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
    binario = compila_arnes(tmp)
    if binario is None:
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

    # ── 5. el punto de control que sigue al raton ──
    print("\n── el cursor mueve su punto de control ──")
    fallos += prueba_cursor(tmp)

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
            # El emisor son 20 floats fijos; ver `we_psys_load`.
            if s.emisor and len(s.emit) != 20:
                fallos.append(f"{d.name}: emit emite {len(s.emit)} floats, "
                              f"el C espera 20")

            if s.cinta:
                st["cintas"] += 1
            if s.estela:
                st["estelas"] += 1
                largo = _largo_estela(s)
                if largo is None:
                    st["estelas_sin_cota"] += 1
                else:
                    largos.append(largo)

            for x in s.sin_soporte:
                fuera[x] += 1
            # No son piezas fuera de la simulacion: son las que solo hacen
            # algo cuando el raton esta sobre el fondo.
            if s.cps_cursor:
                st["cp_cursor"] += 1
            if s.con_cursor:
                st["tiran_del_cursor"] += 1
            if s.dibujable:
                st["dibujables"] += 1
                weparticles.escribir(s, tmp / "x.psys", 1)

    print("\n── corpus ──")
    for k in ("sistemas", "dibujables", "piezas", "estelas", "cintas",
              "cp_cursor", "tiran_del_cursor", "error", "escena_err"):
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
