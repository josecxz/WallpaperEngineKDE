#!/usr/bin/env python3
"""Comprueba las matrices y las luces que el plan le pasa a un pase iluminado.

Con la iluminacion encendida el shader deja de conformarse con la MVP: quiere
saber donde cae cada fragmento en el mundo, hacia donde mira, y donde estan las
luces. Son cuatro matrices y dos arrays que antes no se emitian, y ninguna de
las dos formas de equivocarse avisa.

  * Si la geometria no acaba donde acababa antes, la capa se mueve o
    desaparece sin un solo error. Paso: al no emitir `g_ViewProjectionMatrix`
    ---que solo se usa por este camino--- GL la daba a cero, el quad colapsaba
    a un punto y la escena entera salia negra.
  * Si la matriz de normales no conserva longitudes, lo que se rompe no es la
    normal sino la DISTANCIA a la luz, porque el shader expresa esa direccion
    en la base que arma con ella. Paso: con la inversa de la escala, la
    distancia salia dividida por dos mil y el fondo se iba a blanco puro.

Asi que aqui se comprueban las dos propiedades que tienen que cumplirse, no los
numeros concretos: que `VP * Mundo` reproduce la MVP de siempre, y que la
matriz de normales es ortonormal.

Con el tiempo se le han sumado los otros dos uniforms que nadie leia, por la
misma razon ---fallan callando---:

  * El `default` de un sampler que el material no enlaza. Sin ponerlo, el
    sampler se queda en la unidad 0 y el shader usa la propia imagen como si
    fuera el otro mapa.
  * La opacidad del objeto, que cada generacion de shaders lee de un nombre
    distinto. Iba solo a `g_Alpha`, que no lo lee ninguno de los de imagen.

Uso:
    python3 tools/test_werender.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import werender
import wescene

CANVAS = (3840, 2160)


def _objeto(**campos) -> wescene.SceneObject:
    raw = {"id": 1, "image": "x.tex"}
    raw.update(campos)
    return wescene.SceneObject(id=1, name="prueba", kind="image", raw=raw)


def _luz(**campos) -> wescene.SceneObject:
    raw = {"id": 2, "light": "point", "color": "1 1 1",
           "intensity": 1.0, "radius": 100.0, "origin": "10 20 30"}
    raw.update(campos)
    return wescene.SceneObject(id=2, name="luz", kind="light", raw=raw)


def _escena(objetos, general=None) -> wescene.Scene:
    return wescene.Scene(general=general or {}, camera={}, objects=objetos)


def prueba_vp_reconstruye_la_mvp(fallos: list[str]) -> None:
    """`VP * Mundo` tiene que dar la MVP que se usaba antes de haber luces.

    Es la garantia de que encender la iluminacion no mueve nada de sitio: el
    vertice cambia de camino ---pasa por el mundo en vez de ir directo--- y
    tiene que llegar al mismo pixel.
    """
    casos = [
        ("capa centrada", _objeto(origin="1920 1080 0", size="3840 2160"), False),
        ("capa pequena y girada", _objeto(origin="700 300 0", size="512 256",
                                          angles="0 0 0.6"), False),
        ("capa escalada", _objeto(origin="1000 900 0", size="800 600",
                                  scale="1.5 0.5 1"), False),
        ("malla puppet", _objeto(origin="1500 700 0", size="600 400",
                                 scale="2 2 1"), True),
    ]
    for nombre, obj, malla in casos:
        mvp = werender.object_mvp(obj, CANVAS, mesh=malla)
        mundo = werender.object_world(obj, CANVAS, mesh=malla)
        vp = werender.vp_de(mvp, mundo)
        compuesta = (np.array(vp).reshape(4, 4) @ np.array(mundo).reshape(4, 4)).ravel()
        if not np.allclose(compuesta, np.array(mvp), atol=1e-9):
            fallos.append(f"{nombre}: VP * Mundo no reproduce la MVP")

    # Las particulas van por otra matriz: su espacio local son pixeles del
    # sistema, no el quad. La propiedad tiene que valer igual.
    p = _objeto(origin="900 400 0", scale="0.5 0.25 1", particle="p.json")
    mvp = werender.particle_mvp(p, CANVAS)
    mundo = werender.particle_world(p, CANVAS)
    compuesta = (np.array(werender.vp_de(mvp, mundo)).reshape(4, 4)
                 @ np.array(mundo).reshape(4, 4)).ravel()
    if not np.allclose(compuesta, np.array(mvp), atol=1e-9):
        fallos.append("particulas: VP * Mundo no reproduce la MVP")


def prueba_normales_ortonormal(fallos: list[str]) -> None:
    """La matriz de normales conserva longitudes y deja quieta una capa plana."""
    for ang in (0.0, 0.7, -2.1, math.pi):
        m = np.array(werender.matriz_normales(math.cos(ang), math.sin(ang))).reshape(3, 3)
        if not np.allclose(m @ m.T, np.eye(3), atol=1e-9):
            fallos.append(f"la matriz de normales no es ortonormal en {ang:.2f} rad")
        # La normal de una capa es (0, 0, 1) por construccion: girar la capa en
        # su plano no la inclina.
        if not np.allclose(m @ np.array([0.0, 0.0, 1.0]), [0.0, 0.0, 1.0], atol=1e-9):
            fallos.append(f"la matriz de normales mueve la normal en {ang:.2f} rad")


def prueba_luces(fallos: list[str]) -> None:
    sc = _escena([_luz(color="1 0.5 0.25", intensity=2.0, radius=300.0,
                       origin="100 200 300")])
    luces = werender.luces_de_escena(sc)
    if len(luces) != 1:
        fallos.append("no se leyo la luz puntual")
    else:
        lz = luces[0]
        if lz.tipo != "point":
            fallos.append(f"clase mal leida: {lz.tipo}")
        if lz.origen != [100.0, 200.0, 300.0]:
            fallos.append(f"origen mal leido: {lz.origen}")
        # El shader recibe un solo color: la intensidad va dentro.
        if not np.allclose(lz.color, [2.0, 1.0, 0.5]):
            fallos.append(f"la intensidad no se aplico al color: {lz.color}")
        if lz.radio != 300.0:
            fallos.append(f"radio mal leido: {lz.radio}")

    # Una luz apagada por el autor no cuenta, y no invalida la escena.
    sc = _escena([_luz(visible=False), _luz()])
    if len(werender.luces_de_escena(sc)) != 1:
        fallos.append("una luz invisible no deberia contar")

    # El tubo es un SEGMENTO y la escena dice cual: `controlpoint` es el otro
    # extremo, relativo al origen. Antes se descartaba la escena entera por no
    # saber ponerlo. Ver 3053927686.
    sc = _escena([_luz(light="ltube", origin="100 200 300",
                       controlpoint="50 0 0")])
    luces = werender.luces_de_escena(sc)
    if len(luces) != 1 or luces[0].tipo != "tube":
        fallos.append("no se leyo la luz de tubo")
    elif luces[0].extremo != [150.0, 200.0, 300.0]:
        fallos.append(f"el extremo del tubo mal puesto: {luces[0].extremo}")

    # Sin `controlpoint` el tubo degenera en punto, que es el caso que
    # `PointSegmentDelta` ya trata: los dos extremos coinciden.
    sc = _escena([_luz(light="ltube", origin="100 200 300")])
    luces = werender.luces_de_escena(sc)
    if luces and luces[0].extremo != luces[0].origen:
        fallos.append(f"un tubo sin controlpoint no es un punto: {luces[0]}")

    # Un foco si sigue sin ponerse: el shader lo declara, pero su orientacion
    # sale de `angles` y no hay ninguno en la biblioteca con el que verificarlo.
    sc = _escena([_luz(light="lspot"), _luz()])
    clases = set(werender.por_tipo(werender.luces_de_escena(sc)))
    if not (clases - set(werender.CLASES_DE_LUZ)):
        fallos.append("un foco deberia quedar fuera de las clases que ponemos")


def prueba_empaquetado(fallos: list[str]) -> None:
    """La cuarta luz viaja en los `.w` de las otras tres, no en un cuarto vec4."""
    luces = [werender.Luz("point", [0, 0, 0], [float(i + 1)] * 3, 1.0,
                          [0, 0, 0]) for i in range(4)]
    v = werender.colores_premultiplicados(luces)
    if len(v) != 3:
        fallos.append(f"el empaquetado deberia dar 3 vec4, dio {len(v)}")
        return
    for i in range(3):
        if not np.allclose(v[i][:3], [i + 1.0] * 3):
            fallos.append(f"la luz {i} no esta en el rgb del elemento {i}")
    if not np.allclose([v[0][3], v[1][3], v[2][3]], [4.0, 4.0, 4.0]):
        fallos.append("la cuarta luz no esta repartida en los .w")

    # El radio entra al cuadrado: es lo unico que lleva el alcance por este
    # camino, donde el shader solo divide por la distancia al cuadrado.
    v = werender.colores_premultiplicados(
        [werender.Luz("point", [0, 0, 0], [1.0, 1.0, 1.0], 10.0, [0, 0, 0])])
    if not np.allclose(v[0][:3], [100.0, 100.0, 100.0]):
        fallos.append(f"el color no se premultiplico por el radio^2: {v[0][:3]}")


def prueba_sampler_por_defecto(fallos: list[str]) -> None:
    """El shader dice con que rellenar un sampler que el material no enlaza.

    Hay que hacerle caso porque un sampler sin enlazar NO lee negro: se queda
    en la unidad 0 ---la del slot 0--- y el shader acaba usando la propia
    imagen como si fuera el otro mapa. Asi desaparecia la capa entera de
    3624164256, cuyo parallax declara `g_Texture1` con `default: util/black`.
    """
    for meta, espera, por_que in (
            ({"default": "util/black"}, "util/black", "el mapa de profundidad sin pintar"),
            ({"default": "util/white"}, "util/white", "el albedo que no viene"),
            ({"default": "gradient/gradient_toon_smooth"},
             "gradient/gradient_toon_smooth", "un gradiente de la libreria"),
            ({"default": "_rt_FullFrameBuffer"}, "", "buffer del motor, no fichero"),
            ({"default": "_alias_lightCookie"}, "", "subsistema que no tenemos"),
            ({"label": "sin default"}, "", "el shader no dice nada"),
            (None, "", "el shader ni declara el sampler")):
        da = werender.textura_por_defecto(meta)
        if da != espera:
            fallos.append(f"textura_por_defecto({meta}) dio {da!r}, "
                          f"se esperaba {espera!r} ({por_que})")


def prueba_valor_de_usuario(fallos: list[str]) -> None:
    """Un campo atado a una propiedad vale lo que la propiedad, no su copia.

    `{"user": "neon", "value": "1 0 0"}` con `neon` en `0 1 1` vale CIAN. La
    copia es del instante en que el autor guardo. Leerla dejaba la Miku de
    1518454472 roja donde su preview es cian.
    """
    props = {"neon": {"type": "color", "value": "0 1 1"},
             "apagado": {"type": "bool", "value": False}}
    datos = {"objects": [{"color": {"user": "neon", "value": "1 0 0"},
                          "passes": [{"constantshadervalues": {
                              "c": {"user": "apagado", "value": True},
                              "suelto": {"user": "no_existe", "value": "9 9 9"},
                              "raro": {"user": {"anidado": 1}, "value": "7 7 7"}}}]}]}
    wescene._refrescar_valores_de_usuario(datos, props)
    o = datos["objects"][0]
    if o["color"]["value"] != "0 1 1":
        fallos.append(f"el color no se refresco: {o['color']}")
    cs = o["passes"][0]["constantshadervalues"]
    if cs["c"]["value"] is not False:
        fallos.append(f"la constante no se refresco: {cs['c']}")
    # Lo que no nombra una propiedad conocida se queda como estaba: es lo que
    # el autor tenia en pantalla, y `user` no siempre es un nombre.
    if cs["suelto"]["value"] != "9 9 9" or cs["raro"]["value"] != "7 7 7":
        fallos.append(f"se toco lo que no habia que tocar: {cs}")


def prueba_curva_de_animacion(fallos: list[str]) -> None:
    """El valor de una curva de fotogramas clave en un instante dado.

    El caso que importa es el telon de entrada de 3577990983: una capa negra
    cuyo `alpha` va de 1 a 0 en 90 fotogramas y que WE guardo en 1. Sin
    evaluar la curva se queda opaca para siempre y tapa el wallpaper.
    """
    telon = {"options": {"fps": 30, "length": 90, "mode": "single"},
             "c0": [{"frame": 0, "value": 1}, {"frame": 60, "value": 1},
                    {"frame": 90, "value": 0}]}
    for t, espera, por_que in ((0.0, 1.0, "en el arranque, opaco"),
                               (2.0, 1.0, "aun no empieza a irse"),
                               (2.5, 0.5, "a mitad del fundido"),
                               (3.0, 0.0, "justo al acabar"),
                               (60.0, 0.0, "un minuto despues sigue apagado")):
        v = wescene._valor_animado(telon, t)
        if v is None or abs(v[0] - espera) > 1e-6:
            fallos.append(f"telon en t={t}: {v} en vez de {espera} ({por_que})")

    # `loop` vuelve a empezar; `mirror` va y vuelve. Un plan estatico los
    # congela, pero en el instante que toca.
    for modo, casos in (("loop", ((0.0, 0.0), (0.5, 15.0), (1.0, 0.0))),
                        ("mirror", ((0.0, 0.0), (1.0, 30.0), (1.5, 15.0)))):
        curva = {"options": {"fps": 30, "length": 30, "mode": modo},
                 "c0": [{"frame": 0, "value": 0}, {"frame": 30, "value": 30}]}
        for t, espera in casos:
            v = wescene._valor_animado(curva, t)
            if v is None or abs(v[0] - espera) > 1e-6:
                fallos.append(f"{modo} en t={t}: {v} en vez de {espera}")

    # Un vector anima un canal por componente.
    tres = {"options": {"fps": 30, "length": 30, "mode": "single"},
            "c0": [{"frame": 0, "value": 0}, {"frame": 30, "value": 3}],
            "c1": [{"frame": 0, "value": 10}, {"frame": 30, "value": 20}],
            "c2": [{"frame": 0, "value": 5}, {"frame": 30, "value": 5}]}
    v = wescene._valor_animado(tres, 0.5)
    if v is None or [round(x, 4) for x in v] != [1.5, 15.0, 5.0]:
        fallos.append(f"tres canales dieron {v}")

    # Una curva que no se entiende no puede reventar el render.
    if wescene._valor_animado({"options": {}, "c0": []}, 1.0) is not None:
        fallos.append("una curva vacia deberia dar None")


def prueba_mezcla_de_objeto(fallos: list[str]) -> None:
    """`colorBlendMode` decide como se compone la capa sobre la escena.

    Solo se traducen los modos cuyo elemento neutro es el NEGRO, que es con lo
    que arranca el buffer del objeto: si no, la capa pintaria tambien donde es
    transparente. `multiply` y `darken` los sabe hacer el hardware y aun asi
    quedan fuera por eso.

    Costo de no tenerlo: la capa `ripple1440p` de Lonely Cat es negra y opaca
    de verdad ---RGB 3.8, alfa 255--- y con modo `add` no aporta nada;
    componiendola con alfa normal pintaba un rectangulo negro sobre la escena.
    """
    for modo, espera, por_que in ((31, 1, "el aditivo de WE"),
                                  (9, 1, "add: el hardware satura igual"),
                                  (7, 4, "screen"),
                                  (6, 5, "lighten es un max"),
                                  (10, 5, "max, lo mismo que lighten"),
                                  (0, 0, "normal"),
                                  (2, 0, "multiply apagaria fuera de la capa"),
                                  (1, 0, "darken es un min, mismo problema"),
                                  (11, 0, "overlay necesita leer el destino"),
                                  (None, 0, "el objeto no lo declara")):
        da = werender.MEZCLA_AL_COMPONER.get(modo, 0)
        if da != espera:
            fallos.append(f"colorBlendMode {modo} dio {da}, se esperaba "
                          f"{espera} ({por_que})")


def prueba_herencia_de_grupo(fallos: list[str]) -> None:
    """El `origin` de un hijo es relativo al padre, dibuje el padre o no.

    Durante un tiempo solo heredaban los hijos de un grupo vacio. Era un
    parche a otro fallo ---la mezcla del objeto--- y se llevaba la lluvia de
    3053927686 a la esquina del lienzo.
    """
    padre = wescene.SceneObject(id=1, name="fondo", kind="image",
                                raw={"id": 1, "image": "models/f.json",
                                     "origin": "1920 1080 0", "scale": "2 2 2"})
    hijo = wescene.SceneObject(id=2, name="lluvia", kind="image",
                               raw={"id": 2, "image": "models/l.json",
                                    "parent": 1, "origin": "10 -20 0",
                                    "scale": "3 3 3"})
    org, esc, _ang = werender.transform_absoluto(hijo, {"1": padre, "2": hijo})
    if [round(x, 4) for x in org] != [1940.0, 1040.0, 0.0]:
        fallos.append(f"el origen del hijo no se compuso: {org}")
    if [round(x, 4) for x in esc] != [6.0, 6.0, 6.0]:
        fallos.append(f"la escala del hijo no se compuso: {esc}")
    # Sin padre no cambia nada.
    org, esc, _ang = werender.transform_absoluto(padre, {"1": padre})
    if [round(x, 4) for x in org] != [1920.0, 1080.0, 0.0]:
        fallos.append(f"un objeto sin padre no deberia moverse: {org}")


def prueba_visibilidad_heredada(fallos: list[str]) -> None:
    """Apagar un grupo apaga lo que cuelga de el.

    Mirando solo el campo `visible` de cada objeto se dibujan capas que el
    autor escondio dentro de un grupo apagado. Lonely Cat trae la escena SEIS
    veces, una por idioma, y apaga cinco por el padre: sin heredar se
    dibujaban 107 objetos de mas, y de ahi su nevada de puntos blancos.
    """
    datos = {"objects": [
        {"id": 1, "name": "grupo apagado", "visible": False},
        {"id": 2, "name": "hijo", "parent": 1},
        {"id": 3, "name": "nieto", "parent": 2},
        {"id": 4, "name": "grupo vivo"},
        {"id": 5, "name": "hijo del vivo", "parent": 4},
        {"id": 6, "name": "hijo apagado del vivo", "parent": 4, "visible": False},
        {"id": 7, "name": "huerfano", "parent": 999},
    ]}
    v = wescene._visibilidad_heredada(datos, {})
    for o in datos["objects"]:
        espera = o["id"] in (4, 5, 7)
        da = v[id(o)]
        if da != espera:
            fallos.append(f"{o['name']} (id {o['id']}): visible={da}, "
                          f"se esperaba {espera}")

    # Un ciclo en los datos no puede colgar el cargador.
    ciclo = {"objects": [{"id": 1, "parent": 2}, {"id": 2, "parent": 1}]}
    if len(wescene._visibilidad_heredada(ciclo, {})) != 2:
        fallos.append("un ciclo de padres deberia resolverse igual")


def prueba_niveles_mipmap(fallos: list[str]) -> None:
    """El nivel mas alto de la piramide del buffer de escena.

    El reflejo muestrea con `roughness * g_TextureNMipMapInfo`, asi que este
    numero decide cuanto llega a desenfocarse. `glGenerateMipmap` va dividiendo
    por dos hasta 1x1: son `floor(log2(max(w, h))) + 1` niveles.
    """
    for w, h, espera, por_que in ((3840, 2160, 12, "lienzo 4K"),
                                  (1920, 1200, 11, "un panel 16:10"),
                                  (1024, 1024, 11, "potencia de dos exacta"),
                                  (1, 1, 1, "un buffer de un pixel")):
        da = werender.niveles_mipmap(w, h)
        if da != espera:
            fallos.append(f"niveles_mipmap({w}, {h}) dio {da}, "
                          f"se esperaba {espera} ({por_que})")


def prueba_opacidad_del_objeto(fallos: list[str]) -> None:
    """La opacidad tiene que salir por los tres nombres que leen los shaders.

    Cada generacion lee uno, y son ramas excluyentes del mismo fichero. Iba
    solo en `g_Alpha`, que no lo lee ninguno de los de imagen: la sombra del
    vinilo de 3624164256 ---negra al 10 %--- salia opaca, un lunar negro en
    mitad del personaje.
    """
    lineas = werender.uniforms_de_tinte([0.0, 0.0, 0.0], 0.1, 1.0)
    por_nombre = {l.split()[1]: l.split()[2:] for l in lineas}

    if "g_Color4" not in por_nombre:
        fallos.append("no se emite g_Color4")
    elif len(por_nombre["g_Color4"]) != 4 or float(por_nombre["g_Color4"][3]) != 0.1:
        fallos.append(f"la opacidad no va en el .w de g_Color4: {por_nombre.get('g_Color4')}")
    for nombre in ("g_UserAlpha", "g_Alpha"):
        if nombre not in por_nombre or float(por_nombre[nombre][0]) != 0.1:
            fallos.append(f"la opacidad no llega a {nombre}: {por_nombre.get(nombre)}")

    # El color va en el rgb y el brillo aparte: son cosas distintas.
    lineas = werender.uniforms_de_tinte([1.0, 0.5, 0.25], 1.0, 2.0)
    por_nombre = {l.split()[1]: l.split()[2:] for l in lineas}
    if [float(x) for x in por_nombre["g_Color4"][:3]] != [1.0, 0.5, 0.25]:
        fallos.append(f"el color no llega intacto: {por_nombre['g_Color4']}")
    if float(por_nombre["g_Brightness"][0]) != 2.0:
        fallos.append("el brillo no llega a g_Brightness")
    # Un objeto sin opacidad declarada no debe oscurecer nada.
    if float(por_nombre["g_Color4"][3]) != 1.0 or float(por_nombre["g_UserAlpha"][0]) != 1.0:
        fallos.append("con alpha 1 la capa no queda neutra")


def prueba_color_del_shader_plano(fallos: list[str]) -> None:
    """El rgb tiene que salir tambien por `g_Color`, el del shader plano.

    `flat.frag` ---y `flatpoint` y `editorsprite`--- no leen ninguno de los
    otros tres nombres: su fragmento entero es `vec4(g_Color, g_Alpha)`. Sin
    emitirlo GL lo da a cero y la capa sale NEGRA OPACA, tapando lo de debajo.
    Son 44 capas en 15 escenas; la mas cara es la base blanca de las nubes de
    2262142032, que borraba el cielo y dejaba la ciudad en siluetas.
    """
    por_nombre = {l.split()[1]: l.split()[2:]
                  for l in werender.uniforms_de_tinte([1.0, 0.5, 0.25], 1.0, 1.0)}

    if "g_Color" not in por_nombre:
        fallos.append("no se emite g_Color: el shader plano se dibuja negro")
    elif [float(x) for x in por_nombre["g_Color"]] != [1.0, 0.5, 0.25]:
        fallos.append(f"el color no llega a g_Color: {por_nombre['g_Color']}")

    # El blanco por defecto es el caso que rompia la escena: sin g_Color, un
    # `Solid` de color 1 1 1 salia a 0 0 0.
    por_nombre = {l.split()[1]: l.split()[2:]
                  for l in werender.uniforms_de_tinte([1.0, 1.0, 1.0], 1.0, 1.0)}
    if [float(x) for x in por_nombre.get("g_Color", [])] != [1.0, 1.0, 1.0]:
        fallos.append(f"una capa blanca no sale blanca: {por_nombre.get('g_Color')}")

    # Estos shaders no declaran g_Brightness, asi que el brillo solo puede
    # llegar multiplicado dentro del rgb.
    por_nombre = {l.split()[1]: l.split()[2:]
                  for l in werender.uniforms_de_tinte([1.0, 0.5, 0.0], 1.0, 2.0)}
    if [float(x) for x in por_nombre.get("g_Color", [])] != [2.0, 1.0, 0.0]:
        fallos.append(f"el brillo no entra en g_Color: {por_nombre.get('g_Color')}")

    # La opacidad NO va en g_Color: la lee g_Alpha, que es otro nombre. Si se
    # colara aqui se aplicaria dos veces.
    if len(por_nombre.get("g_Color", [])) != 3:
        fallos.append("g_Color tiene que ser un vec3, no llevar el alfa")


def main() -> int:
    fallos: list[str] = []
    for prueba in (prueba_vp_reconstruye_la_mvp, prueba_normales_ortonormal,
                   prueba_luces, prueba_empaquetado,
                   prueba_sampler_por_defecto, prueba_niveles_mipmap,
                   prueba_valor_de_usuario, prueba_curva_de_animacion,
                   prueba_mezcla_de_objeto, prueba_herencia_de_grupo,
                   prueba_visibilidad_heredada,
                   prueba_opacidad_del_objeto,
                   prueba_color_del_shader_plano):
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
