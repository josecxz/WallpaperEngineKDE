#!/usr/bin/env python3
"""El contrato de una hoja de sprites cuyo fotograma elige la hora.

Se reparte en tres, como un reloj: `wescript.py` evalúa el script de la capa y
da la tabla de 24 fotogramas, `werender.py` la escribe en el pase base con la
hoja (la línea `hojahora`), y `src/wereloj.c` elige la fila con la hora local
y da `g_Texture0Rotation` y `g_Texture0Translation` ---en los DOS ejecutores---.
Esta prueba compila ese módulo desde `src/` y comprueba:

  1. Con la hoja real de `number.am` (22x40, dos fotogramas de 22x20) y la
     locale `es_ES`, que es la que hereda el escritorio y la que rompe
     `strtof`: a las 09:00 da los uniforms de WE del fotograma 0 ---rotación
     (1, 0, 0, 0.5), traslación (0, 0)---, y a las 15:00 los del 1, con la
     traslación (0, 0.5). Y las 24 horas contra la tabla.
  2. Que lo que se SUBE es el reflejo de eso, porque la textura de capa se
     sube volteada (`texture()` en werender.py): la misma cuenta que
     `werender.volteo_de_hoja`.
  3. Que la línea del plan de `3299228616` es la que se esperaba, y que los
     dos ejecutores llaman a `we_hoja_uniforms`.

Uso:
    python3 tools/test_hoja.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pkg_inspect
import wepaths
import werender
import wescene
import wescript
import wetex
from wescene import AssetResolver

RAIZ = Path(__file__).resolve().parent.parent
ESCENA = "3299228616"
CAPA = 303
TOLERANCIA = 1e-6

ARNES = r"""
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wereloj.h"

/* argv[1]: un fichero con la línea `hojahora` del plan; argv[2]: la locale
 * con la que se LEE. Por la entrada, un instante por línea; por la salida,
 * los uniforms de WE y los que se suben. */
int main(int argc, char **argv)
{
    if (argc > 2 && !setlocale(LC_ALL, argv[2]))
        return 4;
    /* Sin fichero: lo que `strtof` lee de `0.5` en esa locale, para saber que
     * la prueba prueba algo. */
    if (strcmp(argv[1], "-") == 0) {
        printf("%g\n", strtof("0.5", NULL));
        return 0;
    }
    FILE *f = fopen(argv[1], "r");
    if (!f) return 2;
    char linea[16384];
    if (!fgets(linea, sizeof linea, f)) return 2;
    fclose(f);
    const char *p = linea;
    while (*p && *p != ' ') p++;           /* fuera `hojahora` */
    WeHoja *h = we_hoja_nueva();
    if (!we_hoja_linea(h, p)) {
        printf("no la lee\n");
        return 3;
    }
    /* Para escribir se vuelve a la locale C: si no, el arnés imprimiría
     * `0,5` y fallaría la prueba, no el módulo. */
    setlocale(LC_ALL, "C");
    char pet[64];
    while (fgets(pet, sizeof pet, stdin)) {
        time_t t = (time_t)strtoll(pet, NULL, 10);
        float r[4], tr[2], rg[4], tg[2];
        if (!we_hoja_uniforms_we(h, t, r, tr) || !we_hoja_uniforms(h, t, rg, tg)) {
            printf("sin uniforms\n");
            continue;
        }
        printf("we %.9g %.9g %.9g %.9g %.9g %.9g gl %.9g %.9g %.9g %.9g %.9g %.9g\n",
               r[0], r[1], r[2], r[3], tr[0], tr[1],
               rg[0], rg[1], rg[2], rg[3], tg[0], tg[1]);
    }
    we_hoja_free(h);
    return 0;
}
"""


def compila(tmp: Path) -> Path:
    src = tmp / "arnes.c"
    src.write_text(ARNES)
    exe = tmp / "arnes"
    r = subprocess.run(
        ["cc", "-O1", "-std=c11", "-Wall", "-Wextra", f"-I{RAIZ}/src",
         "-o", str(exe), str(src), str(RAIZ / "src" / "wereloj.c")],
        capture_output=True, text=True)
    if r.returncode or r.stderr.strip():
        raise SystemExit("no compila el arnés sin avisos:\n" + r.stderr)
    return exe


def capa_y_hoja():
    """La capa 303 de la escena y su hoja: frames y el tamaño que se sube."""
    d = Path(wepaths.we_workshop()) / ESCENA
    _, ents = pkg_inspect.read_pkg(str(d / "scene.pkg"))
    j = json.loads([e for e in ents if e["name"] == "scene.json"][0]["data"])
    obj = [o for o in j["objects"] if o.get("id") == CAPA][0]
    res = AssetResolver.for_wallpaper(d, Path(wepaths.we_assets()))
    modelo = json.loads(res.read_bytes(obj["image"]))
    material = json.loads(res.read_bytes(modelo["material"]))
    nombre = material["passes"][0]["textures"][0]
    tex = wetex.read_texture(res.read_bytes(wescene.texture_path(nombre)))
    # Lo que se sube: la imagen recortada, como en `texture()`.
    mip = tex.images[0][0]
    iw, ih = tex.image_size
    return obj, tex, (min(mip.width, iw or mip.width), min(mip.height, ih or mip.height))


def corre(exe: Path, linea: str, locale: str, horas: list[int],
          tmp: Path) -> list[list[float]]:
    plan = tmp / "hoja.txt"
    plan.write_text(linea + "\n")
    # Los instantes son de un día en UTC y el arnés corre con TZ=UTC: la hora
    # local es la que se pide, sin depender de la zona de esta máquina.
    entrada = "".join(
        f"{int(dt.datetime(2026, 10, 10, h, 0, 0, tzinfo=dt.timezone.utc).timestamp())}\n"
        for h in horas)
    p = subprocess.run([str(exe), str(plan), locale], input=entrada,
                       capture_output=True, text=True,
                       env={**os.environ, "TZ": "UTC"})
    if p.returncode:
        raise SystemExit(f"el arnés falla [{locale}]: {p.stdout} {p.stderr}")
    salida = []
    for l in p.stdout.splitlines():
        t = l.split()
        if len(t) != 14:
            raise SystemExit(f"salida rara [{locale}]: {l!r}")
        salida.append([float(x) for x in t[1:7]] + [float(x) for x in t[8:14]])
    return salida


def cerca(a, b) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= TOLERANCIA for x, y in zip(a, b))


def main() -> int:
    fallos: list[str] = []
    obj, tex, (tw, th) = capa_y_hoja()
    print(f"── hoja de {ESCENA} capa {CAPA} ──")
    print(f"  textura {tw}x{th}, {len(tex.frames)} fotogramas: "
          + ", ".join(f"{f['width']:g}x{f['height']:g}@({f['x']:g},{f['y']:g})"
                      for f in tex.frames))
    if (tw, th) != (22, 40) or len(tex.frames) != 2:
        fallos.append(f"la hoja no es la de 22x40 con dos fotogramas: {tw}x{th}")

    tabla = wescript.hoja_por_hora(obj)
    print(f"  tabla {tabla}")
    if tabla != [0] * 12 + [1] * 12:
        fallos.append(f"tabla {tabla}")
        tabla = [0] * 12 + [1] * 12
    fot = werender.fotogramas_de_hoja(tex.frames, tw, th, max(tabla) + 1)
    linea = werender.linea_hojahora(True, fot, tabla)

    esperado_we = {9: [1, 0, 0, 0.5, 0, 0], 15: [1, 0, 0, 0.5, 0, 0.5]}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        exe = compila(tmp)
        p = subprocess.run([str(exe), "-", "es_ES.UTF-8"],
                           capture_output=True, text=True)
        print(f"  strtof(\"0.5\") sin guarda con es_ES: {p.stdout.strip() or p.returncode}")
        if p.returncode or float(p.stdout) != 0.0:
            fallos.append("la locale es_ES no muerde aquí: la prueba no "
                          "probaría la guarda")
        for locale in ("C", "es_ES.UTF-8"):
            horas = list(range(24))
            salida = corre(exe, linea, locale, horas, tmp)
            for h, fila in zip(horas, salida):
                we, gl = fila[:6], fila[6:]
                r, t = werender.volteo_de_hoja(fot[tabla[h]])
                if not cerca(we, fot[tabla[h]]):
                    fallos.append(f"[{locale}] {h:02d}:00 WE {we} != {fot[tabla[h]]}")
                if not cerca(gl, r + t):
                    fallos.append(f"[{locale}] {h:02d}:00 subidos {gl} != {r + t}")
                if h in esperado_we:
                    ok = cerca(we, esperado_we[h])
                    print(f"  {'ok' if ok else 'MAL':3} [{locale:11}] {h:02d}:00 "
                          f"rotación {we[:4]} traslación {we[4:]}  "
                          f"(se suben {gl[:4]} {gl[4:]})")
                    if not ok:
                        fallos.append(f"[{locale}] {h:02d}:00 da {we}, "
                                      f"no {esperado_we[h]}")

    # La línea que de verdad escribe werender para esta escena.
    with tempfile.TemporaryDirectory() as td:
        d = Path(wepaths.we_workshop()) / ESCENA
        p = subprocess.run(
            [sys.executable, str(RAIZ / "tools" / "werender.py"), str(d),
             str(Path(td) / "x.png"), "--emit-plan", str(Path(td) / "plan")],
            capture_output=True, text=True)
        plan = (Path(td) / "plan" / "plan.txt").read_text() if not p.returncode else ""
    del_plan = [l for l in plan.splitlines() if l.startswith("hojahora ")]
    print(f"  líneas hojahora en el plan: {len(del_plan)}")
    if del_plan != [linea]:
        fallos.append(f"el plan trae {del_plan!r}, no {linea!r}")

    # Los dos ejecutores llaman a la misma función.
    for f in ("tools/glexec.c", "src/glexecutor.cpp"):
        n = len(re.findall(r"\bwe_hoja_uniforms\s*\(", (RAIZ / f).read_text()))
        print(f"  {f:20} llama a we_hoja_uniforms {n} vez")
        if n < 1:
            fallos.append(f"{f} no llama a we_hoja_uniforms")

    if fallos:
        print(f"\nFALLO: {len(fallos)}")
        for f in fallos[:20]:
            print(f"  {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
