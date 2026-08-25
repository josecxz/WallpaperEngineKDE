#!/usr/bin/env python3
"""Regresion end-to-end del grafo de escena.

Tres criterios, los tres objetivos:

  1. Toda referencia de toda escena tiene que resolverse: modelos,
     materiales, shaders, texturas y efectos. Una sola sin resolver es un
     agujero en el modelo del grafo.
  2. Las variantes de shader que las escenas piden de verdad tienen que
     compilar. Esto es mas exigente que test_weshader.py, que compila con
     los combos por defecto: aqui se usan los combos reales de cada pase,
     que es lo que se subira a la GPU.
  3. Y el PAR tiene que enlazar. Compilar no basta: lo que tiene que casar
     entre el vertice y el fragmento es la interfaz ---el tipo y la longitud
     de cada varying, y el tipo de cada uniform con el mismo nombre--- y eso
     no se mira hasta que se crea el programa. Con las dos etapas compilando
     al 100 %, 14 pares de 297 no enlazaban y el motor se quedaba sin esos
     pases sin decir nada.

Uso:
    cc -O2 -o /tmp/glslcheck tools/glslcheck.c -lEGL
    python3 tools/test_wescene.py /tmp/glslcheck [--limit N]
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
import weshader
import wescene
from wescene import AssetResolver, SceneError, load_scene

MESA_ENV = {"__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json"}


def main() -> int:
    check = Path(sys.argv[1])
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    we = wepaths.we_assets()
    dirs = sorted(d for d in wepaths.we_workshop().iterdir()
                  if (d / "scene.pkg").is_file())
    if limit:
        dirs = dirs[:limit]

    tmp = Path(tempfile.mkdtemp(prefix="wescene-"))
    stats = Counter()
    unresolved = Counter()
    missing_tex = Counter()
    variants: list[Path] = []
    pares: list[list[Path]] = []
    seen_variant: set[str] = set()

    for d in dirs:
        try:
            res = AssetResolver.for_wallpaper(d, we)
            scene = load_scene(res)
        except SceneError as e:
            stats["escena_err"] += 1
            unresolved[f"scene.json: {e}"[:80]] += 1
            continue
        except Exception as e:
            stats["escena_err"] += 1
            unresolved[f"{type(e).__name__}: {e}"[:80]] += 1
            continue

        stats["escenas"] += 1
        stats["objetos"] += len(scene.objects)
        for o in scene.objects:
            stats[f"obj_{o.kind}"] += 1
        stats["pases"] += len(scene.render_passes)
        for u in scene.unresolved:
            unresolved[u.split(": ", 1)[-1][:80]] += 1
            stats["referencias_sin_resolver"] += 1

        # Las texturas nombradas por los materiales tienen que existir.
        for p in scene.render_passes:
            for t in p.textures:
                if not t or t.startswith("_rt_"):
                    continue
                stats["texturas_referenciadas"] += 1
                if not res.exists(wescene.texture_path(t)):
                    stats["texturas_sin_resolver"] += 1
                    missing_tex[t] += 1

        # Traducir cada variante con SUS combos reales.
        sresolver = weshader.Resolver(
            overlay=res.entries, roots=[d, we, we / "shaders"])
        for p in scene.render_passes:
            if p.command:
                stats["pases_copy"] += 1
                continue
            key = f"{p.shader}|{sorted(p.combos.items())}"
            if key in seen_variant:
                continue
            seen_variant.add(key)
            # Las dos etapas se traducen con lo que el PAR acordo, igual que en
            # `werender`: traducirlas por su cuenta es justo lo que producia los
            # pares que compilan y no enlazan.
            combos_v, combos_f = weshader.combos_de_pase(
                p.vert, p.frag, sresolver, p.combos)
            varyings = weshader.varyings_de_pase(
                p.vert, p.frag, sresolver, combos_v, combos_f)
            par: list[Path] = []
            for stage, src, cmb in (("vert", p.vert, combos_v),
                                    ("frag", p.frag, combos_f)):
                try:
                    out = weshader.translate(src, stage, sresolver,
                                             combos=cmb, varyings=varyings)
                except Exception as e:
                    stats["traduccion_err"] += 1
                    unresolved[f"translate {p.shader}.{stage}: {e}"[:80]] += 1
                    continue
                name = f"{len(variants):05d}_{p.shader.replace('/', '__')}.{stage}"
                dest = tmp / name
                dest.write_text(out)
                variants.append(dest)
                par.append(dest)
            if len(par) == 2:
                pares.append(par)

    print("── resolucion del grafo ──")
    for k in ("escenas", "escena_err", "objetos", "obj_image", "obj_particle",
              "obj_sound", "obj_light", "obj_model", "obj_text", "obj_unknown",
              "pases", "pases_copy", "referencias_sin_resolver",
              "texturas_referenciadas", "texturas_sin_resolver", "traduccion_err"):
        if stats[k]:
            print(f"  {k:<26} {stats[k]}")
    if unresolved:
        print("\n  referencias sin resolver:")
        for k, v in unresolved.most_common(10):
            print(f"    {v:>5} x {k}")
    if missing_tex:
        print("\n  texturas sin resolver:")
        for k, v in missing_tex.most_common(6):
            print(f"    {v:>5} x {k}")

    print(f"\n── compilacion de {len(variants)} variantes reales ──")
    for label, env_extra in (("Mesa (Intel)", MESA_ENV), ("NVIDIA", {})):
        env = {**os.environ, **env_extra}
        ok = 0
        for i in range(0, len(variants), 150):
            chunk = variants[i:i + 150]
            p = subprocess.run([str(check), "--desktop", *map(str, chunk)],
                               capture_output=True, text=True, env=env)
            ok += sum(1 for l in p.stdout.splitlines() if l.startswith("OK "))
        pct = 100.0 * ok / len(variants) if variants else 0.0
        print(f"  {label:<14} {ok}/{len(variants)}  ({pct:.1f}%)")

    print(f"\n── enlace de {len(pares)} pares reales ──")
    for label, env_extra in (("Mesa (Intel)", MESA_ENV), ("NVIDIA", {})):
        env = {**os.environ, **env_extra}
        ok, motivos = 0, Counter()
        for i in range(0, len(pares), 60):
            chunk = pares[i:i + 60]
            args = [str(x) for par in chunk for x in par]
            p = subprocess.run([str(check), "--desktop", "--link", *args],
                               capture_output=True, text=True, env=env)
            ok += sum(1 for l in p.stdout.splitlines() if l.startswith("OK "))
            for bloque in p.stderr.split("== enlace ")[1:]:
                log = bloque.partition("\n")[2]
                motivo = next((l.strip() for l in log.splitlines()
                               if "error" in l.lower()), log.strip())
                motivos[motivo[:90]] += 1
        pct = 100.0 * ok / len(pares) if pares else 0.0
        print(f"  {label:<14} {ok}/{len(pares)}  ({pct:.1f}%)")
        for m, n in motivos.most_common(6):
            print(f"       {n} x {m}")

    print(f"\nvariantes en: {tmp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
