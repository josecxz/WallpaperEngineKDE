#!/usr/bin/env python3
"""Lado Python del video: lo que hay que saber de un MP4 ANTES de decodificarlo.

Mismo reparto que `weparticles.py` frente a `src/weparticles.c`: aqui vive lo
que hay que **decidir**, y decodificar lo hace el C que comparten los dos
ejecutores. Lo unico que se decide de un video es como encaja en la pantalla, y
para eso basta con su tamano.

Por que no se pregunta a `ffprobe`: hasta hace nada una capa de video se
resolvia llamando a `ffmpeg` para congelar su primer fotograma, y eso ataba la
generacion del plan a que hubiera un binario de ffmpeg en el PATH. Ahora la
decodificacion la hace `libavcodec` dentro del motor, y seria un paso atras
volver a necesitar el ejecutable para leer dos enteros que estan en la cabecera
del fichero.

Lo que se lee es la caja `tkhd` de ISO-BMFF, que da el tamano de PRESENTACION
--- ya con la correccion de aspecto aplicada, que es justo lo que hace falta
para encajarlo--- y no el tamano codificado de `stsd`.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


class VideoError(Exception):
    pass


def _cajas(buf: bytes, ini: int, fin: int):
    """Recorre las cajas de ISO-BMFF entre `ini` y `fin`: (tipo, datos, fin)."""
    p = ini
    while p + 8 <= fin:
        (tam,) = struct.unpack_from(">I", buf, p)
        tipo = buf[p + 4:p + 8]
        cuerpo = p + 8
        if tam == 1:
            # Caja grande: el tamano de verdad son 8 bytes detras del tipo.
            if cuerpo + 8 > fin:
                return
            (tam,) = struct.unpack_from(">Q", buf, cuerpo)
            cuerpo += 8
        elif tam == 0:
            tam = fin - p          # hasta el final del fichero
        if tam < 8 or p + tam > fin:
            return
        yield tipo, cuerpo, p + tam
        p += tam


def _tkhd(buf: bytes, ini: int, fin: int) -> tuple[int, int] | None:
    """Tamano de presentacion de una pista, o None si no lo declara."""
    if fin - ini < 4:
        return None
    version = buf[ini]
    # Los campos que hay antes de la matriz cambian de ancho con la version.
    salto = 4 + (32 if version == 1 else 20) + 8 + 8 + 36
    if ini + salto + 8 > fin:
        return None
    w, h = struct.unpack_from(">II", buf, ini + salto)
    # 16.16 en coma fija. Una pista de audio los trae a cero, y ese es
    # justamente el modo de distinguirla sin mirar su `hdlr`.
    w, h = w >> 16, h >> 16
    return (w, h) if w > 0 and h > 0 else None


def dimensiones(ruta: str | Path | bytes) -> tuple[int, int]:
    """`(ancho, alto)` de la primera pista con imagen. Levanta si no hay.

    Se lee el fichero entero: los MP4 del corpus van de 9 MB a 560 MB y buscar
    `moov` a saltos no ahorra nada frente a leerlo una vez en la generacion del
    plan, que ya decodifica texturas de decenas de MB.
    """
    buf = ruta if isinstance(ruta, bytes) else Path(ruta).read_bytes()
    for tipo, ini, fin in _cajas(buf, 0, len(buf)):
        if tipo != b"moov":
            continue
        for t2, i2, f2 in _cajas(buf, ini, fin):
            if t2 != b"trak":
                continue
            for t3, i3, f3 in _cajas(buf, i2, f2):
                if t3 == b"tkhd":
                    d = _tkhd(buf, i3, f3)
                    if d:
                        return d
    raise VideoError("sin pista de video: no hay `tkhd` con tamano")


def encaje(video: tuple[int, int], pantalla: tuple[int, int]) -> tuple[float, float]:
    """Escala (sx, sy) para que el video CUBRA la pantalla sin deformarse.

    Cubrir y no caber: un fondo con franjas negras arriba y abajo no es un
    fondo. El corpus es todo 16:9 y una pantalla 16:10 le recorta un 11 % de
    alto, que es lo que hace el propio Wallpaper Engine.

    Se devuelve la escala del QUAD, no de las UV: el quad se pasa de la
    pantalla y el recorte lo hace el viewport, que es exacto y gratis.
    """
    vw, vh = video
    pw, ph = pantalla
    if vw <= 0 or vh <= 0 or pw <= 0 or ph <= 0:
        return 1.0, 1.0
    escala = max(pw / vw, ph / vh)
    return vw * escala / pw, vh * escala / ph


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for f in sys.argv[1:]:
        try:
            w, h = dimensiones(f)
            print(f"{w:5d}x{h:<5d}  {f}")
        except (VideoError, OSError, struct.error) as e:
            print(f"  fallo: {f}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
