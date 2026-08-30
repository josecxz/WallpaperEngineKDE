#!/usr/bin/env python3
"""Los scripts de las capas de texto: qué escriben, y en qué instante.

148 de los 172 objetos de texto del corpus no traen una cadena sino un
**script**: `export function update(value)` que devuelve lo que hay que
dibujar. 133 llaman a `new Date`. Son relojes y fechas, y sin ejecutarlos lo
que se dibuja es el `value` que el autor tenía en pantalla al guardar --- las
12:34 de un día de 2021.

No hay motor de JavaScript en esta máquina, y meter uno como dependencia de un
fondo de escritorio no sale a cuenta. Pero tampoco hace falta: el vocabulario
que usan estos 51 scripts distintos es diminuto y cerrado ---`if`, `for`,
`switch`, `let`, aritmética, concatenación, los getters de `Date` y un puñado
de métodos de cadena---, así que este módulo lo interpreta.

**El evaluador no basta**, y esa es la parte que importa del diseño. Ejecutar
el script una vez al preparar el plan solo cambia una hora congelada de 2021
por una congelada de hoy. Lo que el motor necesita es el **formato**: qué
trozos de la cadena son literales y qué trozos son un campo del reloj, para
que el ejecutor la rehaga cada fotograma sin volver a pasar por aquí. De eso
se encarga `formato_de`, que lo deduce y **lo comprueba**: solo declara un
reloj cuando el formato reproduce lo que devuelve el script en ~1050 instantes
repartidos por cuatro años. Si algo no cuadra, se queda el `value` de siempre.

Uso:
    python3 tools/wescript.py            # barrido: qué scripts del corpus salen
    python3 tools/wescript.py <id>       # y el detalle de un wallpaper
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


class ScriptError(Exception):
    """El script usa algo que este intérprete no cubre."""


# ── léxico ──────────────────────────────────────────────────────────────────

# Los operadores largos van antes que los cortos: `===` tiene que ganarle a
# `==`, y `>=` a `>`.
_OPERADORES = [
    "===", "!==", "**=", "...", "=>",
    "==", "!=", "<=", ">=", "&&", "||", "??", "++", "--",
    "+=", "-=", "*=", "/=", "%=", "|=", "&=",
    "{", "}", "(", ")", "[", "]", ";", ",", ".", ":", "?",
    "+", "-", "*", "/", "%", "<", ">", "=", "!", "&", "|", "^", "~",
]

_NUM_RE = re.compile(r"(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass
class Token:
    tipo: str          # num | str | plantilla | ident | op | fin
    valor: object
    pos: int


def _lee_cadena(src: str, i: int) -> tuple[str, int]:
    """Una cadena entre comillas simples o dobles, con escapes."""
    cierre = src[i]
    i += 1
    salida = []
    while i < len(src):
        c = src[i]
        if c == "\\":
            salida.append(_escape(src, i))
            i += _largo_escape(src, i)
            continue
        if c == cierre:
            return "".join(salida), i + 1
        salida.append(c)
        i += 1
    raise ScriptError("cadena sin cerrar")


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\",
            "'": "'", '"': '"', "`": "`", "b": "\b", "f": "\f", "v": "\v"}


def _largo_escape(src: str, i: int) -> int:
    """Cuántos caracteres ocupa el escape que empieza en `i`."""
    c = src[i + 1:i + 2]
    return 6 if c == "u" else 4 if c == "x" else 2


def _escape(src: str, i: int) -> str:
    c = src[i + 1]
    if c == "u":
        return chr(int(src[i + 2:i + 6], 16))
    if c == "x":
        return chr(int(src[i + 2:i + 4], 16))
    return _ESCAPES.get(c, c)


def _lee_plantilla(src: str, i: int) -> tuple[list, int]:
    """Una plantilla `a${expr}b` -> lista de trozos: str o ('expr', fuente)."""
    i += 1
    trozos: list = []
    literal: list[str] = []
    while i < len(src):
        c = src[i]
        if c == "\\":
            literal.append(_escape(src, i))
            i += _largo_escape(src, i)
            continue
        if c == "`":
            trozos.append("".join(literal))
            return trozos, i + 1
        if c == "$" and src[i + 1:i + 2] == "{":
            trozos.append("".join(literal))
            literal = []
            j, hondo = i + 2, 1
            while j < len(src) and hondo:
                if src[j] == "{":
                    hondo += 1
                elif src[j] == "}":
                    hondo -= 1
                j += 1
            trozos.append(("expr", src[i + 2:j - 1]))
            i = j
            continue
        literal.append(c)
        i += 1
    raise ScriptError("plantilla sin cerrar")


def tokenizar(src: str) -> list[Token]:
    toks: list[Token] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i):
            i = src.find("\n", i)
            if i < 0:
                break
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i)
            if j < 0:
                break
            i = j + 2
            continue
        if c in "'\"":
            s, i = _lee_cadena(src, i)
            toks.append(Token("str", s, i))
            continue
        if c == "`":
            trozos, i = _lee_plantilla(src, i)
            toks.append(Token("plantilla", trozos, i))
            continue
        m = _NUM_RE.match(src, i)
        if m and (c.isdigit() or (c == "." and src[i + 1:i + 2].isdigit())):
            texto = m.group(0)
            val = int(texto, 16) if texto[:2].lower() == "0x" else float(texto)
            toks.append(Token("num", val, i))
            i = m.end()
            continue
        m = _IDENT_RE.match(src, i)
        if m:
            toks.append(Token("ident", m.group(0), i))
            i = m.end()
            continue
        for op in _OPERADORES:
            if src.startswith(op, i):
                toks.append(Token("op", op, i))
                i += len(op)
                break
        else:
            # Una expresión regular literal. No se interpreta ninguna, pero hay
            # que reconocerla para no confundir su `/` con una división.
            raise ScriptError(f"carácter inesperado {c!r}")
    toks.append(Token("fin", None, n))
    return toks


# ── sintaxis ────────────────────────────────────────────────────────────────
#
# El AST son tuplas: ("nombre", ...). No hay clases porque no hay nada que
# colgarles: el evaluador es un `match` sobre el primer elemento.

_PRECEDENCIA = {
    "||": 1, "??": 1, "&&": 2,
    "|": 3, "^": 4, "&": 5,
    "==": 6, "!=": 6, "===": 6, "!==": 6,
    "<": 7, ">": 7, "<=": 7, ">=": 7,
    "+": 9, "-": 9,
    "*": 10, "/": 10, "%": 10,
}

_ASIGNACIONES = {"=", "+=", "-=", "*=", "/=", "%=", "|=", "&="}

_PALABRAS = {"let", "var", "const", "if", "else", "return", "function", "new",
             "for", "while", "switch", "case", "default", "break", "continue",
             "typeof", "export", "import", "of", "in", "do", "class"}


class Parser:
    def __init__(self, toks: list[Token]):
        self.t = toks
        self.i = 0

    # --- utilidades
    def mira(self, k: int = 0) -> Token:
        j = self.i + k
        return self.t[j] if j < len(self.t) else self.t[-1]

    def es(self, valor: str, tipo: str = "op") -> bool:
        t = self.mira()
        return t.tipo == tipo and t.valor == valor

    def come(self, valor: str, tipo: str = "op") -> Token:
        if not self.es(valor, tipo):
            t = self.mira()
            raise ScriptError(f"se esperaba {valor!r} y hay {t.valor!r}")
        self.i += 1
        return self.t[self.i - 1]

    def prueba(self, valor: str, tipo: str = "op") -> bool:
        if self.es(valor, tipo):
            self.i += 1
            return True
        return False

    def punto_y_coma(self) -> None:
        self.prueba(";")

    # --- programa
    def programa(self) -> list:
        cuerpo = []
        while self.mira().tipo != "fin":
            cuerpo.append(self.sentencia())
        return cuerpo

    def sentencia(self):
        t = self.mira()
        if t.tipo == "ident":
            if t.valor == "export":
                self.i += 1
                return self.sentencia()
            if t.valor == "import":
                raise ScriptError("import")
            if t.valor in ("let", "var", "const"):
                return self.declaracion()
            if t.valor == "function":
                return self.funcion()
            if t.valor == "if":
                return self.si()
            if t.valor == "for":
                return self.para()
            if t.valor == "while":
                self.i += 1
                self.come("(")
                cond = self.expresion()
                self.come(")")
                return ("while", cond, self.sentencia())
            if t.valor == "switch":
                return self.segun()
            if t.valor == "return":
                self.i += 1
                if self.es(";") or self.es("}"):
                    self.punto_y_coma()
                    return ("return", None)
                e = self.expresion()
                self.punto_y_coma()
                return ("return", e)
            if t.valor == "break":
                self.i += 1
                self.punto_y_coma()
                return ("break",)
            if t.valor == "continue":
                self.i += 1
                self.punto_y_coma()
                return ("continue",)
        if self.es("{"):
            return ("bloque", self.bloque())
        if self.es(";"):
            self.i += 1
            return ("vacio",)
        e = self.expresion()
        self.punto_y_coma()
        return ("expr", e)

    def bloque(self) -> list:
        self.come("{")
        cuerpo = []
        while not self.es("}"):
            if self.mira().tipo == "fin":
                raise ScriptError("bloque sin cerrar")
            cuerpo.append(self.sentencia())
        self.come("}")
        return cuerpo

    def declaracion(self):
        self.i += 1
        decls = []
        while True:
            nombre = self.mira()
            if nombre.tipo != "ident":
                raise ScriptError("nombre de variable")
            self.i += 1
            valor = self.asignacion() if self.prueba("=") else None
            decls.append((nombre.valor, valor))
            if not self.prueba(","):
                break
        self.punto_y_coma()
        return ("decl", decls)

    def funcion(self):
        self.i += 1
        nombre = self.mira().valor if self.mira().tipo == "ident" else None
        if nombre:
            self.i += 1
        params = self.parametros()
        return ("func", nombre, params, self.bloque())

    def parametros(self) -> list[str]:
        self.come("(")
        ps = []
        while not self.es(")"):
            t = self.mira()
            if t.tipo != "ident":
                raise ScriptError("parámetro")
            ps.append(t.valor)
            self.i += 1
            if not self.prueba(","):
                break
        self.come(")")
        return ps

    def si(self):
        self.i += 1
        self.come("(")
        cond = self.expresion()
        self.come(")")
        entonces = self.sentencia()
        si_no = None
        if self.mira().tipo == "ident" and self.mira().valor == "else":
            self.i += 1
            si_no = self.sentencia()
        return ("if", cond, entonces, si_no)

    def para(self):
        self.i += 1
        self.come("(")
        # `for (const x of xs)`. El `in` no se cubre: en el corpus no aparece.
        if (self.mira().tipo == "ident" and self.mira().valor in ("let", "var", "const")
                and self.mira(2).tipo == "ident" and self.mira(2).valor == "of"):
            nombre = self.mira(1).valor
            self.i += 3
            iterable = self.expresion()
            self.come(")")
            return ("forof", nombre, iterable, self.sentencia())
        inicio = None
        if not self.es(";"):
            inicio = (self.declaracion()
                      if self.mira().tipo == "ident"
                      and self.mira().valor in ("let", "var", "const")
                      else ("expr", self.expresion()))
        self.punto_y_coma()
        cond = None if self.es(";") else self.expresion()
        self.come(";")
        paso = None if self.es(")") else self.expresion()
        self.come(")")
        return ("for", inicio, cond, paso, self.sentencia())

    def segun(self):
        self.i += 1
        self.come("(")
        disc = self.expresion()
        self.come(")")
        self.come("{")
        casos = []
        while not self.es("}"):
            if self.mira().tipo == "ident" and self.mira().valor == "case":
                self.i += 1
                etiqueta = self.expresion()
                self.come(":")
            elif self.mira().tipo == "ident" and self.mira().valor == "default":
                self.i += 1
                self.come(":")
                etiqueta = None
            else:
                raise ScriptError("case")
            cuerpo = []
            while not (self.es("}") or (self.mira().tipo == "ident"
                                        and self.mira().valor in ("case", "default"))):
                cuerpo.append(self.sentencia())
            casos.append((etiqueta, cuerpo))
        self.come("}")
        return ("switch", disc, casos)

    # --- expresiones
    def expresion(self):
        e = self.asignacion()
        while self.prueba(","):          # el operador coma; sale en los `for`
            e = ("coma", e, self.asignacion())
        return e

    def asignacion(self):
        izq = self.ternario()
        t = self.mira()
        if t.tipo == "op" and t.valor in _ASIGNACIONES:
            self.i += 1
            return ("asigna", t.valor, izq, self.asignacion())
        return izq

    def ternario(self):
        cond = self.binaria(0)
        if self.prueba("?"):
            a = self.asignacion()
            self.come(":")
            return ("ternario", cond, a, self.asignacion())
        return cond

    def binaria(self, minimo: int):
        izq = self.unaria()
        while True:
            t = self.mira()
            if t.tipo != "op":
                break
            p = _PRECEDENCIA.get(t.valor)
            if p is None or p < minimo:
                break
            self.i += 1
            der = self.binaria(p + 1)
            izq = ("bin", t.valor, izq, der)
        return izq

    def unaria(self):
        t = self.mira()
        if t.tipo == "op" and t.valor in ("!", "-", "+", "~"):
            self.i += 1
            return ("un", t.valor, self.unaria())
        if t.tipo == "op" and t.valor in ("++", "--"):
            self.i += 1
            return ("preinc", t.valor, self.unaria())
        if t.tipo == "ident" and t.valor == "typeof":
            self.i += 1
            return ("typeof", self.unaria())
        if t.tipo == "ident" and t.valor == "new":
            self.i += 1
            destino = self.sufijos(self.primaria(), sin_llamada=True)
            args = self.argumentos() if self.es("(") else []
            return self.sufijos(("new", destino, args))
        return self.sufijos(self.primaria())

    def sufijos(self, e, sin_llamada: bool = False):
        while True:
            if self.prueba("."):
                nombre = self.mira()
                if nombre.tipo != "ident":
                    raise ScriptError("nombre de propiedad")
                self.i += 1
                e = ("miembro", e, ("lit", nombre.valor))
            elif self.es("["):
                self.i += 1
                idx = self.expresion()
                self.come("]")
                e = ("miembro", e, idx)
            elif self.es("(") and not sin_llamada:
                e = ("llama", e, self.argumentos())
            elif self.mira().tipo == "op" and self.mira().valor in ("++", "--"):
                op = self.mira().valor
                self.i += 1
                e = ("postinc", op, e)
            else:
                return e

    def argumentos(self) -> list:
        self.come("(")
        args = []
        while not self.es(")"):
            args.append(self.asignacion())
            if not self.prueba(","):
                break
        self.come(")")
        return args

    def primaria(self):
        t = self.mira()
        if t.tipo == "num" or t.tipo == "str":
            self.i += 1
            return ("lit", t.valor)
        if t.tipo == "plantilla":
            self.i += 1
            partes = []
            for trozo in t.valor:
                if isinstance(trozo, tuple):
                    sub = Parser(tokenizar(trozo[1]))
                    partes.append(sub.expresion())
                else:
                    partes.append(("lit", trozo))
            return ("plantilla", partes)
        if t.tipo == "ident":
            if t.valor in ("true", "false"):
                self.i += 1
                return ("lit", t.valor == "true")
            if t.valor in ("null", "undefined"):
                self.i += 1
                return ("lit", None)
            if t.valor == "function":
                return self.funcion()
            if t.valor in _PALABRAS:
                raise ScriptError(f"palabra clave en expresión: {t.valor}")
            if self.mira(1).tipo == "op" and self.mira(1).valor == "=>":
                self.i += 2
                if self.es("{"):
                    return ("func", None, [t.valor], self.bloque())
                return ("func", None, [t.valor], [("return", self.asignacion())])
            self.i += 1
            return ("var", t.valor)
        if self.es("("):
            self.i += 1
            # Una lambda `(a, b) => ...`: se reconoce por la flecha.
            guardado = self.i
            try:
                e = self.expresion()
                self.come(")")
                if self.es("=>"):
                    raise ScriptError("flecha")
                return e
            except ScriptError:
                self.i = guardado
                params = []
                while not self.es(")"):
                    params.append(self.mira().valor)
                    self.i += 1
                    self.prueba(",")
                self.come(")")
                self.come("=>")
                if self.es("{"):
                    return ("func", None, params, self.bloque())
                return ("func", None, params, [("return", self.asignacion())])
        if self.es("["):
            self.i += 1
            elems = []
            while not self.es("]"):
                elems.append(self.asignacion())
                if not self.prueba(","):
                    break
            self.come("]")
            return ("array", elems)
        if self.es("{"):
            self.i += 1
            pares = []
            while not self.es("}"):
                k = self.mira()
                self.i += 1
                clave = str(k.valor)
                if self.prueba(":"):
                    pares.append((clave, self.asignacion()))
                else:                       # taquigrafía {x}
                    pares.append((clave, ("var", clave)))
                if not self.prueba(","):
                    break
            self.come("}")
            return ("objeto", pares)
        raise ScriptError(f"expresión inesperada: {t.valor!r}")


# ── evaluación ──────────────────────────────────────────────────────────────

class _Corte(Exception):
    """`return`, `break` y `continue` viajan como excepción."""

    def __init__(self, clase, valor=None):
        self.clase = clase
        self.valor = valor


class Objeto(dict):
    """Un objeto de JS. Es un dict; lo separa del resto para `typeof`."""


class Constructor:
    """Lo que devuelve `createScriptProperties()`: una cadena de `.addX({...})`.

    Cada `add*` declara una propiedad con su valor POR DEFECTO y devuelve el
    propio constructor para poder encadenar; `finish()` cierra la cadena y
    devuelve el objeto que el script lee como `scriptProperties`.

    Los valores por defecto no son un adorno: la escena solo guarda en
    `scriptproperties` las propiedades que el usuario tocó ---`3299228616`
    guarda cuatro de las cuatro, pero otros guardan una--- y las que faltan
    las pone el script. Sin esto un `if (scriptProperties.showSeconds)` leería
    `undefined` en vez de `false`, que da lo mismo, pero un
    `if (!scriptProperties.use24hFormat)` leería lo contrario de lo que el
    autor dejó puesto.
    """

    def __init__(self, encima: dict):
        self.props: dict[str, object] = {}
        self.encima = encima

    def add(self, args: list):
        d = args[0] if args and isinstance(args[0], dict) else {}
        nombre = d.get("name")
        if isinstance(nombre, str):
            self.props[nombre] = d.get("value")
        return self

    def finish(self) -> "Objeto":
        return Objeto({**self.props, **self.encima})


@dataclass
class Funcion:
    params: list[str]
    cuerpo: list
    ambito: "Ambito"


class Ambito:
    def __init__(self, padre: "Ambito | None" = None):
        self.vars: dict[str, object] = {}
        self.padre = padre

    def busca(self, nombre: str) -> "Ambito | None":
        a = self
        while a is not None:
            if nombre in a.vars:
                return a
            a = a.padre
        return None

    def get(self, nombre: str):
        a = self.busca(nombre)
        if a is None:
            raise ScriptError(f"variable sin definir: {nombre}")
        return a.vars[nombre]

    def set(self, nombre: str, valor) -> None:
        a = self.busca(nombre)
        (a or self).vars[nombre] = valor

    def declara(self, nombre: str, valor) -> None:
        self.vars[nombre] = valor


class Fecha:
    """`new Date()` congelado en el instante que se le pasa.

    Es hora LOCAL, como en el navegador: un reloj de fondo de escritorio
    enseña la hora del escritorio.
    """

    def __init__(self, cuando: dt.datetime):
        self.d = cuando

    def metodo(self, nombre: str):
        d = self.d
        tabla = {
            "getFullYear": lambda: d.year,
            "getMonth": lambda: d.month - 1,          # 0..11, como JS
            "getDate": lambda: d.day,
            "getDay": lambda: (d.weekday() + 1) % 7,  # 0 = domingo, como JS
            "getHours": lambda: d.hour,
            "getMinutes": lambda: d.minute,
            "getSeconds": lambda: d.second,
            "getMilliseconds": lambda: d.microsecond // 1000,
            "getTime": lambda: d.timestamp() * 1000.0,
            "getTimezoneOffset": lambda: 0,
        }
        if nombre not in tabla:
            raise ScriptError(f"Date.{nombre}")
        return tabla[nombre]


def js_num(x: str) -> str:
    """Cómo imprime JS un número: sin `.0` si es entero."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, float):
        if x != x:
            return "NaN"
        if x == int(x) and abs(x) < 1e21:
            return str(int(x))
        return repr(x)
    return str(x)


def js_str(v) -> str:
    if v is None:
        return "undefined"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return js_num(v)
    if isinstance(v, list):
        return ",".join(js_str(x) for x in v)
    if isinstance(v, str):
        return v
    raise ScriptError("a cadena")


def js_verdad(v) -> bool:
    if v is None or v is False:
        return False
    if v is True:
        return True
    if isinstance(v, (int, float)):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True


def js_numero(v) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if v is None:
        return float("nan")
    if isinstance(v, str):
        try:
            return float(v.strip() or 0)
        except ValueError:
            return float("nan")
    raise ScriptError("a número")


class Interprete:
    def __init__(self, fuente: str, propiedades: dict | None = None):
        toks = tokenizar(fuente)
        # Los literales de cadena del script, que es de donde salen los nombres
        # de los días y de los meses; ver `_tablas_candidatas`.
        self.literales = {t.valor for t in toks if t.tipo == "str"}
        self.ast = Parser(toks).programa()
        self.propiedades = propiedades or {}
        self.global_ = Ambito()
        self.fecha: dt.datetime = dt.datetime.now()
        self._prepara()

    # --- preparación: se ejecuta el cuerpo del módulo una vez
    def _prepara(self) -> None:
        g = self.global_
        g.declara("scriptProperties", Objeto(self.propiedades))
        g.declara("createScriptProperties", "__constructor__")
        g.declara("Math", Objeto())
        g.declara("console", Objeto())
        g.declara("thisLayer", Objeto())
        g.declara("shared", Objeto())
        for s in self.ast:
            if s[0] == "func" and s[1]:
                g.declara(s[1], Funcion(s[2], s[3], g))
        for s in self.ast:
            if s[0] != "func":
                self.ejecuta(s, g)

    def texto(self, cuando: dt.datetime, valor: str = "") -> str:
        """Lo que `update(value)` devuelve en ese instante."""
        f = self.global_.vars.get("update")
        if not isinstance(f, Funcion):
            raise ScriptError("el script no exporta update()")
        self.fecha = cuando
        return js_str(self.llama(f, [valor]))

    # --- sentencias
    def ejecuta(self, s, a: Ambito):
        clase = s[0]
        if clase == "decl":
            for nombre, expr in s[1]:
                a.declara(nombre, self.eval(expr, a) if expr is not None else None)
        elif clase == "expr":
            self.eval(s[1], a)
        elif clase == "bloque":
            hijo = Ambito(a)
            for x in s[1]:
                self.ejecuta(x, hijo)
        elif clase == "if":
            if js_verdad(self.eval(s[1], a)):
                self.ejecuta(s[2], a)
            elif s[3] is not None:
                self.ejecuta(s[3], a)
        elif clase == "return":
            raise _Corte("return", self.eval(s[1], a) if s[1] is not None else None)
        elif clase == "break":
            raise _Corte("break")
        elif clase == "continue":
            raise _Corte("continue")
        elif clase == "for":
            hijo = Ambito(a)
            if s[1] is not None:
                self.ejecuta(s[1], hijo)
            vueltas = 0
            while s[2] is None or js_verdad(self.eval(s[2], hijo)):
                vueltas += 1
                if vueltas > 100000:
                    raise ScriptError("bucle sin fin")
                try:
                    self.ejecuta(s[4], Ambito(hijo))
                except _Corte as c:
                    if c.clase == "break":
                        break
                    if c.clase != "continue":
                        raise
                if s[3] is not None:
                    self.eval(s[3], hijo)
        elif clase == "forof":
            for v in self.eval(s[2], a):
                hijo = Ambito(a)
                hijo.declara(s[1], v)
                try:
                    self.ejecuta(s[3], hijo)
                except _Corte as c:
                    if c.clase == "break":
                        break
                    if c.clase != "continue":
                        raise
        elif clase == "while":
            vueltas = 0
            while js_verdad(self.eval(s[1], a)):
                vueltas += 1
                if vueltas > 100000:
                    raise ScriptError("bucle sin fin")
                try:
                    self.ejecuta(s[2], Ambito(a))
                except _Corte as c:
                    if c.clase == "break":
                        break
                    if c.clase != "continue":
                        raise
        elif clase == "switch":
            disc = self.eval(s[1], a)
            hijo = Ambito(a)
            casos = s[2]
            arranque = next((i for i, (et, _) in enumerate(casos)
                             if et is not None and _igual(self.eval(et, hijo), disc)), None)
            if arranque is None:
                arranque = next((i for i, (et, _) in enumerate(casos) if et is None), None)
            if arranque is not None:
                try:
                    for _, cuerpo in casos[arranque:]:   # cae en cascada, como JS
                        for x in cuerpo:
                            self.ejecuta(x, hijo)
                except _Corte as c:
                    if c.clase != "break":
                        raise
        elif clase == "func":
            if s[1]:
                a.declara(s[1], Funcion(s[2], s[3], a))
        elif clase == "vacio":
            pass
        else:
            raise ScriptError(f"sentencia {clase}")

    # --- expresiones
    def eval(self, e, a: Ambito):
        clase = e[0]
        if clase == "lit":
            return e[1]
        if clase == "var":
            if e[1] == "Date":
                return "__Date__"
            if e[1] == "String":
                return "__String__"
            if e[1] == "Number":
                return "__Number__"
            if e[1] == "parseInt":
                return "__parseInt__"
            if e[1] == "Array":
                return "__Array__"
            return a.get(e[1])
        if clase == "plantilla":
            return "".join(js_str(self.eval(p, a)) for p in e[1])
        if clase == "array":
            return [self.eval(x, a) for x in e[1]]
        if clase == "objeto":
            return Objeto((k, self.eval(v, a)) for k, v in e[1])
        if clase == "func":
            return Funcion(e[2], e[3], a)
        if clase == "coma":
            self.eval(e[1], a)
            return self.eval(e[2], a)
        if clase == "un":
            v = self.eval(e[2], a)
            if e[1] == "!":
                return not js_verdad(v)
            if e[1] == "-":
                return -js_numero(v)
            if e[1] == "+":
                return js_numero(v)
            return ~int(js_numero(v))
        if clase == "typeof":
            try:
                v = self.eval(e[1], a)
            except ScriptError:
                return "undefined"
            if v is None:
                return "undefined"
            if isinstance(v, bool):
                return "boolean"
            if isinstance(v, (int, float)):
                return "number"
            if isinstance(v, str):
                return "string"
            if isinstance(v, Funcion):
                return "function"
            return "object"
        if clase == "bin":
            return self.binaria(e[1], e[2], e[3], a)
        if clase == "ternario":
            return self.eval(e[2] if js_verdad(self.eval(e[1], a)) else e[3], a)
        if clase == "asigna":
            return self.asigna(e[1], e[2], e[3], a)
        if clase in ("preinc", "postinc"):
            viejo = js_numero(self.eval(e[2], a))
            nuevo = viejo + (1 if e[1] == "++" else -1)
            self.guarda(e[2], nuevo, a)
            return nuevo if clase == "preinc" else viejo
        if clase == "miembro":
            return self.miembro(self.eval(e[1], a), self.clave(e[2], a))
        if clase == "new":
            destino = self.eval(e[1], a)
            if destino == "__Date__":
                return Fecha(self.fecha)
            raise ScriptError("new de algo que no es Date")
        if clase == "llama":
            return self.llamada(e, a)
        raise ScriptError(f"expresión {clase}")

    def clave(self, e, a: Ambito):
        v = self.eval(e, a)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else js_str(v)

    def binaria(self, op, ei, ed, a: Ambito):
        if op == "&&":
            izq = self.eval(ei, a)
            return self.eval(ed, a) if js_verdad(izq) else izq
        if op == "||":
            izq = self.eval(ei, a)
            return izq if js_verdad(izq) else self.eval(ed, a)
        if op == "??":
            izq = self.eval(ei, a)
            return self.eval(ed, a) if izq is None else izq
        i, d = self.eval(ei, a), self.eval(ed, a)
        if op == "+":
            if isinstance(i, str) or isinstance(d, str):
                return js_str(i) + js_str(d)
            return js_numero(i) + js_numero(d)
        if op in ("==", "==="):
            return _igual(i, d)
        if op in ("!=", "!=="):
            return not _igual(i, d)
        if op in ("<", ">", "<=", ">="):
            if isinstance(i, str) and isinstance(d, str):
                return {"<": i < d, ">": i > d, "<=": i <= d, ">=": i >= d}[op]
            i, d = js_numero(i), js_numero(d)
            return {"<": i < d, ">": i > d, "<=": i <= d, ">=": i >= d}[op]
        i, d = js_numero(i), js_numero(d)
        if op == "-":
            return i - d
        if op == "*":
            return i * d
        if op == "/":
            return i / d if d else float("inf") if i else float("nan")
        if op == "%":
            # El resto de JS se queda con el signo del dividendo; el de Python
            # con el del divisor. Con horas y meses no se nota, pero el módulo
            # tiene que decir lo que dice JS.
            return float("nan") if d == 0 else i - d * int(i / d)
        if op in ("|", "&", "^"):
            i, d = int(i), int(d)
            return {"|": i | d, "&": i & d, "^": i ^ d}[op]
        raise ScriptError(f"operador {op}")

    def asigna(self, op, destino, expr, a: Ambito):
        valor = self.eval(expr, a)
        if op != "=":
            valor = self.binaria(op[0], destino, ("lit", valor), a)
        self.guarda(destino, valor, a)
        return valor

    def guarda(self, destino, valor, a: Ambito) -> None:
        if destino[0] == "var":
            a.set(destino[1], valor)
            return
        if destino[0] == "miembro":
            obj = self.eval(destino[1], a)
            k = self.clave(destino[2], a)
            if isinstance(obj, list):
                i = int(k)
                while len(obj) <= i:
                    obj.append(None)
                obj[i] = valor
            elif isinstance(obj, dict):
                obj[js_str(k)] = valor
            else:
                raise ScriptError("asignar a algo que no es objeto")
            return
        raise ScriptError("destino de asignación")

    def miembro(self, obj, clave):
        if isinstance(obj, str):
            if clave == "length":
                return len(obj)
            if isinstance(clave, (int, float)):
                i = int(clave)
                return obj[i] if 0 <= i < len(obj) else None
            return ("__met_str__", obj, clave)
        if isinstance(obj, list):
            if clave == "length":
                return len(obj)
            if isinstance(clave, (int, float)):
                i = int(clave)
                return obj[i] if 0 <= i < len(obj) else None
            return ("__met_arr__", obj, clave)
        if isinstance(obj, (int, float)) and not isinstance(obj, bool):
            return ("__met_num__", obj, clave)
        if isinstance(obj, Constructor):
            return ("__met_cons__", obj, clave)
        if isinstance(obj, Fecha):
            return obj.metodo(js_str(clave))
        if obj == "__Date__":
            return ("__met_Date__", obj, clave)
        if isinstance(obj, dict):
            return obj.get(js_str(clave))
        if obj is None:
            raise ScriptError("propiedad de undefined")
        return None

    def llamada(self, e, a: Ambito):
        objetivo, args_ast = e[1], e[2]
        # Math.* y console.* se resuelven por el nombre del objeto, que es lo
        # único que hace falta: no hay más objetos globales en el corpus.
        if objetivo[0] == "miembro" and objetivo[1] == ("var", "Math"):
            args = [js_numero(self.eval(x, a)) for x in args_ast]
            return _math(js_str(self.clave(objetivo[2], a)), args)
        if objetivo[0] == "miembro" and objetivo[1] == ("var", "console"):
            return None
        f = self.eval(objetivo, a)
        if f == "__constructor__":
            return Constructor(self.propiedades)
        if isinstance(f, tuple) and f[0] == "__met_cons__":
            args = [self.eval(x, a) for x in args_ast]
            cons, nombre = f[1], js_str(f[2])
            if nombre == "finish":
                return cons.finish()
            if nombre.startswith("add"):
                return cons.add(args)
            raise ScriptError(f"createScriptProperties().{nombre}")
        if f == "__String__":
            return js_str(self.eval(args_ast[0], a)) if args_ast else ""
        if f == "__Number__" or f == "__parseInt__":
            v = self.eval(args_ast[0], a) if args_ast else None
            n = js_numero(v)
            return float(int(n)) if f == "__parseInt__" and n == n else n
        if isinstance(f, tuple) and f[0].startswith("__met_"):
            args = [self.eval(x, a) for x in args_ast]
            return self.metodo(f, args)
        if callable(f):                              # getter de Date
            return f()
        if isinstance(f, Funcion):
            return self.llama(f, [self.eval(x, a) for x in args_ast])
        raise ScriptError(f"llamada a algo que no es función: {f!r}")

    def metodo(self, ref, args):
        clase, obj, nombre = ref
        nombre = js_str(nombre)
        if clase == "__met_str__":
            return _metodo_cadena(obj, nombre, args)
        if clase == "__met_arr__":
            return self._metodo_array(obj, nombre, args)
        if clase == "__met_num__":
            if nombre == "toString":
                base = int(js_numero(args[0])) if args else 10
                n = int(obj)
                if base == 10:
                    return js_num(obj)
                digitos = "0123456789abcdefghijklmnopqrstuvwxyz"
                signo, n = ("-" if n < 0 else ""), abs(n)
                s = ""
                while True:
                    s = digitos[n % base] + s
                    n //= base
                    if not n:
                        break
                return signo + s
            if nombre == "toFixed":
                return f"{js_numero(obj):.{int(js_numero(args[0])) if args else 0}f}"
            if nombre == "padStart":
                return _metodo_cadena(js_num(obj), nombre, args)
            raise ScriptError(f"Number.{nombre}")
        if clase == "__met_Date__":
            raise ScriptError(f"Date.{nombre} estático")
        raise ScriptError(nombre)

    def _metodo_array(self, obj: list, nombre: str, args):
        if nombre == "push":
            obj.extend(args)
            return len(obj)
        if nombre == "join":
            sep = js_str(args[0]) if args else ","
            return sep.join(js_str(x) for x in obj)
        if nombre == "slice":
            i = int(js_numero(args[0])) if args else 0
            j = int(js_numero(args[1])) if len(args) > 1 else len(obj)
            return obj[i:j]
        if nombre == "indexOf":
            for i, x in enumerate(obj):
                if _igual(x, args[0]):
                    return i
            return -1
        if nombre == "includes":
            return any(_igual(x, args[0]) for x in obj)
        if nombre in ("forEach", "map", "filter"):
            f = args[0]
            if not isinstance(f, Funcion):
                raise ScriptError(nombre)
            salida = []
            for i, x in enumerate(obj):
                r = self.llama(f, [x, float(i), obj][:len(f.params)] or [x])
                if nombre == "map":
                    salida.append(r)
                elif nombre == "filter" and js_verdad(r):
                    salida.append(x)
            return None if nombre == "forEach" else salida
        raise ScriptError(f"Array.{nombre}")

    def llama(self, f: Funcion, args: list):
        a = Ambito(f.ambito)
        for i, p in enumerate(f.params):
            a.declara(p, args[i] if i < len(args) else None)
        try:
            for s in f.cuerpo:
                self.ejecuta(s, a)
        except _Corte as c:
            if c.clase == "return":
                return c.valor
            raise
        return None


def _igual(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return js_numero(a) == js_numero(b)
    if isinstance(a, str) != isinstance(b, str):
        return js_numero(a) == js_numero(b)
    return a == b


def _math(nombre: str, args: list[float]):
    import math
    tabla = {
        "floor": lambda: float(math.floor(args[0])),
        "ceil": lambda: float(math.ceil(args[0])),
        # `Math.round` de JS redondea .5 hacia ARRIBA siempre; el de Python
        # redondea al par.
        "round": lambda: float(math.floor(args[0] + 0.5)),
        "abs": lambda: abs(args[0]),
        "min": lambda: min(args),
        "max": lambda: max(args),
        "pow": lambda: args[0] ** args[1],
        "sqrt": lambda: math.sqrt(args[0]),
        "trunc": lambda: float(int(args[0])),
        "random": lambda: 0.5,
    }
    if nombre not in tabla:
        raise ScriptError(f"Math.{nombre}")
    return tabla[nombre]()


def _metodo_cadena(s: str, nombre: str, args):
    def n(i, defecto=None):
        if i >= len(args) or args[i] is None:
            return defecto
        return int(js_numero(args[i]))
    if nombre == "slice":
        return s[n(0, 0):n(1)] if len(args) > 1 else s[n(0, 0):]
    if nombre == "substring":
        i, j = max(0, n(0, 0)), max(0, n(1, len(s)))
        return s[min(i, j):max(i, j)]
    if nombre == "substr":
        i = n(0, 0)
        i = i if i >= 0 else max(0, len(s) + i)
        return s[i:i + n(1, len(s))]
    if nombre == "padStart":
        relleno = js_str(args[1]) if len(args) > 1 else " "
        largo = n(0, 0)
        if len(s) >= largo or not relleno:
            return s
        return (relleno * largo)[:largo - len(s)] + s
    if nombre == "padEnd":
        relleno = js_str(args[1]) if len(args) > 1 else " "
        largo = n(0, 0)
        if len(s) >= largo or not relleno:
            return s
        return s + (relleno * largo)[:largo - len(s)]
    if nombre == "toUpperCase":
        return s.upper()
    if nombre == "toLowerCase":
        return s.lower()
    if nombre == "trim":
        return s.strip()
    if nombre == "charAt":
        i = n(0, 0)
        return s[i] if 0 <= i < len(s) else ""
    if nombre == "indexOf":
        return float(s.find(js_str(args[0])))
    if nombre == "includes":
        return js_str(args[0]) in s
    if nombre == "startsWith":
        return s.startswith(js_str(args[0]))
    if nombre == "endsWith":
        return s.endswith(js_str(args[0]))
    if nombre == "split":
        return s.split(js_str(args[0])) if args else [s]
    if nombre == "concat":
        return s + "".join(js_str(x) for x in args)
    if nombre == "repeat":
        return s * n(0, 0)
    if nombre == "toString":
        return s
    if nombre == "replace":
        # Solo con cadena: una expresión regular literal ni siquiera pasa el
        # léxico, así que aquí nunca llega una.
        return s.replace(js_str(args[0]), js_str(args[1]), 1)
    if nombre == "replaceAll":
        return s.replace(js_str(args[0]), js_str(args[1]))
    raise ScriptError(f"String.{nombre}")


# ── de una capa de texto a un intérprete ────────────────────────────────────

def propiedades_de(obj: dict) -> dict:
    """`scriptproperties` de la capa, con los `{user, value}` ya resueltos.

    El campo mezcla dos cosas: valores puestos a mano y enlaces a una propiedad
    de usuario del `project.json`. Los dos traen `value`, que es el que vale;
    quien quiera el valor del usuario ya lo resolvió antes de llegar aquí.
    """
    props = (obj.get("text") or {}).get("scriptproperties")
    if not isinstance(props, dict):
        return {}
    salida = {}
    for k, v in props.items():
        salida[k] = v.get("value") if isinstance(v, dict) else v
    return salida


def interprete_de(obj: dict) -> Interprete | None:
    """El intérprete de la capa, o None si no trae script."""
    t = obj.get("text")
    if not isinstance(t, dict) or not isinstance(t.get("script"), str):
        return None
    return Interprete(t["script"], propiedades_de(obj))

# ── del script a un formato que el ejecutor sepa rehacer ────────────────────
#
# El ejecutor no puede llamar aquí cada fotograma: vive en C, dentro de
# plasmashell. Lo que viaja en el plan es un FORMATO, y el ejecutor lo rellena
# con su reloj. Los códigos son los de `strftime` donde existe el equivalente,
# para no inventar un dialecto nueva.

CAMPOS = {
    "%H": lambda d: f"{d.hour:02d}",
    "%k": lambda d: str(d.hour),
    "%I": lambda d: f"{(d.hour % 12) or 12:02d}",
    "%l": lambda d: str((d.hour % 12) or 12),
    "%M": lambda d: f"{d.minute:02d}",
    "%S": lambda d: f"{d.second:02d}",
    "%d": lambda d: f"{d.day:02d}",
    "%e": lambda d: str(d.day),
    "%m": lambda d: f"{d.month:02d}",
    "%f": lambda d: str(d.month),
    "%Y": lambda d: f"{d.year:04d}",
    "%y": lambda d: f"{d.year % 100:02d}",
    "%p": lambda d: "AM" if d.hour < 12 else "PM",
    "%P": lambda d: "am" if d.hour < 12 else "pm",
}

# Los campos que no son un número sino una PALABRA, y cuya tabla la pone el
# propio script. No se traducen: hay meses en inglés, en español, en francés,
# en ruso, en vietnamita y en chino, y copiarlos del script es lo único que
# respeta el idioma que el autor eligió. El tercero ---la franja del día, el
# `晚上` de `2821288001`--- no tiene equivalente en `strftime` y por eso lleva
# un código propio.
CAMPOS_TABLA = {
    "%A": ((lambda d: (d.weekday() + 1) % 7), 7),    # 0 = domingo, como JS
    "%B": ((lambda d: d.month - 1), 12),
    "%N": ((lambda d: d.hour), 24),
}


@dataclass
class Formato:
    """Una plantilla que el ejecutor puede rellenar con su reloj."""
    plantilla: str
    tablas: dict[str, list[str]] = field(default_factory=dict)
    # Cada cuánto cambia lo que se dibuja. Sale de qué campos usa: un reloj sin
    # segundos no necesita que nadie lo rehaga sesenta veces por segundo.
    periodo: float = 60.0

    @property
    def alfabeto(self) -> str:
        """Todos los caracteres que la plantilla puede llegar a dibujar."""
        letras = set(re.sub(r"%[A-Za-z%]", "", self.plantilla))
        if "%%" in self.plantilla:
            letras.add("%")
        for codigo in re.findall(r"%[A-Za-z]", self.plantilla):
            if codigo in self.tablas:
                letras.update("".join(self.tablas[codigo]))
            elif codigo in ("%p", "%P"):
                letras.update("AMPamp")
            elif codigo in CAMPOS:
                letras.update("0123456789")
        return "".join(sorted(letras))

    def max_longitud(self) -> int:
        """El texto más largo, en caracteres, que la plantilla puede escribir.

        Es lo que decide cuántos quads reserva la malla: el búfer se pide una
        vez y la cadena cambia, así que tiene que caber el peor caso. Se mide
        recorriendo los mismos instantes con los que se comprobó el formato.
        """
        return max(len(self.render(t)) for t in _instantes_de_prueba())

    def render(self, cuando: dt.datetime) -> str:
        salida = []
        i = 0
        while i < len(self.plantilla):
            c = self.plantilla[i]
            if c == "%" and i + 1 < len(self.plantilla):
                codigo = self.plantilla[i:i + 2]
                if codigo == "%%":
                    salida.append("%")
                elif codigo in self.tablas:
                    salida.append(self.tablas[codigo][CAMPOS_TABLA[codigo][0](cuando)])
                elif codigo in CAMPOS:
                    salida.append(CAMPOS[codigo](cuando))
                else:
                    salida.append(codigo)
                i += 2
                continue
            salida.append(c)
            i += 1
        return "".join(salida)


def _muestras() -> list[dt.datetime]:
    """Instantes con los que se DEDUCE la plantilla.

    Tienen que mover todos los campos a la vez y bastante ---si dos muestras
    comparten el minuto, ese minuto se cuela en la plantilla como literal---,
    y tienen que incluir los sitios donde un formato se rompe: la medianoche y
    el mediodía del reloj de 12 horas, y los valores de una sola cifra, que
    separan el campo rellenado con ceros del que no.
    """
    return [
        dt.datetime(2027, 11, 19, 21, 46, 58),   # viernes, todo de dos cifras
        dt.datetime(2026, 3, 5, 7, 8, 9),        # jueves, todo de una cifra
        dt.datetime(2024, 12, 25, 0, 0, 0),      # miércoles, medianoche
        dt.datetime(2025, 6, 1, 12, 34, 45),     # domingo, mediodía
        dt.datetime(2023, 1, 31, 23, 59, 1),     # martes
        dt.datetime(2028, 8, 14, 16, 22, 37),    # lunes
        dt.datetime(2022, 9, 3, 4, 15, 26),      # sábado
    ]


def _instantes_de_prueba() -> list[dt.datetime]:
    """Instantes con los que se COMPRUEBA la plantilla ya deducida.

    No son al azar: recorren las 24 horas en punto y en su último segundo, los
    doce meses, los siete días de la semana y un barrido largo que cruza años
    bisiestos.
    """
    salida = []
    base = dt.datetime(2024, 1, 1, 0, 0, 0)
    for k in range(1000):
        salida.append(base + dt.timedelta(
            days=k * 1.37, hours=k * 0.53, minutes=k * 7, seconds=k * 13))
    for h in range(24):
        salida.append(dt.datetime(2025, 3, 9, h, 0, 0))
        salida.append(dt.datetime(2025, 3, 9, h, 59, 59))
    for m in range(1, 13):
        salida.append(dt.datetime(2026, m, 1, 12, 30, 0))
        salida.append(dt.datetime(2026, m, 28, 0, 5, 0))
    for d in range(7):
        salida.append(dt.datetime(2027, 2, 1 + d, 15, 15, 15))
    return salida

def _grupos_de_barrido(codigo: str) -> list[list[dt.datetime]]:
    """Tres instantes por cada valor del campo, con lo demás distinto.

    Tres y no uno porque con uno se cuela el campo vecino: barriendo los doce
    meses el día de la semana también cambia, y `'Wednesday'` sale en marzo y
    en ningún otro mes igual que `'March'`. Con tres muestras por mes ---años y
    días distintos--- el nombre del mes es el único literal que está en las
    tres.
    """
    if codigo == "%A":
        # El 1 de febrero de 2027 es lunes; se recorre la semana y se repite en
        # otros dos meses y años, para que solo se repita el día de la semana.
        base = [dt.datetime(2027, 2, 7), dt.datetime(2025, 6, 1),
                dt.datetime(2023, 10, 1)]
        grupos = []
        for k in range(7):
            fila = []
            for b in base:
                d = b + dt.timedelta(days=(k - (b.weekday() + 1) % 7) % 7)
                fila.append(d.replace(hour=12, minute=30, second=30))
            grupos.append(fila)
        return grupos
    if codigo == "%B":
        return [[dt.datetime(2027, m, 15, 12, 30, 30),
                 dt.datetime(2024, m, 6, 9, 15, 45),
                 dt.datetime(2022, m, 23, 18, 5, 5)] for m in range(1, 13)]
    return [[dt.datetime(2027, 6, 15, h, 30, 30),
             dt.datetime(2024, 2, 6, h, 15, 45),
             dt.datetime(2022, 10, 23, h, 5, 5)] for h in range(24)]


def _tablas_candidatas(ip: "Interprete", valor: str) -> dict[str, list[list[str]]]:
    """Las tablas de palabras que el script pueda tener, sacadas de sus literales.

    Los nombres de día y de mes están escritos EN el script, como literales de
    cadena; no hay que adivinarlos, hay que reconocerlos. Se barre el campo
    ---los siete días, los doce meses, las 24 horas--- con tres instantes por
    valor, y el nombre de ese valor es el literal que sale en los tres.

    Devuelve hasta dos variantes por campo, la del literal más largo y la del
    más corto, porque un script puede traer a la vez `'Sunday'` y `'Sun'` y
    `'Sun'` está dentro del otro. Cuál usa de verdad lo decide la búsqueda de
    la plantilla, y en último término la comprobación.
    """
    salida: dict[str, list[list[str]]] = {}
    for codigo, (clave, tamano) in CAMPOS_TABLA.items():
        grupos = _grupos_de_barrido(codigo)
        try:
            textos = [[ip.texto(t, valor) for t in fila] for fila in grupos]
        except Exception:
            continue
        candidatos: list[set[str]] = []
        for fila in textos:
            candidatos.append({lit for lit in ip.literales
                               if lit and all(lit in s for s in fila)})
        # Un literal que sale en TODOS los valores del campo no es el campo:
        # es texto fijo que el script pone al lado.
        constantes = set.intersection(*candidatos) if candidatos else set()
        candidatos = [c - constantes for c in candidatos]
        if any(not c for c in candidatos):
            continue
        # Los nombres propios salen en un solo valor; una franja del día
        # ---`晚上` cubre varias horas--- sale en varios, y ahí manda el largo.
        cuenta: dict[str, int] = {}
        for c in candidatos:
            for lit in c:
                cuenta[lit] = cuenta.get(lit, 0) + 1
        variantes: list[list[str]] = []
        for preferir_unicos in (True, False):
            tabla = []
            for c in candidatos:
                unicos = [x for x in c if cuenta[x] == 1] if preferir_unicos else []
                tabla.append(max(unicos or list(c), key=len))
            if tabla not in variantes:
                variantes.append(tabla)
        corta = [min(c, key=len) for c in candidatos]
        if corta not in variantes:
            variantes.append(corta)
        if all(len(v) == tamano for v in variantes):
            salida[codigo] = variantes
    return salida


def _busca_plantilla(salidas: list[str], muestras: list[dt.datetime],
                     tablas: dict[str, list[str]]) -> list[str] | None:
    """Corta las siete muestras A LA VEZ en literales y campos.

    Buscar el formato sobre una sola cadena es ambiguo ---en `21:46` el `21`
    puede ser la hora, el día o el mes--- y diferenciar cadenas cortas se
    equivoca: `SequenceMatcher` empareja el `2` de `21:46` con el de `16:22` y
    se lleva por delante los dos puntos. Cortarlas en paralelo quita las dos
    cosas: un campo solo vale si encaja en las SIETE a la vez, y un literal
    solo vale si las siete traen el mismo carácter.

    Se prueban primero los trozos largos, y con vuelta atrás: si una elección
    deja el resto sin cortar, se deshace.
    """
    n = len(salidas)
    candidatos = [(c, [tablas[c][CAMPOS_TABLA[c][0](t)] for t in muestras])
                  for c in tablas]
    candidatos += [(c, [fn(t) for t in muestras]) for c, fn in CAMPOS.items()]
    visto: set[tuple[int, ...]] = set()

    def paso(pos: tuple[int, ...]) -> list[str] | None:
        if all(p == len(s) for p, s in zip(pos, salidas)):
            return []
        if pos in visto:
            return None
        visto.add(pos)
        # Los campos primero, del más largo al más corto: si `2027` es el año,
        # no hay que dejar que `20` se lo lleve a trozos.
        opciones = sorted(candidatos, key=lambda c: -len(c[1][0]))
        for codigo, textos in opciones:
            if any(not t or not s.startswith(t, p)
                   for t, s, p in zip(textos, salidas, pos)):
                continue
            resto = paso(tuple(p + len(t) for p, t in zip(pos, textos)))
            if resto is not None:
                return [codigo] + resto
        letras = {s[p] for s, p in zip(salidas, pos) if p < len(s)}
        if len(letras) == 1 and all(p < len(s) for s, p in zip(salidas, pos)):
            c = letras.pop()
            resto = paso(tuple(p + 1 for p in pos))
            if resto is not None:
                return [("%%" if c == "%" else c)] + resto
        return None

    return paso(tuple(0 for _ in range(n)))


def formato_de(ip: Interprete, valor: str = "") -> Formato | None:
    """Deduce el formato del script, y solo lo devuelve si se comprueba.

    Deducir es cortar siete muestras en paralelo; ver `_busca_plantilla`. Lo
    que da la garantía no es eso sino la comprobación: la plantilla tiene que
    reproducir lo que devuelve el script en los ~1050 instantes de
    `_instantes_de_prueba`. Con una sola diferencia se descarta y la capa se
    queda con su cadena congelada, que es exactamente lo que hacía antes.
    """
    muestras = _muestras()
    try:
        salidas = [ip.texto(t, valor) for t in muestras]
    except Exception:
        return None
    if not all(salidas) or len(set(salidas)) == 1:
        # Vacía en algún instante, o la misma siempre: no es un reloj.
        return None

    candidatas = _tablas_candidatas(ip, valor)
    # Se prueba primero sin tablas ---la mayoría son relojes de solo números---
    # y luego con cada combinación de variantes. Son como mucho ocho.
    import itertools
    combinaciones: list[dict[str, list[str]]] = [{}]
    codigos = list(candidatas)
    for r in range(1, len(codigos) + 1):
        for cuales in itertools.combinations(codigos, r):
            for eleccion in itertools.product(*(candidatas[c] for c in cuales)):
                combinaciones.append(dict(zip(cuales, eleccion)))

    for tablas in combinaciones:
        piezas = _busca_plantilla(salidas, muestras, tablas)
        if piezas is None:
            continue
        usadas = {c: t for c, t in tablas.items() if c in piezas}
        fmt = Formato("".join(piezas), usadas, 1.0 if "%S" in piezas else 60.0)
        try:
            if all(fmt.render(t) == ip.texto(t, valor)
                   for t in _instantes_de_prueba()):
                # Una plantilla con salto de linea es un reloj de VARIAS
                # lineas, y la disposicion del ejecutor es de una sola: el
                # `SATURDAY` de `2946362143` empieza por `\n`. Mejor dejarla
                # con su cadena congelada que dibujarla en el renglon que no
                # es.
                if "\n" in fmt.plantilla or any(
                        "\n" in p for tab in usadas.values() for p in tab):
                    return None
                return fmt
        except Exception:
            continue
    return None


def reloj_de(obj: dict) -> Formato | None:
    """El formato de una capa de texto, o None si no es un reloj traducible."""
    try:
        ip = interprete_de(obj)
    except (ScriptError, Exception):
        return None
    if ip is None:
        return None
    t = obj.get("text") or {}
    valor = t.get("value") if isinstance(t.get("value"), str) else ""
    return formato_de(ip, valor or "")


# ── barrido del corpus ──────────────────────────────────────────────────────

def main() -> int:
    import json
    import pkg_inspect
    import wepaths

    objetivo = sys.argv[1] if len(sys.argv) > 1 else None
    ws = Path(wepaths.we_workshop())
    total = con_script = evaluados = relojes = 0
    fallos: dict[str, int] = {}
    for d in sorted(ws.iterdir()):
        if objetivo and d.name != objetivo:
            continue
        pkg = d / "scene.pkg"
        if not pkg.is_file():
            continue
        try:
            _, entradas = pkg_inspect.read_pkg(str(pkg))
            escena = [e for e in entradas if e["name"] == "scene.json"]
            if not escena:
                continue
            j = json.loads(escena[0]["data"])
        except Exception:
            continue
        for o in j.get("objects") or []:
            if not isinstance(o, dict) or "text" not in o:
                continue
            total += 1
            t = o["text"]
            if not isinstance(t, dict) or not isinstance(t.get("script"), str):
                continue
            con_script += 1
            try:
                ip = Interprete(t["script"], propiedades_de(o))
                salida = ip.texto(dt.datetime.now(),
                                  t.get("value") if isinstance(t.get("value"), str) else "")
                evaluados += 1
            except Exception as e:
                clave = f"{type(e).__name__}: {e}"[:70]
                fallos[clave] = fallos.get(clave, 0) + 1
                if objetivo:
                    print(f"  {d.name} {o.get('name','')!r}: {clave}")
                continue
            fmt = formato_de(ip, t.get("value") if isinstance(t.get("value"), str) else "")
            if fmt:
                relojes += 1
            if objetivo:
                plantilla = repr(fmt.plantilla) if fmt else "---"
                print(f"  {d.name} {str(o.get('name','')):<16} "
                      f"guardado={t.get('value')!r:<26} ahora={salida!r:<26} "
                      f"formato={plantilla}")
    print(f"\ncapas de texto {total}, con script {con_script}, "
          f"evaluadas {evaluados}, con formato comprobado {relojes}")
    if fallos:
        print("\nlo que no cubre el intérprete:")
        for k, n in sorted(fallos.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>3}  {k}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
