#!/usr/bin/env python3
"""Prueba de regresion del decodificador .tex.

No lleva ficheros de prueba propios: valida contra los assets de Wallpaper
Engine instalados y contra las 145 suscripciones del Workshop. Dos criterios,
los dos objetivos:

  1. El parser debe consumir cada fichero hasta el ultimo byte. Un solo byte
     sobrante significa que un campo esta mal leido en alguna version del
     contenedor.
  2. Los bloques BC/DXT se contrastan pixel a pixel contra el decodificador
     DDS de PIL, que es independiente. Se tolera una diferencia de 1 por
     canal: la spec de D3D deja libre el redondeo de la paleta interpolada.

Uso:  python3 tools/test_wetex.py [--workshop]
"""

from __future__ import annotations

import glob
import io
import struct
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import wepaths
import wetex
from pkg_inspect import read_pkg

FOURCC = {wetex.TexFormat.DXT1: b"DXT1",
          wetex.TexFormat.DXT3: b"DXT3",
          wetex.TexFormat.DXT5: b"DXT5"}


def dds_wrap(raw: bytes, w: int, h: int, fourcc: bytes) -> bytes:
    """Envuelve bloques BC crudos en un DDS minimo para dárselos a PIL."""
    hdr = b"DDS " + struct.pack("<7I", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000,
                                h, w, len(raw), 0, 0)
    hdr += b"\0" * 44
    hdr += struct.pack("<2I", 32, 0x4) + fourcc + b"\0" * 20
    hdr += struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    return hdr + raw


def check(name: str, data: bytes, res: Counter, errs: Counter) -> None:
    try:
        tex = wetex.read_texture(data)
    except wetex.TexError as e:
        if "volumen" in str(e):
            res["lut_omitido"] += 1
        else:
            res["parse_err"] += 1
            errs[f"{name}: {e}"[:90]] += 1
        return
    except Exception as e:
        res["parse_err"] += 1
        errs[f"{name}: {type(e).__name__}: {e}"[:90]] += 1
        return

    res["parse_ok"] += 1
    if tex.trailing:
        res["bytes_sobrantes"] += 1
        errs[f"{name}: {tex.trailing} B sin consumir"] += 1

    for mips in tex.images:
        for mip in mips:
            if mip.video:
                res["video_mp4"] += 1
                continue
            try:
                mine = mip.to_rgba(tex.format)
            except Exception as e:
                res["decode_err"] += 1
                errs[f"{name}: decode {type(e).__name__}: {e}"[:90]] += 1
                continue
            res["decode_ok"] += 1

            if tex.format in FOURCC and not mip.embedded:
                ref = np.array(Image.open(io.BytesIO(dds_wrap(
                    mip.raw, mip.width, mip.height, FOURCC[tex.format]
                ))).convert("RGBA")).astype(np.int16)
                d = np.abs(mine.astype(np.int16) - ref[:mine.shape[0], :mine.shape[1]])
                if d.max() > 1:
                    res["dxt_discrepa"] += 1
                    errs[f"{name}: DXT difiere en {d.max()}"] += 1
                else:
                    res["dxt_verificado"] += 1


def main() -> int:
    res, errs = Counter(), Counter()

    for f in sorted(glob.glob(f"{wepaths.we_assets()}/**/*.tex", recursive=True)):
        check(Path(f).name, Path(f).read_bytes(), res, errs)

    if "--workshop" in sys.argv:
        for p in sorted(glob.glob(f"{wepaths.we_workshop()}/*/*.pkg")):
            try:
                _, entries = read_pkg(p)
            except Exception as e:
                res["pkg_err"] += 1
                errs[f"{Path(p).parent.name}: {type(e).__name__}"] += 1
                continue
            res["pkg_ok"] += 1
            for e in entries:
                if e["name"].lower().endswith(".tex"):
                    check(f"{Path(p).parent.name}/{e['name']}", e["data"], res, errs)

    for k in sorted(res):
        print(f"  {k:<18} {res[k]}")

    fallos = res["parse_err"] + res["decode_err"] + res["bytes_sobrantes"] + res["dxt_discrepa"]
    if fallos:
        print(f"\nFALLOS: {fallos}")
        for k, v in errs.most_common(15):
            print(f"  {v:>4} x {k}")
        return 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
