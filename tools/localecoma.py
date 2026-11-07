"""La locale con coma decimal con la que las pruebas imitan al escritorio.

Con coma decimal `strtof("0.5")` da 0 (CLAUDE.md, regla 6), y los arneses
en C lo prueban con una locale asi. Pedir `es_ES.UTF-8` a ciegas no vale:
donde no esta instalada, `setlocale` falla, el arnes sigue en `C` y la
prueba pasa sin probar nada. Se prefiere `es_ES`, y si no, cualquier otra
instalada cuya coma decimal se compruebe con `locale decimal_point`.
"""

from __future__ import annotations

import functools
import os
import subprocess

PREFERIDAS = ("es_es.utf8", "es_es.utf-8", "de_de.utf8", "fr_fr.utf8",
              "it_it.utf8", "pt_br.utf8")


def _separador(loc: str) -> str | None:
    try:
        r = subprocess.run(["locale", "decimal_point"], capture_output=True,
                           text=True, timeout=5,
                           env={**os.environ, "LC_ALL": loc})
    except (OSError, subprocess.SubprocessError):
        return None
    # Una locale que no existe no da error: contesta lo de `C`.
    return r.stdout.strip() if r.returncode == 0 else None


@functools.cache
def locale_con_coma() -> str | None:
    """Una locale instalada con coma decimal, o None si no hay ninguna."""
    try:
        salida = subprocess.run(["locale", "-a"], capture_output=True,
                                text=True, check=True, timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None

    def preferencia(nombre: str) -> tuple:
        bajo = nombre.lower()
        # Las UTF-8 antes: los arneses escriben texto con acentos.
        return (PREFERIDAS.index(bajo) if bajo in PREFERIDAS else len(PREFERIDAS),
                "utf" not in bajo, nombre)

    return next((n for n in sorted(salida, key=preferencia)
                 if _separador(n) == ","), None)


SIN_COMA = ("no hay ninguna locale con coma decimal instalada: la prueba de "
            "la locale del escritorio no prueba nada (instala es_ES.UTF-8)")
