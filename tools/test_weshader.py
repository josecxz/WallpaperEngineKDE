#!/usr/bin/env python3
"""Regresion del traductor de shaders: traduce el corpus y lo compila de verdad.

El criterio no es "el traductor no revienta", es "el driver acepta el GLSL".
Se compila con Mesa y con NVIDIA porque esta maquina tiene graficos hibridos
y los dos compiladores no aceptan exactamente lo mismo.

Uso:
    cc -O2 -o /tmp/glslcheck tools/glslcheck.c -lEGL -lGLESv2
    python3 tools/test_weshader.py <dir_corpus> <ruta_glslcheck>
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import weshader

WE_ASSETS = Path("/home/jose/wallpapers/steam_library/steamapps/common/wallpaper_engine/assets")
MESA_ENV = {"__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json"}


def categorise(log: str) -> str:
    """Agrupa el log del compilador para que 2000 fallos no sean 2000 lineas."""
    for line in log.splitlines():
        line = line.strip()
        if not line or line.startswith("=="):
            continue
        line = re.sub(r"^\d+:\d+\(\d+\):\s*", "", line)      # Mesa
        line = re.sub(r"^0\(\d+\)\s*:\s*", "", line)          # NVIDIA
        line = re.sub(r"['`][^'`]*['`]", "X", line)
        line = re.sub(r"\b\d+\b", "N", line)
        return line[:100]
    return "(sin log)"


def compile_batch(check: Path, files: list[Path], env_extra: dict,
                  extra_args: list[str] | None = None) -> tuple[set[str], dict]:
    env = {**os.environ, **env_extra}
    extra_args = extra_args or []
    ok: set[str] = set()
    logs: dict[str, str] = {}
    for i in range(0, len(files), 150):
        chunk = files[i:i + 150]
        p = subprocess.run([str(check), *extra_args, *map(str, chunk)],
                           capture_output=True, text=True, env=env)
        for line in p.stdout.splitlines():
            if line.startswith("OK "):
                ok.add(line[3:])
        for block in p.stderr.split("== ")[1:]:
            head, _, rest = block.partition(" ==\n")
            logs[head] = rest
    return ok, logs


def main() -> int:
    corpus = Path(sys.argv[1])
    check = Path(sys.argv[2])

    shaders = [f for f in sorted(corpus.rglob("*")) if f.suffix in (".frag", ".vert")]
    tmp = Path(tempfile.mkdtemp(prefix="weshader-"))

    translated: list[Path] = []
    trans_err = Counter()
    n_trans_fail = 0

    for f in shaders:
        # Un wallpaper puede traer su propia version de un header; su carpeta
        # tiene que ganar sobre los assets compartidos.
        pkg_root = f
        while pkg_root.parent != corpus and pkg_root.parent.name != "shaders":
            if pkg_root.parent == corpus:
                break
            pkg_root = pkg_root.parent
        roots = [f.parent, f.parent.parent, f.parent.parent.parent,
                 WE_ASSETS, WE_ASSETS / "shaders"]
        resolver = weshader.Resolver(roots=[r for r in roots if r.is_dir()])
        stage = "vert" if f.suffix == ".vert" else "frag"
        try:
            out = weshader.translate(f.read_text(errors="replace"), stage, resolver)
        except weshader.ShaderError as e:
            n_trans_fail += 1
            trans_err[str(e)[:70]] += 1
            continue
        except Exception as e:
            n_trans_fail += 1
            trans_err[f"{type(e).__name__}: {e}"[:70]] += 1
            continue

        dest = tmp / (str(f.relative_to(corpus)).replace("/", "__"))
        dest = dest.with_suffix(f.suffix)
        dest.write_text(out)
        translated.append(dest)

    print(f"shaders en el corpus : {len(shaders)}")
    print(f"traducidos           : {len(translated)}")
    print(f"traduccion fallida   : {n_trans_fail}")
    if trans_err:
        for k, v in trans_err.most_common(8):
            print(f"    {v:>4} x {k}")

    for label, env_extra, extra_args in (
            ("Mesa (Intel)", MESA_ENV, ["--desktop"]),
            ("NVIDIA", {}, ["--desktop"])):
        ok, logs = compile_batch(check, translated, env_extra, extra_args)
        fail = [d for d in translated if str(d) not in ok]
        pct = 100.0 * len(ok) / len(translated) if translated else 0.0
        print(f"\n── {label}: compilan {len(ok)}/{len(translated)} ({pct:.1f}%)")
        if fail:
            cats = Counter(categorise(logs.get(str(d), "")) for d in fail)
            for k, v in cats.most_common(10):
                print(f"    {v:>4} x {k}")
    print(f"\ntraducidos en: {tmp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
