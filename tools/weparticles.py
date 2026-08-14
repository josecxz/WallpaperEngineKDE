#!/usr/bin/env python3
"""Sistemas de particulas: del JSON de Wallpaper Engine a un fichero `.psys`.

Un sistema de particulas no es una capa mas. El resto del motor resuelve el
grafo una vez y el ejecutor solo dibuja; aqui hay ESTADO que avanza con el
reloj, y ese estado no puede vivir en Python porque el plan se genera una sola
vez y luego se ejecuta miles de veces.

El reparto es el mismo de siempre, con la frontera un paso mas alla:

  * Python (este modulo) lee el JSON, traduce nombres a numeros, aplica los
    valores por defecto y escribe un `.psys` --- una lista plana de piezas con
    sus parametros ya resueltos.
  * `src/weparticles.c` simula. No conoce Wallpaper Engine: solo ejecuta las
    piezas que le llegan. Se compila en los DOS ejecutores para que la
    simulacion no pueda divergir entre el render offline y el escritorio.

El orden de los floats de cada pieza es el contrato entre los dos ficheros y
esta escrito en ambos. El lado C rechaza la pieza si no le llegan los que
espera, asi que una divergencia sale como un aviso, no como basura dibujada.

Censo del corpus (823 sistemas en 106 escenas) que decide que hay que cubrir:

    emisores       sphererandom 607, boxrandom 216           -> los dos
    inicializadores 10 nombres, los 8 mas comunes son el 99% -> los 8
    operadores      13 nombres                               -> los 12 mayores
    renderers      sprite 586, spritetrail 145, rope 34, ropetrail 32
    shader         genericparticle, uno solo, en los 823

Lo que NO se simula, y por que:

  * `mapsequencebetweencontrolpoints` / `mapsequencearoundcontrolpoint` (14
    sistemas): colocan las particulas a lo largo de una ruta de puntos de
    control, no las emiten al azar. Es otro modelo de emision, no un parametro.
  * `remapvalue` (2 sistemas): remapea un canal arbitrario a otro.

Los tres renderers de estela SI se dibujan, por dos caminos distintos:

  * `spritetrail` (145) no necesita historial: el sprite se orienta y se estira
    a lo largo de su propia velocidad, y eso lo hace el vertex shader entero.
    Solo hay que darle los tres numeros de `ComputeParticleTrailTangents`; ver
    `_estela`.
  * `rope` y `ropetrail` (66) son otro shader --- `genericropeparticle` --- y
    una cinta cosida por donde ha pasado la particula: ahi si hace falta
    guardar el historial, que lleva `src/weparticles.c`. Ver `_cinta`.

De `rope` y `ropetrail` se pierde la curva: el geometry shader subdivide cada
segmento con una Bezier (`subdivision`), y la ruta sin geometry shader ---la que
usamos--- une los puntos con quads rectos.

Uso:
    python3 tools/weparticles.py <dir_wallpaper>      # censo de la escena
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
from wescene import AssetResolver, SceneError


def _fl(value) -> list[float]:
    """Numero, bool o cadena '0.5 0.2 0.1' -> lista de floats."""
    if isinstance(value, dict):
        return _fl(value.get("value"))
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
            out.extend(_fl(v))
        return out
    return []


def _v3(value, defecto: float = 0.0) -> list[float]:
    """Tres componentes. Un escalar se reparte a los tres.

    No es un capricho: `rotationrandom` declara `min: -0.4` tanto como
    `min: "0 0 3.141"`, y leer el escalar como (x, 0, 0) dejaria la rotacion
    del sprite --- que es la componente z --- clavada a cero.
    """
    v = _fl(value)
    if not v:
        return [defecto, defecto, defecto]
    if len(v) == 1:
        return [v[0], v[0], v[0]]
    return (v + [defecto, defecto, defecto])[:3]


def _f1(value, defecto: float) -> float:
    v = _fl(value)
    return v[0] if v else defecto


# ── vocabulario ─────────────────────────────────────────────────────────────
#
# Cada entrada devuelve la lista de floats EN EL ORDEN que espera
# `src/weparticles.c`. Un nombre ausente de estas tablas se cuenta como no
# soportado y se anota; nunca se emite a medias.

def _init_vida(e):   return [_f1(e.get("min"), 1.0), _f1(e.get("max"), 1.0)]
def _init_tam(e):    return [_f1(e.get("min"), 32.0), _f1(e.get("max"), 32.0)]
def _init_alfa(e):   return [_f1(e.get("min"), 1.0), _f1(e.get("max"), 1.0)]


def _init_color(e):
    # Los colores de particula van de 0 a 255; el shader los quiere de 0 a 1.
    # Sin `max` el color es fijo: 145 sistemas del corpus solo declaran `min`.
    mn = _v3(e.get("min"), 255.0)
    mx = _v3(e.get("max"), 255.0) if e.get("max") is not None else list(mn)
    return [c / 255.0 for c in mn] + [c / 255.0 for c in mx]


def _init_vec(e):
    return _v3(e.get("min")) + _v3(e.get("max"))


def _init_turbvel(e):
    return [_f1(e.get("scale"), 0.01), _f1(e.get("timescale"), 1.0),
            _f1(e.get("speedmin"), 0.0), _f1(e.get("speedmax"), 0.0),
            _f1(e.get("phasemax"), 0.0)] + _v3(e.get("offset"))


INICIALIZADORES = {
    "lifetimerandom": _init_vida,
    "sizerandom": _init_tam,
    "alpharandom": _init_alfa,
    "colorrandom": _init_color,
    "velocityrandom": _init_vec,
    "rotationrandom": _init_vec,
    "angularvelocityrandom": _init_vec,
    "turbulentvelocityrandom": _init_turbvel,
}


def _op_mov(e):
    return _v3(e.get("gravity")) + [_f1(e.get("drag"), 0.0)]


def _op_fade(e):
    # `fadeouttime` es el instante en que EMPIEZA a apagarse; 1 = no se apaga.
    return [_f1(e.get("fadeintime"), 0.0), _f1(e.get("fadeouttime"), 1.0)]


def _op_rampa(e):
    # Los tiempos son fracciones de la vida de la particula, no segundos.
    return [_f1(e.get("starttime"), 0.0), _f1(e.get("endtime"), 1.0),
            _f1(e.get("startvalue"), 1.0), _f1(e.get("endvalue"), 1.0)]


def _op_color(e):
    return [_f1(e.get("starttime"), 0.0), _f1(e.get("endtime"), 1.0)] \
        + _v3(e.get("startvalue"), 1.0) + _v3(e.get("endvalue"), 1.0)


def _osc(e, esc_min: float = 1.0):
    fmin = _f1(e.get("frequencymin"), _f1(e.get("frequencymax"), 0.0))
    fmax = _f1(e.get("frequencymax"), fmin)
    return [fmin, fmax,
            _f1(e.get("scalemin"), esc_min), _f1(e.get("scalemax"), 1.0),
            _f1(e.get("phasemin"), 0.0), _f1(e.get("phasemax"), 0.0)]


def _op_oscpos(e):
    # Aqui `scalemin/max` son la AMPLITUD en pixeles, no un factor: el defecto
    # neutro es 0, y la mascara decide sobre que ejes se mueve.
    return [_f1(e.get("frequencymin"), 0.0), _f1(e.get("frequencymax"), 0.0),
            _f1(e.get("scalemin"), 0.0), _f1(e.get("scalemax"), 0.0),
            _f1(e.get("phasemin"), 0.0), _f1(e.get("phasemax"), 0.0)] \
        + _v3(e.get("mask"), 1.0)


def _op_angmov(e):
    return _v3(e.get("force")) + [_f1(e.get("drag"), 0.0)]


def _op_turb(e):
    return [_f1(e.get("scale"), 0.01), _f1(e.get("timescale"), 1.0),
            _f1(e.get("speedmin"), 0.0), _f1(e.get("speedmax"), 0.0),
            _f1(e.get("phasemin"), 0.0), _f1(e.get("phasemax"), 0.0)] \
        + _v3(e.get("mask"), 1.0)


def _op_atrae(e):
    return [_f1(e.get("controlpoint"), 0.0), _f1(e.get("scale"), 0.0),
            _f1(e.get("threshold"), 0.0)] + _v3(e.get("origin"))


def _op_vortice(e):
    # OJO con `axis`: sin declarar queda a cero, y con el eje a cero el producto
    # vectorial del operador es cero y no mueve NADA --- 9 de los 12 vortices del
    # corpus estan asi. Ponerle el eje Z (que es lo que escriben los 2 que si lo
    # declaran) los hace girar, pero en `3219398263` sale una malla de cintas
    # blancas por todo el cielo que el preview no tiene, y leer el operador como
    # velocidad en vez de como aceleracion lo empeora. Es un hilo aparte: la
    # magnitud del operador, no su eje. Se deja como estaba hasta tener con que
    # decidir.
    return [_f1(e.get("distanceinner"), 0.0), _f1(e.get("distanceouter"), 1.0),
            _f1(e.get("speedinner"), 0.0), _f1(e.get("speedouter"), 0.0)] \
        + _v3(e.get("axis"), 0.0)


OPERADORES = {
    "movement": _op_mov,
    "alphafade": _op_fade,
    "sizechange": _op_rampa,
    "alphachange": _op_rampa,
    "colorchange": _op_color,
    "oscillatealpha": lambda e: _osc(e),
    "oscillatesize": lambda e: _osc(e),
    "oscillateposition": _op_oscpos,
    "angularmovement": _op_angmov,
    "turbulence": _op_turb,
    "controlpointattract": _op_atrae,
    "vortex": _op_vortice,
}

# `rope` y `ropetrail` se aceptan pero se dibujan como sprites sueltos; ver el
# encabezado del modulo.
RENDERERS = ("sprite", "spritetrail", "rope", "ropetrail")

# `maxlength` por defecto. El valor que sale de `ComputeParticleTrailTangents`
# no son pixeles: es el largo de la estela EN ANCHOS DE SPRITE, porque
# `ComputeParticlePosition` multiplica los dos ejes por el tamano de la
# particula. Asi que 1 significa "tan larga como ancha", que es el unico
# valor por defecto que deja sano el corpus entero; ver `_estela`.
MAX_POR_DEFECTO = 1.0


# Cuantos puntos tiene la cola de una cinta y cada cuanto se muestrea, cuando
# el JSON no lo dice. `segments` solo aparece en 6 de los 66 sistemas ---con 8 y
# con 10--- y `length` en 30, casi siempre entre 0.2 y 0.5 s.
CINTA_PUNTOS = 8
CINTA_SEGUNDOS = 0.4


def _cinta(e: dict) -> tuple[int, int, float]:
    """`(modo, puntos, intervalo)` de un `rope` o un `ropetrail`.

    El modo lo lee `we_psys_load` y decide el layout del vertice; los otros dos
    son cuanta cola guarda cada particula. `subdivision` NO entra aqui: es la
    suavidad de la curva Bezier y la evalua el geometry shader, que en esta ruta
    no se usa --- los segmentos salen rectos.
    """
    modo = 1 if e.get("name") == "rope" else 2
    puntos = e.get("segments")
    puntos = int(puntos) if isinstance(puntos, (int, float)) else CINTA_PUNTOS
    puntos = max(2, min(32, puntos))
    largo = e.get("length")
    largo = float(largo) if isinstance(largo, (int, float)) else CINTA_SEGUNDOS
    return (modo, puntos, max(1.0 / 60.0, largo / puntos))


def _estela(e: dict) -> tuple[float, float, float]:
    """Los tres numeros que `ComputeParticleTrailTangents` espera en `g_RenderVar0`.

        up = normalize(v) * max(minlength, min(|v| * length, maxlength))

    y ese `up` lo escala despues el tamano de la particula, asi que las tres
    cifras son relativas a el, no pixeles.

    Reparto del corpus (145 sistemas): `length` en 131 --- mediana 0.007, con un
    grupo de 17 en 1.0 ---, `maxlength` en 68 --- de 1 a 100, mediana 6 --- y
    `minlength` en uno solo.

    Los dos valores por defecto son lecturas, no hechos, y **el que importa es
    `maxlength`**: sin tope, un sistema con `length: 1` y particulas a 250 px/s
    pide una estela de 250 anchos de sprite. Medido en *Snow perspective* de
    `2868108515`: copos de 16 px con rastros de 4092. Con el tope en 1 los tres
    grupos del corpus caen a la vez en un rango creible --- la lluvia, que
    declara `length: 0.005` y `maxlength: 100`, se queda en sus 24 px; los copos
    en 16; las brasas, en un ancho de sprite.

    `length` por defecto vale 1: los 14 sistemas que no lo declaran declaran los
    tres `maxlength: 6`, y con `length = 1` cualquier particula que se mueva
    deprisa se pega al tope, que es tener el largo fijo que dice `maxlength`.
    """
    def num(clave: str, por_defecto: float) -> float:
        v = e.get(clave)
        return float(v) if isinstance(v, (int, float)) else por_defecto

    return (num("length", 1.0), num("maxlength", MAX_POR_DEFECTO),
            num("minlength", 0.0))


def _cursor(op: dict, cursor: set[int]) -> bool:
    """El operador tira de un punto de control que mueve el CURSOR.

    `flags & 1` en un punto de control lo ata al puntero, y de las 136
    apariciones de `controlpointattract` del corpus, 106 apuntan justo a ese
    punto: el preset de luciernagas y sus derivados, que en Wallpaper Engine
    persiguen al raton.

    Sin puntero, ese punto se queda en el origen del sistema y el operador deja
    de ser una interaccion para convertirse en un sumidero: con `scale -500` y
    `drag 2.5` la velocidad terminal hacia el centro son 200 px/s, diez veces la
    turbulencia que deberia dispersarlas. La nube de 512 px de radio se
    apelotona en una bola de 64 --- que es el `threshold` --- y el wallpaper
    pierde justo el efecto por el que se puso.

    Estando el puntero fuera del fondo, lo fiel es que no atraiga nada. Cuando
    el motor en vivo sepa donde esta el puntero, este es el sitio por donde
    entra.
    """
    if op.get("name") != "controlpointattract":
        return False
    return int(_f1(op.get("controlpoint"), 0.0)) in cursor


@dataclass
class Sistema:
    maxcount: int = 32
    starttime: float = 0.0
    emisor: str = ""
    emit: list[float] = field(default_factory=list)
    cps: dict[int, list[float]] = field(default_factory=dict)
    inits: list[tuple[str, list[float]]] = field(default_factory=list)
    opers: list[tuple[str, list[float]]] = field(default_factory=list)
    material: str = ""
    renderer: str = "sprite"
    # `(length, maxlength, minlength)` de un `spritetrail`, tal como los pide
    # `g_RenderVar0`; None en los demas renderers. Ver `_estela`.
    estela: tuple[float, float, float] | None = None
    # `(modo, puntos, intervalo)` de un `rope` o un `ropetrail`; None si el
    # renderer dibuja sprites sueltos. Ver `_cinta`.
    cinta: tuple[int, int, float] | None = None
    # Recorrido de la hoja de sprites: 0 una pasada por vida, 1 un fotograma
    # fijo al azar por particula. `anim_mult` repite la secuencia.
    anim_modo: int = 0
    anim_mult: float = 1.0
    # Piezas del JSON que este modulo no sabe traducir. Se anotan para que el
    # renderizador pueda decirlo, en vez de dibujar un sistema incompleto en
    # silencio.
    sin_soporte: list[str] = field(default_factory=list)
    # Operadores que dependen del cursor y por eso quedan inactivos; ver
    # `_cursor`.
    sin_cursor: list[str] = field(default_factory=list)

    @property
    def dibujable(self) -> bool:
        return bool(self.material and self.emisor)


def cargar(res: AssetResolver, ruta: str, override: dict | None = None) -> Sistema:
    """Resuelve el JSON de un sistema de particulas.

    `override` es el `instanceoverride` del objeto que lo usa. No es un detalle:
    lo llevan 725 de los 823 objetos del corpus, porque los sistemas son
    PRESETS compartidos y cada escena los ajusta desde el editor sin tocar el
    preset. Los factores llegan hasta 200 en `count` y 50 en `lifetime`, asi que
    ignorarlos no da un resultado parecido: da uno distinto.

    Se aplican aqui, sobre los valores ya resueltos, y no en el simulador: el
    fichero `.psys` describe el sistema tal y como esta escena lo quiere, y el
    lado C no tiene que saber que existe un mecanismo de presets.
    """
    pj = res.read_json(ruta)
    s = Sistema(maxcount=int(_f1(pj.get("maxcount"), 32.0)),
                starttime=_f1(pj.get("starttime"), 0.0),
                material=pj.get("material") or "")
    ov = override if isinstance(override, dict) else {}

    # `randomframe` congela cada particula en un fotograma de la hoja en vez de
    # recorrerla: son 89 sistemas --- lluvia, escombros, petalos --- donde la
    # variedad esta entre particulas, no dentro de cada una.
    s.anim_modo = 1 if pj.get("animationmode") == "randomframe" else 0
    s.anim_mult = max(1.0, _f1(pj.get("sequencemultiplier"), 1.0))

    # Puntos de control movidos por el cursor. Ver `_cursor`.
    cursor: set[int] = set()
    for cp in pj.get("controlpoint") or []:
        if isinstance(cp, dict):
            i = int(_f1(cp.get("id"), 0.0))
            s.cps[i] = _v3(cp.get("offset"))
            if int(_f1(cp.get("flags"), 0.0)) & 1:
                cursor.add(i)

    # WE permite varios emisores; el corpus no usa ninguno con mas de uno, y
    # tomar el primero es preferible a sumarlos mal.
    for e in pj.get("emitter") or []:
        if not isinstance(e, dict):
            continue
        nombre = e.get("name", "")
        if nombre not in ("sphererandom", "boxrandom"):
            s.sin_soporte.append(f"emitter:{nombre}")
            continue
        if s.emisor:
            s.sin_soporte.append(f"emitter extra:{nombre}")
            continue
        s.emisor = nombre
        # `distancemax` es un escalar en la esfera (el radio) y un vector en la
        # caja (los tres semiejes). `_v3` reparte el escalar a los tres, que es
        # justo lo que hace falta en los dos casos.
        s.emit = ([_f1(e.get("rate"), 0.0)]
                  + _v3(e.get("distancemin"), 0.0)
                  + _v3(e.get("distancemax"), 0.0)
                  + _v3(e.get("directions"), 1.0)
                  + _v3(e.get("origin"), 0.0)
                  + _v3(e.get("sign"), 0.0)
                  + [_f1(e.get("instantaneous"), 0.0),
                     _f1(e.get("duration"), 0.0)])

    for e in pj.get("initializer") or []:
        if not isinstance(e, dict):
            continue
        fn = INICIALIZADORES.get(e.get("name", ""))
        if fn is None:
            s.sin_soporte.append(f"initializer:{e.get('name')}")
        else:
            s.inits.append((e["name"], fn(e)))

    for e in pj.get("operator") or []:
        if not isinstance(e, dict):
            continue
        fn = OPERADORES.get(e.get("name", ""))
        if fn is None:
            s.sin_soporte.append(f"operator:{e.get('name')}")
        elif _cursor(e, cursor):
            s.sin_cursor.append(e["name"])
        else:
            s.opers.append((e["name"], fn(e)))

    for e in pj.get("renderer") or []:
        if isinstance(e, dict) and e.get("name") in RENDERERS:
            s.renderer = e["name"]
            if s.renderer == "spritetrail":
                s.estela = _estela(e)
            elif s.renderer in ("rope", "ropetrail"):
                s.cinta = _cinta(e)
                # Un solo sistema del corpus pide `orientation: fixed` con un
                # eje suyo, en vez de la estela girada hacia la camara que
                # calcula `ComputeParticleTrailTangents`. Se anota en vez de
                # dibujarlo mal en silencio.
                if e.get("orientation") not in (None, "camera"):
                    s.sin_soporte.append(f"estela {e['orientation']}")
        elif isinstance(e, dict):
            s.sin_soporte.append(f"renderer:{e.get('name')}")

    _aplicar_override(s, ov)
    _ritmo_implicito(s)
    return s


def _ritmo_implicito(s: Sistema) -> None:
    """Sin `rate` declarado, el emisor mantiene el deposito lleno.

    64 sistemas de 35 escenas no declaran ritmo de emision. Tomarlo como cero
    --- que es lo que dice el JSON --- deja el sistema sin emitir NUNCA: la
    escena carga, el pase dibuja y no sale nada, sin un solo error por medio.

    La lectura razonable es que quien no fija ritmo esta controlando la densidad
    con `maxcount`: para sostener N particulas de vida media V hacen falta N/V
    nacimientos por segundo. Se calcula despues del `instanceoverride`, para que
    un `count` de 1.5 suba tambien el ritmo y la densidad salga la pedida.
    """
    if not s.emisor or s.emit[0] > 0:
        return
    vida = dict(s.inits).get("lifetimerandom")
    media = (vida[0] + vida[1]) / 2.0 if vida else 1.0
    s.emit[0] = s.maxcount / max(media, 1e-3)


def _aplicar_override(s: Sistema, ov: dict) -> None:
    """Escala el preset con los factores que declara el objeto.

    Todos son FACTORES, no valores absolutos: el rango del corpus
    --- `size` de 0.01 a 18, `count` de 0.01 a 200 --- solo tiene sentido como
    multiplicador sobre lo que trae el preset.
    """
    if not ov:
        return

    k = _f1(ov.get("count"), 1.0)
    if k != 1.0:
        s.maxcount = max(1, int(round(s.maxcount * k)))
    k = _f1(ov.get("rate"), 1.0)
    if k != 1.0 and s.emit:
        s.emit[0] *= k

    esc = {"lifetimerandom": _f1(ov.get("lifetime"), 1.0),
           "sizerandom": _f1(ov.get("size"), 1.0),
           "velocityrandom": _f1(ov.get("speed"), 1.0),
           "alpharandom": _f1(ov.get("alpha"), 1.0)}
    nuevos = []
    for nombre, vals in s.inits:
        f = esc.get(nombre, 1.0)
        if f != 1.0:
            vals = [v * f for v in vals]
        nuevos.append((nombre, vals))
    s.inits = nuevos

    # El alfa y el color son del OBJETO aunque el preset no los declare: si no
    # hay inicializador que escalar, se crea uno. En el corpus hay 345 objetos
    # con `alpha` y algunos bajan a 0.01 --- son las capas de refraccion, cuyo
    # albedo es blanco opaco a proposito y solo se ven por lo que deforman.
    tiene = {n for n, _ in s.inits}
    a = _f1(ov.get("alpha"), 1.0)
    if a != 1.0 and "alpharandom" not in tiene:
        s.inits.append(("alpharandom", [a, a]))

    # `colorn` viene normalizado y `color` de 0 a 255; los dos tinen el color
    # del preset, y `brightness` lo escala.
    tinte = _v3(ov.get("colorn"), 1.0) if ov.get("colorn") is not None else None
    if tinte is None and ov.get("color") is not None:
        tinte = [c / 255.0 for c in _v3(ov.get("color"), 255.0)]
    b = _f1(ov.get("brightness"), 1.0)
    if tinte is not None or b != 1.0:
        t = tinte or [1.0, 1.0, 1.0]
        t = [c * b for c in t]
        if "colorrandom" in tiene:
            s.inits = [(n, [v * t[i % 3] for i, v in enumerate(vals)])
                       if n == "colorrandom" else (n, vals)
                       for n, vals in s.inits]
        else:
            s.inits.append(("colorrandom", t + t))
        # `colorchange` FIJA el color, asi que el tinte tambien tiene que pasar
        # por sus dos extremos o los 55 sistemas que lo usan lo perderian. Sus
        # dos primeros floats son tiempos, no color.
        s.opers = [(n, vals[:2] + [v * t[i % 3] for i, v in enumerate(vals[2:])])
                   if n == "colorchange" else (n, vals)
                   for n, vals in s.opers]

    # `controlpointN` coloca un punto de control en coordenadas del sistema.
    for clave, valor in ov.items():
        m = re.fullmatch(r"controlpoint(\d+)", str(clave))
        if m:
            s.cps[int(m.group(1))] = _v3(valor)


def escribir(s: Sistema, destino: Path, semilla: int) -> None:
    """Vuelca el sistema al formato que lee `we_psys_load`.

    `semilla` fija la aleatoriedad: la misma escena tiene que dar el mismo PNG
    en dos ejecuciones o la regresion no vale para nada.
    """
    def num(v: float) -> str:
        return f"{v:.6g}"

    lineas = [f"# generado por tools/weparticles.py",
              f"maxcount {s.maxcount}",
              f"starttime {num(s.starttime)}",
              f"seed {semilla & 0x7fffffff}",
              f"anim {s.anim_modo} {num(s.anim_mult)}"]
    if s.cinta:
        lineas.append(f"cinta {s.cinta[0]} {s.cinta[1]} {num(s.cinta[2])}")
    if s.emisor:
        lineas.append(f"emit {s.emisor} " + " ".join(num(v) for v in s.emit))
    for i, off in sorted(s.cps.items()):
        lineas.append(f"cp {i} " + " ".join(num(v) for v in off))
    for nombre, vals in s.inits:
        lineas.append(f"init {nombre} " + " ".join(num(v) for v in vals))
    for nombre, vals in s.opers:
        lineas.append(f"oper {nombre} " + " ".join(num(v) for v in vals))
    destino.write_text("\n".join(lineas) + "\n")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    res = AssetResolver.for_wallpaper(Path(sys.argv[1]), wepaths.we_assets())
    data = res.read_json("scene.json")
    n = 0
    for o in data.get("objects", []):
        if not o.get("particle"):
            continue
        n += 1
        try:
            s = cargar(res, o["particle"], o.get("instanceoverride"))
        except SceneError as e:
            print(f"  {o.get('name')!r}: {e}")
            continue
        print(f"  {o.get('name')!r:32} {s.emisor or '(sin emisor)':<14} "
              f"max={s.maxcount:<5} t0={s.starttime:<5g} {s.renderer}")
        print(f"      init: {', '.join(k for k, _ in s.inits) or '-'}")
        print(f"      oper: {', '.join(k for k, _ in s.opers) or '-'}")
        if s.sin_soporte:
            print(f"      sin soporte: {', '.join(s.sin_soporte)}")
    print(f"\nsistemas de particulas: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
