#!/usr/bin/env python3
"""Inferencia del ANCHO de una expresion GLSL, en componentes (1..4).

No es un compilador ni pretende serlo. Responde a una sola pregunta --- cuantas
componentes produce esta expresion --- que es lo unico que hace falta para
aplicar la truncacion implicita de HLSL, la familia mas grande de shaders que
no compilan.

La regla de oro es devolver **None ante cualquier duda**. Un intento anterior
infirio el ancho barriendo identificadores y tomando el maximo: rompio 124
variantes que ya compilaban, porque un barrido plano no distingue las funciones
que REDUCEN el ancho de las que lo propagan --- `dot(delta, delta)` devuelve un
escalar y le pegaba un `.x` a un float. De ahi que aqui haya un parser de
verdad, y que "no lo se" sea un resultado de primera clase distinto de "es 1".

El corpus ayuda: sus 570 variantes usan 31 builtins de GLSL, declaran 138
funciones propias --- cuyo tipo de retorno esta en su propia declaracion --- y
NINGUNA usa `struct`, que es la parte cara de inferir tipos.
"""

from __future__ import annotations

import re

# Ancho de los tipos escalares y vectoriales. Las matrices quedan fuera a
# proposito: no hacen falta para truncar y su algebra complica el analisis.
ANCHO_TIPO = {
    "float": 1, "int": 1, "uint": 1, "bool": 1, "double": 1,
    "vec2": 2, "ivec2": 2, "uvec2": 2, "bvec2": 2, "dvec2": 2,
    "vec3": 3, "ivec3": 3, "uvec3": 3, "bvec3": 3, "dvec3": 3,
    "vec4": 4, "ivec4": 4, "uvec4": 4, "bvec4": 4, "dvec4": 4,
}
TIPOS_OPACOS = ("mat2", "mat3", "mat4", "mat2x2", "mat3x3", "mat4x4",
                "sampler2D", "sampler3D", "samplerCube", "void")

COMPONENTES = set("xyzwrgbastpq")

# Builtins cuyo ancho NO es el maximo de sus argumentos. Todo lo que no este
# aqui y sea conocido propaga, que es la regla de las funciones genType.
BUILTIN_FIJO = {
    "dot": 1, "length": 1, "distance": 1, "determinant": 1,
    "all": 1, "any": 1,
    "cross": 3,
    "texture": 4, "textureLod": 4, "texelFetch": 4, "textureGrad": 4,
    "textureProj": 4, "textureSize": 2,
}
BUILTIN_PROPAGA = {
    "abs", "acos", "asin", "atan", "ceil", "clamp", "cos", "cosh", "degrees",
    "dFdx", "dFdy", "exp", "exp2", "faceforward", "floor", "fract", "fwidth",
    "inversesqrt", "log", "log2", "max", "min", "mix", "mod", "modf",
    "normalize", "pow", "radians", "reflect", "refract", "round", "roundEven",
    "sign", "sin", "sinh", "smoothstep", "sqrt", "step", "tan", "tanh",
    "trunc", "matrixCompMult", "greaterThan", "greaterThanEqual", "lessThan",
    "lessThanEqual", "equal", "notEqual", "not",
    # Del prelude de compatibilidad: se expanden a lo de arriba.
    "frac", "lerp", "saturate", "atan2", "ddx", "ddy", "rsqrt", "fmod",
    "mod2", "mul", "CASTF", "CASTU", "CASTI",
}
# Macros del prelude con ancho fijo.
BUILTIN_FIJO.update({
    "texSample2D": 4, "texSample2DLod": 4, "texSample2DBackBuffer": 4,
    "texSample3D": 4, "texSampleCube": 4, "texLoad2D": 4, "SampleLevel": 4,
    "texSample2DCompare": 4,
    "CAST2": 2, "CAST3": 3, "CAST4": 4,
})

_TOKEN_RE = re.compile(r"""
    (?P<num>\d+\.\d*(?:[eE][-+]?\d+)?[fF]?|\.\d+(?:[eE][-+]?\d+)?[fF]?|\d+[uU]?)
  | (?P<ident>[A-Za-z_]\w*)
  | (?P<op><<=|>>=|<=|>=|==|!=|&&|\|\||\+\+|--|[-+*/%<>=!&|^~?:.,;()\[\]{}])
  | (?P<ws>\s+)
""", re.X)


def tokenizar(src: str) -> list[str] | None:
    """Lista de tokens, o None si aparece algo que no se reconoce."""
    fuera, i = [], 0
    while i < len(src):
        m = _TOKEN_RE.match(src, i)
        if not m:
            return None
        if not m.group("ws"):
            fuera.append(m.group(0))
        i = m.end()
    return fuera


class _Parser:
    """Precedencia por escalada. Devuelve anchos, no arboles.

    Cada metodo devuelve un ancho (1..4) o None. None se propaga: si una
    subexpresion no se entiende, la expresion entera queda sin determinar.
    """

    def __init__(self, tokens: list[str], tabla: dict[str, int],
                 funciones: dict[str, int]):
        self.t = tokens
        self.i = 0
        self.tabla = tabla
        self.funciones = funciones

    def ojear(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def comer(self) -> str | None:
        tok = self.ojear()
        if tok is not None:
            self.i += 1
        return tok

    # ── niveles de precedencia, de menor a mayor ──────────────────────────
    def expresion(self) -> int | None:
        return self.ternario()

    def ternario(self) -> int | None:
        cond = self.logico()
        if self.ojear() != "?":
            return cond
        self.comer()
        a = self.expresion()
        if self.ojear() != ":":
            return None
        self.comer()
        b = self.expresion()
        if a is None or b is None:
            return None
        return max(a, b)

    def logico(self) -> int | None:
        izq = self.comparacion()
        while self.ojear() in ("&&", "||", "^^"):
            self.comer()
            der = self.comparacion()
            if izq is None or der is None:
                return None
            izq = 1                      # los logicos dan un bool escalar
        return izq

    def comparacion(self) -> int | None:
        izq = self.aditivo()
        while self.ojear() in ("<", ">", "<=", ">=", "==", "!="):
            self.comer()
            der = self.aditivo()
            if izq is None or der is None:
                return None
            izq = 1                      # comparar da bool escalar
        return izq

    def aditivo(self) -> int | None:
        izq = self.multiplicativo()
        while self.ojear() in ("+", "-"):
            self.comer()
            der = self.multiplicativo()
            izq = self._combinar(izq, der)
        return izq

    def multiplicativo(self) -> int | None:
        izq = self.unario()
        while self.ojear() in ("*", "/", "%"):
            self.comer()
            der = self.unario()
            izq = self._combinar(izq, der)
        return izq

    @staticmethod
    def _combinar(a: int | None, b: int | None) -> int | None:
        """Escalar con vector da el vector; vector con vector exige igualdad."""
        if a is None or b is None:
            return None
        if a == 1:
            return b
        if b == 1:
            return a
        return a if a == b else None

    def unario(self) -> int | None:
        while self.ojear() in ("-", "+", "!", "~", "++", "--"):
            self.comer()
        return self.sufijo()

    def sufijo(self) -> int | None:
        val = self.primario()
        while True:
            tok = self.ojear()
            if tok == ".":
                self.comer()
                campo = self.comer()
                if not campo or not set(campo) <= COMPONENTES:
                    return None          # no es un swizzle: fuera
                val = len(campo)
            elif tok == "[":
                self.comer()
                prof = 1
                while prof and self.i < len(self.t):
                    c = self.comer()
                    prof += (c == "[") - (c == "]")
                if prof:
                    return None
                # Indexar un vector da un escalar. Sobre una matriz daria un
                # vector, pero las matrices no entran en este analisis.
                val = 1 if val is not None else None
            elif tok in ("++", "--"):
                self.comer()
            else:
                return val

    def primario(self) -> int | None:
        tok = self.comer()
        if tok is None:
            return None
        if tok == "(":
            val = self.expresion()
            if self.ojear() != ")":
                return None
            self.comer()
            return val
        if re.fullmatch(r"[\d.].*", tok):
            return 1                     # literal numerico
        if not re.fullmatch(r"[A-Za-z_]\w*", tok):
            return None
        if self.ojear() == "(":          # llamada o constructor
            args = self._argumentos()
            if args is None:
                return None
            if tok in ANCHO_TIPO:
                return ANCHO_TIPO[tok]
            if tok in TIPOS_OPACOS:
                return None
            if tok in BUILTIN_FIJO:
                return BUILTIN_FIJO[tok]
            if tok in self.funciones:
                return self.funciones[tok]
            if tok in BUILTIN_PROPAGA:
                validos = [a for a in args if a is not None]
                if len(validos) != len(args) or not validos:
                    return None
                return max(validos)
            return None                  # funcion desconocida
        return self.tabla.get(tok)

    def _argumentos(self) -> list[int | None] | None:
        if self.comer() != "(":
            return None
        args: list[int | None] = []
        if self.ojear() == ")":
            self.comer()
            return args
        while True:
            args.append(self.expresion())
            tok = self.comer()
            if tok == ")":
                return args
            if tok != ",":
                return None


def ancho(expr: str, tabla: dict[str, int],
          funciones: dict[str, int] | None = None) -> int | None:
    """Ancho de la expresion, o None si no se puede afirmar."""
    tokens = tokenizar(expr)
    if tokens is None:
        return None
    p = _Parser(tokens, tabla, funciones or {})
    val = p.expresion()
    return val if p.i == len(tokens) else None      # sobra texto: no fiarse


_FUNC_RE = re.compile(
    r"^[ \t]*(?:(?:const|highp|mediump|lowp)[ \t]+)*"
    r"(\w+)[ \t]+(\w+)[ \t]*\(([^)]*)\)[ \t]*\{", re.M)
_DECL_VAR_RE = re.compile(
    r"^[ \t]*(?:(?:const|highp|mediump|lowp|flat|smooth|noperspective|"
    r"uniform|in|out|inout|attribute|varying)[ \t]+)*"
    r"(\w+)[ \t]+(\w+)[ \t]*(?:=|;)")


def tabla_de_funciones(body: str) -> dict[str, int]:
    """Ancho de retorno de las funciones que el propio shader declara."""
    fuera: dict[str, int] = {}
    for m in _FUNC_RE.finditer(body):
        if m.group(1) in ANCHO_TIPO:
            fuera[m.group(2)] = ANCHO_TIPO[m.group(1)]
    return fuera


def tabla_global(body: str) -> dict[str, int]:
    """Uniforms, varyings y globales: lo visible desde cualquier funcion."""
    fuera: dict[str, int] = {}
    prof = 0
    for linea in body.splitlines():
        if prof == 0:
            m = _DECL_VAR_RE.match(linea)
            if m and m.group(1) in ANCHO_TIPO:
                fuera.setdefault(m.group(2), ANCHO_TIPO[m.group(1)])
        prof += linea.count("{") - linea.count("}")
        prof = max(prof, 0)
    return fuera
