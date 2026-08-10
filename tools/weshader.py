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

#define texSample2D(s, uv) texture((s), (uv))
#define texSample2DLod(s, uv, lod) textureLod((s), (uv), (lod))
#define texSample2DBackBuffer(s, uv) texture((s), (uv))
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
    "PerformLighting_V1": "funcion de iluminacion no presente en los assets",
}

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

REQUIRE_RE = re.compile(r"^[ \t]*#[ \t]*require\b[^\n]*$", re.M)
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
              target: str = DEFAULT_TARGET) -> str:
    """Traduce un shader de WE a GLSL compilable.

    stage: "vert" o "frag".
    combos: valores del pase de scene.json; pisan los defaults de [COMBO].
    target: "gl330" (por defecto) o "es320". Ver TARGETS.
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

    # `#require X` declara una dependencia de un modulo del motor; no es GLSL y
    # el driver la rechaza como directiva desconocida. Se emite siempre a nivel
    # superior, aunque lo que la necesita este dentro de un `#if`, asi que no
    # sirve para decidir nada: quien decide es el escaneo de UNSUPPORTED sobre
    # las ramas vivas. En el corpus solo aparece `#require LightingV1`, en los
    # 8 shaders con iluminacion.
    body = REQUIRE_RE.sub("", body)

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

    # WE declara los samplers g_TextureN segun los slots enlazados en el pase,
    # asi que hay shaders que los usan sin declararlos. Se declaran los que
    # falten, junto con los uniforms de tamano que WE genera en paralelo.
    body, hoisted = hoist_uniforms(body)

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
    if target == "es320":
        parts.append(PRELUDE_PRECISION)
    parts.append(PRELUDE_COMPAT)
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
