#!/usr/bin/env python3
"""Lo que el intérprete de `wescript.py` cubre, y lo que tiene que rechazar.

No hay motor de JavaScript con el que comparar, así que el oráculo es lo que
dice JS en cada caso, escrito a mano y pequeño:

  1. Desestructurar un array al declarar ---`const [a, b, c] = [...]`---, con
     `undefined` para lo que falte y huecos `[, b]`.
  2. `Boolean` como función, la del `.filter(Boolean)`.
  3. `engine` con un solo miembro, `registerAsset`, que devuelve algo opaco.
     Cualquier otro miembro tiene que seguir siendo un ScriptError, porque con
     él la salida depende del motor; y también lo es usar lo que devuelve
     `registerAsset` en el texto.
  4. Sobre el corpus: las capas que leen otro miembro de `engine` siguen sin
     reloj, y las que solo registran fuentes sí lo dan.

Uso:
    python3 tools/test_wescript.py
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pkg_inspect
import wepaths
import wescript

AHORA = dt.datetime(2026, 10, 10, 17, 38, 5)


def update(cuerpo: str, modulo: str = "") -> str:
    """Lo que devuelve un `update` mínimo, con `modulo` delante."""
    ip = wescript.Interprete(
        f"{modulo}\nexport function update(value) {{ {cuerpo} }}", {})
    return ip.texto(AHORA)


def rechaza(cuerpo: str, modulo: str = "") -> bool:
    try:
        update(cuerpo, modulo)
    except wescript.ScriptError:
        return True
    return False


SINTETICOS = [
    # (qué, cuerpo de update, lo que dice JS)
    ("desestructura", "const [a, b, c] = [1, 'x', 3]; return a + b + c;", "1x3"),
    ("le faltan elementos", "const [p, q] = [7]; return p + ',' + typeof q + ',' + (q === undefined);",
     "7,undefined,true"),
    ("con hueco", "let [, b, , d] = ['a', 'b', 'c', 'd', 'e']; return b + d;", "bd"),
    ("con let y otra declaración", "let [h, m] = [9, 5], s = 'z'; return h + ':' + m + s;", "9:5z"),
    ("de una cadena", "const [x, y] = 'ok'; return y + x;", "ko"),
    ("en un bloque", "if (true) { const [d, mo, y] = ['01', '02', 2026]; return `${y}/${mo}/${d}`; }",
     "2026/02/01"),
    ("Boolean en filter", "return [1, 0, '', null, 'y'].filter(Boolean).join('-');", "1-y"),
    ("Boolean llamado", "return [Boolean(0), Boolean('a'), Boolean(null), typeof Boolean].join(',');",
     "false,true,false,function"),
    ("filter(Boolean) de un reloj",
     "const pad = n => n.toString().padStart(2, '0'); const t = new Date();"
     "return [pad(t.getHours()), pad(t.getMinutes()), null].filter(Boolean).join(':');",
     "17:38"),
]

# Scripts cuya salida depende del motor: tienen que lanzar.
RECHAZOS = [
    ("engine.frametime", "return engine.frametime;", ""),
    ("engine.frametime acumulado", "t += engine.frametime; return 'x';", "let t = 0;"),
    ("engine.registerAudioBuffers", "return 'x';", "engine.registerAudioBuffers(64);"),
    ("engine[\"timeOfDay\"]", "return engine['timeOfDay'];", ""),
    ("escribir en engine", "engine.foo = 1; return 'x';", ""),
    ("el recurso en el texto", "return engine.registerAsset('f.otf');", ""),
    ("un miembro del recurso", "return engine.registerAsset('f.otf').name;", ""),
    ("desestructurar un número", "const [a] = 5; return 'x';", ""),
    ("desestructurar con defecto", "const [a = 1] = []; return 'x';", ""),
    ("desestructurar un objeto", "const {a} = {a: 1}; return 'x';", ""),
]

# `registerAsset` en el cuerpo del módulo, como hacen las capas que registran
# sus fuentes para `applyUserProperties`: el intérprete se construye.
REGISTRO = ("let fuentes = ['a.otf', 'b.ttf']; let cache = [];"
            "fuentes.forEach(f => { cache.push(engine.registerAsset(f)) });")


def corpus(fallos: list[str]) -> tuple[int, int]:
    """Las capas del corpus con `engine`: (con reloj, sin reloj).

    Las que leen otro miembro ---`engine.frametime` en el contador de fps y en
    los dos títulos con cursor que parpadea--- tienen que seguir sin reloj; las
    que solo llaman a `registerAsset`, darlo.
    """
    con = sin = 0
    for d in sorted(wepaths.we_workshop().iterdir()):
        p = d / "scene.pkg"
        if not p.is_file():
            continue
        try:
            _, ents = pkg_inspect.read_pkg(str(p))
            sj = [e for e in ents if e["name"] == "scene.json"]
            s = json.loads(sj[0]["data"]) if sj else {}
        except Exception:
            continue
        for o in s.get("objects") or []:
            t = o.get("text") if isinstance(o, dict) else None
            if not (isinstance(t, dict) and isinstance(t.get("script"), str)
                    and "engine" in t["script"]):
                continue
            src = t["script"]
            otros = sorted(set(re.findall(r"\bengine\s*\.\s*(\w+)", src))
                           - {"registerAsset"})
            fmt = wescript.reloj_de(o)
            etq = f"{d.name} {o.get('id')} {o.get('name', '')!r}"
            if otros and fmt is not None:
                fallos.append(f"{etq}: usa engine.{otros} y da reloj {fmt.plantilla!r}")
            if not otros and fmt is None:
                fallos.append(f"{etq}: solo usa engine.registerAsset y no da reloj")
            print(f"  {etq:42} engine.{otros or ['registerAsset']} -> "
                  f"{fmt.plantilla if fmt else None!r}")
            if fmt is None:
                sin += 1
            else:
                con += 1
    return con, sin


def main() -> int:
    fallos: list[str] = []
    print("── sintéticos ──")
    for que, cuerpo, espera in SINTETICOS:
        try:
            r = update(cuerpo)
        except wescript.ScriptError as e:
            r = f"ScriptError: {e}"
        ok = r == espera
        print(f"  {'ok' if ok else 'MAL':3} {que:32} {r!r}")
        if not ok:
            fallos.append(f"{que}: {r!r} y JS dice {espera!r}")
    for que, cuerpo, modulo in RECHAZOS:
        ok = rechaza(cuerpo, modulo)
        print(f"  {'ok' if ok else 'MAL':3} {que:32} {'ScriptError' if ok else 'pasa'}")
        if not ok:
            fallos.append(f"{que}: no lanza ScriptError")
    try:
        r = update("return 'hola';", REGISTRO)
    except wescript.ScriptError as e:
        r = f"ScriptError: {e}"
    print(f"  {'ok' if r == 'hola' else 'MAL':3} {'registerAsset en el módulo':32} {r!r}")
    if r != "hola":
        fallos.append(f"registerAsset en el módulo: {r!r}")
    # Y con `formato_de`, que es lo que decide si una capa es un reloj.
    ip = wescript.Interprete(
        "export function update(value) { return engine.frametime + ':' + "
        "new Date().getMinutes(); }", {})
    if wescript.formato_de(ip) is not None:
        fallos.append("formato_de da reloj con engine.frametime")

    print("── capas del corpus con engine ──")
    con, sin = corpus(fallos)
    print(f"  con reloj {con}, sin reloj {sin}")

    if fallos:
        print(f"\nFALLO: {len(fallos)}")
        for f in fallos:
            print(f"  {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
