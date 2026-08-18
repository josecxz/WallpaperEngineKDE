#!/usr/bin/env python3
"""Control del motor desde la linea de comandos.

    wectl list [texto]     lista los wallpapers de la biblioteca
    wectl set <id|texto>   prepara uno y lo pone en el escritorio
    wectl shuffle          pone uno al azar; --cada <t> lo repite solo
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
import random
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
from werender import emit_plan

RAIZ = Path(__file__).resolve().parent.parent
ESCENA = RAIZ / "plugin" / "contents" / "scene"
PLUGIN = "org.jose.wallpaperengine"
PLUGIN_IMAGEN = "org.kde.image"

# Unidades de systemd que llevan la rotacion. Son de USUARIO, no del sistema:
# el motor vive dentro de plasmashell y no hay nada que rotar sin sesion.
UNIDAD = "wallpaperengine-shuffle"
UNIDADES = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) \
    / "systemd" / "user"
# Que wallpapers quedan por salir. Es estado de la maquina, no configuracion:
# XDG_STATE_HOME es justo para esto.
ESTADO = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) \
    / "wallpaperengine" / "shuffle.json"


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


def preparar(ruta: Path) -> dict:
    """Genera el plan de `ruta` y lo pone en su sitio de una pieza.

    El plan NO se escribe encima del que hay. Dos razones, y la segunda es la
    que obliga:

    * `emit_plan` numera los ficheros por indice ---`p000.frag`, `tex017.rgba`---
      y no borra lo que sobra. Escribiendo encima, un wallpaper de 20 pases sobre
      uno de 113 deja 93 sin usar. Con `set` a mano se nota poco; rotando por una
      biblioteca de 125 escenas el directorio crece hasta la union de todas.
    * Si la generacion falla a medias ---una escena rota, el disco lleno--- el
      escritorio se queda con medio plan. Generando aparte, un fallo deja intacto
      lo que ya funcionaba.

    Asi que se genera en un directorio hermano y se cambia por un rename, que es
    lo mismo que hace `install-qml` con la biblioteca y por lo mismo.

    El plan nombra sus assets por ruta absoluta, asi que hay que decirle a
    `emit_plan` donde van a ACABAR y no donde se estan escribiendo; si no, sale
    apuntando al directorio de trabajo y el motor arranca sin encontrar nada.
    """
    nueva = ESCENA.with_name(ESCENA.name + ".nueva")
    vieja = ESCENA.with_name(ESCENA.name + ".vieja")
    shutil.rmtree(nueva, ignore_errors=True)
    shutil.rmtree(vieja, ignore_errors=True)
    try:
        stats = emit_plan(ruta, nueva, ESCENA)
    except BaseException:
        shutil.rmtree(nueva, ignore_errors=True)
        raise
    if ESCENA.exists():
        ESCENA.rename(vieja)
    nueva.rename(ESCENA)
    shutil.rmtree(vieja, ignore_errors=True)
    return stats


def construir() -> None:
    """Deja el modulo QML compilado e instalado, o se para con un error.

    El modulo vive fuera del paquete y puede no estar instalado todavia, asi
    que cada cambio de fondo pasa por aqui. Con los objetos al dia son 16 ms
    medidos ---`make` no compila nada y la instalacion es copiar 261 KB---,
    o sea nada al lado del segundo largo que cuesta generar el plan.

    Se retiene **stderr** y se deja pasar la salida normal: por stdout van las
    dos lineas de donde ha quedado cada cosa, que son las que interesan, y por
    stderr los avisos del compilador, que no pintan nada en medio de un cambio
    de fondo. Si el `make` falla se vuelcan enteros; y para verlos a diario
    esta `make build`.
    """
    r = subprocess.run(["make", "-s", "install-qml", "install-package"],
                       cwd=RAIZ, stderr=subprocess.PIPE, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr)
        raise CtlError("no se pudo construir el modulo QML; el escritorio se "
                       "queda como estaba. Arreglalo y repite la orden.")


def aplicar(ruta: Path) -> dict:
    """Prepara un wallpaper y lo deja puesto en el escritorio.

    **Construir va primero, y no es un detalle de orden.** `preparar` cambia el
    plan por un rename, o sea que en cuanto vuelve ya esta el plan nuevo en su
    sitio; si el `make` fallara despues, el escritorio se quedaria con una
    escena nueva corriendo sobre el `.so` anterior ---el plan de una version y
    el motor de otra---, que es lo mas caro de depurar de todo lo que puede
    salir mal aqui. Construyendo antes, un fallo de compilacion deja las dos
    mitades como estaban.
    """
    construir()
    stats = preparar(ruta)
    recargar()
    return stats


def plan_instalado() -> str | None:
    try:
        for linea in (ESCENA / "plan.txt").read_text().splitlines():
            if linea.startswith("title "):
                return linea[6:]
    except OSError:
        return None
    return None


# ── rotacion ────────────────────────────────────────────────────────────────
#
# El "cada x tiempo" no puede vivir dentro del plugin. El QML no genera planes:
# cambiar de wallpaper es traducir shaders y decodificar texturas, o sea Python,
# ~1 s por escena. Asi que la rotacion es un temporizador de systemd de USUARIO
# que llama a este mismo `wectl`, y el plugin ni se entera --- ve un plan nuevo y
# lo carga, igual que con `set`.

SUFIJOS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
# Por debajo de un minuto el temporizador no seria honesto (systemd agrupa los
# disparos) y ademas cada cambio parpadea: `recargar` sale al fondo de Plasma y
# vuelve. Un minuto ya es absurdo, pero es decision del usuario, no nuestra.
INTERVALO_MINIMO = 60


def _intervalo(texto: str) -> int:
    """`30m`, `2h`, `90s`, `1d` -> segundos. Un numero pelado son minutos."""
    t = texto.strip().lower()
    factor = SUFIJOS.get(t[-1:], 60)
    if t[-1:] in SUFIJOS:
        t = t[:-1]
    try:
        n = float(t)
    except ValueError:
        raise CtlError(f"no entiendo el intervalo {texto!r}; "
                       f"prueba `30m`, `2h` o `90s`")
    seg = int(n * factor)
    if seg < INTERVALO_MINIMO:
        raise CtlError(f"{texto!r} son {seg} s; el minimo es "
                       f"{INTERVALO_MINIMO} s")
    return seg


def _leer_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text())
    except (OSError, ValueError):
        return {}


def _guardar_estado(estado: dict) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".json.nuevo")
    tmp.write_text(json.dumps(estado, indent=1))
    tmp.replace(ESTADO)


def _sacar_de_la_bolsa(estado: dict, entradas: list[tuple[str, str]]) -> str:
    """El siguiente wallpaper, sacado de una bolsa que se rellena al vaciarse.

    Sortear cada vez sobre la lista entera es lo obvio y es lo peor: con 125
    escenas, la probabilidad de repetir alguna en las diez primeras vueltas es
    casi 1, y el usuario ve dos veces la misma antes que decenas que no han
    salido nunca. Con bolsa salen TODAS antes de que se repita ninguna.

    La bolsa se guarda en disco porque cada cambio es un proceso distinto: lo
    lanza el temporizador y muere. Se filtra contra la biblioteca en cada
    llamada, asi que suscribirse a un wallpaper nuevo o borrar uno no la rompe.
    """
    validos = {i for i, _ in entradas}
    bolsa = [i for i in estado.get("bolsa", []) if i in validos]
    if not bolsa:
        bolsa = sorted(validos)
        random.shuffle(bolsa)
        # La costura entre dos vueltas es el unico sitio donde la bolsa puede
        # repetir: si el ultimo de una es el primero de la siguiente. Se cambia
        # por otro y ya no hay forma de ver dos veces seguidas lo mismo.
        if len(bolsa) > 1 and bolsa[-1] == estado.get("puesto"):
            bolsa[0], bolsa[-1] = bolsa[-1], bolsa[0]
    elegido = bolsa.pop()
    estado["bolsa"] = bolsa
    return elegido


def _systemctl(*args: str, comprobar: bool = True) -> str:
    try:
        r = subprocess.run(["systemctl", "--user", *args],
                           capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        raise CtlError("no se encontro systemctl; la rotacion necesita systemd")
    except subprocess.TimeoutExpired:
        raise CtlError("systemd no responde")
    if comprobar and r.returncode != 0:
        raise CtlError(f"systemd rechazo la orden: "
                       f"{(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def rotacion_encender(segundos: int) -> None:
    """Instala y arranca el temporizador de usuario.

    La descripcion se compone con los segundos ya interpretados y no con lo que
    escribio el usuario: un fichero de unidad es una linea por directiva, asi que
    un `--cada` con un salto de linea dentro colaria directivas nuevas en la
    unidad. Nadie va a atacarse a si mismo, pero tampoco cuesta nada.
    """
    UNIDADES.mkdir(parents=True, exist_ok=True)
    yo = Path(__file__).resolve()
    (UNIDADES / f"{UNIDAD}.service").write_text(f"""\
[Unit]
Description=Cambia el fondo de WallpaperEngine a otro al azar
Documentation=file://{RAIZ}/README.md
# Sin plasmashell no hay a quien pedirle el cambio; ver `wectl shuffle`.
After=plasma-plasmashell.service
PartOf=graphical-session.target

[Service]
Type=oneshot
WorkingDirectory={RAIZ}
ExecStart={sys.executable} {yo} shuffle
""")
    (UNIDADES / f"{UNIDAD}.timer").write_text(f"""\
[Unit]
Description=Rota el fondo de WallpaperEngine cada {_en_palabras(segundos)}
PartOf=graphical-session.target

[Timer]
# El primer disparo cuenta desde que arranca el temporizador y los siguientes
# desde el anterior, asi que el intervalo se respeta tambien tras un `set` a
# mano o una sesion nueva.
OnActiveSec={segundos}
OnUnitActiveSec={segundos}
AccuracySec=1s

[Install]
WantedBy=graphical-session.target
""")
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", f"{UNIDAD}.timer")


def rotacion_apagar() -> None:
    _systemctl("disable", "--now", f"{UNIDAD}.timer", comprobar=False)
    for u in (f"{UNIDAD}.timer", f"{UNIDAD}.service"):
        (UNIDADES / u).unlink(missing_ok=True)
    _systemctl("daemon-reload", comprobar=False)


def _proximo_disparo() -> float | None:
    """Segundos que faltan para el siguiente cambio, o None si no se sabe.

    Se pregunta por D-Bus y no con `systemctl show`: el disparo de un
    temporizador monotono sale por ahi como `NextElapseUSecMonotonic=2h 8min
    6.555745s`, ya formateado para leerlo, y volver a convertir ESO en un numero
    es analizar la salida bonita de una herramienta. La propiedad cruda son
    microsegundos desde el arranque, que es lo que hay que restarle al uptime.

    Cualquier tropiezo devuelve None y el estado se limita a no decir cuanto
    falta, que es mejor que inventarse una hora.
    """
    def dbus(*args: str) -> str:
        r = subprocess.run(["busctl", "--user", *args],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""

    try:
        ruta = dbus("call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                    "org.freedesktop.systemd1.Manager", "GetUnit", "s",
                    f"{UNIDAD}.timer")
        if not ruta.startswith('o "'):
            return None
        valor = dbus("get-property", "org.freedesktop.systemd1",
                     ruta[3:].rstrip('"'), "org.freedesktop.systemd1.Timer",
                     "NextElapseUSecMonotonic")
        proximo = int(valor.split()[1]) / 1e6
        arriba = float(Path("/proc/uptime").read_text().split()[0])
        return max(0.0, proximo - arriba)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def rotacion_estado() -> tuple[str, bool, float | None] | None:
    """`(descripcion, si esta andando, segundos que faltan)`; None si no hay."""
    if not (UNIDADES / f"{UNIDAD}.timer").is_file():
        return None
    salida = _systemctl("show", f"{UNIDAD}.timer", "--property=ActiveState",
                        "--property=Description", comprobar=False)
    campos = dict(l.split("=", 1) for l in salida.splitlines() if "=" in l)
    descripcion = campos.get("Description") or "rotacion"
    if campos.get("ActiveState") != "active":
        return (descripcion, False, None)
    return (descripcion, True, _proximo_disparo())


def _en_palabras(segundos: float) -> str:
    if segundos < 90:
        return f"{segundos:.0f} s"
    if segundos < 5400:
        return f"{segundos / 60:.0f} min"
    return f"{segundos / 3600:.1f} h"


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
    stats = aplicar(ruta)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"puesto en el escritorio: {titulo}")
    return 0


def cmd_shuffle(args) -> int:
    if args.parar:
        rotacion_apagar()
        print("rotacion parada; el fondo se queda como esta")
        return 0

    # El intervalo se interpreta ANTES de tocar el escritorio: un `--cada` mal
    # escrito tiene que quedarse en un error, no en un fondo cambiado y un error.
    segundos = _intervalo(args.cada) if args.cada else None

    entradas = biblioteca()
    if not entradas:
        raise CtlError("no hay escenas en la biblioteca")

    estado = _leer_estado()
    raiz = wepaths.we_workshop()
    titulos = dict(entradas)
    # Si una escena no se deja preparar se pasa a la siguiente en vez de dejar
    # el escritorio como estaba: el usuario pidio un cambio. No se apunta como
    # rota --- una lista negra en disco envejece mal y se lleva por delante lo
    # que fallo un dia por el disco lleno ---, asi que volvera a intentarse en
    # la siguiente vuelta, que es un segundo perdido cada 125 cambios.
    errores = []
    # Construir aqui fuera y no solo dentro de `aplicar`: el bucle se traga
    # cualquier excepcion para pasar a la siguiente escena, y un `make` roto
    # falla igual con las cinco. Sin esto, un error de compilacion se reporta
    # como "ninguna de las escenas probadas se pudo preparar", que manda a
    # mirar la biblioteca cuando el problema es el motor.
    construir()
    for _ in range(min(5, len(entradas))):
        elegido = _sacar_de_la_bolsa(estado, entradas)
        titulo = titulos.get(elegido, elegido)
        try:
            aplicar(raiz / elegido)
        except Exception as e:
            errores.append(f"  {titulo} ({elegido}): {type(e).__name__}: {e}")
            continue
        estado["puesto"] = elegido
        _guardar_estado(estado)
        if errores:
            print("no se pudieron preparar:", file=sys.stderr)
            print("\n".join(errores), file=sys.stderr)
        print(f"al azar: {titulo}  ({elegido})")
        print(f"quedan {len(estado['bolsa'])} de {len(entradas)} "
              f"antes de repetir")
        if segundos is not None:
            rotacion_encender(segundos)
            print(f"rotacion activada: otro cada {_en_palabras(segundos)}")
        return 0

    _guardar_estado(estado)
    raise CtlError("ninguna de las escenas probadas se pudo preparar:\n"
                   + "\n".join(errores))


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
    rot = rotacion_estado()
    if rot is None:
        print("rotacion       : parada")
    else:
        descripcion, andando, faltan = rot
        if not andando:
            print(f"rotacion       : instalada pero parada ({descripcion})")
        elif faltan is None:
            print(f"rotacion       : {descripcion}")
        else:
            cuando = datetime.now().timestamp() + faltan
            print(f"rotacion       : {descripcion}; el siguiente en "
                  f"{_en_palabras(faltan)} "
                  f"({datetime.fromtimestamp(cuando):%H:%M})")
        bolsa = _leer_estado().get("bolsa")
        if bolsa is not None:
            print(f"                 quedan {len(bolsa)} sin repetir")
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

    s = sub.add_parser("shuffle", help="pone uno al azar de toda la biblioteca")
    s.add_argument("--cada", metavar="TIEMPO",
                   help="ademas, repetirlo solo cada TIEMPO: 30m, 2h, 90s")
    s.add_argument("--parar", action="store_true",
                   help="para la rotacion automatica")
    s.set_defaults(fn=cmd_shuffle)

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
