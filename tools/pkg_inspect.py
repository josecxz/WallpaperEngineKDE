#!/usr/bin/env python3
"""Inventario de un contenedor scene.pkg de Wallpaper Engine.

Formato (PKGV0016):
    u32 len + char[len]   cadena de version, p.ej. "PKGV0016"
    u32                   numero de entradas
    por entrada:
        u32 len + char[len]   ruta logica
        u32                   offset relativo al inicio de los blobs
        u32                   tamano en bytes
    ...blobs...

Los offsets son relativos al final de la tabla, no al inicio del fichero.
"""

import json
import struct
import sys
from collections import Counter
from pathlib import Path


def _str(buf, pos):
    (n,) = struct.unpack_from("<I", buf, pos)
    pos += 4
    return buf[pos:pos + n].decode("utf-8"), pos + n


def read_pkg(path):
    buf = Path(path).read_bytes()
    version, pos = _str(buf, 0)
    (count,) = struct.unpack_from("<I", buf, pos)
    pos += 4

    entries = []
    for _ in range(count):
        name, pos = _str(buf, pos)
        offset, size = struct.unpack_from("<II", buf, pos)
        pos += 8
        entries.append({"name": name, "offset": offset, "size": size})

    base = pos  # los blobs empiezan justo despues de la tabla
    for e in entries:
        e["data"] = buf[base + e["offset"]:base + e["offset"] + e["size"]]
    return version, entries


def main():
    pkg = sys.argv[1]
    version, entries = read_pkg(pkg)

    print(f"version : {version}")
    print(f"entradas: {len(entries)}")
    print(f"payload : {sum(e['size'] for e in entries) / 2**20:.1f} MiB\n")

    by_ext = Counter(Path(e["name"]).suffix.lower() or "(sin ext)" for e in entries)
    print("por extension:")
    for ext, n in by_ext.most_common():
        total = sum(e["size"] for e in entries if (Path(e["name"]).suffix.lower() or "(sin ext)") == ext)
        print(f"  {ext:<10} {n:>3} ficheros  {total / 2**20:>7.2f} MiB")

    print("\ncontenido:")
    for e in sorted(entries, key=lambda x: -x["size"]):
        print(f"  {e['size']:>9}  {e['name']}")

    if len(sys.argv) > 2:
        outdir = Path(sys.argv[2])
        for e in entries:
            dest = outdir / e["name"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(e["data"])
        print(f"\nextraido -> {outdir}")


if __name__ == "__main__":
    main()
