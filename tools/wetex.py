#!/usr/bin/env python3
"""Decodificador del formato .tex de Wallpaper Engine.

Implementacion de referencia. El objetivo es fijar el formato con algo que
se pueda validar a ojo (exporta PNG) antes de portarlo a C++ para el motor.

Estructura del fichero
----------------------
    str   "TEXV0005"          version del contenedor externo
    str   "TEXI0001"          version de la cabecera de imagen
    u32   format              ver TexFormat
    u32   flags               ver TexFlags
    u32   textureWidth        tamano real en GPU (potencia de dos)
    u32   textureHeight
    u32   imageWidth          tamano util dentro de la textura
    u32   imageHeight
    [u32  depth]              SOLO si flags & IS_VOLUME (LUTs 3D)
    u32   dominantColor       ARGB
    str   "TEXB000{1..4}"     version del contenedor de imagenes
    u32   imageCount
    [u32  freeImageFormat]    si version >= 2; -1 = datos crudos,
                              >= 0 = fichero de imagen embebido (13 = PNG)
    [u32  reserved]           SOLO en version 4
    por imagen:
        u32 mipmapCount
        por mipmap:
            u32 width
            u32 height
            [u32 isLZ4Compressed]    si version >= 2
            [u32 decompressedSize]   si version >= 2
            u32 dataSize
            u8[dataSize] data
    [str "TEXS000{1..3}" + frames]   si la textura esta animada

Las cadenas son ASCII terminadas en NUL, no llevan prefijo de longitud
(a diferencia de las del contenedor .pkg, que si lo llevan).
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from pathlib import Path

import numpy as np


class TexFormat(IntEnum):
    RGBA8888 = 0
    DXT5 = 4
    DXT3 = 6
    DXT1 = 7
    RG88 = 8
    R8 = 9
    RG1616F = 10
    R16F = 11


class TexFlags(IntFlag):
    NO_INTERPOLATION = 1
    CLAMP_UVS = 2
    IS_GIF = 4
    # El payload del mipmap es un MP4 (H.264) entero, no pixeles. La cabecera
    # sigue declarando un `format` de pixel que hay que ignorar: si se hace
    # caso, el resultado es ruido en vez de un error.
    IS_VIDEO = 0x20
    # Observado en materials/lut/*.tex: anade un campo de profundidad a la
    # cabecera y convierte la textura en un volumen 3D aplanado.
    IS_VOLUME = 0x40


class TexError(Exception):
    pass


# ── LZ4 ──────────────────────────────────────────────────────────────────
# Formato de bloque (no frame): sin cabecera magica ni checksums. El tamano
# de salida viene del contenedor, asi que no hace falta parsearlo.

def lz4_decompress(src: bytes, dst_size: int) -> bytes:
    dst = bytearray(dst_size)
    s, d, n = 0, 0, len(src)

    while s < n:
        token = src[s]
        s += 1

        lit_len = token >> 4
        if lit_len == 15:
            while True:
                b = src[s]
                s += 1
                lit_len += b
                if b != 255:
                    break

        if lit_len:
            dst[d:d + lit_len] = src[s:s + lit_len]
            s += lit_len
            d += lit_len

        # El ultimo bloque termina tras los literales, sin secuencia de match.
        if s >= n:
            break

        offset = src[s] | (src[s + 1] << 8)
        s += 2
        if offset == 0:
            raise TexError("offset LZ4 nulo")

        match_len = token & 0x0F
        if match_len == 15:
            while True:
                b = src[s]
                s += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4  # minimo de match del formato

        p = d - offset
        if offset >= match_len:
            # Sin solape: se puede copiar de una pasada.
            dst[d:d + match_len] = dst[p:p + match_len]
            d += match_len
        else:
            # Solape intencionado (patron repetido): byte a byte.
            for _ in range(match_len):
                dst[d] = dst[p]
                d += 1
                p += 1

    if d != dst_size:
        raise TexError(f"LZ4: se esperaban {dst_size} B, se obtuvieron {d}")
    return bytes(dst)


# ── Descompresion de bloques BC/DXT ──────────────────────────────────────
# Todas devuelven RGBA8888. Vectorizado por bloques con numpy: hacerlo con
# bucles en Python sobre una textura de 4K tarda minutos.

def _bc_colors(blocks: np.ndarray, opaque: bool):
    """Decodifica la mitad de color (8 B) de un bloque BC1/2/3.

    blocks: (N, 8) uint8. Devuelve (N, 16, 4) uint8 RGBA.
    """
    c0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
    c1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)

    def unpack565(c):
        r = ((c >> 11) & 0x1F).astype(np.uint32)
        g = ((c >> 5) & 0x3F).astype(np.uint32)
        b = (c & 0x1F).astype(np.uint32)
        # Replicado de bits altos: mas exacto que un simple desplazamiento.
        return np.stack([(r << 3) | (r >> 2),
                         (g << 2) | (g >> 4),
                         (b << 3) | (b >> 2)], axis=-1)

    p0, p1 = unpack565(c0), unpack565(c1)
    pal = np.zeros((len(blocks), 4, 4), dtype=np.uint32)
    pal[:, 0, :3], pal[:, 1, :3] = p0, p1
    pal[:, 0, 3] = pal[:, 1, 3] = 255

    # En BC1 el orden de c0/c1 selecciona el modo; en BC2/BC3 siempre es el
    # de 4 colores porque el alfa va aparte.
    four = (c0 > c1) | opaque
    f = four[:, None]

    a = (2 * p0 + p1 + 1) // 3
    b = (p0 + 2 * p1 + 1) // 3
    h = (p0 + p1) // 2

    pal[:, 2, :3] = np.where(f, a, h)
    pal[:, 3, :3] = np.where(f, b, 0)
    pal[:, 2, 3] = 255
    pal[:, 3, 3] = np.where(four, 255, 0)  # modo 3 colores: indice 3 = transparente

    bits = (blocks[:, 4].astype(np.uint32)
            | (blocks[:, 5].astype(np.uint32) << 8)
            | (blocks[:, 6].astype(np.uint32) << 16)
            | (blocks[:, 7].astype(np.uint32) << 24))
    idx = (bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))[None, :]) & 3

    return np.take_along_axis(pal, idx[:, :, None], axis=1).astype(np.uint8)


def _decode_bc(data: bytes, width: int, height: int, kind: int) -> np.ndarray:
    """kind: 1 = BC1/DXT1, 2 = BC2/DXT3, 3 = BC3/DXT5."""
    bw, bh = (width + 3) // 4, (height + 3) // 4
    stride = 8 if kind == 1 else 16
    need = bw * bh * stride
    if len(data) < need:
        raise TexError(f"BC{kind}: faltan datos ({len(data)} < {need})")

    raw = np.frombuffer(data[:need], dtype=np.uint8).reshape(bw * bh, stride)
    color_half = raw if kind == 1 else raw[:, 8:]
    px = _bc_colors(color_half, opaque=(kind != 1))

    if kind == 2:  # BC2: 4 bits de alfa por pixel, sin interpolar
        al = raw[:, :8]
        nib = np.zeros((len(raw), 16), dtype=np.uint8)
        nib[:, 0::2] = al & 0x0F
        nib[:, 1::2] = al >> 4
        px[:, :, 3] = nib * 17  # 0..15 -> 0..255
    elif kind == 3:  # BC3: dos extremos + indices de 3 bits interpolados
        a0 = raw[:, 0].astype(np.uint16)
        a1 = raw[:, 1].astype(np.uint16)
        abits = np.zeros(len(raw), dtype=np.uint64)
        for i in range(6):
            abits |= raw[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
        aidx = (abits[:, None] >> (3 * np.arange(16, dtype=np.uint64))[None, :]) & np.uint64(7)

        apal = np.zeros((len(raw), 8), dtype=np.uint16)
        apal[:, 0], apal[:, 1] = a0, a1
        eight = a0 > a1
        for i in range(1, 7):
            # 8 valores si a0 > a1, si no 6 valores + 0 y 255 fijos
            v8 = ((7 - i) * a0 + i * a1) // 7
            v6 = ((5 - i) * a0 + i * a1) // 5 if i < 6 else 0
            apal[:, i + 1] = np.where(eight, v8, v6)
        apal[:, 6] = np.where(eight, apal[:, 6], 0)
        apal[:, 7] = np.where(eight, apal[:, 7], 255)
        px[:, :, 3] = np.take_along_axis(apal, aidx.astype(np.intp), axis=1).astype(np.uint8)

    # Recomponer los bloques 4x4 en la imagen final y recortar al tamano util.
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return img[:height, :width]


# ── Formatos sin comprimir ───────────────────────────────────────────────

def _decode_plain(data: bytes, width: int, height: int, fmt: TexFormat) -> np.ndarray:
    n = width * height
    out = np.zeros((n, 4), dtype=np.uint8)
    out[:, 3] = 255

    if fmt is TexFormat.RGBA8888:
        need = n * 4
        if len(data) < need:
            raise TexError(f"RGBA8888: faltan datos ({len(data)} < {need})")
        return np.frombuffer(data[:need], dtype=np.uint8).reshape(height, width, 4)

    if fmt is TexFormat.R8:
        a = np.frombuffer(data[:n], dtype=np.uint8)
        out[:, 0] = out[:, 1] = out[:, 2] = a

    elif fmt is TexFormat.RG88:
        a = np.frombuffer(data[:n * 2], dtype=np.uint8).reshape(n, 2)
        out[:, 0], out[:, 1] = a[:, 0], a[:, 1]

    elif fmt is TexFormat.R16F:
        a = np.frombuffer(data[:n * 2], dtype=np.float16).astype(np.float32)
        v = np.clip(a, 0, 1) * 255
        out[:, 0] = out[:, 1] = out[:, 2] = v.astype(np.uint8)

    elif fmt is TexFormat.RG1616F:
        a = np.frombuffer(data[:n * 4], dtype=np.float16).reshape(n, 2).astype(np.float32)
        v = (np.clip(a, 0, 1) * 255).astype(np.uint8)
        out[:, 0], out[:, 1] = v[:, 0], v[:, 1]

    else:
        raise TexError(f"formato sin implementar: {fmt!r}")

    return out.reshape(height, width, 4)


# ── Parser del contenedor ────────────────────────────────────────────────

@dataclass
class Mipmap:
    width: int
    height: int
    raw: bytes                 # ya descomprimido de LZ4, aun en formato nativo
    embedded: bool = False     # True si `raw` es un PNG/JPEG completo
    video: bool = False        # True si `raw` es un MP4 completo

    def to_rgba(self, fmt: TexFormat) -> np.ndarray:
        if self.video:
            raise TexError("es una textura de video (MP4); usa .raw y decodifica con mpv")
        if self.embedded:
            import io
            from PIL import Image
            return np.array(Image.open(io.BytesIO(self.raw)).convert("RGBA"))
        if fmt in (TexFormat.DXT1, TexFormat.DXT3, TexFormat.DXT5):
            kind = {TexFormat.DXT1: 1, TexFormat.DXT3: 2, TexFormat.DXT5: 3}[fmt]
            return _decode_bc(self.raw, self.width, self.height, kind)
        return _decode_plain(self.raw, self.width, self.height, fmt)


@dataclass
class Texture:
    format: TexFormat
    flags: TexFlags
    texture_size: tuple[int, int]
    image_size: tuple[int, int]
    dominant_color: int
    container: str
    images: list[list[Mipmap]] = field(default_factory=list)
    depth: int | None = None
    gif_size: tuple[int, int] | None = None
    frames: list[dict] = field(default_factory=list)
    trailing: int = 0           # bytes sin consumir; debe ser 0

    @property
    def is_volume(self) -> bool:
        return bool(self.flags & TexFlags.IS_VOLUME)

    @property
    def is_animated(self) -> bool:
        return bool(self.frames)

    @property
    def is_video(self) -> bool:
        return bool(self.flags & TexFlags.IS_VIDEO)


class _Reader:
    def __init__(self, buf: bytes):
        self.b, self.p = buf, 0

    def u32(self) -> int:
        (v,) = struct.unpack_from("<I", self.b, self.p)
        self.p += 4
        return v

    def i32(self) -> int:
        (v,) = struct.unpack_from("<i", self.b, self.p)
        self.p += 4
        return v

    def f32(self) -> float:
        (v,) = struct.unpack_from("<f", self.b, self.p)
        self.p += 4
        return v

    def cstr(self) -> str:
        e = self.b.index(b"\0", self.p)
        s = self.b[self.p:e].decode("ascii")
        self.p = e + 1
        return s

    def take(self, n: int) -> bytes:
        v = self.b[self.p:self.p + n]
        if len(v) != n:
            raise TexError("fin de fichero inesperado")
        self.p += n
        return v


def read_texture(buf: bytes) -> Texture:
    r = _Reader(buf)

    magic = r.cstr()
    if magic != "TEXV0005":
        raise TexError(f"magic desconocido: {magic!r}")
    header_ver = r.cstr()
    if header_ver != "TEXI0001":
        raise TexError(f"cabecera desconocida: {header_ver!r}")

    fmt = r.u32()
    flags = TexFlags(r.u32())
    tw, th = r.u32(), r.u32()
    iw, ih = r.u32(), r.u32()
    depth = r.u32() if flags & TexFlags.IS_VOLUME else None
    dominant = r.u32()

    container = r.cstr()
    if not container.startswith("TEXB"):
        raise TexError(f"contenedor desconocido: {container!r}")
    cver = int(container[4:])

    tex = Texture(
        format=TexFormat(fmt) if fmt in TexFormat._value2member_map_ else fmt,
        flags=flags,
        texture_size=(tw, th),
        image_size=(iw, ih),
        dominant_color=dominant,
        container=container,
        depth=depth,
    )

    if tex.is_volume:
        # Los LUT 3D de materials/lut/ traen un layout de mipmap propio que
        # todavia no esta resuelto. Fallar aqui es preferible a devolver
        # pixeles basura: no hace falta ninguno para renderizar una escena.
        raise TexError("textura de volumen (LUT 3D) sin soportar")

    image_count = r.u32()
    # Ojo: TEXB0002 NO lleva freeImageFormat, solo TEXB0003 en adelante.
    # Asumirlo desplaza un uint32 y rompe todas las texturas de particulas.
    free_image_format = r.i32() if cver >= 3 else -1
    if cver >= 4:
        r.u32()  # reservado; observado siempre a 0

    for _ in range(image_count):
        mips: list[Mipmap] = []
        for _ in range(r.u32()):
            w, h = r.u32(), r.u32()
            if cver >= 2:
                compressed = r.u32() == 1
                decompressed_size = r.u32()
            else:
                compressed, decompressed_size = False, 0
            data = r.take(r.u32())
            if compressed:
                data = lz4_decompress(data, decompressed_size)
            # El flag es la fuente de verdad, pero comprobamos tambien la caja
            # `ftyp` de ISO-BMFF: una textura de video cuyo MP4 pese mas que
            # width*height*bpp se decodificaria como ruido sin avisar.
            is_video = bool(flags & TexFlags.IS_VIDEO) or data[4:8] == b"ftyp"
            mips.append(Mipmap(w, h, data,
                               embedded=free_image_format >= 0 and not is_video,
                               video=is_video))
        tex.images.append(mips)

    # Seccion opcional de animacion.
    if r.p < len(buf) - 1:
        try:
            smagic = r.cstr()
        except ValueError:
            smagic = ""
        if smagic.startswith("TEXS"):
            sver = int(smagic[4:])
            count = r.u32()
            if sver >= 3:
                # Solo la version 3 lleva el tamano del gif, y como enteros.
                tex.gif_size = (r.u32(), r.u32())
            # La version 1 guarda las coordenadas del sprite como enteros;
            # de la 2 en adelante como float.
            num = r.i32 if sver == 1 else r.f32
            for _ in range(count):
                tex.frames.append({
                    "image_id": r.u32(),
                    "frame_time": r.f32(),
                    "x": num(), "y": num(),
                    "width": num(), "width_y": num(),
                    "height_x": num(), "height": num(),
                })

    tex.trailing = len(buf) - r.p
    return tex


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 1

    src = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else None

    tex = read_texture(src.read_bytes())
    print(f"{src.name}")
    print(f"  formato   : {tex.format!r}")
    print(f"  flags     : {tex.flags!r}")
    print(f"  textura   : {tex.texture_size[0]}x{tex.texture_size[1]}")
    print(f"  imagen    : {tex.image_size[0]}x{tex.image_size[1]}")
    print(f"  contenedor: {tex.container}  imagenes={len(tex.images)}"
          f"  mipmaps={[len(m) for m in tex.images]}")
    if tex.is_volume:
        print(f"  volumen   : profundidad {tex.depth}")
    if tex.is_animated:
        print(f"  animacion : {len(tex.frames)} fotogramas")
    print(f"  sobrante  : {tex.trailing} B")

    if out:
        from PIL import Image
        out.mkdir(parents=True, exist_ok=True)
        for i, mips in enumerate(tex.images):
            for j, m in enumerate(mips):
                rgba = m.to_rgba(tex.format)
                name = f"{src.stem}_img{i}_mip{j}.png"
                Image.fromarray(rgba, "RGBA").save(out / name)
        print(f"  -> PNG en {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
