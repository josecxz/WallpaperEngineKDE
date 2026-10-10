#!/usr/bin/env python3
"""El contrato entre las dos mitades de un reloj, y el barrido del corpus.

Un reloj se reparte en tres: `wescript.py` deduce la plantilla del JavaScript
de la capa, `wetext.py` rasteriza el alfabeto y calcula las métricas, y
`src/wereloj.c` rellena la plantilla y rehace los quads --- en los DOS
ejecutores, igual que las partículas. Las dos mitades hacen la misma cuenta y
esta prueba las compara sobre el corpus entero:

  1. La plantilla que emite Python y la cadena que escribe el C coinciden, en
     los mismos instantes con los que se dedujo el formato.
  2. Los vértices que calcula `quads_de_reloj` y los que calcula
     `we_reloj_vertices` coinciden.
  3. Y las dos cosas con la locale `es_ES`, que es la que hereda plasmashell:
     el `strtof` del lado C lee `0.899` como `0` si nadie lo sujeta, y todas
     las métricas del alfabeto se van a cero sin un solo error por medio.
  4. Un caso sintético de varios renglones ---el salto en mitad de la
     plantilla, al principio y dentro de una tabla, con las tres alineaciones
     y espaciado---, porque en el corpus solo hay una capa así y solo se parte
     en dos los sábados.

Uso:
    python3 tools/test_wereloj.py
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import pkg_inspect
import wepaths
import wescript
import wetext
from wescene import AssetResolver

RAIZ = Path(__file__).resolve().parent.parent

ARNES = r"""
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wereloj.h"

/* Qt adopta la locale del entorno al arrancar; sin esto la prueba no prueba
 * nada, porque un binario en C se queda en la locale "C" por defecto. */
int main(int argc, char **argv)
{
    if (argc > 2)
        setlocale(LC_ALL, argv[2]);

    FILE *f = fopen(argv[1], "r");
    if (!f) return 2;
    WeReloj *r = we_reloj_nuevo();
    char linea[8192];
    while (fgets(linea, sizeof linea, f)) {
        char kw[32];
        if (sscanf(linea, "%31s", kw) != 1) continue;
        /* La linea del plan es `<kw> <id de malla> <resto>`, y el ejecutor le
         * pasa a wereloj.c solo el resto: aqui hay que quitar los dos. */
        const char *p = linea;
        for (int k = 0; k < 2; k++) {
            while (*p && *p != ' ') p++;
            while (*p == ' ') p++;
        }
        we_reloj_linea(r, kw, p);
    }
    fclose(f);

    /* Lo que la locale tiene que atravesar es la LECTURA del plan, que es
     * donde vive el `strtof`. Para escribir el resultado se vuelve a la
     * locale C: si no, el propio arnes imprimiria `-200,589584` y lo que
     * fallaria seria la prueba, no el modulo. */
    setlocale(LC_ALL, "C");

    /* Cada linea de la entrada estandar es un instante en segundos desde la
     * epoca; por cada uno se escribe el texto y los vertices. */
    char pet[64];
    int nv = we_reloj_nvertices(r);
    float *v = malloc((size_t)nv * 5 * sizeof *v);
    while (fgets(pet, sizeof pet, stdin)) {
        time_t t = (time_t)strtoll(pet, NULL, 10);
        char texto[512];
        we_reloj_texto(r, t, texto, sizeof texto);
        /* El salto de línea va escapado: la salida se lee por líneas. */
        printf("texto ");
        for (const char *c = texto; *c; c++) {
            if (*c == '\n') fputs("\\n", stdout);
            else if (*c == '\\') fputs("\\\\", stdout);
            else putchar(*c);
        }
        printf("\n");
        we_reloj_vertices(r, t, v);
        printf("verts %d", nv);
        for (int i = 0; i < nv * 5; i++) printf(" %.6f", v[i]);
        printf("\n");
    }
    we_reloj_free(r);
    return 0;
}
"""


def compila(tmp: Path) -> Path:
    src = tmp / "arnes.c"
    src.write_text(ARNES)
    exe = tmp / "arnes"
    r = subprocess.run(
        ["cc", "-O1", "-std=c11", "-Wall", f"-I{RAIZ}/src", "-o", str(exe),
         str(src), str(RAIZ / "src" / "wereloj.c")],
        capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("no compila el arnés:\n" + r.stderr)
    return exe


def lineas_del_plan(mid: int, fmt, r) -> list[str]:
    """Las mismas directivas que escribe `werender._emit_reloj`."""
    import werender
    alin = {"left": 0, "top": 0, "center": 1, "right": 2, "bottom": 2}
    lineas = [
        f"reloj {mid} {fmt.periodo:g} {r.caja[0]:g} {r.caja[1]:g} "
        f"{r.pad[0]:g} {r.pad[1]:g} "
        f"{alin.get(r.halign, 1)} {alin.get(r.valign, 1)} "
        f"{r.u:.9g} {r.alto_linea:.9g} {r.max_glifos} {r.espaciado:.9g}",
        f"relojfmt {mid} {werender._escapa(fmt.plantilla)}",
    ]
    for codigo, tabla in fmt.tablas.items():
        palabras = " ".join(werender._escapa(x) for x in tabla)
        lineas.append(f"relojtab {mid} {codigo} {len(tabla)} {palabras}")
    for g in r.glifos:
        lineas.append(
            f"relojglifo {mid} {g.cp} {g.avance:.6g} "
            + " ".join(f"{x:.6g}" for x in g.ink)
            + " " + " ".join(f"{x:.9g}" for x in g.uv))
    return lineas


def capas_de_reloj():
    """Todas las capas del corpus cuyo script se traduce a un formato."""
    ws = Path(wepaths.we_workshop())
    we = Path(wepaths.we_assets())
    for d in sorted(ws.iterdir()):
        pkg = d / "scene.pkg"
        if not pkg.is_file():
            continue
        try:
            _, entradas = pkg_inspect.read_pkg(str(pkg))
            escena = [e for e in entradas if e["name"] == "scene.json"]
            if not escena:
                continue
            j = json.loads(escena[0]["data"])
            res = AssetResolver.for_wallpaper(d, we)
        except Exception:
            continue
        for o in j.get("objects") or []:
            if not isinstance(o, dict) or "text" not in o:
                continue
            try:
                fmt = wescript.reloj_de(o)
            except Exception:
                continue
            if fmt is None:
                continue
            yield d.name, o, fmt, res


# Los instantes tienen que cruzar la medianoche, el cambio de mes y el de
# año: es donde una plantilla mal deducida deja de coincidir. Y un sábado, que
# es el único día en que el reloj de `2946362143` tiene dos renglones.
INSTANTES = [
    dt.datetime(2027, 11, 19, 21, 46, 58),
    dt.datetime(2026, 3, 5, 7, 8, 9),
    dt.datetime(2024, 12, 31, 23, 59, 59),
    dt.datetime(2025, 1, 1, 0, 0, 0),
    dt.datetime(2025, 6, 15, 12, 0, 0),
    dt.datetime(2028, 2, 29, 13, 5, 45),
    dt.datetime(2026, 10, 10, 13, 5, 7),
]


def _desescapa(s: str) -> str:
    """La cadena que escribe el arnés, con el salto de línea escapado."""
    salida, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in "n\\":
            salida.append("\n" if s[i + 1] == "n" else "\\")
            i += 2
        else:
            salida.append(s[i])
            i += 1
    return "".join(salida)


def compara(exe: Path, plan: Path, fmt, r, etq: str,
            fallos: list[str]) -> int:
    """Python contra C para un reloj ya escrito en `plan`, con las dos
    locales. Devuelve 1 si también coincidió con `es_ES`."""
    for locale in ("C", "es_ES.UTF-8"):
        # `es_ES` es la que hereda el escritorio y la que rompe `strtof`.
        entrada = "\n".join(
            str(int(t.timestamp())) for t in INSTANTES) + "\n"
        p = subprocess.run([str(exe), str(plan), locale],
                           input=entrada, capture_output=True, text=True)
        if p.returncode:
            fallos.append(f"{etq} [{locale}]: el arnés falla")
            return 0
        salida = p.stdout.splitlines()
        for k, t in enumerate(INSTANTES):
            esperado = fmt.render(t)
            dado = _desescapa(salida[2 * k][len("texto "):])
            if dado != esperado:
                fallos.append(
                    f"{etq} [{locale}] {t}: texto {dado!r} != {esperado!r}")
                return 0
            py = wetext.quads_de_reloj(r, esperado)
            trozos = salida[2 * k + 1].split()
            c = np.array([float(x) for x in trozos[2:]],
                         dtype=float).reshape(-1, 5)
            if c.shape != py.shape:
                fallos.append(f"{etq} [{locale}]: {c.shape} != {py.shape}")
                return 0
            peor = float(np.abs(c - py).max())
            if peor > 0.01:
                fallos.append(
                    f"{etq} [{locale}] {t}: vértices difieren en {peor:.4f}")
                return 0
    return 1


def _reloj_sintetico(halign: str, valign: str, espaciado: float,
                     max_glifos: int) -> wetext.Reloj:
    """Un alfabeto inventado ---cifras, dos puntos y mayúsculas, del mismo
    ancho y con la tinta desplazada--- para no depender de ninguna fuente."""
    letras = "0123456789:ABDEIJLMNORSUVX"
    glifos = [wetext.Glifo(ord(c), 11.5, (0.5, 3.25, 10.75, 21.5),
                           (0.0, k / len(letras), 1.0, (k + 1) / len(letras)))
              for k, c in enumerate(letras)]
    return wetext.Reloj(atlas=np.zeros((1, 1, 4), np.uint8), glifos=glifos,
                        u=0.75, alto_linea=27.0, caja=(400.0, 300.0),
                        pad=(6.0, 4.0), halign=halign, valign=valign,
                        max_glifos=max_glifos, espaciado=espaciado)


def contrato_de_renglones(exe: Path, tmp: Path, fallos: list[str]) -> int:
    """Plantillas con `\\n` en mitad, al principio y dentro de una tabla, con
    las tres alineaciones y espaciado. Antes de comparar se comprueba que
    Python de verdad pone los renglones a alturas distintas: si no, coincidir
    con el C sería coincidir en una sola línea y la prueba no probaría nada."""
    dias = ["\nDOM", "LUN", "MAR", "MIE", "JUE", "VIE", "\nSAB"]
    # Un salto AL PRINCIPIO no mueve nada con `bottom` ---el bloque crece
    # hacia arriba y el último renglón se queda donde estaba---, así que esos
    # casos van arriba o en el centro, y el de abajo lleva el salto en mitad.
    # Los espaciados llevan decimales para que la pasada con `es_ES` pruebe
    # también el undécimo número de la línea `reloj`.
    casos = [
        (wescript.Formato("%H\n%M", {}, 60.0), "center", "center", 3.25),
        (wescript.Formato("\n%H:%M", {}, 60.0), "right", "top", 0.0),
        (wescript.Formato("%H:%M\n%A", {"%A": dias}, 60.0), "left", "top", 5.5),
        (wescript.Formato("%A %H:%M", {"%A": dias}, 60.0), "center", "center", 2.5),
        (wescript.Formato("%M\n%H", {}, 60.0), "left", "bottom", 4.75),
    ]
    hechos = 0
    for n, (fmt, ha, va, esp) in enumerate(casos):
        r = _reloj_sintetico(ha, va, esp, fmt.max_longitud())
        etq = f"sintético {fmt.plantilla!r} {ha}/{va}"
        # El bloque de una línea y el de dos no caen igual: con un renglón
        # vacío delante la tinta baja, uno entero arriba y medio en el centro.
        # Abajo no se mueve, porque el bloque crece hacia arriba.
        una = wetext.quads_de_reloj(r, "12")
        dos = wetext.quads_de_reloj(r, "\n12")
        if va != "bottom" and np.allclose(una, dos):
            fallos.append(f"{etq}: Python no cuenta el renglón vacío")
            continue
        partida = wetext.quads_de_reloj(r, "12\n34")
        if len({round(float(y), 3) for y in partida[0:16:4, 1]}) < 2:
            fallos.append(f"{etq}: Python no parte en renglones")
            continue
        plan = tmp / f"sintetico{n}.txt"
        plan.write_text("\n".join(lineas_del_plan(0, fmt, r)) + "\n")
        hechos += compara(exe, plan, fmt, r, etq, fallos)
    return hechos


def main() -> int:
    fallos: list[str] = []
    con_locale = 0
    n_capas = 0
    renglones = 0
    escenas = set()

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        exe = compila(tmp)
        sinteticos = contrato_de_renglones(exe, tmp, fallos)
        for wid, obj, fmt, res in capas_de_reloj():
            n_capas += 1
            escenas.add(wid)
            etq = f"{wid} {obj.get('name', '')!r}"
            try:
                r = wetext.disponer_reloj(res, obj, fmt.alfabeto,
                                          fmt.max_longitud(), 0.5)
            except Exception as e:
                fallos.append(f"{etq}: sin disponer ({e})")
                continue
            if r is None:
                fallos.append(f"{etq}: sin disponer")
                continue
            if any("\n" in fmt.render(t) for t in INSTANTES):
                renglones += 1

            plan = tmp / "reloj.txt"
            plan.write_text("\n".join(lineas_del_plan(0, fmt, r)) + "\n")
            con_locale += compara(exe, plan, fmt, r, etq, fallos)

    print("── relojes del corpus ──")
    print(f"  escenas con reloj    {len(escenas)}")
    print(f"  capas de reloj       {n_capas}")
    print(f"  con la locale es_ES  {con_locale}")
    print(f"  con varios renglones {renglones}")
    print(f"  sintéticos con \\n    {sinteticos} de 5")
    if fallos:
        print(f"\nFALLO: {len(fallos)} discrepancias")
        for f in fallos[:20]:
            print(f"  {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
