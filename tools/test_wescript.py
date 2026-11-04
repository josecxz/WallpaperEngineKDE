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
  7. `Math.sin` y `Math.cos`, y `engine.runtime` cuando quien evalúa lo da
     (`vector_en`); en un texto sigue siendo un ScriptError. Un script de
     `angles` o de `origin` que oscila con él: la forma
     `K + A · sin(ω · t + φ)` en sintéticos ---con seno, con coseno y fase,
     con producto de los dos, con ω negativa---, y ninguna cuando suma dos
     senos, lee el `value`, lee la hora, toca una componente que no es suya,
     no es periódico o no cambia. Sobre el corpus, de todos los scripts de
     `angles` y `origin` la dan exactamente `3050043876`/338 (`angles`,
     0 + 3·sin(1·t)) y `3521337568`/222 (`origin`, y = 992.82019 +
     10·sin(1·t)), y la forma da lo que el intérprete a 1e-6 en 2400 tiempos
     de [0, 600] s que no son los de la aceptación.

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
    ("Math.sin", "return [Math.sin(0), Math.round(Math.sin(1.5707963267948966) * 1000)].join(',');",
     "0,1000"),
    ("Math.cos", "return [Math.cos(0), Math.round(Math.cos(3.141592653589793) * 10)].join(',');",
     "1,-10"),
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

def vaiven(cuerpo: str, campo: str = "origin", modulo: str = ""):
    """Las formas de un `update` sintético en `campo`, guardado a 10 20 0,
    con `modulo` delante en el cuerpo del módulo."""
    return wescript.vaiven_de({campo: {
        "script": f"{modulo} export function update(value) {{ {cuerpo} }}",
        "value": "10.00000 20.00000 0.00000"}}, campo)


VAIVENES = [
    # (qué, campo, cuerpo de update, las formas que tienen que salir)
    ("seno en y", "origin",
     "value.y = 992.82019 + (Math.sin(engine.runtime * 1) * 10); return value;",
     [(1, (992.82019, 10.0, 1.0, 0.0))]),
    ("coseno con fase", "origin",
     "value.x = 5 + Math.cos(engine.runtime * 2.5 + 1) * 7; return value;",
     [(0, (5.0, 7.0, 2.5, 1.0 + 1.5707963267948966))]),
    ("x e y a la vez", "origin",
     "let t = engine.runtime; return {x: 3 + Math.sin(t * 0.5) * 2,"
     " y: Math.cos(t * 0.25) * 4, z: value.z};",
     [(0, (3.0, 2.0, 0.5, 0.0)), (1, (0.0, 4.0, 0.25, 1.5707963267948966))]),
    ("producto de seno y coseno", "origin",
     "value.x = Math.sin(engine.runtime * 0.3) * Math.cos(engine.runtime * 0.3);"
     "return value;", [(0, (0.0, 0.5, 0.6, 0.0))]),
    ("ω negativa", "origin",
     "value.y = Math.sin(-engine.runtime * 40) * 2; return value;", None),
    ("balanceo en angles", "angles",
     "value.z = 0 + (Math.sin(engine.runtime * 1) * 3); return value;",
     [(2, (0.0, 3.0, 1.0, 0.0))]),
    ("dos senos", "origin",
     "value.y = Math.sin(engine.runtime) + Math.sin(2 * engine.runtime); return value;", None),
    ("lee el value", "origin",
     "value.y = value.y + Math.sin(engine.runtime); return value;", None),
    ("lee la hora", "origin",
     "value.y = Math.sin(engine.runtime + new Date().getSeconds()); return value;", None),
    ("lee timeOfDay", "origin",
     "value.y = Math.sin(engine.runtime) * engine.timeOfDay; return value;", None),
    ("la z de origin", "origin",
     "value.z = Math.sin(engine.runtime); return value;", None),
    ("la x de angles", "angles",
     "value.x = Math.sin(engine.runtime); return value;", None),
    ("no es periódico", "origin",
     "value.y = Math.sin(engine.runtime * engine.runtime); return value;", None),
    ("una recta", "origin", "value.y = engine.runtime * 3; return value;", None),
    ("siempre el mismo", "origin", "value.y = 3; return value;", None),
    ("no devuelve", "origin", "value.y = Math.sin(engine.runtime);", None),
]

# Las capas del corpus que pueden dar vaivén: escena, capa y campo.
VAIVENES_CORPUS = {("3050043876", 338, "angles"), ("3521337568", 222, "origin")}


def vaivenes_del_corpus(fallos: list[str]) -> None:
    """Los scripts de `angles` y `origin` del corpus: quién da vaivén y si es
    exacto, en 2400 tiempos que no son los de `_tiempos_de_prueba`."""
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
            for campo in ("angles", "origin"):
                a = o.get(campo) if isinstance(o, dict) else None
                if not (isinstance(a, dict) and isinstance(a.get("script"), str)):
                    continue
                vistos += 1
                formas = wescript.vaiven_de(o, campo)
                if formas is None:
                    continue
                aceptados.append((d.name, o.get("id"), campo))
                props = {k: (v.get("value") if isinstance(v, dict) else v)
                         for k, v in (a.get("scriptproperties") or {}).items()}
                ip = wescript.Interprete(a["script"], props)
                v = [float(x) for x in a["value"].split()]
                if campo == "angles":
                    v = [math.degrees(x) for x in v]
                ts = [0.1234 + k * 0.25 for k in range(2400)]
                peor = max(abs(wescript.valor_del_vaiven(f, t) - ip.vector_en(t, v)[i])
                           for t in ts for i, f in formas)
                ok = peor <= 1e-6
                print(f"  {'ok' if ok else 'MAL':3} {d.name} {o.get('id'):>5} {campo} "
                      f"{formas}: {len(ts)} t, error máximo {peor:.3g}")
                if not ok:
                    fallos.append(f"vaiven {d.name} {o.get('id')}: error {peor:.3g}")
    print(f"  scripts de angles y origin: {vistos}, con vaivén: {sorted(aceptados)}")
    if set(aceptados) != VAIVENES_CORPUS or len(aceptados) != 2:
        fallos.append(f"vaivenes del corpus: aceptados {aceptados}")


def fijo(cuerpo: str, campo: str = "origin", modulo: str = "",
         valor="10.00000 20.00000 0.00000", props=None):
    """`valor_fijo_de` de un `update` sintético en `campo`, en un lienzo de
    3840x2160."""
    return wescript.valor_fijo_de({campo: {
        "script": f"{modulo} export function update(value) {{ {cuerpo} }}",
        "value": valor, "scriptproperties": props or {}}}, campo, (3840.0, 2160.0))


FIJOS = [
    # (qué, campo, cuerpo de update, módulo, lo que tiene que salir)
    ("deslizador por el lienzo", "origin",
     "value.x = scriptProperties.x * engine.canvasSize.x;"
     "value.y = scriptProperties.y * engine.canvasSize.y; return value;", "",
     [-1029.12, -1239.84, 0.0]),
    ("un Vec3 nuevo", "origin", "return new Vec3(1, 2, value.z);", "", [1.0, 2.0, 0.0]),
    ("con init", "origin", "return new Vec3(base.x * 2, base.y, base.z);",
     "let base; export function init(value) { base = value; }", [20.0, 20.0, 0.0]),
    ("solo la y", "origin", "value.y = 7; return value;", "", [10.0, 7.0, 0.0]),
    ("alpha", "alpha", "return 0.25;", "", [0.25]),
    ("angles en grados", "angles", "value.z = 90; return value;", "",
     [10.0, 20.0, 1.5707963267948966]),
    ("lo mismo que guardó", "origin", "return value;", "", None),
    ("lee engine.runtime", "origin", "value.y = engine.runtime; return value;", "", None),
    ("lee la hora", "origin", "value.y = new Date().getHours(); return value;", "", None),
    ("lee el value", "origin", "value.y = value.y + 1; return value;", "", None),
    ("acumula", "origin", "n = n + 1; value.y = n; return value;", "let n = 0;", None),
    ("no devuelve", "origin", "value.y = 3;", "", None),
    ("devuelve un número", "origin", "return 3;", "", [3.0, 3.0, 3.0]),
    ("plantilla de audio en silencio", "scale",
     "const d = scriptProperties.maxvalue - scriptProperties.minvalue;"
     "const a = audio.average[scriptProperties.frequency] - s;"
     "s += a * Math.min(1.0, engine.frametime * scriptProperties.smoothing);"
     "s = Math.min(1.0, s); return ini * (s * d + scriptProperties.minvalue);",
     "const audio = engine.registerAudioBuffers(engine.AUDIO_RESOLUTION_16);"
     "let s = 0; let ini;"
     "export var scriptProperties = createScriptProperties()"
     ".addSlider({name: 'frequency', value: 0}).addSlider({name: 'smoothing', value: 15})"
     ".addSlider({name: 'minvalue', value: 0.8}).addSlider({name: 'maxvalue', value: 1.2})"
     ".finish();"
     "export function init(value) { ini = (typeof value === 'number') ? value : value.x; }",
     [8.0, 8.0, 8.0]),
    ("audio que acumula", "origin", "t += engine.frametime; value.y = t; return value;",
     "const a = engine.registerAudioBuffers(16); let t = 0;", None),
    ("resolución de audio que WE no admite", "origin", "return new Vec3(1, 2, 3);",
     "const a = engine.registerAudioBuffers(20);", None),
    ("sin lienzo en el motor", "origin", "value.x = engine.screenResolution.x; return value;",
     "", None),
    ("con un suceso del ratón", "origin", "return new Vec3(1, 2, 3);",
     "export function cursorClick(e) {}", None),
    ("con un suceso de la música", "color", "return c;",
     "let c = new Vec3(0, 0, 0); export function mediaThumbnailChanged(e) "
     "{ c = e.primaryColor; }", None),
    ("con applyUserProperties", "origin", "return new Vec3(1, 2, 3);",
     "export function applyUserProperties(p) {}", None),
]

# Los campos del corpus que dan un valor fijo, por escena: los 19 `origin`
# que coloca un deslizador en `3462491575` y la capa `定位` de `3521337568`;
# y las 19 `scale` con la plantilla de WE de respuesta al audio, en silencio:
# 17 en `3462491575` y una `dragonink1` en `3238423642` y en `3810943704`.
FIJOS_CORPUS = {"3462491575": 36, "3521337568": 1, "3238423642": 1,
                "3810943704": 1}


def fijos_del_corpus(fallos: list[str]) -> None:
    """Los campos con script del corpus, con las propiedades del usuario ya
    puestas como hace `wescene`: quién da valor fijo, y que sean los de
    `FIJOS_CORPUS`."""
    import wescene
    vistos, por_escena = 0, {}
    for d in sorted(wepaths.we_workshop().iterdir()):
        p = d / "scene.pkg"
        if not p.is_file():
            continue
        _, ents = pkg_inspect.read_pkg(str(p))
        sj = [e for e in ents if e["name"] == "scene.json"]
        s = json.loads(sj[0]["data"]) if sj else {}
        try:
            props = json.loads((d / "project.json").read_text()).get(
                "general", {}).get("properties", {})
        except (OSError, ValueError):
            props = {}
        wescene._refrescar_valores_de_usuario(s, props or {})
        proj = (s.get("general") or {}).get("orthogonalprojection") or {}
        lienzo = (float(proj["width"]), float(proj["height"])) \
            if "width" in proj and "height" in proj else None
        for o in s.get("objects") or []:
            for campo in wescript.CAMPOS_FIJOS:
                a = o.get(campo) if isinstance(o, dict) else None
                if not (isinstance(a, dict) and isinstance(a.get("script"), str)):
                    continue
                vistos += 1
                if wescript.valor_fijo_de(o, campo, lienzo) is not None:
                    por_escena[d.name] = por_escena.get(d.name, 0) + 1
    ok = por_escena == FIJOS_CORPUS
    print(f"  {'ok' if ok else 'MAL':3} campos con script: {vistos}, fijos: {por_escena}")
    if not ok:
        fallos.append(f"fijos del corpus: {por_escena}")


def deslizador_en_un_vector(fallos: list[str]) -> None:
    """Un deslizador atado a un campo de tres componentes las pone todas."""
    import wescene
    escena = {"objects": [{"scale": {"user": "s", "value": "1.00000 1.00000 1.00000"},
                           "alpha": {"user": "a", "value": 1.0}}]}
    wescene._refrescar_valores_de_usuario(
        escena, {"s": {"type": "slider", "value": 0.403},
                 "a": {"type": "slider", "value": 0.5}})
    o = escena["objects"][0]
    r = (o["scale"]["value"], o["alpha"]["value"])
    ok = r == ("0.403 0.403 0.403", 0.5)
    print(f"  {'ok' if ok else 'MAL':3} {'deslizador en una scale':32} {r}")
    if not ok:
        fallos.append(f"deslizador en un vector: {r}")


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

    print("── vaivén con engine.runtime ──")
    ip = wescript.Interprete(
        "export function update(value) { value.x = engine.runtime; return value; }", {})
    r = ip.vector_en(2.5, [1.0, 2.0, 3.0])
    print(f"  {'ok' if r == [2.5, 2.0, 3.0] else 'MAL':3} {'engine.runtime con vector_en':32} {r}")
    if r != [2.5, 2.0, 3.0]:
        fallos.append(f"engine.runtime con vector_en: {r}")
    for que, campo, cuerpo, espera in VAIVENES:
        r = vaiven(cuerpo, campo)
        ok = (r == espera if espera is None or r is None else
              len(r) == len(espera) and all(
                  i == j and all(abs(x - y) <= 1e-9 for x, y in zip(f, g))
                  for (i, f), (j, g) in zip(r, espera)))
        # Con ω negativa la forma sale con ω positiva y la fase de ±π; lo que
        # cuenta es que exista y dé el script, y eso lo mira el corpus.
        if que == "ω negativa":
            ok = r is not None and len(r) == 1 and abs(r[0][1][2] - 40.0) <= 1e-9 \
                and abs(abs(r[0][1][3]) - 3.141592653589793) <= 1e-9
        print(f"  {'ok' if ok else 'MAL':3} {que:32} {r}")
        if not ok:
            fallos.append(f"vaiven {que}: {r} y tenía que ser {espera}")
    # Con cuentas propias: la x alterna con cada llamada, aunque la y sea un
    # seno limpio. Sin `let n` en el módulo ni siquiera llegaría a evaluarse.
    r = vaiven("n = n + 1; value.y = Math.sin(engine.runtime); value.x = n % 2;"
               "return value;", modulo="let n = 0;")
    print(f"  {'ok' if r is None else 'MAL':3} {'cuenta llamadas':32} {r}")
    if r is not None:
        fallos.append(f"vaiven cuenta llamadas: {r}")
    r = vaiven("n = n + 1; value.y = Math.sin(engine.runtime) + (n > 3000 ? 1 : 0);"
               "return value;", modulo="let n = 0;")
    print(f"  {'ok' if r is None else 'MAL':3} {'cambia tras muchas llamadas':32} {r}")
    if r is not None:
        fallos.append(f"vaiven cambia tras muchas llamadas: {r}")
    vaivenes_del_corpus(fallos)

    print("── valor fijo ──")
    for que, campo, cuerpo, modulo, espera in FIJOS:
        valor = "1.0" if campo == "alpha" else "10.00000 20.00000 0.00000"
        r = fijo(cuerpo, campo, modulo, valor,
                 {"x": -0.268, "y": -0.574} if "deslizador" in que else None)
        ok = (r == espera if espera is None or r is None else
              len(r) == len(espera) and all(abs(x - y) <= 1e-9 for x, y in zip(r, espera)))
        print(f"  {'ok' if ok else 'MAL':3} {que:32} {r}")
        if not ok:
            fallos.append(f"valor fijo {que}: {r} y tenía que ser {espera}")
    deslizador_en_un_vector(fallos)
    fijos_del_corpus(fallos)

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
