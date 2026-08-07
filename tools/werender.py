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
    cc -O2 -o /tmp/glexec tools/glexec.c -lEGL -lGL
    python3 tools/werender.py <dir_wallpaper> <salida.png> [--time 0.0]
                              [--only-base] [--exec /tmp/glexec]
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import wemdl
import wepaths
import wescene
import weshader
import wetex
from wescene import AssetResolver, SceneError, load_scene

IDENTITY = [1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]


def object_mvp(obj, canvas: tuple[int, int], mesh: bool = False) -> list[float]:
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
    origin = (_floats(obj.raw.get("origin")) + [w / 2, h / 2, 0])[:3]
    scale = (_floats(obj.raw.get("scale")) + [1.0, 1.0, 1.0])[:3]
    size = (_floats(obj.raw.get("size")) + [float(w), float(h)])[:2]
    angles = (_floats(obj.raw.get("angles")) + [0.0, 0.0, 0.0])[:3]

    # Semiextension y centro, normalizados a clip space (-1..1).
    if mesh:
        sx = 2.0 * scale[0] / w
        sy = 2.0 * scale[1] / h
    else:
        sx = size[0] * scale[0] / w
        sy = size[1] * scale[1] / h
    crop = (_floats(obj.raw.get("_cropoffset")) + [0.0, 0.0])[:2] if APPLY_CROP else [0.0, 0.0]
    tx = 2.0 * (origin[0] + crop[0]) / w - 1.0
    ty = 2.0 * (origin[1] + crop[1]) / h - 1.0

    c = math.cos(angles[2])
    s = math.sin(angles[2])
    # Rotacion en Z antes de la escala; los angulos vienen en radianes.
    return [ sx * c, -sy * s, 0.0, tx,
             sx * s,  sy * c, 0.0, ty,
             0.0,     0.0,    1.0, 0.0,
             0.0,     0.0,    0.0, 1.0]

def layer_size(obj, canvas: tuple[int, int]) -> tuple[float, float]:
    """Tamano del rectangulo de la capa en pixeles, sin escala ni colocacion."""
    size = (_floats(obj.raw.get("size")) + [float(canvas[0]), float(canvas[1])])[:2]
    return max(size[0], 1.0), max(size[1], 1.0)


APPLY_CROP = bool(int(os.environ.get("WE_APPLY_CROP", "0")))

COMPOSITE_RT_RE = re.compile(r"^_rt_imageLayerComposite_\d+_[ab]$")


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
        self.mesh_files: list[Path] = []
        self.notes: list[str] = []
        self.stats = {"pases": 0, "sin_shader": 0, "sin_textura": 0,
                      "puppet": 0, "puppet_omitido": 0, "puppet_animado": 0}
        self.dump_dir: Path | None = None
        self._tex_dims: dict[int, tuple[int, int]] = {}

    # ── texturas ──────────────────────────────────────────────────────────
    def texture(self, name: str, mode: str = "") -> tuple[int, int, int] | None:
        """Decodifica una textura a RGBA cruda y devuelve (id, ancho, alto).

        `mode` es el modo que declara el sampler en sus metadatos. Los mapas
        `flowmask` codifican un VECTOR de arrastre por pixel: RG - 0.498 son
        (dx, dy) en convencion de WE, con v hacia abajo. Nuestro buffer vive
        con v hacia arriba, asi que ademas de recolocar el mapa (eso lo hace
        el volteo comun) hay que invertir el VALOR de su componente vertical:
        sin ello el parpado de Jeanne -- un `shake` cuyo flujo tira del
        parpado -- arrastraba hacia arriba y el gesto salia al reves.
        """
        clave = (name, mode == "flowmask")
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

        # glReadPixels y las UV de GL van de abajo a arriba; las texturas de WE
        # se guardan con el origen arriba. Se voltea al subir, una sola vez.
        rgba = np.ascontiguousarray(rgba[::-1])
        if mode == "flowmask":
            # G' espeja G alrededor del centro 0.498 (127 en 8 bits).
            rgba = rgba.copy()
            rgba[:, :, 1] = 254 - rgba[:, :, 1]
        i = len(self.tex_ids)
        path = self.tmp / f"tex{i:03d}.rgba"
        path.write_bytes(rgba.tobytes())
        self.tex_ids[clave] = i
        self._tex_dims[i] = (rgba.shape[1], rgba.shape[0])
        self.lines.append(f"tex {i} {path} {rgba.shape[1]} {rgba.shape[0]}")
        return i, rgba.shape[1], rgba.shape[0]


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

        self.stats["puppet_animado"] += 1
        return MeshAnim(nb, keys, float(a.duration),
                        (idx16.tobytes(), pesos.tobytes(), mats.tobytes()))

    def emit_pass(self, p, sresolver, canvas: tuple[int, int], obj=None) -> None:
        # Los metadatos del shader dicen que uniform se enlaza con que
        # propiedad del material, y con que valor por defecto.
        meta = weshader.parse_uniform_meta(weshader.normalise_newlines(p.frag))
        meta.update(weshader.parse_uniform_meta(weshader.normalise_newlines(p.vert)))

        # Un combo declarado en los metadatos de un sampler se activa cuando
        # ese slot esta realmente enlazado en el pase. Sin esto la mascara de
        # un efecto se ignora y el efecto se aplica a la imagen entera: el
        # `pulse` de la escena de referencia hacia oscilar el brillo del
        # wallpaper completo casi al doble en vez de solo la zona enmascarada.
        combos = dict(p.combos)
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
            vert = weshader.translate(p.vert, "vert", sresolver, combos=combos)
            frag = weshader.translate(p.frag, "frag", sresolver, combos=combos)
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
        self.body.append(f"blend {p.blending if p.stage == 'base' else 'none'}")

        bind_by_index = {b["index"]: b["name"] for b in p.binds}
        for slot in range(8):
            uni = f"g_Texture{slot}"
            name = p.textures[slot] if slot < len(p.textures) else None
            src = None
            if name:
                if COMPOSITE_RT_RE.match(name):
                    # `_rt_imageLayerComposite_<id>_a|_b` no es un buffer
                    # cualquiera: es el par ping-pong del propio objeto, que el
                    # ejecutor ya mantiene. Crearlo como buffer nuevo lo deja
                    # vacio y cualquier efecto que combine con el da negro.
                    src = "prev"
                elif name.startswith("_rt_"):
                    src = f"rt:{name}"
                else:
                    modo = str(meta.get(uni, {}).get("mode", ""))
                    t = self.texture(name, modo)
                    if t:
                        src = f"tex:{t[0]}"
                        self.body.append(
                            f"u4f g_Texture{slot}Resolution {t[1]} {t[2]} {t[1]} {t[2]}")
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
        if obj is not None and p.stage == "base" and mesh_id is not None:
            sw, sh = layer_size(obj, canvas)
            mvp = [2.0 / sw, 0, 0, 0,  0, 2.0 / sh, 0, 0,
                   0, 0, 1, 0,  0, 0, 0, 1]
        else:
            mvp = IDENTITY
        self.body.append("umat4 g_ModelViewProjectionMatrix " +
                         " ".join(f"{x:.6g}" for x in mvp))
        self.body.append("u1f g_Time @TIME@")
        self.body.append(f"u3f g_Screen {canvas[0]} {canvas[1]} "
                         f"{canvas[0] / max(1, canvas[1])}")
        self.body.append("u4f g_Texture0Rotation 1 0 0 1")
        self.body.append("u2f g_Texture0Translation 0 0")
        self.body.append("u4f g_Color4 1 1 1 1")
        self.body.append("u1f g_Brightness 1")
        self.body.append("u1f g_UserAlpha 1")
        self.body.append("u1f g_Alpha 1")

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

    def _build(self, max_passes: int | None) -> tuple[int, int]:
        scene = load_scene(self.res)
        general = scene.general
        proj = general.get("orthogonalprojection")
        canvas = ((int(proj["width"]), int(proj["height"]))
                  if isinstance(proj, dict) else (1920, 1080))
        self.lines.append(f"canvas {canvas[0]} {canvas[1]}")
        # Instante al que deformar las mallas. Solo lo usa glexec, que no
        # tiene reloj propio: el motor en vivo pasa su tiempo real.
        self.lines.append(f"meshtime {self.time:.6f}")
        we = wepaths.we_assets()
        sresolver = weshader.Resolver(
            overlay=self.res.entries, roots=[we, we / "shaders"])
        for obj in scene.objects:
            if obj.kind != "image" or not obj.passes:
                continue
            self._emit_mesh(obj)
            # Marca de inicio de objeto. El ejecutor la usa para componer el
            # objeto anterior sobre la escena en vez de pisarlo. `copybackground`
            # dice si este objeto arranca desde una copia de lo que hay detras
            # (lo que necesitan las capas de post-proceso) o desde vacio.
            copybg = 1 if obj.raw.get("copybackground") else 0
            place = " ".join(f"{x:.6g}" for x in object_mvp(obj, canvas))
            self.body.append(f"object {copybg} {place}")
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
                if max_passes is not None and self.stats["pases"] >= max_passes:
                    break
                self.emit_pass(p, sresolver, canvas, obj)
        self.stats["canvas"] = canvas
        return canvas

    def render(self, out_png: Path, only_base: bool = False,
               max_passes: int | None = None, frames: int = 1) -> dict:
        scene = load_scene(self.res)
        general = scene.general
        canvas = (int(_floats(general.get("orthogonalprojection", {}).get("width", 1920))[0]),
                  int(_floats(general.get("orthogonalprojection", {}).get("height", 1080))[0])) \
            if isinstance(general.get("orthogonalprojection"), dict) else (1920, 1080)

        self.lines.append(f"canvas {canvas[0]} {canvas[1]}")
        # Instante al que deformar las mallas. Solo lo usa glexec, que no
        # tiene reloj propio: el motor en vivo pasa su tiempo real.
        self.lines.append(f"meshtime {self.time:.6f}")

        we = wepaths.we_assets()
        sresolver = weshader.Resolver(
            overlay=self.res.entries,
            roots=[we, we / "shaders"])

        for obj in scene.objects:
            if obj.kind != "image" or not obj.passes:
                continue
            self._emit_mesh(obj)
            # Marca de inicio de objeto. El ejecutor la usa para componer el
            # objeto anterior sobre la escena en vez de pisarlo. `copybackground`
            # dice si este objeto arranca desde una copia de lo que hay detras
            # (lo que necesitan las capas de post-proceso) o desde vacio.
            copybg = 1 if obj.raw.get("copybackground") else 0
            place = " ".join(f"{x:.6g}" for x in object_mvp(obj, canvas))
            self.body.append(f"object {copybg} {place}")
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

        raw = self.tmp / "out.rgba"

        # Los efectos temporales (motion blur) acumulan entre fotogramas: en
        # una sola pasada su buffer de historia esta vacio por definicion y el
        # resultado sale oscurecido. Repetir el plan deja que converjan, que es
        # lo que pasa en ejecucion real. Los render targets se crean una vez y
        # persisten entre repeticiones, asi que basta con repetir los pases.
        plan_lines = list(self.lines)
        for i in range(max(1, frames)):
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


def emit_plan(wallpaper: Path, out_dir: Path) -> dict:
    """Escribe el plan como plantilla, con @TIME@ sin sustituir.

    Es la interfaz con el motor en C++: Python resuelve el grafo, traduce los
    shaders y decodifica las texturas una vez; el ejecutor de C++ repite ese
    mismo plan cada fotograma poniendo el tiempo que toque. Los assets se
    copian junto al plan para que no dependa de un directorio temporal.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    r = Renderer(wallpaper, Path("/nonexistent"), 0.0)
    canvas = r._build(None)

    remap: dict[str, str] = {}
    for src in sorted(r.tmp.iterdir()):
        if src.suffix in (".rgba", ".vert", ".frag", ".bin"):
            dst = out_dir / src.name
            dst.write_bytes(src.read_bytes())
            remap[str(src)] = str(dst)

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
    return {"pases": r.stats["pases"], "canvas": canvas,
            "assets": len(remap), "plan": str(out_dir / "plan.txt")}


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
    exec_path = Path("/tmp/glexec")
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
            import shutil
            shutil.rmtree(r.tmp, ignore_errors=True)
    for k, v in stats.items():
        if k == "log" and v:
            print(f"  log del compilador (cola):\n{v}")
        else:
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
