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

# Tipo base de cada tipo declarado. Hace falta aparte del ancho porque `%`
# exige enteros en GLSL y en HLSL vale tambien sobre flotantes.
BASE_TIPO = {t: ("float" if t in ("float", "double") or t.startswith(("vec", "dvec"))
                 else "int" if t == "int" or t.startswith("ivec")
                 else "uint" if t == "uint" or t.startswith("uvec")
                 else "bool")
             for t in ANCHO_TIPO}

# Tipo base que devuelven los builtins cuyo resultado no es el de sus
# argumentos. El resto propaga, igual que con el ancho.
BASE_FIJA = {
    "dot": "float", "length": "float", "distance": "float",
    "determinant": "float", "cross": "float",
    "texture": "float", "textureLod": "float", "texelFetch": "float",
    "textureGrad": "float", "textureProj": "float", "textureSize": "int",
    "all": "bool", "any": "bool", "not": "bool",
    "greaterThan": "bool", "greaterThanEqual": "bool", "lessThan": "bool",
    "lessThanEqual": "bool", "equal": "bool", "notEqual": "bool",
    "texSample2D": "float", "texSample2DLod": "float",
    "texSample2DBackBuffer": "float", "texSample3D": "float",
    "texSampleCube": "float", "texLoad2D": "float", "SampleLevel": "float",
    "texSample2DCompare": "float",
    "CAST2": "float", "CAST3": "float", "CAST4": "float",
    "CASTF": "float", "CASTI": "int", "CASTU": "uint",
    "float": "float", "int": "int", "uint": "uint", "bool": "bool",
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
    """Precedencia por escalada. Devuelve tipos, no arboles.

    Un tipo es la pareja `(base, ancho)` --- p.ej. `("float", 3)` para vec3 ---
    o None. None se propaga: si una subexpresion no se entiende, la expresion
    entera queda sin determinar. Esa distincion entre "no lo se" y un valor
    concreto es lo que permite ser conservador aguas arriba.
    """

    def __init__(self, tokens, tabla, funciones, permisivo=False):
        self.t = tokens
        self.i = 0
        self.tabla = tabla
        self.funciones = funciones
        # Con `permisivo`, un operador entre vectores de ancho distinto no
        # invalida la expresion: se anota el recorte que HLSL haria y se sigue
        # con el ancho menor. Apagado ---lo normal--- el parser responde None,
        # que es lo que hace seguro a todo lo que se apoya en `tipo`.
        self.permisivo = permisivo
        self.recortes: list[tuple[int, int, int]] = []

    def ojear(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def comer(self):
        tok = self.ojear()
        if tok is not None:
            self.i += 1
        return tok

    # ── niveles de precedencia, de menor a mayor ──────────────────────────
    def expresion(self):
        return self.ternario()

    def ternario(self):
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
        return (_base_comun(a[0], b[0]), max(a[1], b[1]))

    def logico(self):
        izq = self.comparacion()
        while self.ojear() in ("&&", "||", "^^"):
            self.comer()
            der = self.comparacion()
            if izq is None or der is None:
                return None
            izq = ("bool", 1)
        return izq

    def comparacion(self):
        izq = self.aditivo()
        while self.ojear() in ("<", ">", "<=", ">=", "==", "!="):
            self.comer()
            der = self.aditivo()
            if izq is None or der is None:
                return None
            izq = ("bool", 1)
        return izq

    def aditivo(self):
        ini = self.i
        izq = self.multiplicativo()
        while self.ojear() in ("+", "-"):
            medio = self.i
            self.comer()
            ini_der = self.i
            der = self.multiplicativo()
            izq = self._combinar(izq, der, ini, medio, ini_der, self.i)
            ini = ini      # el operando izquierdo sigue empezando donde empezo
        return izq

    def multiplicativo(self):
        ini = self.i
        izq = self.unario()
        while self.ojear() in ("*", "/", "%"):
            medio = self.i
            self.comer()
            ini_der = self.i
            der = self.unario()
            izq = self._combinar(izq, der, ini, medio, ini_der, self.i)
        return izq

    def _combinar(self, a, b, ini_a=None, fin_a=None, ini_b=None, fin_b=None):
        """Escalar con vector da el vector; vector con vector exige igualdad.

        Cuando los dos son vectores de ancho distinto, GLSL lo rechaza y HLSL
        se queda con el mas estrecho. Aqui se anota que operando habria que
        recortar --- y donde esta --- y se sigue con el ancho menor, para que la
        expresion entera se pueda seguir tipando.
        """
        if a is None or b is None:
            return None
        base = _base_comun(a[0], b[0])
        if base is None:
            return None
        if a[1] == 1:
            return (base, b[1])
        if b[1] == 1:
            return (base, a[1])
        if a[1] == b[1]:
            return (base, a[1])
        if not self.permisivo or ini_a is None:
            return None
        estrecho = min(a[1], b[1])
        if a[1] > estrecho:
            self.recortes.append((ini_a, fin_a, estrecho))
        else:
            self.recortes.append((ini_b, fin_b, estrecho))
        return (base, estrecho)

    def unario(self):
        while self.ojear() in ("-", "+", "!", "~", "++", "--"):
            self.comer()
        return self.sufijo()

    def sufijo(self):
        val = self.primario()
        while True:
            tok = self.ojear()
            if tok == ".":
                self.comer()
                campo = self.comer()
                if not campo or not set(campo) <= COMPONENTES or val is None:
                    return None          # no es un swizzle: fuera
                val = (val[0], len(campo))
            elif tok == "[":
                self.comer()
                prof = 1
                while prof and self.i < len(self.t):
                    c = self.comer()
                    prof += (c == "[") - (c == "]")
                if prof or val is None:
                    return None
                # Indexar un vector da un escalar. Sobre una matriz daria un
                # vector, pero las matrices no entran en este analisis.
                val = (val[0], 1)
            elif tok in ("++", "--"):
                self.comer()
            else:
                return val

    def primario(self):
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
            # `1` es int, `1.0` float y `1u` uint: la distincion importa
            # porque `%` solo acepta enteros.
            if tok[-1] in "uU":
                return ("uint", 1)
            return ("float", 1) if ("." in tok or "e" in tok or "E" in tok) else ("int", 1)
        if not re.fullmatch(r"[A-Za-z_]\w*", tok):
            return None
        if self.ojear() == "(":          # llamada o constructor
            args = self._argumentos()
            if args is None:
                return None
            if tok in ANCHO_TIPO:
                return (BASE_TIPO[tok], ANCHO_TIPO[tok])
            if tok in TIPOS_OPACOS:
                return None
            if tok in BUILTIN_FIJO:
                return (BASE_FIJA.get(tok, "float"), BUILTIN_FIJO[tok])
            if tok in self.funciones:
                return self.funciones[tok]
            if tok in BUILTIN_PROPAGA:
                validos = [a for a in args if a is not None]
                if len(validos) != len(args) or not validos:
                    return None
                base = BASE_FIJA.get(tok)
                if base is None:
                    base = _base_comun(*[a[0] for a in validos]) if validos else None
                if base is None:
                    return None
                return (base, max(a[1] for a in validos))
            return None                  # funcion desconocida
        return self.tabla.get(tok)

    def _argumentos(self):
        if self.comer() != "(":
            return None
        args = []
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


def _base_comun(*bases):
    """Tipo base al que promocionan varios: float gana, luego uint, luego int."""
    bs = [b for b in bases if b is not None]
    if len(bs) != len(bases) or not bs:
        return None
    if "float" in bs:
        return "float"
    if "uint" in bs:
        return "uint"
    if "int" in bs:
        return "int"
    return "bool"


def tipo(expr: str, tabla: dict, funciones: dict | None = None):
    """`(base, ancho)` de la expresion, o None si no se puede afirmar."""
    tokens = tokenizar(expr)
    if tokens is None:
        return None
    p = _Parser(tokens, tabla, funciones or {})
    val = p.expresion()
    return val if p.i == len(tokens) else None      # sobra texto: no fiarse


_SWZ = "xyzw"


def truncar(expr: str, tabla: dict, funciones: dict | None = None) -> str | None:
    """Aplica la truncacion implicita de HLSL a los operadores de la expresion.

    `saturate(depth) * pixelSize` con `depth` vec4 y `pixelSize` vec2 es legal
    en HLSL --- se queda con las dos primeras componentes del ancho --- y GLSL
    lo rechaza con "vector size mismatch". Aqui se reescribe como
    `(saturate(depth)).xy * pixelSize`.

    Devuelve None si no hay nada que recortar o si la expresion no se entiende;
    quien llama se queda entonces con el texto original. El recorte se calcula
    con el parser, no con una expresion regular: hay que saber DONDE empieza y
    acaba cada operando, y eso una busqueda plana no lo sabe.
    """
    tokens = tokenizar(expr)
    if tokens is None:
        return None
    p = _Parser(tokens, tabla, funciones or {}, permisivo=True)
    val = p.expresion()
    if val is None or p.i != len(tokens) or not p.recortes:
        return None
    # De dentro hacia fuera, para que los indices de los tramos no se muevan.
    fuera = list(tokens)
    for ini, fin, ancho_ in sorted(p.recortes, key=lambda r: -r[0]):
        if ini >= fin or fin > len(fuera):
            return None
        tramo = " ".join(fuera[ini:fin])
        fuera[ini:fin] = [f"({tramo}).{_SWZ[:ancho_]}"]
    return " ".join(fuera)


def ancho(expr: str, tabla: dict, funciones: dict | None = None) -> int | None:
    """Solo el ancho. Envoltorio sobre `tipo` para el uso mas comun."""
    t = tipo(expr, tabla, funciones)
    return t[1] if t else None


_FUNC_RE = re.compile(
    r"^[ \t]*(?:(?:const|highp|mediump|lowp)[ \t]+)*"
    r"(\w+)[ \t]+(\w+)[ \t]*\(([^)]*)\)[ \t]*\{", re.M)
_DECL_VAR_RE = re.compile(
    r"^[ \t]*(?:(?:const|highp|mediump|lowp|flat|smooth|noperspective|"
    r"uniform|in|out|inout|attribute|varying)[ \t]+)*"
    r"(\w+)[ \t]+(\w+)[ \t]*(?:=|;)")


def tabla_de_funciones(body: str) -> dict[str, tuple[str, int]]:
    """Tipo de retorno de las funciones que el propio shader declara."""
    fuera: dict[str, tuple[str, int]] = {}
    for m in _FUNC_RE.finditer(body):
        if m.group(1) in ANCHO_TIPO:
            fuera[m.group(2)] = (BASE_TIPO[m.group(1)], ANCHO_TIPO[m.group(1)])
    return fuera


def tabla_global(body: str) -> dict[str, tuple[str, int]]:
    """Uniforms, varyings y globales: lo visible desde cualquier funcion."""
    fuera: dict[str, tuple[str, int]] = {}
    prof = 0
    for linea in body.splitlines():
        if prof == 0:
            m = _DECL_VAR_RE.match(linea)
            if m and m.group(1) in ANCHO_TIPO:
                fuera.setdefault(m.group(2),
                                 (BASE_TIPO[m.group(1)], ANCHO_TIPO[m.group(1)]))
        prof += linea.count("{") - linea.count("}")
        prof = max(prof, 0)
    return fuera
