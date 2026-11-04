#!/usr/bin/env python3
"""El contrato de una capa que gira con la hora: las agujas de un reloj.

Se reparte en tres, como un reloj de texto: `wescript.py` reduce el script de
`angles` a `z = A · frac(B · tod) + C` en grados (`giro_por_hora`),
`werender.py` lo escribe detrás del `object` de la capa (la línea `giro`), y
`src/wegiro.c` evalúa la forma con la hora y gira la colocación ---en los DOS
ejecutores---. Esta prueba compila ese módulo desde `src/` y comprueba, con
las tres líneas `giro` del plan de `2396319149` (las agujas 362, 368 y 371):

  1. Que `we_giro_grados` da lo mismo que `wescript.grados_del_giro` con la
     forma que dedujo Python, a 1e-4 grados, en más de 100 `tod` por aguja
     ---entre ellos 0, 0,5, cambios de minuto y de hora y 0,999999---, leyendo
     la línea en `C` y en `es_ES.UTF-8`, donde `strtod("0.5")` sin guarda da 0.
     Como las tres solo llevan enteros, también una línea sintética con
     decimales en los cinco campos, que sin la guarda se leería mal.
  2. Que `we_giro_coloca`, sobre la colocación que `object_mvp` hornea con el
     `value` guardado, da la misma matriz que `object_mvp` con el ángulo de la
     hora puesto en `angles`, en radianes, a 1e-6: unidades, signo y eje. Las
     dos giran en píxeles del lienzo, y el ejecutor lo saca de la propia línea
     `giro`, así que se prueba con la línea del lienzo de la escena y con la
     misma línea reescrita para otro 16:9 de 1920x1080 y uno cuadrado; la
     línea con decimales, sobre una capa sintética no cuadrada que ya trae su
     ángulo `base`, donde girar en clip en vez de en píxeles da otra matriz.
  3. Que eso vale también con el plan emitido con `resolucion`, como el de
     `wectl` en vivo: a 1920x1200 y a 1366x768 la línea `canvas` dice la
     resolución de dibujo redondeada (2133x1200, 1366x768), cuya proporción
     no es la del lienzo. Se toman las líneas `object` y `giro` del plan tal
     cual, como los ejecutores, y el giro tiene que quedar a 1e-6 de
     `object_mvp` en el lienzo de la ESCENA. Para que el caso discrimine, el
     giro con la proporción de `canvas` tiene que separarse más de 1e-6.
  4. Que `we_hora_del_dia` es la hora local como fracción del día, con su
     fracción de segundo, con `TZ=UTC` y con `TZ=Etc/GMT-2`.
  5. Que `tools/glexec.c` y `src/glexecutor.cpp` llaman los dos a
     `we_giro_linea`, `we_giro_grados` y `we_giro_coloca`.

Y el vaivén, un `angles` o un `origin` que oscila con `engine.runtime`
(`wescript.vaiven_de`, la línea `vaiven`, `we_vaiven_*` en el mismo módulo),
con las dos líneas `vaiven` de los planes de `3050043876` (capa 338,
`angles`) y `3521337568` (capa 222, `origin`):

  6. Que `we_vaiven_valor` da lo mismo que `wescript.valor_del_vaiven` con la
     forma deducida, y que el propio script evaluado por el intérprete, a
     1e-5, en 1201 tiempos de [0, 600] s, leyendo la línea en `C` y en
     `es_ES.UTF-8`; también una sintética con decimales en todos los campos.
  7. Que `we_vaiven_coloca`, sobre la colocación que `object_mvp` hornea con
     el `value`, da la de `object_mvp` con el valor de ese instante puesto en
     el campo, a 1e-6: el giro en píxeles del lienzo en `angles`, y en
     `origin` la traslación, con el signo de y del lienzo. Las dos con el
     parallax de cámara en reposo de la escena (`parallax_de_camara`), que
     sale del `origin` y en `3521337568` hace que la capa se mueva 1,025
     veces el vaivén. Para que el caso discrimine, la misma línea con los
     ejes sin ese 1 + k tiene que separarse más de 1e-6.
  8. Que una línea con `@TIME@` sin poner se lee igual, sin tiempo, y que
     los dos ejecutores llaman a `we_vaiven_linea` y `we_vaiven_coloca`.

Uso:
    python3 tools/test_giro.py
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pkg_inspect
import wepaths
import werender
import wescript

RAIZ = Path(__file__).resolve().parent.parent
ESCENA = "2396319149"
AGUJAS = (362, 368, 371)
TOL_GRADOS = 1e-4
TOL_MATRIZ = 1e-6
# Lienzos donde se compara con `object_mvp`: el de la escena se añade delante.
LIENZOS = ((1920, 1080), (1000, 1000))
# Resoluciones de dibujo con las que se emite el plan, como lo emite `wectl`.
RESOLUCIONES = ((1920, 1200), (1366, 768))

ARNES = r"""
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wegiro.h"

/* argv[1]: `-` para ver qué lee `strtod` de `0.5` en la locale de argv[2];
 * `hora` para pasar instantes `<segundos> <nanosegundos>` a fracción del día;
 * si no, un fichero con la línea `giro` del plan, que se LEE en la locale de
 * argv[2]. Por la entrada, `<tod> <m0> <m1> <m4> <m5>`; por la salida, una
 * primera línea con el lienzo que se leyó y después los grados y la parte
 * lineal girada. */
/* `vaiven <fichero> <locale>`: la línea `vaiven` del fichero se LEE en esa
 * locale. Sale una primera línea con lo leído y, por cada petición
 * `<t> <m0> <m1> <m3> <m4> <m5> <m7>`, el valor y esas seis de la colocación
 * después de `we_vaiven_coloca`. */
static int vaiven(const char *fichero, const char *loc)
{
    if (!setlocale(LC_ALL, loc))
        return 4;
    FILE *f = fopen(fichero, "r");
    if (!f) return 2;
    char linea[1024];
    if (!fgets(linea, sizeof linea, f)) return 2;
    fclose(f);
    WeVaiven v;
    if (!we_vaiven_linea(&v, linea + 6)) {
        printf("no la lee\n");
        return 3;
    }
    setlocale(LC_ALL, "C");
    printf("leida %d %.17g %.17g %.17g %.17g %.17g %d %.17g %.17g %.17g\n",
           v.angulo, v.k, v.a, v.w, v.fase, v.base, v.con_tiempo, v.t,
           v.p[0], v.p[1]);
    char pet[512];
    while (fgets(pet, sizeof pet, stdin)) {
        double t;
        float m[16] = {0};
        if (sscanf(pet, "%lf %f %f %f %f %f %f", &t, m + 0, m + 1, m + 3,
                   m + 4, m + 5, m + 7) != 7)
            continue;
        const double valor = we_vaiven_valor(&v, t);
        we_vaiven_coloca(&v, t, m);
        printf("%.17g %.9g %.9g %.9g %.9g %.9g %.9g\n", valor, m[0], m[1],
               m[3], m[4], m[5], m[7]);
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc > 3 && strcmp(argv[1], "vaiven") == 0)
        return vaiven(argv[2], argv[3]);
    if (argc > 2 && !setlocale(LC_ALL, argv[2]))
        return 4;
    if (strcmp(argv[1], "-") == 0) {
        printf("%g\n", strtod("0.5", NULL));
        return 0;
    }
    char pet[256];
    if (strcmp(argv[1], "hora") == 0) {
        while (fgets(pet, sizeof pet, stdin)) {
            long long s = 0, ns = 0;
            if (sscanf(pet, "%lld %lld", &s, &ns) == 2)
                printf("%.17g\n", we_hora_del_dia((time_t)s, (long)ns));
        }
        return 0;
    }
    FILE *f = fopen(argv[1], "r");
    if (!f) return 2;
    char linea[1024];
    if (!fgets(linea, sizeof linea, f)) return 2;
    fclose(f);
    const char *p = linea;
    while (*p && *p != ' ') p++;           /* fuera `giro` */
    WeGiro g;
    if (!we_giro_linea(&g, p)) {
        printf("no la lee\n");
        return 3;
    }
    /* Para leer las peticiones y escribir se vuelve a la locale C: si no, el
     * arnés leería y escribiría con coma y fallaría la prueba, no el módulo. */
    setlocale(LC_ALL, "C");
    printf("lienzo %d %d\n", g.ancho, g.alto);
    while (fgets(pet, sizeof pet, stdin)) {
        double tod;
        float m[16] = {0};
        if (sscanf(pet, "%lf %f %f %f %f", &tod, m + 0, m + 1, m + 4, m + 5) != 5)
            continue;
        const double grados = we_giro_grados(&g, tod);
        we_giro_coloca(&g, grados, m);
        printf("%.17g %.9g %.9g %.9g %.9g\n", grados, m[0], m[1], m[4], m[5]);
    }
    return 0;
}
"""


def compila(tmp: Path) -> Path:
    src = tmp / "arnes.c"
    src.write_text(ARNES)
    exe = tmp / "arnes"
    r = subprocess.run(
        ["cc", "-O1", "-std=c11", "-Wall", "-Wextra", f"-I{RAIZ}/src",
         "-o", str(exe), str(src), str(RAIZ / "src" / "wegiro.c"), "-lm"],
        capture_output=True, text=True)
    if r.returncode or r.stderr.strip():
        raise SystemExit("no compila el arnés sin avisos:\n" + r.stderr)
    return exe


def tods() -> list[float]:
    """150 en rejilla, y a cada lado de unos cuantos cambios de minuto y de
    hora, más 0, 0,5 y 0,999999."""
    t = {k / 150.0 for k in range(150)}
    for m in (1, 59, 60, 61, 719, 720, 721, 1439):
        for d in (-1e-8, 0.0, 1e-8):
            t.add(m / 1440.0 + d)
    t.update({0.0, 0.5, 0.999999})
    return sorted(t)


class _Capa:
    """Lo que `object_mvp` mira de un objeto: el `raw` y sus pases."""

    def __init__(self, raw: dict):
        self.raw = raw
        self.passes = []


def con_lienzo(linea: str, lienzo: tuple[int, int]) -> str:
    """La línea `giro` con otro lienzo de escena: los dos últimos campos."""
    return " ".join(linea.split()[:-2] + [str(lienzo[0]), str(lienzo[1])])


def _compara(exe: Path, tmp: Path, linea: str, lienzo: tuple[int, int],
             base: list[float], nombre: str, grados_py, raw_girada) -> list[str]:
    """Pasa por el arnés la línea `giro` y la colocación `base`, en `C` y en
    `es_ES.UTF-8`, y compara cada `tod` con lo que da Python: el lienzo leído
    con `lienzo`, los grados con `grados_py(tod)` y la matriz con `object_mvp`
    de `raw_girada(grados)` en `lienzo`."""
    fallos = []
    ts = tods()
    (tmp / "giro.txt").write_text(linea + "\n")
    entrada = "".join(f"{t!r} {base[0]!r} {base[1]!r} {base[4]!r} {base[5]!r}\n"
                      for t in ts)
    for locale in ("C", "es_ES.UTF-8"):
        r = subprocess.run([str(exe), str(tmp / "giro.txt"), locale],
                           input=entrada, capture_output=True, text=True)
        salida = r.stdout.splitlines()
        leido = salida[0] if salida else ""
        peor_g = peor_m = 1.0
        if (not r.returncode and len(salida) == len(ts) + 1
                and leido == f"lienzo {lienzo[0]} {lienzo[1]}"):
            peor_g = peor_m = 0.0
            for t, l in zip(ts, salida[1:]):
                g, *m = (float(x) for x in l.split())
                peor_g = max(peor_g, abs(g - grados_py(t)))
                esp = werender.object_mvp(_Capa(raw_girada(g)), lienzo)
                peor_m = max(peor_m, max(abs(a - b) for a, b in
                                         zip(m, (esp[0], esp[1], esp[4], esp[5]))))
        ok = len(ts) >= 100 and peor_g <= TOL_GRADOS and peor_m <= TOL_MATRIZ
        lz = f"{lienzo[0]}x{lienzo[1]}"
        print(f"  {'ok' if ok else 'MAL':3} {nombre} {lz:9} [{locale:11}] {len(ts)} tod, "
              f"{leido or '-'}: grados a {peor_g:.3g} de Python, matriz a "
              f"{peor_m:.3g} de object_mvp")
        if not ok:
            fallos.append(f"{nombre} {lz} [{locale}]: {leido or '-'}, grados "
                          f"{peor_g:.3g}, matriz {peor_m:.3g}")
    return fallos


def gira_en_pixeles(m: list[float], grados: float, aspecto: float) -> list[float]:
    """D · R(grados) · D⁻¹ sobre la 2x2 (m0, m1, m4, m5), con D = diag(2/w, 2/h)
    de proporción `aspecto`: la cuenta de `we_giro_coloca`, en Python, para
    ver cuánto se separa con otra proporción."""
    a = math.radians(grados)
    c, s, k = math.cos(a), math.sin(a), aspecto
    return [c * m[0] - s * m[2] / k, c * m[1] - s * m[3] / k,
            s * k * m[0] + c * m[2], s * k * m[1] + c * m[3]]


# Las capas con vaivén del corpus: escena, capa y campo.
VAIVENES = (("3050043876", 338, "angles"), ("3521337568", 222, "origin"))
TOL_VAIVEN = 1e-5


def tiempos() -> list[float]:
    """1201 `runtime` en [0, 600] s, uno cada medio segundo."""
    return [k * 0.5 for k in range(1201)]


def quieta(raw: dict) -> dict:
    """La capa con cada campo con script cambiado por su `value`: lo que
    hornea el plan."""
    return {k: (v["value"] if isinstance(v, dict) and "script" in v else v)
            for k, v in raw.items()}


def con_paralaje(raw: dict, general: dict, lienzo) -> dict:
    """La capa con el parallax de cámara en reposo de la escena puesto, como
    lo pone `werender` al cargarla: sale de su `origin`."""
    from types import SimpleNamespace
    werender.parallax_de_camara(SimpleNamespace(
        general=general, properties={}, objects=[_Capa(raw)]), lienzo)
    return raw


def con_valor(raw: dict, campo: str, i: int, valor: float) -> dict:
    """La capa quieta con la componente `i` de `campo` puesta a `valor`, en
    las unidades del script (grados en `angles`, pasados a radianes)."""
    q = quieta(raw)
    v = [float(x) for x in str(q[campo]).split()]
    v = (v + [0.0, 0.0, 0.0])[:3]
    v[i] = math.radians(valor) if campo == "angles" else valor
    q[campo] = " ".join(repr(x) for x in v)
    return q


def _compara_vaiven(exe: Path, tmp: Path, linea: str, lienzo, base, nombre,
                    valor_py, valor_script, raw_en) -> list[str]:
    """Pasa por el arnés la línea `vaiven` y la colocación `base` en `C` y en
    `es_ES.UTF-8`; compara el valor con `valor_py(t)` y `valor_script(t)` y
    la colocación con `object_mvp` de `raw_en(valor)`."""
    fallos = []
    ts = tiempos()
    (tmp / "vaiven.txt").write_text(linea + "\n")
    idx = (0, 1, 3, 4, 5, 7)
    entrada = "".join(f"{t!r} " + " ".join(repr(base[i]) for i in idx) + "\n"
                      for t in ts)
    for locale in ("C", "es_ES.UTF-8"):
        r = subprocess.run([str(exe), "vaiven", str(tmp / "vaiven.txt"), locale],
                           input=entrada, capture_output=True, text=True)
        salida = r.stdout.splitlines()
        peor_py = peor_js = peor_m = 1.0
        if not r.returncode and len(salida) == len(ts) + 1:
            peor_py = peor_js = peor_m = 0.0
            for t, l in zip(ts, salida[1:]):
                v, *m = (float(x) for x in l.split())
                peor_py = max(peor_py, abs(v - valor_py(t)))
                if valor_script is not None:
                    peor_js = max(peor_js, abs(v - valor_script(t)))
                esp = werender.object_mvp(_Capa(raw_en(v)), lienzo)
                peor_m = max(peor_m, max(abs(a - esp[i]) for a, i in zip(m, idx)))
        ok = (len(ts) >= 1000 and peor_py <= TOL_VAIVEN and peor_js <= TOL_VAIVEN
              and peor_m <= TOL_MATRIZ)
        print(f"  {'ok' if ok else 'MAL':3} {nombre} [{locale:11}] {len(ts)} t: "
              f"valor a {peor_py:.3g} de Python y "
              + (f"a {peor_js:.3g} del script, " if valor_script else "sin script, ")
              + f"matriz a {peor_m:.3g} de object_mvp")
        if not ok:
            fallos.append(f"vaiven {nombre} [{locale}]: {salida[:1]}, valor "
                          f"{peor_py:.3g}/{peor_js:.3g}, matriz {peor_m:.3g}")
    return fallos


def _sin_parallax_en_reposo(raw, general, lienzo, base, i, forma,
                            linea: str) -> list[str]:
    """Lo que se separaría de `object_mvp` la línea `vaiven origin` con los
    ejes sin el 1 + k del parallax en reposo de una raíz, la cuenta de
    `we_vaiven_coloca` hecha aquí: en clip y en unidades de lienzo. Para que
    el caso discrimine tiene que pasar de 1e-6."""
    k = con_paralaje(quieta(raw), general, lienzo).get("_paralaje_k") or [0.0, 0.0]
    ex, ey = (float(x) for x in linea.split()[-2:])
    ex, ey = ex / (1.0 + k[0]), ey / (1.0 + k[1])
    b0 = forma[0]
    peor = peor_u = 0.0
    for t in tiempos():
        v = wescript.valor_del_vaiven(forma, t)
        esp = werender.object_mvp(_Capa(con_paralaje(con_valor(raw, "origin", i, v),
                                                     general, lienzo)), lienzo)
        dado = (base[3] + ex * (v - b0), base[7] + ey * (v - b0))
        sep = max(abs(dado[0] - esp[3]), abs(dado[1] - esp[7]))
        peor = max(peor, sep)
        peor_u = max(peor_u, abs(dado[0] - esp[3]) * lienzo[0] / 2.0,
                     abs(dado[1] - esp[7]) * lienzo[1] / 2.0)
    print(f"      sin el 1 + k del parallax en reposo (k = {k[0]:g}, {k[1]:g}) se "
          f"separaría {peor:.3g} en clip, {peor_u:.3g} unidades de lienzo")
    if peor <= TOL_MATRIZ:
        return ["vaiven origin: sin el 1 + k no se separa; el caso no discrimina"]
    return []


def prueba_vaiven(exe: Path, tmp: Path) -> list[str]:
    fallos: list[str] = []
    for escena, capa, campo in VAIVENES:
        d = Path(wepaths.we_workshop()) / escena
        _, ents = pkg_inspect.read_pkg(str(d / "scene.pkg"))
        sj = json.loads(next(e for e in ents if e["name"] == "scene.json")["data"])
        raw = next(o for o in sj["objects"] if o.get("id") == capa)
        lienzo = (int(sj["general"]["orthogonalprojection"]["width"]),
                  int(sj["general"]["orthogonalprojection"]["height"]))
        werender.emit_plan(d, tmp / f"plan_{escena}", ruta_final=Path("/PLAN"))
        plan = (tmp / f"plan_{escena}" / "plan.txt").read_text().splitlines()
        lineas = [l for l in plan if l.startswith("vaiven ")]
        formas = wescript.vaiven_de(raw, campo)
        print(f"── vaiven de {escena}/{capa} ({campo}): {lineas}, forma {formas} ──")
        if len(lineas) != 1 or not formas or len(formas) != 1:
            fallos.append(f"{escena}: {len(lineas)} líneas vaiven, formas {formas}")
            continue
        i, forma = formas[0]
        props = raw[campo].get("scriptproperties") or {}
        ip = wescript.Interprete(raw[campo]["script"], props)
        entrada = [float(x) for x in str(raw[campo]["value"]).split()]
        if campo == "angles":
            entrada = [math.degrees(x) for x in entrada]
        entrada = (entrada + [0.0, 0.0, 0.0])[:3]
        general = sj["general"]
        base = werender.object_mvp(
            _Capa(con_paralaje(quieta(raw), general, lienzo)), lienzo)
        fallos += _compara_vaiven(
            exe, tmp, lineas[0].replace("@TIME@", "0"), lienzo, base,
            f"{escena}/{capa}", lambda t: wescript.valor_del_vaiven(forma, t),
            lambda t: ip.vector_en(t, entrada)[i],
            lambda v: con_paralaje(con_valor(raw, campo, i, v), general, lienzo))
        if campo == "origin":
            fallos += _sin_parallax_en_reposo(raw, general, lienzo, base, i, forma,
                                              lineas[0])

    # Con decimales en todo, que es donde muerde la locale. Una capa
    # sintética no cuadrada, con el ángulo ya horneado y un lienzo 16:9.
    lz = (1920, 1080)
    sint = {"origin": "700.25 300.5 0", "size": "512.5 128.25",
            "scale": "1.25 0.75 1", "angles": f"0 0 {math.radians(12.5)!r}"}
    forma = (12.5, 2.75, 0.625, 0.375)
    base = werender.object_mvp(_Capa(sint), lz)
    fallos += _compara_vaiven(
        exe, tmp, f"vaiven angles 12.5 2.75 0.625 0.375 12.5 4.25 {lz[0]} {lz[1]}",
        lz, base, "angles con decimales",
        lambda t: wescript.valor_del_vaiven(forma, t), None,
        lambda v: dict(sint, angles=f"0 0 {math.radians(v)!r}"))
    forma = (300.5, 7.25, 1.5, -0.5)
    fallos += _compara_vaiven(
        exe, tmp, f"vaiven origin 300.5 7.25 1.5 -0.5 300.5 4.25 0 {2.0 / lz[1]!r}",
        lz, base, "origin con decimales",
        lambda t: wescript.valor_del_vaiven(forma, t), None,
        lambda v: dict(sint, origin=f"700.25 {v!r} 0"))

    # Con `@TIME@` sin poner: se lee sin tiempo y con lo de detrás.
    (tmp / "vaiven.txt").write_text("vaiven origin 1.5 2.5 0.5 0 1.5 @TIME@ 0.25 0.5\n")
    r = subprocess.run([str(exe), "vaiven", str(tmp / "vaiven.txt"), "es_ES.UTF-8"],
                       input="", capture_output=True, text=True)
    ok = r.returncode == 0 and r.stdout.split()[1:] == \
        "0 1.5 2.5 0.5 0 1.5 0 0 0.25 0.5".split()
    print(f"  {'ok' if ok else 'MAL':3} línea con @TIME@: {r.stdout.strip() or r.returncode}")
    if not ok:
        fallos.append(f"la línea con @TIME@ da {r.stdout.strip() or r.returncode}")
    return fallos


class _Nodo(_Capa):
    """Una capa con lo que `Renderer._lineas_de_vaiven` mira además."""
    kind, name = "image", "sintética"


class _Colocador:
    """Lo que `_lineas_de_vaiven` necesita de un `Renderer`."""
    _lineas_de_vaiven = werender.Renderer._lineas_de_vaiven
    _vaiven_del_origin = werender.Renderer._vaiven_del_origin

    def __init__(self, por_id: dict, canvas: tuple[int, int]):
        self.por_id, self.canvas = por_id, canvas
        self.notes: list[str] = []
        self.stats: dict[str, int] = {}


def _oscila(kx: float, ax: float, ky: float, ay: float) -> str:
    return ("export function update(value) {"
            f" value.x = {kx!r} + Math.sin(engine.runtime * 0.7) * {ax!r};"
            f" value.y = {ky!r} + Math.cos(engine.runtime * 0.3) * {ay!r};"
            " return value; }")


def prueba_vaiven_de_hijos() -> list[str]:
    """Una capa que cuelga de otras cuyo `origin` oscila queda, con las líneas
    `vaiven` del plan, donde la dejaría `object_mvp` si esos `origin` valieran
    de verdad lo que da el script: la raíz, con el parallax en reposo, y una
    intermedia dentro de un padre escalado y girado. El `angles` que oscila
    en una capa con hijos no se hereda."""
    lz = (1920, 1080)
    general = {"cameraparallax": True, "cameraparallaxamount": 0.5}
    raiz = {"id": 1, "origin": {"script": _oscila(700.5, 12.25, 410.0, 7.5),
                                "value": "700.5 400.25 0"},
            "angles": {"script": "export function update(value) { value.z = "
                                 "20 + Math.sin(engine.runtime) * 3; return value; }",
                       "value": f"0 0 {math.radians(20.0)!r}"},
            "scale": "1.5 0.75 1", "parallaxDepth": "0.5 0.25"}
    medio = {"id": 2, "parent": 1, "scale": "2 0.5 1",
             "angles": f"0 0 {math.radians(-35.0)!r}",
             "origin": {"script": _oscila(30.25, 5.5, -12.0, 3.25),
                        "value": "30.25 -9.5 0"}}
    hoja = {"id": 3, "parent": 2, "origin": "11.5 -7.25 0", "size": "512.5 128.25",
            "scale": "1.25 0.75 1", "angles": f"0 0 {math.radians(12.5)!r}"}

    def por_id(r, m, h=hoja):
        return {"1": _Nodo(r), "2": _Nodo(m), "3": _Nodo(h)}

    def fija(raw, x, y):
        q = quieta(raw)
        q["origin"] = f"{x!r} {y!r} 0"
        return q

    r0 = con_paralaje(quieta(raiz), general, lz)
    base = werender.object_mvp(_Nodo(hoja), lz, por_id=por_id(r0, quieta(medio)))
    k = r0["_paralaje_k"]
    # El emisor ve los scripts; el parallax, como lo pone `werender` al cargar.
    rs = dict(raiz, _paralaje_k=k)
    col = _Colocador(por_id(rs, medio), lz)
    lineas = col._lineas_de_vaiven(col.por_id["3"], {"1", "2"})
    print(f"── vaivén de una capa con padres: {len(lineas)} líneas ──")
    fallos = []
    if len(lineas) != 4 or any(not l.startswith("vaiven origin ") for l in lineas):
        fallos.append(f"una hoja con dos padres que oscilan: {lineas}")
    propias = col._lineas_de_vaiven(col.por_id["1"], {"1", "2"})
    if len(propias) != 2 or any(not l.startswith("vaiven origin ") for l in propias):
        fallos.append(f"una raíz con hijos y angles que oscila: {propias}")

    peor = quieta_peor = 0.0
    for t in tiempos():
        m = list(base)
        for l in lineas:
            c = l.split()
            forma = tuple(float(x) for x in c[2:6])
            d = wescript.valor_del_vaiven(forma, t) - float(c[6])
            m[3] += float(c[8]) * d
            m[7] += float(c[9]) * d
        rx = 700.5 + math.sin(t * 0.7) * 12.25
        ry = 410.0 + math.cos(t * 0.3) * 7.5
        mx = 30.25 + math.sin(t * 0.7) * 5.5
        my = -12.0 + math.cos(t * 0.3) * 3.25
        esp = werender.object_mvp(_Nodo(hoja), lz, por_id=por_id(
            con_paralaje(fija(raiz, rx, ry), general, lz), fija(medio, mx, my)))
        peor = max(peor, max(abs(a - b) for a, b in zip(m, esp)))
        quieta_peor = max(quieta_peor, max(abs(a - b) for a, b in zip(base, esp)))
    ok = peor <= TOL_MATRIZ and quieta_peor > 100 * TOL_MATRIZ
    print(f"  {'ok' if ok else 'MAL':3} hoja a {peor:.3g} de object_mvp "
          f"(sin las líneas, a {quieta_peor:.3g})")
    if not ok:
        fallos.append(f"vaivén de los padres: {peor:.3g}, sin él {quieta_peor:.3g}")
    return fallos


def main() -> int:
    fallos: list[str] = []
    d = Path(wepaths.we_workshop()) / ESCENA
    _, ents = pkg_inspect.read_pkg(str(d / "scene.pkg"))
    sj = json.loads(next(e for e in ents if e["name"] == "scene.json")["data"])
    por_id = {o.get("id"): o for o in sj["objects"]}
    lienzo = (int(sj["general"]["orthogonalprojection"]["width"]),
              int(sj["general"]["orthogonalprojection"]["height"]))

    tmp = Path(tempfile.mkdtemp(prefix="test-giro-"))
    try:
        werender.emit_plan(d, tmp / "plan", ruta_final=Path("/PLAN"))
        lineas = [l for l in (tmp / "plan" / "plan.txt").read_text().splitlines()
                  if l.startswith("giro ")]
        print(f"── las líneas `giro` del plan de {ESCENA}: {len(lineas)} ──")
        if len(lineas) != len(AGUJAS):
            fallos.append(f"el plan trae {len(lineas)} líneas giro")
        exe = compila(tmp)

        p = subprocess.run([str(exe), "-", "es_ES.UTF-8"], capture_output=True,
                           text=True)
        print(f"  strtod(\"0.5\") sin guarda con es_ES: {p.stdout.strip() or p.returncode}")
        if p.returncode or float(p.stdout) != 0.0:
            fallos.append("la locale es_ES no muerde aquí: la prueba no "
                          "probaría la guarda")

        lienzos = (lienzo,) + tuple(l for l in LIENZOS if l != lienzo)
        for linea, capa in zip(lineas, AGUJAS):
            raw = por_id[capa]
            forma = wescript.giro_por_hora(raw)
            # La colocación que hornea el plan, con el `value` guardado.
            quieta = dict(raw, angles=raw["angles"]["value"])
            v = [float(x) for x in raw["angles"]["value"].split()]
            for lz in lienzos:
                base = werender.object_mvp(_Capa(quieta), lz)
                fallos += _compara(exe, tmp, con_lienzo(linea, lz), lz, base,
                                   f"{capa}",
                                   lambda t: wescript.grados_del_giro(forma, t),
                                   lambda g: dict(raw, angles=f"{v[0]} {v[1]} "
                                                  f"{math.radians(g)!r}"))

        # Con decimales, que es donde muerde la locale: la forma, la base y
        # la hora del plan, que aquí va puesta y no como `@HORA@`. La hora no
        # la mira el arnés, pero tiene que leerse sin descolocar lo de antes
        # ni el lienzo de detrás. La capa es sintética, no cuadrada y con el
        # ángulo `base` ya horneado: ahí, girar la colocación en clip en vez
        # de en píxeles no daría lo que `object_mvp`.
        forma, base_g = (-0.5, 1.5, 0.25), 0.75
        sint = {"origin": "700.25 300.5 0", "size": "512.5 128.25",
                "scale": "1.25 0.75 1"}
        for lz in lienzos:
            base = werender.object_mvp(
                _Capa(dict(sint, angles=f"0 0 {math.radians(base_g)!r}")), lz)
            fallos += _compara(exe, tmp, f"giro -0.5 1.5 0.25 0.75 0.5 {lz[0]} {lz[1]}",
                               lz, base, "con decimales",
                               lambda t: wescript.grados_del_giro(forma, t),
                               lambda g: dict(sint, angles=f"0 0 {math.radians(g)!r}"))

        # Una línea sin lienzo, la de un plan de antes, se sigue leyendo y lo
        # deja a 0: `we_giro_coloca` gira entonces en clip, como se horneó.
        (tmp / "giro.txt").write_text("giro -720 1 0 0 @HORA@\n")
        r = subprocess.run([str(exe), str(tmp / "giro.txt"), "es_ES.UTF-8"],
                           input="", capture_output=True, text=True)
        ok = r.returncode == 0 and r.stdout.strip() == "lienzo 0 0"
        print(f"  {'ok' if ok else 'MAL':3} línea sin lienzo: {r.stdout.strip() or r.returncode}")
        if not ok:
            fallos.append(f"la línea sin lienzo da {r.stdout.strip() or r.returncode}")

        # El plan con `resolucion`, como en vivo: `canvas` es la resolución
        # de dibujo y no el lienzo. Las líneas `object` y `giro` se toman del
        # plan tal cual, como las toman los ejecutores.
        for res in RESOLUCIONES:
            out = tmp / f"plan_{res[0]}x{res[1]}"
            werender.emit_plan(d, out, ruta_final=Path("/PLAN"), resolucion=res)
            plan = (out / "plan.txt").read_text().splitlines()
            canvas = next(tuple(int(x) for x in l.split()[1:3])
                          for l in plan if l.startswith("canvas "))
            pares = [(plan[i - 1], l) for i, l in enumerate(plan)
                     if l.startswith("giro ") and plan[i - 1].startswith("object ")]
            print(f"── plan con resolucion {res[0]}x{res[1]}: canvas "
                  f"{canvas[0]}x{canvas[1]} (proporción {canvas[0] / canvas[1]:.6f} "
                  f"frente a {lienzo[0] / lienzo[1]:.6f}), {len(pares)} giros ──")
            if len(pares) != len(AGUJAS):
                fallos.append(f"resolucion {res}: {len(pares)} líneas giro "
                              "detrás de un object")
            for (obj, linea), capa in zip(pares, AGUJAS):
                raw = por_id[capa]
                forma = wescript.giro_por_hora(raw)
                v = [float(x) for x in raw["angles"]["value"].split()]
                base = [float(x) for x in obj.split()[2:18]]
                fallos += _compara(exe, tmp, linea, lienzo, base,
                                   f"{capa} plan a {res[0]}x{res[1]}",
                                   lambda t: wescript.grados_del_giro(forma, t),
                                   lambda g: dict(raw, angles=f"{v[0]} {v[1]} "
                                                  f"{math.radians(g)!r}"))
                # Lo que habría dado girar con la proporción de `canvas`.
                peor = 0.0
                for t in tods():
                    g = wescript.grados_del_giro(forma, t)
                    dado = gira_en_pixeles([base[0], base[1], base[4], base[5]],
                                           g - v[2], canvas[0] / canvas[1])
                    esp = werender.object_mvp(_Capa(dict(
                        raw, angles=f"{v[0]} {v[1]} {math.radians(g)!r}")), lienzo)
                    peor = max(peor, max(abs(a - b) for a, b in
                                         zip(dado, (esp[0], esp[1], esp[4], esp[5]))))
                print(f"      con la proporción de canvas se separaría {peor:.3g}")
                if peor <= TOL_MATRIZ:
                    fallos.append(f"{capa} plan a {res}: la proporción de canvas "
                                  "no se separa; el caso no discrimina")

        print("── we_hora_del_dia ──")
        instantes = [(1791394680, 0), (1791394680, 500000000), (1791417599, 999000000),
                     (1791331200, 0)]
        for tz, desfase in (("UTC", 0), ("Etc/GMT-2", 7200)):
            r = subprocess.run([str(exe), "hora"], capture_output=True, text=True,
                               input="".join(f"{s} {ns}\n" for s, ns in instantes),
                               env={**os.environ, "TZ": tz})
            dados = [float(x) for x in r.stdout.split()]
            esperados = [((s + desfase) % 86400 + ns / 1e9) / 86400.0
                         for s, ns in instantes]
            peor = max((abs(a - b) for a, b in zip(dados, esperados)), default=1.0)
            ok = len(dados) == len(instantes) and peor <= 1e-12
            print(f"  {'ok' if ok else 'MAL':3} TZ={tz:10} {dados}")
            if not ok:
                fallos.append(f"we_hora_del_dia con TZ={tz}: {dados} y {esperados}")

        fallos += prueba_vaiven(exe, tmp)
        fallos += prueba_vaiven_de_hijos()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("── los dos ejecutores ──")
    for f in ("tools/glexec.c", "src/glexecutor.cpp"):
        texto = (RAIZ / f).read_text()
        faltan = [fn for fn in ("we_giro_linea", "we_giro_grados", "we_giro_coloca",
                                "we_vaiven_linea", "we_vaiven_coloca")
                  if f"{fn}(" not in texto]
        print(f"  {'ok' if not faltan else 'MAL':3} {f}: "
              f"{'llama a las cinco' if not faltan else 'no llama a ' + str(faltan)}")
        if faltan:
            fallos.append(f"{f} no llama a {faltan}")

    if fallos:
        print(f"\nFALLO: {len(fallos)}")
        for f in fallos:
            print(f"  {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
