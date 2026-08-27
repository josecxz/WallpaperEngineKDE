#!/usr/bin/env python3
"""Texto de una escena de Wallpaper Engine: del campo `text` a quads de glifos.

Una capa de texto no trae geometria ni material: trae una cadena, una fuente y
una caja. Quien la dibuja es `shaders/font`, que muestrea un ATLAS de glifos
con `a_TexCoord` --- exactamente el mismo layout de vertice que una malla
puppet (vec3 posicion + vec2 UV). Asi que todo el trabajo es fabricar ese atlas
y esos vertices; el ejecutor no se entera de que hay texto de por medio.

Se rasteriza POR LINEA y no por glifo. Es menos codigo y mejor tipografia: PIL
---FreeType con HarfBuzz por debajo--- resuelve kerning, ligaduras y shaping de
una vez, y una capa de texto del corpus tiene como mucho dos lineas. Rasterizar
glifo a glifo obligaria a reimplementar esa parte y saldria peor.

**La unidad que hay que averiguar** es cuanto mide un `pointsize` en unidades
de lienzo. No esta en el formato: se deduce de que WE guarda en `size` la caja
que el mismo calculo, y `size = extension_del_texto * K + 2 * padding`. Medido
sobre las capas cuya fuente viene EN el wallpaper ---las `systemfont_*` no
valen, porque en Linux se sustituyen y las metricas ya no son las del autor---
sale K = 4.137, y sale igual en lienzos de 564x1120 y de 3840x2160, asi que es
una constante y no una proporcion de la pantalla. Dos cadenas del mismo
wallpaper, de 23 y 34 caracteres, dan 4.1371 y 4.1368: la relacion es
proporcional pura, no hay termino independiente escondido.

Que `padding` va SIN escalar se ve en `3237641967`, que tiene la misma cadena y
la misma fuente con `padding` 0 y 3: la caja mide 252 y 258, exactamente 2x3
mas.

Lo que este modulo NO hace, y hay que saberlo al mirar el resultado: 148 de los
167 objetos de texto del corpus traen el texto en un SCRIPT de JavaScript, y
133 de esos llaman a `new Date`. Son relojes. Sin motor de scripting lo que se
dibuja es su `value`, la copia que el autor tenia en pantalla al guardar ---
"12:34" en 57 de ellos. La tipografia sale bien; la hora, congelada.
"""

from __future__ import annotations

import io
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from wescene import AssetResolver, SceneError


class TextoError(Exception):
    pass


# Unidades de lienzo por punto de `pointsize`. Ver la cabecera del modulo.
UNIDADES_POR_PUNTO = 4.137

# El atlas se rasteriza a mas resolucion de la que se va a ver. No es lujo: la
# capa se dibuja primero en un buffer del tamano del lienzo ---donde su
# rectangulo sale AMPLIADO, un cuadro de 365 unidades ocupa los 3840 px de
# ancho--- y al componer se vuelve a encoger. Ese ida y vuelta son dos
# remuestreos bilineales, y con el atlas a tamano final el texto sale lavado.
SUPERMUESTREO = 2.0

# Topes del tamano de rasterizado, en pixeles de la em. El de abajo evita que
# una capa diminuta quede ilegible; el de arriba acota lo que puede pedir un
# `pointsize` grande en 4K.
PX_MIN, PX_MAX = 8, 512

# Y un segundo tope, por ancho de la linea mas larga: el tamano de la em no
# dice cuanto ocupa la linea, y el credito de `3577990983` son 39 caracteres.
# Al pasarse se rebaja el tamano en la proporcion justa, una sola vez, en vez
# de pedirle al driver una textura que puede no dar.
ANCHO_ATLAS_MAX = 4096

# Separacion entre lineas dentro del atlas, para que el filtrado bilineal de
# una no muerda la de al lado.
BORDE = 2

# Fuente con la que se sigue adelante cuando no hay ninguna otra. Viene con WE,
# asi que existe siempre que exista la instalacion.
FUENTE_DE_RESPALDO = "fonts/NotoSans-Regular.ttf"

_fc_cache: dict[str, bytes | None] = {}


def texto_de(campo) -> str:
    """La cadena que hay que dibujar.

    El campo puede ser la cadena, o el envoltorio `{"value": ...}` con el que
    viajan los campos atados a un script o a una propiedad configurable. En los
    dos casos manda `value`, que es lo que `_refrescar_valores_de_usuario` deja
    ya puesto al dia con la propiedad del `project.json`.
    """
    if isinstance(campo, str):
        return campo
    if isinstance(campo, dict):
        v = campo.get("value")
        if isinstance(v, str):
            return v
    return ""


def _por_fontconfig(familia: str) -> bytes | None:
    """La fuente del sistema que mas se parece a la que pide el wallpaper.

    `systemfont_consolas` y `systemfont_arial` son 83 de los 167 objetos del
    corpus y son fuentes de Windows: aqui no estan. fontconfig da el sustituto
    ---Arial cae en Liberation Sans, que es metricamente compatible--- y con
    eso el texto sale del tamano correcto aunque el trazo no sea el mismo.
    """
    if familia in _fc_cache:
        return _fc_cache[familia]
    blob = None
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", familia],
                           capture_output=True, text=True, timeout=5)
        ruta = Path(r.stdout.strip())
        if r.returncode == 0 and ruta.is_file():
            blob = ruta.read_bytes()
    except (OSError, subprocess.SubprocessError):
        pass
    _fc_cache[familia] = blob
    return blob


def resolver_fuente(res: AssetResolver, nombre: str) -> bytes:
    """Los bytes de la fuente, del paquete, de los assets o del sistema.

    Los tres origenes existen de verdad en el corpus: 47 objetos traen la
    fuente dentro de su propio `scene.pkg` (`fonts/workshop/<id>/…`), 37 la
    toman de la instalacion de WE y 83 piden una del sistema.
    """
    if not isinstance(nombre, str) or not nombre:
        raise TextoError("el objeto no declara fuente")
    if nombre.startswith("systemfont_"):
        blob = _por_fontconfig(nombre[len("systemfont_"):])
        if blob:
            return blob
        try:
            return res.read_bytes(FUENTE_DE_RESPALDO)
        except SceneError as e:
            raise TextoError(f"sin fuente para {nombre!r}: {e}") from e
    try:
        return res.read_bytes(nombre)
    except SceneError as e:
        raise TextoError(f"fuente sin resolver: {nombre!r} ({e})") from e


def _numeros(valor, n: int, defecto: float) -> list[float]:
    """`n` floats de un campo que puede venir como numero, cadena o `{value}`.

    Es el mismo trato que `werender._floats` le da a todo lo demas; se repite
    aqui en corto para no arrastrar una dependencia circular entre los dos
    modulos.
    """
    if isinstance(valor, dict):
        valor = valor.get("value")
    if isinstance(valor, (int, float)):
        salida = [float(valor)]
    elif isinstance(valor, str):
        salida = []
        for t in valor.replace(",", " ").split():
            try:
                salida.append(float(t))
            except ValueError:
                pass
    elif isinstance(valor, (list, tuple)):
        salida = [float(x) for x in valor if isinstance(x, (int, float))]
    else:
        salida = []
    return (salida + [salida[-1] if salida else defecto] * n)[:n]


def _bandera(valor) -> bool:
    if isinstance(valor, dict):
        valor = valor.get("value")
    return bool(valor)


@dataclass
class Linea:
    texto: str
    avance: float          # ancho de la linea en px de rasterizado
    ink: tuple[int, int, int, int]   # caja de tinta (x0, y0, x1, y1)
    img: Image.Image | None


@dataclass
class Disposicion:
    """Todo lo que hace falta para dibujar la capa, ya en unidades de lienzo."""
    atlas: np.ndarray                 # (h, w, 4) uint8, con la cobertura en R
    vertices: np.ndarray              # (4*nlineas, 5) float32: xyz + uv
    indices: np.ndarray               # u16
    extent: tuple[float, float]       # lo que ocupa el bloque, con padding
    lineas: int


def _envolver(texto: str, font, ancho_max: float) -> list[str]:
    """Parte las lineas que no caben, por palabras y sin cortar palabras cortas.

    Solo lo piden 14 objetos del corpus (`limitwidth`), y ninguno con mas de
    una linea declarada, pero es donde la caja y el texto discrepan y sin esto
    se salen del rectangulo.
    """
    salida: list[str] = []
    for cruda in texto.split("\n"):
        if font.getlength(cruda) <= ancho_max or not cruda.strip():
            salida.append(cruda)
            continue
        actual = ""
        for palabra in cruda.split(" "):
            prueba = f"{actual} {palabra}".strip() if actual else palabra
            if actual and font.getlength(prueba) > ancho_max:
                salida.append(actual)
                actual = palabra
            else:
                actual = prueba
        salida.append(actual)
    return salida


def _recortar(lineas: list[str], font, maxrows: int, elipsis: bool) -> list[str]:
    if maxrows <= 0 or len(lineas) <= maxrows:
        return lineas
    cortadas = lineas[:maxrows]
    if elipsis and cortadas:
        cortadas[-1] = cortadas[-1].rstrip() + "…"
    return cortadas


def disponer(res: AssetResolver, obj: dict,
             px_por_unidad: float = 1.0) -> Disposicion | None:
    """Rasteriza y coloca el texto del objeto dentro de su rectangulo.

    `px_por_unidad` es a cuantos pixeles de dibujo equivale una unidad de
    lienzo; de ahi sale a que tamano se rasteriza el atlas. Los vertices salen
    SIEMPRE en unidades de lienzo relativas al centro de la capa, con la y
    hacia arriba, que es el espacio en el que el ejecutor dibuja una malla.

    Devuelve None cuando no hay nada que dibujar. En el corpus son 8 capas, y
    todas la misma cosa: los titulos de cancion y artista de los dos
    wallpapers con reproductor de musica, que su script rellena en vivo y
    guardan vacios. Un plan con una malla de cero vertices no seria mas
    correcto, solo mas dificil de leer.
    """
    texto = texto_de(obj.get("text"))
    if not texto.strip():
        return None

    puntos = _numeros(obj.get("pointsize"), 1, 0.0)[0]
    if puntos <= 0:
        return None
    # Alto de la em en unidades de lienzo, y a cuantos pixeles se rasteriza.
    em = puntos * UNIDADES_POR_PUNTO
    px = int(round(em * px_por_unidad * SUPERMUESTREO))
    px = max(PX_MIN, min(PX_MAX, px))
    # Lo que mide un pixel del atlas en unidades de lienzo. Es de aqui, y no
    # del tamano pedido, porque `px` esta redondeado y topado: usar el pedido
    # descuadraria el texto justo en las capas que tocan los topes.
    u = em / px

    blob = resolver_fuente(res, obj.get("font"))
    font = ImageFont.truetype(io.BytesIO(blob), px)

    caja = _numeros(obj.get("size"), 2, 0.0)
    pad = _numeros(obj.get("padding"), 2, 0.0)
    util_w = max(0.0, caja[0] - 2 * pad[0])
    util_h = max(0.0, caja[1] - 2 * pad[1])

    lineas_txt = texto.split("\n")
    if _bandera(obj.get("limitwidth")):
        ancho_max = _numeros(obj.get("maxwidth"), 1, 0.0)[0]
        if ancho_max > 0:
            lineas_txt = _envolver(texto, font, ancho_max / u)
    if _bandera(obj.get("limitrows")):
        lineas_txt = _recortar(lineas_txt, font,
                               int(_numeros(obj.get("maxrows"), 1, 0.0)[0]),
                               _bandera(obj.get("limituseellipsis")))

    # La linea mas larga manda sobre el tope de ancho, y solo se sabe con la
    # fuente ya cargada: el tamano de la em no dice cuanto avanza el texto.
    ancho_px = max((font.getlength(t) for t in lineas_txt), default=0.0)
    if ancho_px > ANCHO_ATLAS_MAX:
        px = max(PX_MIN, int(px * ANCHO_ATLAS_MAX / ancho_px))
        font = ImageFont.truetype(io.BytesIO(blob), px)
        u = em / px

    asc, desc = font.getmetrics()
    alto_linea = float(asc + desc)
    # `spacing` es (horizontal, vertical) en unidades de lienzo; en el corpus
    # los 21 que lo declaran dicen "0 0", asi que solo se suma al interlineado.
    espaciado = _numeros(obj.get("spacing"), 2, 0.0)[1] / u

    lineas: list[Linea] = []
    for t in lineas_txt:
        avance = float(font.getlength(t))
        if not t.strip():
            lineas.append(Linea(t, avance, (0, 0, 0, 0), None))
            continue
        # `getbbox` da la caja de TINTA respecto al origen de la linea, que es
        # su borde izquierdo sobre la linea del ascendente. Puede empezar en
        # negativo ---una `j` sobresale por la izquierda---, y de ahi que el
        # origen del dibujo se desplace por el.
        x0, y0, x1, y1 = font.getbbox(t)
        w = max(1, x1 - x0 + 2 * BORDE)
        h = max(1, y1 - y0 + 2 * BORDE)
        img = Image.new("L", (w, h), 0)
        ImageDraw.Draw(img).text((BORDE - x0, BORDE - y0), t, font=font, fill=255)
        lineas.append(Linea(t, avance, (x0 - BORDE, y0 - BORDE,
                                        x0 - BORDE + w, y0 - BORDE + h), img))

    pintadas = [l for l in lineas if l.img is not None]
    if not pintadas:
        return None

    # ── atlas: las lineas apiladas, que es todo el empaquetado que hace falta
    aw = max(l.img.width for l in pintadas)
    ah = sum(l.img.height for l in pintadas)
    atlas = np.zeros((ah, aw, 4), dtype=np.uint8)
    y = 0
    for l in pintadas:
        w, h = l.img.width, l.img.height
        # La cobertura va en los cuatro canales: `font.frag` sin MSDF la lee
        # por `ConvertSampleR8`, o sea `.r`, y tenerla tambien en el alfa deja
        # el atlas mirable tal cual al depurar.
        atlas[y:y + h, 0:w, :] = np.asarray(l.img, dtype=np.uint8)[:, :, None]
        l.uv = (0.0, y / ah, w / aw, (y + h) / ah)
        y += h

    # ── colocacion, en unidades de lienzo y con la y hacia ABAJO de momento
    bloque_h = len(lineas) * alto_linea + max(0, len(lineas) - 1) * espaciado
    halign = str(obj.get("horizontalalign") or "center")
    valign = str(obj.get("verticalalign") or "center")
    if "top" in valign:
        y_bloque = 0.0
    elif "bottom" in valign:
        y_bloque = util_h / u - bloque_h
    else:
        y_bloque = (util_h / u - bloque_h) / 2.0

    verts = np.zeros((4 * len(pintadas), 5), dtype="<f4")
    idx = np.zeros(6 * len(pintadas), dtype="<u2")
    n = 0
    ancho_bloque = max(l.avance for l in lineas)
    for i, l in enumerate(lineas):
        if l.img is None:
            continue
        if "left" in halign:
            x_linea = 0.0
        elif "right" in halign:
            x_linea = util_w / u - l.avance
        else:
            x_linea = (util_w / u - l.avance) / 2.0
        y_linea = y_bloque + i * (alto_linea + espaciado)
        # Esquinas de la tinta, en px de atlas y luego en unidades de lienzo
        # relativas a la esquina superior izquierda de la zona util.
        ix0, iy0, ix1, iy1 = l.ink
        x_a = (x_linea + ix0) * u
        x_b = (x_linea + ix1) * u
        y_a = (y_linea + iy0) * u
        y_b = (y_linea + iy1) * u
        # De ahi al centro de la capa, con la y hacia arriba.
        X0 = -caja[0] / 2.0 + pad[0] + x_a
        X1 = -caja[0] / 2.0 + pad[0] + x_b
        Y0 = caja[1] / 2.0 - pad[1] - y_a
        Y1 = caja[1] / 2.0 - pad[1] - y_b
        u0, v0, u1, v1 = l.uv
        # El atlas se sube volteado, como todas las texturas del motor: la v
        # que mira hacia abajo en el atlas mira hacia arriba en GL.
        esquinas = ((X0, Y0, u0, 1.0 - v0), (X1, Y0, u1, 1.0 - v0),
                    (X1, Y1, u1, 1.0 - v1), (X0, Y1, u0, 1.0 - v1))
        for j, (x, yv, tu, tv) in enumerate(esquinas):
            verts[4 * n + j] = (x, yv, 0.0, tu, tv)
        idx[6 * n:6 * n + 6] = (4 * n, 4 * n + 1, 4 * n + 2,
                                4 * n, 4 * n + 2, 4 * n + 3)
        n += 1

    return Disposicion(
        atlas=atlas, vertices=verts[:4 * n], indices=idx[:6 * n],
        extent=(ancho_bloque * u + 2 * pad[0], bloque_h * u + 2 * pad[1]),
        lineas=n)


def main() -> int:
    """Barrido del corpus: que se dibujaria de cada capa de texto."""
    import json
    import wepaths

    ws = Path(wepaths.we_workshop())
    we = Path(wepaths.we_assets())
    objetivo = sys.argv[1] if len(sys.argv) > 1 else None
    total = fallos = vacios = 0
    for d in sorted(ws.iterdir()):
        if objetivo and d.name != objetivo:
            continue
        if not (d / "scene.pkg").is_file():
            continue
        try:
            res = AssetResolver.for_wallpaper(d, we)
            data = json.loads(res.read_text("scene.json"))
        except Exception:
            continue
        for o in data.get("objects", []):
            if not o.get("text"):
                continue
            total += 1
            try:
                disp = disponer(res, o, 1.0)
            except (TextoError, OSError, ValueError) as e:
                fallos += 1
                print(f"{d.name} {str(o.get('name'))[:20]:20} FALLA  {e}")
                continue
            if disp is None:
                vacios += 1
                continue
            caja = _numeros(o.get("size"), 2, 0.0)
            print(f"{d.name} {str(o.get('name'))[:20]:20} "
                  f"{texto_de(o.get('text'))[:22]!r:24} "
                  f"lineas={disp.lineas} atlas={disp.atlas.shape[1]}x{disp.atlas.shape[0]} "
                  f"ocupa={disp.extent[0]:7.1f}x{disp.extent[1]:6.1f} "
                  f"caja={caja[0]:7.1f}x{caja[1]:6.1f}")
    print(f"\n{total} capas de texto: {total - fallos - vacios} dispuestas, "
          f"{vacios} sin texto, {fallos} fallidas")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
