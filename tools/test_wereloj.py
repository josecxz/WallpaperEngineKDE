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
  5. Un reloj del corpus con pares de kerning distintos de cero, a una hora
     que los usa, a 1e-4 y con las dos locales: el par viaja en su propia
     línea (`relojkern`) y es lo que el C suma de más. Y las capas del corpus
     con pares, contra los números del plan y al margen del float del C.

Uso:
    python3 tools/test_wereloj.py
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import ImageFont

sys.path.insert(0, str(Path(__file__).parent))
import pkg_inspect
import wepaths
import wescript
import wetext
from wescene import AssetResolver
from localecoma import SIN_COMA, locale_con_coma

# La locale de coma con que el escritorio rompe `strtof` (CLAUDE.md, regla 6):
# `es_ES` si esta instalada, o cualquier otra de coma. Ver tools/localecoma.py.
COMA = locale_con_coma() or "es_ES.UTF-8"

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
    /* Si la locale no esta instalada, `setlocale` falla y el arnes seguiria
     * en "C": la pasada con coma no probaria nada y saldria bien. */
    if (argc > 2 && !setlocale(LC_ALL, argv[2]))
        return 3;

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
    return werender.lineas_de_reloj(mid, fmt, r)


def capas_de_reloj(dirs=None):
    """Todas las capas del corpus cuyo script se traduce a un formato, o solo
    las de las escenas de `dirs`."""
    ws = Path(wepaths.we_workshop())
    we = Path(wepaths.we_assets())
    for d in sorted(dirs if dirs is not None else ws.iterdir()):
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


def reloj_del_plan(r: wetext.Reloj, lineas: list[str]) -> wetext.Reloj:
    """El mismo reloj con los números tal como viajan en el plan, que es lo
    que lee el C: el avance y la tinta van con seis cifras. Comparar contra
    esto deja fuera el redondeo del plan y deja solo la cuenta."""
    glifos, kern = [], {}
    caja, pad, u, alto, esp = r.caja, r.pad, r.u, r.alto_linea, r.espaciado
    for x in lineas:
        t = x.split()
        if t[0] == "reloj":
            v = [float(y) for y in t[2:]]
            caja, pad, u, alto, esp = (v[1], v[2]), (v[3], v[4]), v[7], v[8], v[10]
        elif t[0] == "relojglifo":
            v = [float(y) for y in t[2:]]
            glifos.append(wetext.Glifo(int(v[0]), v[1], tuple(v[2:6]),
                                       tuple(v[6:10])))
        elif t[0] == "relojkern":
            kern[(int(t[2]), int(t[3]))] = float(t[4])
    return dataclasses.replace(r, glifos=glifos, kern=kern, caja=caja,
                               pad=pad, u=u, alto_linea=alto, espaciado=esp)


def compara(exe: Path, plan: Path, fmt, r, etq: str,
            fallos: list[str], instantes=INSTANTES,
            tope: float | None = 0.01) -> int:
    """Python contra C para un reloj ya escrito en `plan`, con las dos
    locales. Devuelve 1 si también coincidió con la de coma (`COMA`).

    Con `tope=None` el margen es el del float del C: 1e-4, o 8 ulp de float32
    a la magnitud del vértice si es mayor ---hay capas a 2400 unidades del
    centro, donde un ulp ya son 2,4e-4---."""
    for locale in ("C", COMA):
        # `es_ES` es la que hereda el escritorio y la que rompe `strtof`.
        entrada = "\n".join(
            str(int(t.timestamp())) for t in instantes) + "\n"
        p = subprocess.run([str(exe), str(plan), locale],
                           input=entrada, capture_output=True, text=True)
        if p.returncode:
            fallos.append(f"{etq} [{locale}]: el arnés falla")
            return 0
        salida = p.stdout.splitlines()
        for k, t in enumerate(instantes):
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
            margen = tope if tope is not None else max(
                1e-4, 8 * float(np.spacing(np.float32(np.abs(py[:, :2]).max()))))
            if peor > margen:
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


# El kerning con una fuente de verdad: la del reloj de `3029745918` (capa 90),
# en la que «04» mide 258,8 px con raqm y 271 glifo a glifo a 200 px de em
# (NOTAS.md). Lo que se prueba no es la escena sino que un par distinto de
# cero llega al C y lo mueve igual que a Python; si la escena no está, falla.
KERN_ESCENA, KERN_CAPA = "3029745918", 90
KERN_INSTANTE = dt.datetime(2026, 10, 12, 4, 42, 0)


def contrato_de_kerning(exe: Path, tmp: Path, fallos: list[str]) -> int:
    """Un reloj con pares distintos de cero, a una hora en la que el renglón
    los usa. Antes de comparar con el C se comprueba que los pares de verdad
    mueven la tinta y que el renglón mide lo que mide raqm; luego, los
    vértices del C contra los de Python a 1e-4, con las dos locales."""
    d = Path(wepaths.we_workshop()) / KERN_ESCENA
    capa = next(((o, fmt, res) for _, o, fmt, res in capas_de_reloj([d])
                 if o.get("id") == KERN_CAPA), None)
    etq = f"kerning {KERN_ESCENA}/{KERN_CAPA}"
    if capa is None:
        fallos.append(f"{etq}: no está en el corpus")
        return 0
    obj, fmt, res = capa
    r = wetext.disponer_reloj(res, obj, fmt.alfabeto, fmt.max_longitud(),
                              0.5, cadenas=fmt.cadenas())
    texto = fmt.render(KERN_INSTANTE)
    usados = [(ord(a), ord(b)) for a, b in zip(texto, texto[1:])
              if (ord(a), ord(b)) in r.kern]
    if not usados:
        fallos.append(f"{etq}: {texto!r} no usa ningún par")
        return 0
    con = wetext.quads_de_reloj(r, texto)
    sin = wetext.quads_de_reloj(dataclasses.replace(r, kern={}), texto)
    if float(np.abs(con - sin).max()) < 1e-3:
        fallos.append(f"{etq}: los pares no mueven nada")
        return 0
    em = wetext._numeros(obj.get("pointsize"), 1, 0.0)[0] * wetext.UNIDADES_POR_PUNTO
    px = int(round(em / r.u))
    font = ImageFont.truetype(
        io.BytesIO(wetext.resolver_fuente(res, obj.get("font"))), px)
    _, ancho = wetext._plumas(texto, {g.cp: g.avance for g in r.glifos}, r.kern)
    if abs(ancho - font.getlength(texto)) / px > 0.01:
        fallos.append(f"{etq}: {texto!r} mide {ancho} y raqm {font.getlength(texto)}")
        return 0
    plan = tmp / "kerning.txt"
    lineas = lineas_del_plan(0, fmt, r)
    if sum(x.startswith("relojkern ") for x in lineas) != len(r.kern):
        fallos.append(f"{etq}: el plan no lleva los {len(r.kern)} pares")
        return 0
    plan.write_text("\n".join(lineas) + "\n")
    r = reloj_del_plan(r, lineas)
    print(f"  {etq}: {texto!r}, {len(r.kern)} pares en el alfabeto, "
          f"{len(usados)} en el renglón; mueven la tinta "
          f"{float(np.abs(con - sin).max()):.3f} unidades")
    return compara(exe, plan, fmt, r, etq, fallos,
                   [KERN_INSTANTE] + INSTANTES, 1e-4)


def main() -> int:
    fallos: list[str] = []
    con_locale = 0
    con_pares = 0
    n_capas = 0
    renglones = 0
    escenas = set()

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        exe = compila(tmp)
        sinteticos = contrato_de_renglones(exe, tmp, fallos)
        kerning = contrato_de_kerning(exe, tmp, fallos)
        for wid, obj, fmt, res in capas_de_reloj():
            n_capas += 1
            escenas.add(wid)
            etq = f"{wid} {obj.get('name', '')!r}"
            try:
                r = wetext.disponer_reloj(res, obj, fmt.alfabeto,
                                          fmt.max_longitud(), 0.5,
                                          cadenas=fmt.cadenas())
            except Exception as e:
                fallos.append(f"{etq}: sin disponer ({e})")
                continue
            if r is None:
                fallos.append(f"{etq}: sin disponer")
                continue
            if any("\n" in fmt.render(t) for t in INSTANTES):
                renglones += 1

            plan = tmp / "reloj.txt"
            lineas = lineas_del_plan(0, fmt, r)
            plan.write_text("\n".join(lineas) + "\n")
            # Con pares, más fino y contra lo que lleva el plan: el kerning es
            # lo único que el C suma de más, y el par más pequeño es 1/64 de
            # píxel, que a 0,01 de margen podría no verse.
            if r.kern:
                con_pares += 1
                con_locale += compara(exe, plan, fmt, reloj_del_plan(r, lineas),
                                      etq, fallos, tope=None)
            else:
                con_locale += compara(exe, plan, fmt, r, etq, fallos)

    print("── relojes del corpus ──")
    print(f"  escenas con reloj    {len(escenas)}")
    print(f"  capas de reloj       {n_capas}")
    print(f"  con la locale {COMA:<6} {con_locale}")
    print(f"  con varios renglones {renglones}")
    print(f"  sintéticos con \\n    {sinteticos} de 5")
    print(f"  con kerning (al ulp) {con_pares}")
    print(f"  caso de kerning      {kerning} de 1")
    if locale_con_coma() is None:
        fallos.append(SIN_COMA)
    if fallos:
        print(f"\nFALLO: {len(fallos)} discrepancias")
        for f in fallos[:20]:
            print(f"  {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
