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

Se comprueban nueve cosas:

  1. Los dos lados conocen exactamente los mismos nombres.
  2. Cada pieza emitida trae los floats que el lector espera.
  3. Los `.psys` del corpus entero se escriben sin excepciones, y las piezas
     que quedan fuera son solo las declaradas como no soportadas.
  4. El lector en C entiende los decimales con la locale del escritorio puesta.
  5. La marca del cursor viaja: un punto de control con la marca puesta lo
     mueve `we_psys_puntero`, y sin puntero el operador que tira de el no
     actua.
  6. Los tres hijos de evento nacen cuando les toca; ver `prueba_hijos`.
  7. `orientation` sigue la regla que `wallpaper64.exe` aplica a los cuatro
     renderers, y ningun renderer del corpus pide una base que no sea la
     canonica.
  8. Un sistema con varios emisores emite por todos, cada uno en su forma y a
     su ritmo, al mismo deposito; ver `prueba_emisores`.
  9. `turbulentvelocityrandom` sigue la regla leida en `wallpaper64.exe`, con
     sus defectos; ver `prueba_turbvel`.

Uso:
    python3 tools/test_weparticles.py [--limit N]
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import weparticles
import wepaths
import wescene
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


ARNES_HIJOS_C = r"""
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "weparticles.h"
/* <padre.psys> <hijo.psys> <modo> <rafaga> <instancias> <escala> <segundos>
 *
 * Ata el hijo al padre, avanza los dos a 30 fps y escribe cuantas particulas
 * tiene cada uno y a que distancia media queda cada particula del hijo de la
 * del padre mas cercana, medida en el espacio del PADRE: el hijo se dibuja
 * con su escala encima, asi que sus posiciones se multiplican por ella. */
int main(int argc, char **argv)
{
    WeParticleSystem *pa = we_psys_load(argv[1], NULL);
    WeParticleSystem *h = we_psys_load(argv[2], NULL);
    if (!pa || !h) { printf("-1\n"); return 0; }
    float e = (float)atof(argv[6]);
    const float esc[3] = {e, e, 1.0f};
    we_psys_seguir(h, pa, atoi(argv[3]), atoi(argv[4]), atoi(argv[5]), 1.0f, esc);
    float t = (float)atof(argv[7]);
    int np = 0, nh = 0;
    for (int f = 0; f <= (int)(t * 30.0f + 0.5f); f++) {
        np = we_psys_update(pa, f / 30.0f) / WE_PSYS_VERTICES_POR_PARTICULA;
        nh = we_psys_update(h, f / 30.0f) / WE_PSYS_VERTICES_POR_PARTICULA;
    }
    const float *vp = we_psys_vertices(pa), *vh = we_psys_vertices(h);
    int fp = we_psys_floats_por_vertice(pa), fh = we_psys_floats_por_vertice(h);
    double suma = 0;
    for (int i = 0; i < nh; i++) {
        const float *q = vh + (size_t)i * WE_PSYS_VERTICES_POR_PARTICULA * fh;
        double mejor = 1e30;
        for (int j = 0; j < np; j++) {
            const float *r = vp + (size_t)j * WE_PSYS_VERTICES_POR_PARTICULA * fp;
            double d = hypot(q[0] * e - r[0], q[1] * e - r[1]);
            if (d < mejor) mejor = d;
        }
        suma += mejor;
    }
    printf("%d %d %.2f\n", np, nh, nh ? suma / nh : -1.0);
    return 0;
}
"""

"""El padre de la prueba de hijos: pocas particulas, de 6 s de vida, que nacen
repartidas en 400 px y se alejan a 60 px/s. Lo bastante separadas y rapidas
para que un hijo que no las siga se note."""
PSYS_PADRE = """\
maxcount 8
starttime 0
seed 3
anim 0 1
emit sphererandom 2 0 0 0 400 400 0 1 1 0 0 0 0 0 0 0 0 0 60 60
init lifetimerandom 6 6 1
"""

"""El hijo: el `rate` es el de CADA instancia y el emisor es un punto, asi que
cada particula nace exactamente donde esta la que sigue."""
PSYS_HIJO = """\
maxcount 400
starttime 0
seed 5
anim 0 1
emit sphererandom 20 0 0 0 0 0 0 1 1 0 0 0 0 0 0 0 0 0 0 0
init lifetimerandom 0.2 0.2 1
"""


def compila_arnes_hijos(tmp: Path) -> Path | None:
    fuente, binario = tmp / "arnes_hijos.c", tmp / "arnes_hijos"
    fuente.write_text(ARNES_HIJOS_C)
    try:
        subprocess.run(["cc", "-O0", "-std=c11", f"-I{FUENTE_C.parent}",
                        "-o", str(binario), str(fuente), str(FUENTE_C), "-lm"],
                       check=True, capture_output=True)
    except Exception as e:
        print(f"  (no se pudo compilar el arnes de hijos: {e}, prueba omitida)")
        return None
    return binario


def prueba_hijos(tmp: Path) -> list[str]:
    """Los tres hijos de evento, de la linea `psyspadre` al simulador.

    Lo que se exige es lo que distingue a cada uno, y lo que costaria verlo en
    un PNG:

    - `eventfollow` emite donde ESTA la particula que sigue: su estela tiene
      que quedarse pegada a particulas que se mueven a 60 px/s, tambien con
      una escala de entrada distinta de 1.
    - `eventspawn` nace con el padre: a los 3 s, con padres de 6 s de vida, ya
      tiene que haber estallado.
    - `eventdeath` nace con su muerte: a los 3 s todavia no ha muerto ninguno,
      y a los 9 s si.
    - Ninguno emite por su cuenta: un `eventspawn` con rafaga 0 no saca nada,
      aunque su `.psys` traiga `rate 20`.
    """
    binario = compila_arnes_hijos(tmp)
    if binario is None:
        return []
    padre, hijo = tmp / "padre.psys", tmp / "hijo.psys"
    padre.write_text(PSYS_PADRE)
    hijo.write_text(PSYS_HIJO)

    def mide(modo: int, rafaga: int, escala: float, t: float):
        r = subprocess.run([str(binario), str(padre), str(hijo), str(modo),
                            str(rafaga), "4", str(escala), str(t)],
                           capture_output=True, text=True)
        campos = r.stdout.split()
        return (int(campos[0]), int(campos[1]), float(campos[2])) \
            if len(campos) == 3 else None

    MUERE, NACE, SIGUE = 0, 1, 2
    fallos = []
    for escala in (1.0, 2.5):
        m = mide(SIGUE, 0, escala, 4.0)
        if m is None:
            return ["el arnes de hijos no devolvio nada"]
        print(f"  eventfollow  escala {escala:<4g} padre {m[0]}  hijo {m[1]:<4} "
              f"a {m[2]:.1f} px de su particula")
        if m[1] < 10:
            fallos.append(f"eventfollow con escala {escala:g}: solo {m[1]} "
                          f"particulas, no esta emitiendo")
        # 0,2 s de vida a 60 px/s: lo mas lejos que puede quedar una particula
        # de la que la solto son 12 px. Con la escala sin aplicar, o con la
        # estela soltada donde nacio el padre, sale a cientos.
        elif m[2] > 15.0:
            fallos.append(f"eventfollow con escala {escala:g}: la estela queda "
                          f"a {m[2]:.0f} px de su particula, no la sigue")
    nace3, muere3, muere9 = mide(NACE, 3, 1.0, 3.0), mide(MUERE, 3, 1.0, 3.0), \
        mide(MUERE, 3, 1.0, 9.0)
    print(f"  eventspawn   a los 3 s: {nace3[1]} particulas")
    print(f"  eventdeath   a los 3 s: {muere3[1]}, a los 9 s: {muere9[1]}")
    if not nace3[1]:
        fallos.append("eventspawn no estalla cuando nace el padre")
    if muere3[1]:
        fallos.append("eventdeath estalla antes de que muera ningun padre")
    if not muere9[1]:
        fallos.append("eventdeath no estalla cuando muere el padre")
    sin_rafaga = mide(NACE, 0, 1.0, 3.0)
    if sin_rafaga[1]:
        fallos.append(f"un hijo de evento emite por su cuenta: {sin_rafaga[1]} "
                      f"particulas con rafaga 0")
    return fallos


ARNES_EMISORES_C = r"""
#include <locale.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "weparticles.h"
/* <psys> <segundos>: simula con la locale del entorno y escribe las piezas sin
 * reconocer, los emisores, cuantas particulas hay en la caja lejana (x > 1000),
 * cuantas en la esfera del origen (a menos de 300), cuantas fuera de las dos, y
 * las vivas de cada emisor segun el simulador. */
int main(int argc, char **argv)
{
    setlocale(LC_ALL, "");
    int desconocidas = -1;
    WeParticleSystem *s = we_psys_load(argv[1], &desconocidas);
    if (!s) { printf("-1\n"); return 0; }
    int nv = we_psys_update(s, (float)atof(argv[2]));
    const float *v = we_psys_vertices(s);
    int paso = we_psys_floats_por_vertice(s);
    int caja = 0, esfera = 0, fuera = 0;
    for (int i = 0; i < nv; i += WE_PSYS_VERTICES_POR_PARTICULA) {
        const float *w = v + (size_t)i * paso;
        if (w[0] > 1000.0f) caja++;
        else if (hypotf(w[0], w[1]) < 300.0f) esfera++;
        else fuera++;
    }
    printf("%d %d %d %d %d %d %d\n", desconocidas, we_psys_emisores(s), caja,
           esfera, fuera, we_psys_vivas(s, 0), we_psys_vivas(s, 1));
    return 0;
}
"""


class _Resolver:
    """Lo minimo de `AssetResolver` para que `cargar` lea un preset en memoria."""
    def __init__(self, pj: dict):
        self.pj = pj

    def read_json(self, ruta: str) -> dict:
        return self.pj


"""Dos emisores de formas DISJUNTAS: una caja de 100 px de semieje lejos del
origen, a 15/s tras el `rate 0.5` del objeto, y una esfera que no declara nada
---como el segundo emisor de los dos sistemas del corpus---, o sea 256 px y
10/s, que el objeto deja en 5/s. Sin velocidad y con 100 s de vida, cada
particula se queda donde nacio y se puede contar de quien es por donde esta."""
PRESET_EMISORES = {
    "maxcount": 1000,
    "emitter": [{"name": "boxrandom", "rate": 30, "distancemax": "100 100 0",
                 "origin": "2000 0 0"},
                {"name": "sphererandom"}],
    "initializer": [{"name": "lifetimerandom", "min": 100, "max": 100}],
    "renderer": [{"name": "sprite"}],
    "material": "x.json",
}


def prueba_emisores(tmp: Path) -> list[str]:
    """Varios emisores, de `cargar` al simulador.

    Lo que se exige:

    - Python guarda los dos emisores, sin anotar ninguno como extra, con los
      defectos de siempre en el que no declara nada y el `rate` del objeto
      aplicado a CADA uno; y el `.psys` lleva una linea `emit` por emisor.
    - El C los lee los dos con la locale del escritorio, y cada uno suelta en
      su region y a su ritmo: a los 10 s, 150 en la caja y 50 en la esfera.
    - El deposito es UNO: con `maxcount 40` hay 40 particulas en total, no 40
      por emisor, y las dos regiones tienen alguna.
    """
    fallos = []
    s = weparticles.cargar(_Resolver(PRESET_EMISORES), "p.json", {"rate": 0.5})
    extra = [x for x in s.sin_soporte if x.startswith("emitter")]
    formas = [n for n, _ in s.emisores]
    print(f"  emisores {formas}  ritmos {[e[0] for _, e in s.emisores]}")
    if formas != ["boxrandom", "sphererandom"] or extra:
        return [f"dos emisores: Python guarda {formas} y anota {extra}"]
    caja, esfera = s.emisores[0][1], s.emisores[1][1]
    if [caja[0], esfera[0]] != [15.0, 5.0]:
        fallos.append(f"el `rate` del objeto no multiplica a cada emisor: "
                      f"{caja[0]:g} y {esfera[0]:g}, se esperaba 15 y 5")
    if esfera[4:7] != list(weparticles.DISTANCIA_POR_DEFECTO) \
            or esfera[7:10] != list(weparticles.DIRECCIONES_POR_DEFECTO):
        fallos.append(f"el segundo emisor no recibe los defectos: {esfera}")

    fuente, binario = tmp / "arnes_emisores.c", tmp / "arnes_emisores"
    fuente.write_text(ARNES_EMISORES_C)
    try:
        subprocess.run(["cc", "-O0", "-std=c11", f"-I{FUENTE_C.parent}",
                        "-o", str(binario), str(fuente), str(FUENTE_C), "-lm"],
                       check=True, capture_output=True)
    except Exception as e:
        # Sin compilador se omite, como las demas; con el, no compilar es que
        # el simulador ha perdido `we_psys_emisores`/`we_psys_vivas`.
        if shutil.which("cc") is None:
            print(f"  (sin compilador de C: {e}, prueba omitida)")
            return fallos
        return fallos + [f"el arnes de emisores no compila: {e}"]

    loc = locale_con_coma()
    locales = [("C", "C")] + ([(loc, loc)] if loc else [])
    for maxcount in (1000, 40):
        s.maxcount = maxcount
        psys = tmp / f"emisores{maxcount}.psys"
        weparticles.escribir(s, psys, 11)
        n_emit = sum(l.startswith("emit ") for l in psys.read_text().splitlines())
        if n_emit != 2:
            fallos.append(f"el .psys lleva {n_emit} lineas `emit`, no 2")
        for etq, entorno in locales:
            r = subprocess.run([str(binario), str(psys), "10"],
                               capture_output=True, text=True,
                               env=dict(os.environ, LC_ALL=entorno))
            c = [int(x) for x in r.stdout.split()]
            if len(c) != 7:
                fallos.append(f"el arnes de emisores no devolvio nada ({etq})")
                continue
            desc, n_em, en_caja, en_esfera, fuera, vivas0, vivas1 = c
            print(f"  maxcount {maxcount:<5} LC_ALL={etq:<12} caja {en_caja:<4} "
                  f"esfera {en_esfera:<4} fuera {fuera}  "
                  f"(vivas por emisor {vivas0} + {vivas1})")
            donde = f"maxcount {maxcount}, LC_ALL={etq}"
            if desc or n_em != 2:
                fallos.append(f"{donde}: el C lee {n_em} emisores y descarta "
                              f"{desc} piezas")
            if fuera or (en_caja, en_esfera) != (vivas0, vivas1):
                fallos.append(f"{donde}: las particulas no nacen en la forma de "
                              f"su emisor ({fuera} fuera de las dos)")
            if maxcount == 1000 and not (145 <= en_caja <= 155
                                         and 45 <= en_esfera <= 55):
                fallos.append(f"{donde}: {en_caja} en la caja y {en_esfera} en "
                              f"la esfera; a 15/s y 5/s deberian ser 150 y 50")
            if maxcount == 40 and (en_caja + en_esfera != 40
                                   or not en_caja or not en_esfera):
                fallos.append(f"{donde}: {en_caja} + {en_esfera} particulas; "
                              f"el deposito comun de 40 tiene que llenarse "
                              f"con las dos")
    return fallos


ARNES_TURBVEL_C = r"""
#include <locale.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "weparticles.h"
/* <psys> <segundos>: simula con la locale del entorno y escribe las piezas sin
 * reconocer, cuantas particulas hay, su velocidad media y cuanto se aparta de
 * ella la que mas. */
int main(int argc, char **argv)
{
    setlocale(LC_ALL, "");
    int desconocidas = -1;
    WeParticleSystem *s = we_psys_load(argv[1], &desconocidas);
    if (!s) { printf("-1\n"); return 0; }
    int nv = we_psys_update(s, (float)atof(argv[2]));
    const float *v = we_psys_vertices(s);
    int paso = we_psys_floats_por_vertice(s);
    double m[3] = {0, 0, 0}, dev = 0;
    int n = 0;
    for (int i = 0; i < nv; i += WE_PSYS_VERTICES_POR_PARTICULA, n++)
        for (int k = 0; k < 3; k++)
            m[k] += v[(size_t)i * paso + 13 + k];
    for (int k = 0; k < 3 && n; k++)
        m[k] /= n;
    for (int i = 0; i < nv; i += WE_PSYS_VERTICES_POR_PARTICULA)
        for (int k = 0; k < 3; k++)
            dev = fmax(dev, fabs(v[(size_t)i * paso + 13 + k] - m[k]));
    setlocale(LC_NUMERIC, "C");
    printf("%d %d %.5f %.5f %.5f %.5f\n", desconocidas, n, m[0], m[1], m[2], dev);
    return 0;
}
"""

# La tabla de permutacion de Perlin (Improved Noise, 2002), que es la que
# `wallpaper64.exe` guarda en 0x140484f40. Va escrita aqui y no leida del .c
# para que la prueba no compare el simulador consigo mismo.
PERLIN = [
    151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225,
    140, 36, 103, 30, 69, 142, 8, 99, 37, 240, 21, 10, 23, 190, 6, 148,
    247, 120, 234, 75, 0, 26, 197, 62, 94, 252, 219, 203, 117, 35, 11, 32,
    57, 177, 33, 88, 237, 149, 56, 87, 174, 20, 125, 136, 171, 168, 68, 175,
    74, 165, 71, 134, 139, 48, 27, 166, 77, 146, 158, 231, 83, 111, 229, 122,
    60, 211, 133, 230, 220, 105, 92, 41, 55, 46, 245, 40, 244, 102, 143, 54,
    65, 25, 63, 161, 1, 216, 80, 73, 209, 76, 132, 187, 208, 89, 18, 169,
    200, 196, 135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173, 186, 3, 64,
    52, 217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212,
    207, 206, 59, 227, 47, 16, 58, 17, 182, 189, 28, 42, 223, 183, 170, 213,
    119, 248, 152, 2, 44, 154, 163, 70, 221, 153, 101, 155, 167, 43, 172, 9,
    129, 22, 39, 253, 19, 98, 108, 110, 79, 113, 224, 232, 178, 185, 112, 104,
    218, 246, 97, 228, 251, 34, 242, 193, 238, 210, 144, 12, 191, 179, 162, 241,
    81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31, 181, 199, 106, 157,
    184, 84, 204, 176, 115, 121, 50, 45, 127, 4, 150, 254, 138, 236, 205, 93,
    222, 114, 67, 29, 24, 72, 243, 141, 128, 195, 78, 66, 215, 61, 156, 180,
]


def _snoise1(x: float) -> float:
    """El `snoise1` de WE (0x14027b090), en doble precision."""
    i0 = math.floor(x)
    x0 = x - i0
    x1 = x0 - 1.0
    def grad(h: int, d: float) -> float:
        g = 1.0 + (h & 7)
        return (-g if h & 8 else g) * d
    return 0.395 * ((1 - x0 * x0) ** 4 * grad(PERLIN[i0 & 255], x0)
                    + (1 - x1 * x1) ** 4 * grad(PERLIN[(i0 + 1) & 255], x1))


def _regla_turbvel(v: list[float], reloj: float) -> list[float]:
    """La velocidad que da la regla de WE con fase y rapidez FIJAS (min = max).

    `v` son los 13 floats de la pieza. Rodrigues con `right` normalizado, que es
    lo que hace `glm::rotate` (0x1401e2500) por el vector."""
    vmin, _, fmin, _, ts, esc, off = v[:7]
    fw, rt = v[7:10], v[10:13]
    ang = math.pi * esc * _snoise1((fmin + reloj) * ts) + off
    n = math.sqrt(sum(c * c for c in rt))
    e = [c / n for c in rt]
    c, s = math.cos(ang), math.sin(ang)
    ef = sum(a * b for a, b in zip(e, fw))
    x = [e[1] * fw[2] - e[2] * fw[1], e[2] * fw[0] - e[0] * fw[2],
         e[0] * fw[1] - e[1] * fw[0]]
    return [(fw[k] * c + x[k] * s + e[k] * ef * (1 - c)) * vmin for k in range(3)]


def prueba_turbvel(tmp: Path) -> list[str]:
    """`turbulentvelocityrandom` con la regla leida en wallpaper64.exe.

    Lo que se exige:

    - Python inserta los defectos de WE: rapidez 100..250 en una escena
      ortografica y 0,5..1 si no, fase 0..0,1, `timescale` 1, `scale` 1,
      `offset` 0, `forward` 0 1 0 y `right` 0 0 1; y `wescene.ortografica`
      decide como el cargador de WE.
    - El simulador gira `forward` alrededor de `right` el angulo
      pi * scale * snoise1((fase + reloj) * timescale) + offset. Con la fase y
      la rapidez fijas, todas las particulas de una rafaga nacen con la MISMA
      velocidad, y tiene que ser la de la regla: sin el giro saldrian por
      `forward` tal cual; con el `offset` como desplazamiento, sin sumarlo al
      angulo; con `right` sin normalizar, girando de mas; y con el reloj del
      sistema en vez del de la escena, en otro sitio del ruido.
    """
    fallos = []
    pz = {"name": "turbulentvelocityrandom"}
    orto, persp = weparticles._init_turbvel(pz), weparticles._init_turbvel(pz, False)
    if orto != [100.0, 250.0, 0.0, 0.1, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]:
        fallos.append(f"turbvel: defectos en una escena ortografica {orto}")
    if persp[:2] != [0.5, 1.0] or persp[2:] != orto[2:]:
        fallos.append(f"turbvel: defectos en una escena en perspectiva {persp}")
    pz_up = dict(pz, up="0 100 0", offset=-0.5, forward="0 0.25 0", right="10 0 1")
    v = weparticles._init_turbvel(pz_up)
    if v[6] != -0.5 or v[7:] != [0.0, 0.25, 0.0, 10.0, 0.0, 1.0]:
        fallos.append(f"turbvel: `offset`, `forward` o `right` no llegan tal cual: {v}")
    for general, quiere in (({}, False),
                            ({"orthogonalprojection": None}, False),
                            ({"orthogonalprojection": {"auto": True}}, True),
                            ({"orthogonalprojection": {"width": 1920, "height": 1080}}, True),
                            ({"orthogonalprojection": {"width": 1920, "height": 0}}, False),
                            ({"orthogonalprojection": {"width": 0, "height": 1080}}, False)):
        if wescene.ortografica(general) != quiere:
            fallos.append(f"ortografica({general}) no da {quiere}")

    fuente, binario = tmp / "arnes_turbvel.c", tmp / "arnes_turbvel"
    fuente.write_text(ARNES_TURBVEL_C)
    try:
        subprocess.run(["cc", "-O0", "-std=c11", f"-I{FUENTE_C.parent}",
                        "-o", str(binario), str(fuente), str(FUENTE_C), "-lm"],
                       check=True, capture_output=True)
    except Exception as e:
        if shutil.which("cc") is None:
            print(f"  (sin compilador de C: {e}, prueba omitida)")
            return fallos
        return fallos + [f"el arnes de la turbulencia no compila: {e}"]

    loc = locale_con_coma()
    locales = [("C", "C")] + ([(loc, loc)] if loc else [])
    # Una rafaga de 20 que nace en el primer paso, sin ritmo, con fase y
    # rapidez fijas. `starttime` pone el reloj de la escena en -starttime al
    # nacer.
    casos = [
        ("defectos de ejes", {"phasemin": 0.37, "phasemax": 0.37, "scale": 0.5,
                              "speedmin": 100, "speedmax": 100}, 0.0),
        ("offset es un angulo", {"phasemin": 0.37, "phasemax": 0.37, "scale": 0.5,
                                 "offset": 1.0, "speedmin": 100, "speedmax": 100}, 0.0),
        ("right sin normalizar", {"phasemin": 0.37, "phasemax": 0.37, "scale": 0.5,
                                  "forward": "0 0.25 0", "right": "10 0 1",
                                  "up": "0 100 0", "speedmin": 80, "speedmax": 80}, 0.0),
        ("reloj de la escena", {"phasemin": 0.37, "phasemax": 0.37, "scale": 0.5,
                                "timescale": 2, "speedmin": 100, "speedmax": 100}, 1.5),
        ("forward nulo", {"phasemin": 0.37, "phasemax": 0.37, "forward": "0 0 0",
                          "speedmin": 100, "speedmax": 100}, 0.0),
    ]
    for etq, campos, arranque in casos:
        preset = {"maxcount": 20, "starttime": arranque,
                  "emitter": [{"name": "sphererandom", "rate": 0,
                               "instantaneous": 20}],
                  "initializer": [{"name": "lifetimerandom", "min": 100, "max": 100},
                                  dict(pz, **campos)],
                  "renderer": [{"name": "sprite"}],
                  "material": "x.json"}
        s = weparticles.cargar(_Resolver(preset), "p.json")
        vals = dict(s.inits)["turbulentvelocityrandom"]
        quiere = _regla_turbvel(vals, -arranque)
        psys = tmp / "turbvel.psys"
        weparticles.escribir(s, psys, 5)
        for etq_loc, entorno in locales:
            r = subprocess.run([str(binario), str(psys), "0.01"],
                               capture_output=True, text=True,
                               env=dict(os.environ, LC_ALL=entorno))
            c = r.stdout.split()
            if len(c) != 6:
                fallos.append(f"turbvel {etq}: el arnes no devolvio nada ({etq_loc})")
                continue
            desc, n = int(c[0]), int(c[1])
            hay, dev = [float(x) for x in c[2:5]], float(c[5])
            print(f"  {etq:<22} LC_ALL={etq_loc:<12} n {n:<3} v ({hay[0]:8.3f}, "
                  f"{hay[1]:8.3f}, {hay[2]:8.3f})  regla ({quiere[0]:8.3f}, "
                  f"{quiere[1]:8.3f}, {quiere[2]:8.3f})")
            err = max(abs(a - b) for a, b in zip(hay, quiere))
            if desc or n != 20 or dev > 1e-3 or err > 1e-2:
                fallos.append(f"turbvel {etq} (LC_ALL={etq_loc}): {n} particulas, "
                              f"{desc} piezas descartadas, v {hay} contra la regla "
                              f"{[round(x, 3) for x in quiere]}")
    return fallos


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


# Lo que `wallpaper64.exe` hace con `orientation` (`0x1401c22e0` lo lee,
# `0x1402298b0` pone los tres `g_Orientation*`), reducido a la pregunta de
# `_orientacion`: si la base que sale es la canonica que ya emite el plan. Las
# cintas van por la MISMA rutina que los sprites, asi que la respuesta no
# depende de `cinta`.
CASOS_ORIENTACION = [
    # (renderer, ¿base canonica?)
    ({"name": "sprite"}, True),
    ({"name": "sprite", "orientation": "camera"}, True),
    ({"name": "sprite", "orientation": "screen"}, True),
    # `up` del objeto, con el eje (0, 1, 0) por defecto: sin z, da la de screen.
    ({"name": "rope", "orientation": "upright", "subdivision": 2}, True),
    ({"name": "rope", "orientation": "upright", "axis": "0 0 0"}, True),
    ({"name": "sprite", "orientation": "upright", "axis": "1 1 0"}, True),
    # `flags & 1`: `up` del mundo, y el eje no se mira.
    ({"name": "sprite", "orientation": "upright", "axis": "0 0 1", "flags": 1}, True),
    # Un `up` con z tuerce `forward` fuera de la vista.
    ({"name": "rope", "orientation": "upright", "axis": "0 0 1"}, False),
    ({"name": "sprite", "orientation": "upright", "axis": "0 1 1"}, False),
    ({"name": "spritetrail", "orientation": "fixed", "axis": "0 0 1"}, True),
    ({"name": "ropetrail", "orientation": "fixed", "axis": "0 0 1"}, True),
    ({"name": "spritetrail", "orientation": "fixed", "axis": "0 1 0"}, False),
    ({"name": "rope", "orientation": "fixed"}, False),
    ({"name": "sprite", "orientation": "otra"}, False),
]


def prueba_orientacion() -> list[str]:
    fallos = []
    for e, canonica in CASOS_ORIENTACION:
        for cinta in (False, True):
            aviso = weparticles._orientacion(e, cinta)
            if (aviso is None) != canonica:
                fallos.append(f"orientation {e} (cinta={cinta}): "
                              f"{'avisa' if aviso else 'no avisa'} y WE "
                              f"{'da la base canonica' if canonica else 'da otra base'}")
    print(f"  {len(CASOS_ORIENTACION)} casos, {len(fallos)} fallos")
    return fallos


def aviso_de_orientacion(x: str) -> bool:
    return x.startswith(("orientacion ", "estela "))


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

    # ── 6. los hijos de evento ──
    print("\n── los hijos de evento ──")
    fallos += prueba_hijos(tmp)

    # ── 7. `orientation`, con la regla de WE ──
    print("\n── orientation ──")
    fallos += prueba_orientacion()

    # ── 8. varios emisores al mismo deposito ──
    print("\n── varios emisores ──")
    fallos += prueba_emisores(tmp)

    # ── 9. la turbulencia con la regla de WE ──
    print("\n── turbulentvelocityrandom ──")
    fallos += prueba_turbvel(tmp)

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
                                       o.get("instanceoverride"),
                                       ortografica=wescene.ortografica(
                                           escena.get("general") or {}))
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
            # Cada emisor son 20 floats fijos; ver `we_psys_load`.
            for _, emit in s.emisores:
                if len(emit) != 20:
                    fallos.append(f"{d.name}: emit emite {len(emit)} floats, "
                                  f"el C espera 20")
            if len(s.emisores) > 1:
                st["varios_emisores"] += 1

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
                # Emiten todos, hasta `MAX_EMISORES`; uno que sobre es un
                # sistema que el simulador dibujaria a medias.
                if x.startswith("emitter extra"):
                    fallos.append(f"{d.name} {o.get('name')!r}: {x}")
                # Ninguna orientacion del corpus pide otra base; si una
                # aparece, es un caso nuevo que mirar en el motor.
                if aviso_de_orientacion(x):
                    fallos.append(f"{d.name} {o.get('name')!r}: {x}")
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
              "varios_emisores", "cp_cursor", "tiran_del_cursor", "error", "escena_err"):
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
