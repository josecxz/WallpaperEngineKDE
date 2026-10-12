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

Y la hoja que corre sola por su `frame_time` (la línea `hojatiempo`):

  4. Con la hoja real de la capa 389 de `2262142032` (dos fotogramas de
     0,26 s), en `C` y en `es_ES`: a 0,10 s el fotograma 0, a 0,36 s el 1 y a
     0,62 s otra vez el 0, porque es un bucle; y los uniforms que se suben, a
     1e-6 de `werender.volteo_de_hoja`.
  5. Que el plan de `2262142032` trae esa línea en el pase de la capa, sin
     `#define spritesheet`/`version` en minúsculas, y que los dos ejecutores
     llaman a `we_hoja_tiempo_uniforms`.

Y la que reparte sus fotogramas entre varias imágenes del `.tex` (la línea
`hojaimagenes`, que es una `hojatiempo` con la textura de cada fotograma):

  6. Con la hoja real de la capa 983 de `2262142032` (167 fotogramas de
     0,04 s: 119 en la imagen 0, de 2048x2048, y 48 en la 1, de 2048x1024),
     en `C` y en `es_ES`: en instantes de fotogramas de la imagen 0 (también
     uno girado) y de la 1, `we_hoja_tiempo_textura` da la textura de la
     imagen del fotograma, y los uniforms están a 1e-6 de los que calcula
     Python partiendo por el tamaño de ESA imagen ---y no a 1e-6 de los que
     saldrían con el de la 0, para que la prueba distinga---. Leída de
     `hojatiempo`, la misma hoja da textura -1 (la del sampler), y lo que va
     detrás de `hojatiempo` no se lee como `hojaimagenes`.
  7. Que en el plan de `2262142032` la capa (y la 1017, que tiene la misma
     tabla) lleva su `hojaimagenes`, con dos
     texturas que siguen al `image_id`, y que los dos ejecutores llaman a
     `we_hoja_tiempo_textura`.

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


ARNES_TIEMPO = r"""
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wereloj.h"

/* argv[1]: un fichero con la línea `hojatiempo` del plan; argv[2]: la locale
 * con la que se LEE. Por la entrada, un instante de escena por línea; por la
 * salida, el fotograma y los uniforms que se suben. */
int main(int argc, char **argv)
{
    if (argc > 2 && !setlocale(LC_ALL, argv[2]))
        return 4;
    FILE *f = fopen(argv[1], "r");
    if (!f) return 2;
    static char linea[65536];
    if (!fgets(linea, sizeof linea, f)) return 2;
    fclose(f);
    const char *p = linea;
    while (*p && *p != ' ') p++;           /* fuera `hojatiempo` */
    WeHoja *h = we_hoja_nueva();
    if (!we_hoja_tiempo_linea(h, p)) {
        printf("no la lee\n");
        return 3;
    }
    /* Leída por tiempo, no tiene tabla por hora. */
    float r[4], tr[2];
    if (we_hoja_uniforms(h, 0, r, tr)) {
        printf("tambien por hora\n");
        return 5;
    }
    setlocale(LC_ALL, "C");
    char pet[64];
    while (fgets(pet, sizeof pet, stdin)) {
        double t = strtod(pet, NULL);
        if (!we_hoja_tiempo_uniforms(h, t, r, tr)) {
            printf("sin uniforms\n");
            continue;
        }
        printf("%d %.9g %.9g %.9g %.9g %.9g %.9g\n", we_hoja_fotograma_en(h, t),
               r[0], r[1], r[2], r[3], tr[0], tr[1]);
    }
    we_hoja_free(h);
    return 0;
}
"""


ARNES_IMAGENES = r"""
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wereloj.h"

/* argv[1]: un fichero con la hoja como `hojatiempo` y, debajo, como
 * `hojaimagenes`; argv[2]: la locale con la que se LEE. Por la entrada, un
 * instante de escena por línea; por la salida, el fotograma, la textura y los
 * uniforms. */
int main(int argc, char **argv)
{
    if (argc > 2 && !setlocale(LC_ALL, argv[2]))
        return 4;
    FILE *f = fopen(argv[1], "r");
    if (!f) return 2;
    static char tiempo[65536], imagenes[65536];
    if (!fgets(tiempo, sizeof tiempo, f) || !fgets(imagenes, sizeof imagenes, f))
        return 2;
    fclose(f);
    const char *p = tiempo, *q = imagenes;
    while (*p && *p != ' ') p++;           /* fuera `hojatiempo` */
    while (*q && *q != ' ') q++;           /* fuera `hojaimagenes` */
    WeHoja *h = we_hoja_nueva();
    /* Leída de `hojatiempo`, la textura es la del sampler. */
    if (!we_hoja_tiempo_linea(h, p) || we_hoja_tiempo_textura(h, 0.0) != -1) {
        printf("hojatiempo con textura\n");
        return 5;
    }
    /* Siete números por fotograma no son una `hojaimagenes`. */
    if (we_hoja_imagenes_linea(h, p)) {
        printf("lee hojatiempo como hojaimagenes\n");
        return 6;
    }
    if (!we_hoja_imagenes_linea(h, q)) {
        printf("no lee hojaimagenes\n");
        return 7;
    }
    setlocale(LC_ALL, "C");
    char pet[64];
    float r[4], tr[2];
    while (fgets(pet, sizeof pet, stdin)) {
        double t = strtod(pet, NULL);
        if (!we_hoja_tiempo_uniforms(h, t, r, tr)) {
            printf("sin uniforms\n");
            continue;
        }
        printf("%d %d %.9g %.9g %.9g %.9g %.9g %.9g\n",
               we_hoja_fotograma_en(h, t), we_hoja_tiempo_textura(h, t),
               r[0], r[1], r[2], r[3], tr[0], tr[1]);
    }
    we_hoja_free(h);
    return 0;
}
"""


def compila(tmp: Path, arnes: str = ARNES, nombre: str = "arnes") -> Path:
    src = tmp / f"{nombre}.c"
    src.write_text(arnes)
    exe = tmp / nombre
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


ESCENA_TIEMPO = "2262142032"
CAPA_TIEMPO = 389
# Instante de escena -> fotograma que toca: 0,26 s cada uno y vuelta al 0.
ESPERADO_TIEMPO = {0.10: 0, 0.36: 1, 0.62: 0}


def hoja_de_capa(escena: str, capa: int):
    """La hoja de la capa y el tamaño que se sube, como en `capa_y_hoja`."""
    d = Path(wepaths.we_workshop()) / escena
    _, ents = pkg_inspect.read_pkg(str(d / "scene.pkg"))
    j = json.loads([e for e in ents if e["name"] == "scene.json"][0]["data"])
    obj = [o for o in j["objects"] if o.get("id") == capa][0]
    res = AssetResolver.for_wallpaper(d, Path(wepaths.we_assets()))
    modelo = json.loads(res.read_bytes(obj["image"]))
    material = json.loads(res.read_bytes(modelo["material"]))
    nombre = material["passes"][0]["textures"][0]
    tex = wetex.read_texture(res.read_bytes(wescene.texture_path(nombre)))
    mip = tex.images[0][0]
    iw, ih = tex.image_size
    return obj, tex, (min(mip.width, iw or mip.width), min(mip.height, ih or mip.height))


def prueba_por_tiempo(fallos: list[str]) -> None:
    """Los puntos 4 y 5 de arriba."""
    obj, tex, (tw, th) = hoja_de_capa(ESCENA_TIEMPO, CAPA_TIEMPO)
    dur = [f["frame_time"] for f in tex.frames]
    print(f"\n── hoja por frame_time de {ESCENA_TIEMPO} capa {CAPA_TIEMPO} ──")
    print(f"  textura {tw}x{th}, {len(tex.frames)} fotogramas de "
          + ", ".join(f"{d:.6g}" for d in dur) + " s, "
          f"{len(tex.images)} imagen, scripts con getTextureAnimation: "
          f"{wescript.mueve_la_hoja(obj)}")
    if len(tex.frames) != 2 or any(abs(d - 0.26) > 1e-6 for d in dur):
        fallos.append(f"la hoja no es la de dos fotogramas de 0,26 s: {dur}")
    fot = werender.fotogramas_de_hoja(tex.frames, tw, th, len(tex.frames))
    linea = werender.linea_hojatiempo(True, fot, dur)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        exe = compila(tmp, ARNES_TIEMPO, "arnes_tiempo")
        for locale in ("C", "es_ES.UTF-8"):
            plan = tmp / "hoja.txt"
            plan.write_text(linea + "\n")
            p = subprocess.run([str(exe), str(plan), locale],
                               input="".join(f"{t}\n" for t in ESPERADO_TIEMPO),
                               capture_output=True, text=True)
            if p.returncode:
                fallos.append(f"el arnés de tiempo falla [{locale}]: {p.stdout} {p.stderr}")
                continue
            for (t, quiero), l in zip(ESPERADO_TIEMPO.items(), p.stdout.splitlines()):
                c = l.split()
                i, gl = int(c[0]), [float(x) for x in c[1:7]]
                r, tr = werender.volteo_de_hoja(fot[quiero])
                ok = i == quiero and cerca(gl, r + tr)
                print(f"  {'ok' if ok else 'MAL':3} [{locale:11}] t={t:.2f} s "
                      f"fotograma {i} (toca {quiero})  se suben {gl[:4]} {gl[4:]}")
                if not ok:
                    fallos.append(f"[{locale}] t={t} da {i} {gl}, no {quiero} {r + tr}")

    # El plan de la escena: la línea, en el pase de la capa, y los combos.
    with tempfile.TemporaryDirectory() as td:
        d = Path(wepaths.we_workshop()) / ESCENA_TIEMPO
        p = subprocess.run(
            [sys.executable, str(RAIZ / "tools" / "werender.py"), str(d),
             str(Path(td) / "x.png"), "--emit-plan", str(Path(td) / "plan")],
            capture_output=True, text=True)
        dir_plan = Path(td) / "plan"
        plan = (dir_plan / "plan.txt").read_text() if not p.returncode else ""
        minusculas = [f.name for f in sorted(dir_plan.glob("*.vert")) + sorted(dir_plan.glob("*.frag"))
                      if re.search(r"#define (spritesheet|version)\b", f.read_text())]
        vert = None
        for bloque in plan.split("\npass\n"):
            if linea in bloque.splitlines():
                vert = Path(re.search(r"^prog (\S+)", bloque, re.M).group(1))
                vert = vert.read_text() if vert.is_file() else ""
    print(f"  la línea de la capa en el plan: {'sí' if vert is not None else 'NO'}; "
          f"#define SPRITESHEET 1 en su .vert: "
          f"{'sí' if vert and '#define SPRITESHEET 1' in vert else 'NO'}; "
          f"ficheros con combos en minúsculas: {len(minusculas)}")
    if vert is None:
        fallos.append("el plan de 2262142032 no trae la hojatiempo de la capa 389")
    elif "#define SPRITESHEET 1" not in vert:
        fallos.append("el .vert de la capa 389 no enciende SPRITESHEET")
    if minusculas:
        fallos.append(f"combos en minúsculas en {minusculas}")

    for f in ("tools/glexec.c", "src/glexecutor.cpp"):
        n = len(re.findall(r"\bwe_hoja_tiempo_uniforms\s*\(", (RAIZ / f).read_text()))
        print(f"  {f:20} llama a we_hoja_tiempo_uniforms {n} vez")
        if n < 1:
            fallos.append(f"{f} no llama a we_hoja_tiempo_uniforms")


CAPA_IMAGENES = 983
# Instantes de escena (el centro de un fotograma de 0,04 s): el 0 y el 47 de
# la imagen 0, el 115 girado de la 0, el 119 ---el primero de la 1---, el 128
# y el último, y el 47 otra vez en la segunda vuelta.
INSTANTES_IMAGENES = (0.02, 1.90, 4.62, 4.78, 5.14, 6.66, 8.58)
# Las texturas que se dan a cada imagen en la línea de prueba: cualquier
# número que no sea el índice sirve para ver que se devuelve el del plan.
TEXTURA_DE_IMAGEN = 100


def prueba_varias_imagenes(fallos: list[str]) -> None:
    """Los puntos 6 y 7 de arriba."""
    d = Path(wepaths.we_workshop()) / ESCENA_TIEMPO
    obj, tex, (tw, th) = hoja_de_capa(ESCENA_TIEMPO, CAPA_IMAGENES)
    dur = [f["frame_time"] for f in tex.frames]
    imgs = [int(f["image_id"]) for f in tex.frames]
    # Lo que se sube de cada imagen: recortada a `image_size`, como en `texture()`.
    iw, ih = tex.image_size
    tam = [(min(im[0].width, iw or im[0].width), min(im[0].height, ih or im[0].height))
           for im in tex.images]
    print(f"\n── hoja de varias imágenes de {ESCENA_TIEMPO} capa {CAPA_IMAGENES} ──")
    print(f"  {len(tex.frames)} fotogramas, por imagen "
          f"{ {k: imgs.count(k) for k in sorted(set(imgs))} }, imágenes "
          + ", ".join(f"{w}x{h}" for w, h in tam)
          + f", scripts con getTextureAnimation: {wescript.mueve_la_hoja(obj)}")
    if len(tam) != 2 or tam[0][1] == tam[1][1] or set(imgs) != {0, 1}:
        fallos.append(f"la hoja no es la de dos imágenes de distinto alto: {tam}")
    fot = [werender.fotogramas_de_hoja([f], *tam[k], 1)[0]
           for f, k in zip(tex.frames, imgs)]
    con_la_0 = werender.fotogramas_de_hoja(tex.frames, tw, th, len(tex.frames))
    tiempo = werender.linea_hojatiempo(True, fot, dur)
    linea = werender.linea_hojaimagenes(True, fot, dur,
                                        [TEXTURA_DE_IMAGEN + k for k in imgs])

    total = sum(dur)
    vistas = set()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        exe = compila(tmp, ARNES_IMAGENES, "arnes_imagenes")
        plan = tmp / "hoja.txt"
        plan.write_text(tiempo + "\n" + linea + "\n")
        for locale in ("C", "es_ES.UTF-8"):
            p = subprocess.run([str(exe), str(plan), locale],
                               input="".join(f"{t}\n" for t in INSTANTES_IMAGENES),
                               capture_output=True, text=True)
            if p.returncode:
                fallos.append(f"el arnés de imágenes falla [{locale}]: {p.stdout} {p.stderr}")
                continue
            for t, l in zip(INSTANTES_IMAGENES, p.stdout.splitlines()):
                c = l.split()
                i, textura = int(c[0]), int(c[1])
                gl = [float(x) for x in c[2:8]]
                quiero = int((t % total) / 0.04)
                r, tr = werender.volteo_de_hoja(fot[quiero])
                r0, tr0 = werender.volteo_de_hoja(con_la_0[quiero])
                distinto = imgs[quiero] == 0 or not cerca(gl, r0 + tr0)
                ok = (i == quiero and textura == TEXTURA_DE_IMAGEN + imgs[quiero]
                      and cerca(gl, r + tr) and distinto)
                vistas.add(imgs[quiero])
                print(f"  {'ok' if ok else 'MAL':3} [{locale:11}] t={t:.2f} s "
                      f"fotograma {i} (toca {quiero}, imagen {imgs[quiero]}"
                      f"{', girado' if tex.frames[quiero]['width'] == 0 else ''}) "
                      f"textura {textura}  se suben {gl[:4]} {gl[4:]}")
                if not ok:
                    fallos.append(f"[{locale}] t={t} da {i} {textura} {gl}, no "
                                  f"{quiero} {TEXTURA_DE_IMAGEN + imgs[quiero]} {r + tr}")
    if vistas != {0, 1}:
        fallos.append(f"los instantes no cubren las dos imágenes: {vistas}")

    # El plan de la escena: la `hojaimagenes` de la capa, con las texturas
    # que le hayan tocado. Las mismas cifras y duraciones que la de prueba;
    # la 1017 tiene la misma tabla, así que salen las dos.
    with tempfile.TemporaryDirectory() as td:
        p = subprocess.run(
            [sys.executable, str(RAIZ / "tools" / "werender.py"), str(d),
             str(Path(td) / "x.png"), "--emit-plan", str(Path(td) / "plan")],
            capture_output=True, text=True)
        plan = (Path(td) / "plan" / "plan.txt").read_text() if not p.returncode else ""
    sin_tex = [x for k, x in enumerate(linea.split()[3:]) if k % 8 != 7]
    todas = []
    for l in plan.splitlines():
        c = l.split()
        if c[:3] == linea.split()[:3] and [x for k, x in enumerate(c[3:])
                                           if k % 8 != 7] == sin_tex:
            todas.append([int(x) for x in c[3:][7::8]])
    # Dos texturas y dos imágenes, y cada imagen siempre con la misma.
    siguen = [len(ids) == len(imgs) and len(set(ids)) == 2
              and len(set(zip(imgs, ids))) == 2 for ids in todas]
    print(f"  líneas hojaimagenes con la tabla de la capa en el plan: {len(todas)}; "
          f"texturas {[sorted(set(ids)) for ids in todas]}, que siguen al "
          f"image_id: {sum(siguen)}")
    if not todas or not all(siguen):
        fallos.append("el plan de 2262142032 no trae la hojaimagenes de la capa 983 "
                      "siguiendo al image_id")

    for f in ("tools/glexec.c", "src/glexecutor.cpp"):
        n = len(re.findall(r"\bwe_hoja_tiempo_textura\s*\(", (RAIZ / f).read_text()))
        print(f"  {f:20} llama a we_hoja_tiempo_textura {n} vez")
        if n < 1:
            fallos.append(f"{f} no llama a we_hoja_tiempo_textura")


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

    prueba_por_tiempo(fallos)
    prueba_varias_imagenes(fallos)

    if fallos:
        print(f"\nFALLO: {len(fallos)}")
        for f in fallos[:20]:
            print(f"  {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
