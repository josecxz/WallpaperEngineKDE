#!/usr/bin/env python3
"""Regresion de LUZ: renderiza cada escena y mide cuanta sale.

Por que existe: el resto de la bateria comprueba que el plan se genere y que
los shaders compilen, y con eso una escena puede quedarse **negra sin que nada
proteste**. Paso de verdad, y no una vez: `3077334064` se preparaba sin una
sola queja ---11 pases, cero shaders perdidos, cero texturas ausentes--- y
salia a 18 de luminancia media sobre 255; con ella, `2810252468` a 11,3 y
`3053927686` a 4,3. Las tres llevaban meses asi. Un `normalize(0,0)` en el
parallax por profundidad las apagaba, y ninguna herramienta lo decia.

Lo que mide, por escena:

  * `media`  ---luminancia media del fotograma, que es lo que separa "negra"
    de "oscura pero viva".
  * `p99`    ---el percentil 99. Una escena legitimamente oscura tiene brillos;
    una rota es plana. Sin este dato, un cielo nocturno y un fallo se parecen.
  * `oscuro` ---fraccion de pixeles por debajo de 8. Con la media sola, un
    destello en una esquina disimula un lienzo apagado.

Uso:
    cc -O2 -o /tmp/glexec tools/glexec.c -lEGL -lGL
    python3 tools/test_luminancia.py /tmp/glexec --guardar luz.json
    python3 tools/test_luminancia.py /tmp/glexec --referencia luz.json

Sin `--referencia` avisa de las escenas apagadas y deja la tabla. Con ella,
ademas, marca las que han PERDIDO luz respecto a la ultima medida, que es como
se caza una regresion antes de que llegue al escritorio. Con `--desde` reanaliza
una medida ya guardada sin volver a renderizar, para afinar umbrales.

La referencia no se guarda en el repositorio: depende de que wallpapers tenga
cada uno. Se genera en local y se compara contra si misma.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
import werender

# El criterio NO es un umbral absoluto, y averiguarlo costo dos falsos
# positivos: `Dark Queen [4K]` mide 4.23 de media y `Samurai - Cyberpunk 2077`
# 5.39, o sea por debajo de tres de las cuatro escenas rotas conocidas ---y las
# dos estan perfectas: son obras deliberadamente negras, con una corona o un
# demonio encendidos sobre un fondo en penumbra. Cualquier umbral absoluto que
# cace las rotas se lleva por delante el arte oscuro.
#
# Lo que si separa es comparar contra el PREVIEW del autor, que es un fotograma
# de la escena tal como debe verse. La razon `nuestro / preview` deja los dos
# grupos sin solapamiento:
#
#     2968771936  0.00 / 144.63 = 0.00   rota
#     3577990983  1.95 /  68.07 = 0.03   rota
#     1518454472  3.88 /  70.09 = 0.06   rota
#     3624053922  4.07 /  70.67 = 0.06   rota
#     3459506773  4.23 /  11.32 = 0.37   arte oscuro, correcta
#     2311315748  5.39 /  21.29 = 0.25   arte oscuro, correcta
#
# El preview es material del autor: a veces es un recorte o arte promocional en
# vez de una captura fiel, asi que la razon es aproximada y el umbral, generoso.
RAZON_APAGADA = 0.15
# Por debajo de esto el preview es tan oscuro que la razon no dice nada, y se
# cae al criterio absoluto.
PREVIEW_MINIMO = 5.0
APAGADA = 8.0
SOSPECHOSA_MEDIA = 25.0
SOSPECHOSA_P99 = 120.0
# Cuanta luz puede perder una escena antes de considerarlo regresion.
CAIDA = 0.25


def preview(escena: Path) -> float | None:
    """Luminancia media del preview del autor, o None si no hay o no se lee.

    Los `.gif` traen varios fotogramas; con el primero basta para saber si la
    escena deberia tener luz.
    """
    for p in sorted(escena.glob("preview*")):
        try:
            im = Image.open(p)
            try:
                im.seek(0)
            except Exception:                                # noqa: BLE001
                pass
            return float(np.asarray(im.convert("RGB"), dtype=np.float32).mean())
        except Exception:                                    # noqa: BLE001
            continue
    return None


def mide(png: Path) -> dict:
    a = np.asarray(Image.open(png).convert("RGB"), dtype=np.float32).mean(axis=2)
    return {"media": round(float(a.mean()), 2),
            "p99": round(float(np.percentile(a, 99)), 2),
            "oscuro": round(float((a < 8).mean()), 4)}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    glexec = Path(sys.argv[1])
    args = sys.argv[2:]

    def opcion(nombre, por_defecto=None):
        return args[args.index(nombre) + 1] if nombre in args else por_defecto

    limite = int(opcion("--limit", 0) or 0)
    # Reanalizar una medida guardada, sin renderizar: afinar los umbrales no
    # deberia costar los seis minutos que cuesta pasar el corpus.
    desde = opcion("--desde")
    fotogramas = int(opcion("--frames", 6))
    referencia = opcion("--referencia")
    guardar = opcion("--guardar")

    base = json.loads(Path(referencia).read_text()) if referencia else {}

    if desde:
        return informe(json.loads(Path(desde).read_text()), base, [], 0.0,
                       guardar=None)

    escenas = sorted(d for d in wepaths.we_workshop().iterdir()
                     if (d / "scene.pkg").is_file())
    if limite:
        escenas = escenas[:limite]
    print(f"escenas: {len(escenas)}   fotogramas: {fotogramas}   "
          f"apagada por debajo de {APAGADA} de media")

    tmp = Path(tempfile.mkdtemp(prefix="luz-"))
    res, fallos, t0 = {}, [], time.time()
    try:
        for n, esc in enumerate(escenas, 1):
            png = tmp / "f.png"
            r = None
            try:
                r = werender.Renderer(esc, glexec, 4.0)
                r.render(png, frames=fotogramas)
                v = mide(png)
                ref = preview(esc)
                if ref is not None:
                    v["preview"] = round(ref, 2)
                    if ref >= PREVIEW_MINIMO:
                        v["razon"] = round(v["media"] / ref, 3)
                res[esc.name] = v
            except BaseException as e:                       # noqa: BLE001
                res[esc.name] = {"error": f"{type(e).__name__}: {e}"}
                fallos.append(f"{esc.name}: no renderiza ({type(e).__name__})")
            finally:
                # `render()` no borra su temporal ---lo hace el CLI de
                # `werender`--- y aqui son 125 escenas: sin esto se llenan
                # cientos de MB de /tmp, que ademas es un tmpfs.
                if r is not None:
                    shutil.rmtree(r.tmp, ignore_errors=True)
                png.unlink(missing_ok=True)
            if n % 20 == 0:
                print(f"  ...{n}/{len(escenas)}", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return informe(res, base, fallos, time.time() - t0, guardar)


def informe(res, base, fallos, segundos, guardar) -> int:
    def apagada(v):
        """Rota = mucho mas oscura que su preview; sin preview, casi negra."""
        if "media" not in v:
            return False
        if "razon" in v:
            return v["razon"] < RAZON_APAGADA
        return v["media"] < APAGADA

    apagadas = [(k, v) for k, v in res.items() if apagada(v)]
    sospechosas = [(k, v) for k, v in res.items()
                   if "media" in v and APAGADA <= v["media"] < SOSPECHOSA_MEDIA
                   and v["p99"] < SOSPECHOSA_P99]
    caidas = []
    for k, v in res.items():
        b = base.get(k)
        if not b or "media" not in b or "media" not in v:
            continue
        if b["media"] > 1 and v["media"] < b["media"] * (1 - CAIDA):
            caidas.append((k, b["media"], v["media"]))

    vivas = sorted((v["media"], k) for k, v in res.items() if "media" in v)
    if segundos:
        print(f"\nrenderizadas {len(vivas)}/{len(res)} en {segundos:.0f}s")
    print("\n── las 10 mas oscuras ──")
    for media, k in vivas[:10]:
        v = res[k]
        marca = ("  <-- APAGADA" if apagada(v) else
                 "  <-- sospechosa" if v["p99"] < SOSPECHOSA_P99
                 and media < SOSPECHOSA_MEDIA else "")
        razon = f"{v['razon']:5.2f}" if "razon" in v else "    -"
        print(f"  {k:12} media {media:6.2f}  p99 {v['p99']:6.2f}  "
              f"negro {v['oscuro'] * 100:5.1f}%  vs preview {razon}{marca}")

    if caidas:
        print("\n── han perdido luz respecto a la referencia ──")
        for k, antes, ahora in caidas:
            print(f"  {k:12} {antes:6.2f} -> {ahora:6.2f}")

    if guardar:
        Path(guardar).write_text(json.dumps(res, indent=1, sort_keys=True))
        print(f"\nreferencia guardada en {guardar}")

    print(f"\napagadas (menos del {RAZON_APAGADA:.0%} de su preview): "
          f"{len(apagadas)}   "
          f"sospechosas: {len(sospechosas)}   "
          f"regresiones: {len(caidas)}   no renderizan: {len(fallos)}")
    for f in fallos[:10]:
        print("  ", f)
    malo = bool(apagadas or caidas or fallos)
    print("\n" + ("FALLO" if malo else "OK"))
    return 1 if malo else 0


if __name__ == "__main__":
    sys.exit(main())
