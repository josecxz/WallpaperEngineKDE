#!/usr/bin/env python3
"""Control del motor desde la linea de comandos.

    wectl list [texto]     lista los wallpapers de la biblioteca
    wectl set <id|texto>   prepara uno y lo pone en el escritorio
    wectl start            vuelve a activar el motor
    wectl stop             devuelve el escritorio al fondo de Plasma
    wectl status           que hay puesto y como va

Todo pasa por la API de scripting de Plasma via D-Bus, que aplica el cambio
EN CALIENTE. Es la diferencia importante con `make reload`, que reinicia
plasmashell entero: ahi se pierden las ventanas de un vistazo, tarda segundos
y -- probando varios wallpapers seguidos -- agota el limite de arranques de
systemd y deja el escritorio caido. Con D-Bus nada de eso ocurre.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
from werender import emit_plan

RAIZ = Path(__file__).resolve().parent.parent
ESCENA = RAIZ / "plugin" / "contents" / "scene"
PLUGIN = "org.jose.wallpaperengine"
PLUGIN_IMAGEN = "org.kde.image"


class CtlError(RuntimeError):
    """Algo que el usuario puede arreglar; se imprime sin traza."""


# ── Plasma ──────────────────────────────────────────────────────────────────

def _script(js: str) -> str:
    """Ejecuta un script de Plasma y devuelve lo que imprima."""
    try:
        r = subprocess.run(
            ["qdbus6", "org.kde.plasmashell", "/PlasmaShell",
             "org.kde.PlasmaShell.evaluateScript", js],
            capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        raise CtlError("no se encontro qdbus6; instala qt6-tools")
    except subprocess.TimeoutExpired:
        raise CtlError("plasmashell no responde")
    if r.returncode != 0:
        err = (r.stderr or r.stdout).strip()
        if "was not provided" in err or "ServiceUnknown" in err:
            raise CtlError("plasmashell no esta corriendo")
        raise CtlError(f"plasmashell rechazo el script: {err}")
    return r.stdout.strip()


def plugins_actuales() -> list[str]:
    salida = _script(
        "var o = []; var d = desktops();"
        "for (var i = 0; i < d.length; i++) o.push(d[i].wallpaperPlugin);"
        "print(o.join(' '));")
    return salida.split() if salida else []


def poner_plugin(nombre: str) -> None:
    _script("var d = desktops();"
            "for (var i = 0; i < d.length; i++)"
            f" d[i].wallpaperPlugin = {json.dumps(nombre)};")


def recargar() -> None:
    """Fuerza a Plasma a releer el plan.

    Cambiar el fichero no basta: plasmashell no lo vigila, y volver a poner el
    mismo plugin tampoco dispara nada. Hay que salir a otro plugin y volver.
    """
    poner_plugin(PLUGIN_IMAGEN)
    poner_plugin(PLUGIN)


# ── biblioteca ──────────────────────────────────────────────────────────────

def _plano(s: str) -> str:
    """Sin acentos ni mayusculas, para buscar sin pelearse con el teclado."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


def biblioteca() -> list[tuple[str, str]]:
    """(id, titulo) de los wallpapers que son escenas, ordenados por titulo."""
    salida = []
    for d in sorted(wepaths.we_workshop().iterdir()):
        if not (d / "scene.pkg").is_file():
            continue          # video o web: este motor no los ejecuta
        try:
            proyecto = json.loads((d / "project.json").read_text())
        except Exception:
            continue
        salida.append((d.name, str(proyecto.get("title", "?"))))
    return sorted(salida, key=lambda t: _plano(t[1]))


def resolver(consulta: str) -> tuple[Path, str]:
    """Un id exacto, o el unico titulo que contenga el texto."""
    raiz = wepaths.we_workshop()
    if (raiz / consulta / "scene.pkg").is_file():
        titulos = dict(biblioteca())
        return raiz / consulta, titulos.get(consulta, consulta)

    q = _plano(consulta)
    hallados = [(i, t) for i, t in biblioteca() if q in _plano(t)]
    if not hallados:
        raise CtlError(f"ningun wallpaper coincide con {consulta!r}; "
                       f"prueba `wectl list`")
    if len(hallados) > 1:
        lineas = "\n".join(f"    {i}  {t}" for i, t in hallados[:10])
        raise CtlError(f"{consulta!r} coincide con {len(hallados)}:\n{lineas}\n"
                       f"  afina el texto o usa el id")
    return raiz / hallados[0][0], hallados[0][1]


def plan_instalado() -> str | None:
    try:
        for linea in (ESCENA / "plan.txt").read_text().splitlines():
            if linea.startswith("title "):
                return linea[6:]
    except OSError:
        return None
    return None


# ── ordenes ─────────────────────────────────────────────────────────────────

def cmd_list(args) -> int:
    entradas = biblioteca()
    if args.texto:
        q = _plano(args.texto)
        entradas = [(i, t) for i, t in entradas if q in _plano(t)]
    if not entradas:
        print("sin coincidencias")
        return 1
    puesto = plan_instalado()
    for i, t in entradas:
        marca = "*" if puesto and puesto.endswith(f"({i})") else " "
        print(f" {marca} {i:12} {t}")
    print(f"\n{len(entradas)} escenas. El * es la que hay preparada.")
    return 0


def cmd_set(args) -> int:
    ruta, titulo = resolver(args.wallpaper)
    print(f"preparando: {titulo}  ({ruta.name})")
    ESCENA.mkdir(parents=True, exist_ok=True)
    stats = emit_plan(ruta, ESCENA)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    # El modulo QML vive fuera del paquete y puede no estar instalado todavia.
    subprocess.run(["make", "-s", "install-qml", "install-package"],
                   cwd=RAIZ, check=False)
    recargar()
    print(f"puesto en el escritorio: {titulo}")
    return 0


def cmd_start(args) -> int:
    if plan_instalado() is None:
        raise CtlError("no hay ningun plan preparado; usa `wectl set <wallpaper>`")
    poner_plugin(PLUGIN)
    print(f"motor activo: {plan_instalado()}")
    return 0


def cmd_stop(args) -> int:
    poner_plugin(PLUGIN_IMAGEN)
    print("motor parado; el escritorio vuelve al fondo de Plasma")
    return 0


def cmd_status(args) -> int:
    print(f"plan preparado : {plan_instalado() or '(ninguno)'}")
    try:
        activos = plugins_actuales()
    except CtlError as e:
        print(f"escritorio     : {e}")
        return 1
    nuestros = sum(1 for p in activos if p == PLUGIN)
    print(f"escritorios    : {nuestros} de {len(activos)} con el motor")
    print(f"estado         : {'EN MARCHA' if nuestros else 'parado'}")
    reg = subprocess.run(
        ["journalctl", "--user", "-b", "-g", "SceneView", "--no-pager", "-n", "2"],
        capture_output=True, text=True)
    for linea in reg.stdout.strip().splitlines():
        if "SceneView:" in linea:
            print("  " + linea.split("SceneView:", 1)[1].strip())
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="wectl", description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="orden", required=True)

    s = sub.add_parser("list", help="lista los wallpapers de la biblioteca")
    s.add_argument("texto", nargs="?", help="filtra por titulo")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("set", help="prepara un wallpaper y lo pone")
    s.add_argument("wallpaper", help="id de Workshop o parte del titulo")
    s.set_defaults(fn=cmd_set)

    for nombre, fn, ayuda in (("start", cmd_start, "activa el motor"),
                              ("stop", cmd_stop, "para el motor"),
                              ("status", cmd_status, "que hay puesto")):
        sub.add_parser(nombre, help=ayuda).set_defaults(fn=fn)

    args = p.parse_args()
    try:
        return args.fn(args)
    except (CtlError, wepaths.WePathError) as e:
        print(f"wectl: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
