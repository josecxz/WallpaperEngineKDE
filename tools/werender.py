#!/usr/bin/env python3
"""Renderizador offline: ejecuta una escena de WE y vuelca un PNG.

Une las cuatro piezas ya resueltas -- contenedor, texturas, shaders y grafo --
y las pasa a `glexec`, que solo ejecuta. Aqui vive lo que hay que decidir:

  * Binding de propiedades. Cada uniform lleva metadatos JSON en su comentario;
    la clave `material` dice con que entrada de `constantshadervalues` se
    enlaza, y `default` que valor usar si el pase no la trae. Es el ultimo
    subsistema del inventario original que faltaba por resolver.
  * Uniforms del motor: g_Time, g_ModelViewProjectionMatrix,
    g_TextureNResolution... los pone el motor, no el material.
  * Resolucion de bindings: `previous` es el buffer acumulado del objeto y
    los `_rt_*` son buffers intermedios con nombre.

Uso:
    make glexec        # deja el ejecutor en obj/glexec
    python3 tools/werender.py <dir_wallpaper> <salida.png> [--time 0.0]
                              [--only-base] [--exec obj/glexec]
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import wemdl
import weparticles
import wepaths
import wescene
import weshader
import wetex
from wescene import AssetResolver, SceneError, load_scene

IDENTITY = [1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]


def transform_absoluto(obj, por_id: dict | None) -> tuple[list[float], list[float], list[float]]:
    """`origin`, `scale` y `angles` compuestos con los del grupo que los contiene.

    Una escena puede agrupar objetos: el hijo declara `parent` y su `origin` es
    RELATIVO al del grupo.

    Solo heredan la transformacion los GRUPOS: objetos sin nada que dibujar,
    que existen unicamente para mover a sus hijos. Si el padre es una capa
    dibujable, el hijo ya viene en coordenadas del lienzo. No es una suposicion
    de estilo, es lo que separa dos escenas reales: en Cyberpunk
    Edgerunners-Lucy los padres son grupos vacios y sin componer la Tierra se
    iba a la esquina inferior; en Lonely Cat el padre es la imagen de fondo a
    pantalla completa y heredar de ella llevaba tres capas de 1920x1080 al
    centro, tapando la escena --- de 38.05 de media a 8.01.

    Afecta a 476 objetos de 10 escenas, con hasta 5 niveles de anidamiento.
    """
    cadena = []
    visto = set()
    cur = obj
    while cur is not None:
        if id(cur) in visto:        # ciclo en los datos: se corta
            break
        visto.add(id(cur))
        cadena.append(cur)
        padre = cur.raw.get("parent")
        cur = por_id.get(str(padre)) if (por_id and padre) else None
        if cur is not None and any(cur.raw.get(k)
                                   for k in ("image", "particle", "model", "text")):
            cur = None              # el padre dibuja: no es un grupo

    org, esc, ang = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [0.0, 0.0, 0.0]
    # De la raiz hacia el objeto: cada nivel aplica su rotacion y escala al
    # origin del siguiente, que viene expresado en el marco del padre.
    for nodo in reversed(cadena):
        o = (_floats(nodo.raw.get("origin")) + [0.0, 0.0, 0.0])[:3]
        s = (_floats(nodo.raw.get("scale")) + [1.0, 1.0, 1.0])[:3]
        a = (_floats(nodo.raw.get("angles")) + [0.0, 0.0, 0.0])[:3]
        c, sn = math.cos(ang[2]), math.sin(ang[2])
        lx, ly = o[0] * esc[0], o[1] * esc[1]
        org = [org[0] + lx * c - ly * sn, org[1] + lx * sn + ly * c,
               org[2] + o[2] * esc[2]]
        esc = [esc[0] * s[0], esc[1] * s[1], esc[2] * s[2]]
        ang = [ang[0] + a[0], ang[1] + a[1], ang[2] + a[2]]
    return org, esc, ang


def object_mvp(obj, canvas: tuple[int, int], mesh: bool = False,
               por_id: dict | None = None) -> list[float]:
    """Matriz que coloca la geometria del objeto en su sitio del lienzo.

    El quad que sube el ejecutor va de -1 a 1. El objeto declara su centro
    (`origin`), su tamano en pixeles (`size`) y su `scale`, todo en
    coordenadas del lienzo; hay que mapear uno al otro y de ahi a clip space.

    Con `mesh` la geometria no es el quad sino la malla puppet, cuyos vertices
    ya vienen en pixeles respecto al centro del objeto. Ahi `size` no pinta
    nada -- aplicarlo escalaria dos veces -- y basta con pasar de pixeles a
    clip space.

    El shader hace `mul(vec4(a_Position, 1.0), g_ModelViewProjectionMatrix)`,
    que es la convencion de vector-fila de HLSL: en GLSL `v * M` toma columnas,
    asi que el array plano que se sube es la matriz escrita por filas.
    """
    w, h = canvas
    hx, hy, ax, ay, c, s, _ = _colocacion(obj, canvas, mesh, por_id)
    sx, sy = 2.0 * hx / w, 2.0 * hy / h
    tx = 2.0 * ax / w - 1.0
    ty = 2.0 * ay / h - 1.0
    # Rotacion en Z antes de la escala; los angulos vienen en radianes.
    return [ sx * c, -sy * s, 0.0, tx,
             sx * s,  sy * c, 0.0, ty,
             0.0,     0.0,    1.0, 0.0,
             0.0,     0.0,    0.0, 1.0]


def _colocacion(obj, canvas: tuple[int, int], mesh: bool = False,
                por_id: dict | None = None
                ) -> tuple[float, float, float, float, float, float, float]:
    """Semiextension, centro, giro y profundidad de la capa, EN PIXELES.

    Es la mitad de `object_mvp` que no depende de a donde vaya el resultado.
    Se separa porque hay dos destinos y tienen que coincidir: clip space para
    dibujar, y coordenadas del lienzo para iluminar. Si divergieran, la luz
    caeria en un sitio distinto de donde se ve la capa.
    """
    w, h = canvas
    # Una capa `passthrough` (composelayer, fullscreenlayer, projectlayer)
    # trabaja sobre el fotograma completo: su origin y su size describen el
    # rectangulo que el autor ve en el editor, no donde se dibuja.
    origin, scale, angles = transform_absoluto(obj, por_id)
    if not _floats(obj.raw.get("origin")):
        origin = [w / 2, h / 2, 0.0]      # sin origin declarado: al centro
    size = (_floats(obj.raw.get("size")) + [float(w), float(h)])[:2]

    # Semiextension y centro, normalizados a clip space (-1..1).
    if mesh:
        sx = 2.0 * scale[0] / w
        sy = 2.0 * scale[1] / h
    else:
        sx = size[0] * scale[0] / w
        sy = size[1] * scale[1] / h
    crop = (_floats(obj.raw.get("_cropoffset")) + [0.0, 0.0])[:2] if APPLY_CROP else [0.0, 0.0]

    # `alignment` dice a QUE punto del rectangulo se refiere `origin`. El valor
    # por defecto es `center`, que es lo que asume el resto de este calculo;
    # los demas desplazan el centro media capa en la direccion que toque.
    #
    # Solo se aplica si la capa declara `size`: sin el, `size` cae al lienzo
    # entero y el desplazamiento seria de media pantalla. En el corpus son 51
    # objetos de 448 --- los otros 397 dicen `center`, o sea nada.
    ax, ay = origin[0] + crop[0], origin[1] + crop[1]
    alin = obj.raw.get("alignment")
    if isinstance(alin, str) and _floats(obj.raw.get("size")):
        media_w, media_h = size[0] * scale[0] / 2.0, size[1] * scale[1] / 2.0
        # El eje Y del lienzo crece hacia arriba, como en clip space.
        if "left" in alin:
            ax += media_w
        elif "right" in alin:
            ax -= media_w
        if "bottom" in alin:
            ay += media_h
        elif "top" in alin:
            ay -= media_h

    return (sx * w / 2.0, sy * h / 2.0, ax, ay,
            math.cos(angles[2]), math.sin(angles[2]), origin[2])


def object_world(obj, canvas: tuple[int, int], mesh: bool = False,
                 por_id: dict | None = None) -> list[float]:
    """Matriz que lleva la geometria del objeto a coordenadas del LIENZO.

    Es `object_mvp` parada un paso antes: sin normalizar a clip space. Ese
    espacio intermedio --- pixeles del lienzo, z hacia el espectador --- es el
    mundo que ven los shaders en `v_WorldPos`, y es el mismo en el que la
    escena declara el `origin` de sus luces. No hay conversion de por medio
    porque no hace falta ninguna: son las mismas unidades.
    """
    hx, hy, ax, ay, c, s, az = _colocacion(obj, canvas, mesh, por_id)
    return [ hx * c, -hy * s, 0.0, ax,
             hx * s,  hy * c, 0.0, ay,
             0.0,     0.0,    1.0, az,
             0.0,     0.0,    0.0, 1.0]


def particle_mvp(obj, canvas: tuple[int, int],
                 por_id: dict | None = None) -> list[float]:
    """Matriz de un sistema de particulas: pixeles del sistema -> clip space.

    Aqui no hay rectangulo de capa que llenar. Las particulas nacen en
    coordenadas del propio sistema --- el emisor las reparte alrededor del
    (0,0,0) local --- y el objeto dice donde cae ese origen en el lienzo. Asi
    que la matriz lleva directamente del espacio del sistema al lienzo entero,
    y el objeto se compone despues con la identidad.

    Es lo contrario que una capa de imagen, y por una razon concreta: el tamano
    de cada sprite tambien va en pixeles del sistema, asi que `scale` tiene que
    afectar por igual a donde caen las particulas y a lo grandes que son. Con
    una sola matriz sale gratis.
    """
    w, h = canvas
    origin, scale, angles = transform_absoluto(obj, por_id)
    if not _floats(obj.raw.get("origin")):
        origin = [w / 2, h / 2, 0.0]
    c, s = math.cos(angles[2]), math.sin(angles[2])
    sx, sy = scale[0], scale[1]
    # La tercera fila va a CERO, no a la identidad. Una particula se mueve en
    # las tres dimensiones aunque la escena sea plana --- la turbulencia sin
    # mascara empuja tambien en z --- y su z local esta en pixeles: valores de
    # 10 o 20 salen del rango de recorte [-1, 1] y GL descarta el triangulo
    # entero. Dos antorchas de un wallpaper se simulaban perfectamente y no
    # dibujaban un solo pixel, sin ningun error de por medio.
    #
    # Aplanarlas no pierde nada: la prueba de profundidad esta desactivada en
    # todo el motor y el orden lo decide la secuencia de pases.
    return [2.0 * sx * c / w, -2.0 * sy * s / w, 0.0, 2.0 * origin[0] / w - 1.0,
            2.0 * sx * s / h,  2.0 * sy * c / h, 0.0, 2.0 * origin[1] / h - 1.0,
            0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 1.0]


def particle_world(obj, canvas: tuple[int, int],
                   por_id: dict | None = None) -> list[float]:
    """`particle_mvp` parada antes de clip space: sistema -> lienzo.

    A diferencia de la de dibujo, esta SI lleva la z. Aquella la aplana porque
    una particula con z de 10 o 20 se saldria del rango de recorte y GL tiraria
    el triangulo; aqui no hay recorte que valga, y la z es justo lo que decide
    si la particula esta delante o detras del foco.
    """
    w, h = canvas
    origin, scale, angles = transform_absoluto(obj, por_id)
    if not _floats(obj.raw.get("origin")):
        origin = [w / 2, h / 2, 0.0]
    c, s = math.cos(angles[2]), math.sin(angles[2])
    return [scale[0] * c, -scale[1] * s, 0.0,      origin[0],
            scale[0] * s,  scale[1] * c, 0.0,      origin[1],
            0.0,           0.0,          scale[2], origin[2],
            0.0,           0.0,          0.0,      1.0]


# La camara de estas escenas es ortografica ---`orthogonalprojection`---, asi
# que el espectador esta en el infinito y el vector de vista es constante:
# (0, 0, 1) para todo el lienzo. Los shaders no lo reciben hecho, lo derivan de
# `g_EyePosition - worldPos`, asi que la unica forma de decir "infinito" es un
# ojo lo bastante lejos. A 100.000 px el borde de un lienzo de 3840 se desvia
# 1,1 grados, que no se ve; poner el ojo cerca inventaria una perspectiva que
# la escena no tiene y ladearia los brillos hacia el centro.
OJO_Z = 100000.0

# WE reserva sitio para cuatro luces por pase: `g_LightsPosition[4]`. En el
# corpus ninguna escena pasa de tres.
MAX_LUCES = 4

# Con que cae la luz entre su origen y su radio: `saturate(1 - d/radio)` elevado
# a esto. Sale de la generacion anterior de shaders, que atenua el difuso con
# `lightAttn * lightAttn`. No esta en el formato de escena, asi que es un valor
# por defecto, no un dato leido.
EXPONENTE_POR_DEFECTO = 2.0


def inversa_de(mvp: list[float]) -> list[float]:
    """La inversa de una MVP, sorteando la fila z aplanada.

    `particle_mvp` pone la tercera fila a CERO a proposito ---una particula con
    z de 10 px se saldria del rango de recorte y GL tiraria el triangulo--- y
    eso deja la matriz singular. Para invertirla se le repone la identidad en
    esa fila: quien lee la inversa la usa para llevar el puntero de clip space
    al espacio local, donde la z no pinta nada.
    """
    m = np.array(mvp, dtype=np.float64).reshape(4, 4)
    if abs(np.linalg.det(m)) < 1e-12:
        m = m.copy()
        m[2] = [0.0, 0.0, 1.0, 0.0]
    try:
        return list(np.linalg.inv(m).ravel())
    except np.linalg.LinAlgError:
        return list(IDENTITY)


def vp_de(mvp: list[float], mundo: list[float]) -> list[float]:
    """La matriz vista-proyeccion que le falta al pase, deducida de las otras.

    Con la iluminacion encendida el vertice deja de usar la MVP para colocar el
    triangulo y pasa por el mundo: `gl_Position = mul(worldPos, M_VP)`. O sea
    que pide una tercera matriz que el plan nunca ha emitido; sin ella GL la da
    a cero, el quad colapsa a un punto y la capa desaparece --- que es como se
    quedaba la escena entera en negro, sin un solo error de por medio.

    No hay que inventarla: la MVP y la de mundo ya estan, y como
    `MVP = VP * Mundo`, la que falta es `MVP * Mundo^-1`. Sale exacta para
    cualquier tipo de pase ---capa, malla o particula--- sin distinguir casos, y
    por construccion el triangulo acaba en el mismo sitio que sin luces.
    """
    try:
        w = np.linalg.inv(np.array(mundo, dtype=np.float64).reshape(4, 4))
    except np.linalg.LinAlgError:
        # Una capa con un eje a escala cero. No se puede deshacer, y forzar la
        # cuenta daria infinitos: mejor la proyeccion del lienzo, que al menos
        # deja la geometria en pantalla.
        return list(IDENTITY)
    return list((np.array(mvp, dtype=np.float64).reshape(4, 4) @ w).ravel())


def uniforms_de_tinte(col: list[float], alfa: float, brillo: float) -> list[str]:
    """Color, brillo y opacidad del objeto, por los tres nombres que se leen.

    Cada generacion de shaders lee la opacidad de un sitio, y son ramas
    excluyentes del mismo fichero: `genericimage2` aplica `g_Color4` entero
    ---rgb Y alfa--- si esta definido VERSION, y si no `g_Brightness` sobre el
    rgb y `g_UserAlpha` sobre el alfa. Mandarla solo en `g_Alpha` la perdia en
    las dos: ese nombre lo usan otros seis shaders, ninguno de estos.

    No se aplica dos veces: en toda la libreria no hay un `.frag` que lea dos
    de los tres.
    """
    return [f"u4f g_Color4 {col[0]:.6g} {col[1]:.6g} {col[2]:.6g} {alfa:.6g}",
            f"u1f g_Brightness {brillo:.6g}",
            f"u1f g_UserAlpha {alfa:.6g}",
            f"u1f g_Alpha {alfa:.6g}"]


def textura_por_defecto(meta_uni: dict | None) -> str:
    """Con que rellenar un sampler que el material deja sin enlazar.

    El shader lo dice en sus metadatos. Hay que hacerle caso: un sampler sin
    enlazar NO lee negro, se queda en la unidad 0 ---la del slot 0--- y el
    shader acaba usando la propia imagen como si fuera el otro mapa.

    Los `_rt_*` y los `_alias_*` devuelven cadena vacia a proposito: no son
    ficheros sino buffers de subsistemas que este motor no tiene ---sombras,
    reflejos, cookies de luz--- y fabricarlos vacios es peor que dejarlos.
    """
    d = str((meta_uni or {}).get("default", ""))
    return "" if d.startswith(("_rt_", "_alias_")) else d


def _inverso(x: float) -> float:
    """1/x, pero un eje aplastado no colapsa la normal.

    Una escala de 0 dejaria esa fila de la matriz a cero y con ella la normal;
    `normalize(0, 0, 0)` es NaN y una capa en NaN se lleva por delante todo lo
    que se componga encima. Ya ha pasado dos veces en este motor.
    """
    return 1.0 / x if abs(x) > 1e-9 else 1.0


def matriz_normales(c: float, s: float) -> list[float]:
    """La matriz de normales: SOLO el giro, escrita por filas como las demas.

    La traspuesta de la inversa ---`R * S^-1`, que es lo que pide un normal
    bajo escala no uniforme--- aqui es justo lo que no vale. Este uniform no se
    usa solo para girar la normal: el shader lo mete en `BuildTangentSpace` y
    con el arma la BASE en la que luego expresa la direccion a cada luz. Una
    base que encoge x e y por 1/1920 no cambia hacia donde apunta esa
    direccion, pero le cambia el MODULO, y el modulo es la distancia a la luz
    de la que sale `color / d^2`. Con la distancia dividida por dos mil, el
    fondo entero salia blanco puro.

    El giro es ortonormal, conserva longitudes, y para una capa plana ---cuya
    normal es (0, 0, 1) por construccion--- deja la normal donde estaba, que es
    lo correcto: escalar el ancho de una imagen no la inclina.
    """
    return [c, -s, 0.0,
            s,  c, 0.0,
            0.0, 0.0, 1.0]


def colores_premultiplicados(luces) -> list[list[float]]:
    """Las cuatro luces empaquetadas en tres vec4, como las pide WE.

    `g_LightsColorPremultiplied` no es una lista de colores: es la traspuesta.
    Los tres primeros van en el `.rgb` de cada elemento y el CUARTO se reparte
    por los tres `.w`. Asi caben cuatro colores en tres vec4 sin desperdiciar
    registros, y el shader lo recompone con
    `vec3(g_LightsColorPremultiplied[0].w, [1].w, [2].w)`.

    "Premultiplicado" es por el radio al cuadrado. Los shaders que leen esta
    array atenuan con `color / d^2` y nada mas ---no reciben el radio---, asi
    que sin ese factor una luz de radio 1200 llegaria a su propio borde con
    0.7/1.44e6, que es invisible. Con el, a la distancia del radio la luz vale
    exactamente su color, que es lo que el autor ve en el editor.
    """
    cols = []
    for i in range(MAX_LUCES):
        if i < len(luces):
            _, col, radio, _exp = luces[i]
            cols.append([c * radio * radio for c in col])
        else:
            cols.append([0.0, 0.0, 0.0])
    return [[cols[i][0], cols[i][1], cols[i][2], cols[3][i]] for i in range(3)]


def luces_de_escena(scene) -> list[tuple[list[float], list[float], float]]:
    """Las luces puntuales visibles, en coordenadas del lienzo.

    Devuelve por luz: posicion, color ya multiplicado por su intensidad, radio
    y exponente de decaimiento. La intensidad se funde con el color porque el
    shader no la recibe aparte. El radio se queda suelto: uno de los dos
    caminos lo manda tal cual y el otro lo necesita al cuadrado dentro del
    color, y de eso ya se ocupa `colores_premultiplicados`.

    El exponente no sale del `scene.json` ---ninguna de las 9 luces del corpus
    lo declara, y el campo `exponent` del formato es de color, no de luces---
    pero tampoco es una constante del shader: en el modulo que WE genera de
    verdad viaja con cada luz, en el `.w` de su origen. Aqui viaja igual, con
    `EXPONENTE_POR_DEFECTO` mientras no se sepa de donde leerlo, para que el
    dia que aparezca sea una linea y no un cambio de shader.

    Devuelve la lista VACIA si la escena tiene alguna luz visible que no sea
    puntual. Las de tipo `ltube` son un SEGMENTO, no un punto: su brillo sale
    de los dos extremos y la escena solo declara el centro, asi que no hay
    forma de ponerla. Y encender la iluminacion a medias sale peor que no
    encenderla: el shader cambia el color por `ambiente * albedo + luz`, o sea
    que el ambiente OSCURECE la capa contando con que las luces devuelvan lo
    que quita. Medido en la unica escena del corpus donde pasa (3053927686,
    una luz de tubo y una puntual fuera de alcance): con la luz a medias cae de
    39.31 a 11.52 de media, y su propio preview esta en 89.99.
    """
    fuera = []
    for obj in scene.objects:
        if obj.kind != "light":
            continue
        if not wescene.is_visible(obj.raw.get("visible"), scene.properties):
            continue                      # apagada por el autor: no cuenta
        if str(obj.raw.get("light") or "") not in ("point", "lpoint"):
            return []
        org = (_floats(obj.raw.get("origin")) + [0.0, 0.0, 0.0])[:3]
        col = (_floats(obj.raw.get("color")) + [1.0, 1.0, 1.0])[:3]
        # `intensity` y `origin` pueden venir animados o guiados por script ---
        # la luz que sigue al cursor de una escena del corpus. `_floats` se
        # queda con el valor guardado, que es la pose en que el autor lo dejo.
        ints = (_floats(obj.raw.get("intensity")) + [1.0])[0]
        radio = (_floats(obj.raw.get("radius")) + [0.0])[0]
        if radio <= 0.0:
            continue                      # sin alcance no alumbra nada
        fuera.append(([org[0], org[1], org[2]],
                      [col[0] * ints, col[1] * ints, col[2] * ints], radio,
                      EXPONENTE_POR_DEFECTO))
    return fuera[:MAX_LUCES]


def layer_size(obj, canvas: tuple[int, int]) -> tuple[float, float]:
    """Tamano del rectangulo de la capa en pixeles, sin escala ni colocacion."""
    size = (_floats(obj.raw.get("size")) + [float(canvas[0]), float(canvas[1])])[:2]
    return max(size[0], 1.0), max(size[1], 1.0)


APPLY_CROP = bool(int(os.environ.get("WE_APPLY_CROP", "0")))

COMPOSITE_RT_RE = re.compile(r"^_rt_imageLayerComposite_(\d+)_[ab]$")

# Nombres con los que un shader pide lo que ya hay dibujado detras. No son
# buffers propios: el ejecutor los resuelve al acumulado de la escena.
BUFFERS_DEL_MOTOR = ("_rt_FullFrameBuffer", "_rt_MipMappedFrameBuffer")


def _buffers_de_composicion(scene) -> dict[str, list[str]]:
    """Por id de capa, los buffers `_rt_imageLayerComposite_*` que otra lee.

    Se deduce recorriendo la escena, no de una lista escrita a mano: vale para
    cualquier wallpaper que use el mecanismo. Las autorreferencias se excluyen
    --- ahi el nombre significa el par ping-pong del propio objeto.
    """
    fuera: dict[str, list[str]] = {}
    for o in scene.objects:
        mio = str(o.raw.get("id"))
        for e in (o.raw.get("effects") or []):
            if not isinstance(e, dict):
                continue
            for ps in (e.get("passes") or []):
                if not isinstance(ps, dict):
                    continue
                for t in (ps.get("textures") or []):
                    m = COMPOSITE_RT_RE.match(t) if isinstance(t, str) else None
                    if m and m.group(1) != mio and t not in fuera.get(m.group(1), ()):
                        fuera.setdefault(m.group(1), []).append(t)
    return fuera


def rt_size(name: str, canvas: tuple[int, int]) -> tuple[int, int]:
    """WE codifica el divisor de resolucion en el nombre del render target.

    Tiene que coincidir con lo que hace glexec al crearlos, o los shaders
    reciben una resolucion que no corresponde a la textura que muestrean.
    """
    div = 1
    if "Half" in name:
        div = 2
    elif "Quarter" in name:
        div = 4
    elif "Eighth" in name:
        div = 8
    return canvas[0] // div, canvas[1] // div


def _floats(value) -> list[float]:
    """Los valores de WE pueden ser numero, bool o cadena '0.5 0.2 0.1'."""
    if isinstance(value, dict):
        # Un campo animado por script llega como objeto: `{"script": "...",
        # "value": "206.97 312.49 0"}`. `value` es la copia que el autor tenia
        # al guardar, igual que en `visible`. No hay motor de scripts, asi que
        # esa copia es la mejor aproximacion; devolver [] era lo peor posible,
        # porque `origin` caia al centro del lienzo y `scale` a 1.
        #
        # En Cyberpunk Edgerunners-Lucy eso mandaba al centro la atmosfera, el
        # reloj y la capa de posicionamiento. En el corpus son 249 objetos de
        # 21 escenas: 49 origin, 39 scale, 9 angles, 89 color y 63 alpha.
        return _floats(value.get("value"))
    if isinstance(value, bool):
        return [1.0 if value else 0.0]
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        try:
            return [float(x) for x in value.split()]
        except ValueError:
            return []
    if isinstance(value, list):
        out: list[float] = []
        for v in value:
            out.extend(_floats(v))
        return out
    return []


def _trs(pos, rot, scale) -> np.ndarray:
    """Matriz 4x4 en convencion de vector-fila, como las del propio formato."""
    cz, sz = math.cos(rot[2]), math.sin(rot[2])
    m = np.eye(4, dtype=np.float64)
    m[0, 0], m[0, 1] = cz * scale[0], sz * scale[0]
    m[1, 0], m[1, 1] = -sz * scale[1], cz * scale[1]
    m[2, 2] = scale[2] if scale[2] else 1.0
    m[3, 0:3] = pos
    return m


def _smooth_weights(mesh, n_bones: int, iters: int) -> np.ndarray:
    """Difunde los pesos de hueso sobre la conectividad de la malla.

    El .mdl trae pesos casi binarios: en Jeanne, 384 de 431 vertices estan
    atados a UN solo hueso con peso 1. Esa atadura dura es lo que desgarra la
    costura entre el brazo (que rota 0.47) y el cuerpo (estatico), y lo que
    concentra la cizalla del skinning lineal en unas pocas aristas -- el
    "codo" que en realidad no existe, porque los dos huesos que mueven el
    brazo tienen su pivote en el hombro, a 124 px uno del otro.

    Suavizar promedia el peso de cada vertice con el de sus vecinos y
    renormaliza. Conserva las regiones que definio el artista (el centro de
    cada region apenas cambia) y solo ablanda las fronteras, que es donde
    esta el problema.
    """
    if iters <= 0:
        return np.asarray(mesh.bone_weights, dtype=np.float64)

    nv = mesh.vertex_count
    W = np.zeros((nv, n_bones))
    idx = np.asarray(mesh.bone_indices)
    w0 = np.asarray(mesh.bone_weights, dtype=np.float64)
    for slot in range(4):
        val = np.clip(idx[:, slot], 0, n_bones - 1)
        np.add.at(W, (np.arange(nv), val), w0[:, slot])

    # Vecindario por aristas de los triangulos.
    tri = np.asarray(mesh.indices).reshape(-1, 3)
    a = np.concatenate([tri[:, 0], tri[:, 1], tri[:, 2]])
    b = np.concatenate([tri[:, 1], tri[:, 2], tri[:, 0]])
    src = np.concatenate([a, b])
    dst = np.concatenate([b, a])
    grado = np.bincount(src, minlength=nv).astype(np.float64)
    grado[grado == 0] = 1.0

    for _ in range(iters):
        acum = np.zeros_like(W)
        np.add.at(acum, src, W[dst])
        W = 0.5 * W + 0.5 * (acum / grado[:, None])
        W /= np.maximum(W.sum(axis=1, keepdims=True), 1e-12)
    return W


def _skin_matrices(bones, anim, k: int) -> np.ndarray:
    """Matriz de skinning de cada hueso en la clave `k`: (huesos, 4, 4).

    Skinning jerarquico estandar con vector-fila:

        G_j = B_j · G_padre        matriz de reposo, compuesta hasta la raiz
        P_j = A_j · P_padre        pose animada, compuesta igual
        skin_j = inv(G_j) · P_j

    Las matrices del MDLS y las claves del MDLA son LOCALES a su padre, y hay
    que componer las dos o ninguna. Aqui se probo antes componer solo la pose
    animada dejando la de reposo sin componer: esa mezcla inconsistente daba
    un resultado roto y llevo a descartar la jerarquia entera, que era la
    conclusion equivocada.

    Lo que lo demuestra es anatomico. En el brazo de Jeanne, el hueso 1 es
    hijo del 0. Sin componer, su anclaje cae en canvas (2243,858), a 124 px
    del hombro -- dos huesos apilados en el mismo sitio, que cizallan el brazo
    en vez de articularlo. Compuesto cae en (2465,567): el codo, justo entre
    el hombro (2142,785) y el guantelete (2406,490).

    Medido sobre las cuatro capas, componer mejora o empata en todas y no
    mueve ni un pixel lo que debe quedarse quieto (la pierna de Jeanne sigue
    a 0 px). El brazo del estandarte pasa de 7 aristas rotas a 0, con el
    estiron maximo de 1.450 a 1.052. jdarcjik no cambia, y es el control:
    sus dos huesos son raiz, asi que componer no puede alterarlo.

    Los padres siempre aparecen antes que sus hijos en el bloque MDLS, asi que
    basta un recorrido en orden.
    """
    def componer(mats):
        g: list[np.ndarray] = []
        for j, bone in enumerate(bones):
            g.append(mats[j] @ g[bone.parent] if 0 <= bone.parent < j else mats[j])
        return g

    reposo = [np.asarray(b.matrix, dtype=np.float64) for b in bones]
    pose = []
    for j in range(len(bones)):
        tr = anim.tracks[min(j, anim.tracks.shape[0] - 1)][k]
        pose.append(_trs(tr[0:3], tr[3:6], tr[6:9]))

    G, P = componer(reposo), componer(pose)
    return np.stack([np.linalg.inv(G[j]) @ P[j] for j in range(len(bones))])


def _skin(mesh, blob: bytes, rel: str, stats, notes) -> np.ndarray:
    """Deforma la malla por huesos en el instante WE_PUPPET_TIME.

    Es skinning en CPU, horneado a un tiempo fijo: sirve para comprobar que
    las pistas son correctas comparando dos renders a tiempos distintos, sin
    tocar el motor. La animacion de verdad necesita evaluar los huesos por
    fotograma en C++ y subirlos como `g_Bones[]`.

    Las matrices del formato son de vector-fila (`v * M`), igual que la MVP.
    La formula es la de siempre: v' = suma_j peso_j * (v * inv(B_j) * A_j),
    con B_j la matriz de reposo del hueso y A_j su transformacion animada.
    """
    t = os.environ.get("WE_PUPPET_TIME")
    if t is None:
        return np.asarray(mesh.positions, dtype=np.float64)
    try:
        bones, p = wemdl.parse_skeleton(blob, mesh.consumed, rel)
        if blob[p:p + 4] != b"MDLA":
            raise wemdl.MdlError("sin bloque de animacion")
        anims, _ = wemdl.parse_animations(blob, p, rel, len(bones))
    except wemdl.MdlError as e:
        notes.append(f"puppet sin animacion ({rel}): {e}")
        return np.asarray(mesh.positions, dtype=np.float64)
    if not anims:
        return np.asarray(mesh.positions, dtype=np.float64)

    a = anims[0]
    keys = a.tracks.shape[1]
    # El ultimo fotograma repite el primero para cerrar el bucle, asi que el
    # periodo son `keys - 1` intervalos.
    k = int(round((float(t) / max(a.duration, 1e-6)) * (keys - 1))) % max(keys - 1, 1)

    v = np.concatenate([np.asarray(mesh.positions, dtype=np.float64),
                        np.ones((mesh.vertex_count, 1))], axis=1)
    out = np.zeros((mesh.vertex_count, 4))
    W = _smooth_weights(mesh, len(bones), int(os.environ.get("WE_PUPPET_SMOOTH", "40")))
    skin = _skin_matrices(bones, a, k)
    for j in range(len(bones)):
        out += W[:, j, None] * (v @ skin[j])
    stats["puppet_animado"] += 1
    return out[:, 0:3]


class MeshAnim(NamedTuple):
    """Bloque de animacion listo para escribir tras los indices de la malla."""

    bones: int
    keys: int
    duration: float
    blocks: tuple[bytes, ...]
    extent: tuple[float, float] = (0.0, 0.0)   # |x|,|y| max de la malla deformada


class Renderer:
    def __init__(self, wallpaper: Path, exec_path: Path, time: float = 0.0):
        self.res = AssetResolver.for_wallpaper(wallpaper, wepaths.we_assets())
        self.exec_path = exec_path
        self.time = time
        self.tmp = Path(tempfile.mkdtemp(prefix="werender-"))
        self.tex_ids: dict[str, int] = {}
        self.lines: list[str] = []   # cabecera: canvas, texturas y mallas
        self.body: list[str] = []    # los pases, repetibles por fotograma
        # Malla puppet por objeto. La clave es id(obj) y no el nombre porque
        # dos capas pueden compartirlo; el objeto es el que manda.
        self.meshes: dict[int, int] = {}
        # Margen de render por objeto; ver _emit_mesh.
        self.margins: dict[int, float] = {}
        self.canvas: tuple[int, int] = (1920, 1080)
        # Luces de la escena y su ambiente; los rellena `_build` al leerla.
        self.luces: list[tuple[list[float], list[float], float]] = []
        self.ambiente: list[float] = [1.0, 1.0, 1.0]
        self.cielo: list[float] = [1.0, 1.0, 1.0]
        self.mesh_files: list[Path] = []
        self.notes: list[str] = []
        self.stats = {"pases": 0, "sin_shader": 0, "sin_textura": 0,
                      "puppet": 0, "puppet_omitido": 0, "puppet_animado": 0,
                      "psys": 0, "psys_parcial": 0, "psys_estela": 0,
                      "psys_cinta": 0, "psys_sin_estela": 0}
        self.dump_dir: Path | None = None
        self._tex_dims: dict[int, tuple[int, int]] = {}
        # Sistema de particulas por objeto, con la misma clave que las mallas.
        self.psys: dict[int, int] = {}
        # Los tres numeros de `g_RenderVar0` de los objetos con `spritetrail`.
        self.estelas: dict[int, tuple[float, float, float]] = {}
        # `(modo, puntos, intervalo)` de los objetos con `rope` o `ropetrail`.
        self.cintas: dict[int, tuple[int, int, float]] = {}
        self._hojas: dict[str, tuple[int, tuple | None]] = {}
        self.por_id: dict[str, object] = {}

    # ── texturas ──────────────────────────────────────────────────────────
    def texture(self, name: str, mode: str = "",
                margin: float = 1.0, flip: bool = True) -> tuple[int, int, int] | None:
        """Decodifica una textura a RGBA cruda y devuelve (id, ancho, alto).

        `mode` es el modo que declara el sampler en sus metadatos. Los mapas
        `flowmask` codifican un VECTOR de arrastre por pixel: RG - 0.498 son
        (dx, dy) en convencion de WE, con v hacia abajo. Nuestro buffer vive
        con v hacia arriba, asi que ademas de recolocar el mapa (eso lo hace
        el volteo comun) hay que invertir el VALOR de su componente vertical:
        sin ello el parpado de Jeanne -- un `shake` cuyo flujo tira del
        parpado -- arrastraba hacia arriba y el gesto salia al reves.
        """
        clave = (name, mode == "flowmask", round(margin, 4), flip)
        if clave in self.tex_ids:
            i = self.tex_ids[clave]
            return i, self._tex_dims[i][0], self._tex_dims[i][1]
        try:
            tex = wetex.read_texture(self.res.read_bytes(wescene.texture_path(name)))
            mip = tex.images[0][0]
            rgba = mip.to_rgba(tex.format)
        except Exception:
            self.stats["sin_textura"] += 1
            return None

        # WE rellena las texturas hasta potencia de dos y a veces el relleno
        # esta EN LOS PIXELES, no solo en la cabecera: el fondo de Sniper Girl
        # es una imagen de 2560x1440 dentro de un buffer de 4096x2048, en la
        # esquina superior izquierda, con el resto a alfa cero. Subiendo el
        # buffer entero, las UV 0..1 de la capa recorren tambien el relleno y
        # la escena sale encogida en un rincon ocupando 0.625 x 0.703 de la
        # pantalla, con el resto negro --- que es exactamente lo que se veia.
        #
        # Se recorta aqui, ANTES del volteo, porque la imagen esta arriba en
        # el orden en que WE la guarda. Recortar en vez de pasar la proporcion
        # en `g_TextureNResolution` es lo que funciona con cualquier shader:
        # los de WE que escalan las UV con `.zw / .xy` obtienen 1 y muestrean
        # la textura entera, que ya es la imagen, y los que no escalan --- el
        # pase base usa `a_TexCoord` tal cual --- tambien aciertan.
        iw, ih = tex.image_size
        h0, w0 = rgba.shape[:2]
        if 0 < iw < w0 or 0 < ih < h0:
            rgba = np.ascontiguousarray(rgba[:min(ih or h0, h0), :min(iw or w0, w0)])
            self.stats["texturas_recortadas"] = \
                self.stats.get("texturas_recortadas", 0) + 1

        # glReadPixels y las UV de GL van de abajo a arriba; las texturas de WE
        # se guardan con el origen arriba. Se voltea al subir, una sola vez.
        #
        # Las de particula NO. En una capa normal el volteo se cancela con el de
        # las UV, pero un sprite muestrea un RECTANGULO de la textura y ahi no
        # se cancela nada: la fila 0 de la hoja acabaria abajo y los fotogramas
        # se reproducirian en orden inverso, cada uno del reves. El quad de la
        # particula lo construye `weparticles.c` con v=0 arriba, que es
        # exactamente la orientacion de la textura sin voltear.
        if flip:
            rgba = np.ascontiguousarray(rgba[::-1])
        if mode == "flowmask":
            # G' espeja G alrededor del centro 0.498 (127 en 8 bits).
            rgba = rgba.copy()
            rgba[:, :, 1] = 254 - rgba[:, :, 1]

        # Las mascaras estan pintadas sobre el rectangulo de la capa y los
        # pases de efecto las muestrean con a_TexCoord sobre TODO el buffer.
        # Si la capa se renderiza con margen (ver _emit_mesh), el buffer es
        # mayor que la capa y la mascara se estiraria: el parpadeo de Jeanne
        # dejaba de caer sobre los ojos. Se rellena con el mismo margen para
        # que la parte pintada siga cubriendo exactamente la capa.
        #
        # El borde va a 0 en las mascaras de opacidad (fuera de la capa el
        # efecto no actua) y a 127 en las de flujo, que es su valor neutro.
        if margin > 1.0 and mode in ("opacitymask", "flowmask"):
            h0, w0 = rgba.shape[:2]
            w1, h1 = int(round(w0 * margin)), int(round(h0 * margin))
            relleno = 127 if mode == "flowmask" else 0
            lienzo = np.full((h1, w1, 4), relleno, dtype=rgba.dtype)
            if mode == "opacitymask":
                lienzo[:, :, 3] = 255
            x0, y0 = (w1 - w0) // 2, (h1 - h0) // 2
            lienzo[y0:y0 + h0, x0:x0 + w0] = rgba
            rgba = lienzo
        i = len(self.tex_ids)
        path = self.tmp / f"tex{i:03d}.rgba"
        path.write_bytes(rgba.tobytes())
        self.tex_ids[clave] = i
        self._tex_dims[i] = (rgba.shape[1], rgba.shape[0])
        self.lines.append(f"tex {i} {path} {rgba.shape[1]} {rgba.shape[0]}")
        return i, rgba.shape[1], rgba.shape[0]


    # ── particulas ────────────────────────────────────────────────────────
    def info_textura(self, name: str | None):
        """`(formato, hoja)` de una textura de particula.

        `formato` es el codigo de `wetex.TexFormat`, que coincide numero a
        numero con los `FORMAT_*` de `shaders/common_fragment.h`. El shader lo
        recibe en el combo TEX0FORMAT y con el desempaqueta la muestra:
        RG88 y RG1616F guardan el gris en R y el ALFA en G, y sin decirselo el
        shader lee un sprite rojo y completamente opaco. Es lo que convertia los
        haces de luz de un wallpaper en barras rojas macizas cruzando la
        pantalla, y la niebla en manchas grises sin bordes.

        `hoja` es `(ancho_uv, alto_uv, n_fotogramas, proporcion)` si la textura
        es una hoja de sprites, o None. Son 277 de los 823 sistemas del corpus
        --- niebla, humo, fuego, petalos, casi todas de 64 fotogramas --- y sin
        el combo SPRITESHEET la particula muestrea la hoja ENTERA: en vez de una
        voluta de niebla sale la rejilla de 8x8. La rejilla es regular en todo
        el corpus, que es justo lo que asume `ComputeSpriteFrame`: le basta el
        tamano de un fotograma en UV.
        """
        if not name:
            return (0, None)
        if name in self._hojas:
            return self._hojas[name]
        info = (0, None)
        try:
            tex = wetex.read_texture(self.res.read_bytes(wescene.texture_path(name)))
            hoja = None
            if tex.frames:
                f = tex.frames[0]
                # Contra lo que se SUBE, que no es ni `texture_size` ni siempre
                # el mipmap. WE rellena hasta potencia de dos y guarda el
                # tamano relleno en la cabecera; una hoja de 1280x256 declarada
                # como 2048x256 daba fotogramas de 0.125 de ancho en vez de
                # 0.2. Pero el relleno tambien puede estar en los pixeles ---el
                # mipmap mide lo relleno y la imagen ocupa una esquina---, y
                # ahi `texture()` recorta antes de subir. Las dos formas se
                # cubren con el minimo: es el tamano que acaba en la GPU.
                mip = tex.images[0][0]
                iw, ih = tex.image_size
                tw = float(min(mip.width, iw) if iw else mip.width)
                th = float(min(mip.height, ih) if ih else mip.height)
                anc, alt = float(f["width"]), float(f["height"])
                if anc > 0 and alt > 0 and tw > 0 and th > 0:
                    hoja = (anc / tw, alt / th, len(tex.frames), alt / anc)
            info = (int(tex.format), hoja)
        except Exception:
            info = (0, None)
        self._hojas[name] = info
        return info

    def _emit_psys(self, obj) -> None:
        """Escribe el `.psys` del objeto y lo declara en la cabecera del plan."""
        ruta = obj.raw.get("particle")
        if not isinstance(ruta, str) or not ruta:
            return
        try:
            sis = weparticles.cargar(self.res, ruta,
                                     obj.raw.get("instanceoverride"))
        except Exception as e:
            self.notes.append(f"[{obj.name}] particulas: {e}")
            return
        if not sis.dibujable:
            self.notes.append(f"[{obj.name}] particulas sin emisor o sin material")
            return
        if sis.sin_soporte:
            self.stats["psys_parcial"] += 1
            self.notes.append(f"[{obj.name}] piezas sin soporte: "
                              + ", ".join(sis.sin_soporte))

        i = len(self.psys)
        destino = self.tmp / f"s{i:03d}.psys"
        # La semilla se deriva del id del objeto --- con crc32 y no con hash(),
        # que Python aleatoriza entre procesos: dos ejecuciones del mismo
        # wallpaper tienen que dar el mismo PNG o la regresion no compara nada.
        # Que dependa del id, y no del indice, evita ademas que dos sistemas de
        # la misma escena caigan en la misma secuencia.
        semilla = zlib.crc32(str(obj.raw.get("id")).encode()) or 1
        # El campo de ruido de la turbulencia se muestrea en coordenadas del
        # LIENZO, no del sistema. El simulador solo conoce la posicion local de
        # cada particula ---todos los sistemas nacen alrededor de su (0,0,0)---
        # asi que sin esto todos muestrean la misma zona del campo y salen en la
        # misma direccion, sea cual sea el wallpaper. Desplazando el muestreo
        # por el origen del objeto, la direccion pasa a depender de DONDE esta
        # el sistema, que es dato del wallpaper, y dos humos distintos de la
        # misma escena dejan de correr en paralelo.
        org, _, _ = transform_absoluto(obj, self.por_id)
        weparticles.desplazar_ruido(sis, org)
        weparticles.escribir(sis, destino, semilla)
        self.lines.append(f"psys {i} {destino}")
        self.psys[id(obj)] = i
        self.stats["psys"] += 1
        if sis.estela:
            self.estelas[id(obj)] = sis.estela
            self.stats["psys_estela"] += 1
        elif sis.cinta:
            self.cintas[id(obj)] = sis.cinta
            self.stats["psys_cinta"] += 1
        elif sis.renderer != "sprite":
            self.stats["psys_sin_estela"] += 1

    # ── un pase ───────────────────────────────────────────────────────────
    def _emit_mesh(self, obj) -> None:
        """Sube la malla puppet del objeto, si la tiene y sabemos leerla.

        Se escribe intercalada como 5 float por vertice (posicion + UV), que es
        justo el layout del quad del ejecutor: asi los shaders no cambian y el
        VAO de la malla usa las mismas dos localizaciones de atributo.

        Tras los indices va, opcional, el bloque de animacion:

            u16[nverts][4]           indices de hueso
            f32[nverts][4]           pesos
            f32[nkeys][nbones][12]   matrices de skinning ya compuestas

        Las matrices llegan resueltas del todo: inversa de reposo, compuesta
        con la del padre y evaluada en cada clave. El ejecutor solo hace la
        suma ponderada. Asi la trigonometria y la jerarquia viven en un unico
        sitio y las dos implementaciones no pueden discrepar; es ademas el
        reparto que ya usa el resto del proyecto, con Python decidiendo y el
        ejecutor solo ejecutando.

        Son 12 y no 16 floats porque la ultima columna de estas matrices es
        siempre (0,0,0,1). Las claves van por fotograma y no por hueso para
        que el ejecutor lea las de un instante seguidas en memoria.

        El skinning lo hace UNO de los dos, nunca los dos: con WE_PUPPET_TIME
        se hornea aqui (la referencia offline) y no se emite el bloque; sin el
        se manda la pose de reposo con las pistas y deforma el ejecutor.
        """
        if os.environ.get("WE_NO_PUPPET"):
            return          # para aislar la malla al depurar
        # `puppet` no lo declara el objeto sino el modelo al que apunta su
        # `image`, junto a `material` y `autosize`.
        img = obj.raw.get("image")
        if not isinstance(img, str) or not img:
            return
        try:
            rel = self.res.read_json(img).get("puppet")
        except SceneError:
            return
        if not isinstance(rel, str) or not rel:
            return
        try:
            blob = self.res.read_bytes(rel)
            m = wemdl.parse_mdl(blob, rel)
        except (SceneError, wemdl.MdlError, KeyError) as e:
            self.stats["puppet_omitido"] += 1
            self.notes.append(f"puppet sin malla ({rel}): {e}")
            return

        pos = _skin(m, blob, rel, self.stats, self.notes)

        inter = np.empty((m.vertex_count, 5), dtype="<f4")
        inter[:, 0:3] = pos
        inter[:, 3] = m.uvs[:, 0]
        # Las texturas se suben volteadas (ver _tex), asi que v=0 es el borde
        # de abajo. En la malla la v crece hacia abajo: medido como
        # corr(y, v) = -1 exacto en las cuatro capas de Jeanne, que es lo que
        # cabe esperar de una rejilla regular. Hay que invertirla.
        inter[:, 4] = 1.0 - m.uvs[:, 1]
        idx = np.asarray(m.indices, dtype="<u2")

        mid = len(self.mesh_files)
        path = self.tmp / f"mesh{mid:03d}.bin"
        anim = self._mesh_anim(m, blob, rel)
        with open(path, "wb") as fh:
            fh.write(inter.tobytes())
            fh.write(idx.tobytes())
            for parte in anim.blocks if anim else ():
                fh.write(parte)
        self.mesh_files.append(path)
        cola = f" {anim.bones} {anim.keys} {anim.duration:.6f}" if anim else ""
        self.lines.append(f"mesh {mid} {path} {m.vertex_count} {idx.size}{cola}")
        self.meshes[id(obj)] = mid
        # Margen con que se renderiza esta capa: cuanto hay que agrandar su
        # rectangulo para que quepa la malla deformada, con un 5% de holgura.
        # 1.0 si no se sale, para no cambiar nada donde no hace falta.
        margen = 1.0
        if anim:
            sw, sh = layer_size(obj, self.canvas)
            margen = max(1.0, 2.0 * anim.extent[0] / sw, 2.0 * anim.extent[1] / sh) * 1.05
        self.margins[id(obj)] = margen
        self.stats["puppet"] += 1

    def _mesh_anim(self, m, blob: bytes, rel: str) -> MeshAnim | None:
        """Empaqueta huesos y pistas para que el ejecutor deforme por fotograma.

        Devuelve None cuando no hay nada que animar, y tambien cuando el
        skinning ya se horneo en `_skin`: los dos caminos escriben la misma
        posicion y aplicar ambos deformaria dos veces.
        """
        if os.environ.get("WE_PUPPET_TIME") is not None:
            return None
        try:
            bones, p = wemdl.parse_skeleton(blob, m.consumed, rel)
            anims, _ = wemdl.parse_animations(blob, p, rel, len(bones))
        except wemdl.MdlError as e:
            self.notes.append(f"puppet sin animacion ({rel}): {e}")
            return None
        if not bones or not anims:
            return None

        a = anims[0]
        keys = int(a.tracks.shape[1])
        nb = len(bones)

        mats = np.empty((keys, nb, 12), dtype="<f4")
        for k in range(keys):
            mats[k] = _skin_matrices(bones, a, k)[:, :, 0:3].reshape(nb, 12)

        # Los indices de hueso son u32 en el .mdl, pero ningun puppet del
        # corpus pasa de unas decenas de huesos: caben de sobra en u16.
        # WE_PUPPET_SMOOTH difunde los pesos por la malla antes de subirlos;
        # ver _smooth_weights. Se queda con las 4 mayores contribuciones por
        # vertice, que es lo que admite el formato del plan.
        suav = int(os.environ.get("WE_PUPPET_SMOOTH", "40"))
        if suav > 0:
            W = _smooth_weights(m, nb, suav)
            orden = np.argsort(-W, axis=1)[:, :4]
            top = np.take_along_axis(W, orden, axis=1)
            top /= np.maximum(top.sum(axis=1, keepdims=True), 1e-12)
            idx16 = np.zeros((m.vertex_count, 4), dtype="<u2")
            pesos = np.zeros((m.vertex_count, 4), dtype="<f4")
            idx16[:, :orden.shape[1]] = orden
            pesos[:, :top.shape[1]] = top
        else:
            idx16 = np.asarray(m.bone_indices, dtype="<u2")
            pesos = np.asarray(m.bone_weights, dtype="<f4")

        # Extension maxima de la malla deformada, en unidades locales. El
        # buffer del objeto ES su rectangulo, asi que la geometria que se sale
        # se recorta: el guantelete de Jeanne desaparecia al subir el brazo.
        # Se mide en vez de fijar una constante, para no gastar resolucion de
        # buffer en capas que no la necesitan.
        P = np.asarray(m.positions, dtype=np.float64)[:, :2]
        vh = np.c_[P, np.zeros(len(P)), np.ones(len(P))]
        Wd = np.zeros((len(P), nb))
        for sl in range(4):
            np.add.at(Wd, (np.arange(len(P)), np.clip(idx16[:, sl], 0, nb - 1)),
                      pesos[:, sl].astype(np.float64))
        ext = np.abs(P).max(axis=0)
        paso = max(1, keys // 60)
        for kk in range(0, keys, paso):
            M = mats[kk].astype(np.float64).reshape(nb, 4, 3)
            out = np.zeros((len(P), 3))
            for j in range(nb):
                full = np.zeros((4, 4)); full[:, 0:3] = M[j]; full[3, 3] = 1.0
                out += Wd[:, j, None] * (vh @ full)[:, 0:3]
            ext = np.maximum(ext, np.abs(out[:, 0:2]).max(axis=0))

        self.stats["puppet_animado"] += 1
        return MeshAnim(nb, keys, float(a.duration),
                        (idx16.tobytes(), pesos.tobytes(), mats.tobytes()),
                        (float(ext[0]), float(ext[1])))

    def emit_pass(self, p, sresolver, canvas: tuple[int, int], obj=None) -> None:
        # Un sistema de particulas no dibuja el quad de la capa sino lo que
        # simula `weparticles`. Se resuelve lo primero porque decide hasta el
        # shader: las cintas usan otro.
        psys_id = self.psys.get(id(obj)) if obj is not None else None
        particula = psys_id is not None and p.stage == "base"
        estela = self.estelas.get(id(obj)) if particula else None
        cinta = self.cintas.get(id(obj)) if particula else None

        fuente_v, fuente_f = p.vert, p.frag
        if cinta:
            fuente_v = sresolver.read("genericropeparticle.vert")
            fuente_f = sresolver.read("genericropeparticle.frag")

        # Los metadatos del shader dicen que uniform se enlaza con que
        # propiedad del material, y con que valor por defecto.
        #
        # Hay que leerlos CON LOS INCLUDES EXPANDIDOS. Los uniforms comunes se
        # declaran en las cabeceras --- `common_composite.h`,
        # `common_particles.h` --- y mirando solo el fichero de arriba no
        # existen: no se emiten, GL los deja a cero y el shader multiplica por
        # ese cero sin que nada falle. `g_CompositeColor` es el caso claro:
        # `effect.rgb *= g_CompositeColor` con la cabecera diciendo
        # `default: "1 1 1"`. En `2868108515` el fondo se dibujaba entero
        # ---la pantalla llegaba a 183 de media--- y el ultimo pase del efecto
        # de desenfoque lo reescribia a NEGRO con `blend none`. Todo lo que
        # venia detras quedaba pintando sobre negro.
        def metadatos(fuente: str) -> dict:
            texto = weshader.normalise_newlines(fuente)
            try:
                texto = weshader.resolve_includes(texto, sresolver)
            except weshader.ShaderError:
                pass          # sin el include, al menos los de este fichero
            return weshader.parse_uniform_meta(texto)

        meta = metadatos(fuente_f)
        meta.update(metadatos(fuente_v))

        # Un combo declarado en los metadatos de un sampler se activa cuando
        # ese slot esta realmente enlazado en el pase. Sin esto la mascara de
        # un efecto se ignora y el efecto se aplica a la imagen entera: el
        # `pulse` de la escena de referencia hacia oscilar el brillo del
        # wallpaper completo casi al doble en vez de solo la zona enmascarada.
        combos = dict(p.combos)
        # La iluminacion se enciende solo si hay con que iluminar. Un pase con
        # el combo activo y las luces a cero no queda plano: queda NEGRO, porque
        # el shader sustituye el color por `ambiente * albedo + luz` y ahi todo
        # vale cero. Es lo que le pasaba al EVA de Asuka, que desaparecia en una
        # mancha oscura.
        #
        # Y el valor se FUERZA, no se quita. Cada shader trae su propio
        # `default` para el combo ---en `generic4` es 1--- que se aplica en
        # cuanto la clave no esta, asi que borrarla no apaga nada: lo enciende.
        # `obj` entra en la condicion porque de el salen las matrices de mundo:
        # un pase suelto, sin objeto detras, no puede alimentar el combo y
        # encenderlo lo dejaria a oscuras.
        combos["LIGHTING"] = 1 if (self.luces and obj is not None
                                   and combos.get("LIGHTING")) else 0
        # Los reflejos son otro subsistema: piden el fotograma ya compuesto y
        # mipmapeado en `_rt_MipMappedFrameBuffer`. Siguen apagados.
        combos["REFLECTION"] = 0

        # Un sampler con `formatcombo` no se conforma con la textura: pide
        # ademas un `TEX<n>FORMAT` con SU empaquetado, y lo usa como valor
        # dentro del codigo ---`ConvertTextureFormat(TEX8FORMAT, ...)`---, no
        # en un `#if`. Sin definirlo el shader no compila, pero solo cuando esa
        # linea esta viva: por eso no se notaba. Con `LIGHTING` encendido,
        # `fur4` se cae con «undefined variable TEX8FORMAT».
        #
        # Son 17 declaraciones en la libreria y la mitad son el slot 1, el mapa
        # de normales, que es justo lo que enciende el camino de la
        # iluminacion. El formato sale de la textura que se vaya a enlazar de
        # verdad, sea la del material o la que el shader declare por defecto.
        for slot in range(8):
            m = meta.get(f"g_Texture{slot}")
            if not m or not m.get("formatcombo"):
                continue
            nombre = (p.textures[slot]
                      if slot < len(p.textures) and p.textures[slot]
                      else textura_por_defecto(m))
            if not nombre or nombre.startswith("_rt_"):
                continue
            combos.setdefault(f"TEX{slot}FORMAT", self.info_textura(nombre)[0])

        # Los combos del vertice los pone el motor, no el material: describen
        # el formato que va a llegar, que es decision del ejecutor.
        hoja = None
        if particula:
            formato, hoja = self.info_textura(p.textures[0] if p.textures else None)
            combos.update({
                # Como viene empaquetada la muestra del slot 0; ver info_textura.
                "TEX0FORMAT": formato,
                # Sin geometry shader: el quad de cada particula viene ya
                # armado desde CPU. Es la ruta que el propio shader contempla.
                "GS_ENABLED": 0,
                # Siempre se manda velocidad y vida en el vertice; declararlo
                # cuesta 16 bytes por vertice y ahorra una variante de shader.
                "THICKFORMAT": 1,
                # `spritetrail`: el sprite se orienta y se estira a lo largo de
                # su velocidad en vez de por su rotacion. No hace falta
                # historial --- lo resuelve el vertex shader con la velocidad
                # que ya va en el vertice --- y los tres numeros que le faltan
                # viajan en `g_RenderVar0`.
                "TRAILRENDERER": 1 if estela else 0,
                "SPRITESHEET": 1 if hoja else 0,
            })
        if cinta:
            # Las cintas son OTRO shader. Los 66 sistemas `rope`/`ropetrail` del
            # corpus declaran `genericparticle` en su material, igual que los
            # sprites: quien decide el shader es el renderer, no el material.
            #
            # `TRAILRENDERER` distingue los dos repartos de UV que trae
            # `genericropeparticle.vert`: `ropetrail` cuenta desde la cabeza y
            # alarga la cinta mientras nacen segmentos; `rope` la recorre al
            # reves. `SPRITESHEET` no existe aqui --- una cinta no muestrea una
            # hoja de fotogramas --- y la hoja se descarta para que no se emita
            # un combo que ese shader no declara.
            hoja = None
            combos["SPRITESHEET"] = 0
            combos["TRAILRENDERER"] = 1 if cinta[0] == 2 else 0
            combos["TRAILSCROLLALPHA"] = 0
        for uni_name, m in meta.items():
            combo = m.get("combo")
            if not combo or combo in combos:
                continue
            mm = re.fullmatch(r"g_Texture(\d+)", uni_name)
            if mm:
                slot = int(mm.group(1))
                bound = slot < len(p.textures) and p.textures[slot]
                if bound:
                    combos[combo] = 1

        try:
            vert = weshader.translate(fuente_v, "vert", sresolver, combos=combos)
            frag = weshader.translate(fuente_f, "frag", sresolver, combos=combos)
        except Exception:
            self.stats["sin_shader"] += 1
            return

        n = self.stats["pases"]
        vp = self.tmp / f"p{n:03d}.vert"
        fp = self.tmp / f"p{n:03d}.frag"
        vp.write_text(vert)
        fp.write_text(frag)

        self.body.append("pass")
        self.body.append(f"prog {vp} {fp}")
        self.body.append(f"target {p.target or 'SCREEN'}")
        # Los pases de efecto son post-proceso: limpian el destino y escriben
        # la pantalla entera leyendo el resultado anterior. Con la mezcla de GL
        # activada sobre un destino limpiado a (0,0,0,0) sale dstA = srcA^2, y
        # el alfa se hunde pase a pase hasta cero. La composicion entre efectos
        # la hace el propio shader (combo BLENDMODE / ApplyBlending); el
        # `blending` del material describe eso, no el estado de GL.
        if particula:
            # Un sprite de particula se mezcla con los demas sprites DENTRO del
            # buffer del objeto, y ese buffer se compone despues sobre la
            # escena. Los modos `premul_*` son los unicos que dejan un alfa
            # utilizable tras esa doble pasada; ver `set_blend` en glexec.c.
            self.body.append("blend " + ("premul_additive"
                                         if p.blending == "additive"
                                         else "premul_alpha"))
        else:
            self.body.append(f"blend {p.blending if p.stage == 'base' else 'none'}")

        bind_by_index = {b["index"]: b["name"] for b in p.binds}
        for slot in range(8):
            uni = f"g_Texture{slot}"
            name = p.textures[slot] if slot < len(p.textures) else None
            src = None
            if name:
                m_comp = COMPOSITE_RT_RE.match(name)
                if m_comp and obj is not None and m_comp.group(1) == str(obj.raw.get("id")):
                    # `_rt_imageLayerComposite_<id propio>_a|_b` es el par
                    # ping-pong del propio objeto, que el ejecutor ya mantiene.
                    # Crearlo como buffer nuevo lo deja vacio y cualquier
                    # efecto que combine con el da negro. Son 86 de las 122
                    # referencias del corpus.
                    src = "prev"
                elif m_comp:
                    # Apunta a OTRA capa: es una composicion leyendo a sus
                    # fuentes. Esa capa se dibuja aparte y deja aqui su
                    # resultado. 36 referencias en 9 escenas.
                    src = f"rt:{name}"
                elif name.startswith("_rt_"):
                    src = f"rt:{name}"
                else:
                    modo = str(meta.get(uni, {}).get("mode", ""))
                    # Solo los pases de efecto muestrean con a_TexCoord sobre
                    # el buffer; el pase base usa las UV propias de la malla,
                    # que el margen no altera.
                    mg = (self.margins.get(id(obj), 1.0)
                          if obj is not None and p.stage != "base" else 1.0)
                    t = self.texture(name, modo, mg, flip=not particula)
                    if t:
                        src = f"tex:{t[0]}"
                        self.body.append(
                            f"u4f g_Texture{slot}Resolution {t[1]} {t[2]} {t[1]} {t[2]}")
                if src and src.startswith("rt:"):
                    # Todo buffer con nombre necesita su resolucion. Para el
                    # slot 0 no se nota --- el vertice usa la UV base --- pero
                    # los slots 1 y 2 derivan `v_TexCoord.zw` de ella, y a cero
                    # muestrean fuera del buffer: el efecto lee transparente y
                    # se anula.
                    rw, rh = rt_size(name, canvas)
                    self.body.append(
                        f"u4f g_Texture{slot}Resolution {rw} {rh} {rw} {rh}")
            elif particula and str(meta.get(uni, {}).get("default", "")) in BUFFERS_DEL_MOTOR:
                # Sampler oculto que el material no declara y cuyo valor por
                # defecto es el fotograma ya dibujado. Es como `genericparticle`
                # lo recibe para refractarlo: 89 pases del corpus activan
                # REFRACT, y su albedo es blanco opaco a proposito --- toda la
                # imagen sale de deformar lo que hay detras. Sin enlazarlo, el
                # shader multiplica por lo que haya en la unidad de textura y
                # las gotas de lluvia salian como cuadrados blancos macizos.
                #
                # Solo estos dos nombres, que el ejecutor resuelve al buffer de
                # escena sin crear nada. Otros defaults ocultos --- el atlas de
                # sombras, por ejemplo --- pertenecen a subsistemas que no
                # existen, y enlazarlos solo crearia buffers vacios.
                b = str(meta[uni]["default"])
                src = f"rt:{b}"
                rw, rh = rt_size(b, canvas)
                self.body.append(f"u4f g_Texture{slot}Resolution {rw} {rh} {rw} {rh}")
            elif slot in bind_by_index or (slot == 0 and p.stage != "base"):
                b = bind_by_index.get(slot, "previous")
                src = "prev" if b == "previous" else f"rt:{b}"
                # La resolucion tiene que ser la del buffer que se lee, no la
                # del canvas: los pases de blur trabajan a media o a un cuarto
                # y muestrear con la resolucion equivocada descuadra el kernel.
                # `previous` es el buffer del objeto, que representa la capa.
                if b == "previous" and obj is not None:
                    w, h = layer_size(obj, canvas)
                else:
                    w, h = rt_size(b, canvas)
                self.body.append(
                    f"u4f g_Texture{slot}Resolution {w} {h} {w} {h}")
            if src is None:
                # El shader declara el sampler y dice con que rellenarlo cuando
                # el material no lo trae. Hay que hacerlo: un sampler sin
                # enlazar NO lee negro, se queda en la unidad 0 --- que es la
                # del slot 0 --- y el shader acaba usando la propia imagen como
                # si fuera el otro mapa.
                #
                # Es lo que borraba `3624164256`: su parallax por profundidad
                # declara `g_Texture1` con `default: util/black` ---sin mapa
                # pintado no hay desplazamiento--- y al no enlazarlo tomaba el
                # color de la escena por profundidad. El raymarch se iba a
                # muestrear a cualquier parte y la capa desaparecia: 68.17 de
                # media con solo las capas base, 13.07 con el efecto puesto.
                #
                # Los `_rt_*` y los `_alias_*` quedan fuera a proposito: no son
                # ficheros sino buffers de subsistemas que este motor no tiene
                # ---sombras, reflejos, cookies de luz---, y fabricarlos vacios
                # es peor que dejarlos.
                por_defecto = textura_por_defecto(meta.get(uni))
                if por_defecto:
                    t = self.texture(por_defecto,
                                     str(meta[uni].get("mode", "")),
                                     1.0, flip=not particula)
                    if t:
                        src = f"tex:{t[0]}"
                        self.body.append(f"u4f g_Texture{slot}Resolution "
                                         f"{t[1]} {t[2]} {t[1]} {t[2]}")

            if src:
                self.body.append(f"sampler {uni} {src}")

        # Uniforms que aporta el motor.
        # Solo el pase base dibuja geometria; los de efecto son post-proceso a
        # pantalla completa sobre el buffer del objeto y se quedan con la
        # identidad.
        # Solo el pase base de un objeto con puppet dibuja su malla; los de
        # efecto siguen siendo el quad a pantalla completa.
        mesh_id = self.meshes.get(id(obj)) if (obj is not None and p.stage == "base") else None
        if mesh_id is not None:
            self.body.append(f"mesh {mesh_id}")
        if particula:
            self.body.append(f"psys {psys_id}")

        # Los pases corren en el ESPACIO DE LA CAPA: el buffer del objeto
        # representa su rectangulo, no el lienzo. Un quad base lo llena con la
        # identidad; una malla solo pasa de pixeles de capa a clip. Colocarla
        # en el lienzo (origin, scale, angulos) ocurre una unica vez, al
        # componer el objeto sobre la escena con la matriz de `object`.
        #
        # La razon de fondo son las mascaras de los efectos: estan pintadas
        # sobre el rectangulo de la capa y los shaders las muestrean con
        # a_TexCoord. Con los efectos a pantalla completa la mascara se
        # estiraba sobre el lienzo: en Jeanne (capa 4200x2227, lienzo
        # 3840x2160) el parpadeo -- un `shake` cuya mascara son literalmente
        # los parpados -- caia cerca de los ojos pero descuadrado.
        if particula:
            mvp = particle_mvp(obj, canvas, por_id=self.por_id)
        elif obj is not None and p.stage == "base" and mesh_id is not None:
            sw, sh = layer_size(obj, canvas)
            # El margen agranda el rectangulo que se mapea al buffer, para que
            # la malla deformada no se recorte contra el borde. La matriz de
            # colocacion lo deshace al componer, asi que la capa acaba en el
            # mismo sitio y del mismo tamano.
            mg = self.margins.get(id(obj), 1.0)
            mvp = [2.0 / (sw * mg), 0, 0, 0,  0, 2.0 / (sh * mg), 0, 0,
                   0, 0, 1, 0,  0, 0, 0, 1]
        else:
            mvp = IDENTITY
        self.body.append("umat4 g_ModelViewProjectionMatrix " +
                         " ".join(f"{x:.6g}" for x in mvp))
        # Un pase iluminado necesita saber DONDE esta cada fragmento en el
        # lienzo; el resto no gasta esos uniforms ni cambia de comportamiento.
        luz = bool(combos.get("LIGHTING"))
        if particula:
            # `ComputeParticleTangents` orienta el sprite con estos tres ejes.
            # La escena es plana y mira al lienzo de frente, asi que son los
            # canonicos; sin emitirlos GL los da a cero y el quad colapsa a un
            # punto --- no se dibuja nada y no hay error que lo diga.
            # El eje vertical lleva la correccion de la escala NO UNIFORME
            # del objeto. La MVP del sistema escala x e y por separado ---0.25
            # y 0.5 en el humo de Sniper Girl--- y eso estira el sprite al doble
            # de alto que de ancho: la voluta sale como una neblina vertical en
            # vez de un penacho. Medido contra una captura de WE, alla la
            # voluta mide ~150 px de ancho, que es el `size` por la escala EN X,
            # y no 300 de alto. Compensando aqui, el quad sale cuadrado y las
            # posiciones siguen respetando la escala que puso el autor.
            _, _esc, _ = (transform_absoluto(obj, self.por_id) if obj is not None
                          else (None, [1.0, 1.0, 1.0], None))
            _ky = (_esc[0] / _esc[1]) if _esc[1] else 1.0
            self.body.append("u3f g_OrientationRight 1 0 0")
            self.body.append(f"u3f g_OrientationUp 0 {_ky:.6g} 0")
            self.body.append("u3f g_OrientationForward 0 0 1")
            self.body.append("u3f g_ViewRight 1 0 0")
            self.body.append("u3f g_ViewUp 0 1 0")
            # `g_ModelMatrix` no coloca nada: el vertice de particula saca de el
            # `v_WorldPos`, y `gl_Position` sale de la MVP, que va aparte. Sin
            # luces da igual lo que valga mientras sea coherente con el ojo, y
            # se deja como estaba --- clip space y ojo en (0, 0, 1). Con luces
            # tiene que ser el mundo de verdad, porque el foco esta a 500 px del
            # plano y en clip space eso serian 500 pantallas de distancia.
            if luz:
                self.body.append("u3f g_EyePosition "
                                 f"{canvas[0] / 2:.6g} {canvas[1] / 2:.6g} {OJO_Z:.6g}")
                mundo = particle_world(obj, canvas, por_id=self.por_id)
                self.body.append("umat4 g_ViewProjectionMatrix " + " ".join(
                    f"{x:.6g}" for x in vp_de(mvp, mundo)))
                _, _e, _a = transform_absoluto(obj, self.por_id)
                self.body.append("umat3 g_NormalModelMatrix " + " ".join(
                    f"{x:.6g}" for x in matriz_normales(
                        math.cos(_a[2]), math.sin(_a[2]))))
            else:
                self.body.append("u3f g_EyePosition 0 0 1")
                mundo = mvp
            self.body.append("umat4 g_ModelMatrix " + " ".join(f"{x:.6g}" for x in mundo))
            self.body.append("umat4 g_ModelMatrixInverse " +
                             " ".join(f"{x:.6g}" for x in IDENTITY))
            if hoja:
                # Lo que `ComputeSpriteFrame` necesita para recortar la hoja:
                # tamano de un fotograma en UV, cuantos hay, y la proporcion de
                # uno solo --- que es la que decide la forma del sprite, no la
                # de la hoja entera.
                self.body.append(f"u4f g_RenderVar1 {hoja[0]:.6g} {hoja[1]:.6g} "
                                 f"{hoja[2]} {hoja[3]:.6g}")
            else:
                self.body.append("u4f g_RenderVar1 1 1 1 1")
            if cinta:
                # `genericropeparticle.vert` lee en `g_RenderVar0` cuantos
                # segmentos tiene la cinta (.x y .w) y cuanto ha avanzado el
                # reloj desde el ultimo punto del historial (.z).
                #
                # Ese .z es un valor POR FOTOGRAMA y aqui solo hay constantes;
                # con 1 la cuenta se simplifica a `posicion / (puntos - 1)`, que
                # es un reparto de UV estable. Lo que se pierde es el
                # deslizamiento suave de la textura mientras nace un segmento:
                # la cinta avanza a saltos de un segmento.
                self.body.append(f"u4f g_RenderVar0 {cinta[1]} 0 1 {cinta[1]}")
            elif estela:
                # length, maxlength, minlength: ver `weparticles._estela`. El
                # cuarto no lo lee nadie.
                self.body.append("u4f g_RenderVar0 "
                                 + " ".join(f"{v:.6g}" for v in estela) + " 0")
            else:
                self.body.append("u4f g_RenderVar0 1 1 1 1")
        elif luz:
            self.body.append("u3f g_EyePosition "
                             f"{canvas[0] / 2:.6g} {canvas[1] / 2:.6g} {OJO_Z:.6g}")
            _malla = (p.stage == "base" and mesh_id is not None)
            mundo = object_world(obj, canvas, mesh=_malla, por_id=self.por_id)
            self.body.append("umat4 g_ModelMatrix " + " ".join(f"{x:.6g}" for x in mundo))
            self.body.append("umat4 g_ViewProjectionMatrix " + " ".join(
                f"{x:.6g}" for x in vp_de(mvp, mundo)))
            _, _, _, _, _c, _s, _ = _colocacion(obj, canvas, _malla, self.por_id)
            self.body.append("umat3 g_NormalModelMatrix " + " ".join(
                f"{x:.6g}" for x in matriz_normales(_c, _s)))

        if luz:
            # Las arrays se mandan elemento a elemento: GL sabe resolver
            # `g_LightsPosition[2]` como nombre, asi que no hace falta que el
            # plan ni el ejecutor aprendan lo que es un array.
            self.body.append("u3f g_LightAmbientColor "
                             + " ".join(f"{x:.6g}" for x in self.ambiente))
            self.body.append("u3f g_LightSkylightColor "
                             + " ".join(f"{x:.6g}" for x in self.cielo))
            for i in range(MAX_LUCES):
                if i < len(self.luces):
                    org, col, radio, expo = self.luces[i]
                else:
                    # Un hueco vacio no se puede dejar sin escribir: GL daria
                    # cero tambien en el radio, y el decaimiento divide por el.
                    org, col, radio, expo = ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                                             1.0, EXPONENTE_POR_DEFECTO)
                self.body.append(f"u3f g_LightsPosition[{i}] "
                                 + " ".join(f"{x:.6g}" for x in org))
                self.body.append(f"u4f g_LightsColorRadius[{i}] "
                                 + " ".join(f"{x:.6g}" for x in col)
                                 + f" {radio:.6g}")
                self.body.append(f"u1f g_LightsExponent[{i}] {expo:.6g}")
            # La otra forma de mandar los mismos colores. No es alternativa a
            # la de arriba: cada generacion de shaders lee una, y un pase puede
            # necesitar las dos ---el vertice saca las direcciones de
            # `g_LightsPosition` y el fragmento el color de aqui.
            for i, v in enumerate(colores_premultiplicados(self.luces)):
                self.body.append(f"u4f g_LightsColorPremultiplied[{i}] "
                                 + " ".join(f"{x:.6g}" for x in v))
        self.body.append("u1f g_Time @TIME@")
        self.body.append(f"u3f g_Screen {canvas[0]} {canvas[1]} "
                         f"{canvas[0] / max(1, canvas[1])}")
        # La proyeccion de la textura del efecto y la posicion del parallax.
        # No es adorno: `depthparallax` saca de la matriz inversa los dos ejes
        # proyectados y los NORMALIZA. Sin emitirla GL la da a cero, los ejes
        # salen (0,0), `normalize` hace 0/0 y el NaN viaja por `v_ParallaxOffset`
        # hasta las coordenadas de muestreo: la escena entera sale NEGRA. Es la
        # misma familia que el NaN de `g_TexelSize`, y le pasa a `3077334064`
        # ---un 4K de 11 pases que se preparaba sin una sola queja--- que asi
        # pasa de luminancia media 18 a 91.
        #
        # La escena es plana y mira al lienzo de frente, asi que la identidad es
        # el valor neutro, igual que con `g_Orientation*`. La posicion del
        # parallax va al centro, que es el reposo mientras el motor no sepa
        # donde esta el puntero; cuando lo sepa, se engancha aqui.
        ident = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
        self.body.append(f"umat4 g_EffectTextureProjectionMatrix {ident}")
        self.body.append(f"umat4 g_EffectTextureProjectionMatrixInverse {ident}")
        self.body.append("u2f g_ParallaxPosition 0.5 0.5")
        # El puntero, en UV y en reposo. NO se puede dejar sin emitir: cero no
        # es "sin cursor", es el cursor clavado en la esquina superior
        # izquierda, y 14 variantes del corpus lo leen. El centro es lo mismo
        # que ya asume `g_ParallaxPosition`, y lo que se vera hasta que el
        # motor sepa donde esta el raton de verdad.
        self.body.append("u2f g_PointerPosition 0.5 0.5")
        self.body.append("u2f g_PointerPositionLast 0.5 0.5")
        # La inversa de la MVP lleva el puntero de clip space al espacio local
        # de la capa. Sin emitirla GL la da a cero y ahi dentro hay una
        # division: es la misma familia de fallo que dejo tres escenas negras
        # con `g_EffectTextureProjectionMatrixInverse`.
        self.body.append("umat4 g_ModelViewProjectionMatrixInverse "
                         + " ".join(f"{x:.6g}" for x in inversa_de(mvp)))
        if obj is not None:
            # Donde cae este fragmento en la PANTALLA, que no es donde cae en
            # el buffer de la capa: los pases de efecto dibujan un quad a
            # pantalla completa sobre su propio buffer, asi que su MVP es la
            # identidad y no sirve para situarse en la escena.
            self.body.append("umat4 g_EffectModelViewProjectionMatrix " + " ".join(
                f"{x:.6g}" for x in object_mvp(obj, canvas, por_id=self.por_id)))
            # De esta solo se leen las LONGITUDES de sus dos primeros ejes, y
            # lo que se espera ahi es el factor de escala de la capa ---1 cuando
            # no esta escalada---, porque multiplica una resolucion. Va sin
            # rotacion a proposito: con nuestra convencion de escribir las
            # matrices por filas, `m[0]` en GLSL no es el eje sino la fila, y
            # mezclar el giro daria una longitud que no es la escala. Nadie la
            # multiplica, solo la mide.
            _, _esc, _ = transform_absoluto(obj, self.por_id)
            self.body.append(f"umat4 g_LayerModelMatrix {_esc[0]:.6g} 0 0 0 "
                             f"0 {_esc[1]:.6g} 0 0  0 0 {_esc[2]:.6g} 0  0 0 0 1")
        # Tamano de un texel del buffer al que escribe ESTE pase. Es lo que
        # usan los shaders de desenfoque para saber cuanto vale un paso:
        #
        #   ratio = g_TexelSize * g_Texture0Resolution.xy   -> (1, 1)
        #   v_PixelSize = 2 * g_TexelSize * vec2(ratio.y / ratio.x, ...)
        #
        # Sin emitirlo, GL lo da a cero y ese cociente es 0/0. El resultado es
        # NaN, y de ahi en adelante manda el driver: NVIDIA lo absorbia y Mesa
        # -- el del escritorio -- lo propagaba, asi que 3146507587 se veia bien
        # en el render offline y se desvanecia a negro en vivo. La misma escena,
        # renderizada offline forzando Mesa, se desvanecia igual.
        tw, th = rt_size(p.target, canvas) if p.target else canvas
        self.body.append(f"u2f g_TexelSize {1.0 / max(1, tw):.9g} "
                         f"{1.0 / max(1, th):.9g}")
        self.body.append("u4f g_Texture0Rotation 1 0 0 1")
        self.body.append("u2f g_Texture0Translation 0 0")
        # Alfa, brillo y color son del OBJETO, no del material: una capa puede
        # declararse a media opacidad o tenida. Estaban fijos a neutro, asi que
        # se dibujaban a plena intensidad. En el corpus hay 133 objetos con
        # color no blanco, 68 con brillo distinto de 1 y 67 con alfa distinto
        # de 1; el mas visible es la suciedad de lente de Asuka, con alfa 0.45,
        # que tapaba la escena entera.
        #
        # Solo en el pase base: los de efecto trabajan sobre el buffer ya
        # dibujado, y algunos declaran su propio g_Alpha -- aplicarlo dos veces
        # oscureceria la capa a cada efecto.
        if obj is not None and p.stage == "base":
            col = (_floats(obj.raw.get("color")) + [1.0, 1.0, 1.0])[:3]
            # Por _floats, que ademas de numero y cadena entiende el objeto
            # con `value` de los campos animados por script.
            alfa = (_floats(obj.raw.get("alpha")) + [1.0])[0]
            brillo = (_floats(obj.raw.get("brightness")) + [1.0])[0]
        else:
            col, alfa, brillo = [1.0, 1.0, 1.0], 1.0, 1.0
        # La opacidad del objeto viaja por TRES sitios distintos porque cada
        # generacion de shaders la lee de uno, y son ramas excluyentes del
        # mismo fichero: `genericimage2` aplica `g_Color4` entero (rgb Y alfa)
        # si esta definido VERSION, y si no `g_Brightness` sobre el rgb y
        # `g_UserAlpha` sobre el alfa. Mandarla solo en `g_Alpha` --- que es lo
        # que se hacia --- la perdia en las dos: ese nombre lo usan otros seis
        # shaders, ninguno de estos.
        #
        # No se aplica dos veces: en toda la libreria no hay un shader que lea
        # dos de los tres. Comprobado sobre los .frag de `assets/shaders`.
        #
        # Costo de no tenerlo: la sombra del disco de vinilo de 3624164256 es
        # negra con `alpha: 0.1`, y salia OPACA --- un lunar negro en mitad del
        # personaje.
        self.body.extend(uniforms_de_tinte(col, alfa, brillo))

        # Constantes del material, resueltas via metadatos.
        for uni_name, m in meta.items():
            key = m.get("material")
            value = p.constants.get(key) if key else None
            if value is None:
                value = m.get("default")
            vals = _floats(value)
            if not vals or len(vals) > 4:
                continue
            self.body.append(
                f"u{len(vals)}f {uni_name} " + " ".join(f"{v:.6g}" for v in vals))

        self.body.append("endpass")
        if self.dump_dir is not None:
            self.body.append(f"dump {self.dump_dir}/after{n:03d}.rgba")
        self.stats["pases"] += 1

    # ── escena completa ───────────────────────────────────────────────────
    def render_sequence(self, out_dir: Path, count: int, fps: float,
                        warmup: int = 6) -> dict:
        """Renderiza `count` fotogramas consecutivos avanzando g_Time.

        Los fotogramas de calentamiento no se guardan: sirven para que los
        efectos temporales (motion blur) llenen su buffer de historia. Sin
        ellos los primeros fotogramas salen oscurecidos.
        """
        self._build(None)
        out_dir.mkdir(parents=True, exist_ok=True)
        w, h = self.stats["canvas"]

        plan = list(self.lines)
        for i in range(warmup):
            plan.extend(l.replace("@TIME@", f"{self.time + i / fps:.5f}")
                        for l in self.body)
        for i in range(count):
            t = self.time + (warmup + i) / fps
            plan.extend(l.replace("@TIME@", f"{t:.5f}") for l in self.body)
            plan.append(f"dump {out_dir}/f{i:04d}.rgba")

        plan_path = self.tmp / "plan_seq.txt"
        plan_path.write_text("\n".join(plan) + "\n")
        r = subprocess.run([str(self.exec_path), str(plan_path)],
                           capture_output=True, text=True)
        self.stats["glexec"] = r.stdout.strip()
        self.stats["fotogramas"] = count
        if r.returncode != 0:
            self.stats["error"] = r.stderr[-2000:]
        return self.stats

    def _build(self, max_passes: int | None,
               only_base: bool = False) -> tuple[int, int]:
        scene = load_scene(self.res)
        general = scene.general
        proj = general.get("orthogonalprojection")
        # El tamano puede venir como numero o como cadena, y hasta como campo
        # animado por script; `_floats` entiende las tres formas.
        canvas = ((int(_floats(proj.get("width", 1920))[0]),
                   int(_floats(proj.get("height", 1080))[0]))
                  if isinstance(proj, dict) else (1920, 1080))
        self.canvas = canvas
        self.luces = luces_de_escena(scene)
        # `ambientcolor` es la luz que llega a todo por igual y `skylightcolor`
        # la que viene de abajo; el vertice mezcla las dos segun a donde mire la
        # normal. Sin ninguna de las dos declaradas se usa blanco, que deja la
        # capa como esta hoy en vez de apagarla.
        amb = (_floats(general.get("ambientcolor")) + [1.0, 1.0, 1.0])[:3]
        self.ambiente = amb
        self.cielo = (_floats(general.get("skylightcolor")) + amb)[:3]
        self.lines.append(f"canvas {canvas[0]} {canvas[1]}")
        # Instante al que deformar las mallas. Solo lo usa glexec, que no
        # tiene reloj propio: el motor en vivo pasa su tiempo real.
        self.lines.append(f"meshtime {self.time:.6f}")
        we = wepaths.we_assets()
        sresolver = weshader.Resolver(
            overlay=self.res.entries, roots=[we, we / "shaders"])
        por_id = {str(o.raw.get("id")): o for o in scene.objects}
        # Lo necesita `emit_pass` para colocar las particulas, que se resuelven
        # pase a pase y no en este bucle.
        self.por_id = por_id
        self.buffers_de = _buffers_de_composicion(scene)
        # Las capas que solo llenan un buffer se dibujan ANTES que nadie: asi
        # el buffer esta listo cuando la composicion lo muestrea, sin depender
        # de que el autor las haya puesto en orden dentro de la escena.
        orden = ([o for o in scene.objects if getattr(o, "solo_buffer", False)]
                 + [o for o in scene.objects if not getattr(o, "solo_buffer", False)])
        for obj in orden:
            if obj.kind not in ("image", "particle") or not obj.passes:
                continue
            if obj.kind == "particle":
                self._emit_psys(obj)
                # Sin sistema simulable no hay geometria: el pase se quedaria
                # sin `psys` y dibujaria el quad a pantalla completa con la
                # textura de la particula estirada por todo el lienzo.
                if id(obj) not in self.psys:
                    continue
            self._emit_mesh(obj)
            # Marca de inicio de objeto. El ejecutor la usa para componer el
            # objeto anterior sobre la escena en vez de pisarlo. `copybackground`
            # dice si este objeto arranca desde una copia de lo que hay detras
            # (lo que necesitan las capas de post-proceso) o desde vacio.
            copybg = 1 if obj.raw.get("copybackground") else 0
            if obj.kind == "particle":
                # Las particulas ya se dibujan en coordenadas del lienzo: su
                # matriz lleva del espacio del sistema al lienzo entero, asi que
                # componer su buffer es una copia 1:1.
                mvp_obj = list(IDENTITY)
            else:
                mvp_obj = object_mvp(obj, canvas, por_id=por_id)
            mg = self.margins.get(id(obj), 1.0)
            if mg != 1.0:
                for i in (0, 1, 4, 5):     # la parte lineal 2x2
                    mvp_obj[i] *= mg
            place = " ".join(f"{x:.6g}" for x in mvp_obj)
            # `colorBlendMode` del objeto: como se combina la capa con lo que
            # hay detras. Va aqui y no en el pase base porque el pase base
            # dibuja sobre el buffer VACIO del objeto -- la mezcla con la
            # escena ocurre al componer, que es esto.
            #
            # El 31, 44 de los 91 usos del corpus, es `A + B*opacity`: aditivo
            # puro, exactamente glBlendFunc(GL_SRC_ALPHA, GL_ONE). Sin el, la
            # suciedad de lente de Asuka -- bokeh claro sobre negro -- tapaba
            # la escena entera en vez de solo aportar sus brillos.
            #
            # Los demas modos son mezclas tipo Photoshop (multiply, darken...)
            # sin equivalente en el hardware; se componen como siempre.
            aditivo = 1 if obj.raw.get("colorBlendMode") == 31 else 0
            if obj.kind == "particle":
                # El buffer de un sistema de particulas ya viene premultiplicado
                # por el alfa de cada sprite; componerlo multiplicando otra vez
                # apagaria justo los halos, que es donde vive casi todo el
                # brillo de una particula.
                aditivo = 3 if obj.passes[0].blending == "additive" else 2
            # Una capa que solo llena su buffer de composicion no se compone
            # sobre la escena: otra la muestreara por nombre.
            solo = 1 if getattr(obj, "solo_buffer", False) else 0
            self.body.append(f"object {copybg} {place} {aditivo} {solo}")
            buffers = self.buffers_de.get(str(obj.raw.get("id")), ())
            for p in obj.passes:
                if p.command == "copy":
                    src = "prev" if not p.source or COMPOSITE_RT_RE.match(p.source) \
                        else p.source
                    dst = "prev" if not p.target or COMPOSITE_RT_RE.match(p.target) \
                        else p.target
                    self.body.append(f"copy {src} {dst}")
                    continue
                if p.command:
                    continue
                if only_base and p.stage != "base":
                    continue
                if max_passes is not None and self.stats["pases"] >= max_passes:
                    break
                self.emit_pass(p, sresolver, canvas, obj)
            # Ya dibujado el objeto entero, su compuesto se vuelca a los
            # buffers con nombre que otra capa va a muestrear.
            for nombre in buffers:
                self.body.append(f"copy prev {nombre}")
        self.stats["canvas"] = canvas
        return canvas

    def render(self, out_png: Path, only_base: bool = False,
               max_passes: int | None = None, frames: int = 1) -> dict:
        # Mismo armado que `render_sequence`: un unico sitio decide como se
        # recorre la escena. Tenerlo duplicado costo que las particulas
        # funcionaran por un camino y no por el otro.
        canvas = self._build(max_passes, only_base)

        raw = self.tmp / "out.rgba"

        # Los efectos temporales (motion blur) acumulan entre fotogramas: en
        # una sola pasada su buffer de historia esta vacio por definicion y el
        # resultado sale oscurecido. Repetir el plan deja que converjan, que es
        # lo que pasa en ejecucion real. Los render targets se crean una vez y
        # persisten entre repeticiones, asi que basta con repetir los pases.
        #
        # Cada repeticion abre con `frame`, que cierra el objeto pendiente y
        # limpia la escena igual que el motor en vivo. Sin eso la escena
        # acumulaba una composicion por repeticion y salia mas brillante
        # cuantas mas se pedian, que es lo contrario de lo que se quiere
        # observar: escondio durante toda una sesion que 3146507587 salia
        # negra. (Aquella escena ya esta arreglada --- era un sampler sin
        # enlazar, ver NOTAS --- y hoy converge hacia arriba, de 10.88 con un
        # fotograma a 21.20 con doce. La leccion sobre `frame` sigue valiendo:
        # sin el, lo que se mide es la acumulacion, no la escena.)
        plan_lines = list(self.lines)
        for i in range(max(1, frames)):
            plan_lines.append("frame")
            plan_lines.extend(l.replace("@TIME@", f"{self.time:.5f}")
                              for l in self.body)
        plan_lines.append(f"output {raw}")
        self.stats["fotogramas"] = max(1, frames)

        plan = self.tmp / "plan.txt"
        plan.write_text("\n".join(plan_lines) + "\n")

        r = subprocess.run([str(self.exec_path), str(plan)],
                           capture_output=True, text=True)
        self.stats["glexec"] = r.stdout.strip()
        if r.returncode != 0 or not raw.is_file():
            self.stats["error"] = r.stderr[-2000:]
            return self.stats

        px = np.frombuffer(raw.read_bytes(), dtype=np.uint8)
        px = px.reshape(canvas[1], canvas[0], 4)[::-1]   # deshacer el volteo
        Image.fromarray(px, "RGBA").save(out_png)
        self.stats["salida"] = str(out_png)
        self.stats["canvas"] = canvas
        self.stats["log"] = r.stderr[-1500:] if r.stderr else ""
        return self.stats


def emit_plan(wallpaper: Path, out_dir: Path,
              ruta_final: Path | None = None) -> dict:
    """Escribe el plan como plantilla, con @TIME@ sin sustituir.

    Es la interfaz con el motor en C++: Python resuelve el grafo, traduce los
    shaders y decodifica las texturas una vez; el ejecutor de C++ repite ese
    mismo plan cada fotograma poniendo el tiempo que toque. Los assets se
    copian junto al plan para que no dependa de un directorio temporal.

    El plan nombra sus assets por ruta ABSOLUTA, asi que quien lo genere en un
    sitio para moverlo a otro ---`wectl.preparar`, que lo escribe aparte y lo
    cambia por un rename para no dejar el escritorio a medias--- tiene que decir
    en `ruta_final` donde van a acabar. Sin eso el plan sale apuntando al
    directorio de trabajo y el motor no encuentra ni una textura en cuanto se
    mueve.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    destino = ruta_final if ruta_final is not None else out_dir
    r = Renderer(wallpaper, Path("/nonexistent"), 0.0)
    canvas = r._build(None)

    remap: dict[str, str] = {}
    for src in sorted(r.tmp.iterdir()):
        if src.suffix in (".rgba", ".vert", ".frag", ".bin", ".psys"):
            dst = out_dir / src.name
            dst.write_bytes(src.read_bytes())
            remap[str(src)] = str(destino / src.name)

    def fix(line: str) -> str:
        for a, b in remap.items():
            line = line.replace(a, b)
        return line

    # El titulo viaja en el plan para que el HUD no tenga que llevarlo escrito
    # a mano (y mentir cuando se cambia de wallpaper).
    title = wallpaper.name
    pj = wallpaper / "project.json"
    if pj.is_file():
        try:
            title = json.loads(pj.read_text(errors="replace")).get("title", title)
        except Exception:
            pass
    header = [f"title {title} ({wallpaper.name})"]
    plan = header + [fix(l) for l in r.lines] + [fix(l) for l in r.body]
    (out_dir / "plan.txt").write_text("\n".join(plan) + "\n")
    # Los assets ya estan copiados en `out_dir`: lo que queda en el temporal es
    # basura, ~60 MB por escena. `render()` lo borra en su `finally` y esto no
    # lo hacia: generar el plan de las 125 escenas seguidas dejaba 7 GB en /tmp,
    # que es un tmpfs, y lo llenaba a media pasada.
    shutil.rmtree(r.tmp, ignore_errors=True)
    return {"pases": r.stats["pases"], "canvas": canvas,
            "assets": len(remap), "plan": str(destino / "plan.txt")}


def main() -> int:
    if "--emit-plan" in sys.argv:
        i = sys.argv.index("--emit-plan")
        for k, v in emit_plan(Path(sys.argv[1]), Path(sys.argv[i + 1])).items():
            print(f"  {k}: {v}")
        return 0
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    wallpaper = Path(sys.argv[1])
    out = Path(sys.argv[2])
    # Donde lo deja `make glexec`. Antes apuntaba a /tmp/glexec, que no lo
    # escribe nadie: quedaba el binario de la ultima vez que alguien lo copio a
    # mano, y un plan nuevo contra un ejecutor viejo no falla --- se salta en
    # silencio lo que no entiende. Con el uniform de la matriz de normales sin
    # subir, el fondo de dos escenas salia negro y no habia nada que lo dijera.
    exec_path = Path("obj/glexec")
    if "--exec" in sys.argv:
        exec_path = Path(sys.argv[sys.argv.index("--exec") + 1])
    t = 0.0
    if "--time" in sys.argv:
        t = float(sys.argv[sys.argv.index("--time") + 1])

    r = Renderer(wallpaper, exec_path, t)
    mp = None
    if "--passes" in sys.argv:
        mp = int(sys.argv[sys.argv.index("--passes") + 1])
    frames = 1
    if "--frames" in sys.argv:
        frames = int(sys.argv[sys.argv.index("--frames") + 1])
    try:
        stats = r.render(out, only_base="--only-base" in sys.argv, max_passes=mp,
                         frames=frames)
    finally:
        # Cada render deja ~200 MB de texturas RGBA decodificadas; sin esto
        # una sesion de depuracion llena /tmp. `--keep` lo conserva para
        # inspeccionar el plan y los shaders generados.
        if "--keep" in sys.argv:
            print(f"  temporales: {r.tmp}")
        else:
            shutil.rmtree(r.tmp, ignore_errors=True)
    for k, v in stats.items():
        if k == "log" and v:
            print(f"  log del compilador (cola):\n{v}")
        else:
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
