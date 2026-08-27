#!/usr/bin/env python3
"""Grafo de escena de Wallpaper Engine: parseo y aplanado a plan de render.

Una escena no es una lista de capas: es un grafo de render con recursos
nombrados. La cadena de indirecciones para pintar una sola imagen es

    scene.json  objects[].image = "models/X.json"
      -> model.material         = "materials/X.json"
        -> material.passes[].shader   -> shaders/<name>.vert + .frag
        -> material.passes[].textures -> materials/<name>.tex
        -> material.passes[].combos   -> variantes del shader

y encima cada objeto lleva una cadena de efectos, donde cada efecto es a su
vez una lista de pases con render target y bindings de entrada:

    objects[].effects[].file = "effects/vhs/effect.json"
      -> effect.passes[].material -> igual que arriba
      -> effect.passes[].target   -> "_rt_..." (buffer intermedio)
      -> effect.passes[].bind     -> [{name, index}] de donde vienen las entradas

Los `passes` que trae el objeto en scene.json no son los pases: son
*overrides* posicionales sobre los del effect.json (combos,
constantshadervalues y texturas). Confundirlos es el error facil.

Este modulo resuelve todo eso a una lista plana de RenderPass. No simula
particulas ni reproduce audio: eso son subsistemas aparte.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
from pkg_inspect import read_pkg


class SceneError(Exception):
    pass


@dataclass
class AssetResolver:
    """Sistema de ficheros virtual: primero el paquete, luego los assets de WE.

    Un wallpaper puede traer su propia version de cualquier asset compartido,
    asi que el paquete siempre gana.
    """
    entries: dict[str, bytes] = field(default_factory=dict)
    roots: list[Path] = field(default_factory=list)
    # Una escena referencia el mismo shader o material una vez por pase: el
    # Warwick usa shine_gaussian cuatro veces. Sin cache se releen y
    # redecodifican todos, y en el barrido de las 125 escenas se nota.
    _text: dict[str, str] = field(default_factory=dict, repr=False)
    _json: dict[str, dict] = field(default_factory=dict, repr=False)

    @classmethod
    def for_wallpaper(cls, wallpaper_dir: Path, we_assets: Path) -> AssetResolver:
        entries: dict[str, bytes] = {}
        pkg = wallpaper_dir / "scene.pkg"
        if pkg.is_file():
            _, items = read_pkg(pkg)
            entries = {e["name"]: e["data"] for e in items}
        return cls(entries=entries, roots=[wallpaper_dir, we_assets])

    def read_bytes(self, name: str) -> bytes:
        name = name.lstrip("/")
        if name in self.entries:
            return self.entries[name]
        for root in self.roots:
            p = root / name
            if p.is_file():
                return p.read_bytes()
        raise SceneError(f"asset sin resolver: {name!r}")

    def read_text(self, name: str) -> str:
        cached = self._text.get(name)
        if cached is None:
            cached = self.read_bytes(name).decode("utf-8", "replace")
            self._text[name] = cached
        return cached

    def read_json(self, name: str) -> dict:
        cached = self._json.get(name)
        if cached is not None:
            return cached
        try:
            parsed = json.loads(self.read_text(name))
        except json.JSONDecodeError as e:
            raise SceneError(f"json invalido en {name!r}: {e}") from e
        self._json[name] = parsed
        return parsed

    def exists(self, name: str) -> bool:
        try:
            self.read_bytes(name)
            return True
        except SceneError:
            return False


def texture_path(name: str) -> str:
    """Los materiales nombran texturas sin ruta ni extension."""
    return f"materials/{name}.tex"


def shader_paths(name: str) -> tuple[str, str]:
    return f"shaders/{name}.vert", f"shaders/{name}.frag"


@dataclass
class RenderPass:
    """Un pase ya resuelto: todo lo necesario para crear un programa GL.

    No todos los pases son de shader. Los que traen `command` (por ahora solo
    "copy") son un blit entre render targets y no tienen programa asociado.
    """
    owner: str                       # objeto al que pertenece
    stage: str                       # "base" o el nombre del efecto
    shader: str
    vert: str
    frag: str
    command: str | None = None
    source: str | None = None
    combos: dict[str, object] = field(default_factory=dict)
    constants: dict[str, object] = field(default_factory=dict)
    textures: list[str | None] = field(default_factory=list)
    target: str | None = None        # None = escribe al buffer del objeto
    binds: list[dict] = field(default_factory=list)
    blending: str = "normal"
    cullmode: str = "nocull"
    depthtest: str = "disabled"


@dataclass
class SceneObject:
    id: int
    name: str
    kind: str                        # image | particle | text | sound | light | model
    visible: object = True
    origin: str = ""
    angles: str = ""
    scale: str = ""
    parallax_depth: str = ""
    passes: list[RenderPass] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    # El objeto no se compone sobre la escena: se dibuja para dejar su
    # resultado en `_rt_imageLayerComposite_<id>_a|_b`, donde OTRA capa lo
    # muestrea. Ver `ids_compuestos`.
    solo_buffer: bool = False


@dataclass
class Scene:
    general: dict
    camera: dict
    objects: list[SceneObject] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)

    @property
    def render_passes(self) -> list[RenderPass]:
        return [p for o in self.objects for p in o.passes]


def _refrescar_valores_de_usuario(nodo, properties: dict) -> None:
    """Pone al dia la copia de todo campo atado a una propiedad configurable.

    Un campo del `scene.json` puede venir como
    `{"user": "neon_2", "value": "1 0 0"}`. El `value` NO es el valor: es la
    copia que el campo tenia cuando el autor guardo, y quien manda es la
    propiedad del `project.json`. `is_visible` ya lo sabia para `visible`; el
    resto de campos ---colores, alfas, escalas y sobre todo las constantes de
    los materiales--- seguian leyendo la copia.

    No es un detalle. En el corpus hay 450 campos atados a una propiedad y
    **92 con la copia desfasada**, repartidos en 22 escenas. El caso que se ve
    a simple vista es `1518454472`: sus contornos de neon declaran
    `{"user": "neon_2", "value": "1 0 0"}` con `neon_2` en `0 1 1`, asi que la
    Miku salia ROJA donde su preview es CIAN --- el color complementario, que
    es lo que delata que no es un problema de brillo sino de leer el campo
    equivocado.

    Se sustituye solo la copia y se deja el resto del objeto intacto, para que
    quien lea `user` ---`is_visible`--- siga viendo lo mismo. Si `user` no
    nombra una propiedad conocida, la copia se queda: es lo que el autor tenia
    en pantalla, y hay wallpapers donde `user` es a su vez un objeto.
    """
    if isinstance(nodo, dict):
        clave = nodo.get("user")
        if isinstance(clave, str) and "value" in nodo:
            prop = properties.get(clave)
            if isinstance(prop, dict) and "value" in prop:
                nodo["value"] = prop["value"]
        for v in nodo.values():
            _refrescar_valores_de_usuario(v, properties)
    elif isinstance(nodo, list):
        for v in nodo:
            _refrescar_valores_de_usuario(v, properties)


def _valor_animado(anim: dict, t: float):
    """El valor de una curva de fotogramas clave en el segundo `t`.

    Devuelve una lista de floats, un canal por componente: `c0`, `c1`, `c2`
    son la x, la y y la z de un `origin`, o el unico canal de un `alpha`.
    Devuelve None si la curva no se entiende.

    La interpolacion es LINEAL. Los fotogramas clave traen ademas tiradores de
    bezier en `front` y `back`, y no se usan: sobre curvas de fundido ---que es
    para lo que sirven en este corpus--- la diferencia es la forma de la rampa,
    no si acaba encendida o apagada.
    """
    op = anim.get("options") or {}
    fps = float(op.get("fps") or 30.0)
    largo = float(op.get("length") or 0.0)
    modo = str(op.get("mode") or "single")

    f = t * fps
    if largo > 0.0:
        if modo == "loop":
            f = f % largo
        elif modo == "mirror":
            f = f % (2.0 * largo)
            if f > largo:
                f = 2.0 * largo - f
        else:                       # "single" y cualquier otro: se queda al final
            f = min(f, largo)

    fuera: list[float] = []
    for nombre in sorted(k for k in anim if k != "options"):
        claves = anim[nombre]
        if not isinstance(claves, list) or not claves:
            return None
        try:
            puntos = sorted((float(k["frame"]), float(k["value"])) for k in claves)
        except (KeyError, TypeError, ValueError):
            return None
        if f <= puntos[0][0]:
            fuera.append(puntos[0][1])
            continue
        if f >= puntos[-1][0]:
            fuera.append(puntos[-1][1])
            continue
        for (f0, v0), (f1, v1) in zip(puntos, puntos[1:]):
            if f0 <= f <= f1:
                k = 0.0 if f1 == f0 else (f - f0) / (f1 - f0)
                fuera.append(v0 + (v1 - v0) * k)
                break
    return fuera or None


def _evaluar_animaciones(nodo, t: float) -> None:
    """Pone al dia la copia de todo campo animado, al segundo `t`.

    Igual que con las propiedades del usuario, `value` es una COPIA: la que el
    campo tenia en el instante en que el autor guardo la escena, que no tiene
    por que ser el valor de reposo. Un telon de entrada lo demuestra:
    `3577990983` trae una capa de color solido negro cuyo `alpha` va de 1 a 0
    en 90 fotogramas ---un fundido de tres segundos--- y guardada en el 1. Sin
    evaluar la curva esa capa se queda OPACA para siempre y tapa el wallpaper
    entero: la escena salia negra menos un ramo de flores que se dibuja encima.

    El plan se genera para un instante, asi que esto no reproduce la animacion:
    la congela donde toque. Para el modo `single`, que es el de los fundidos de
    entrada y dos de cada tres curvas del corpus, congelar despues de su
    duracion ES el valor definitivo. Los modos `loop` y `mirror` quedan en el
    instante del plan, que es exactamente lo que un plan estatico puede dar.
    """
    if isinstance(nodo, dict):
        anim = nodo.get("animation")
        if isinstance(anim, dict) and "value" in nodo:
            vals = _valor_animado(anim, t)
            if vals is not None:
                nodo["value"] = (vals[0] if len(vals) == 1 and
                                 not isinstance(nodo["value"], str)
                                 else " ".join(f"{v:.6g}" for v in vals))
        for v in nodo.values():
            _evaluar_animaciones(v, t)
    elif isinstance(nodo, list):
        for v in nodo:
            _evaluar_animaciones(v, t)


def _visibilidad_heredada(data: dict, properties: dict) -> dict[int, bool]:
    """Por objeto, si se dibuja mirando TODA su cadena de padres.

    Apagar un grupo apaga lo que cuelga de el, que es para lo que sirve
    agrupar. Mirando solo el campo `visible` de cada objeto se dibujan capas
    que el autor dejo escondidas dentro de un grupo apagado.

    No es un caso raro: Lonely Cat (`3299228616`) trae la escena entera SEIS
    veces, una por idioma, y apaga cinco por el padre. Sus hijos ---campos de
    estrellas, destellos, la ondulacion del agua--- no dicen nada de si se ven,
    asi que se dibujaban los seis juegos: 107 objetos de mas sobre 18 que
    debian verse, y de ahi la nevada de puntos blancos que su preview no tiene.
    En el corpus son 150 objetos de mas repartidos en 4 escenas.

    Devuelve un mapa por `id()` del diccionario crudo y no por el campo `id`,
    porque hay escenas que repiten identificadores.
    """
    por_id = {str(o.get("id")): o for o in data.get("objects", [])}
    fuera: dict[int, bool] = {}
    for o in data.get("objects", []):
        cur, visto, ve = o, set(), True
        while cur is not None and id(cur) not in visto:
            visto.add(id(cur))
            if not is_visible(cur.get("visible", True), properties):
                ve = False
                break
            padre = cur.get("parent")
            cur = por_id.get(str(padre)) if padre else None
        fuera[id(o)] = ve
    return fuera


def is_visible(value, properties: dict) -> bool:
    """Resuelve el campo `visible` de un objeto o de un efecto.

    Puede ser un bool, o `{"user": "propiedad", "value": X}`: la capa solo se
    dibuja si esa propiedad configurable del wallpaper vale lo indicado. Sin
    esto se dibujan capas y efectos que el autor dejo apagados.
    """
    if not isinstance(value, dict):
        return value is None or bool(value)

    # `value` NO es una condicion contra la que comparar: es una copia del
    # valor que tenia la propiedad al guardar la escena. Quien manda es la
    # propiedad. Leerlo como condicion invierte el resultado justo cuando la
    # copia vale false: en el wallpaper de Asuka, la capa `Fullscreen` declara
    # {"user": "flare", "value": false} con `flare` apagado, y se dibujaba
    # precisamente por estar apagada -- un velo de destellos sobre la escena.
    #
    # `user` no siempre es el nombre de una propiedad: en algunos wallpapers
    # es a su vez un objeto. Ante cualquier forma que no se entienda se usa la
    # copia, que es lo que el autor tenia en pantalla al guardar.
    key = value.get("user")
    copia = bool(value.get("value", True))
    if not isinstance(key, str):
        return copia
    prop = properties.get(key)
    if not isinstance(prop, dict) or "value" not in prop:
        return copia
    return bool(prop["value"])


def _object_kind(o: dict) -> str:
    """Tipo del objeto, por el primer campo con VALOR, no con clave.

    Un sistema de particulas se declara con `image: null`, `model: null` y
    `particle: "..."` a la vez. Mirar solo si la clave existe lo clasifica como
    imagen vacia y pierde la particula.
    """
    for k in ("image", "particle", "sound", "light", "model", "text"):
        if o.get(k):
            return k
    return "unknown"


def _load_material(res: AssetResolver, path: str) -> list[dict]:
    """Devuelve los pases declarados por un material."""
    mat = res.read_json(path)
    return mat.get("passes", [])


def _make_pass(res: AssetResolver, owner: str, stage: str, mp: dict,
               override: dict | None, target: str | None,
               binds: list[dict]) -> RenderPass:
    shader = mp.get("shader")
    if not shader:
        raise SceneError(f"pase sin shader en {owner}/{stage}")
    vpath, fpath = shader_paths(shader)

    combos = dict(mp.get("combos") or {})
    constants = dict(mp.get("constantshadervalues") or {})
    textures = list(mp.get("textures") or [])

    # El override del objeto pisa lo que declara el material.
    if override:
        combos.update(override.get("combos") or {})
        constants.update(override.get("constantshadervalues") or {})
        if override.get("textures"):
            ov = override["textures"]
            textures = list(ov) + textures[len(ov):]

    return RenderPass(
        owner=owner, stage=stage, shader=shader,
        vert=res.read_text(vpath),
        frag=res.read_text(fpath),
        combos=combos, constants=constants, textures=textures,
        target=target, binds=binds,
        blending=mp.get("blending", "normal"),
        cullmode=mp.get("cullmode", "nocull"),
        depthtest=mp.get("depthtest", "disabled"),
    )


COMPOSITE_RT_RE = re.compile(r"^_rt_imageLayerComposite_(\d+)_[ab]$")


def _ids_de_composicion(data: dict) -> set[str]:
    """Ids de capas cuyo buffer de composicion lee OTRA capa.

    Se recorre la escena en crudo, no una lista escrita a mano: cualquier
    wallpaper que use el mecanismo queda cubierto sin tocar el codigo. Se
    excluyen las autorreferencias, que significan otra cosa --- el par
    ping-pong del propio objeto --- y que el ejecutor ya resuelve.
    """
    fuera: set[str] = set()
    for o in data.get("objects", []):
        mio = str(o.get("id"))
        for eff in o.get("effects", []) or []:
            if not isinstance(eff, dict):
                continue
            for p in eff.get("passes", []) or []:
                if not isinstance(p, dict):
                    continue
                for t in p.get("textures", []) or []:
                    m = COMPOSITE_RT_RE.match(t) if isinstance(t, str) else None
                    if m and m.group(1) != mio:
                        fuera.add(m.group(1))
    return fuera


def load_scene(res: AssetResolver, strict: bool = False,
               tiempo: float | None = None) -> Scene:
    data = res.read_json("scene.json")
    scene = Scene(general=data.get("general", {}), camera=data.get("camera", {}))

    # Las propiedades configurables del wallpaper deciden que capas y efectos
    # estan activos.
    try:
        props = res.read_json("project.json").get("general", {}).get("properties", {})
    except SceneError:
        props = {}
    scene.properties = props or {}
    _refrescar_valores_de_usuario(data, scene.properties)
    if tiempo is not None:
        _evaluar_animaciones(data, tiempo)

    # Capas que otra capa muestrea por su buffer de composicion.
    #
    # Un efecto puede leer `_rt_imageLayerComposite_<id>_a|_b`. Cuando el id es
    # el del propio objeto se refiere a su par ping-pong, que el ejecutor ya
    # mantiene --- 86 de las 122 referencias del corpus son de estas. Pero
    # cuando apunta a OTRO objeto es una capa de composicion leyendo a sus
    # fuentes, y esas fuentes suelen estar marcadas invisibles: son 36
    # referencias en 9 escenas, 33 de ellas a capas ocultas.
    #
    # Descartarlas por invisibles dejaba el buffer vacio y la composicion en
    # negro: es lo que hacia que en Cyberpunk Edgerunners-Lucy no hubiera
    # Tierra, aunque sus tres capas --- textura, nubes y cara oculta --- esten
    # ahi y bien colocadas.
    ids_compuestos = _ids_de_composicion(data)
    visible_de = _visibilidad_heredada(data, scene.properties)

    for o in data.get("objects", []):
        kind = _object_kind(o)
        obj = SceneObject(
            id=o.get("id", -1), name=o.get("name", ""), kind=kind,
            visible=o.get("visible", True), origin=o.get("origin", ""),
            angles=o.get("angles", ""), scale=o.get("scale", ""),
            parallax_depth=o.get("parallaxDepth", ""), raw=o,
        )
        if not visible_de[id(o)]:
            # Invisible pero muestreada por otra capa: hay que construir sus
            # pases igual. No se compone sobre la escena, solo llena su buffer.
            if str(o.get("id")) in ids_compuestos:
                obj.solo_buffer = True
                scene.objects.append(obj)
            else:
                obj.kind = "oculto"
                scene.objects.append(obj)
                continue
        else:
            scene.objects.append(obj)

        def note(msg: str) -> None:
            if strict:
                raise SceneError(msg)
            scene.unresolved.append(msg)

        # ── pase base: solo los objetos con geometria lo tienen ──
        if kind == "image":
            # `image` puede venir a null: son objetos que existen en la escena
            # como contenedor pero no dibujan geometria propia.
            try:
                if not o.get("image"):
                    raise SceneError("el objeto no declara modelo")
                model = res.read_json(o["image"])
                # El recorte vive en el modelo, no en el objeto: WE recorta la
                # textura a su caja minima y guarda cuanto se desplazo.
                if model.get("cropoffset"):
                    o["_cropoffset"] = model["cropoffset"]
                # `passthrough` marca las capas de utilidad --- composelayer,
                # fullscreenlayer, projectlayer --- que operan sobre el
                # fotograma entero y no sobre su rectangulo.
                if model.get("passthrough"):
                    o["_passthrough"] = True
                if not model.get("material"):
                    raise SceneError(f"modelo sin material: {o['image']!r}")
                for mp in _load_material(res, model["material"]):
                    obj.passes.append(_make_pass(res, obj.name, "base", mp,
                                                 None, None, []))
            except SceneError as e:
                note(f"[{obj.name}] base: {e}")

        elif kind == "particle":
            # Un sistema de particulas llega al material por su propio JSON en
            # vez de por un modelo, pero de ahi en adelante es un pase normal:
            # los 823 sistemas del corpus usan el mismo shader,
            # `genericparticle`. Lo que cambia es la GEOMETRIA --- la generan
            # los vertices que simula `weparticles`, no un quad --- y eso se
            # decide en el renderizador, no aqui.
            try:
                pdef = res.read_json(o["particle"])
                if not pdef.get("material"):
                    raise SceneError(f"sistema sin material: {o['particle']!r}")
                for mp in _load_material(res, pdef["material"]):
                    obj.passes.append(_make_pass(res, obj.name, "base", mp,
                                                 None, None, []))
            except SceneError as e:
                note(f"[{obj.name}] particulas: {e}")

        elif kind == "text":
            # Una capa de texto no nombra material: WE elige uno de
            # `materials/fonts/` segun como este hecha la fuente. Se toma
            # `basefont`, que es el camino de rasterizado corriente ---
            # `g_Texture0` trae la cobertura y el shader la usa de alfa sobre
            # `g_Color4` ---, porque el atlas lo fabricamos nosotros y no es un
            # campo de distancias. Los otros cinco materiales son variantes:
            # MSDF, fuente en color y las dos con profundidad.
            #
            # El fondo opaco (`fontbackground`, shader `flat`) se queda fuera a
            # proposito: en el corpus `opaquebackground` es falso o no esta en
            # los 167 objetos, asi que ese pase no lo pide nadie.
            #
            # La GEOMETRIA la pone el renderizador, como en las particulas: son
            # los quads de las lineas ya rasterizadas, y el atlas se enlaza en
            # `g_Texture0` sin pasar por el material.
            try:
                for mp in _load_material(res, "materials/fonts/basefont.json"):
                    obj.passes.append(_make_pass(res, obj.name, "base", mp,
                                                 None, None, []))
            except SceneError as e:
                note(f"[{obj.name}] texto: {e}")

        # ── cadena de efectos ──
        for eff in o.get("effects", []):
            if not is_visible(eff.get("visible", True), scene.properties):
                continue
            fname = eff.get("file", "")
            ename = fname.split("/")[1] if "/" in fname else fname
            try:
                edef = res.read_json(fname)
            except SceneError as e:
                note(f"[{obj.name}] efecto {ename}: {e}")
                continue

            # Los overrides del objeto son posicionales sobre effect.passes.
            overrides = eff.get("passes") or []

            # Los FBO marcados `"unique": true` se instancian por objeto: el
            # effect.json los nombra en generico (`_rt_FullCompoBuffer1`) pero
            # el scene.json referencia la instancia con los ids pegados
            # (`_rt_FullCompoBuffer1_128_145`). Sin traducir entre los dos, un
            # efecto temporal escribe en un buffer y lee de otro, y su historia
            # se queda vacia para siempre.
            instanced = {n for ov in overrides
                         for n in (ov.get("textures") or [])
                         if isinstance(n, str) and n.startswith("_rt_")}
            alias: dict[str, str] = {}
            for fbo in edef.get("fbos", []):
                if not fbo.get("unique"):
                    continue
                g = fbo.get("name", "")
                for i in instanced:
                    if i.startswith(g + "_"):
                        alias[g] = i
                        break

            def rt(name: str | None) -> str | None:
                return alias.get(name, name) if name else name
            for i, ep in enumerate(edef.get("passes", [])):
                ov = overrides[i] if i < len(overrides) else None

                if "command" in ep:
                    obj.passes.append(RenderPass(
                        owner=obj.name, stage=ename, shader="", vert="", frag="",
                        command=ep["command"], source=rt(ep.get("source")),
                        target=rt(ep.get("target"))))
                    continue

                try:
                    for mp in _load_material(res, ep["material"]):
                        binds = [{**b, "name": rt(b.get("name"))}
                                 for b in (ep.get("bind") or [])]
                        obj.passes.append(_make_pass(
                            res, obj.name, ename, mp, ov,
                            rt(ep.get("target")), binds))
                except SceneError as e:
                    note(f"[{obj.name}] efecto {ename} pase {i}: {e}")

    return scene


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    we = wepaths.we_assets()
    res = AssetResolver.for_wallpaper(Path(sys.argv[1]), we)
    scene = load_scene(res)

    print(f"objetos: {len(scene.objects)}   pases de render: {len(scene.render_passes)}")
    for o in scene.objects:
        print(f"  {o.kind:<9} {o.name!r}  pases={len(o.passes)}")
        for p in o.passes:
            tex = ", ".join(t or "<bind>" for t in p.textures) or "-"
            tgt = f" -> {p.target}" if p.target else ""
            print(f"      {p.stage:<14} {p.shader:<34} [{tex}]{tgt}")
    if scene.unresolved:
        print(f"\nsin resolver ({len(scene.unresolved)}):")
        for u in scene.unresolved[:10]:
            print(f"  {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
