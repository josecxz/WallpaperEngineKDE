#!/usr/bin/env python3
"""Decodificador de mallas puppet (.mdl) de Wallpaper Engine.

Un objeto con `puppet` no se dibuja sobre un quad: trae una malla propia cuyos
vertices se deforman por huesos. Sin ella la capa se coloca por `origin` y
queda donde el autor no la puso -- que es el sintoma de la animacion de
parpadeo descolocada en Jeanne.

Formato (descubierto comparando los 84 .mdl de la biblioteca):

    char[]  magic  "MDLV00NN" terminado en nul, como PKGV0016 y TEXV0005
    byte[12]       constantes; identicas en las 6 versiones observadas
    char[]         ruta del material, terminada en nul
    byte[hueco]    relleno que depende de la version
    u32            campo de formato (0 en las versiones soportadas)
    u32            TAMANO EN BYTES del bloque de vertices, no su numero
    vertice[]      ver LAYOUT
    u32            TAMANO EN BYTES del bloque de indices, tampoco su numero
    u16[]          indices, triangulos
    ...            bloques MDLS (esqueleto) y MDLA (animacion), sin decodificar
    byte[]         relleno a cero; algunos exportadores rellenan a 1 MiB

Los dos tamanos son en bytes y no en elementos: leerlos como numero de
elementos desborda el fichero, que fue justo el primer indicio.

LAYOUT del vertice, 52 bytes = 13 campos de 4 bytes:

    [ 0.. 2]  float3  posicion (z siempre 0: son mallas planas)
    [ 3.. 6]  u32 x4  indices de hueso
    [ 7..10]  float4  pesos, suman 1
    [11..12]  float2  UV

Que [3..6] son enteros y no flotantes se ve en un vertice atado al hueso 6:
como flotante ese patron de bits es un denormal (8e-45), no un 6. Y que
[7..10] son los pesos lo confirma que sumen 1 en los 19462 vertices del
corpus, con una desviacion maxima de 1.19e-07 -- el epsilon del float.

Versiones no soportadas: 0017, 0019 y 0023 sitúan el bloque en otro sitio y
usan un stride mayor que no queda determinado por el corpus (40 y 80 encajan
igual de bien). Se rechazan con un error explicito en lugar de adivinar.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# version -> (bytes de relleno tras la ruta del material, stride del vertice)
#
# Sale de buscar, para cada version, que pares (hueco, stride) hacen cuadrar la
# cadena entera en TODOS sus ficheros: tamano divisible por el stride, bloque
# de indices consistente e indice maximo < numero de vertices. Para estas tres
# versiones la solucion es unica.
VERSIONS = {
    "MDLV0013": (0, 52),
    "MDLV0014": (0, 52),
    "MDLV0016": (4, 52),
}

# Las versiones vistas en la biblioteca que aun no sabemos leer.
KNOWN_UNSUPPORTED = ("MDLV0017", "MDLV0019", "MDLV0023")

STRIDE_FIELDS = 13          # campos de 4 bytes por vertice
HEADER_CONST = 12           # bytes constantes entre el magic y la ruta

# Valores observados en el campo que precede al tamano del bloque. 0 en las
# versiones 0013 y 0014; en 0016 vale la misma constante que aparece justo
# detras del magic, asi que parece un marcador de serializacion y no un
# formato de vertice. No sabemos leerlo, pero comprobarlo sigue valiendo:
# un valor distinto significa que hemos perdido la alineacion.
FORMAT_FIELD = frozenset((0x0, 0x01800009))


class MdlError(Exception):
    """El fichero no es un .mdl legible."""


@dataclass(frozen=True)
class Mesh:
    """Malla puppet ya decodificada.

    Los arrays son vistas de numpy sobre el buffer original: no se copia nada
    hasta que alguien escriba.
    """

    version: str
    material: str
    positions: np.ndarray      # (n, 3) float32
    uvs: np.ndarray            # (n, 2) float32
    bone_indices: np.ndarray   # (n, 4) uint32
    bone_weights: np.ndarray   # (n, 4) float32
    indices: np.ndarray        # (m,)  uint16, m multiplo de 3
    consumed: int              # bytes leidos; el resto es MDLS/MDLA o relleno

    @property
    def vertex_count(self) -> int:
        return int(self.positions.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.indices.shape[0] // 3)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Caja envolvente en el espacio local del modelo."""
        return self.positions.min(axis=0), self.positions.max(axis=0)


@dataclass(frozen=True)
class Bone:
    """Hueso en pose de reposo."""

    parent: int                # -1 si es raiz
    matrix: np.ndarray         # (4, 4) float32, por filas


def parse_skeleton(buf: bytes, pos: int, name: str = "<memoria>") -> tuple[list[Bone], int]:
    """Lee el bloque MDLS que sigue a la geometria.

    Estructura, deducida del corpus:

        char[]  magic "MDLS000N" terminado en nul
        u32     tamano restante
        u32     numero de huesos
        por hueso:
            u8      relleno
            u32     siempre 1; proposito desconocido
            i32     indice del padre, -1 si es raiz
            u32     TAMANO EN BYTES de la matriz (64), no su numero de celdas
            float[16]  matriz 4x4
            char[]  nombre del hueso, terminado en nul (casi siempre vacio)

    El relleno y el u32 van por hueso, no en la cabecera: leerlos una sola vez
    cuadra el primer hueso y descarrila el segundo, que es como se detecto.

    Que el numero de huesos es ese campo se comprueba solo: coincide con
    max(indice de hueso en los vertices) + 1 en todo el corpus, que es una
    medida independiente sacada del bloque de geometria.
    """
    ver, p = _cstring(buf, pos)
    if not ver.startswith("MDLS"):
        raise MdlError(f"{name}: se esperaba MDLS y hay {ver!r}")
    _total, count = struct.unpack_from("<II", buf, p)
    p += 8
    bones: list[Bone] = []
    for i in range(count):
        p += 1 + 4                              # relleno + el u32 que vale 1
        parent, mbytes = struct.unpack_from("<iI", buf, p)
        p += 8
        if mbytes != 64:
            raise MdlError(f"{name}: hueso {i} con matriz de {mbytes} b, se esperaban 64")
        m = np.frombuffer(buf, "<f4", 16, p).reshape(4, 4)
        p += 64
        _bone_name, p = _cstring(buf, p)
        bones.append(Bone(parent=parent, matrix=m))
    return bones, p


@dataclass(frozen=True)
class Animation:
    """Animacion de huesos ya decodificada."""

    name: str
    mode: str                  # "loop" en todo el corpus visto
    duration: float
    frames: int
    tracks: np.ndarray         # (huesos, fotogramas+1, 9) float32

    @property
    def positions(self) -> np.ndarray:
        return self.tracks[:, :, 0:3]

    @property
    def rotations(self) -> np.ndarray:
        return self.tracks[:, :, 3:6]

    @property
    def scales(self) -> np.ndarray:
        return self.tracks[:, :, 6:9]


def parse_animations(buf: bytes, pos: int, name: str = "<memoria>") -> tuple[list[Animation], int]:
    """Lee el bloque MDLA que sigue al esqueleto.

        char[]  magic "MDLA000N"
        u32     tamano restante
        u32     numero de animaciones
        por animacion:
            u32     identificador
            u32     siempre 0
            char[]  nombre
            char[]  modo ("loop")
            f32     duracion
            u32     numero de fotogramas
            u32     siempre 0
            u32     numero de pistas == numero de huesos
            por pista:
                u32     siempre 0
                u32     TAMANO EN BYTES de la pista
                float[] las claves
            u32     siempre 0, cierra la animacion

    El par (0, tamano) va POR PISTA, no una vez en la cabecera. Leyendolo una
    sola vez cuadra la primera pista y deja sin consumir el resto; en los
    ficheros con dos animaciones el desajuste se acumula y descarrila la
    segunda. Es el mismo prefijo por registro que ya aparecio en los huesos.

    El u32 de cola solo se nota con dos animaciones: con una sola se lo come el
    relleno del final y el bloque cuadra igual. Sin el, la segunda animacion
    arranca cuatro bytes antes y lee el cero de cierre como identificador.

    Cada fotograma son 9 float: posicion(3), rotacion(3) y escala(3). Tres
    comprobaciones cruzadas lo sostienen, y ninguna sale del propio bloque:

      - el numero de pistas coincide con los huesos que declara el MDLS
      - el tamano de pista es siempre multiplo exacto de 36
      - y da siempre `fotogramas + 1` claves: el fotograma que cierra el bucle
    """
    ver, p = _cstring(buf, pos)
    if not ver.startswith("MDLA"):
        # Seis mallas del corpus (DRAGON 1-3, WOMEN, SWORD y una Rider) llegan
        # aqui sin tag y con cientos de bytes que NO son relleno: tras el
        # esqueleto hay otro bloque sin identificar. No es un fallo del lector
        # de animaciones, asi que se distingue del caso "tag equivocado".
        resto = len(buf) - pos
        raise MdlError(f"{name}: se esperaba MDLA y hay {ver!r} "
                       f"({resto} b sin identificar tras el esqueleto)")
    _total, count = struct.unpack_from("<II", buf, p)
    p += 8

    anims: list[Animation] = []
    for i in range(count):
        p += 8                                  # identificador + un u32 a 0
        anim_name, p = _cstring(buf, p)
        mode, p = _cstring(buf, p)
        duration, frames, _z1, ntracks = struct.unpack_from("<fIII", buf, p)
        p += 16

        pistas = []
        for k in range(ntracks):
            _z2, tbytes = struct.unpack_from("<II", buf, p)
            p += 8
            if tbytes % 36:
                raise MdlError(f"{name}: pista {k} de {tbytes} b no es multiplo de 36")
            if p + tbytes > len(buf):
                raise MdlError(f"{name}: la pista {k} de '{anim_name}' desborda el fichero")
            pistas.append(np.frombuffer(buf, "<f4", tbytes // 4, p).reshape(-1, 9))
            p += tbytes

        p += 4                                  # cierre de la animacion

        t = np.stack(pistas) if pistas else np.zeros((0, 0, 9), dtype="<f4")
        anims.append(Animation(name=anim_name, mode=mode, duration=float(duration),
                               frames=int(frames), tracks=t))
    return anims, p


def _cstring(buf: bytes, pos: int) -> tuple[str, int]:
    """Lee una cadena terminada en nul y devuelve tambien la posicion siguiente."""
    end = buf.find(b"\0", pos)
    if end < 0:
        raise MdlError("cadena sin terminador nul")
    return buf[pos:end].decode("utf-8", "replace"), end + 1


def load_mdl(path: str | Path) -> Mesh:
    """Decodifica un .mdl. Lanza MdlError si la version no esta soportada."""
    path = Path(path)
    return parse_mdl(path.read_bytes(), name=path.name)


def parse_mdl(buf: bytes, name: str = "<memoria>") -> Mesh:
    version, pos = _cstring(buf, 0)
    if version not in VERSIONS:
        extra = " (version conocida pero sin decodificar)" if version in KNOWN_UNSUPPORTED else ""
        raise MdlError(f"{name}: version {version} no soportada{extra}")
    gap, stride = VERSIONS[version]

    pos += HEADER_CONST
    material, pos = _cstring(buf, pos)
    pos += gap

    fmt, vsize = struct.unpack_from("<II", buf, pos)
    pos += 8
    if fmt not in FORMAT_FIELD:
        raise MdlError(f"{name}: campo de formato inesperado {fmt:#x}")
    if vsize == 0 or vsize % stride:
        raise MdlError(f"{name}: bloque de vertices de {vsize} b no es multiplo de {stride}")

    n = vsize // stride
    if pos + vsize > len(buf):
        raise MdlError(f"{name}: el bloque de vertices desborda el fichero")

    # Una sola lectura del bloque, reinterpretada como float y como entero. Es
    # el mismo buffer: no se copia ni se recorre dos veces.
    flat_f = np.frombuffer(buf, "<f4", n * STRIDE_FIELDS, pos).reshape(n, STRIDE_FIELDS)
    flat_u = np.frombuffer(buf, "<u4", n * STRIDE_FIELDS, pos).reshape(n, STRIDE_FIELDS)
    pos += vsize

    (isize,) = struct.unpack_from("<I", buf, pos)
    pos += 4
    if isize == 0 or isize % 6:
        raise MdlError(f"{name}: bloque de indices de {isize} b no forma triangulos")
    if pos + isize > len(buf):
        raise MdlError(f"{name}: el bloque de indices desborda el fichero")

    indices = np.frombuffer(buf, "<u2", isize // 2, pos)
    pos += isize
    if int(indices.max()) >= n:
        raise MdlError(f"{name}: indice {indices.max()} fuera de rango con {n} vertices")

    return Mesh(
        version=version,
        material=material,
        positions=flat_f[:, 0:3],
        uvs=flat_f[:, 11:13],
        bone_indices=flat_u[:, 3:7],
        bone_weights=flat_f[:, 7:11],
        indices=indices,
        consumed=pos,
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    for arg in sys.argv[1:]:
        try:
            m = load_mdl(arg)
        except MdlError as e:
            print(f"{Path(arg).name}: {e}")
            continue
        lo, hi = m.bounds()
        w = np.asarray(m.bone_weights)
        print(f"{Path(arg).name}")
        print(f"  version   {m.version}   material {m.material}")
        print(f"  malla     {m.vertex_count} vertices, {m.triangle_count} triangulos")
        print(f"  caja      x [{lo[0]:.1f}, {hi[0]:.1f}]  y [{lo[1]:.1f}, {hi[1]:.1f}]  z [{lo[2]:.1f}, {hi[2]:.1f}]")
        print(f"  huesos    hasta {int(m.bone_indices.max())}, "
              f"{int((w > 0).sum(axis=1).max())} influencias por vertice como mucho")
        print(f"  leidos    {m.consumed} de {Path(arg).stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
