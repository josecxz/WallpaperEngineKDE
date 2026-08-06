"""Localiza la instalacion de Wallpaper Engine y su contenido de Workshop.

Estas rutas no pueden codificarse: Steam deja cada biblioteca donde el usuario
quiera, y una instalacion copiada a mano puede no aparecer siquiera en
`libraryfolders.vdf` -- que es justo el caso de la maquina donde se escribio
esto. Por eso el orden es:

  1. `WE_ASSETS` / `WE_WORKSHOP`, que mandan siempre.
  2. Las bibliotecas que Steam declara en `libraryfolders.vdf`.
  3. Las ubicaciones habituales de Steam (incluido el flatpak).

Si nada da resultado se lanza `WePathError` diciendo que variable definir, en
lugar de fallar mas adelante con un `FileNotFoundError` sin contexto.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

# Wallpaper Engine en Steam.
APPID = "431960"

# Raices habituales de Steam. Cada una deberia contener un `steamapps/`.
_STEAM_ROOTS = (
    "~/.steam/steam",
    "~/.steam/root",
    "~/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",  # flatpak
)

_ASSETS_REL = ("steamapps", "common", "wallpaper_engine", "assets")
_WORKSHOP_REL = ("steamapps", "workshop", "content", APPID)


class WePathError(RuntimeError):
    """No se encontro la instalacion de Wallpaper Engine."""


def _vdf_library_paths(vdf: Path) -> list[Path]:
    """Extrae las rutas de biblioteca de un libraryfolders.vdf.

    El fichero es VDF, no JSON, pero solo necesitamos las lineas
    `"path"  "/donde/sea"`; una expresion regular evita una dependencia.
    """
    try:
        text = vdf.read_text(errors="replace")
    except OSError:
        return []
    return [Path(m) for m in re.findall(r'"path"\s*"([^"]+)"', text)]


@lru_cache(maxsize=1)
def steam_libraries() -> tuple[Path, ...]:
    """Bibliotecas de Steam detectadas, sin repetir y en orden de preferencia."""
    found: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        p = p.expanduser()
        if p not in seen and (p / "steamapps").is_dir():
            seen.add(p)
            found.append(p)

    roots = [Path(r).expanduser() for r in _STEAM_ROOTS]
    for r in roots:
        add(r)
    # Las declaradas por Steam pueden estar en cualquier disco.
    for r in roots:
        for lib in _vdf_library_paths(r / "steamapps" / "libraryfolders.vdf"):
            add(lib)

    return tuple(found)


def _resolve(env_var: str, rel: tuple[str, ...], what: str) -> Path:
    override = os.environ.get(env_var)
    if override:
        p = Path(override).expanduser()
        if not p.is_dir():
            raise WePathError(f"{env_var}={override} no es un directorio")
        return p

    for lib in steam_libraries():
        p = lib.joinpath(*rel)
        if p.is_dir():
            return p

    probed = "\n  ".join(str(lib.joinpath(*rel)) for lib in steam_libraries()) \
        or "(no se detecto ninguna biblioteca de Steam)"
    raise WePathError(
        f"no se encontro {what}.\n"
        f"Define {env_var} con la ruta, por ejemplo:\n"
        f"  export {env_var}=/ruta/a/steam_library/{'/'.join(rel)}\n"
        f"Se probaron:\n  {probed}")


def we_assets() -> Path:
    """Directorio `assets` de Wallpaper Engine (shaders y texturas comunes)."""
    return _resolve("WE_ASSETS", _ASSETS_REL, "los assets de Wallpaper Engine")


def we_workshop() -> Path:
    """Directorio con los wallpapers suscritos en Workshop."""
    return _resolve("WE_WORKSHOP", _WORKSHOP_REL, "el contenido de Workshop")


if __name__ == "__main__":
    for name, fn in (("assets", we_assets), ("workshop", we_workshop)):
        try:
            print(f"{name:9} {fn()}")
        except WePathError as e:
            print(f"{name:9} {e}")
