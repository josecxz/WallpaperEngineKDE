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
import shutil
import subprocess
import sys
import tempfile
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


def _orto(canvas: tuple[int, int]) -> np.ndarray:
    """Pixeles del lienzo -> clip, la proyeccion ortografica de la escena. La
    z se queda a cero: la MVP de una capa aplana la profundidad del `origin`
    (la prueba de profundidad esta apagada en todo el motor), y es la de mundo
    la que la lleva, para la luz."""
    w, h = canvas
    return np.array([[2.0 / w, 0.0, 0.0, -1.0],
                     [0.0, 2.0 / h, 0.0, -1.0],
                     [0.0, 0.0, 1.0, 0.0],
                     [0.0, 0.0, 0.0, 1.0]])


def _mvp_frente_a_mundo(obj, canvas, malla, por_id=None) -> float:
    """Lo que mas se separa un elemento de `object_mvp` de `orto · object_world`."""
    mvp = np.array(werender.object_mvp(obj, canvas, mesh=malla,
                                       por_id=por_id)).reshape(4, 4)
    mundo = np.array(werender.object_world(obj, canvas, mesh=malla,
                                           por_id=por_id)).reshape(4, 4)
    mundo[2, 3] = 0.0       # la z del `origin`, ver `_orto`
    return float(np.abs(mvp - _orto(canvas) @ mundo).max())


def prueba_giro_en_pixeles(fallos: list[str]) -> None:
    """Una capa girada gira en PIXELES del lienzo, y despues se proyecta.

    `object_mvp` giraba ya en clip ---R · D · E en vez de D · R · E, con
    D = diag(2/w, 2/h)---, asi que en un lienzo no cuadrado una capa girada
    que no estuviera a 0 o 180 grados salia estirada en x por ancho/alto y
    cizallada: la aguja de las horas de 2396319149, horizontal a las 03:00,
    16/9 mas larga y 9/16 mas fina. `object_world` (la luz) y `particle_mvp`
    ya giraban en pixeles; las tres tienen que dar la misma colocacion.

    En sintetico, una capa de 100x100 girada sigue ocupando 100x100 px: las
    columnas de la parte lineal, devueltas a pixeles, miden 50 (la
    semiextension) y son perpendiculares. En el corpus, cada capa de imagen o
    de texto de las 129 escenas, como malla y como quad, da la misma MVP que
    la ortografica por la de mundo.
    """
    lienzo = (1920, 1080)
    for grados in (90.0, 30.0):
        obj = _objeto(origin="700 300 0", size="100 100",
                      angles=f"0 0 {math.radians(grados)!r}")
        m = np.array(werender.object_mvp(obj, lienzo)).reshape(4, 4)
        px = np.diag([lienzo[0] / 2.0, lienzo[1] / 2.0]) @ m[:2, :2]
        normas = np.linalg.norm(px, axis=0)
        cruce = float(px[:, 0] @ px[:, 1])
        if np.abs(normas - 50.0).max() > 1e-9 or abs(cruce) > 1e-9:
            fallos.append(f"capa de 100x100 a {grados} grados en 1920x1080: "
                          f"columnas de {normas} px, producto {cruce:.3g}")
        print(f"    100x100 a {grados:g} grados en 1920x1080: columnas de "
              f"{normas[0]:.12g} y {normas[1]:.12g} px, producto {cruce:.3g}")
        peor = _mvp_frente_a_mundo(obj, lienzo, False)
        if peor > 1e-9:
            fallos.append(f"capa de 100x100 a {grados} grados: MVP a {peor:.3g} "
                          "de orto * mundo")
        # Y la VP que se deduce para una capa iluminada es la ortografica pura.
        vp = np.array(werender.vp_de(werender.object_mvp(obj, lienzo),
                                     werender.object_world(obj, lienzo))).reshape(4, 4)
        if np.abs(vp - _orto(lienzo)).max() > 1e-9:
            fallos.append(f"capa de 100x100 a {grados} grados: la VP no es la "
                          "ortografica del lienzo")

    import wepaths
    capas = giradas = 0
    escenas_giradas: set[str] = set()
    peor = 0.0
    for d in sorted(wepaths.we_workshop().iterdir()):
        if not (d / "scene.pkg").is_file():
            continue
        try:
            res = wescene.AssetResolver.for_wallpaper(d, wepaths.we_assets())
            sc = wescene.load_scene(res)
        except Exception:
            continue
        proj = sc.general.get("orthogonalprojection")
        lz = ((int(werender._floats(proj.get("width", 1920))[0]),
               int(werender._floats(proj.get("height", 1080))[0]))
              if isinstance(proj, dict) else (1920, 1080))
        por_id = {o.raw.get("id"): o for o in sc.objects}
        for o in sc.objects:
            if o.kind not in ("image", "text") or not o.passes:
                continue
            if o.raw.get("_passthrough") and not werender._es_composelayer(o):
                continue
            for malla in (False, True):
                e = _mvp_frente_a_mundo(o, lz, malla, por_id)
                peor = max(peor, e)
                if e > 1e-6:
                    fallos.append(f"{d.name} {o.name!r} (malla {malla}): MVP a "
                                  f"{e:.3g} de orto * mundo")
            capas += 1
            _, _, ang = werender.transform_absoluto(o, por_id)
            if lz[0] != lz[1] and abs(math.sin(ang[2])) > 1e-6:
                giradas += 1
                escenas_giradas.add(d.name)
    print(f"    corpus: {capas} capas de imagen o texto, peor elemento a "
          f"{peor:.3g} de orto * mundo; giradas en lienzo no cuadrado: "
          f"{giradas} en {len(escenas_giradas)} escenas")
    if capas == 0:
        fallos.append("giro en pixeles: no se ha leido ninguna capa del corpus")


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


def prueba_hijo_sin_origin(fallos: list[str]) -> None:
    """Un hijo sin `origin` esta en el punto de su padre, no en el centro.

    En WE el campo vale 0 si falta y es relativo al padre. Se iba al centro del
    lienzo: 34 hijos en 10 escenas, el «FPS 60» de 3462491575 entre ellos.
    """
    lienzo = (1000, 800)
    padre = wescene.SceneObject(id=1, name="padre", kind="image",
                                raw={"id": 1, "image": "models/p.json",
                                     "origin": "100 50 0", "scale": "2 2 2",
                                     "size": "10 10"})
    hijo = wescene.SceneObject(id=2, name="hijo", kind="image",
                               raw={"id": 2, "image": "models/h.json",
                                    "parent": 1, "size": "10 10"})
    por_id = {"1": padre, "2": hijo}
    # Mismo punto: la colocacion del hijo y la del padre dan el mismo centro.
    _, _, ax, ay, *_ = werender._colocacion(hijo, lienzo, False, por_id)
    _, _, px, py, *_ = werender._colocacion(padre, lienzo, False, por_id)
    if (round(ax, 6), round(ay, 6)) != (round(px, 6), round(py, 6)):
        fallos.append(f"el hijo sin origin no esta en su padre: "
                      f"{(ax, ay)} frente a {(px, py)}")
    # Una raiz sin `origin`, y un hijo de un padre que no existe, como antes.
    for raw in ({"id": 3, "size": "10 10"},
                {"id": 3, "size": "10 10", "parent": 99}):
        suelta = wescene.SceneObject(id=3, name="suelta", kind="image", raw=raw)
        if not werender._al_centro_sin_origin(suelta, por_id):
            fallos.append(f"sin padre real deberia ir al centro: {raw}")


def prueba_parallax_de_camara(fallos: list[str]) -> None:
    """El parallax de camara en reposo, tal como lo hace WE.

    `amount * depth * (origin - centro)`, con el `origin` y la profundidad de
    la RAIZ: el hijo se mueve con su grupo aunque declare otra profundidad.
    Una escena con el parallax apagado no mueve nada. Ver `parallax_de_camara`.
    """
    def escena(encendido):
        raiz = wescene.SceneObject(id=1, name="grupo", kind="image",
                                   raw={"id": 1, "origin": "700 150 0",
                                        "parallaxDepth": "2 1"})
        hijo = wescene.SceneObject(id=2, name="hijo", kind="image",
                                   raw={"id": 2, "parent": 1,
                                        "origin": "10 0 0",
                                        "parallaxDepth": "5 5"})
        quieto = wescene.SceneObject(id=3, name="fondo", kind="image",
                                     raw={"id": 3, "origin": "100 100 0"})
        general = {"cameraparallax": encendido, "cameraparallaxamount": 0.5,
                   "orthogonalprojection": {"width": 1000, "height": 500}}
        # El ojo fuera del origen no cuenta: WE lo pone a cero en una escena
        # ortografica sin `paths` antes de que llegue al objetivo del parallax.
        # Sumado, la raiz se iria (-200, -20) y el test lo cazaria.
        camara = {"eye": "200 40 0", "center": "200 40 -1", "up": "0 1 0"}
        return wescene.Scene(general=general, camera=camara,
                             objects=[raiz, hijo, quieto]), raiz, hijo, quieto

    sc, raiz, hijo, quieto = escena(True)
    n = werender.parallax_de_camara(sc, (1000, 500))
    por_id = {"1": raiz, "2": hijo, "3": quieto}
    if n != 1:
        fallos.append(f"parallax: se movieron {n} raices, se esperaba 1")
    # 0.5 * 2 * (700 - 500) = 200 ; 0.5 * 1 * (150 - 250) = -50
    org, _, _ = werender.transform_absoluto(raiz, por_id)
    if [round(x, 3) for x in org[:2]] != [900.0, 100.0]:
        fallos.append(f"parallax: la raiz deberia quedar en (900, 100): {org}")
    org, _, _ = werender.transform_absoluto(hijo, por_id)
    if [round(x, 3) for x in org[:2]] != [910.0, 100.0]:
        fallos.append(f"parallax: el hijo no se mueve con su grupo: {org}")
    if raiz.raw.get("_paralaje_k") != [1.0, 0.5]:
        fallos.append(f"parallax: amount*depth deberia ser (1, 0.5): "
                      f"{raiz.raw.get('_paralaje_k')}")
    org, _, _ = werender.transform_absoluto(quieto, por_id)
    if [round(x, 3) for x in org[:2]] != [100.0, 100.0]:
        fallos.append(f"parallax: una capa sin profundidad se ha movido: {org}")

    sc, raiz, _hijo, _quieto = escena(False)
    if werender.parallax_de_camara(sc, (1000, 500)) or raiz.raw.get("_paralaje"):
        fallos.append("parallax: con `cameraparallax` apagado no deberia mover nada")


def prueba_posicion_de_parallax(fallos: list[str]) -> None:
    """`g_ParallaxPosition` es el P de la camara partido por el lienzo.

    Leido en wallpaper64.exe (caso 0x6b del `switch` de uniforms, 0x1400d9e90,
    que copia lo que la camara escribe en 0x140189cbe): con
    `cameraparallaxmouseinfluence` y la y hacia ARRIBA. Las dos formas de
    equivocarse dan un numero razonable y ninguna avisa:

    * Sin la influencia, las dos escenas del corpus que la ponen negativa
      ---y `cameraparallaxamount` a 0, asi que la camara no se mueve y la
      influencia solo llega aqui--- mueven la profundidad al reves y entre
      3,7 y cinco veces mas fuerte.
    * Con la y de la pantalla, el efecto se mueve al reves en vertical.

    Se mira la funcion y el plan de fotograma de `3077334064` (m = -0,2) y de
    `3624164256` (m = -0,27), y que con `cameraparallax` apagado ---en
    `3624164256` cuelga de una propiedad del usuario--- se quede en el centro.
    """
    casos = [(((0.2, 0.3), -0.2), (0.56, 0.46)),
             (((0.8, 0.9), 0.7), (0.71, 0.22)),
             (((0.1, 0.75), 1.0), (0.1, 0.25)),
             (((1.4, -0.3), 1.0), (1.0, 1.0))]      # el raton, acotado
    for (puntero, m), esperado in casos:
        got = werender.posicion_de_parallax(puntero, m)
        if any(abs(a - b) > 1e-9 for a, b in zip(got, esperado)):
            fallos.append(f"g_ParallaxPosition: con el raton en {puntero} y "
                          f"m = {m} da {got}, se esperaba {esperado}")

    import wepaths
    raiz = Path(__file__).resolve().parent.parent
    for escena, apagado, esperado in (("3077334064", False, (0.56, 0.46)),
                                      ("3624164256", False, (0.581, 0.446)),
                                      ("3624164256", True, (0.5, 0.5))):
        d = wepaths.we_workshop() / escena
        if not d.is_dir():
            fallos.append(f"g_ParallaxPosition: falta la escena {escena}")
            continue
        r = werender.Renderer(d, raiz / "obj" / "glexec", 0.0,
                              puntero=(0.2, 0.3))
        if apagado:
            # La propiedad del usuario que enciende su `cameraparallax`.
            leer = r.res.read_json

            def sin_parallax(nombre, leer=leer):
                datos = leer(nombre)
                if nombre == "project.json":
                    datos["general"]["properties"]["disableparallax"]["value"] = False
                return datos
            r.res.read_json = sin_parallax
        try:
            r._build(None)
            plan = r._fotograma(r.time)
            vals, prog = [], None
            for linea in plan:
                if linea.startswith("prog "):
                    prog = linea.split()[1:3]
                elif linea.startswith("u2f g_ParallaxPosition") and prog and \
                        "g_ParallaxPosition" in "".join(Path(f).read_text()
                                                        for f in prog):
                    vals.append([float(x) for x in linea.split()[2:4]])
        finally:
            shutil.rmtree(r.tmp, ignore_errors=True)
        if not vals or any(abs(a - b) > 1e-4 for v in vals
                           for a, b in zip(v, esperado)):
            fallos.append(f"g_ParallaxPosition: {escena} "
                          f"{'apagado ' if apagado else ''}con el raton en "
                          f"(0.2, 0.3) sube {vals}, se esperaba {esperado}")


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


def prueba_temblor_de_camara(fallos: list[str]) -> None:
    """El temblor de camara de WE (`camerashake`), con la formula del motor.

    Tres cosas, porque las tres fallan callando:

    * La amplitud en el lienzo: `0,1 * amplitud * 0,1 * alto` de la
      `orthogonalprojection`, partida por el ancho y por el alto para la
      linea `temblor`. Y nada si `camerashake` esta apagado, tambien cuando
      lo apaga una propiedad del usuario cuya copia en la escena dice `true`.
    * La curva que evaluan los dos ejecutores, `src/wetemblor.c`, contra
      valores calculados a mano con la forma leida en 0x140199580.
    * El plan de una escena del corpus que lo enciende (`1692307745`) lleva la
      linea `temblor` y una `tiembla` por capa, y el de una que lo tiene en
      `false` tras una propiedad con `script` (`2968771936`) no lleva ninguna.
    """
    orto = {"width": 1920, "height": 1080}
    g = {"camerashake": True, "camerashakeamplitude": 0.5,
         "camerashakespeed": 1.2, "camerashakeroughness": 0.5,
         "orthogonalprojection": orto}
    t = werender.temblor_de_camara(g, {}, (1920, 1080))
    # 0,1 * 0,5 * 0,1 * 1080 = 5,4 px
    if t is None or any(abs(a - b) > 1e-9 for a, b in
                        zip(t, (5.4 / 1920, 5.4 / 1080, 1.2, 0.5))):
        fallos.append(f"temblor: (ax, ay, velocidad, rugosidad) = {t}, se "
                      f"esperaba (5.4/1920, 5.4/1080, 1.2, 0.5)")
    if werender.temblor_de_camara(dict(g, camerashake=False), {}, (1920, 1080)):
        fallos.append("temblor: con `camerashake: false` no deberia temblar")
    usuario = dict(g, camerashake={"user": "cs", "value": True})
    if werender.temblor_de_camara(usuario, {"cs": {"value": False}},
                                  (1920, 1080)):
        fallos.append("temblor: manda la propiedad del usuario, no la copia")
    if not werender.temblor_de_camara(usuario, {"cs": {"value": True}},
                                      (1920, 1080)):
        fallos.append("temblor: la propiedad del usuario lo enciende")
    sin_orto = {k: v for k, v in g.items() if k != "orthogonalprojection"}
    if werender.temblor_de_camara(sin_orto, {}, (1920, 1080)):
        fallos.append("temblor: sin `orthogonalprojection` no hay lienzo "
                      "con el que escalarlo")

    # La curva, en C. (velocidad, rugosidad, t) -> (x, y) con amplitud 1.
    casos = [((1.0, 0.5, 1.0), (0.492393, 0.885683)),     # rugosidad^3 = 0,125
             ((1.27, 0.92, 0.5), (0.675029, 0.857936)),
             ((0.88, 0.0, 2.0), (0.021995, 0.880560)),    # sin rugosidad
             ((0.88, 1.0, 2.0), (0.021995, 0.880560))]    # r^3 = 1: tampoco
    raiz = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        fuente, binario = Path(tmp) / "arnes.c", Path(tmp) / "arnes"
        fuente.write_text(
            '#include <stdio.h>\n#include <stdlib.h>\n#include "wetemblor.h"\n'
            "int main(int c, char **v) {\n"
            "    float x, y;\n"
            "    we_temblor(1.0f, 1.0f, strtof(v[1], 0), strtof(v[2], 0),\n"
            "               strtof(v[3], 0), &x, &y);\n"
            '    printf("%.6f %.6f\\n", x, y);\n'
            "    return 0;\n}\n")
        try:
            subprocess.run(["cc", "-O2", "-std=c11", f"-I{raiz / 'src'}",
                            "-o", str(binario), str(fuente),
                            str(raiz / "src" / "wetemblor.c"), "-lm"],
                           check=True, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            fallos.append(f"temblor: no compila src/wetemblor.c: {e}")
            return
        for (v, r, s), esperado in casos:
            sale = subprocess.run([str(binario), str(v), str(r), str(s)],
                                  capture_output=True, text=True,
                                  env={"LC_ALL": "C"}).stdout.split()
            got = [float(x) for x in sale]
            if len(got) != 2 or any(abs(a - b) > 1e-4
                                    for a, b in zip(got, esperado)):
                fallos.append(f"temblor: la curva en (v={v}, r={r}, t={s}) "
                              f"da {got}, se esperaba {esperado}")

    # El plan de verdad, en las dos direcciones.
    import wepaths
    taller = wepaths.we_workshop()
    for escena, tiembla in (("1692307745", True), ("2968771936", False)):
        d = taller / escena
        if not d.is_dir():
            fallos.append(f"temblor: falta la escena {escena} del corpus")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            werender.emit_plan(d, Path(tmp))
            plan = (Path(tmp) / "plan.txt").read_text().splitlines()
        lineas = [l for l in plan if l.startswith("temblor ")]
        capas = sum(1 for l in plan if l == "tiembla")
        if not tiembla:
            if lineas or capas:
                fallos.append(f"temblor: {escena} lo tiene apagado y su plan "
                              f"lleva {len(lineas)} `temblor` y {capas} "
                              f"`tiembla`")
            continue
        # 0,1 * 0,18 * 0,1 * 1080 = 1,944 px; velocidad 1,4, rugosidad 1
        esperado = (1.944 / 1920, 1.944 / 1080, 1.4, 1.0)
        valores = [float(x) for x in lineas[0].split()[1:]] if lineas else []
        if len(valores) != 4 or any(abs(a - b) > 1e-6
                                    for a, b in zip(valores, esperado)):
            fallos.append(f"temblor: {escena} deberia llevar `temblor "
                          f"{' '.join(f'{x:.6g}' for x in esperado)}`: "
                          f"{lineas}")
        objetos = sum(1 for l in plan if l.startswith("object "))
        if capas == 0 or capas > objetos:
            fallos.append(f"temblor: {escena} lleva {capas} `tiembla` para "
                          f"{objetos} objetos")


def prueba_particulas_en_perspectiva(fallos: list[str]) -> None:
    """Un sistema con el bit 0x4 de su `flags` («Perspective rendering»).

    WE lo dibuja con una camara en perspectiva que rehace a partir de la
    ortografica (0x1401e5b60): ojo a `d = alto / (2 tan(fov/2))` del lienzo,
    centrado en el, y `XMMatrixPerspectiveFovRH` con 5 y max(15000, d + 1000).
    Lo que tiene que cumplirse, con las cuentas hechas aqui a mano:

    * En z = 0 la particula cae en el MISMO pixel que con la ortografica: el
      ojo esta justo a la distancia a la que el lienzo llena el fov.
    * A otra z, su posicion respecto al centro del lienzo y su tamano se
      multiplican por `d / (d - z)`, con z en pixeles de lienzo; detras del
      ojo (z > d) el recorte la tira.
    * El fov es `perspectiveoverridefov`, 95 si no esta, acotado a
      [0,1, 179,9].
    * El plan del starfield de `1927028828` ---estrellas que solo se mueven en
      z--- lleva `perspectiva 1` en su `.psys` y una MVP proyectiva en su
      pase; el de una escena sin el bit no lleva ninguna de las dos cosas.
    """
    if werender.fov_de_perspectiva({}) != 95.0:
        fallos.append("perspectiva: sin `perspectiveoverridefov` el fov es 95")
    if werender.fov_de_perspectiva({"perspectiveoverridefov": 30.0}) != 30.0:
        fallos.append("perspectiva: el fov es `perspectiveoverridefov`")
    if werender.fov_de_perspectiva({"perspectiveoverridefov": 200}) != 179.9:
        fallos.append("perspectiva: el fov se acota a 179,9")

    w, h = CANVAS
    obj = _objeto(origin="1500 700 40", scale="2 1.5 3", angles="0 0 0.4",
                  particle="p.json")
    orto = np.array(werender.particle_mvp(obj, CANVAS)).reshape(4, 4)
    for fov in (95.0, 30.0):
        m = np.array(werender.particle_mvp_perspectiva(obj, CANVAS, fov)
                     ).reshape(4, 4)
        d = h / (2.0 * math.tan(math.radians(fov) / 2.0))

        def pixel(mat, p):
            c = mat @ np.array([p[0], p[1], p[2], 1.0])
            return np.array([(c[0] / c[3] + 1) * w / 2,
                             (c[1] / c[3] + 1) * h / 2]), c[3]

        # El origin del objeto tiene z = 40 y su escala en z es 3: el plano
        # z = 0 del LIENZO es la z del sistema -40/3.
        z0 = -40.0 / 3.0
        for x, y in ((0.0, 0.0), (300.0, -200.0), (-900.0, 450.0)):
            a, _ = pixel(orto, (x, y, z0))
            b, _ = pixel(m, (x, y, z0))
            if np.abs(a - b).max() > 1e-6:
                fallos.append(f"perspectiva (fov {fov}): en z = 0 la particula "
                              f"({x}, {y}) cae en {b}, no en {a} como en "
                              f"ortografico")
        centro = np.array([w / 2, h / 2])
        for zs in (60.0, -150.0):
            zl = 3.0 * zs + 40.0
            k = d / (d - zl)
            p0, _ = pixel(orto, (300.0, -200.0, zs))
            p1, _ = pixel(orto, (310.0, -200.0, zs))
            q0, _ = pixel(m, (300.0, -200.0, zs))
            q1, _ = pixel(m, (310.0, -200.0, zs))
            if np.abs((q0 - centro) - k * (p0 - centro)).max() > 1e-6:
                fallos.append(f"perspectiva (fov {fov}): a z = {zl} la "
                              f"posicion no se aleja del centro por "
                              f"d/(d-z) = {k:.4f}")
            tam_o, tam_p = np.linalg.norm(p1 - p0), np.linalg.norm(q1 - q0)
            if abs(tam_p - k * tam_o) > 1e-6:
                fallos.append(f"perspectiva (fov {fov}): a z = {zl} el tamano "
                              f"es {tam_p:.4f} px y no {k * tam_o:.4f}")
        _, wc = pixel(m, (0.0, 0.0, (d + 10.0 - 40.0) / 3.0))
        if wc >= 0:
            fallos.append(f"perspectiva (fov {fov}): detras del ojo w tiene "
                          f"que ser negativa y es {wc}")

    import wepaths
    taller = wepaths.we_workshop()
    for escena, con_bit in (("1927028828", True), ("1828218519", False)):
        d = taller / escena
        if not d.is_dir():
            fallos.append(f"perspectiva: falta la escena {escena} del corpus")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            werender.emit_plan(d, Path(tmp))
            plan = (Path(tmp) / "plan.txt").read_text().splitlines()
            marcados = {p.name for p in Path(tmp).glob("*.psys")
                        if "perspectiva 1" in p.read_text().splitlines()}
        # La MVP de cada pase que dibuja un `psys`, por su indice.
        mvps, actual = {}, None
        for l in plan:
            if l.startswith("psys ") and len(l.split()) == 2:
                actual = int(l.split()[1])
            elif l.startswith("umat4 g_ModelViewProjectionMatrix ") and \
                    actual is not None:
                mvps[actual] = [float(x) for x in l.split()[2:]]
                actual = None
        proyectivas = {i for i, v in mvps.items() if v[12:16] != [0, 0, 0, 1]}
        nombres = {f"s{i:03d}.psys" for i in proyectivas}
        if con_bit and (not marcados or nombres != marcados):
            fallos.append(f"perspectiva: en {escena} los .psys con "
                          f"`perspectiva 1` son {sorted(marcados)} y los "
                          f"pases con MVP proyectiva {sorted(nombres)}")
        if not con_bit and (marcados or proyectivas):
            fallos.append(f"perspectiva: {escena} no tiene el bit y lleva "
                          f"{sorted(marcados)} / {sorted(proyectivas)}")


def main() -> int:
    fallos: list[str] = []
    for prueba in (prueba_vp_reconstruye_la_mvp, prueba_giro_en_pixeles,
                   prueba_normales_ortonormal,
                   prueba_luces, prueba_empaquetado,
                   prueba_sampler_por_defecto, prueba_niveles_mipmap,
                   prueba_valor_de_usuario, prueba_curva_de_animacion,
                   prueba_mezcla_de_objeto, prueba_herencia_de_grupo,
                   prueba_hijo_sin_origin,
                   prueba_parallax_de_camara, prueba_posicion_de_parallax,
                   prueba_temblor_de_camara,
                   prueba_particulas_en_perspectiva,
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
