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

Se comprueban doce cosas:

  1. Los dos lados conocen exactamente los mismos nombres.
  2. Cada pieza emitida trae los floats que el lector espera.
  3. Los `.psys` del corpus entero se escriben sin excepciones, y las piezas
     que quedan fuera son solo las declaradas como no soportadas.
  4. El lector en C entiende los decimales con la locale del escritorio puesta.
  5. La marca del cursor viaja: un punto de control con la marca puesta lo
     mueve `we_psys_puntero`, y sin puntero el operador que tira de el no
     actua.
  6. Los tres hijos de evento nacen cuando les toca, y una instancia de
     nacimiento o de muerte con `rate` emite como en `wallpaper64.exe`; ver
     `prueba_hijos`.
  7. `orientation` sigue la regla que `wallpaper64.exe` aplica a los cuatro
     renderers, y ningun renderer del corpus pide una base que no sea la
     canonica.
  8. Un sistema con varios emisores emite por todos, cada uno en su forma y a
     su ritmo, al mismo deposito; ver `prueba_emisores`.
  9. `turbulentvelocityrandom` sigue la regla leida en `wallpaper64.exe`, con
     sus defectos; ver `prueba_turbvel`.
 10. El emisor nace alrededor de su punto de control mas su `origin`, y el
     `controlpoint` viaja al final de la linea `emit`; ver
     `prueba_punto_del_emisor`.
 11. Un `rope` es UNA cinta que une las particulas vivas de la mas vieja a la
     mas nueva, como la cose `wallpaper64.exe`; ver `prueba_cuerda`.
 12. Con `subdivision`, cada tramo del `rope` sigue la Bezier de
     `genericropeparticle.geom`, y con `subdivision: 0` la cuerda es la recta
     de siempre, numero a numero; ver `prueba_subdivision`.

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
 * target del Makefile. Con `<usar> <radio>` detras, `usar` 0 deja el sistema
 * sin puntero, y ademas cuenta las particulas a menos de `radio` del punto. */
int main(int argc, char **argv)
{
    setlocale(LC_ALL, "");
    int desconocidas = -1;
    WeParticleSystem *s = we_psys_load(argv[1], &desconocidas);
    if (!s) { printf("-1\n"); return 0; }
    if (argc < 3) { printf("%d\n", desconocidas); return 0; }

    float p[3] = {0, 0, 0};
    if (argc >= 6) {
        p[0] = (float)atof(argv[3]);
        p[1] = (float)atof(argv[4]);
        p[2] = (float)atof(argv[5]);
        if (argc < 7 || atoi(argv[6]))
            we_psys_puntero(s, p);
    }
    const float radio = argc >= 8 ? (float)atof(argv[7]) : -1.0f;
    int nv = we_psys_update(s, (float)atof(argv[2]));
    const float *v = we_psys_vertices(s);
    int paso = we_psys_floats_por_vertice(s);
    double cx = 0, cy = 0;
    int n = 0, dentro = 0;
    for (int i = 0; i < nv; i += 1) {
        cx += v[(size_t)i * paso];
        cy += v[(size_t)i * paso + 1];
        n++;
    }
    /* Un registro por particula (sprite instanciado): su centro. */
    for (int i = 0; radio >= 0 && i < nv; i += 1) {
        double x = 0, y = 0;
        for (int k = 0; k < 1; k++) {
            x += v[(size_t)(i + k) * paso];
            y += v[(size_t)(i + k) * paso + 1];
        }
        x /= 1;
        y /= 1;
        if ((x - p[0]) * (x - p[0]) + (y - p[1]) * (y - p[1]) < radio * radio)
            dentro++;
    }
    /* Se ha simulado con la locale del escritorio ---que es de lo que va la
     * prueba de al lado--- pero los numeros hay que ESCRIBIRLOS con punto o
     * no los lee quien llama. */
    setlocale(LC_NUMERIC, "C");
    printf("%d %d %.1f %.1f", desconocidas, we_psys_cursor(s),
           n ? cx / n : 0.0, n ? cy / n : 0.0);
    if (radio >= 0)
        printf(" %d", dentro);
    printf("\n");
    return 0;
}
"""

"""Un sistema con un punto de control atado al cursor y un operador que tira
de el. `scale`, `threshold` y `drag` son los del preset `fireflies` de WE, que
es el origen de 111 de los 136 `controlpointattract` del corpus; el ritmo y el
tope estan subidos para que haya particulas que contar cerca del puntero. Las
particulas nacen quietas, en el disco plano de `directions 1 1 0` ---el defecto
de WE---: con `1 1 1` la esfera las reparte en z hasta 512 px y la distancia,
que el operador mide en 3D, deja fuera de su alcance a la mitad de las que en
pantalla caen junto al puntero."""
PSYS_CURSOR = """\
maxcount 4000
starttime 0
seed 7
anim 0 1
emit sphererandom 400 0 0 0 512 512 0 1 1 0 0 0 0 0 0 0 0 0 0 0
cp 0 0 0 0 0
cp 1 0 0 0 1
init lifetimerandom 30 30 1
oper movement 0 0 0 2.5
oper controlpointattract 1 @ESCALA@ 64 0
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
        np = we_psys_update(pa, f / 30.0f) / 1;
        nh = we_psys_update(h, f / 30.0f) / 1;
    }
    const float *vp = we_psys_vertices(pa), *vh = we_psys_vertices(h);
    int fp = we_psys_floats_por_vertice(pa), fh = we_psys_floats_por_vertice(h);
    double suma = 0;
    for (int i = 0; i < nh; i++) {
        const float *q = vh + (size_t)i * 1 * fh;
        double mejor = 1e30;
        for (int j = 0; j < np; j++) {
            const float *r = vp + (size_t)j * 1 * fp;
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

"""El mismo hijo con su punto 0 lejos. Suelto, emitiria alrededor de el; colgado
de un padre lo coloca el evento, y sumarle ademas el punto lo llevaria a 7 km
de la particula que sigue."""
PSYS_HIJO_CON_PUNTO = PSYS_HIJO + "cp 0 5000 -5000 0 0\n"

"""Un hijo con `rate` y sin `instantaneous`, como los 8 de nacimiento del corpus
que no declaran rafaga: 10 por segundo, 0,5 s de vida. El `maxcount` es el que
escribe el plan, el del preset (20) por las 2 instancias de la entrada."""
PSYS_HIJO_RITMO = """\
maxcount 40
starttime 0
seed 9
anim 0 1
emit sphererandom 10 0 0 0 0 0 0 1 1 0 0 0 0 0 0 0 0 0 0 0
init lifetimerandom 0.5 0.5 1
"""

"""El mismo con 3 de `maxcount` en el preset: cada instancia se queda en 3 vivas
aunque su ritmo diera para 5."""
PSYS_HIJO_RITMO_TOPE = PSYS_HIJO_RITMO.replace("maxcount 40", "maxcount 6")


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
    - Una instancia de `eventspawn` o `eventdeath` cuyo emisor tiene `rate`
      sigue la regla de `wallpaper64.exe` (ver NOTAS, «La instancia de un hijo
      de evento»): sin `instantaneous` no suelta nada de golpe y emite a su
      `rate` donde la creo el evento, para siempre ---tambien cuando ya ha
      muerto la particula que la creo---; solo hay `maxcount` de la entrada a
      la vez, y cada una con el `maxcount` del preset como tope. Con 2
      instancias de 10/s y 0,5 s de vida son 2 x 10 x 0,5 = 10 vivas a los 3 s
      y a los 8 s, cuando las dos particulas que las crearon (nacidas hacia
      0,5 y 1 s, con 6 s de vida) ya han muerto; con 3 de tope, 2 x 3 = 6.
      Sin la regla, o con el hijo atado a la vida del padre, a los 8 s no
      queda nada; sin el tope de instancias, cada nacimiento del padre (uno
      cada 0,5 s) suma 5.
    - El punto de control del hijo no lo mueve: lo coloca el evento, asi que
      un `eventfollow` con su punto 0 lejos sigue pegado a su particula.
    """
    binario = compila_arnes_hijos(tmp)
    if binario is None:
        return []
    padre, hijo = tmp / "padre.psys", tmp / "hijo.psys"
    padre.write_text(PSYS_PADRE)
    hijo.write_text(PSYS_HIJO)
    hijo_punto = tmp / "hijo_punto.psys"
    hijo_punto.write_text(PSYS_HIJO_CON_PUNTO)
    ritmo, ritmo_tope = tmp / "hijo_ritmo.psys", tmp / "hijo_ritmo_tope.psys"
    ritmo.write_text(PSYS_HIJO_RITMO)
    ritmo_tope.write_text(PSYS_HIJO_RITMO_TOPE)

    def mide(modo: int, rafaga: int, escala: float, t: float, h: Path = hijo,
             instancias: int = 4):
        r = subprocess.run([str(binario), str(padre), str(h), str(modo),
                            str(rafaga), str(instancias), str(escala), str(t)],
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
    m = mide(SIGUE, 0, 1.0, 4.0, hijo_punto)
    print(f"  eventfollow  con el punto 0 del hijo en (5000, -5000): "
          f"a {m[2]:.1f} px de su particula")
    if m[1] < 10 or m[2] > 15.0:
        fallos.append(f"eventfollow con el punto 0 del hijo lejos: {m[1]} "
                      f"particulas a {m[2]:.0f} px de la suya; el punto del "
                      f"hijo no debe moverlo")
    # La instancia con `rate`: (modo, psys, instante, lo que dice la regla).
    for modo, h, t, esperado in ((NACE, ritmo, 3.0, 10), (NACE, ritmo, 8.0, 10),
                                 (NACE, ritmo_tope, 8.0, 6),
                                 (MUERE, ritmo, 3.0, 0), (MUERE, ritmo, 9.0, 10)):
        m = mide(modo, 0, 1.0, t, h, instancias=2)
        tipo = "eventspawn" if modo == NACE else "eventdeath"
        print(f"  {tipo:<12} con rate, sin instantaneous, {h.stem}: "
              f"{m[1]} vivas a los {t:g} s (regla: {esperado})")
        if abs(m[1] - esperado) > 1:
            fallos.append(f"{tipo} con rate y sin instantaneous ({h.stem}): "
                          f"{m[1]} vivas a los {t:g} s, la regla de WE da "
                          f"{esperado}")
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
    for (int i = 0; i < nv; i += 1) {
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
    for (int i = 0; i < nv; i += 1, n++)
        for (int k = 0; k < 3; k++)
            m[k] += v[(size_t)i * paso + 11 + k];
    for (int k = 0; k < 3 && n; k++)
        m[k] /= n;
    for (int i = 0; i < nv; i += 1)
        for (int k = 0; k < 3; k++)
            dev = fmax(dev, fabs(v[(size_t)i * paso + 11 + k] - m[k]));
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


ARNES_PUNTO_C = r"""
#include <locale.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "weparticles.h"
/* <psys> <segundos> <x> <y> <z> del puntero <x> <y> <z> esperados: simula con
 * la locale del entorno y el puntero puesto desde el primer paso, y escribe
 * las piezas sin reconocer, cuantas particulas hay y la mayor distancia de
 * una de ellas al sitio esperado. Todo entero en la linea de ordenes, para
 * que `atof` no dependa de la locale que se esta probando. */
int main(int argc, char **argv)
{
    setlocale(LC_ALL, "");
    if (argc < 9) return 2;
    int desconocidas = -1;
    WeParticleSystem *s = we_psys_load(argv[1], &desconocidas);
    if (!s) { printf("-1\n"); return 0; }
    const float p[3] = {(float)atof(argv[3]), (float)atof(argv[4]),
                        (float)atof(argv[5])};
    const double e[3] = {atof(argv[6]), atof(argv[7]), atof(argv[8])};
    we_psys_puntero(s, p);
    int nv = we_psys_update(s, (float)atof(argv[2]));
    const float *v = we_psys_vertices(s);
    int paso = we_psys_floats_por_vertice(s);
    int n = 0;
    double peor = 0.0;
    for (int i = 0; i < nv; i += 1) {
        const float *w = v + (size_t)i * paso;
        double d = sqrt((w[0] - e[0]) * (w[0] - e[0]) + (w[1] - e[1]) * (w[1] - e[1])
                        + (w[2] - e[2]) * (w[2] - e[2]));
        if (d > peor) peor = d;
        n++;
    }
    setlocale(LC_NUMERIC, "C");
    printf("%d %d %.6f\n", desconocidas, n, peor);
    return 0;
}
"""


def preset_punto(cursor: int, controlpoint: int | None) -> dict:
    """Una esfera de radio 0 y sin velocidad en `origin` (10, 20, 0), con el
    punto `cursor` atado al raton y el otro quieto en (0, 0, 0). Cada particula
    nace exactamente en el centro del emisor y se queda ahi 100 s."""
    em = {"name": "sphererandom", "rate": 30, "distancemin": 0,
          "distancemax": 0, "speedmin": 0, "speedmax": 0, "origin": "10 20 0"}
    if controlpoint is not None:
        em["controlpoint"] = controlpoint
    return {
        "maxcount": 200,
        "emitter": [em],
        "controlpoint": [{"id": i, "flags": 1 if i == cursor else 0,
                          "offset": "0 0 0"} for i in (0, 1)],
        "initializer": [{"name": "lifetimerandom", "min": 100, "max": 100}],
        "renderer": [{"name": "sprite"}],
        "material": "x.json",
    }


def prueba_punto_del_emisor(tmp: Path) -> list[str]:
    """El emisor nace en su punto de control mas su `origin`.

    Es la regla que lee `wallpaper64.exe` para la esfera y la caja, lleve el
    emisor `flags: 2` o no; ver NOTAS. Con el puntero en (300, -200, 0), un
    emisor de radio 0 en `origin` (10, 20, 0) tiene que soltar todas sus
    particulas en (310, -180, 0):

    - con el cursor en el punto 0 y sin `controlpoint`, que es el 0;
    - con el cursor en el punto 1 y `controlpoint: 1`, que Python escribe como
      un campo mas al FINAL de la linea `emit`, y solo entonces;
    - y si a ese `.psys` se le quita el campo ---un plan escrito antes---, el
      emisor vuelve al punto 0, que esta quieto, y nacen en (10, 20, 0).

    Las tres con la locale C y con una de coma.
    """
    fallos = []
    casos = []
    for etq, cursor, cp, esperado in (
            ("cursor en el 0, sin controlpoint", 0, None, (310, -180, 0)),
            ("cursor en el 1, controlpoint 1", 1, 1, (310, -180, 0))):
        s = weparticles.cargar(_Resolver(preset_punto(cursor, cp)), "p.json")
        emit = s.emisores[0][1]
        largo = 21 if cp else 20
        if len(emit) != largo or (cp and emit[20] != float(cp)):
            fallos.append(f"{etq}: Python escribe {len(emit)} floats en `emit` "
                          f"({emit[20:]}), se esperaban {largo}")
        psys = tmp / f"punto{cursor}.psys"
        weparticles.escribir(s, psys, 7)
        casos.append((etq, psys, esperado))
    # El mismo `.psys` del punto 1 sin el ultimo campo de `emit`.
    lineas = []
    for l in casos[1][1].read_text().splitlines():
        lineas.append(l.rsplit(" ", 1)[0] if l.startswith("emit ") else l)
    viejo = tmp / "punto1_sin_campo.psys"
    viejo.write_text("\n".join(lineas) + "\n")
    casos.append(("cursor en el 1, sin el campo", viejo, (10, 20, 0)))

    fuente, binario = tmp / "arnes_punto.c", tmp / "arnes_punto"
    fuente.write_text(ARNES_PUNTO_C)
    try:
        subprocess.run(["cc", "-O0", "-std=c11", f"-I{FUENTE_C.parent}",
                        "-o", str(binario), str(fuente), str(FUENTE_C), "-lm"],
                       check=True, capture_output=True)
    except Exception as e:
        if shutil.which("cc") is None:
            print(f"  (sin compilador de C: {e}, prueba omitida)")
            return fallos
        return fallos + [f"el arnes del punto del emisor no compila: {e}"]

    loc = locale_con_coma()
    locales = [("C", "C")] + ([(loc, loc)] if loc else [])
    for etq, psys, esperado in casos:
        for etq_loc, entorno in locales:
            r = subprocess.run([str(binario), str(psys), "2", "300", "-200", "0",
                                *(str(x) for x in esperado)],
                               capture_output=True, text=True,
                               env=dict(os.environ, LC_ALL=entorno))
            c = r.stdout.split()
            if len(c) != 3:
                fallos.append(f"{etq}, LC_ALL={etq_loc}: el arnes no devolvio nada")
                continue
            desc, n, peor = int(c[0]), int(c[1]), float(c[2])
            print(f"  {etq:<34} LC_ALL={etq_loc:<12} {n:3} particulas, "
                  f"a {peor:.6f} como mucho de {esperado}")
            if desc or n < 30 or peor > 1e-3:
                fallos.append(f"{etq}, LC_ALL={etq_loc}: {n} particulas, la mas "
                              f"lejana a {peor:g} de {esperado} ({desc} piezas "
                              f"sin reconocer)")
    return fallos


ARNES_CUERDA_C = r"""
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include "weparticles.h"
/* <psys> <segundos> [0]: simula con la locale del entorno y escribe las piezas sin
 * reconocer, cuantas particulas hay vivas, cuantos vertices salen, y por cada
 * quad de seis el inicio, el fin, los dos controles, `trailLength` y
 * `trailPosition`; ver el layout en `weparticles.h`. Si los seis vertices de
 * un quad no llevan los mismos extremos, lo dice. Con un tercer argumento,
 * antes hace un `update` en el instante 0, que no avanza el reloj. */
int main(int argc, char **argv)
{
    /* Los segundos se leen ANTES de poner la locale: son de la prueba, no del
     * lector, y con la coma `atof("2.37")` daria 2. */
    float segundos = (float)atof(argv[2]);
    setlocale(LC_ALL, "");
    int desconocidas = -1;
    WeParticleSystem *s = we_psys_load(argv[1], &desconocidas);
    if (!s) { printf("-1\n"); return 0; }
    if (argc > 3)
        we_psys_update(s, 0.0f);
    int nv = we_psys_update(s, segundos);
    const float *v = we_psys_vertices(s);
    int paso = we_psys_floats_por_vertice(s);
    setlocale(LC_NUMERIC, "C");
    printf("%d %d %d %d\n", desconocidas, we_psys_cinta(s), we_psys_vivas(s, 0), nv);
    for (int i = 0; i + 6 <= nv; i += 6) {
        const float *w = v + (size_t)i * paso;
        for (int k = 1; k < 6; k++)
            for (int c = 0; c < 24; c++)
                if (w[(size_t)k * paso + c] != w[c])
                    printf("quad %d: el vertice %d no lleva el mismo dato %d\n",
                           i / 6, k, c);
        printf("%.4f %.4f %.4f  %.4f %.4f %.4f  %.4f %.4f %.4f  "
               "%.4f %.4f %.4f  %.1f %.1f\n",
               w[0], w[1], w[2], w[4], w[5], w[6], w[12], w[13], w[14],
               w[16], w[17], w[18], w[7], w[15]);
    }
    return 0;
}
"""


def preset_cuerda(renderer: str) -> dict:
    """Particulas que nacen en el origen a 10/s y se van a 100 px/s hacia +x
    durante 0,55 s: la `x` de cada una es su edad por 100, asi que el orden de
    nacimiento se lee en la posicion. Con `maxcount` 7 el deposito se recorre
    en rueda y los huecos dejan de ir en el orden en que nacieron. El `rope`
    declara `subdivision: 0`: esta prueba es la de la cuerda recta, y sin
    declararlo WE pone 4."""
    return {
        "maxcount": 7,
        "emitter": [{"name": "sphererandom", "rate": 10, "distancemin": 0,
                     "distancemax": 0, "speedmin": 0, "speedmax": 0}],
        "initializer": [{"name": "lifetimerandom", "min": 0.55, "max": 0.55},
                        {"name": "velocityrandom", "min": "100 0 0",
                         "max": "100 0 0"}],
        "renderer": [{"name": renderer}
                     | ({"subdivision": 0} if renderer == "rope" else {})],
        "material": "x.json",
    }


def prueba_cuerda(tmp: Path) -> list[str]:
    """`rope` une las particulas vivas en el orden en que nacieron.

    Es lo que lee `wallpaper64.exe` (NOTAS, «Como cose WE un `rope`»): la lista
    de vivas se anade al nacer y se borra al morir, y el constructor de
    vertices une la `k` con la `k+1`, con la `k-1` y la `k+2` de control y el
    propio extremo de control en las puntas. Con `N` vivas:

    - salen exactamente `6·(N−1)` vertices, uno por quad y segmento;
    - el fin de cada segmento es el inicio del siguiente;
    - el primero empieza en la mas vieja ---la de `x` mayor--- y la `x` baja a
      lo largo de la cuerda aunque los huecos del deposito vayan en rueda;
    - `trailPosition` es `k`, `trailLength` es `N`, y los controles son los
      vecinos, o el propio extremo en las dos puntas.

    Python no guarda cola para el `rope` (`cinta 1 0`), y el `ropetrail` del
    mismo preset la sigue guardando. En la locale C y en una de coma.

    Y un estallido `instantaneous` de 5 que se repite ---el primer `update`
    en el instante 0 no avanza el reloj y el segundo vuelve a estallar en los
    mismos huecos--- no mete dos veces a nadie en la cuerda: 5 vivas, 24
    vertices.
    """
    fallos = []
    s = weparticles.cargar(_Resolver(preset_cuerda("rope")), "p.json")
    t = weparticles.cargar(_Resolver(preset_cuerda("ropetrail")), "p.json")
    if s.cinta != (1, 0, 0.0) or not t.cinta or t.cinta[0] != 2 or t.cinta[1] < 2:
        fallos.append(f"Python: `rope` da {s.cinta} y `ropetrail` {t.cinta}; "
                      f"se esperaba (1, 0, 0.0) y un historial de 2 o mas")
    psys = tmp / "cuerda.psys"
    weparticles.escribir(s, psys, 5)

    fuente, binario = tmp / "arnes_cuerda.c", tmp / "arnes_cuerda"
    fuente.write_text(ARNES_CUERDA_C)
    try:
        subprocess.run(["cc", "-O0", "-std=c11", f"-I{FUENTE_C.parent}",
                        "-o", str(binario), str(fuente), str(FUENTE_C), "-lm"],
                       check=True, capture_output=True)
    except Exception as e:
        if shutil.which("cc") is None:
            print(f"  (sin compilador de C: {e}, prueba omitida)")
            return fallos
        return fallos + [f"el arnes de la cuerda no compila: {e}"]

    loc = locale_con_coma()
    locales = [("C", "C")] + ([(loc, loc)] if loc else [])
    for segundos in ("2", "2.37"):
        for etq, entorno in locales:
            donde = f"{segundos} s, LC_ALL={etq}"
            r = subprocess.run([str(binario), str(psys), segundos],
                               capture_output=True, text=True,
                               env=dict(os.environ, LC_ALL=entorno))
            lineas = r.stdout.splitlines()
            cab = lineas[0].split() if lineas else []
            if len(cab) != 4:
                fallos.append(f"{donde}: el arnes no devolvio nada")
                continue
            desc, cinta, vivas, nv = (int(x) for x in cab)
            quads = [[float(x) for x in l.split()] for l in lineas[1:]
                     if not l.startswith("quad")]
            raros = [l for l in lineas[1:] if l.startswith("quad")]
            xs = [q[0] for q in quads] + ([quads[-1][3]] if quads else [])
            print(f"  {donde:<26} {vivas} vivas, {nv} vertices, x a lo largo: "
                  + " ".join(f"{x:.0f}" for x in xs))
            if desc or cinta != 1 or vivas < 3:
                fallos.append(f"{donde}: cinta {cinta}, {vivas} vivas, {desc} "
                              f"piezas sin reconocer")
                continue
            if nv != 6 * (vivas - 1) or len(quads) != vivas - 1 or raros:
                fallos.append(f"{donde}: {nv} vertices con {vivas} vivas; una "
                              f"cuerda da {6 * (vivas - 1)}"
                              + (f" ({raros[0]})" if raros else ""))
                continue
            for k, q in enumerate(quads):
                ini, fin, c0, c1 = q[0:3], q[3:6], q[6:9], q[9:12]
                ant = quads[k - 1][0:3] if k else ini
                sig = quads[k + 1][3:6] if k + 1 < len(quads) else fin
                if k + 1 < len(quads) and fin != quads[k + 1][0:3]:
                    fallos.append(f"{donde}: el segmento {k} acaba en {fin} y el "
                                  f"{k + 1} empieza en {quads[k + 1][0:3]}")
                if not ini[0] > fin[0]:
                    fallos.append(f"{donde}: el segmento {k} va de x={ini[0]} a "
                                  f"x={fin[0]}; la cuerda tiene que ir de la mas "
                                  f"vieja a la mas nueva")
                if c0 != ant or c1 != sig:
                    fallos.append(f"{donde}: controles del segmento {k} {c0} "
                                  f"{c1}, se esperaba {ant} {sig}")
                if q[12] != vivas or q[13] != k:
                    fallos.append(f"{donde}: segmento {k} con trailLength "
                                  f"{q[12]} y trailPosition {q[13]}")
            # La mas vieja tiene 0,55 s como mucho; la mas nueva, 0,1.
            if not (45 <= xs[0] <= 55 and xs[-1] <= 10):
                fallos.append(f"{donde}: la cuerda va de x={xs[0]} a x={xs[-1]}; "
                              f"se esperaba de unos 50 a menos de 10")

    estallido = preset_cuerda("rope")
    estallido["maxcount"] = 12
    estallido["emitter"][0].update(rate=0, instantaneous=5)
    estallido["initializer"][0].update(min=100, max=100)
    s = weparticles.cargar(_Resolver(estallido), "p.json")
    psys = tmp / "cuerda_estallido.psys"
    weparticles.escribir(s, psys, 5)
    r = subprocess.run([str(binario), str(psys), "0.5", "0"],
                       capture_output=True, text=True,
                       env=dict(os.environ, LC_ALL="C"))
    cab = (r.stdout.splitlines() or [""])[0].split()
    print(f"  estallido repetido         {cab[2] if len(cab) == 4 else '?'} vivas, "
          f"{cab[3] if len(cab) == 4 else '?'} vertices")
    if len(cab) != 4 or (int(cab[2]), int(cab[3])) != (5, 24):
        fallos.append(f"estallido `instantaneous` repetido: {cab}; una cuerda "
                      f"de 5 vivas da 24 vertices")
    return fallos


ARNES_VERTICES_C = r"""
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include "weparticles.h"
/* <psys> <segundos>: simula con la locale del entorno y escribe las piezas sin
 * reconocer, la cinta, las vivas y los vertices, y despues cada vertice
 * entero, sus 26 floats, con nueve cifras: lo justo para comparar numero a
 * numero. */
int main(int argc, char **argv)
{
    (void)argc;
    float segundos = (float)atof(argv[2]);
    setlocale(LC_ALL, "");
    int desconocidas = -1;
    WeParticleSystem *s = we_psys_load(argv[1], &desconocidas);
    if (!s) { printf("-1\n"); return 0; }
    int nv = we_psys_update(s, segundos);
    const float *v = we_psys_vertices(s);
    int paso = we_psys_floats_por_vertice(s);
    setlocale(LC_NUMERIC, "C");
    printf("%d %d %d %d\n", desconocidas, we_psys_cinta(s), we_psys_vivas(s, 0), nv);
    for (int i = 0; i < nv; i++) {
        for (int c = 0; c < paso; c++)
            printf("%s%.9g", c ? " " : "", v[(size_t)i * paso + c]);
        printf("\n");
    }
    return 0;
}
"""


def preset_zigzag(subdivision: int | None) -> dict:
    """Un `rope` de cuatro vivas que no estan en linea: nacen a 10/s en un
    anillo de 20 a 60 px alrededor del origen ---en el plano, `directions`
    `1 1 0`--- y se van a 100 px/s hacia +x durante 0,4 s, cada una con su
    tamano y su color. A los 2,05 s quedan cuatro, y la cuerda que las une va
    en zigzag. `subdivision` None no la declara."""
    rope = {"name": "rope"}
    if subdivision is not None:
        rope["subdivision"] = subdivision
    return {
        "maxcount": 8,
        "emitter": [{"name": "sphererandom", "rate": 10, "distancemin": 20,
                     "distancemax": 60, "speedmin": 0, "speedmax": 0}],
        "initializer": [{"name": "lifetimerandom", "min": 0.4, "max": 0.4},
                        {"name": "velocityrandom", "min": "100 0 0",
                         "max": "100 0 0"},
                        {"name": "sizerandom", "min": 5, "max": 25},
                        {"name": "colorrandom", "min": "0 0 0",
                         "max": "255 255 255"}],
        "renderer": [rope],
        "material": "x.json",
    }


def _vertices(binario: Path, psys: Path, segundos: str, loc: str):
    """`(cabecera, vertices)` del arnes, o `(None, salida)` si no dio nada."""
    r = subprocess.run([str(binario), str(psys), segundos],
                       capture_output=True, text=True,
                       env=dict(os.environ, LC_ALL=loc))
    lineas = r.stdout.splitlines()
    cab = lineas[0].split() if lineas else []
    if len(cab) != 4:
        return None, r.stdout + r.stderr
    return [int(x) for x in cab], [[float(x) for x in l.split()]
                                   for l in lineas[1:]]


def prueba_subdivision(tmp: Path) -> list[str]:
    """La curva de un `rope`: la Bezier de `genericropeparticle.geom`.

    Con `subdivision: 3` y `N` vivas salen `4·(N−1)` quads, cuatro por tramo.
    Los puntos de dentro del tramo `k`, de la viva `A` a la `B` con los
    controles `C0` y `C3` de siempre, se comparan con lo que el `.geom` evalua
    en Python, a menos de 1e-3, con `s = smoothstep(0, 1, j/4)`:

    - el punto, `cubicBezier(A, A + 0.15·(B − C0), B + 0.15·(A − C3), B, s)`;
    - el ancho que da el vertice sin geometry shader con esos controles y ese
      tamano ---`normalize(cross(ojo, fin − control0))·tamano` en el inicio y
      `normalize(cross(ojo, control1 − inicio))·tamano` en el fin, con el ojo
      en Z---, contra el `mix(Ra, Rb, s)` del `.geom`;
    - el color, `mix`, y la UV que sale de `trailLength`/`trailPosition`,
      contra `mix(uvMin, uvMax, s)`.

    Las vivas `A`, `B` son las de la misma simulacion con `subdivision: 0`, que
    no cambia mas que la geometria. Y con `subdivision: 0` la cuerda sale
    numero a numero igual que con la linea `cinta 1 0 0` de antes, la que un
    `.so` anterior lee sin cuarto numero: `6·(N−1)` vertices. Sin declarar,
    Python pone el 4 de WE, y `100` se queda en 32. En la locale C y en una de
    coma.
    """
    fallos = []
    for decl, quiere in ((3, 3), (0, 0), (None, 4), (100, 32), (-2, 0),
                         (2.9, 2)):
        s = weparticles.cargar(_Resolver(preset_zigzag(decl)), "p.json")
        if s.subdivision != quiere:
            fallos.append(f"Python: `subdivision: {decl}` da {s.subdivision}, "
                          f"WE lo deja en {quiere}")
    psys = {}
    for sub in (3, 0):
        s = weparticles.cargar(_Resolver(preset_zigzag(sub)), "p.json")
        psys[sub] = tmp / f"zigzag{sub}.psys"
        weparticles.escribir(s, psys[sub], 5)
    texto = psys[0].read_text()
    if "\ncinta 1 0 0 0\n" not in texto or "\ncinta 1 0 0 3\n" not in psys[3].read_text():
        fallos.append("la linea `cinta` del `rope` no lleva la subdivision al final")
    psys["antes"] = tmp / "zigzag_antes.psys"
    psys["antes"].write_text(texto.replace("\ncinta 1 0 0 0\n", "\ncinta 1 0 0\n"))

    fuente, binario = tmp / "arnes_vertices.c", tmp / "arnes_vertices"
    fuente.write_text(ARNES_VERTICES_C)
    try:
        subprocess.run(["cc", "-O0", "-std=c11", f"-I{FUENTE_C.parent}",
                        "-o", str(binario), str(fuente), str(FUENTE_C), "-lm"],
                       check=True, capture_output=True)
    except Exception as e:
        if shutil.which("cc") is None:
            print(f"  (sin compilador de C: {e}, prueba omitida)")
            return fallos
        return fallos + [f"el arnes de vertices no compila: {e}"]

    def resta(a, b): return [x - y for x, y in zip(a, b)]
    def suma(a, b): return [x + y for x, y in zip(a, b)]
    def por(a, k): return [x * k for x in a]
    def mezcla(a, b, s): return [x + (y - x) * s for x, y in zip(a, b)]
    def dist(a, b): return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
    def ancho(d, tam):
        # cross((0, 0, 1), d), normalizado y por el tamano
        r = [-d[1], d[0], 0.0]
        n = math.sqrt(r[0] ** 2 + r[1] ** 2)
        return [x / n * tam for x in r] if n > 0 else [math.nan] * 3
    def bezier(a, b, c, d, t):
        u = 1.0 - t
        return [u**3 * p + 3*t*u*u * q + 3*t*t*u * r + t**3 * w
                for p, q, r, w in zip(a, b, c, d)]

    loc = locale_con_coma()
    locales = [("C", "C")] + ([(loc, loc)] if loc else [])
    segundos = "2.05"
    for etq, entorno in locales:
        donde = f"LC_ALL={etq}"
        cab0, v0 = _vertices(binario, psys[0], segundos, entorno)
        cabv, vv = _vertices(binario, psys["antes"], segundos, entorno)
        cab3, v3 = _vertices(binario, psys[3], segundos, entorno)
        if cab0 is None or cab3 is None or cabv is None:
            fallos.append(f"{donde}: el arnes no devolvio nada")
            continue
        n = cab0[2]
        # ── subdivision 0: la cuerda recta, numero a numero ──
        print(f"  {donde:<20} {n} vivas; subdivision 0: {cab0[3]} vertices, "
              f"{'iguales' if (cab0, v0) == (cabv, vv) else 'DISTINTOS'} a "
              f"`cinta 1 0 0`; subdivision 3: {cab3[3]} vertices")
        if n != 4 or cab0[1] != 1 or cab0[0]:
            fallos.append(f"{donde}: cinta {cab0[1]}, {n} vivas, {cab0[0]} "
                          f"piezas sin reconocer; se esperaba un `rope` de 4")
            continue
        if cab0[3] != 6 * (n - 1) or (cab0, v0) != (cabv, vv):
            fallos.append(f"{donde}: con subdivision 0, {cab0[3]} vertices y "
                          f"{'iguales' if v0 == vv else 'distintos'} a "
                          f"`cinta 1 0 0`; se esperaban {6 * (n - 1)} e iguales")
        # ── subdivision 3: la Bezier del `.geom` ──
        if cab3[2] != n or cab3[3] != 6 * 4 * (n - 1):
            fallos.append(f"{donde}: con subdivision 3, {cab3[2]} vivas y "
                          f"{cab3[3]} vertices; se esperaban {n} y "
                          f"{24 * (n - 1)}")
            continue
        q0 = [v0[i][:24] for i in range(0, len(v0), 6)]
        q3 = [v3[i][:24] for i in range(0, len(v3), 6)]
        if any(v3[i][:24] != q3[i // 6] for i in range(len(v3))):
            fallos.append(f"{donde}: un quad no lleva el mismo dato en sus "
                          f"seis vertices")
        # Las vivas, en orden, con su tamano y su color: [x y z tam r g b a].
        vivas = [q[0:4] + q[8:12] for q in q0] + [q0[-1][4:7] + q0[-1][19:24]]
        peor = {"punto": 0.0, "ancho": 0.0, "color": 0.0, "uv": 0.0}
        for k in range(n - 1):
            A, B = vivas[k], vivas[k + 1]
            C0 = vivas[k - 1] if k else A
            C3 = vivas[k + 2] if k + 2 < n else B
            Ra = ancho(resta(B[:3], C0[:3]), A[3])
            Rb = ancho(resta(C3[:3], A[:3]), B[3])
            ctl1 = suma(A[:3], por(resta(B[:3], C0[:3]), 0.15))
            ctl2 = suma(B[:3], por(resta(A[:3], C3[:3]), 0.15))
            uv_min = 1.0 - k / (n - 1)
            uv_max = uv_min - 1.0 / (n - 1)
            for j in range(5):
                s = (j / 4) ** 2 * (3 - 2 * (j / 4))
                M = bezier(A[:3], ctl1, ctl2, B[:3], s)
                R = mezcla(Ra, Rb, s)
                col = mezcla(A[4:8], B[4:8], s)
                uv = mezcla([uv_min], [uv_max], s)[0]
                # El punto `j` es el inicio del subquad `j` y el fin del `j-1`.
                lados = []
                if j < 4:
                    q = q3[4 * k + j]
                    ini, fin, c0, c1 = q[0:3], q[4:7], q[12:15], q[16:19]
                    largo, pos = q[7], q[15]
                    lados.append((ini, ancho(resta(fin, c0), q[3]), q[8:12],
                                  1.0 - pos / (largo - 1)))
                if j > 0:
                    q = q3[4 * k + j - 1]
                    ini, fin, c0, c1 = q[0:3], q[4:7], q[12:15], q[16:19]
                    largo, pos = q[7], q[15]
                    lados.append((fin, ancho(resta(c1, ini), q[19]), q[20:24],
                                  1.0 - (pos + 1) / (largo - 1)))
                for p, r, c, u in lados:
                    peor["punto"] = max(peor["punto"], dist(p, M))
                    peor["ancho"] = max(peor["ancho"], dist(r, R))
                    peor["color"] = max(peor["color"], dist(c, col))
                    peor["uv"] = max(peor["uv"], abs(u - uv))
        print(f"  {'':<20} contra el .geom, lo peor: punto "
              f"{peor['punto']:.2e}, ancho {peor['ancho']:.2e}, color "
              f"{peor['color']:.2e}, UV {peor['uv']:.2e}")
        for que, d in peor.items():
            if not d < 1e-3:
                fallos.append(f"{donde}: con subdivision 3 el {que} se aparta "
                              f"{d:.3g} de lo que dibuja el .geom")
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
    """La marca del cursor, de `weparticles.py` a `we_psys_puntero`, y la regla
    de `controlpointattract` leida en wallpaper64.exe.

    La marca es un contrato de dos piezas y ninguna falla sola: si no viaja en
    la linea `cp`, o el simulador no la mira, el punto se queda en el origen
    del sistema y el puntero no hace nada.

    La regla (0x140241554): el operador solo actua a menos de `threshold` del
    punto, y la `scale` negativa EMPUJA. Con el puntero en mitad de la nube,
    la de -500 tiene que vaciar el circulo de alrededor y dejar el resto donde
    estaba; la de +500 tiene que apretarlo hacia el centro. El hueco se mide a
    48 px y no a 64: la fuerza cae a cero en el borde, asi que con `drag` las
    empujadas frenan justo antes de los 64 y se quedan en el anillo. Antes
    era al reves: la negativa atraia, desde fuera del circulo, y la nube
    entera se iba al puntero.
    """
    binario = compila_arnes(tmp)
    if binario is None:
        return []

    punto = (100.0, -50.0)
    fallos = []

    def mide(escala: str, usar: bool, radio: float):
        psys = tmp / f"cursor{escala}.psys"
        psys.write_text(PSYS_CURSOR.replace("@ESCALA@", escala))
        r = subprocess.run([str(binario), str(psys), "10", f"{punto[0]}",
                            f"{punto[1]}", "0", "1" if usar else "0",
                            f"{radio}"], capture_output=True, text=True)
        campos = r.stdout.split()
        if len(campos) != 5:
            return None
        return int(campos[1]), float(campos[2]), float(campos[3]), int(campos[4])

    sin = mide("-500", False, 48)
    con = mide("-500", True, 48)
    nucleo_sin = mide("500", False, 16)
    nucleo_con = mide("500", True, 16)
    if None in (sin, con, nucleo_sin, nucleo_con):
        return ["el arnes no devolvio la nube"]

    if not con[0]:
        fallos.append("la marca del cursor no llega al C: `we_psys_cursor` "
                      "dice que no hay ningun punto atado al puntero")
    print(f"  scale -500: a menos de 48 px del puntero {sin[3]} sin el, "
          f"{con[3]} con el")
    print(f"  scale +500: a menos de 16 px del puntero {nucleo_sin[3]} sin el, "
          f"{nucleo_con[3]} con el")
    print(f"  scale -500: centro de la nube ({sin[1]:.0f}, {sin[2]:.0f}) sin "
          f"puntero, ({con[1]:.0f}, {con[2]:.0f}) con el")
    if sin[3] < 20:
        fallos.append(f"sin puntero solo hay {sin[3]} particulas cerca del "
                      "punto: la prueba no tiene que contar")
    if con[3] * 4 > sin[3]:
        fallos.append(f"con scale -500 quedan {con[3]} de {sin[3]} particulas "
                      "a menos de 48 px del puntero: no las aparta")
    if nucleo_con[3] < 2 * nucleo_sin[3]:
        fallos.append(f"con scale +500 hay {nucleo_con[3]} particulas a menos de "
                      f"16 px del puntero, y sin el {nucleo_sin[3]}: no las atrae")
    # Fuera del umbral no actua: la nube de 512 px no se mueve hacia el puntero.
    if math.dist(con[1:3], sin[1:3]) > 20.0:
        fallos.append("con scale -500 el centro de la nube se mueve "
                      f"{math.dist(con[1:3], sin[1:3]):.0f} px: el operador "
                      "actua fuera de `threshold`")
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

    # ── 10. el emisor nace en su punto de control ──
    print("\n── el punto de control del emisor ──")
    fallos += prueba_punto_del_emisor(tmp)

    # ── 11. `rope` une las particulas vivas ──
    print("\n── la cuerda de `rope` ──")
    fallos += prueba_cuerda(tmp)

    # ── 12. la curva del `rope` ──
    print("\n── la curva de `rope` (subdivision) ──")
    fallos += prueba_subdivision(tmp)

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
            # Cada emisor son 20 floats fijos, y un 21 con el punto de
            # control solo si no es el 0; ver `we_psys_load`.
            for _, emit in s.emisores:
                if len(emit) != 20 and not (len(emit) == 21
                                            and emit[20] in range(1, 8)):
                    fallos.append(f"{d.name}: emit emite {len(emit)} floats "
                                  f"({emit[20:]}), el C espera 20, o 21 con "
                                  f"un punto de control de 1 a 7")
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
