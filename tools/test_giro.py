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
     hora puesto en `angles`, en radianes, a 1e-5: unidades, signo y eje.
  3. Que `we_hora_del_dia` es la hora local como fracción del día, con su
     fracción de segundo, con `TZ=UTC` y con `TZ=Etc/GMT-2`.
  4. Que `tools/glexec.c` y `src/glexecutor.cpp` llaman los dos a
     `we_giro_linea`, `we_giro_grados` y `we_giro_coloca`.

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
TOL_MATRIZ = 1e-5

ARNES = r"""
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wegiro.h"

/* argv[1]: `-` para ver qué lee `strtod` de `0.5` en la locale de argv[2];
 * `hora` para pasar instantes `<segundos> <nanosegundos>` a fracción del día;
 * si no, un fichero con la línea `giro` del plan, que se LEE en la locale de
 * argv[2]. Por la entrada, `<tod> <m0> <m1> <m4> <m5>`; por la salida, los
 * grados y la parte lineal girada. */
int main(int argc, char **argv)
{
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

        for linea, capa in zip(lineas, AGUJAS):
            raw = por_id[capa]
            forma = wescript.giro_por_hora(raw)
            # La colocación que hornea el plan, con el `value` guardado.
            quieta = dict(raw, angles=raw["angles"]["value"])
            base = werender.object_mvp(_Capa(quieta), lienzo)
            ts = tods()
            entrada = "".join(f"{t!r} {base[0]!r} {base[1]!r} {base[4]!r} {base[5]!r}\n"
                              for t in ts)
            (tmp / "giro.txt").write_text(linea + "\n")
            for locale in ("C", "es_ES.UTF-8"):
                r = subprocess.run([str(exe), str(tmp / "giro.txt"), locale],
                                   input=entrada, capture_output=True, text=True)
                if r.returncode:
                    fallos.append(f"{capa} [{locale}]: el arnés falla {r.stdout}")
                    continue
                peor_g = peor_m = 0.0
                for t, l in zip(ts, r.stdout.splitlines()):
                    g, *m = (float(x) for x in l.split())
                    peor_g = max(peor_g, abs(g - wescript.grados_del_giro(forma, t)))
                    v = [float(x) for x in raw["angles"]["value"].split()]
                    girada = dict(raw, angles=f"{v[0]} {v[1]} {math.radians(g)!r}")
                    esp = werender.object_mvp(_Capa(girada), lienzo)
                    peor_m = max(peor_m, max(abs(a - b) for a, b in
                                             zip(m, (esp[0], esp[1], esp[4], esp[5]))))
                ok = (len(r.stdout.splitlines()) == len(ts) and len(ts) >= 100
                      and peor_g <= TOL_GRADOS and peor_m <= TOL_MATRIZ)
                print(f"  {'ok' if ok else 'MAL':3} {capa} [{locale:11}] {len(ts)} tod: "
                      f"grados a {peor_g:.3g} de Python, matriz a {peor_m:.3g} de "
                      f"object_mvp")
                if not ok:
                    fallos.append(f"{capa} [{locale}]: grados {peor_g:.3g}, "
                                  f"matriz {peor_m:.3g}")

        # Con decimales, que es donde muerde la locale: la forma, la base y
        # la hora del plan. La hora no la mira el arnés, pero tiene que leerse
        # sin descolocar lo de antes.
        forma, base = (-0.5, 1.5, 0.25), 0.75
        (tmp / "giro.txt").write_text("giro -0.5 1.5 0.25 0.75 0.5\n")
        ts = tods()
        for locale in ("C", "es_ES.UTF-8"):
            r = subprocess.run([str(exe), str(tmp / "giro.txt"), locale],
                               input="".join(f"{t!r} 1 0 0 1\n" for t in ts),
                               capture_output=True, text=True)
            peor_g = peor_m = 1.0
            salida = r.stdout.splitlines()
            if not r.returncode and len(salida) == len(ts):
                peor_g = peor_m = 0.0
                for t, l in zip(ts, salida):
                    g, *m = (float(x) for x in l.split())
                    esp_g = wescript.grados_del_giro(forma, t)
                    peor_g = max(peor_g, abs(g - esp_g))
                    a = math.radians(esp_g - base)
                    esp = (math.cos(a), -math.sin(a), math.sin(a), math.cos(a))
                    peor_m = max(peor_m, max(abs(x - y) for x, y in zip(m, esp)))
            ok = peor_g <= TOL_GRADOS and peor_m <= TOL_MATRIZ
            print(f"  {'ok' if ok else 'MAL':3} con decimales [{locale:11}]: grados a "
                  f"{peor_g:.3g}, matriz a {peor_m:.3g}")
            if not ok:
                fallos.append(f"línea con decimales [{locale}]: grados {peor_g:.3g}, "
                              f"matriz {peor_m:.3g}")

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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("── los dos ejecutores ──")
    for f in ("tools/glexec.c", "src/glexecutor.cpp"):
        texto = (RAIZ / f).read_text()
        faltan = [fn for fn in ("we_giro_linea", "we_giro_grados", "we_giro_coloca")
                  if f"{fn}(" not in texto]
        print(f"  {'ok' if not faltan else 'MAL':3} {f}: "
              f"{'llama a las tres' if not faltan else 'no llama a ' + str(faltan)}")
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
