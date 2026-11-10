#!/usr/bin/env python3
"""Control del motor desde la linea de comandos.

    wectl list [texto]     lista los wallpapers de la biblioteca
    wectl set <id|texto>   prepara uno y lo pone en el escritorio
    wectl shuffle          pone uno al azar; --cada <t> lo repite solo
    wectl shuffletime <t>   ajusta cada cuanto rota, sin cambiar el fondo
    wectl start            vuelve a activar el motor
    wectl stop             para el motor (en Plasma, vuelve su fondo)
    wectl status           que hay puesto y como va
    wectl gpu [dedicated|integrated]  en que grafica se dibuja el fondo
    wectl pantallas [mismo|independiente]  un wallpaper para todas o uno al
                           azar por pantalla (Hyprland)

Todo pasa por la API de scripting de Plasma via D-Bus, que aplica el cambio
EN CALIENTE. Es la diferencia importante con `make reload`, que reinicia
plasmashell entero: ahi se pierden las ventanas de un vistazo, tarda segundos
y -- probando varios wallpapers seguidos -- agota el limite de arranques de
systemd y deja el escritorio caido. Con D-Bus nada de eso ocurre.

En Hyprland las mismas ordenes llevan el fondo de `hyprland/main.qml`, que va
como unidad de systemd de usuario (`wallpaperengine-hyprland`) y se recarga
solo al cambiar el plan. Se elige por `HYPRLAND_INSTANCE_SIGNATURE` /
`XDG_CURRENT_DESKTOP`; ver "Hyprland" mas abajo.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
import werender
from werender import emit_plan

RAIZ = Path(__file__).resolve().parent.parent
ESCENA = RAIZ / "plugin" / "contents" / "scene"
# Un plan por monitor, en `PANTALLAS/<monitor>/`, cuando cada pantalla lleva el
# suyo (`wectl pantallas independiente`, solo en Hyprland).
PANTALLAS = RAIZ / "plugin" / "contents" / "pantallas"
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


# ── Hyprland ────────────────────────────────────────────────────────────────
#
# Fuera de Plasma el fondo no es un plugin sino un proceso propio,
# `hyprland/main.qml`: una superficie layer-shell por monitor con el mismo
# modulo QML. Va como unidad transitoria de systemd de usuario y no como hijo
# de `wectl`, por dos razones: `shuffle` corre en un servicio oneshot, y
# systemd mata todo su cgroup al terminar ---el fondo moriria con el primer
# cambio---; y asi se reinicia solo si se cae.
#
# Reiniciarse solo tiene un peligro: al salir de Hyprland el proceso aborta, y
# el limite de arranques de systemd no lo para (5 en 10 s, y con RestartSec=2 no
# llegan). Si la sesion siguiente es Plasma, su `wayland-1` se llama igual y el
# fondo arranca dentro, con el motor de plasmashell al lado. Por eso cada
# arranque pregunta antes a la instancia de Hyprland que lo creo; la ruta del
# socket no vale, porque se queda en disco cuando el compositor muere.

UNIDAD_HYPRLAND = "wallpaperengine-hyprland"
ANFITRION = RAIZ / "hyprland" / "main.qml"
QML = Path("/usr/lib/qt6/bin/qml")
MODULOS_QML = Path.home() / ".local" / "lib" / "qt6" / "qml"
REGISTRO_HYPRLAND = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) \
    / "wallpaperengine-hyprland.log"
# Lo que en Plasma guarda el panel de ajustes. `gpu` lo escribe `wectl gpu`;
# `opciones` se edita a mano: las de la cabecera de hyprland/main.qml
# (`["--pausa", "2", "--encaje", "1", "--hud"]`).
CONFIG_HYPRLAND = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) \
    / "wallpaperengine" / "hyprland.json"


def en_hyprland() -> bool:
    """Si la sesion es de Hyprland. Vale tambien dentro del servicio de la
    rotacion: Hyprland exporta su firma al entorno de systemd de usuario."""
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) \
        or "hyprland" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


def _config_hyprland(para_escribir: bool = False) -> dict:
    """Lo que hay en `hyprland.json`, o `{}` si no se entiende.

    Se edita a mano. Si esta roto, el fondo arranca con los valores por
    defecto y se avisa; pero no se escribe encima, que se perderia lo que
    tiene. Ver NOTAS, «`hyprland.json` escrito a mano».
    """
    try:
        texto = CONFIG_HYPRLAND.read_text()
    except OSError:
        return {}
    try:
        datos = json.loads(texto)
        if not isinstance(datos, dict):
            raise ValueError("no es un objeto {...}")
    except ValueError as e:
        if para_escribir:
            raise CtlError(f"{CONFIG_HYPRLAND} no se entiende ({e}); arreglalo "
                           f"o borralo antes, que si no se perderia lo que tiene")
        _avisa(f"wectl: {CONFIG_HYPRLAND} no se entiende ({e}); "
               f"se usan los valores por defecto")
        return {}
    return datos


def _opciones_hyprland(cfg: dict) -> list[str]:
    """`opciones` como argumentos de hyprland/main.qml. Lo que no sea una
    lista se ignora con un aviso: un texto se iteraba letra a letra."""
    opciones = cfg.get("opciones", [])
    if isinstance(opciones, list):
        return [str(o) for o in opciones]
    _avisa(f"wectl: `opciones` en {CONFIG_HYPRLAND} tiene que ser una lista, "
           f'como ["--pausa", "2", "--hud"]; se ignora')
    return []


_AVISADOS: set[str] = set()


def _avisa(texto: str) -> None:
    """Un aviso por stderr, una sola vez aunque se lea varias veces."""
    if texto not in _AVISADOS:
        _AVISADOS.add(texto)
        print(texto, file=sys.stderr)


def _guardar_config_hyprland(datos: dict) -> None:
    CONFIG_HYPRLAND.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_HYPRLAND.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(CONFIG_HYPRLAND)


MODOS_PANTALLAS = ("mismo", "independiente")


def modo_pantallas() -> str:
    """`mismo` (un plan para todas las pantallas) o `independiente`.

    Vale para las dos sesiones, aunque viva en `hyprland.json`."""
    m = _config_hyprland().get("pantallas")
    return m if m in MODOS_PANTALLAS else "mismo"


def monitores_hyprland() -> list[tuple[str, int, int]]:
    """Nombre y pixeles de cada monitor encendido, en el orden de Hyprland."""
    try:
        r = subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True,
                           text=True, timeout=10)
        datos = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    salida = []
    for m in datos if isinstance(datos, list) else []:
        if m.get("disabled") or m.get("mirrorOf", "none") not in ("none", None):
            continue
        w, h = m.get("width"), m.get("height")
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            # Girado 90/270 grados, el panel es alto: el plan tambien.
            if m.get("transform", 0) % 2 == 1:
                w, h = h, w
            salida.append((str(m.get("name")), w, h))
    return salida


def monitores_plasma() -> list[tuple[str, int, int]]:
    """Nombre y pixeles de cada salida encendida, segun `kscreen-doctor`."""
    try:
        r = subprocess.run(["kscreen-doctor", "-j"], capture_output=True,
                           text=True, timeout=10)
        salidas = json.loads(r.stdout).get("outputs", [])
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    salida = []
    for o in salidas:
        if not o.get("enabled"):
            continue
        modo = next((m for m in o.get("modes", [])
                     if m.get("id") == o.get("currentModeId")), None)
        tam = (modo or {}).get("size") or {}
        w, h = tam.get("width"), tam.get("height")
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            # El modo es el del panel, sin girar: igual que en Hyprland.
            if o.get("rotation") in ROTACIONES_ALTAS:
                w, h = h, w
            salida.append((str(o.get("name")), w, h))
    return salida


def monitores() -> list[tuple[str, int, int]]:
    """Los monitores de la sesion en curso, sea cual sea."""
    return monitores_hyprland() if en_hyprland() else monitores_plasma()


def fondo_hyprland() -> bool:
    """Si el fondo de Hyprland esta en marcha."""
    r = subprocess.run(["systemctl", "--user", "is-active", "--quiet",
                        UNIDAD_HYPRLAND], capture_output=True)
    return r.returncode == 0


def _estado_hyprland() -> str:
    """El `ActiveState` de la unidad del fondo; `inactive` si no existe."""
    r = subprocess.run(["systemctl", "--user", "show", "-p", "ActiveState",
                        "--value", UNIDAD_HYPRLAND], capture_output=True, text=True)
    return r.stdout.strip() or "inactive"


def hyprland_arrancar() -> None:
    # Tras un fallo, durante el `RestartSec` la unidad esta en `activating`:
    # systemd la levanta sola, y otro `systemd-run` con su nombre se rechaza.
    # Un `stop` a medias se espera.
    for _ in range(50):
        estado = _estado_hyprland()
        if estado != "deactivating":
            break
        time.sleep(0.1)
    if estado in ("active", "activating", "reloading"):
        return
    if not (ESCENA / "plan.txt").is_file():
        raise CtlError("no hay ningun plan preparado; usa `wectl set <wallpaper>`")
    if not QML.is_file():
        raise CtlError(f"no se encontro {QML}; instala qt6-declarative")
    cfg = _config_hyprland()
    opciones = _opciones_hyprland(cfg)
    gpu = "integrada" if cfg.get("gpu") == "integrada" else "dedicada"
    planes = []
    if modo_pantallas() == "independiente":
        # El vigia de cada monitor mira este directorio para ver aparecer su
        # plan; si no existiera, no veria nada hasta el siguiente arranque.
        PANTALLAS.mkdir(parents=True, exist_ok=True)
        planes = ["--planes", str(PANTALLAS)]
    entorno = {"QT_FORCE_STDERR_LOGGING": "1",
               # Para que `hyprland/main.qml` lea el plan y sepa si es web.
               "QML_XHR_ALLOW_FILE_READ": "1",
               "QML_IMPORT_PATH": ":".join(
                   p for p in (str(MODULOS_QML), os.environ.get("QML_IMPORT_PATH"))
                   if p)}
    # Lo que hace falta para hablar con el compositor, por si systemd no lo
    # tiene: en esta sesion si, pero depende de como se arranque Hyprland.
    for var in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
                "XDG_CURRENT_DESKTOP", "XDG_RUNTIME_DIR"):
        if os.environ.get(var):
            entorno[var] = os.environ[var]
    # Una unidad fallida con el mismo nombre impide crear la nueva.
    subprocess.run(["systemctl", "--user", "reset-failed", UNIDAD_HYPRLAND],
                   capture_output=True)
    orden = ["systemd-run", "--user", "--quiet", "--collect",
             f"--unit={UNIDAD_HYPRLAND}",
             "--description=Fondo de WallpaperEngine en Hyprland",
             "-p", "Restart=on-failure", "-p", "RestartSec=2",
             "-p", f"ExecCondition={shutil.which('hyprctl') or 'hyprctl'} version",
             "-p", f"StandardOutput=truncate:{REGISTRO_HYPRLAND}",
             "-p", "StandardError=inherit",
             *[f"--setenv={k}={v}" for k, v in entorno.items()],
             str(QML), str(ANFITRION), "--",
             "--plan", str(ESCENA / "plan.txt"), "--gpu", gpu, *planes, *opciones]
    try:
        r = subprocess.run(orden, capture_output=True, text=True)
    except FileNotFoundError:
        raise CtlError("no se encontro systemd-run; el fondo de Hyprland lo necesita")
    if r.returncode != 0:
        raise CtlError(f"no arranco el fondo de Hyprland: {r.stderr.strip()}")


def hyprland_parar() -> None:
    subprocess.run(["systemctl", "--user", "stop", UNIDAD_HYPRLAND],
                   capture_output=True)
    subprocess.run(["systemctl", "--user", "reset-failed", UNIDAD_HYPRLAND],
                   capture_output=True)


def _registro_hyprland(patron: str, n: int) -> list[str]:
    """Las ultimas `n` lineas del motor en el registro del fondo de Hyprland."""
    try:
        lineas = REGISTRO_HYPRLAND.read_text(errors="replace").splitlines()
    except OSError:
        return []
    return [l.split("SceneView:", 1)[1].strip() for l in lineas
            if "SceneView:" in l and patron in l][-n:]


def recargar() -> None:
    """Deja el motor en marcha sobre el plan que acaba de cambiar.

    Con el motor ya puesto no hay nada que hacer: el fondo vigila el fichero
    del plan y carga la escena nueva debajo de la que se ve, en Plasma
    (`Escenas.qml`) igual que en Hyprland. Antes aqui se salia a otro plugin y
    se volvia, y eso era el parpadeo de cada cambio. Solo hay que pedir algo si
    algun escritorio no lo tiene puesto; si en Hyprland no estaba, se arranca.

    Sin este desvio `shuffle` tomaba el "plasmashell no responde" por una
    escena rota y probaba otras cuatro, cinco planes escritos ---y cinco
    recargas--- por cada cambio.
    """
    if en_hyprland():
        hyprland_arrancar()
        return
    actuales = plugins_actuales()
    if not actuales or any(p != PLUGIN for p in actuales):
        poner_plugin(PLUGIN)


# ── biblioteca ──────────────────────────────────────────────────────────────

def _plano(s: str) -> str:
    """Sin acentos ni mayusculas, para buscar sin pelearse con el teclado."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


def _ejecutable(d: Path) -> bool:
    """Si este motor sabe poner ese wallpaper.

    Tres formas: una escena (`scene.pkg`), un video o, solo en Hyprland y con
    QtWebEngine instalado, una pagina web. Los de video estuvieron fuera hasta
    que el motor aprendio a decodificarlos ---lo necesitaba para las tres
    escenas cuya capa de fondo es un MP4 dentro del `.tex`, y desde ahi los 15 de la biblioteca salen casi
    gratis: su plan es un quad con la textura encima.
    """
    if (d / "scene.pkg").is_file() or werender.video_de(d) is not None:
        return True
    # Los web los pone solo el anfitrion de Hyprland (`hyprland/main.qml`,
    # con QtWebEngine); el plugin de Plasma todavia no.
    return werender.web_de(d) is not None and en_hyprland() and _hay_webengine()


def _hay_webengine() -> bool:
    return any((Path(p) / "QtWebEngine").is_dir()
               for p in ("/usr/lib/qt6/qml", "/usr/lib64/qt6/qml"))


def tipo_de(d: Path) -> str | None:
    """`scene`, `video` o `web`; None si eso no es un wallpaper.

    El tipo lo declara `project.json`, pero **hay que normalizarlo**: 24 de los
    148 de esta biblioteca lo escriben con mayuscula ---`Scene`, `Video`,
    `Web`--- y contarlos tal cual parte la biblioteca en seis tipos en vez de
    tres.

    El unico directorio sin `type` es `2336642563`, y no es que le falte: trae
    `category: Asset`. Es un paquete de materiales que otros wallpapers
    importan, no un fondo, y por eso devuelve None y no sale en la lista.
    """
    pj = d / "project.json"
    if not pj.is_file():
        return None
    try:
        proyecto = json.loads(pj.read_text(errors="replace"))
    except (ValueError, OSError):
        return None
    tipo = str(proyecto.get("type", "")).lower()
    return tipo or None


def inventario() -> list[tuple[str, str, str, bool]]:
    """`(id, titulo, tipo, si este motor lo pone)` de TODA la biblioteca.

    Se separa de `biblioteca()` porque son dos preguntas distintas y las dos
    hacen falta: `list` ensena el inventario entero ---un `web` que no aparece
    no se distingue de uno que no esta instalado--- mientras que `set` y
    `shuffle` solo pueden trabajar con lo que el motor sabe poner.
    """
    salida = []
    for d in sorted(wepaths.we_workshop().iterdir()):
        tipo = tipo_de(d)
        if tipo is None:
            continue
        try:
            proyecto = json.loads((d / "project.json").read_text(errors="replace"))
        except (ValueError, OSError):
            continue
        salida.append((d.name, str(proyecto.get("title", "?")),
                       tipo, _ejecutable(d)))
    return sorted(salida, key=lambda e: _plano(e[1]))


def biblioteca() -> list[tuple[str, str]]:
    """(id, titulo) de los wallpapers que este motor puede poner, por titulo."""
    return [(i, t) for i, t, _, listo in inventario() if listo]


def resolver(consulta: str) -> tuple[Path, str]:
    """Un id exacto, o el unico titulo que contenga el texto."""
    raiz = wepaths.we_workshop()
    if _ejecutable(raiz / consulta):
        titulos = dict(biblioteca())
        return raiz / consulta, titulos.get(consulta, consulta)

    q = _plano(consulta)
    hallados = [(i, t) for i, t in biblioteca() if q in _plano(t)]
    if not hallados:
        # Desde que `list` ensena tambien los que el motor no pone, "ninguno
        # coincide" seria una respuesta falsa para justo esos cuatro: el
        # usuario los acaba de ver en la lista.
        fuera = [(i, t, tipo) for i, t, tipo, listo in inventario()
                 if not listo and (q in _plano(t) or i == consulta)]
        if fuera:
            i, t, tipo = fuera[0]
            raise CtlError(f"{t!r} ({i}) es de tipo {tipo}, y este motor no "
                           f"pone los de ese tipo")
        raise CtlError(f"ningun wallpaper coincide con {consulta!r}; "
                       f"prueba `wectl list`")
    if len(hallados) > 1:
        lineas = "\n".join(f"    {i}  {t}" for i, t in hallados[:10])
        raise CtlError(f"{consulta!r} coincide con {len(hallados)}:\n{lineas}\n"
                       f"  afina el texto o usa el id")
    return raiz / hallados[0][0], hallados[0][1]


@contextlib.contextmanager
def en_exclusiva():
    """Un solo `wectl` cambiando el plan a la vez.

    La rotacion dispara `wectl shuffle` desde systemd cada pocos minutos, y
    nada impedia que cayera encima de un `wectl set` a mano. Los dos construian
    en el MISMO directorio, y el `rmtree` con que empieza uno se llevaba por
    delante los ficheros que el otro estaba escribiendo:

        FileNotFoundError: .../plugin/contents/scene.nueva/p000.frag

    Visto de verdad, con la rotacion cada 60 s. El escritorio no se rompio
    ---el plan viejo seguia en su sitio--- pero el cambio se perdio y el error
    no dice de que va.

    El cerrojo hace esperar al segundo en vez de dejarle pisar. Cuesta lo que
    tarde el primero ---hasta 20 s en el peor wallpaper de la biblioteca--- y a
    cambio los dos cambios ocurren enteros, uno detras de otro.
    """
    ESCENA.parent.mkdir(parents=True, exist_ok=True)
    with open(ESCENA.parent / ".plan.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


# `KScreen::Output::Rotation`, que `kscreen-doctor -j` da como entero: las que
# dejan el panel alto. Es una mascara de bits, no grados.
ROTACIONES_ALTAS = {2, 8, 32, 128}   # Left, Right, Flipped90, Flipped270


def resolucion_de_pantalla() -> tuple[int, int] | None:
    """Los pixeles del monitor mas grande, o None si no se puede saber.

    El plan se genera a la resolucion a la que se va a ver, no al lienzo que
    eligio el autor: el 72% de las escenas de una biblioteca tipica dibujan mas
    puntos de los que caben en el panel, con una razon mediana de 3,6x. Medido
    en la integrada, la escena mas pesada del corpus pasa de 99,9 ms por
    fotograma a 36,3.

    Se toma el monitor MAS GRANDE porque el plan es uno solo y lo comparten
    todas las pantallas: quedarse corto en la grande se veria; sobrar en la
    pequena solo cuesta lo que ya costaba.

    Si `kscreen-doctor` no esta o no se entiende, se devuelve None y el plan
    sale al lienzo del autor, que es como ha funcionado siempre.

    En Hyprland no hay `kscreen-doctor`: se pregunta a `hyprctl`.
    """
    return max(((w, h) for _, w, h in monitores()), key=lambda t: t[0] * t[1],
               default=None)


def preparar(ruta: Path, destino: Path | None = None,
             resolucion: tuple[int, int] | None = None) -> dict:
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

    `destino` es el plan compartido (`ESCENA`) o el de un monitor
    (`PANTALLAS/<monitor>`); el de un monitor se genera a SU resolucion.

    `ESCENA` se lee al llamar y no como valor por defecto: un `= ESCENA` en la
    firma se fija al importar, y `test_wectl`, que redirige `wectl.ESCENA` a
    un temporal, escribia sus planes de mentira en el plan REAL del escritorio
    (desde `513ca75`). En Hyprland el fondo los recargaba. Ver NOTAS, «El test
    que cambiaba el fondo».
    """
    if destino is None:
        destino = ESCENA
    if resolucion is None:
        resolucion = resolucion_de_pantalla()
    with en_exclusiva():
        # El directorio de construccion lleva un nombre unico, no `.nueva` a
        # secas: asi ni siquiera sin el cerrojo ---otro usuario, otra copia del
        # repo--- puede un proceso borrarle los ficheros a otro.
        destino.parent.mkdir(parents=True, exist_ok=True)
        nueva = Path(tempfile.mkdtemp(prefix=destino.name + ".nueva.",
                                      dir=destino.parent))
        vieja = destino.with_name(destino.name + ".vieja")
        shutil.rmtree(vieja, ignore_errors=True)
        try:
            stats = emit_plan(ruta, nueva, destino, resolucion=resolucion)
            if destino.exists():
                destino.rename(vieja)
            nueva.rename(destino)
        except BaseException:
            shutil.rmtree(nueva, ignore_errors=True)
            raise
        finally:
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
    # Un wallpaper concreto va a TODAS las pantallas, tambien en modo
    # independiente: se quitan los planes propios y cada monitor vuelve al
    # compartido. El modo no cambia; el siguiente `shuffle` vuelve a repartir.
    borrar_planes_propios()
    recargar()
    return stats


def borrar_planes_propios() -> None:
    with en_exclusiva():
        if PANTALLAS.is_dir():
            for d in PANTALLAS.iterdir():
                if d.is_dir():
                    shutil.rmtree(d, ignore_errors=True)


def planes_propios() -> dict[str, str]:
    """Monitor -> titulo del plan propio que tiene preparado."""
    salida = {}
    if PANTALLAS.is_dir():
        for d in sorted(PANTALLAS.iterdir()):
            titulo = _titulo_del_plan(d / "plan.txt")
            # Los `<monitor>.nueva.*` y `.vieja` son de un cambio a medias.
            if d.is_dir() and "." not in d.name and titulo:
                salida[d.name] = titulo
    return salida


def _titulo_del_plan(plan: Path) -> str | None:
    try:
        for linea in plan.read_text().splitlines():
            if linea.startswith("title "):
                return linea[6:]
    except OSError:
        return None
    return None


def plan_instalado() -> str | None:
    return _titulo_del_plan(ESCENA / "plan.txt")


# ── rotacion ────────────────────────────────────────────────────────────────
#
# El "cada x tiempo" no puede vivir dentro del plugin. El QML no genera planes:
# cambiar de wallpaper es traducir shaders y decodificar texturas, o sea Python,
# ~1 s por escena. Asi que la rotacion es un temporizador de systemd de USUARIO
# que llama a este mismo `wectl`, y el plugin ni se entera --- ve un plan nuevo y
# lo carga, igual que con `set`.

SUFIJOS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
# Por debajo de un minuto el temporizador no seria honesto (systemd agrupa los
# disparos). Un minuto ya es absurdo, pero es decision del usuario, no nuestra.
# Un minuto. El tope lo pone lo que tarda un cambio completo, medido sobre la
# biblioteca: la mediana esta en unos pocos segundos, pero preparar el plan de
# `2637739953` ---65 pases, 196 assets, 369 MB escritos--- cuesta 18,2 s, y el
# `wectl set` entero se va a ~20 s. Un minuto deja un factor 3 de margen sobre
# el peor caso y evita que un cambio empiece con el anterior a medias.
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
        raise CtlError(f"{texto!r} son {seg} s y el minimo es 1 min: preparar "
                       f"un wallpaper cuesta hasta 18 s en la biblioteca "
                       f"medida, y por debajo de eso los cambios se pisan")
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
    _systemctl("enable", f"{UNIDAD}.timer")
    # `enable --now` NO reinicia un temporizador que ya esta activo: se queda
    # corriendo con los parametros del fichero anterior, asi que cambiar la
    # cadencia no cambiaba nada hasta la siguiente sesion. Se vio en que el
    # proximo disparo se quedaba 18686 s en el pasado. Con `restart` el
    # temporizador se rearma con el fichero nuevo y desde ahora.
    _systemctl("restart", f"{UNIDAD}.timer")


def rotacion_apagar() -> None:
    _systemctl("disable", "--now", f"{UNIDAD}.timer", comprobar=False)
    for u in (f"{UNIDAD}.timer", f"{UNIDAD}.service"):
        (UNIDADES / u).unlink(missing_ok=True)
    _systemctl("daemon-reload", comprobar=False)


def _proximo_disparo() -> float | None:
    """Segundos que faltan para el siguiente cambio, o None si no se sabe.

    Se pregunta con `list-timers --output=json`, que da el instante en
    microsegundos desde la epoca. Antes se leia `NextElapseUSecMonotonic` por
    D-Bus y **estaba mal**: esa propiedad conserva el disparo con el que se armo
    el temporizador la primera vez tras el arranque, asi que con 5,9 h de uptime
    seguia diciendo "44 min", un valor 18686 s en el pasado. `list-timers` si
    recalcula, y es lo mismo que ensena `systemctl` a un humano.

    Cualquier tropiezo devuelve None y el estado se limita a no decir cuanto
    falta, que es mejor que inventarse una hora.
    """
    try:
        r = subprocess.run(["systemctl", "--user", "list-timers",
                            f"{UNIDAD}.timer", "--output=json", "--no-pager"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        filas = json.loads(r.stdout or "[]")
        if not filas or filas[0].get("next") in (None, 0):
            return None
        faltan = filas[0]["next"] / 1e6 - datetime.now().timestamp()
        # systemd usa un centinela enorme para "no hay proximo disparo".
        if faltan > 366 * 86400:
            return None
        return max(0.0, faltan)
    except (OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError):
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
    """Lista el inventario entero, con el tipo que declara cada uno.

    Ensena tambien los que este motor no pone ---los cuatro `web`--- porque un
    wallpaper que no aparece no se distingue de uno que no esta instalado, y
    esa es justo la duda que trae aqui a quien no encuentra el suyo. Cual pone
    y cual no lo dice el pie.
    """
    entradas = inventario()
    if args.texto:
        q = _plano(args.texto)
        entradas = [e for e in entradas if q in _plano(e[1])]
    if not entradas:
        print("sin coincidencias")
        return 1
    puesto = plan_instalado()
    for i, t, tipo, _ in entradas:
        marca = "*" if puesto and puesto.endswith(f"({i})") else " "
        print(f" {marca} {i:12} {tipo:6} {t}")

    cuenta = Counter(tipo for _, _, tipo, _ in entradas)
    desglose = ", ".join(f"{n} {k}" for k, n in sorted(cuenta.items()))
    plural = "wallpaper" if len(entradas) == 1 else "wallpapers"
    print(f"\n{len(entradas)} {plural}: {desglose}. "
          f"El * es el que hay preparado.")
    sueltos = sorted({tipo for _, _, tipo, listo in entradas if not listo})
    if sueltos:
        print(f"Este motor no pone los de tipo {' ni '.join(sueltos)}.")
    return 0


def cmd_set(args) -> int:
    ruta, titulo = resolver(args.wallpaper)
    print(f"preparando: {titulo}  ({ruta.name})")
    stats = aplicar(ruta)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"puesto en el escritorio: {titulo}")
    return 0


def cmd_shuffletime(args) -> int:
    """Cambia SOLO la cadencia de la rotacion, sin tocar el fondo de ahora.

    Existe porque hasta ahora la unica forma de ajustar el intervalo era
    `shuffle --cada`, que ademas cambia el wallpaper al momento: para pasar de
    30 a 10 minutos no habia manera de hacerlo sin llevarse por delante el que
    estabas mirando.

    Si la rotacion estaba parada, esto la enciende con esa cadencia y deja el
    fondo actual; el primer cambio llega dentro de un intervalo completo.
    """
    if args.parar:
        rotacion_apagar()
        print("rotacion parada; el fondo se queda como esta")
        return 0
    if not args.tiempo:
        raise CtlError("dime cada cuanto: `wectl shuffletime 10m`, "
                       "o `wectl shuffletime --parar`")
    segundos = _intervalo(args.tiempo)
    estaba = rotacion_estado()
    antes = estaba is not None and estaba[1]
    rotacion_encender(segundos)
    print(f"{'cadencia cambiada' if antes else 'rotacion activada'}: "
          f"un wallpaper al azar cada {_en_palabras(segundos)}")
    # El plazo lo cuenta systemd desde el ULTIMO cambio, no desde ahora
    # (`OnUnitActiveSec`), asi que al acortar la cadencia el siguiente puede
    # tocar ya. Se dice lo que va a pasar de verdad en vez de prometer un
    # intervalo entero.
    # systemd tarda un instante en calcular el disparo tras habilitar el
    # temporizador; sin esta espera corta la primera consulta sale vacia.
    faltan = _proximo_disparo()
    if faltan is None:
        time.sleep(0.6)
        faltan = _proximo_disparo()
    if faltan is None:
        print("el fondo de ahora se queda")
    elif faltan < 5:
        print("el fondo de ahora cambia enseguida: desde el ultimo cambio ya "
              "habia pasado mas de ese tiempo")
    else:
        print(f"el fondo de ahora se queda; el siguiente, en "
              f"{_en_palabras(faltan)}")
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
    if modo_pantallas() == "independiente":
        return _shuffle_por_pantalla(estado, entradas, raiz, titulos, segundos)
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


def _shuffle_por_pantalla(estado: dict, entradas: list[tuple[str, str]],
                          raiz: Path, titulos: dict[str, str],
                          segundos: int | None) -> int:
    """Un wallpaper distinto al azar para cada monitor.

    Salen de la misma bolsa, uno detras de otro, asi que en un mismo cambio dos
    pantallas no repiten (salvo que la biblioteca tenga menos wallpapers que
    monitores), y entre cambios sigue valiendo la regla de la bolsa: no se
    repite ninguno hasta que hayan salido todos. Cada plan se genera a la
    resolucion de SU monitor.
    """
    mons = monitores()
    if not mons:
        raise CtlError("la sesion no da ningun monitor; "
                       "¿responden hyprctl o kscreen-doctor?")
    puestos = {}
    fallos = []
    for nombre, w, h in mons:
        errores = []
        for _ in range(min(5, len(entradas))):
            elegido = _sacar_de_la_bolsa(estado, entradas)
            try:
                preparar(raiz / elegido, PANTALLAS / nombre, resolucion=(w, h))
            except Exception as e:
                errores.append(f"  {titulos.get(elegido, elegido)} ({elegido}): "
                               f"{type(e).__name__}: {e}")
                continue
            puestos[nombre] = elegido
            estado["puesto"] = elegido
            break
        if errores:
            print(f"no se pudieron preparar para {nombre}:", file=sys.stderr)
            print("\n".join(errores), file=sys.stderr)
        if nombre not in puestos:
            fallos.append(nombre)
    estado["puestos"] = puestos
    _guardar_estado(estado)
    if not puestos:
        raise CtlError("ninguna pantalla recibio wallpaper; mira los errores de arriba")
    recargar()
    for nombre, elegido in puestos.items():
        print(f"{nombre}: {titulos.get(elegido, elegido)}  ({elegido})")
    for nombre in fallos:
        print(f"{nombre}: sin cambio (ninguna escena probada se pudo preparar)")
    print(f"quedan {len(estado['bolsa'])} de {len(entradas)} antes de repetir")
    if segundos is not None:
        rotacion_encender(segundos)
        print(f"rotacion activada: otro por pantalla cada {_en_palabras(segundos)}")
    return 0


def cmd_pantallas(args) -> int:
    """Mismo wallpaper en todas las pantallas, o uno al azar en cada una."""
    actual = modo_pantallas()
    if args.modo is None:
        print(f"pantallas : {actual}")
        if actual == "independiente":
            propios = planes_propios()
            for nombre, _, _ in monitores():
                print(f"  {nombre}: {propios.get(nombre) or plan_instalado() or '(ninguno)'}"
                      + ("" if nombre in propios else "  (compartido)"))
        return 0
    modo = {"same": "mismo", "independent": "independiente"}.get(args.modo, args.modo)
    cfg = _config_hyprland(para_escribir=True)
    cfg["pantallas"] = modo
    _guardar_config_hyprland(cfg)
    if modo == "mismo":
        borrar_planes_propios()
    # `--planes` se pasa al arrancar: cambiar de modo es rearrancar el fondo.
    # Construir ANTES: el fondo nuevo carga el modulo QML que haya instalado, y
    # el modo independiente necesita el de esta version (`VigiaArchivo.existe`).
    construir()
    # Solo para pasar a `independiente`: sin planes propios, un fondo con
    # `--planes` ya es `mismo`, y rearrancarlo era un pantallazo.
    if fondo_hyprland() and modo == "independiente" and actual != "independiente":
        hyprland_parar()
        hyprland_arrancar()
    if modo == "independiente" and actual != "independiente":
        print("pantallas : independiente; repartiendo uno al azar por pantalla")
        return cmd_shuffle(argparse.Namespace(parar=False, cada=None))
    print(f"pantallas : {modo}"
          + (f" ({plan_instalado()} en todas)" if modo == "mismo" and plan_instalado()
             else ""))
    return 0


# Lo que acepta `wectl gpu`, a lo que guarda la clave `DedicatedGpu`. Los
# nombres de marca son los de un portatil Intel + NVIDIA; lo que se elige de
# verdad es "la de plasmashell" u "otra", sea cual sea (src/otragpu.h).
GPUS = {"dedicated": True, "dedicada": True, "nvidia": True,
        "integrated": False, "integrada": False, "intel": False}


def _config_gpu(valor: bool | None = None) -> list[str]:
    """Escribe `DedicatedGpu` en todos los escritorios, si se da, y la lee."""
    grupo = json.dumps(["Wallpaper", PLUGIN, "General"])
    escribe = (f" d[i].writeConfig('DedicatedGpu', {json.dumps(valor)});"
               if valor is not None else "")
    salida = _script(
        "var o = []; var d = desktops();"
        "for (var i = 0; i < d.length; i++) {"
        f" d[i].currentConfigGroup = {grupo};{escribe}"
        " o.push(String(d[i].readConfig('DedicatedGpu', true))); }"
        "print(o.join(' '));")
    return salida.split()


def _gpu_en_uso() -> str | None:
    """La ultima linea del motor que dice donde dibuja, si la hay."""
    # Solo plasmashell: el arnes QML escribe las mismas lineas en el registro.
    reg = subprocess.run(
        ["journalctl", "--user", "-b", "--no-pager", "-n", "1", "_COMM=plasmashell", "-g",
         "SceneView: (el fondo se dibuja en|configurado para dibujar|no hay otra GPU|Qt no dibuja)"],
        capture_output=True, text=True)
    lineas = [l for l in reg.stdout.splitlines() if "SceneView:" in l]
    return lineas[-1].split("SceneView:", 1)[1].strip() if lineas else None


def _cmd_gpu_hyprland(args) -> int:
    cfg = _config_hyprland(para_escribir=args.grafica is not None)
    if args.grafica is None:
        print(f"configurado   : {cfg.get('gpu', 'dedicada')}")
    else:
        cfg["gpu"] = "dedicada" if GPUS[args.grafica] else "integrada"
        _guardar_config_hyprland(cfg)
        # Aqui no hay propiedad que cambiar en caliente desde fuera: el fondo
        # es otro proceso. Se rearranca, que es menos de un segundo de negro.
        if fondo_hyprland():
            hyprland_parar()
            hyprland_arrancar()
            print(f"configurado   : {cfg['gpu']} (fondo reiniciado)")
            time.sleep(2.0)
        else:
            print(f"configurado   : {cfg['gpu']} (se aplica al arrancar)")
    lineas = _registro_hyprland("", 50)
    en_uso = next((l for l in reversed(lineas) if l.startswith((
        "el fondo se dibuja en", "configurado para dibujar", "no hay otra GPU",
        "Qt no dibuja"))), None)
    print(f"en uso        : {en_uso or '(sin datos del motor en el registro)'}")
    return 0


def cmd_gpu(args) -> int:
    if en_hyprland():
        return _cmd_gpu_hyprland(args)
    if args.grafica is None:
        valores = _config_gpu()
        pedida = "dedicada" if all(v != "false" for v in valores) else "integrada"
        print(f"configurado   : {pedida}")
    else:
        dedicada = GPUS[args.grafica]
        _config_gpu(dedicada)
        # El motor la cambia en el siguiente fotograma, sin recargar: el
        # SceneView pide uno al cambiar la propiedad, aunque este en pausa.
        print(f"configurado   : {'dedicada' if dedicada else 'integrada'}"
              " (se aplica en el siguiente fotograma)")
        time.sleep(1.0)
    en_uso = _gpu_en_uso()
    print(f"en uso        : {en_uso or '(sin datos del motor en el registro)'}")
    return 0


def cmd_start(args) -> int:
    if plan_instalado() is None:
        raise CtlError("no hay ningun plan preparado; usa `wectl set <wallpaper>`")
    if en_hyprland():
        andaba = fondo_hyprland()
        hyprland_arrancar()
        print(f"motor {'ya estaba ' if andaba else ''}activo: {plan_instalado()}")
        return 0
    poner_plugin(PLUGIN)
    print(f"motor activo: {plan_instalado()}")
    return 0


def cmd_stop(args) -> int:
    if en_hyprland():
        hyprland_parar()
        print("motor parado; el fondo queda en lo que Hyprland pinte debajo")
        return 0
    poner_plugin(PLUGIN_IMAGEN)
    print("motor parado; el escritorio vuelve al fondo de Plasma")
    return 0


def cmd_status(args) -> int:
    compartido = modo_pantallas() == "independiente"
    print(f"{'plan compartido' if compartido else 'plan preparado '}: "
          f"{plan_instalado() or '(ninguno)'}"
          + ("  (lo usa la pantalla sin plan propio)" if compartido else ""))
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
    if en_hyprland():
        andando = fondo_hyprland()
        print(f"escritorio     : Hyprland (unidad {UNIDAD_HYPRLAND})")
        print(f"estado         : {'EN MARCHA' if andando else 'parado'}")
        cfg = _config_hyprland()
        print(f"pantallas      : {modo_pantallas()}")
        for nombre, titulo in planes_propios().items():
            print(f"  {nombre}: {titulo}")
        opciones = _opciones_hyprland(cfg)
        print(f"gpu            : {cfg.get('gpu', 'dedicada')}"
              + (f"; opciones {' '.join(opciones)}" if opciones else ""))
        if andando:
            for linea in _registro_hyprland("", 2):
                print("  " + linea)
        return 0
    try:
        activos = plugins_actuales()
    except CtlError as e:
        print(f"escritorio     : {e}")
        return 1
    nuestros = sum(1 for p in activos if p == PLUGIN)
    print(f"escritorios    : {nuestros} de {len(activos)} con el motor")
    print(f"estado         : {'EN MARCHA' if nuestros else 'parado'}")
    print(f"pantallas      : {modo_pantallas()}")
    for nombre, titulo in planes_propios().items():
        print(f"  {nombre}: {titulo}")
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
    s.add_argument("--every", "--cada", metavar="TIEMPO", dest="cada",
                   help="ademas, repetirlo solo cada TIEMPO: 30m, 2h, 90s")
    s.add_argument("--parar", action="store_true",
                   help="para la rotacion automatica")
    s.set_defaults(fn=cmd_shuffle)

    s = sub.add_parser("shuffletime",
                       help="cambia cada cuanto rota, sin tocar el fondo")
    s.add_argument("tiempo", nargs="?", metavar="TIEMPO",
                   help="30m, 2h, 90s, 1d; un numero suelto son minutos")
    s.add_argument("--parar", action="store_true", help="para la rotacion")
    s.set_defaults(fn=cmd_shuffletime)

    s = sub.add_parser("gpu", help="en que grafica se dibuja el fondo")
    s.add_argument("grafica", nargs="?", choices=sorted(GPUS), metavar="GRAFICA",
                   help="dedicated (nvidia) o integrated (intel); sin nada, "
                        "dice cual esta configurada y cual se usa")
    s.set_defaults(fn=cmd_gpu)

    s = sub.add_parser("pantallas",
                       help="el mismo wallpaper en todas las pantallas o uno "
                            "al azar en cada una (Hyprland)")
    s.add_argument("modo", nargs="?",
                   choices=["mismo", "independiente", "same", "independent"],
                   help="sin nada, dice el modo y que tiene cada pantalla")
    s.set_defaults(fn=cmd_pantallas)

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
