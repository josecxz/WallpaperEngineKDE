#!/usr/bin/env python3
"""Valida la rotacion de wallpapers de `wectl` sin tocar el escritorio.

Las tres piezas que pueden fallar en silencio, y por que cada una:

  - **la bolsa**: si repite, el usuario ve dos veces la misma escena mientras
    otras no salen nunca, y eso solo se nota tras muchas vueltas
  - **el cambio de plan**: se hace con un rename para que un fallo a medias no
    deje el escritorio sin fondo; hay que comprobar los DOS caminos, el que sale
    bien y el que revienta
  - **el intervalo**: `30m` y `2h` tienen que dar lo que parece

De `aplicar` solo se prueba el orden de sus pasos ---construir, cambiar el plan,
recargar---, que es lo que decide si un fallo deja el escritorio coherente. Lo
que toca plasmashell de verdad es `wectl shuffle` a mano, y esta comprobado que
un fallo ahi se ve al momento en `wectl status`.

Uso:  python3 tools/test_wectl.py
"""

from __future__ import annotations

import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wectl


def prueba_intervalo(fallos: list[str]) -> None:
    print("── intervalos ──")
    for texto, esperado in (("30m", 1800), ("2h", 7200), ("90s", 90),
                            ("1d", 86400), ("45", 2700), ("0.5h", 1800)):
        try:
            visto = wectl._intervalo(texto)
        except wectl.CtlError as e:
            fallos.append(f"intervalo {texto!r} rechazado: {e}")
            continue
        marca = "ok" if visto == esperado else "MAL"
        if visto != esperado:
            fallos.append(f"intervalo {texto!r} da {visto}, esperaba {esperado}")
        print(f"  {texto:>5} -> {visto:>6} s   {marca}")

    for malo in ("hola", "", "10s", "-5m"):
        try:
            wectl._intervalo(malo)
            fallos.append(f"intervalo {malo!r} deberia rechazarse")
            print(f"  {malo!r:>7} -> ACEPTADO (mal)")
        except wectl.CtlError:
            print(f"  {malo!r:>7} -> rechazado   ok")


def prueba_bolsa(fallos: list[str]) -> None:
    """Cuatro vueltas completas sobre una biblioteca de 125, como la real."""
    print("\n── bolsa ──")
    random.seed(20260814)
    entradas = [(f"id{i:03}", f"escena {i}") for i in range(125)]
    estado: dict = {}
    salidas = []
    for _ in range(len(entradas) * 4):
        elegido = wectl._sacar_de_la_bolsa(estado, entradas)
        estado["puesto"] = elegido
        salidas.append(elegido)

    for v in range(4):
        vuelta = salidas[v * 125:(v + 1) * 125]
        if len(set(vuelta)) != 125:
            fallos.append(f"la vuelta {v} repite: "
                          f"{125 - len(set(vuelta))} escenas de mas")
    seguidas = sum(1 for i in range(1, len(salidas))
                   if salidas[i] == salidas[i - 1])
    if seguidas:
        fallos.append(f"{seguidas} veces la misma escena dos veces seguidas")
    print(f"  4 vueltas de 125: {len(set(salidas))} escenas distintas, "
          f"{seguidas} repeticiones seguidas")

    # La biblioteca cambia debajo: un id que ya no esta se cae de la bolsa en
    # vez de intentar prepararse y fallar.
    estado = {"bolsa": ["id001", "ya-no-existe"], "puesto": "id000"}
    elegido = wectl._sacar_de_la_bolsa(estado, entradas)
    if elegido not in dict(entradas):
        fallos.append(f"la bolsa devolvio {elegido!r}, que no esta en la "
                      f"biblioteca")
    print(f"  con un id borrado en la bolsa -> {elegido}   ok")

    # Bolsa vacia y biblioteca de uno: no hay donde elegir, pero no puede
    # caerse ni devolver None.
    estado = {}
    unico = wectl._sacar_de_la_bolsa(estado, [("solo", "la unica")])
    if unico != "solo":
        fallos.append(f"con una sola escena devolvio {unico!r}")
    print(f"  con una sola escena -> {unico}   ok")


def prueba_cambio_de_plan(fallos: list[str]) -> None:
    """El plan se cambia entero o no se cambia."""
    print("\n── cambio de plan ──")
    tmp = Path(tempfile.mkdtemp(prefix="wectl-"))
    escena_real, emit_real = wectl.ESCENA, wectl.emit_plan
    try:
        wectl.ESCENA = tmp / "scene"
        wectl.ESCENA.mkdir(parents=True)
        (wectl.ESCENA / "plan.txt").write_text("title VIEJO\n")
        # Sobrante de un wallpaper con mas pases que el que viene.
        (wectl.ESCENA / "p099.frag").write_text("sobra\n")

        def emit_ok(ruta, out, ruta_final=None):
            out.mkdir(parents=True, exist_ok=True)
            destino = ruta_final if ruta_final is not None else out
            (out / "plan.txt").write_text(
                f"title {ruta.name}\ntex {destino / 'tex000.rgba'}\n")
            (out / "tex000.rgba").write_bytes(b"\0")
            return {"pases": 1}

        wectl.emit_plan = emit_ok
        wectl.preparar(Path("/tmp/NUEVO"))
        quedan = sorted(p.name for p in wectl.ESCENA.iterdir())
        plan = (wectl.ESCENA / "plan.txt").read_text()
        if "p099.frag" in quedan:
            fallos.append("el sobrante del wallpaper anterior sigue ahi")
        if "VIEJO" in plan:
            fallos.append("el plan no se cambio")
        # La razon de pasar `ruta_final`: el plan tiene que nombrar donde ACABAN
        # los assets, no el directorio de trabajo.
        if ".nueva" in plan:
            fallos.append("el plan apunta al directorio de trabajo, "
                          "no al definitivo")
        print(f"  tras cambiar: {quedan}")
        print(f"  el plan nombra el directorio definitivo: "
              f"{'no' if '.nueva' in plan else 'si'}")

        def emit_revienta(ruta, out, ruta_final=None):
            out.mkdir(parents=True, exist_ok=True)
            (out / "plan.txt").write_text("a medias\n")
            raise RuntimeError("escena rota")

        wectl.emit_plan = emit_revienta
        try:
            wectl.preparar(Path("/tmp/ROTO"))
            fallos.append("una escena rota no levanto el error")
        except RuntimeError:
            pass
        plan = (wectl.ESCENA / "plan.txt").read_text()
        if "NUEVO" not in plan:
            fallos.append("tras un fallo, el escritorio se quedo sin su plan")
        # `.plan.lock` es el cerrojo que serializa dos `wectl` a la vez; se
        # queda a proposito, vacio y de 0 bytes. Lo que no puede quedar es un
        # directorio de construccion a medias.
        hermanos = sorted(p.name for p in tmp.iterdir() if p.name != ".plan.lock")
        if hermanos != ["scene"]:
            fallos.append(f"quedaron directorios sueltos: {hermanos}")
        print(f"  tras un fallo: plan intacto, hermanos {hermanos}   ok")

        # Dos a la vez. La rotacion dispara `wectl shuffle` desde systemd y
        # puede caer encima de un `set` a mano: antes los dos construian en el
        # mismo `.nueva` y el que empezaba segundo le borraba los ficheros al
        # primero, que moria con FileNotFoundError. Pasa de verdad, con la
        # rotacion cada 60 s.
        import threading
        errores, a_la_vez, dentro = [], [], threading.Lock()

        def emit_lento(ruta, out, ruta_final=None):
            out.mkdir(parents=True, exist_ok=True)
            with dentro:
                a_la_vez.append(len(a_la_vez) + 1)
                simultaneos = sum(1 for _ in a_la_vez)
            time.sleep(0.25)          # ventana de sobra para pisarse
            (out / "plan.txt").write_text(f"title {ruta.name}\n")
            (out / "tex000.rgba").write_bytes(b"\0")
            with dentro:
                a_la_vez.pop()
            return {"pases": 1, "simultaneos": simultaneos}

        wectl.emit_plan = emit_lento

        def corre(nombre):
            try:
                wectl.preparar(Path(f"/tmp/{nombre}"))
            except BaseException as e:                       # noqa: BLE001
                errores.append(f"{nombre}: {type(e).__name__}: {e}")

        hilos = [threading.Thread(target=corre, args=(n,)) for n in ("UNO", "DOS")]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        if errores:
            fallos.append(f"dos cambios a la vez rompieron: {errores}")
        plan = (wectl.ESCENA / "plan.txt").read_text()
        if "UNO" not in plan and "DOS" not in plan:
            fallos.append(f"tras dos cambios a la vez el plan no es de ninguno: {plan!r}")
        hermanos = sorted(p.name for p in tmp.iterdir() if p.name != ".plan.lock")
        if hermanos != ["scene"]:
            fallos.append(f"dos a la vez dejaron restos: {hermanos}")
        print(f"  dos cambios a la vez: los dos enteros, gana uno "
              f"({plan.split()[1] if len(plan.split()) > 1 else '?'}), sin restos   ok")
    finally:
        wectl.ESCENA, wectl.emit_plan = escena_real, emit_real
        shutil.rmtree(tmp, ignore_errors=True)


def prueba_construir(fallos: list[str]) -> None:
    """Un `make` roto no puede acabar en plan nuevo sobre el motor viejo.

    Es el unico camino de `aplicar` que se puede probar sin plasmashell: se
    comprueba el ORDEN de los tres pasos, que es donde estaba el fallo ---se
    construia despues de cambiar el plan y sin mirar el resultado---.
    """
    print("\n── construir antes de cambiar el plan ──")
    real_sub, real_prep, real_rec = wectl.subprocess, wectl.preparar, \
        wectl.recargar
    hechos: list[str] = []

    class Make:
        """Ocupa el sitio de `subprocess` dentro de wectl: solo usa run y PIPE."""
        PIPE = real_sub.PIPE

        def __init__(self, codigo: int) -> None:
            self.codigo = codigo

        def run(self, cmd, **kw):
            hechos.append("make")
            return real_sub.CompletedProcess(
                cmd, self.codigo, stderr="[el aviso del compilador iria aqui]\n")

    def prep(ruta):
        hechos.append("preparar")
        return {"pases": 1}

    try:
        wectl.preparar = prep
        wectl.recargar = lambda: hechos.append("recargar")

        wectl.subprocess = Make(2)
        hechos.clear()
        try:
            wectl.aplicar(Path("/tmp/DA-IGUAL"))
            fallos.append("un make roto no levanto el error")
        except wectl.CtlError:
            pass
        if "preparar" in hechos or "recargar" in hechos:
            fallos.append(f"con el make roto se siguio adelante: {hechos}")
        print(f"  make roto  -> {hechos}   (ni plan nuevo ni recarga)")

        wectl.subprocess = Make(0)
        hechos.clear()
        wectl.aplicar(Path("/tmp/DA-IGUAL"))
        if hechos != ["make", "preparar", "recargar"]:
            fallos.append(f"el camino bueno hace {hechos}, esperaba "
                          f"['make', 'preparar', 'recargar']")
        print(f"  make bueno -> {hechos}   ok")
    finally:
        wectl.subprocess, wectl.preparar, wectl.recargar = \
            real_sub, real_prep, real_rec


def prueba_unidades(fallos: list[str]) -> None:
    """Las unidades de systemd se escriben donde toca y con lo que toca."""
    print("\n── unidades de systemd ──")
    tmp = Path(tempfile.mkdtemp(prefix="wectl-unidades-"))
    unidades_real, systemctl_real = wectl.UNIDADES, wectl._systemctl
    ordenes: list[tuple] = []
    try:
        wectl.UNIDADES = tmp
        wectl._systemctl = lambda *a, **k: ordenes.append(a) or ""
        wectl.rotacion_encender(1800)
        servicio = (tmp / f"{wectl.UNIDAD}.service").read_text()
        timer = (tmp / f"{wectl.UNIDAD}.timer").read_text()
        if "OnUnitActiveSec=1800" not in timer:
            fallos.append("el temporizador no lleva el intervalo pedido")
        if "shuffle" not in servicio or str(Path(wectl.__file__).resolve()) \
                not in servicio:
            fallos.append("el servicio no llama a este wectl")
        if not any("enable" in o for o in ordenes):
            fallos.append("no se arranco el temporizador")
        print(f"  systemctl: {[' '.join(o) for o in ordenes]}")

        wectl.rotacion_apagar()
        if list(tmp.iterdir()):
            fallos.append("apagar la rotacion dejo unidades sueltas")
        print(f"  tras apagar quedan {len(list(tmp.iterdir()))} unidades   ok")
    finally:
        wectl.UNIDADES, wectl._systemctl = unidades_real, systemctl_real
        shutil.rmtree(tmp, ignore_errors=True)


def prueba_shuffletime(fallos: list[str]) -> None:
    """`shuffletime` ajusta la cadencia sin tocar el plan ni el escritorio."""
    print("\n── cambiar la cadencia ──")
    tmp = Path(tempfile.mkdtemp(prefix="wectl-shuffletime-"))
    reales = (wectl.UNIDADES, wectl._systemctl, wectl._proximo_disparo,
              wectl.preparar, wectl.recargar, wectl.construir)
    tocado: list[str] = []
    try:
        wectl.UNIDADES = tmp
        wectl._systemctl = lambda *a, **k: ""
        wectl._proximo_disparo = lambda: 600.0
        for nombre in ("preparar", "recargar", "construir"):
            setattr(wectl, nombre, lambda *a, _n=nombre, **k: tocado.append(_n))

        class Args:
            tiempo, parar = "10m", False
        wectl.cmd_shuffletime(Args())
        timer = (tmp / f"{wectl.UNIDAD}.timer").read_text()
        if "OnUnitActiveSec=600" not in timer:
            fallos.append("la cadencia no llego al temporizador")
        if tocado:
            fallos.append(f"cambiar la cadencia toco el escritorio: {tocado}")
        print(f"  `shuffletime 10m` -> temporizador a 600 s, sin tocar el fondo   ok")

        class Malo:
            tiempo, parar = "30s", False
        try:
            wectl.cmd_shuffletime(Malo())
            fallos.append("acepto 30s, por debajo del minimo")
        except wectl.CtlError:
            print(f"  `shuffletime 30s` rechazado (minimo {wectl.INTERVALO_MINIMO} s)   ok")
    finally:
        (wectl.UNIDADES, wectl._systemctl, wectl._proximo_disparo,
         wectl.preparar, wectl.recargar, wectl.construir) = reales
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    fallos: list[str] = []
    prueba_intervalo(fallos)
    prueba_bolsa(fallos)
    prueba_cambio_de_plan(fallos)
    prueba_construir(fallos)
    prueba_unidades(fallos)
    prueba_shuffletime(fallos)

    if fallos:
        print("\n── fallos ──")
        for f in fallos:
            print(f"  {f}")
    print("\n" + ("OK" if not fallos else f"FALLO: {len(fallos)}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
