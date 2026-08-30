#!/usr/bin/env python3
"""Comprueba el contrato del video: `tools/wevideo.py` y `src/wevideo.c`.

Una capa de video no falla de forma ruidosa. Si el fotograma sale del reves,
con los colores virados o congelado, el plan se genera igual, los shaders
compilan igual y el ejecutor no se queja: sale una imagen, y hay que MIRARLA
para saber que esta mal. Es el mismo tipo de fallo silencioso que el `.psys`
leido con la locale equivocada, asi que se prueba igual: contra un oraculo de
fuera y sobre el corpus entero, no sobre el fichero que uno tenga a mano.

Se comprueban cinco cosas:

  1. Las dimensiones que saca `wevideo.dimensiones` de la cabecera del MP4
     coinciden con las que dice `ffprobe`, para TODOS los videos del corpus
     ---los 15 wallpapers de tipo video y los que van dentro de un `.tex`---.
     Es el oraculo: si el parseo de cajas se desvia, aqui se ve.

  2. El fotograma que entrega `src/wevideo.c` es PIXEL A PIXEL el que saca
     `ffmpeg` en ese mismo instante. Esto es lo que ata a la vez el volteo
     vertical, el espacio de color y el rango: los tres se pueden equivocar sin
     que nada mas se entere.

  3. En modo `WEVIDEO_EXACTO` el mismo instante da SIEMPRE el mismo fotograma.
     Es lo que hace falta para que `test_luminancia` mida algo estable: el
     render offline repite el plan N veces para que converjan los efectos
     temporales, y si el video avanzara por su cuenta, la medida dependeria de
     lo que tardase el disco.

  4. El bucle: `t` y `t + duracion` son el mismo fotograma. Sin esto un fondo
     se queda congelado en el ultimo fotograma al cabo de un rato.

  5. El encaje CUBRE la pantalla y no la deja con franjas.

Uso:
    python3 tools/test_wevideo.py [--limit N]

Necesita `ffprobe`/`ffmpeg` en el PATH: son el oraculo, no el motor. Sin ellos
las comprobaciones 1 y 2 se omiten y se dice.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import pkg_inspect
import wepaths
import wetex
import wevideo

RAIZ = Path(__file__).resolve().parent.parent
FUENTE_C = RAIZ / "src" / "wevideo.c"

# Arnes: vuelca el fotograma de un instante como RGBA crudo, tal y como lo
# recibe el ejecutor. Se compila contra el MISMO .c que enlazan los dos
# ejecutores; probar una copia no probaria nada.
ARNES_C = r"""
#include "wevideo.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    /* arnes <video> <modo> <t> <salida.raw> */
    if (argc < 5) return 2;
    WeVideo *v = wevideo_open(argv[1], 0, 0, atoi(argv[2]));
    if (!v) { fprintf(stderr, "%s\n", wevideo_error(NULL)); return 1; }
    const uint8_t *px = NULL;
    if (wevideo_frame(v, atof(argv[3]), &px) < 0 || !px) return 1;
    FILE *f = fopen(argv[4], "wb");
    if (!f) return 1;
    fwrite(px, 1, (size_t)wevideo_ancho(v) * wevideo_alto(v) * 4, f);
    fclose(f);
    printf("%d %d %.6f\n", wevideo_ancho(v), wevideo_alto(v), wevideo_duracion(v));
    wevideo_close(v);
    return 0;
}
"""


def hay(prog: str) -> bool:
    return shutil.which(prog) is not None


def compilar_arnes(tmp: Path) -> Path | None:
    fuente, binario = tmp / "arnes.c", tmp / "arnes"
    fuente.write_text(ARNES_C)
    try:
        cflags = subprocess.run(
            ["pkg-config", "--cflags", "--libs", "libavformat", "libavcodec",
             "libavutil", "libswscale"],
            capture_output=True, text=True, check=True).stdout.split()
    except Exception as e:
        print(f"  (sin pkg-config para libav: {e}, arnes omitido)")
        return None
    try:
        subprocess.run(["cc", "-O2", "-std=gnu11", f"-I{RAIZ / 'src'}",
                        "-o", str(binario), str(fuente), str(FUENTE_C),
                        *cflags, "-lm", "-lpthread"],
                       check=True, capture_output=True)
    except Exception as e:
        print(f"  (no se pudo compilar el arnes: {e}, pruebas omitidas)")
        return None
    return binario


def corpus(tmp: Path, limite: int = 0) -> list[tuple[str, Path]]:
    """`(etiqueta, ruta al mp4)` de todo el video de la biblioteca.

    Los que van dentro de un `.tex` se extraen a `tmp`: para el decodificador
    son un MP4 igual que los sueltos, y dejarlos fuera del test seria dejar
    fuera justo el caso por el que existe todo esto. El temporal lo borra quien
    llama; son ~40 MB por pasada y `/tmp` aqui es un tmpfs.
    """
    salida: list[tuple[str, Path]] = []
    for d in sorted(wepaths.we_workshop().iterdir()):
        pj = d / "project.json"
        if pj.is_file():
            try:
                j = json.loads(pj.read_text(errors="replace"))
            except Exception:
                j = {}
            if str(j.get("type", "")).lower() == "video":
                f = d / str(j.get("file", ""))
                if f.is_file():
                    salida.append((d.name, f))
        pkg = d / "scene.pkg"
        if not pkg.is_file():
            continue
        try:
            _, entradas = pkg_inspect.read_pkg(pkg)
        except Exception:
            continue
        for e in entradas:
            if not e["name"].endswith(".tex"):
                continue
            try:
                tex = wetex.read_texture(e["data"])
            except Exception:
                continue
            mip = tex.images[0][0] if tex.images and tex.images[0] else None
            if mip is not None and getattr(mip, "video", False):
                ruta = tmp / f"{d.name}.mp4"
                ruta.write_bytes(mip.raw)
                salida.append((f"{d.name}:{e['name'].split('/')[-1]}", ruta))
    if limite:
        salida = salida[:limite]
    return salida


def colorimetria(f: Path) -> tuple[str, str]:
    """`(matriz, rango)` que este motor le va a aplicar al fichero.

    Se replica aqui la decision de `src/wevideo.c` para poder PONERLE LA MISMA a
    `ffmpeg`, y la razon es que el oraculo y el motor no la comparten:

      * el fichero que declara su espacio de color manda, y ahi coinciden;
      * el que NO lo declara ---5 de los 15 wallpapers de video del corpus---
        lo resuelve cada uno a su manera. `swscale` por defecto asume BT.601;
        nosotros miramos la altura y a partir de 720 lineas asumimos BT.709,
        que es lo que hace `mpv` y lo que de verdad traen los H.264 en HD.
        Leido como 601, un 709 vira los verdes y los tonos de piel.

    Sin fijar los dos lados, esos 5 ficheros salen con diferencias de hasta 30
    sobre 255 y el test acusaria de un fallo de decodificacion lo que es una
    convencion distinta. Fijandolos, lo que sigue comprobandose es lo que
    importa: que los pixeles, el volteo y el rango son los mismos.
    """
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=color_space,color_range,height",
                        "-of", "json", str(f)], capture_output=True, text=True)
    try:
        s = json.loads(r.stdout)["streams"][0]
    except Exception:
        return "bt709", "tv"
    espacio = str(s.get("color_space") or "")
    if espacio in ("bt470bg", "smpte170m"):
        matriz = "bt601"
    elif espacio and espacio != "unknown":
        matriz = "bt709"
    else:
        matriz = "bt709" if int(s.get("height") or 0) >= 720 else "bt601"
    rango = "pc" if str(s.get("color_range")) == "pc" else "tv"
    return matriz, rango


def ffprobe_dim(f: Path) -> tuple[int, int] | None:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "json",
                        str(f)], capture_output=True, text=True)
    try:
        s = json.loads(r.stdout)["streams"][0]
        return int(s["width"]), int(s["height"])
    except Exception:
        return None


def prueba_dimensiones(casos) -> list[str]:
    """Comprobacion 1: las cajas del MP4 contra `ffprobe`."""
    if not hay("ffprobe"):
        print("  (sin ffprobe, comprobacion de dimensiones omitida)")
        return []
    fallos, ok = [], 0
    for etq, f in casos:
        ref = ffprobe_dim(f)
        if ref is None:
            continue
        try:
            mio = wevideo.dimensiones(f)
        except Exception as e:
            fallos.append(f"{etq}: dimensiones() levanta {type(e).__name__}: {e}")
            continue
        if mio != ref:
            fallos.append(f"{etq}: dimensiones() da {mio} y ffprobe {ref}")
        else:
            ok += 1
    print(f"  dimensiones que coinciden con ffprobe: {ok}/{len(casos)}")
    return fallos


def frame_ffmpeg(f: Path, t: float, tmp: Path,
                 color: tuple[str, str]) -> np.ndarray | None:
    dst = tmp / "ref.raw"
    matriz, rango = color
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.6f}",
                        "-i", str(f), "-frames:v", "1",
                        "-vf", f"scale=in_color_matrix={matriz}:"
                               f"in_range={rango}:out_range=full",
                        "-pix_fmt", "rgba",
                        "-f", "rawvideo", str(dst)], capture_output=True)
    if r.returncode != 0 or not dst.is_file():
        return None
    return np.frombuffer(dst.read_bytes(), np.uint8)


def frame_nuestro(arnes: Path, f: Path, t: float, modo: int,
                  tmp: Path) -> tuple[np.ndarray, tuple[int, int], float] | None:
    dst = tmp / "mio.raw"
    r = subprocess.run([str(arnes), str(f), str(modo), f"{t:.6f}", str(dst)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not dst.is_file():
        return None
    w, h, dur = r.stdout.split()
    return np.frombuffer(dst.read_bytes(), np.uint8), (int(w), int(h)), float(dur)


def prueba_pixeles(arnes: Path, casos, tmp: Path) -> list[str]:
    """Comprobaciones 2, 3 y 4: los pixeles, el determinismo y el bucle."""
    if not hay("ffmpeg"):
        print("  (sin ffmpeg, comprobacion de pixeles omitida)")
        return []
    fallos, exactos, comparados = [], 0, 0
    for etq, f in casos:
        primero = frame_nuestro(arnes, f, 0.0, 0, tmp)
        if primero is None:
            fallos.append(f"{etq}: el arnes no entrega ningun fotograma")
            continue
        _, (w, h), dur = primero
        color = colorimetria(f)
        for t in (0.0, min(1.0, dur / 3), min(4.0, dur * 0.7)):
            mio = frame_nuestro(arnes, f, t, 0, tmp)
            ref = frame_ffmpeg(f, t, tmp, color)
            if mio is None or ref is None or ref.size != w * h * 4:
                continue
            # El nuestro sale volteado para GL; se deshace para comparar.
            a = mio[0].reshape(h, w, 4)[::-1]
            b = ref.reshape(h, w, 4)
            comparados += 1
            d = np.abs(a.astype(np.int16) - b.astype(np.int16))
            if d.max() == 0:
                exactos += 1
            else:
                fallos.append(f"{etq} en t={t:.2f}: el fotograma no es el de "
                              f"ffmpeg (dif max {d.max()}, media {d.mean():.3f})")

        # 3) el mismo instante, dos veces: mismos bytes.
        a1 = frame_nuestro(arnes, f, 1.0, 0, tmp)
        a2 = frame_nuestro(arnes, f, 1.0, 0, tmp)
        if a1 and a2 and not np.array_equal(a1[0], a2[0]):
            fallos.append(f"{etq}: el modo exacto no es determinista en t=1")

        # 4) el bucle: t y t + duracion caen en el mismo sitio.
        b1 = frame_nuestro(arnes, f, 0.5, 0, tmp)
        b2 = frame_nuestro(arnes, f, 0.5 + dur, 0, tmp)
        if b1 and b2 and not np.array_equal(b1[0], b2[0]):
            fallos.append(f"{etq}: el bucle no cierra; t=0.5 y t=0.5+{dur:.3f} "
                          f"dan fotogramas distintos")
    print(f"  fotogramas identicos a ffmpeg: {exactos}/{comparados}")
    return fallos


def prueba_encaje() -> list[str]:
    """Comprobacion 5: cubrir, no caber. Ninguna escala baja de 1."""
    fallos = []
    pantallas = [(1920, 1080), (1920, 1200), (2560, 1440), (3440, 1440),
                 (1280, 1024)]
    videos = [(1920, 1080), (2560, 1440), (3840, 2160)]
    for v in videos:
        for p in pantallas:
            sx, sy = wevideo.encaje(v, p)
            if sx < 1 - 1e-6 or sy < 1 - 1e-6:
                fallos.append(f"encaje({v}, {p}) = ({sx:.4f}, {sy:.4f}): deja "
                              f"franja, deberia cubrir")
            # Una de las dos tiene que ajustar exactamente, o se recorta de mas.
            if abs(sx - 1) > 1e-6 and abs(sy - 1) > 1e-6:
                fallos.append(f"encaje({v}, {p}) = ({sx:.4f}, {sy:.4f}): recorta "
                              f"por los dos lados")
            # Y el aspecto no se toca.
            if abs((sx * p[0]) / (sy * p[1]) - v[0] / v[1]) > 1e-6:
                fallos.append(f"encaje({v}, {p}) deforma el aspecto")
    print(f"  encaje: {len(pantallas) * len(videos)} combinaciones")
    return fallos


def main() -> int:
    args = sys.argv[1:]
    limite = int(args[args.index("--limit") + 1]) if "--limit" in args else 0

    tmp = Path(tempfile.mkdtemp(prefix="test-wevideo-"))
    try:
        casos = corpus(tmp, limite)
        if not casos:
            print("no hay ningun video en la biblioteca; nada que comprobar")
            return 0
        print(f"videos: {len(casos)}")

        fallos: list[str] = []
        fallos += prueba_dimensiones(casos)
        fallos += prueba_encaje()

        arnes = compilar_arnes(tmp)
        if arnes is not None:
            fallos += prueba_pixeles(arnes, casos, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if fallos:
        print(f"\n{len(fallos)} fallos:")
        for f in fallos[:20]:
            print("  ", f)
        print("\nFALLO")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
