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
    ...            bloques MDLS (esqueleto), MDAT (anclajes) y MDLA (animacion),
                   sin decodificar
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

Las seis versiones del corpus se leen. Lo que cambia con la version es solo el
relleno entre la ruta del material y el campo de formato --- 0, 4 o 28 bytes.
Quien manda sobre la disposicion del vertice es el CAMPO DE FORMATO, que es el
mismo en 0017, 0019 y 0023.

Que el stride de esas tres es 80 y no 40 se ve en los datos, no en la
aritmetica: con 40 las filas alternan entre dos perfiles distintos, porque cada
vertice ocupa dos. Con 80 aparece la estructura --- posicion en 0..2 con z
cero, indices de hueso como enteros pequenos en 10..13, pesos que suman 1 en
14..17 y UV en 18..19 --- y cuadra en los 40 ficheros que llevan ese formato.
La confirmacion independiente es que los indices de hueso caen dentro del
esqueleto en 83 de las 84 mallas: leer el campo equivocado no da eso.

En MDLV0023 la geometria no la sigue el esqueleto directamente, hay un bloque
intermedio. No se decodifica: se busca el siguiente magic conocido, que es lo
unico que necesita quien llama.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# version -> bytes de relleno entre la ruta del material y el campo de formato.
#
# Es lo unico que cambia con la version. El layout del vertice NO depende de
# ella sino del campo de formato, que es el mismo en 0017, 0019 y 0023.
VERSIONS = {
    "MDLV0013": 0,
    "MDLV0014": 0,
    "MDLV0016": 4,
    "MDLV0017": 28,
    "MDLV0019": 28,
    "MDLV0023": 28,
}

# Versiones vistas en la biblioteca que aun no sabemos leer. Ninguna, de
# momento: se conserva el mecanismo porque el corpus no agota el formato.
KNOWN_UNSUPPORTED: tuple[str, ...] = ()

HEADER_CONST = 12           # bytes constantes entre el magic y la ruta

# Campo de formato -> disposicion del vertice, en campos de 4 bytes:
# (campos por vertice, offset de los huesos, de los pesos, de las UV).
#
# Los tres juegos comparten la misma columna vertebral --- posicion en 0..2 con
# z siempre 0 (las mallas son planas), luego huesos como u32, pesos que suman 1
# y UV --- y se diferencian en cuantos campos hay entre la posicion y los
# huesos: 0, 7 u 8. Esos campos intermedios son constantes o casi (normales y
# tangentes de una malla plana) y no se usan.
#
# Cada disposicion se fijo cruzando los ficheros del corpus: los huesos tienen
# que ser enteros pequenos, los pesos sumar 1 en todos los vertices, las UV
# caer en [0,1] y la z ser cero. Con `0x0180000f` cuadran los 40 ficheros de
# las tres versiones nuevas, y con `0x0181000e` los 2 restantes.
LAYOUTS = {
    0x0:        (13, 3, 7, 11),
    0x01800009: (13, 3, 7, 11),
    0x0180000f: (20, 10, 14, 18),
    0x0181000e: (21, 11, 15, 19),
}


class MdlError(Exception):
    """El fichero no es un .mdl legible."""


# Magics de los bloques que siguen a la geometria.
BLOQUES = (b"MDLS", b"MDLA")


def _saltar_hasta_bloque(buf: bytes, pos: int, limite: int = 1 << 20) -> int:
    """Avanza hasta el siguiente MDLS/MDLA si hay algo intercalado.

    En MDLV0023 la geometria no la sigue el esqueleto directamente: hay un
    bloque intermedio. En 8 de los 12 ficheros del corpus tiene una forma
    reconocible --- `u8, u8, u32 tamano`, y ocupa `tamano + 10` --- pero en los
    otros 4 no, asi que aqui no se decodifica ninguno: se localiza el siguiente
    magic conocido y se sigue. Es lo unico que necesita quien llama, que lo que
    quiere es la posicion del esqueleto.

    Se limita la busqueda para que un fichero corrupto no cueste un barrido del
    buffer entero, y solo se acepta el salto si de verdad aterriza en un magic:
    en caso contrario se devuelve la posicion original y que falle el parseo
    del esqueleto, que da un error mas claro que un desplazamiento inventado.
    """
    if buf[pos:pos + 4] in BLOQUES:
        return pos
    fin = min(len(buf), pos + limite)
    mejor = -1
    for magic in BLOQUES:
        i = buf.find(magic, pos, fin)
        if i >= 0 and (mejor < 0 or i < mejor):
            mejor = i
    return mejor if mejor >= 0 else pos


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
        u32     DESPLAZAMIENTO ABSOLUTO del bloque siguiente
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
    siguiente, count = struct.unpack_from("<II", buf, p)
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
    # El u32 de la cabecera no es el tamano del bloque: es el DESPLAZAMIENTO
    # ABSOLUTO del bloque siguiente, y por ahi se sale. Recorrer los huesos no
    # llega hasta ahi en 58 de los 95 puppets del corpus ---detras de la lista
    # queda un bloque mas, distinto en cada fichero--- y quedarse donde acaba
    # el recorrido dejaba la animacion invisible: `parse_animations` no veia
    # MDLA, avisaba de "bytes sin identificar" y el puppet se dibujaba en su
    # postura de reposo. En los 37 restantes el campo coincide EXACTO con el
    # final del recorrido, que es lo que dice que el campo es esto y no otra
    # cosa. Se comprueba antes de fiarse: tiene que caer detras de lo leido y
    # dentro del fichero.
    return bones, (siguiente if p <= siguiente <= len(buf) else p)


@dataclass(frozen=True)
class Attachment:
    """Punto de anclaje del rig: donde se engancha OTRA capa.

    Es lo que cita el campo `attachment` de un objeto de `scene.json`. La
    matriz es local al hueso, con la misma convencion de vector-fila que las
    de reposo: la traslacion va en la fila 3.
    """

    name: str
    bone: int
    matrix: np.ndarray         # (4, 4) float32, por filas


def parse_attachments(buf: bytes, pos: int,
                      name: str = "<memoria>") -> tuple[list[Attachment], int]:
    """Lee el bloque MDAT, si es el que hay en `pos`.

        char[]     magic "MDAT000N" terminado en nul
        u32        DESPLAZAMIENTO ABSOLUTO del bloque siguiente
        u16        numero de anclajes
        por anclaje:
            u16        indice del hueso del que cuelga
            char[]     nombre, terminado en nul
            float[16]  matriz local respecto a ese hueso

    Es el bloque que `parse_skeleton` deja atras: su cabecera apunta ya al
    siguiente, y `parse_animations` lo salta sin mirarlo para llegar al MDLA.
    Aqui SI se mira, porque el nombre que guarda es la unica forma de resolver
    el `attachment` de una capa --- los huesos del MDLS no tienen nombre, lo
    que parece serlo es un JSON con los limites de la articulacion.

    El recuento es u16 y no u32: con u32 el primer anclaje empieza dos bytes
    tarde y el nombre sale descuadrado. Lo confirma que el recorrido termina
    EXACTO en el desplazamiento que declara la cabecera en los cuatro puppets
    del corpus que traen el bloque, y que los nombres que salen son los mismos
    que citan sus escenas.

    Devuelve la lista vacia ---y `pos` sin tocar--- si ahi no hay un MDAT, que
    es el caso de 81 de los 85 puppets.
    """
    if buf[pos:pos + 4] != b"MDAT":
        return [], pos
    ver, p = _cstring(buf, pos)
    siguiente, = struct.unpack_from("<I", buf, p)
    p += 4
    count, = struct.unpack_from("<H", buf, p)
    p += 2
    fuera: list[Attachment] = []
    for i in range(count):
        hueso, = struct.unpack_from("<H", buf, p)
        p += 2
        nombre, p = _cstring(buf, p)
        m = np.frombuffer(buf, "<f4", 16, p).reshape(4, 4)
        p += 64
        fuera.append(Attachment(name=nombre, bone=hueso, matrix=m))
    return fuera, (siguiente if p <= siguiente <= len(buf) else p)


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


def parse_animations(buf: bytes, pos: int, name: str = "<memoria>",
                     bone_count: int = 0) -> tuple[list[Animation], int]:
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
    # Entre el esqueleto y la animacion puede haber bloques que no sabemos
    # leer --- `MDAT0001` en 5 mallas del corpus. No hay que interpretarlos:
    # TODO bloque empieza por su etiqueta y un u32 con el desplazamiento
    # ABSOLUTO del siguiente, asi que se salta por ahi. Antes se saltaba uno
    # solo y con un tamano fijo, `13 + 80*huesos`, que cuadraba en las seis
    # mallas donde se midio y en ninguna otra: el bloque intermedio no tiene
    # tamano fijo. La cadena termina apuntando al final del fichero, que es
    # como se sabe que un puppet no trae animacion.
    for _ in range(8):
        if ver.startswith("MDLA") or p + 4 > len(buf):
            break
        sig = struct.unpack_from("<I", buf, p)[0]
        if not (pos < sig < len(buf)):
            break
        pos = sig
        ver, p = _cstring(buf, pos)
    if not ver.startswith("MDLA"):
        # Sin bloque de animacion: el puppet se queda en su postura de reposo.
        # Se distingue del caso "tag equivocado" porque no es un fallo del
        # lector, es que la cadena de bloques se acaba.
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
    gap = VERSIONS[version]

    pos += HEADER_CONST
    material, pos = _cstring(buf, pos)
    pos += gap

    fmt, vsize = struct.unpack_from("<II", buf, pos)
    pos += 8
    if fmt not in LAYOUTS:
        raise MdlError(f"{name}: campo de formato desconocido {fmt:#x}")
    campos, off_hueso, off_peso, off_uv = LAYOUTS[fmt]
    stride = campos * 4
    if vsize == 0 or vsize % stride:
        raise MdlError(f"{name}: bloque de vertices de {vsize} b no es multiplo de {stride}")

    n = vsize // stride
    if pos + vsize > len(buf):
        raise MdlError(f"{name}: el bloque de vertices desborda el fichero")

    # Una sola lectura del bloque, reinterpretada como float y como entero. Es
    # el mismo buffer: no se copia ni se recorre dos veces.
    flat_f = np.frombuffer(buf, "<f4", n * campos, pos).reshape(n, campos)
    flat_u = np.frombuffer(buf, "<u4", n * campos, pos).reshape(n, campos)
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

    pos = _saltar_hasta_bloque(buf, pos)

    return Mesh(
        version=version,
        material=material,
        positions=flat_f[:, 0:3],
        uvs=flat_f[:, off_uv:off_uv + 2],
        bone_indices=flat_u[:, off_hueso:off_hueso + 4],
        bone_weights=flat_f[:, off_peso:off_peso + 4],
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
