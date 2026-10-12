#!/usr/bin/env python3
"""Lo que el intérprete de `wescript.py` cubre, y lo que tiene que rechazar.

No hay motor de JavaScript con el que comparar, así que el oráculo es lo que
dice JS en cada caso, escrito a mano y pequeño:

  1. Desestructurar un array al declarar ---`const [a, b, c] = [...]`---, con
     `undefined` para lo que falte y huecos `[, b]`.
  2. `Boolean` como función, la del `.filter(Boolean)`.
  3. `engine` con dos miembros: `registerAsset`, que devuelve algo opaco, y
     `timeOfDay`, la hora local como fracción del día. Cualquier otro miembro
     tiene que seguir siendo un ScriptError, porque con él la salida depende
     del motor; y también lo es usar lo que devuelve `registerAsset` en el
     texto.
  4. Sobre el corpus: las capas que leen otro miembro de `engine` siguen sin
     reloj, y las que solo registran fuentes sí lo dan.
  5. `thisLayer.getTextureAnimation().setFrame(n)` en el script de una
     propiedad que no es texto: la tabla de 24 fotogramas cuando `n` depende
     solo de la hora ---la de la capa 303 de `3299228616`, `[0]*12 + [1]*12`---
     y ninguna cuando no se llama a `setFrame`, cuando el fotograma no cambia,
     cuando depende del minuto o cuando el script usa otro método de la
     animación.
  6. Un script de `angles` que solo lee `engine.timeOfDay`: la forma
     `A · frac(B · tod) + C` en sintéticos ---con y sin `% 1`, con
     desplazamiento--- y ninguna cuando lee `engine.runtime`, el `value` que
     recibe, una hora en minutos enteros, cuando no devuelve el `Vec3`, cuando
     toca otra componente, o cuando no es una recta a tramos. Sobre el corpus,
     de los 7 scripts de `angles` la aceptan exactamente las tres agujas de
     `2396319149` (362, 368 y 371), y en ellas la forma da lo que el
     intérprete, a 1e-6 grados, en más de 2000 `tod` que incluyen 0, 0,5, los
     cambios de minuto y de hora y 0,999999.

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
    ("engine.timeOfDay", "return Math.round(engine.timeOfDay * 86400);", "63485"),
]

# Scripts cuya salida depende del motor: tienen que lanzar.
RECHAZOS = [
    ("engine.frametime", "return engine.frametime;", ""),
    ("engine.frametime acumulado", "t += engine.frametime; return 'x';", "let t = 0;"),
    ("engine.registerAudioBuffers", "return 'x';", "engine.registerAudioBuffers(64);"),
    ("engine[\"runtime\"]", "return engine['runtime'];", ""),
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


def hoja(cuerpo: str) -> list[int] | None:
    """La tabla de un `update` sintético en la propiedad `visible`."""
    return wescript.hoja_por_hora({"visible": {
        "script": f"export function update(value) {{ {cuerpo} }}",
        "value": True}})


AM_PM = ("var h = new Date().getHours();"
         "thisLayer.getTextureAnimation().setFrame(h >= 12 ? 1 : 0); return value;")

HOJAS = [
    # (qué, cuerpo de update, la tabla que tiene que salir)
    ("AM/PM", AM_PM, [0] * 12 + [1] * 12),
    ("una por hora, con fracción", "const a = thisLayer.getTextureAnimation();"
     "a.setFrame(new Date().getHours() + 0.25); return value;", list(range(24))),
    ("sin setFrame", "var h = new Date().getHours(); return h >= 12;", None),
    ("fotograma fijo", "thisLayer.getTextureAnimation().setFrame(1); return value;", None),
    ("con el minuto", "thisLayer.getTextureAnimation()"
     ".setFrame(new Date().getMinutes() % 2); return value;", None),
    ("solo por la tarde", "if (new Date().getHours() >= 12) "
     "thisLayer.getTextureAnimation().setFrame(1); return value;", None),
    ("otro método", "const a = thisLayer.getTextureAnimation(); a.pause();"
     "a.setFrame(new Date().getHours() >= 12 ? 1 : 0); return value;", None),
]


def giro(cuerpo: str) -> tuple[float, float, float] | None:
    """La forma de un `update` sintético en `angles`, guardado a 0 0 0."""
    return wescript.giro_por_hora({"angles": {
        "script": f"export function update(value) {{ {cuerpo} }}",
        "value": "0.00000 0.00000 0.00000"}})


GIROS = [
    # (qué, cuerpo de update, la forma que tiene que salir)
    ("la de las horas", "value.z = engine.timeOfDay * -720; return value;",
     (-720.0, 1.0, 0.0)),
    ("la de los minutos", "value.z = ((engine.timeOfDay * 24) % 1) * -360;"
     "return value;", (-360.0, 24.0, 0.0)),
    ("con desplazamiento", "value.z = 90 + ((engine.timeOfDay * 1440) % 1) * 360;"
     "return value;", (360.0, 1440.0, 90.0)),
    ("con una variable", "let t = engine.timeOfDay; value.z = (t * 2 % 1) * 180;"
     "return value;", (180.0, 2.0, 0.0)),
    ("engine.runtime", "value.z = engine.runtime * 10; return value;", None),
    ("lee el value", "value.z = value.z + engine.timeOfDay * 360; return value;", None),
    ("minutos enteros", "const d = new Date();"
     "value.z = (d.getHours() * 60 + d.getMinutes()) * -0.5; return value;", None),
    ("siempre el mismo", "value.z = 45; return value;", None),
    ("no devuelve", "value.z = engine.timeOfDay * 360;", None),
    ("toca la x", "value.x = 1; value.z = engine.timeOfDay * 360; return value;", None),
    ("no es una recta", "value.z = Math.sqrt(engine.timeOfDay) * 360; return value;", None),
    ("un Vec3 nuevo", "return new Vec3(0, 0, scriptProperties.r);", None),
]

# Las agujas del corpus: lo único que la forma puede aceptar.
AGUJAS = {("2396319149", 362), ("2396319149", 368), ("2396319149", 371)}


def tods_de_comprobacion() -> list[float]:
    """Más de 2000 `tod` en [0, 1), aparte de los de `_tods_de_prueba` con los
    que se acepta la forma: uno cada 24 s, cada cambio de minuto y de hora y
    1e-8 antes y después, 0, 0,5 y 0,999999."""
    tods = {k / 3600.0 for k in range(3600)}
    for m in range(1440):
        for d in (-1e-8, 0.0, 1e-8):
            tods.add(min(max(0.0, m / 1440.0 + d), 0.999999))
    tods.update({0.0, 0.5, 0.999999})
    return sorted(tods)


def giros_del_corpus(fallos: list[str]) -> None:
    """Los 7 scripts de `angles` del corpus: quién da forma y si es exacta."""
    import math
    vistos, aceptados = 0, []
    for d in sorted(wepaths.we_workshop().iterdir()):
        p = d / "scene.pkg"
        if not p.is_file():
            continue
        _, ents = pkg_inspect.read_pkg(str(p))
        sj = [e for e in ents if e["name"] == "scene.json"]
        s = json.loads(sj[0]["data"]) if sj else {}
        for o in s.get("objects") or []:
            a = o.get("angles") if isinstance(o, dict) else None
            if not (isinstance(a, dict) and isinstance(a.get("script"), str)):
                continue
            vistos += 1
            forma = wescript.giro_por_hora(o)
            print(f"  {d.name} {o.get('id'):>5} {str(o.get('name', ''))[:24]!r:28} -> {forma}")
            if forma is None:
                continue
            aceptados.append((d.name, o.get("id")))
            ip = wescript.Interprete(a["script"], {})
            v = [math.degrees(float(x)) for x in a["value"].split()]
            tods = tods_de_comprobacion()
            peor = max(abs(wescript.grados_del_giro(forma, t) - ip.giro_en(t, v))
                       for t in tods)
            ok = peor <= 1e-6 and len(tods) >= 2000
            print(f"  {'ok' if ok else 'MAL':3} {len(tods)} tod, error máximo {peor:.3g} grados")
            if not ok:
                fallos.append(f"giro {d.name} {o.get('id')}: error {peor:.3g}")
    print(f"  scripts de angles: {vistos}, con forma: {sorted(aceptados)}")
    if vistos != 7 or set(aceptados) != AGUJAS or len(aceptados) != 3:
        fallos.append(f"giros del corpus: {vistos} scripts, aceptados {aceptados}")


def hoja_del_corpus(fallos: list[str]) -> None:
    """La capa 303 de `3299228616`, y que el texto de esa escena no cambia."""
    p = wepaths.we_workshop() / "3299228616" / "scene.pkg"
    _, ents = pkg_inspect.read_pkg(str(p))
    s = json.loads([e for e in ents if e["name"] == "scene.json"][0]["data"])
    o = [o for o in s["objects"] if o.get("id") == 303][0]
    tabla = wescript.hoja_por_hora(o)
    ok = tabla == [0] * 12 + [1] * 12
    print(f"  {'ok' if ok else 'MAL':3} {'3299228616 capa 303 visible':32} {tabla}")
    if not ok:
        fallos.append(f"3299228616 capa 303: {tabla}")


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

    print("── setFrame por hora ──")
    for que, cuerpo, espera in HOJAS:
        r = hoja(cuerpo)
        ok = r == espera
        print(f"  {'ok' if ok else 'MAL':3} {que:32} {r}")
        if not ok:
            fallos.append(f"hoja {que}: {r} y tenía que ser {espera}")
    # Para un texto, `setFrame` no cambia lo que devuelve `update`.
    try:
        r = update("thisLayer.getTextureAnimation().setFrame(1); return 'x';")
    except wescript.ScriptError as e:
        r = f"ScriptError: {e}"
    print(f"  {'ok' if r == 'x' else 'MAL':3} {'setFrame en un texto':32} {r!r}")
    if r != "x":
        fallos.append(f"setFrame en un texto: {r!r}")
    hoja_del_corpus(fallos)

    print("── angles por hora ──")
    for que, cuerpo, espera in GIROS:
        r = giro(cuerpo)
        ok = (r == espera if espera is None or r is None
              else all(abs(x - y) <= 1e-9 for x, y in zip(r, espera)))
        print(f"  {'ok' if ok else 'MAL':3} {que:32} {r}")
        if not ok:
            fallos.append(f"giro {que}: {r} y tenía que ser {espera}")
    giros_del_corpus(fallos)

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
