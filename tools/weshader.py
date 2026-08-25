#!/usr/bin/env python3
"""Traductor del dialecto de shader de Wallpaper Engine a GLSL ES 3.20.

Los shaders de WE parecen GLSL pero no lo son. Hay cuatro capas encima:

  1. `#include "common.h"`      GLSL no tiene includes; hay que resolverlos.
  2. `// [COMBO] {...}`         declara una variante compilada; su valor
                                llega desde `combos` en el pase de scene.json
                                y se materializa como un `#define`.
  3. `// {"material":...}`      metadatos JSON en el comentario de cada
                                uniform; enlazan con `constantshadervalues`.
                                Son datos para el motor, no afectan al codigo.
  4. Restos de HLSL             `frac`, `saturate`, `mul`, `CAST4`,
                                `texSample2D`... 31 identificadores que WE
                                inyecta y que aqui hay que reconstruir.

Ademas los shaders usan `varying`/`attribute` (GLSL 1.x) y ningun fichero
declara `#version`, asi que la cabecera tambien la pone el motor.

La lista de 31 no es una suposicion: sale de cruzar todas las llamadas del
corpus contra todo lo definido en los headers. Lo que queda sin definir es,
por eliminacion, lo que aporta el motor.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
import weglsl

# Se apunta a GLSL de escritorio, no a GLSL ES, y no por comodidad: los
# shaders de WY vienen de HLSL y dependen de conversiones implicitas int->float
# que GLSL ES prohibe y el de escritorio permite desde la 1.20. Ademas `sample`
# es palabra reservada en ES y los shaders la usan como nombre de variable.
# Medido sobre el corpus: pasar de "320 es" a "330 core" es la diferencia entre
# el 71% y el 97% de shaders que compilan.
TARGETS = {
    "gl330": "#version 330 core",
    "es320": "#version 320 es",
}
DEFAULT_TARGET = "gl330"

# Los identificadores de HLSL que WE inyecta. Semantica deducida del uso real
# en el corpus, no del nombre: p.ej. `mul(aces_input_matrix, color)` demuestra
# que el orden es matriz-por-vector, no al reves.
PRELUDE_COMPAT = r"""
// ── compatibilidad HLSL -> GLSL ES ──────────────────────────────────────
// WE define GLSL o HLSL segun a que backend compila, y los shaders eligen con
// `#ifdef`. Nosotros no definiamos ninguno, asi que todo `#ifdef GLSL` caia al
// `#else`, o sea a la rama de D3D: `puppettexturechannels` indexaba una matriz
// con un flotante ---que GLSL rechaza--- y el osciloscopio se quedaba sin su
// array de varyings, con lo que el programa no enlazaba. HLSL se queda sin
// definir a proposito: sus ramas invierten la Y de las texturas.
#define GLSL 1
#define frac fract
#define lerp mix
#define saturate(x) clamp((x), 0.0, 1.0)
#define atan2(y, x) atan((y), (x))
#define ddx dFdx
#define ddy dFdy
#define rsqrt inversesqrt
// fmod de HLSL trunca hacia cero; mod de GLSL usa floor. No son lo mismo
// para negativos, asi que no vale con hacer #define fmod mod.
#define fmod(x, y) ((x) - (y) * trunc((x) / (y)))
#define mod2(x, y) mod((x), (y))
#define mul(a, b) ((a) * (b))
#define clip(x) do { if ((x) < 0.0) discard; } while (false)

#define float2 vec2
#define float3 vec3
#define float4 vec4
#define float2x2 mat2
#define float3x3 mat3
#define float4x4 mat4
#define int2 ivec2
#define int3 ivec3
#define int4 ivec4

#define CASTF(x) float(x)
#define CASTU(x) uint(x)
#define CASTI(x) int(x)
#define CAST2(x) vec2(x)
#define CAST3(x) vec3(x)
#define CAST4(x) vec4(x)
#define CAST2X2(x) mat2(x)
#define CAST3X3(x) mat3(x)
#define CAST4X4(x) mat4(x)

// El `.xy` no sobra: HLSL trunca solo, y los shaders pasan `v_TexCoord`, que
// es vec4. `texture(sampler2D, vec4)` no existe y el pase entero se cae. Sobre
// un vec2 el swizzle es legal y no cambia nada, asi que vale para los dos.
#define texSample2D(s, uv) texture((s), (uv).xy)
#define texSample2DLod(s, uv, lod) textureLod((s), (uv).xy, (lod))
#define texSample2DBackBuffer(s, uv) texture((s), (uv).xy)
#define texSample3D(s, uv) texture((s), (uv))
#define texSampleCube(s, uv) texture((s), (uv))
#define texLoad2D(s, uv) texelFetch((s), ivec2(uv), 0)
#define SampleLevel(s, uv, lod) textureLod((s), (uv), (lod))
// El sampler de comparacion devuelve escalar; los shaders leen .r sobre el
// resultado, asi que hay que envolverlo en un vec4.
#define texSample2DCompare(s, uv, z) vec4(texture((s), vec3((uv), (z))))

#define MAKE_SAMPLER2D_ARGUMENT(s) s
#define DECLARE_SAMPLER2D_PARAMETER(s) highp sampler2D s
"""

PRELUDE_PRECISION = """
precision highp float;
precision highp int;
precision highp sampler2D;
precision highp sampler3D;
precision highp samplerCube;
"""

FRAG_OUTPUT = """
layout(location = 0) out vec4 wpFragColor;
"""

# Identificadores que no tienen equivalente y que delatan un shader que este
# traductor no puede cubrir. Se detectan para dar un error claro en vez de un
# log del compilador ilegible.
UNSUPPORTED = {
    "register": "sintaxis de binding de HLSL (: register(cN))",
    "GetDimensions": "metodo de objeto de HLSL, sin equivalente directo",
}

# `PerformLighting_V1` NO esta en los assets: la inyecta el motor de WE donde
# encuentra `#require LightingV1`, y por eso los 8 shaders que la llaman
# tampoco declaran las dos arrays de luces que consume. Hay que reponer las
# tres cosas.
#
# El cuerpo no es una invencion: WE deja la misma cuenta escrita a mano en
# otros sitios de su propia libreria, y de ahi sale entera.
#
#   * La suma de cuatro luces puntuales y el ambiente aparte, en
#     `effects/fluidsimulation/.../fluidsimulation_combine.frag`, que hace el
#     bucle desenrollado en vez de llamar a la funcion.
#   * El termino por luz, en `ComputePBRLightShadow` (`common_pbr_2.h`), que es
#     esta misma funcion con sombras. Se llama con `shadowFactor` a 1.
#   * El exponente del decaimiento, de `ComputeLightSpecular`
#     (`common_fragment.h`): la generacion anterior de shaders atenua el
#     difuso con `lightAttn * lightAttn` sobre el mismo `saturate(1 - d/radio)`,
#     o sea 2. Pero NO es una constante: en el modulo que WE genera de verdad
#     ---esta como texto en `wallpaper64.exe`, ver NOTAS--- el exponente viaja
#     con la luz, en el `.w` de su origen. Aqui va en `g_LightsExponent`, que
#     el plan rellena; 2 es solo el valor por defecto.
#
# Se construye sobre `ComputePBRLightShadow` y no sobre `ComputePBRLight`
# porque `common_pbr_2.h` --- el header que incluyen los 8 --- ya no define la
# segunda. Por eso se inyecta en el sitio del `#require`, que en los 8 va
# despues de los `#include`: alli el helper ya esta declarado.
LIGHTING_V1_GLSL = """
uniform vec3 g_LightsPosition[4];
uniform vec4 g_LightsColorRadius[4];
uniform float g_LightsExponent[4];

vec3 PerformLighting_V1(vec3 worldPos, vec3 albedo, vec3 normal, vec3 viewDir,
                        vec3 specularTint, vec3 f0, float roughness, float metallic)
{
	vec3 suma = vec3(0.0, 0.0, 0.0);
	for (int i = 0; i < 4; ++i) {
		vec3 hacia = g_LightsPosition[i] - worldPos;
		// Una particula puede nacer justo encima de la luz. Alli `length` da 0 y
		// la normalizacion de dentro reparte NaN por toda la capa; el corpus ya
		// se ha ido a negro dos veces por un normalize(0).
		hacia.z += step(dot(hacia, hacia), 1e-8) * 1e-4;
		suma += ComputePBRLightShadow(normal, hacia, viewDir, albedo,
			g_LightsColorRadius[i].rgb, max(g_LightsColorRadius[i].w, 1e-4),
			g_LightsExponent[i], specularTint, f0, roughness, metallic, 1.0);
	}
	return suma;
}
"""


def combos_de_pase(fuente_v: str, fuente_f: str, resolver,
                   material: dict | None = None) -> tuple[dict, dict]:
    """Los combos de cada etapa, prestandose lo que a la otra le falta.

    Un combo vale para el PROGRAMA, no para una etapa: WE lo declara una sola
    vez ---en el vertice o en el fragmento, donde le venga--- y las dos mitades
    lo ven. Traduciendo cada etapa por su cuenta, la que no lo declara se queda
    sin el `#define` y evalua `#if KERNEL == 0` como cierto, porque una macro
    indefinida vale 0.

    No es teorico: `godrays_gaussian` declara KERNEL solo en el vertice, con
    default 1. El vertice salia con `out vec2 v_TexCoord[7]` y el fragmento con
    `in vec2 v_TexCoord[13]`, y el programa NO ENLAZA:

        error: array length mismatch between stages for variable v_TexCoord

    Las dos etapas compilan por separado, asi que una prueba de compilacion no
    lo ve. Eran 8 de los 14 fallos de enlace del corpus, y de lejos el grupo
    grande de los 82 pases que se perdian en los planes reales.

    **Solo se presta lo que hace falta**: unicamente el combo que la etapa
    CONSULTA en un `#if` y no declara. Empujar todos los defaults de una etapa
    a la otra enciende ademas ramas que esa etapa nunca miro; medido, en este
    corpus da la misma imagen, pero no hay razon para arriesgarla.

    Y arregla mas de lo que se perdia: la mayoria de las escenas de godrays
    traen su propia copia del shader, con `v_TexCoord` como vec4 en las dos
    mitades, asi que enlazaban --- y corrian con el vertice calculando 7
    muestras y el fragmento leyendo 13.
    """
    def declarados(fuente: str) -> tuple[str, dict]:
        texto = normalise_newlines(fuente)
        try:
            texto = resolve_includes(texto, resolver)
        except ShaderError:
            pass          # sin el include, al menos los de este fichero
        return texto, parse_combos(texto)

    texto_v, combos_v = declarados(fuente_v)
    texto_f, combos_f = declarados(fuente_f)

    for texto, propios, ajenos in ((texto_v, combos_v, combos_f),
                                   (texto_f, combos_f, combos_v)):
        for nombre in undefined_conditionals(texto, set(propios)):
            if nombre in ajenos:
                propios[nombre] = ajenos[nombre]

    mat = material or {}
    combos_v.update(mat)
    combos_f.update(mat)
    return combos_v, combos_f


_VARYING_DECL_RE = re.compile(
    r"^[ \t]*(?:varying|out|in)[ \t]+(\w+)[ \t]+([A-Za-z_]\w*)[ \t]*;[ \t]*$")


def varyings_de_pase(fuente_v: str, fuente_f: str, resolver,
                     combos_v: dict, combos_f: dict) -> dict[str, str]:
    """Los varying cuyo tipo no coincide entre las dos etapas, y con cual queda.

    HLSL enlaza por semantica y tolera que el pixel shader declare menos
    componentes de las que escribe el vertex shader: lee las primeras. GLSL
    exige que el tipo sea el MISMO y, si no, tira el programa:

        error: vertex shader output `v_TexCoord' declared as type `vec4',
               but fragment shader input declared as type `vec2'

    Los autores se apoyan en esa tolerancia. En el corpus son 3 pares y el
    desajuste esta en la fuente, no en la traduccion: `rotate2d` declara
    `varying vec2` en el vertice y `varying vec3` en el fragmento; el
    `test_shader` de 2844906964, `vec4` y `vec2`.

    **Gana el vertice**, porque es quien produce: lo que el interpolador
    transporta es lo que el vertex shader declaro, y el fragmento leyendo de
    mas leeria componentes que nadie escribio. Los usos del fragmento son
    swizzles ---`v_TexCoord.xy`--- que siguen valiendo al cambiar el ancho, y
    los pocos que usan el varying entero caen en la truncacion implicita que ya
    se aplica despues.

    Solo cuentan las declaraciones VIVAS: una dentro de `#if KERNEL == 0` no
    dice nada si ese combo esta apagado, y quien decide eso son los combos ya
    prestados por [[combos_de_pase]].
    """
    def declaradas(fuente: str, combos: dict) -> dict[str, str]:
        texto = normalise_newlines(fuente)
        try:
            texto = resolve_includes(texto, resolver)
        except ShaderError:
            pass
        valores = parse_combos(texto)
        valores.update(combos)
        fuera: dict[str, str] = {}
        for linea in strip_dead_branches(_strip_comments(texto), valores).splitlines():
            m = _VARYING_DECL_RE.match(linea)
            if m:
                fuera[m.group(2)] = m.group(1)
        return fuera

    tipos_v = declaradas(fuente_v, combos_v)
    tipos_f = declaradas(fuente_f, combos_f)
    return {n: t for n, t in tipos_v.items()
            if n in tipos_f and tipos_f[n] != t}


def forzar_varyings(body: str, tipos: dict[str, str]) -> str:
    """Reescribe el tipo de los varying que [[varyings_de_pase]] desempata."""
    if not tipos:
        return body
    fuera: list[str] = []
    for linea in body.splitlines():
        m = _VARYING_DECL_RE.match(linea)
        if m and m.group(2) in tipos and m.group(1) != tipos[m.group(2)]:
            linea = linea.replace(m.group(1), tipos[m.group(2)], 1)
        fuera.append(linea)
    return "\n".join(fuera)


def inyectar_lighting_v1(body: str) -> tuple[str, bool]:
    """Repone la funcion de iluminacion en el sitio donde WE la inyectaria.

    Devuelve el cuerpo y si se pudo poner. Solo se pone cuando el helper sobre
    el que se apoya esta a la vista: un shader que pidiera `LightingV1` sin
    incluir `common_pbr_2.h` compilaria peor con la inyeccion que sin ella ---
    un error de simbolo ajeno en vez del que se entiende.
    """
    if "LightingV1" not in body or "ComputePBRLightShadow" not in body:
        return body, False

    puesta = False

    def _sub(m: re.Match) -> str:
        nonlocal puesta
        if "LightingV1" not in m.group(0):
            return ""
        puesta = True
        return LIGHTING_V1_GLSL

    return REQUIRE_DIR_RE.sub(_sub, body), puesta


COMBO_RE = re.compile(r"//\s*\[COMBO\]\s*(\{.*?\})\s*$", re.M)
INCLUDE_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]+"([^"]+)"[ \t]*$', re.M)
UNIFORM_META_RE = re.compile(
    r"^[ \t]*uniform[ \t]+(\w+)[ \t]+(\w+)[^;]*;[ \t]*//[ \t]*(\{.*?\})[ \t]*$", re.M)


class ShaderError(Exception):
    pass


def normalise_newlines(src: str) -> str:
    """Pasa todo a LF.

    Los shaders extraidos de un scene.pkg conservan CRLF, y leerlos como bytes
    no aplica la traduccion de saltos de linea que si hace read_text(). Las
    expresiones de este modulo anclan en `$`, que no admite el \\r previo: el
    mismo shader se resolvia bien desde disco y se quedaba sin resolver desde
    el paquete.
    """
    return src.replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class Resolver:
    """Resuelve `#include` con las rutas de busqueda de WE.

    El paquete del wallpaper gana sobre los assets compartidos: un wallpaper
    puede traer su propia version de un header.
    """
    roots: list[Path] = field(default_factory=list)
    overlay: dict[str, bytes] = field(default_factory=dict)

    def read(self, name: str) -> str:
        for key in (name, f"shaders/{name}"):
            if key in self.overlay:
                return normalise_newlines(self.overlay[key].decode("utf-8", "replace"))
        for root in self.roots:
            for cand in (root / name, root / "shaders" / name):
                if cand.is_file():
                    return normalise_newlines(
                        cand.read_text(encoding="utf-8", errors="replace"))
        raise ShaderError(f"include sin resolver: {name!r}")


def resolve_includes(src: str, resolver: Resolver, seen: set[str] | None = None) -> str:
    """Expande includes recursivamente, una sola vez cada uno.

    WE no usa include guards; incluir dos veces el mismo header redefine sus
    funciones y el shader no compila.
    """
    seen = seen if seen is not None else set()

    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name in seen:
            return f"// [include ya insertado: {name}]"
        seen.add(name)
        return resolve_includes(resolver.read(name), resolver, seen)

    return INCLUDE_RE.sub(repl, src)


def parse_combos(src: str) -> dict[str, object]:
    """Devuelve {NOMBRE_COMBO: valor_por_defecto}.

    Los combos vienen de dos sitios distintos, y con el primero solo no basta:

      1. Directivas `// [COMBO] {...}` de la cabecera del shader.
      2. La clave `combo` en los metadatos de un uniform. Ahi el combo se
         activa cuando el slot correspondiente esta enlazado en el pase; si
         no lo esta, queda a 0. `MASK` es el caso tipico: lo declara el
         comentario de g_Texture2, no ninguna directiva [COMBO].
    """
    out: dict[str, object] = {}
    for m in COMBO_RE.finditer(src):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if "combo" in d:
            out[d["combo"]] = d.get("default", 0)
    for meta in parse_uniform_meta(src).values():
        if "combo" in meta:
            out.setdefault(meta["combo"], 0)
    return out


IF_RE = re.compile(r"^[ \t]*#[ \t]*(?:if|elif)\b([^\n]*)$", re.M)
IFDEF_RE = re.compile(r"^[ \t]*#[ \t]*(?:ifdef|ifndef)[ \t]+([A-Za-z_]\w*)", re.M)
DEFINED_RE = re.compile(r"\bdefined\s*\(?\s*([A-Za-z_]\w*)")
DEFINE_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)", re.M)
IDENT_RE = re.compile(r"\b([A-Za-z_]\w*)\b")


def undefined_conditionals(body: str, known: set[str]) -> set[str]:
    """Identificadores usados en #if/#elif que nadie define.

    GLSL ES trata una macro indefinida dentro de #if como error de
    compilacion, al reves que el GLSL de escritorio, que la evalua como 0.
    WE compila igualmente, asi que su semantica es la de escritorio: un combo
    sin asignar vale 0. Para reproducirla hay que declararlos explicitamente.
    """
    defined = set(DEFINE_RE.findall(body)) | known
    used: set[str] = set()
    for m in IF_RE.finditer(body):
        expr = m.group(1)
        # `defined(X)` es legal con X sin definir; no cuenta.
        expr = re.sub(r"\bdefined\s*\(\s*\w+\s*\)", "", expr)
        expr = re.sub(r"\bdefined\s+\w+", "", expr)
        used.update(IDENT_RE.findall(expr))
    return {n for n in used - defined if not n.isdigit()}


def parse_uniform_meta(src: str) -> dict[str, dict]:
    """Metadatos JSON del comentario de cada uniform.

    Es lo que enlaza un uniform con la propiedad del material: la clave
    `material` da el nombre usado en `constantshadervalues` de scene.json.
    """
    out: dict[str, dict] = {}
    for m in UNIFORM_META_RE.finditer(src):
        try:
            out[m.group(2)] = json.loads(m.group(3))
        except json.JSONDecodeError:
            pass
    return out


UNIFORM_DECL_RE = re.compile(
    r"^[ \t]*uniform[ \t]+[A-Za-z_]\w*[ \t]+[A-Za-z_]\w*(?:\[[^\]]*\])?[ \t]*;[ \t]*$")
COND_OPEN_RE = re.compile(r"^[ \t]*#[ \t]*(?:if|ifdef|ifndef)\b")
COND_CLOSE_RE = re.compile(r"^[ \t]*#[ \t]*endif\b")


def hoist_uniforms(body: str) -> tuple[str, list[str]]:
    """Saca las declaraciones de uniform al principio del shader.

    Los shaders de WE ponen `#include` arriba y los `uniform` despues, pero
    las funciones del header ya usan g_Texture0. GLSL exige declarar antes de
    usar, asi que sin esto no compilan. WE hace lo mismo internamente: inyecta
    los uniforms estandar antes de nada.

    Solo se izan las declaraciones de nivel superior: una que este dentro de
    un #if depende de su combo y sacarla la activaria siempre.
    """
    kept: list[str] = []
    hoisted: list[str] = []
    depth = 0
    for line in body.splitlines():
        if COND_OPEN_RE.match(line):
            depth += 1
        elif COND_CLOSE_RE.match(line):
            depth = max(0, depth - 1)
        elif depth == 0 and UNIFORM_DECL_RE.match(line):
            hoisted.append(line.strip())
            continue
        kept.append(line)
    return "\n".join(kept), hoisted


_DEFINE_OBJ_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)\(?([^\n]*)$", re.M)
_DECL_NOMBRE_RE = re.compile(r"^uniform[ \t]+\w+[ \t]+([A-Za-z_]\w*)")


def quitar_uniforms_muertos(body: str, hoisted: list[str]) -> list[str]:
    """Descarta los uniform que el shader declara y no usa.

    Un uniform sin usar no cambia un pixel, pero SI cuenta para el enlace: el
    enlazador compara los uniform de las dos etapas por nombre antes de tirar
    lo que no se usa, y si no coinciden en tipo se lleva el programa entero.
    Pasa de verdad en `frame_builder`, donde el autor declaro
    `vec2 u_refResolution` en el vertice y `float u_refResolution` en el
    fragmento ---dos defaults distintos, "512 512" y 512--- y el fragmento no
    lo toca. Mesa corta con:

        error: uniform `u_refResolution' declared as type `float' and `vec2'

    NVIDIA no se queja, que es lo que despista: son 3 pares del corpus y solo
    fallan en el driver del escritorio.

    Quitarlo es preferible a unificar el tipo a mano: no hay que elegir cual de
    los dos defaults gana, y la etapa que si lo usa se queda como estaba.

    Un `#define alias u_refResolution` cuenta como uso solo si `alias` se usa;
    si no, la declaracion seguiria viva por una linea que nadie expande.

    Del alias valen TODAS sus definiciones, no la primera: este traductor deja
    los `#if` para el driver, asi que un mismo nombre llega definido varias
    veces con cuerpos distintos. `genericimage4` define `M_MDL` como
    `g_AltModelMatrix` y como `g_ModelMatrix`, y quedarse con una borraba la
    otra ---la que usaba el pase base de casi toda imagen---.
    """
    macros: dict[str, list[tuple[int, str]]] = {}
    pendientes: list[tuple[str, int]] = []
    for n, linea in enumerate(body.splitlines()):
        m = _DEFINE_OBJ_RE.match(linea)
        if m:
            macros.setdefault(m.group(1), []).append((n, m.group(2)))
        elif not linea.lstrip().startswith("#"):
            pendientes.extend((ident, n) for ident in IDENT_RE.findall(linea))

    # El nombre solo expande si YA estaba definido donde aparece: en
    # `frame_builder` el fragmento declara una variable local `res` mucho antes
    # del `#define res u_refResolution`, y sin mirar el orden esa variable
    # mantenia vivo el uniform que sobra --- justo el que rompe el enlace.
    usados: set[str] = set()
    while pendientes:
        ident, linea = pendientes.pop()
        usados.add(ident)
        for n, cuerpo in macros.get(ident, ()):
            if n < linea:
                pendientes.extend((x, linea) for x in IDENT_RE.findall(cuerpo)
                                  if x not in usados)
    return [l for l in hoisted
            if (m := _DECL_NOMBRE_RE.match(l)) is None or m.group(1) in usados]


def equilibrar_condicionales(body: str) -> str:
    """Quita los `#endif` sobrantes y cierra los `#if` que queden abiertos.

    Tres shaders del corpus traen un `#endif` de mas -- descuido del autor, no
    del traductor: la fuente ya viene con 7 `#if` y 8 `#endif`. WE los compila
    igual, asi que su preprocesador lo tolera; el de GLSL no, y corta con
    "#endif without #if" llevandose el shader entero.

    Se corrige en la direccion de dibujar: sobra un `#endif`, se ignora; falta
    uno, se anade al final. Sobre una fuente equilibrada no cambia nada.
    """
    fuera: list[str] = []
    prof = 0
    for linea in body.splitlines():
        if COND_ABRE_RE.match(linea):
            prof += 1
        elif COND_FIN_RE.match(linea):
            if prof == 0:
                continue            # sin `#if` que cerrar: se descarta
            prof -= 1
        elif (COND_ELIF_RE.match(linea) or COND_ELSE_RE.match(linea)) and prof == 0:
            continue                # `#else`/`#elif` huerfano, mismo criterio
        fuera.append(linea)
    fuera.extend(["#endif"] * prof)
    return "\n".join(fuera)


_TRUNC_DECL_RE = re.compile(
    r"^([ \t]*(?:(?:const|highp|mediump|lowp)[ \t]+)*"
    r"(float|int|uint|bool|[iub]?vec[234])[ \t]+\w+[ \t]*=[ \t]*)(.+);[ \t]*$")
# `for (int i = <expr>; ...)`: el inicializador de un bucle es una declaracion
# como cualquier otra y sufre la misma conversion implicita.
_TRUNC_FOR_RE = re.compile(
    r"^([ \t]*for[ \t]*\([ \t]*(?:(?:const|highp|mediump|lowp)[ \t]+)*"
    r"(float|int|uint|bool|[iub]?vec[234])[ \t]+\w+[ \t]*=[ \t]*)([^;]+);")
# Asignacion a algo que ya existe, con o sin swizzle y con o sin operador:
# `v_NoiseCoord = ...`, `albedo.rgb += ...`. El `(?!=)` deja fuera `==`.
_TRUNC_ASIG_RE = re.compile(
    r"^([ \t]*)(\w+)(\.[xyzwrgba]+)?[ \t]*([-+*/]?)=(?!=)[ \t]*(.+);[ \t]*$")
_TRUNC_FUNC_RE = re.compile(r"^[ \t]*(\w+)[ \t]+(\w+)[ \t]*\(([^)]*)\)[ \t]*\{")
_TRUNC_PARAM_RE = re.compile(r"(?:in|out|inout)?[ \t]*(\w+)[ \t]+(\w+)")
_SWZ = "xyzw"


def _sin_uint(expr: str, tabla: dict) -> str:
    """Pasa a `int` los identificadores `uint` de una expresion.

    GLSL no mezcla `uint` con `int` ni siquiera con un literal: en las barras de
    audio del corpus, `(barFreq1 + 1) % RESOLUTION` no compila porque `barFreq1`
    es `uint`, el `1` es `int` y `RESOLUTION` una macro. HLSL convierte solo.

    Se hace al reves de lo que parece --- bajar el `uint` a `int` en vez de
    subir los enteros --- porque el literal y la macro pueden estar en cualquier
    sitio de la expresion y el identificador se sabe donde esta. El destino de
    la asignacion vuelve a envolver en `uint(...)`, asi que el tipo final no
    cambia; y los valores son indices de espectro, muy lejos de desbordar.
    """
    def repl(m: re.Match) -> str:
        t = tabla.get(m.group(0))
        return f"int({m.group(0)})" if t and t[0] == "uint" and t[1] == 1 else m.group(0)

    return re.sub(r"\b[A-Za-z_]\w*\b(?![ \t]*\()", repl, expr)


def _porcentaje_a_mod(expr: str, tabla: dict, funcs: dict) -> str:
    """`a % b` sobre flotantes pasa a `mod(a, b)`.

    En HLSL `%` vale tambien para flotantes; en GLSL exige enteros y corta con
    "LHS of operator % must be an integer". No se puede traducir a ciegas: `%`
    entre enteros es GLSL valido y `mod` devolveria un flotante.

    Se parte por el `%` de nivel superior --- fuera de parentesis --- y solo se
    cambia si el tipo base de la izquierda se puede AFIRMAR que es flotante.
    """
    prof = 0
    for i, c in enumerate(expr):
        if c in "([":
            prof += 1
        elif c in ")]":
            prof -= 1
        elif c == "%" and prof == 0:
            izq, der = expr[:i].strip(), expr[i + 1:].strip()
            t = weglsl.tipo(izq, tabla, funcs)
            if t and t[0] == "float":
                der = _porcentaje_a_mod(der, tabla, funcs)
                return f"mod({izq}, float({der}))"
            break
    return expr


_LLAMADA_RE = re.compile(r"\b(\w+)[ \t]*\(")


def _corta_argumentos(texto: str, i: int) -> tuple[list[str], int] | None:
    """Los argumentos de la llamada que abre en `texto[i]`, y donde cierra.

    Corta por las comas de PRIMER nivel: una coma dentro de otra llamada o de
    un constructor no separa argumentos. Devuelve None si el parentesis no
    cierra en esta linea, que es lo normal en una llamada partida en varias.
    """
    prof, ini, args = 0, i + 1, []
    for j in range(i, len(texto)):
        c = texto[j]
        if c == "(":
            prof += 1
        elif c == ")":
            prof -= 1
            if prof == 0:
                args.append(texto[ini:j])
                return ([a for a in args if a.strip() != ""] if len(args) > 1
                        or args[0].strip() else []), j
        elif c == "," and prof == 1:
            args.append(texto[ini:j])
            ini = j + 1
    return None


def truncar_argumentos(body: str) -> str:
    """Aplica la truncacion implicita de HLSL a los ARGUMENTOS de una llamada.

    HLSL deja pasar un vec4 donde se espera un vec2 y se queda con las dos
    primeras componentes; GLSL lo rechaza y se lleva el pase entero. Es lo que
    tumbaba la unica variante del corpus que no compilaba:

        albedo = vec4(maskBokeh(v_TexCoord, ...), albedo.a);
        error C7011: implicit cast from "vec4" to "vec2"

    `v_TexCoord` es un vec4 porque ese shader empaqueta mas cosas en el `zw`, y
    `maskBokeh` pide un vec2.

    La regla que hace esto seguro es la misma que en `truncar_asignaciones`:
    **solo se toca cuando el ancho se puede AFIRMAR** y es mayor que el del
    parametro. `weglsl.ancho` devuelve None ante la duda ---incluidas las
    variables locales, que aqui no se siguen--- y entonces el argumento se deja
    como esta. Un barrido plano con expresiones regulares ya rompio 124
    variantes una vez; el oraculo es el corpus que ya compila.
    """
    params = weglsl.tabla_de_parametros(body)
    if not params:
        return body
    glob = weglsl.tabla_global(body)
    funcs = weglsl.tabla_de_funciones(body)

    def en_linea(linea: str) -> str:
        pos = 0
        while True:
            m = _LLAMADA_RE.search(linea, pos)
            if not m:
                return linea
            firma = params.get(m.group(1))
            corte = _corta_argumentos(linea, m.end() - 1) if firma else None
            if not corte or len(corte[0]) != len(firma):
                pos = m.end()
                continue
            args, fin = corte
            nuevos = []
            for arg, tipo_p in zip(args, firma):
                a = arg.strip()
                if tipo_p is not None and a:
                    w = weglsl.ancho(a, glob, funcs)
                    if w is not None and w > tipo_p[1]:
                        a = f"({a}).{'xyzw'[:tipo_p[1]]}"
                nuevos.append(a)
            nueva = ", ".join(nuevos)
            linea = linea[:m.end()] + nueva + linea[fin:]
            pos = m.end() + len(nueva)

    return "\n".join(l if l.lstrip().startswith("#") else en_linea(l)
                      for l in body.splitlines())


def truncar_asignaciones(body: str) -> str:
    """Aplica la truncacion implicita de HLSL a los inicializadores.

    HLSL deja escribir `float mask = texSample2D(...)` o
    `vec3 albedo = <expr vec4>`: se queda con las primeras componentes. GLSL lo
    rechaza y se lleva el shader entero.

    El ancho lo da `weglsl`, que es un parser de verdad y devuelve None ante la
    duda. Eso es lo que hace segura esta funcion: solo se toca la linea cuando
    el ancho se puede AFIRMAR y es mayor que el declarado. Un intento anterior
    infirio el ancho barriendo identificadores con una expresion regular y
    rompio 124 variantes, porque un barrido plano cree que `dot(a, b)` es
    ancho. La validacion que respalda esto: sobre las 540 variantes que
    compilan --- ya verificadas por GLSL --- la inferencia acierta 6001
    declaraciones, deja 2218 sin determinar y no falla ninguna.
    """
    glob = weglsl.tabla_global(body)
    funcs = weglsl.tabla_de_funciones(body)
    local: dict[str, int] = {}
    fuera: list[str] = []
    prof = 0
    for linea in body.splitlines():
        if prof == 0:
            m = _TRUNC_FUNC_RE.match(linea)
            if m:
                local = {}
                for pm in _TRUNC_PARAM_RE.finditer(m.group(3)):
                    if pm.group(1) in weglsl.ANCHO_TIPO:
                        local[pm.group(2)] = (weglsl.BASE_TIPO[pm.group(1)],
                                              weglsl.ANCHO_TIPO[pm.group(1)])
        m = _TRUNC_DECL_RE.match(linea) if prof > 0 else None
        cola = ";"
        if m is None and prof > 0:
            mf = _TRUNC_FOR_RE.match(linea)
            if mf:
                m = mf
                cola = ";" + linea[mf.end():]
        if m:
            cabeza, tipo, expr = m.group(1), m.group(2), m.group(3)
            destino = weglsl.ANCHO_TIPO[tipo]
            base_destino = weglsl.BASE_TIPO[tipo]
            visible = {**glob, **local}
            expr = _porcentaje_a_mod(expr, visible, funcs)
            # Truncacion implicita DENTRO de la expresion: `vec2 p =
            # saturate(depth) * pixelSize` mezcla anchos y GLSL corta. Se
            # intenta antes de tipar, y si no hay nada que recortar el texto se
            # queda como estaba.
            recortada = weglsl.truncar(expr, visible, funcs)
            if recortada is not None:
                expr = recortada
            got = weglsl.tipo(expr, visible, funcs)
            if got is not None:
                if got[1] > destino:
                    expr = f"({expr}).{_SWZ[:destino]}"
                elif got[1] == 1 and destino > 1:
                    # Difusion de escalar: `vec3 color = 0;` reparte el valor a
                    # las tres componentes en HLSL, y en GLSL hay que
                    # escribirlo. La base no importa: un constructor convierte
                    # ---`vec3(0)` es legal--- asi que tambien vale para el
                    # entero que el autor escribio sin punto.
                    tipo_vec = {"float": "vec", "int": "ivec",
                                "uint": "uvec", "bool": "bvec"}[base_destino]
                    expr = f"{tipo_vec}{destino}({expr})"
                # HLSL convierte solo de flotante a entero al asignar; GLSL no.
                if got[0] == "float" and base_destino in ("int", "uint"):
                    expr = f"{base_destino}({expr})"
            elif destino == 1 and base_destino in ("int", "uint"):
                expr = _sin_uint(expr, visible)
                # Sin poder afirmar el tipo, un destino entero se envuelve
                # igualmente: `uint(x)` e `int(x)` valen para cualquier escalar
                # numerico, y si la expresion fuera ancha la declaracion ya
                # estaba rota. Es lo que arregla las barras de audio ---
                # `uint b = (a + 1) % RESOLUTION`, donde el 1 es int y
                # RESOLUTION una macro --- y los bucles cuyo indice arranca en
                # un uniform flotante.
                expr = f"{base_destino}({expr})"
            linea = f"{cabeza}{expr}{cola}"
            nombre = re.search(r"(\w+)[ \t]*=", cabeza)
            if nombre:
                local[nombre.group(1)] = (weglsl.BASE_TIPO[tipo], destino)
        elif prof > 0:
            # Asignacion a una variable que ya existe: `v_NoiseCoord =
            # v_TexCoord;` con destino vec2 y origen vec4. Es la misma
            # truncacion que en una declaracion, pero el tipo del destino hay
            # que buscarlo en la tabla en vez de leerlo en la linea.
            ma = _TRUNC_ASIG_RE.match(linea)
            if ma:
                sangria, nombre_d, swz, op, expr = ma.groups()
                destino_t = {**glob, **local}.get(nombre_d)
                if destino_t:
                    # Con swizzle manda el swizzle: `albedo.rgb += ...` pide
                    # tres componentes aunque `albedo` sea vec4.
                    ancho_destino = (len(swz) - 1) if swz else destino_t[1]
                    visible = {**glob, **local}
                    recortada = weglsl.truncar(expr, visible, funcs)
                    if recortada is not None:
                        expr = recortada
                    got = weglsl.tipo(expr, visible, funcs)
                    if got is not None and got[1] > ancho_destino:
                        expr = f"({expr}).{_SWZ[:ancho_destino]}"
                    if (got is not None and got[0] == "float"
                            and destino_t[0] in ("int", "uint") and not swz):
                        # Destino entero, valor flotante. En una compuesta hay
                        # que hacer la cuenta EN FLOTANTE y convertir al final:
                        # `bar *= 0.7` con bar entero vale 0 en HLSL, y
                        # `bar *= int(0.7)` lo dejaria en bar --- la barra de
                        # la escena se veria entera en vez de atenuada.
                        conv = destino_t[0]
                        if op:
                            expr = (f"{conv}(float({nombre_d}) {op} ({expr}))")
                            op = ""
                        else:
                            expr = f"{conv}({expr})"
                    linea = f"{sangria}{nombre_d}{swz or ''} {op}= {expr};"
        fuera.append(linea)
        prof += linea.count("{") - linea.count("}")
        prof = max(prof, 0)
    return "\n".join(fuera)


def const_no_constante(body: str) -> str:
    """Quita `const` cuando el inicializador no lo es.

    `const float FEATHER = u_Feather * 0.5;` es legal en HLSL, donde `const`
    significa "no lo reasigno". En GLSL exige una expresion constante en tiempo
    de compilacion y un uniform no lo es. Quitar el calificador conserva el
    significado que el autor le daba.
    """
    tabla = set(re.findall(r"\buniform[ \t]+\w+[ \t]+(\w+)", body))
    tabla |= set(re.findall(r"^[ \t]*(?:in|out|varying|attribute)[ \t]+\w+[ \t]+(\w+)",
                            body, re.M))
    if not tabla:
        return body

    def repl(m: re.Match) -> str:
        if any(re.search(rf"\b{re.escape(n)}\b", m.group(2)) for n in tabla):
            return m.group(1) + m.group(2) + ";"
        return m.group(0)

    return re.sub(r"^([ \t]*)const[ \t]+(\w+[ \t]+\w+[ \t]*=[ \t]*[^;]+);",
                  lambda m: repl(m) if True else m.group(0), body, flags=re.M)


_COMPARACION_RE = re.compile(r"(?:<=|>=|==|!=|<|>)")


def bool_a_float(body: str) -> str:
    """Envuelve en `float(...)` las comparaciones que se usan como numero.

    HLSL convierte `bool` a float solo (true -> 1.0), asi que
    `depth *= (depth < limite) * 6.0;` es legal alli. GLSL no lo permite y el
    driver corta con "invalid operands to *".

    Solo se toca un parentesis que ademas este pegado a un `*`: `if (a < b)` no
    se toca, y tampoco `(a < b) && c`. Es deliberadamente estrecho -- se busca
    el caso que aparece en el corpus, no reimplementar la conversion implicita
    de HLSL.

    Costo de no tenerlo: en 3146507587 los dos pases que calculan el desenfoque
    de profundidad de campo no compilaban, su buffer `_full2` se quedaba sin
    escribir, y el pase que lo consume acababa oscureciendo la escena entera.
    """
    fuera = []
    i = 0
    while i < len(body):
        c = body[i]
        if c != "(":
            fuera.append(c)
            i += 1
            continue
        # Buscar el cierre equilibrado.
        prof, j = 1, i + 1
        while j < len(body) and prof:
            if body[j] == "(":
                prof += 1
            elif body[j] == ")":
                prof -= 1
            j += 1
        if prof:                       # parentesis sin cerrar: no se toca
            fuera.append(c)
            i += 1
            continue
        interior = body[i + 1:j - 1]
        # Comparacion en el nivel superior del grupo, no dentro de otro.
        plano, prof = [], 0
        for ch in interior:
            if ch == "(":
                prof += 1
            elif ch == ")":
                prof -= 1
            elif prof == 0:
                plano.append(ch)
        antes = body[:i].rstrip()
        despues = body[j:].lstrip()
        pegado = antes.endswith("*") or despues.startswith("*")
        # Se recurre siempre en el interior: un grupo que no se convierte
        # puede contener otro que si, como en `f((a < b) * 2.0)`.
        dentro = bool_a_float(interior)
        if pegado and _COMPARACION_RE.search("".join(plano)):
            fuera.append(f"float({dentro})")
        else:
            fuera.append(f"({dentro})")
        i = j
    return "".join(fuera)


_COND_IF_RE = re.compile(r"\bif[ \t]*\(")
_LOGICO_RE = re.compile(r"(?:<=|>=|==|!=|<|>|&&|\|\||(?<![\w.])!(?!=))")


def _grupo(body: str, abre: int) -> int:
    """Indice justo detras del parentesis que cierra el de `abre`, o -1."""
    prof, j = 0, abre
    while j < len(body):
        if body[j] == "(":
            prof += 1
        elif body[j] == ")":
            prof -= 1
            if prof == 0:
                return j + 1
        j += 1
    return -1


def condicion_a_bool(body: str) -> str:
    """Envuelve en `bool(...)` las condiciones que no son booleanas.

    En HLSL cualquier escalar vale de condicion --- distinto de cero es cierto
    --- y en GLSL no: `if (u_userInvertDepthMap)` con un uniform float, o
    `INVERT ? 1 - mask : mask` con un combo, cortan la compilacion con
    "condition must be scalar boolean".

    `bool(x)` es valido para bool, int, uint y float, asi que envolver de mas no
    rompe nada: por eso solo se mira si la condicion lleva ya un operador de
    comparacion o logico, en cuyo caso se deja como esta. Lo que NO se puede
    envolver es un vector, y ahi la condicion la da el parser: si `weglsl` puede
    afirmar que la expresion es ancha, no se toca.
    """
    glob = weglsl.tabla_global(body)
    funcs = weglsl.tabla_de_funciones(body)

    def envolver(expr: str) -> str:
        limpio = expr.strip()
        if not limpio or _LOGICO_RE.search(limpio):
            return expr
        t = weglsl.tipo(limpio, glob, funcs)
        if t and (t[0] == "bool" or t[1] > 1):
            return expr
        return f"bool({limpio})"

    # `if (...)`
    fuera, i = [], 0
    while True:
        m = _COND_IF_RE.search(body, i)
        if not m:
            fuera.append(body[i:])
            break
        fin = _grupo(body, m.end() - 1)
        if fin < 0:
            fuera.append(body[i:])
            break
        fuera.append(body[i:m.end()])
        fuera.append(envolver(body[m.end():fin - 1]))
        fuera.append(")")
        i = fin
    body = "".join(fuera)

    # `cond ? a : b`, con la condicion en la misma linea y sin parentesis suelto.
    def ternario(m: re.Match) -> str:
        return f"{m.group(1)}{envolver(m.group(2))} ?"

    return re.sub(r"(^|[=(,]\s*)([A-Za-z_][\w.]*)\s*\?", ternario, body, flags=re.M)


# Funciones de GLSL cuyo parametro es un `genType`: si un argumento es flotante,
# un literal entero en otro argumento tiene que serlo tambien.
_GENTIPO = ("max", "min", "clamp", "mix", "pow", "step", "smoothstep", "mod",
            "atan", "reflect", "distance", "dot", "cross", "faceforward")
# De todas ellas, estas NO tienen sobrecarga `(genType, float)`: si un argumento
# es vector, los demas tienen que serlo tambien. `max(vec3, 0.0)` compila;
# `pow(vec3, 0.5)` no.
_SIN_ESCALAR = ("pow", "atan", "reflect", "faceforward")
_LITERAL_ENTERO_RE = re.compile(r"^[+-]?\d+$")


def _argumentos(texto: str) -> list[str]:
    """Parte por comas de primer nivel."""
    partes, prof, actual = [], 0, []
    for c in texto:
        if c in "([":
            prof += 1
        elif c in ")]":
            prof -= 1
        if c == "," and prof == 0:
            partes.append("".join(actual))
            actual = []
        else:
            actual.append(c)
    partes.append("".join(actual))
    return partes


def literales_de_llamada(body: str) -> str:
    """`max(0, albedo.rgb)` -> `max(0.0, albedo.rgb)`.

    HLSL promociona el literal entero al tipo del otro argumento; GLSL busca una
    sobrecarga `max(int, vec3)` que no existe y corta. Solo se toca un argumento
    que sea un literal entero PELADO, y solo si otro argumento de la misma
    llamada es de base flotante --- eso lo afirma el parser, no una heuristica.
    """
    # Aqui se miran TODAS las declaraciones, tambien las locales de cualquier
    # funcion: la tabla global no basta porque `albedo` se declara dentro de
    # `main`. Mezclar ambitos podria dar un tipo equivocado, pero lo unico que
    # se decide con el es si un literal entero pasa a flotante, y solo cuando
    # otro argumento de la MISMA llamada es flotante.
    glob = dict(weglsl.tabla_global(body))
    for m in re.finditer(r"^[ \t]*(?:(?:const|highp|mediump|lowp)[ \t]+)*"
                         r"(\w+)[ \t]+(\w+)[ \t]*(?:=|;)", body, re.M):
        if m.group(1) in weglsl.ANCHO_TIPO:
            glob.setdefault(m.group(2), (weglsl.BASE_TIPO[m.group(1)],
                                         weglsl.ANCHO_TIPO[m.group(1)]))
    funcs = weglsl.tabla_de_funciones(body)
    fuera, i = [], 0
    patron = re.compile(r"\b(" + "|".join(_GENTIPO) + r")[ \t]*\(")
    while True:
        m = patron.search(body, i)
        if not m:
            fuera.append(body[i:])
            break
        fin = _grupo(body, m.end() - 1)
        if fin < 0:
            fuera.append(body[i:m.end()])
            i = m.end()
            continue
        args = _argumentos(body[m.end():fin - 1])
        bases = [weglsl.tipo(a.strip(), glob, funcs) for a in args]
        anchos = [b[1] for b in bases if b and b[0] == "float"]
        if anchos:
            # El literal toma el ANCHO del argumento flotante, no solo su base:
            # `max(0, albedo.rgb)` tiene que salir como `max(vec3(0.0), ...)`.
            # `max(0.0, vec3)` sigue sin compilar, porque la sobrecarga que
            # existe es `max(genType, float)` y no al reves.
            ancho = max(anchos)
            def flota(a: str) -> str:
                # Solo el argumento que ES un literal pelado. Tocar los enteros
                # de DENTRO de la expresion se probo y se descarto: hace falta
                # saber que no son un indice de array ni el exponente de un
                # `1e-5`, y un barrido con expresion regular no lo sabe --- se
                # llevo por delante 6 variantes que ya compilaban.
                a = a.strip()
                if not _LITERAL_ENTERO_RE.match(a):
                    return a
                return f"{a}.0" if ancho == 1 else f"vec{ancho}({a}.0)"
            args = [flota(a) for a in args]
            # HLSL trunca el argumento mas ancho al mas estrecho:
            # `mix(vec4, vec3, float)` es `mix(vec4.rgb, vec3, float)`.
            if m.group(1) in _SIN_ESCALAR and max(anchos) > 1:
                # Difundir el escalar al ancho del vector.
                ancho_v = max(anchos)
                nuevos = []
                for a, b in zip(args, bases):
                    if b and b[0] == "float" and b[1] == 1:
                        a = f"vec{ancho_v}({a.strip()})"
                    nuevos.append(a)
                args = nuevos
                bases = [(b[0], ancho_v) if b and b[0] == "float" and b[1] == 1 else b
                         for b in bases]
                anchos = [b[1] for b in bases if b and b[0] == "float"]
            estrecho = min(a for a in anchos if a > 1) if any(a > 1 for a in anchos) else 1
            if estrecho > 1:
                nuevos = []
                for a, b in zip(args, bases):
                    if b and b[0] == "float" and b[1] > estrecho:
                        a = f"({a.strip()}).{_SWZ[:estrecho]}"
                    nuevos.append(a)
                args = nuevos
        fuera.append(body[i:m.end()])
        fuera.append(",".join(args))
        fuera.append(")")
        i = fin
    return "".join(fuera)


_RETURN_RE = re.compile(r"^([ \t]*return[ \t]+)([+-]?\d+)[ \t]*;", re.M)


def literales_de_return(body: str) -> str:
    """`return 0;` dentro de una funcion `float` -> `return 0.0;`."""
    funcs = weglsl.tabla_de_funciones(body)
    if not funcs:
        return body
    lineas = body.splitlines()
    actual = None
    prof = 0
    for n, linea in enumerate(lineas):
        if prof == 0:
            mf = _TRUNC_FUNC_RE.match(linea)
            if mf:
                actual = funcs.get(mf.group(2))
        m = _RETURN_RE.match(linea)
        if m and actual and actual[0] == "float" and actual[1] == 1:
            lineas[n] = f"{m.group(1)}{m.group(2)}.0;"
        prof += linea.count("{") - linea.count("}")
        prof = max(prof, 0)
    return "\n".join(lineas)


_ESCRIBE_VARYING_RE = re.compile(
    r"^[ \t]*(\w+)(?:\.[xyzwrgba]+)?[ \t]*(?:\+|-|\*|/)?=[^=]", re.M)

# Una funcion tambien escribe en lo que le pasan por `out`/`inout`, y eso no
# se parece a una asignacion. `auto_sway` llama `calNode(v_TexCoord, ...)` con
# el primer parametro `inout`: el driver corta con "assignment to varying" y la
# busqueda de asignaciones no lo ve venir.
_PARAM_SALIDA_RE = re.compile(r"\b(out|inout)\b")


def _posiciones_de_salida(body: str) -> dict[str, set[int]]:
    """Por funcion, en que posiciones escribe sus argumentos."""
    fuera: dict[str, set[int]] = {}
    for m in weglsl._FUNC_RE.finditer(body):
        crudo = m.group(3).strip()
        if crudo in ("", "void"):
            continue
        sale = {i for i, trozo in enumerate(crudo.split(","))
                if _PARAM_SALIDA_RE.search(trozo)}
        if sale:
            fuera[m.group(2)] = sale
    return fuera


def _varyings_por_argumento(body: str) -> set[str]:
    """Los identificadores que alguna funcion recibe por `out`/`inout`."""
    salidas = _posiciones_de_salida(body)
    if not salidas:
        return set()
    tocados: set[str] = set()
    for linea in body.splitlines():
        if linea.lstrip().startswith("#"):
            continue
        pos = 0
        while True:
            m = _LLAMADA_RE.search(linea, pos)
            if not m:
                break
            sale = salidas.get(m.group(1))
            corte = _corta_argumentos(linea, m.end() - 1) if sale else None
            if corte:
                for i, arg in enumerate(corte[0]):
                    nombre = arg.strip()
                    if i in sale and re.fullmatch(r"\w+", nombre):
                        tocados.add(nombre)
            pos = m.end()
    return tocados


def varying_escribible(body: str, stage: str) -> str:
    """Da una copia local, DENTRO de `main`, a los varying sobre los que escribe.

    En HLSL la entrada de un pixel shader es un parametro por valor y el codigo
    la modifica sin mas: `v_TexCoord += ...`. En GLSL un `in` es de solo lectura
    y el driver corta con "assignment to read-only variable".

    La copia va dentro de `main` y la DECLARACION NO SE TOCA. Renombrar el
    varying parecia mas simple y es justo lo que no se puede hacer: las etapas
    se casan POR NOMBRE, asi que un `v_TexCoord_in` en el fragment deja de
    recibir lo que el vertex escribe en `v_TexCoord` y el shader compila,
    ejecuta y muestrea en (0,0). En `3555933181` eso borro el personaje y las
    vidrieras dejando solo la lluvia, sin un solo aviso.
    """
    if stage != "frag":
        return body
    escritos = {m.group(1) for m in _ESCRIBE_VARYING_RE.finditer(body)}
    escritos |= _varyings_por_argumento(body)
    if not escritos:
        return body
    # El tipo de cada varying escrito Y las guardas del preprocesador que lo
    # rodean. Las guardas importan: si la declaracion vive dentro de
    # `#if QUAD_MASK` y la copia se emite fuera, con ese combo apagado la copia
    # apunta a una variable que no existe y el shader no compila. Pasa en
    # `auto_sway`.
    tipos: dict[str, str] = {}
    guardas: dict[str, list[str]] = {}
    pila: list[str] = []
    decl = re.compile(r"^[ \t]*(?:varying|in)[ \t]+(\w+)[ \t]+(\w+)[ \t]*;")
    for linea in body.splitlines():
        limpia = linea.strip()
        if COND_ABRE_RE.match(linea):
            pila.append(limpia)
        elif re.match(r"^[ \t]*#[ \t]*(elif|else)\b", linea):
            if pila:
                pila[-1] = limpia
        elif re.match(r"^[ \t]*#[ \t]*endif\b", linea):
            if pila:
                pila.pop()
        else:
            m = decl.match(linea)
            if m and m.group(2) in escritos:
                tipos[m.group(2)] = m.group(1)
                guardas[m.group(2)] = list(pila)
    if not tipos:
        return body

    # TODOS los `main`, no el primero. Un shader puede traer varias versiones
    # de `main` guardadas por `#if`, y como este traductor no resuelve el
    # preprocesador ---los `#define` los evalua el driver--- las tres estan en
    # el texto. `auto_sway` tiene tres: arreglando solo la primera, la que el
    # combo deje viva puede ser otra y el driver corta con "assignment to
    # varying". Se recorren de atras adelante para que los indices no se muevan.
    puntos = list(re.finditer(r"\bvoid[ \t]+main[ \t]*\([^)]*\)[ \t]*\{", body))
    if not puntos:
        return body
    def copia_de(n: str, t: str) -> str:
        dentro = guardas.get(n) or []
        abre = "".join(f"\n{c}" for c in dentro)
        cierra = "\n#endif" * len(dentro)
        return f"{abre}\n\t{t} {n}_rw = {n};{cierra}"

    copias = "".join(copia_de(n, t) for n, t in tipos.items())
    for m in reversed(puntos):
        fin = _grupo_llaves(body, m.end() - 1)
        if fin < 0:
            continue
        cuerpo = body[m.end():fin - 1]
        for nombre in tipos:
            cuerpo = re.sub(rf"\b{re.escape(nombre)}\b", f"{nombre}_rw", cuerpo)
        body = body[:m.end()] + copias + cuerpo + body[fin - 1:]
    return body


def _grupo_llaves(body: str, abre: int) -> int:
    """Indice justo detras de la llave que cierra la de `abre`, o -1."""
    prof, j = 0, abre
    while j < len(body):
        if body[j] == "{":
            prof += 1
        elif body[j] == "}":
            prof -= 1
            if prof == 0:
                return j + 1
        j += 1
    return -1


# `varying vec4 v_Size.xy;` --- con swizzle en el NOMBRE de la declaracion.
_DECL_SWIZZLE_RE = re.compile(
    r"^([ \t]*(?:varying|attribute|in|out)[ \t]+\w+[ \t]+\w+)\.[xyzwrgba]+[ \t]*;",
    re.M)


def declaracion_sin_swizzle(body: str) -> str:
    """Quita el swizzle pegado al nombre en una declaracion.

    No es un error de traduccion: lo escribe asi el autor. `frame_builder` de
    `3562154287` declara

        varying vec4 v_Size.xy; // xy = size, zw = alignment coord

    que no es valido ni en HLSL ni en GLSL --- el compilador de WE se lo traga y
    el del driver corta con "syntax error, unexpected DOT_TOK". El tipo
    declarado manda; el swizzle sobra, y los usos ya escriben `v_Size.xy` donde
    toca.
    """
    return _DECL_SWIZZLE_RE.sub(r"\1;", body)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


# Nodos que puede contener la expresion de un #if una vez sustituidas las
# macros. No se admite Name ni Call: si algo no se sustituyo, el arbol se
# rechaza en vez de evaluarse a ciegas.
_NODOS_COND = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Compare,
    ast.Constant, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.BitAnd, ast.BitOr, ast.BitXor, ast.Invert, ast.LShift, ast.RShift,
)

PRELUDE_DEFINE_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+(\w+)")
# Palabras que pueden abrir una linea seguidas de un identificador y un `(`
# sin que eso sea la definicion de una funcion: `return mod2(x, y);`.
_NO_ES_TIPO = {"return", "if", "while", "for", "else", "do", "switch", "case"}


def prelude_sin_colisiones(prelude: str, body: str) -> str:
    """El prelude de compatibilidad, menos lo que el shader ya define.

    Los `#define` de PRELUDE_COMPAT reconstruyen lo que WE inyecta, pero son
    macros con nombres corrientes y un shader puede declarar el suyo propio.
    Cuando eso pasa, el macro expande tambien la DECLARACION y la destroza:
    `float mod2(float x, float y)` se convierte en `float mod((float x), ...)`,
    que no es GLSL. Se cae el shader entero, y con el la capa.

    Ceder ante la definicion del shader es lo correcto ademas de lo seguro: si
    el autor se molesto en escribir la funcion, es la que WE compila.
    """
    fuera: list[str] = []
    for linea in prelude.splitlines():
        m = PRELUDE_DEFINE_RE.match(linea)
        if m and _define_propia(body, m.group(1)):
            fuera.append(f"// (omitido: el shader define {m.group(1)})")
            continue
        fuera.append(linea)
    return "\n".join(fuera)


def _define_propia(body: str, nombre: str) -> bool:
    """¿El shader declara ya ese nombre, como macro o como funcion?"""
    if re.search(rf"^[ \t]*#[ \t]*define[ \t]+{nombre}\b", body, re.M):
        return True
    for m in re.finditer(rf"^[ \t]*(\w+)[ \t]+{nombre}[ \t]*\(", body, re.M):
        if m.group(1) not in _NO_ES_TIPO:
            return True
    return False


REQUIRE_DIR_RE = re.compile(r"^[ \t]*#[ \t]*require\b[^\n]*$", re.M)
COND_ABRE_RE = re.compile(r"^[ \t]*#[ \t]*(ifdef|ifndef|if)\b([^\n]*)$")
COND_ELIF_RE = re.compile(r"^[ \t]*#[ \t]*elif\b([^\n]*)$")
COND_ELSE_RE = re.compile(r"^[ \t]*#[ \t]*else\b")
COND_FIN_RE = re.compile(r"^[ \t]*#[ \t]*endif\b")


def eval_conditional(expr: str, definidas: set[str],
                     values: dict[str, object]) -> bool | None:
    """Evalua la expresion de un `#if`. None = no se ha podido decidir.

    Reproduce la semantica del GLSL de escritorio, que es la que usa WE: una
    macro sin definir vale 0 dentro de un `#if`. Ante cualquier forma que no
    se entienda devuelve None, y quien llama debe dar la rama por viva: es el
    lado seguro, porque conserva el comportamiento anterior en vez de asumir
    que el codigo dudoso no se compila.
    """
    expr = _strip_comments(expr).strip()
    if not expr:
        return None

    expr = re.sub(r"\bdefined\s*\(\s*(\w+)\s*\)",
                  lambda m: "1" if m.group(1) in definidas else "0", expr)
    expr = re.sub(r"\bdefined\s+(\w+)",
                  lambda m: "1" if m.group(1) in definidas else "0", expr)

    fallo = False

    def macro(m: re.Match) -> str:
        nonlocal fallo
        v = values.get(m.group(0))
        if v is None:
            return "0"                     # sin definir vale 0
        if isinstance(v, bool):
            return str(int(v))
        if isinstance(v, (int, float)):
            return repr(v)
        fallo = True                       # una macro con valor no numerico
        return "0"

    expr = re.sub(r"\b[A-Za-z_]\w*\b", macro, expr)
    if fallo:
        return None

    # C -> Python. El `!` se traduce solo cuando no forma parte de `!=`.
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)
    try:
        # En modo eval un espacio al principio es IndentationError, y el `!`
        # traducido deja uno cuando la expresion empieza por negacion.
        arbol = ast.parse(expr.strip(), mode="eval")
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, _NODOS_COND):
                return None
        return bool(eval(compile(arbol, "<combo>", "eval"),
                         {"__builtins__": {}}, {}))
    except Exception:
        return None


def strip_dead_branches(body: str, values: dict[str, object]) -> str:
    """Devuelve el cuerpo sin las ramas que el preprocesador va a descartar.

    Este traductor NO resuelve los `#if`: los deja en el GLSL y los evalua el
    driver con los `#define` que emitimos delante. Eso esta bien para generar
    codigo, pero no para decidir si un shader usa algo que no sabemos
    traducir, porque entonces se mira tambien lo que nunca se va a compilar.

    Coste real de no hacerlo: las llamadas a `PerformLighting_V1` viven dentro
    de `#if LIGHTING`, un combo que el motor ya desactiva por no tener sistema
    de luces. Se abortaba el shader entero por una rama condenada, y con el se
    caia la capa base y todo lo que colgaba de ella: 16 wallpapers del corpus
    -- uno de cada ocho -- renderizaban completamente negros.
    """
    definidas = set(values) | set(DEFINE_RE.findall(body))
    vivas: list[str] = []
    pila: list[dict] = []

    for linea in body.splitlines():
        viva = pila[-1]["viva"] if pila else True

        m = COND_ABRE_RE.match(linea)
        if m:
            tipo, resto = m.group(1), m.group(2)
            if tipo == "if":
                cond = eval_conditional(resto, definidas, values)
            else:
                nombre = resto.strip().split()[0] if resto.strip() else ""
                cond = (nombre in definidas) if nombre else None
                if cond is not None and tipo == "ifndef":
                    cond = not cond
            dudosa = cond is None
            pila.append({"padre": viva, "dudosa": dudosa,
                         "tomada": cond is True,
                         "viva": viva and (True if dudosa else cond)})
            continue

        m = COND_ELIF_RE.match(linea)
        if m and pila:
            f = pila[-1]
            cond = eval_conditional(m.group(1), definidas, values)
            if cond is None:
                f["dudosa"] = True
            f["viva"] = f["padre"] and (
                True if f["dudosa"] else (not f["tomada"] and bool(cond)))
            f["tomada"] = f["tomada"] or cond is True
            continue

        if COND_ELSE_RE.match(linea) and pila:
            f = pila[-1]
            f["viva"] = f["padre"] and (True if f["dudosa"] else not f["tomada"])
            f["tomada"] = True
            continue

        if COND_FIN_RE.match(linea) and pila:
            pila.pop()
            continue

        if viva:
            vivas.append(linea)

    return "\n".join(vivas)


def translate(src: str,
              stage: str,
              resolver: Resolver,
              combos: dict[str, object] | None = None,
              target: str = DEFAULT_TARGET,
              varyings: dict[str, str] | None = None) -> str:
    """Traduce un shader de WE a GLSL compilable.

    stage: "vert" o "frag".
    combos: valores del pase de scene.json; pisan los defaults de [COMBO].
    target: "gl330" (por defecto) o "es320". Ver TARGETS.
    varyings: tipos que hay que forzar para que las dos etapas casen; los
        calcula `varyings_de_pase`, que es quien ve las dos fuentes.
    """
    if stage not in ("vert", "frag"):
        raise ShaderError(f"etapa desconocida: {stage!r}")
    if target not in TARGETS:
        raise ShaderError(f"objetivo desconocido: {target!r}")

    expanded = resolve_includes(normalise_newlines(src), resolver)

    # Los combos se declaran en comentarios, asi que hay que leerlos antes de
    # quitarlos. Y hay que mirar tambien dentro de los headers incluidos.
    values = parse_combos(expanded)
    values.update(combos or {})

    body = _strip_comments(expanded)
    body = forzar_varyings(body, varyings or {})

    # `#require X` declara una dependencia de un modulo del motor; no es GLSL y
    # el driver la rechaza como directiva desconocida. En el corpus solo
    # aparece `#require LightingV1`, en los 8 shaders con iluminacion, y ahi la
    # directiva no se borra: se cambia por el modulo que pide. El resto se van.
    body, luz_puesta = inyectar_lighting_v1(body)
    body = equilibrar_condicionales(body)
    body = declaracion_sin_swizzle(body)
    body = bool_a_float(body)
    body = const_no_constante(body)
    body = truncar_asignaciones(body)
    body = truncar_argumentos(body)
    body = condicion_a_bool(body)
    body = literales_de_llamada(body)
    body = literales_de_return(body)
    body = varying_escribible(body, stage)

    # GLSL ES 3 sustituye varying/attribute por in/out, con sentido opuesto
    # segun la etapa.
    if stage == "vert":
        body = re.sub(r"\battribute\b", "in", body)
        body = re.sub(r"\bvarying\b", "out", body)
    else:
        if re.search(r"\battribute\b", body):
            raise ShaderError("un fragment shader no puede declarar attribute")
        body = re.sub(r"\bvarying\b", "in", body)

    # gl_FragColor desaparece en GLES 3. No se puede hacer #define sobre un
    # nombre gl_*: el preprocesador de GLSL los tiene reservados.
    if stage == "frag":
        body = re.sub(r"\bgl_FragColor\b", "wpFragColor", body)
        body = re.sub(r"\bgl_FragData\s*\[\s*0\s*\]", "wpFragColor", body)

    # Un combo a 0 significa "apagado", y la traduccion correcta es NO definir
    # la macro. Definirla a 0 rompe los shaders que preguntan con #ifdef en vez
    # de #if: #ifdef solo mira si existe, no su valor, asi que `#define X 0`
    # activa la rama que deberia quedar fuera. Es lo que metia BONECOUNT en
    # genericimage2.vert, el pase base de practicamente toda imagen.
    #
    # Omitirlas es seguro en GLSL de escritorio porque ahi una macro indefinida
    # dentro de #if se evalua como 0. En GLSL ES eso es error, asi que ese
    # objetivo tiene que declararlas y se come el problema del #ifdef.
    # Pero solo se puede omitir si el combo se consulta con #ifdef/defined().
    # Muchos se usan ademas como valor dentro del codigo -- ApplyBlending(
    # BLENDMODE, ...) -- y ahi quitar el #define deja un identificador sin
    # declarar. Hay que mirar como lo pregunta cada shader, no decidirlo global.
    if target == "es320":
        for name in undefined_conditionals(body, set(values)):
            values.setdefault(name, 0)
    else:
        ifdef_only = set(IFDEF_RE.findall(body)) | set(DEFINED_RE.findall(body))
        values = {k: v for k, v in values.items()
                  if v not in (0, False) or k not in ifdef_only}

    # Lo que no sabemos traducir solo importa si se va a compilar. La revision
    # va aqui, y no antes, porque necesita `values` ya cerrado: es el juego de
    # #define que vera el driver y, por tanto, lo que decide que ramas viven.
    vivo = strip_dead_branches(body, values)
    for name, why in UNSUPPORTED.items():
        if re.search(rf"\b{name}\b", vivo):
            raise ShaderError(f"usa {name}: {why}")

    # La iluminacion viva sin la funcion detras es el mismo caso que UNSUPPORTED
    # ---el driver fallaria al enlazar, no al compilar, que es mas dificil de
    # leer--- pero solo si la rama sobrevive a los combos de este pase.
    if not luz_puesta and re.search(r"\bPerformLighting_V1\b", vivo):
        raise ShaderError("usa PerformLighting_V1 y no incluye common_pbr_2.h, "
                          "que es donde vive el termino por luz")

    # WE declara los samplers g_TextureN segun los slots enlazados en el pase,
    # asi que hay shaders que los usan sin declararlos. Se declaran los que
    # falten, junto con los uniforms de tamano que WE genera en paralelo.
    body, hoisted = hoist_uniforms(body)
    hoisted = quitar_uniforms_muertos(body, hoisted)

    declared = set(re.findall(r"\buniform\s+\w+\s+(\w+)", body))
    declared.update(re.findall(r"\buniform\s+\w+\s+(\w+)", "\n".join(hoisted)))
    used_tex = set(re.findall(r"\b(g_Texture\d+)\b", body))
    auto: list[str] = []
    for name in sorted(used_tex - declared):
        auto.append(f"uniform sampler2D {name};")
    for extra, gtype in (("Resolution", "vec4"), ("Texel", "vec4"), ("Rotation", "vec4")):
        for name in sorted(re.findall(rf"\b(g_Texture\d+{extra})\b", body)):
            if name not in declared:
                auto.append(f"uniform {gtype} {name};")

    # `sample` es palabra reservada en GLSL ES pero no en el de escritorio, y
    # los shaders de WE la usan como nombre de variable.
    if target == "es320":
        body = re.sub(r"\bsample\b", "wpSample", body)

    parts = [TARGETS[target]]
    if target == "gl330":
        # HLSL inicializa arrays con llaves --- `vec2 v[3] = { vec2(0, 0), ... }`
        # --- y en GLSL 330 eso es la extension 420pack. Mesa y NVIDIA la tienen;
        # con `enable` el driver que no la tenga avisa y sigue, en vez de cortar.
        parts.append("#extension GL_ARB_shading_language_420pack : enable")
    if target == "es320":
        parts.append(PRELUDE_PRECISION)
    parts.append(prelude_sin_colisiones(PRELUDE_COMPAT, body))
    if values:
        parts.append("\n// ── combos ──")
        for k in sorted(values):
            v = values[k]
            parts.append(f"#define {k} {int(v) if isinstance(v, bool) else v}")
    if stage == "frag":
        parts.append(FRAG_OUTPUT)
    if hoisted:
        parts.append("\n// ── uniforms izados ──")
        parts.extend(hoisted)
    if auto:
        parts.append("\n// ── samplers declarados por el motor ──")
        parts.extend(auto)
    parts.append("\n// ── shader ──")
    parts.append(body)
    return "\n".join(parts)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = Path(sys.argv[1])
    we = wepaths.we_assets()
    resolver = Resolver(roots=[src.parent, src.parent.parent, we, we / "shaders"])
    stage = "vert" if src.suffix == ".vert" else "frag"
    out = translate(src.read_text(errors="replace"), stage, resolver)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(out)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
