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
        org, col, radio, expo = luces[0]
        if org != [100.0, 200.0, 300.0]:
            fallos.append(f"origen mal leido: {org}")
        # El shader recibe un solo color: la intensidad va dentro.
        if not np.allclose(col, [2.0, 1.0, 0.5]):
            fallos.append(f"la intensidad no se aplico al color: {col}")
        if radio != 300.0:
            fallos.append(f"radio mal leido: {radio}")
        # El exponente viaja con la luz, no clavado en el shader: en el modulo
        # que WE genera de verdad va en el `.w` del origen de cada una.
        if expo != werender.EXPONENTE_POR_DEFECTO:
            fallos.append(f"la luz no lleva su exponente: {expo}")

    # Una luz apagada por el autor no cuenta, y no invalida la escena.
    sc = _escena([_luz(visible=False), _luz()])
    if len(werender.luces_de_escena(sc)) != 1:
        fallos.append("una luz invisible no deberia contar")

    # Un tipo que no sabemos poner apaga la iluminacion de la escena entera:
    # media luz oscurece mas de lo que alumbra. Ver 3053927686.
    sc = _escena([_luz(light="ltube"), _luz()])
    if werender.luces_de_escena(sc) != []:
        fallos.append("una luz de tubo deberia dejar la escena sin iluminar")

    # ...pero solo si esta encendida.
    sc = _escena([_luz(light="ltube", visible=False), _luz()])
    if len(werender.luces_de_escena(sc)) != 1:
        fallos.append("una luz de tubo apagada no deberia estorbar")


def prueba_empaquetado(fallos: list[str]) -> None:
    """La cuarta luz viaja en los `.w` de las otras tres, no en un cuarto vec4."""
    luces = [([0, 0, 0], [float(i + 1)] * 3, 1.0, 2.0) for i in range(4)]
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
    v = werender.colores_premultiplicados([([0, 0, 0], [1.0, 1.0, 1.0], 10.0, 2.0)])
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


def main() -> int:
    fallos: list[str] = []
    for prueba in (prueba_vp_reconstruye_la_mvp, prueba_normales_ortonormal,
                   prueba_luces, prueba_empaquetado,
                   prueba_sampler_por_defecto, prueba_opacidad_del_objeto):
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
