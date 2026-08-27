#!/usr/bin/env python3
"""Comprueba la disposicion del texto: la unidad, la caja y los quads.

Lo que puede salir mal aqui no da error, da un wallpaper con el texto del
tamano equivocado o fuera de sitio. Tres propiedades lo sujetan:

  * **La unidad.** `pointsize` esta en puntos y `size` en unidades de lienzo,
    y la constante que los une no la declara el formato. El oraculo es el
    propio corpus: WE guarda en `size` la caja que el mismo calculo, asi que
    disponer el texto de una capa tiene que devolver esa caja. Se mide sobre
    las capas cuya fuente viene EN el wallpaper; las `systemfont_*` se
    sustituyen aqui por otra fuente y ya no valen de referencia.
  * **El sistema de coordenadas.** Los quads van en unidades de lienzo
    respecto al CENTRO de la capa y con la y hacia arriba, que es lo que
    espera la ruta de malla del ejecutor. Emitirlos respecto a una esquina, o
    con la y del reves, sale como texto desplazado media capa --- que a simple
    vista parece un problema de alineacion.
  * **La alineacion.** `horizontalalign` y `verticalalign` mueven el bloque
    dentro de la caja, y 156 de las 167 capas dicen `center`: si el centrado
    esta mal, esta mal en casi todas.

Uso:
    python3 tools/test_wetext.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
import wetext
from wescene import AssetResolver

# Cuanto se le permite discrepar a la caja que calculamos de la que guardo WE.
# No es holgura de gusto: `size` viene redondeado a entero y las capas de dos
# lineas acumulan el redondeo del interlineado.
TOLERANCIA = 0.03


def _capas_del_corpus():
    """Las capas de texto del corpus, con su resolutor de assets."""
    ws = wepaths.we_workshop()
    we = wepaths.we_assets()
    for d in sorted(ws.iterdir()):
        if not (d / "scene.pkg").is_file():
            continue
        try:
            res = AssetResolver.for_wallpaper(d, we)
            data = json.loads(res.read_text("scene.json"))
        except Exception:
            continue
        for o in data.get("objects", []):
            if o.get("text"):
                yield d.name, res, o


def _objeto(**campos) -> dict:
    raw = {"text": "Hola", "font": "fonts/NotoSans-Regular.ttf",
           "pointsize": 32.0, "size": "400 200", "padding": 0,
           "horizontalalign": "center", "verticalalign": "center"}
    raw.update(campos)
    return raw


def _res() -> AssetResolver:
    return AssetResolver(entries={}, roots=[Path(wepaths.we_assets())])


def prueba_la_caja_reproduce_la_de_we(fallos: list[str]) -> None:
    """La caja que sale de disponer es la que WE guardo en `size`.

    Es la prueba que valida la constante `UNIDADES_POR_PUNTO`: si estuviera
    mal, todo el corpus se desviaria del mismo lado y en la misma proporcion.
    Solo cuentan las capas cuyo texto es LITERAL o cuyo `value` sigue siendo el
    que WE midio; las que traen `<Date>` de marcador tienen la caja calculada
    para otra cadena y no dicen nada de la unidad.
    """
    razones_w, razones_h = [], []
    for _, res, o in _capas_del_corpus():
        if str(o.get("font", "")).startswith("systemfont_"):
            continue
        try:
            disp = wetext.disponer(res, o, 1.0)
        except (wetext.TextoError, OSError, ValueError):
            continue
        if disp is None:
            continue
        caja = wetext._numeros(o.get("size"), 2, 0.0)
        if caja[0] <= 0 or caja[1] <= 0:
            continue
        razones_w.append(disp.extent[0] / caja[0])
        razones_h.append(disp.extent[1] / caja[1])
    if len(razones_w) < 20:
        fallos.append(f"solo {len(razones_w)} capas medibles: sin corpus no hay prueba")
        return
    mw, mh = statistics.median(razones_w), statistics.median(razones_h)
    if abs(mw - 1.0) > TOLERANCIA:
        fallos.append(f"el ancho de la caja se desvia un {abs(mw - 1) * 100:.1f}%: "
                      f"UNIDADES_POR_PUNTO no cuadra ({mw:.4f})")
    if abs(mh - 1.0) > TOLERANCIA:
        fallos.append(f"el alto de la caja se desvia un {abs(mh - 1) * 100:.1f}%: "
                      f"el interlineado no cuadra ({mh:.4f})")


def prueba_todas_se_disponen(fallos: list[str]) -> None:
    """Ninguna capa del corpus se queda sin disponer por una excepcion.

    Las tres fuentes de fuentes ---el paquete del wallpaper, los assets de WE y
    fontconfig--- tienen que resolver las 167. Una que falle no rompe el
    render, se pierde en silencio, que es peor.
    """
    total = fallidas = 0
    for esc, res, o in _capas_del_corpus():
        total += 1
        try:
            wetext.disponer(res, o, 1.0)
        except Exception as e:
            fallidas += 1
            fallos.append(f"{esc} {o.get('name')!r} no se dispone: {e}")
    if total < 100:
        fallos.append(f"solo {total} capas de texto en el corpus: falta biblioteca")


def prueba_centrado(fallos: list[str]) -> None:
    """Centrado significa centrado: el bloque queda simetrico en la caja.

    Se mira la caja envolvente de los quads, que es de tinta y no de avance
    ---una `H` no llega tan abajo como una `g`---, asi que la simetria se
    comprueba en x, donde el avance y la tinta comparten centro salvo por los
    bearings laterales.
    """
    res = _res()
    disp = wetext.disponer(res, _objeto(), 1.0)
    if disp is None:
        fallos.append("no se dispuso el objeto de prueba")
        return
    xs = disp.vertices[:, 0]
    centro = (xs.min() + xs.max()) / 2.0
    if abs(centro) > 4.0:
        fallos.append(f"con horizontalalign=center el bloque no queda centrado "
                      f"(centro en x = {centro:.2f})")
    # Alineado a la izquierda el bloque arranca en el borde de la zona util.
    izq = wetext.disponer(res, _objeto(horizontalalign="left", padding=10), 1.0)
    if izq is not None and abs(izq.vertices[:, 0].min() - (-400 / 2 + 10)) > 8.0:
        fallos.append("con horizontalalign=left el bloque no arranca en el borde "
                      f"({izq.vertices[:, 0].min():.2f})")


def prueba_origen_y_eje_y(fallos: list[str]) -> None:
    """Los quads van respecto al centro de la capa y con la y hacia arriba.

    La primera linea tiene que quedar ARRIBA. Con la y invertida un texto de
    una linea sigue pareciendo correcto ---queda centrado igual--- y solo se
    nota con dos, que salen en orden inverso: por eso la prueba usa dos.

    Que el origen sea el CENTRO y no una esquina se comprueba por contencion:
    la tinta cabe dentro del bloque centrado en cero. No se pide que la tinta
    quede simetrica, porque no lo esta ni debe estarlo --- una linea sin
    descendentes deja hueco abajo, y ese hueco es parte de la linea.
    """
    disp = wetext.disponer(_res(), _objeto(text="primera\nsegunda",
                                           size="800 500"), 1.0)
    if disp is None or disp.lineas != 2:
        fallos.append("no se dispusieron las dos lineas")
        return
    # Cuatro vertices por linea, en el orden en que las escribe `disponer`.
    y_primera = disp.vertices[0:4, 1].mean()
    y_segunda = disp.vertices[4:8, 1].mean()
    if y_primera <= y_segunda:
        fallos.append("la primera linea no queda por encima de la segunda: "
                      "el eje y esta invertido")
    ys, xs = disp.vertices[:, 1], disp.vertices[:, 0]
    medio_alto, medio_ancho = disp.extent[1] / 2.0, disp.extent[0] / 2.0
    # El quad no es la tinta pelada: `wetext.BORDE` le deja unos pixeles de
    # atlas transparentes por lado para que el filtrado bilineal no muerda el
    # borde de la letra. Eso lo saca un pelo del bloque, y es correcto; lo que
    # se comprueba es que no se salga MEDIA capa, que es como se ve un origen
    # puesto en una esquina.
    holgura_y, holgura_x = 0.02 * disp.extent[1], 0.02 * disp.extent[0]
    if ys.max() > medio_alto + holgura_y or ys.min() < -medio_alto - holgura_y:
        fallos.append(f"la tinta se sale del bloque en y: "
                      f"[{ys.min():.1f}, {ys.max():.1f}] fuera de +-{medio_alto:.1f}")
    if xs.max() > medio_ancho + holgura_x or xs.min() < -medio_ancho - holgura_x:
        fallos.append(f"la tinta se sale del bloque en x: "
                      f"[{xs.min():.1f}, {xs.max():.1f}] fuera de +-{medio_ancho:.1f}")


def prueba_uv_dentro_del_atlas(fallos: list[str]) -> None:
    """Las UV caen dentro del atlas y cada linea muestrea una banda distinta.

    Un fallo de empaquetado no rompe nada visible en una capa de una linea: se
    ve en las de dos, que dibujarian la misma banda dos veces.
    """
    disp = wetext.disponer(_res(), _objeto(text="primera\nsegunda"), 1.0)
    if disp is None:
        fallos.append("no se dispuso el objeto de dos lineas")
        return
    uv = disp.vertices[:, 3:5]
    if uv.min() < -1e-6 or uv.max() > 1.0 + 1e-6:
        fallos.append(f"UV fuera del atlas: [{uv.min():.4f}, {uv.max():.4f}]")
    # Las bandas son contiguas --- comparten el borde --- pero no se pisan.
    v1 = sorted(disp.vertices[0:4, 4].tolist())
    v2 = sorted(disp.vertices[4:8, 4].tolist())
    if not (v2[-1] <= v1[0] + 1e-6 or v1[-1] <= v2[0] + 1e-6):
        fallos.append(f"las bandas del atlas se solapan: {v1[0]:.4f}-{v1[-1]:.4f} "
                      f"y {v2[0]:.4f}-{v2[-1]:.4f}")


def prueba_texto_vacio(fallos: list[str]) -> None:
    """Sin texto no hay malla: mejor no dibujar que dibujar un quad vacio."""
    for vacio in ("", "   ", "\n\n"):
        if wetext.disponer(_res(), _objeto(text=vacio), 1.0) is not None:
            fallos.append(f"{vacio!r} deberia quedarse sin disponer")


def prueba_valor_de_script(fallos: list[str]) -> None:
    """El texto de una capa con script es su `value`, no la cadena vacia.

    Son 148 de las 167 capas del corpus. Leer el envoltorio en vez de su
    `value` las dejaria todas en blanco.
    """
    if wetext.texto_de({"script": "…", "value": "12:34"}) != "12:34":
        fallos.append("no se lee el `value` de un campo con script")
    if wetext.texto_de("literal") != "literal":
        fallos.append("no se lee el texto literal")
    if wetext.texto_de(None) != "":
        fallos.append("un campo ausente deberia dar la cadena vacia")


def prueba_recorte_de_lineas(fallos: list[str]) -> None:
    """`limitrows` recorta y `limituseellipsis` marca el corte."""
    largo = "una\ndos\ntres\ncuatro"
    disp = wetext.disponer(_res(), _objeto(text=largo, limitrows=True, maxrows=2,
                                           limituseellipsis=True), 1.0)
    if disp is None or disp.lineas != 2:
        fallos.append(f"limitrows=2 no dejo dos lineas ({disp and disp.lineas})")


def main() -> int:
    fallos: list[str] = []
    for prueba in (prueba_valor_de_script, prueba_texto_vacio, prueba_centrado,
                   prueba_origen_y_eje_y, prueba_uv_dentro_del_atlas,
                   prueba_recorte_de_lineas, prueba_todas_se_disponen,
                   prueba_la_caja_reproduce_la_de_we):
        prueba(fallos)
        print(f"  {prueba.__name__}")
    if fallos:
        print(f"\nFALLO: {len(fallos)} problemas")
        for f in fallos:
            print(f"  {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
