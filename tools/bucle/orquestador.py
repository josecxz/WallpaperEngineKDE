#!/usr/bin/env python3
"""El bucle autónomo: triar un pendiente, resolverlo, comprobarlo y mezclarlo.

Tres sesiones de Claude Code en modo `-p`, cada una con su contexto:

  triador        .claude/agents/triador.md   elige UNA tarea medible
  implementador  tools/bucle/implementador.md la resuelve en un worktree
  revisor        .claude/agents/revisor.md   veto sobre lo que no se mide

y entre la segunda y la tercera, las COMPUERTAS, que ejecuta este script y no
un modelo: compilar, los tests, la orden de medida que declaró el
implementador y la luz de las 129 escenas contra la de la rama base. Lo que
dice una sesión de sí misma no cuenta; cuenta el código de salida.

Lo que este script NUNCA hace es tocar el escritorio: ni `make install` ni
`make reload`. Mezcla en la rama base y ahí se para. Instalar es de una
persona (regla 3 de CLAUDE.md).

Uso:
    python3 tools/bucle/orquestador.py                       # una tarea, base main
    python3 tools/bucle/orquestador.py --tareas 3
    python3 tools/bucle/orquestador.py --base Mi_Rama --pista "rope upright"
    python3 tools/bucle/orquestador.py --sin-mezclar         # deja la rama aprobada sin mezclar
    python3 tools/bucle/orquestador.py --estado              # qué se ha hecho y qué está bloqueado
    python3 tools/bucle/orquestador.py --documentar 20261004-211604
                                       # una no resuelta: revisar lo averiguado y mezclarlo

Estado y registros en ~/.local/state/wallpaperengine-bucle/, referencias de
luz, cerrojos y worktrees en ~/.cache/wallpaperengine/bucle/.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ESTADO_DIR = Path.home() / ".local/state/wallpaperengine-bucle"
CACHE = Path.home() / ".cache/wallpaperengine/bucle"
CERROJO_CORPUS = CACHE / "corpus.lock"
MESA = {"__EGL_VENDOR_LIBRARY_FILENAMES":
        "/usr/share/glvnd/egl_vendor.d/50_mesa.json"}

# Lo que ninguna tarea puede tocar. La guardia ya lo impide dentro de la
# sesión; esto lo vuelve a mirar en el diff, por si algo se coló.
PROHIBIDAS = ("tools/wectl.py", ".claude/", "tools/bucle/")

# Tests rápidos (segundos): siempre.
TESTS_SIEMPRE = ["test_werender", "test_weparticles", "test_wereloj",
                 "test_wetext", "test_wectl"]
# Tests caros o específicos: solo si el diff toca lo suyo.
TESTS_SI_TOCA = {
    "test_wetex": ("tools/wetex.py",),
    "test_wemdl": ("tools/wemdl.py",),
    "test_wevideo": ("tools/wevideo.py", "src/wevideo."),
    "test_weshader": ("tools/weshader.py", "tools/weglsl.py",
                      "tools/glslcheck.c"),
    "test_wescene": ("tools/weshader.py", "tools/weglsl.py",
                     "tools/wescene.py", "tools/glslcheck.c"),
}
CAIDA_LUZ = 0.25          # la misma que test_luminancia.CAIDA

ESQ_TRIAJE = {
    "type": "object",
    "properties": {
        "hay_tarea": {"type": "boolean"},
        "id": {"type": "string",
               "description": "identificador corto y estable, kebab-case"},
        "titulo": {"type": "string"},
        "rama": {"type": "string", "pattern": "^[A-Z][A-Za-z0-9]*(_[A-Z0-9][A-Za-z0-9]*)*$"},
        "seccion_notas": {"type": "string",
                          "description": "título y línea de NOTAS.md donde está el pendiente"},
        "descripcion": {"type": "string"},
        "escenas": {"type": "array", "items": {"type": "string"},
                    "description": "ids de Workshop del corpus que tienen el caso"},
        "como_medir": {"type": "string"},
        "criterio_aceptacion": {"type": "string"},
        "riesgos": {"type": "string"},
        "motivo_descarte": {"type": "string"},
    },
    "required": ["hay_tarea"],
}

ESQ_IMPL = {
    "type": "object",
    "properties": {
        "estado": {"enum": ["hecho", "no_resuelto"]},
        "resumen": {"type": "string"},
        "mensaje_commit": {"type": "string",
                           "description": "primera línea corta en castellano, cuerpo opcional"},
        "medida": {"type": "string",
                   "description": "qué se midió, sobre qué escenas, antes y después"},
        "medidas": {
            "type": "array", "minItems": 1,
            "description": "una por cada punto del criterio de aceptación; el "
                           "orquestador las vuelve a ejecutar todas",
            "items": {
                "type": "object",
                "properties": {
                    "criterio": {"type": "string",
                                 "description": "la etiqueta del punto, p. ej. «(b)», y qué comprueba"},
                    "orden": {"type": "string",
                              "description": "una orden de shell que sale con 0 solo si el punto se cumple"},
                    "espera": {"type": "string",
                               "description": "qué tiene que imprimir para demostrarlo"},
                },
                "required": ["criterio", "orden", "espera"],
            },
        },
    },
    "required": ["estado", "resumen", "mensaje_commit", "medida", "medidas"],
}
# Lo que pueden tardar entre todas las medidas declaradas.
MEDIDAS_MAX_S = 60 * 60
# Lo que puede tocar una tarea NO resuelta para que su rama se revise y se
# mezcle como documentación: lo averiguado, sin código.
DOCUMENTACION = ("NOTAS.md", "NOTAS-INDICE.md", "CLAUDE.md", "README.md")
# Lo que no cambia ningún píxel: si dos árboles solo difieren en esto, su luz
# es la misma y no se vuelve a medir.
SIN_RENDER = ("tools/bucle/", ".claude/", "NOTAS.md", "NOTAS-INDICE.md",
              "README.md", "CLAUDE.md", "LICENSE")

ESQ_REV = {
    "type": "object",
    "properties": {
        "veredicto": {"enum": ["APRUEBA", "RECHAZA"]},
        "motivos": {"type": "array", "items": {"type": "string"}},
        "reglas_violadas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["veredicto", "motivos"],
}


# ── utilidades ─────────────────────────────────────────────────────────────

class Registro:
    def __init__(self, dir_: Path):
        self.dir = dir_
        dir_.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str) -> None:
        linea = f"[{datetime.now():%H:%M:%S}] {msg}"
        print(linea, flush=True)
        with open(self.dir / "bucle.log", "a") as f:
            f.write(linea + "\n")

    def guarda(self, nombre: str, contenido) -> Path:
        p = self.dir / nombre
        p.write_text(contenido if isinstance(contenido, str)
                     else json.dumps(contenido, indent=1, ensure_ascii=False))
        return p


def sh(cmd, cwd=None, timeout=None, env=None, check=False) -> subprocess.CompletedProcess:
    e = dict(os.environ, **(env or {}))
    r = subprocess.run(cmd, cwd=cwd, timeout=timeout, env=e, text=True,
                       shell=isinstance(cmd, str), capture_output=True)
    if check and r.returncode:
        raise RuntimeError(f"{cmd}: rc={r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return r


def git(*args, cwd=REPO, check=True) -> str:
    return sh(["git", *args], cwd=cwd, check=check).stdout.strip()


def cola(texto: str, n: int = 60) -> str:
    return "\n".join(texto.splitlines()[-n:])


class Cerrojo:
    """flock: el del corpus lo comparten todas las pasadas de 129 escenas
    (dos a la vez llenan /tmp y se inventan regresiones)."""

    def __init__(self, ruta: Path, bloqueante: bool = True):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(ruta, "w")
        self.bloqueante = bloqueante

    def __enter__(self):
        modo = fcntl.LOCK_EX | (0 if self.bloqueante else fcntl.LOCK_NB)
        fcntl.flock(self.f, modo)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


# ── estado persistente ─────────────────────────────────────────────────────

def carga_estado() -> dict:
    p = ESTADO_DIR / "estado.json"
    return json.loads(p.read_text()) if p.exists() else {"tareas": []}


def guarda_estado(estado: dict) -> None:
    ESTADO_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO_DIR / "estado.json.tmp"
    tmp.write_text(json.dumps(estado, indent=1, ensure_ascii=False))
    tmp.replace(ESTADO_DIR / "estado.json")


def apunta(estado: dict, tarea: dict, resultado: str, **extra) -> None:
    estado["tareas"].append({
        "id": tarea.get("id"), "titulo": tarea.get("titulo"),
        "rama": tarea.get("rama"), "seccion": tarea.get("seccion_notas"),
        "resultado": resultado, "fecha": datetime.now().isoformat(timespec="seconds"),
        **extra})
    guarda_estado(estado)


# ── la guardia ─────────────────────────────────────────────────────────────

def instala_guardia() -> Path:
    """Copia la guardia fuera del repositorio y comprueba que muerde.

    Si apuntara a REPO/tools/bucle/guardia.py, bastaría con que alguien
    cambiara de rama para que el hook fallara... y un hook que falla con un
    código distinto de 2 NO bloquea: la guardia desaparecería sin avisar.
    """
    destino = CACHE / "guardia.py"
    CACHE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "tools/bucle/guardia.py", destino)
    for orden, debe in (("make reload", 2), ("echo systemctl", 2),
                        ("claude -p hola", 2), ("python3 tools/bucle/orquestador.py", 2),
                        ("git commit -m x", 0), ("make glexec", 0)):
        ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": orden}})
        r = subprocess.run([sys.executable, str(destino)], input=ev, text=True,
                           capture_output=True)
        if r.returncode != debe:
            raise SystemExit(f"la guardia no se comporta: «{orden}» dio {r.returncode}")
    return destino


def ajustes(guardia: Path) -> str:
    return json.dumps({"hooks": {"PreToolUse": [{
        "matcher": "Bash|Edit|Write|NotebookEdit|MultiEdit",
        "hooks": [{"type": "command",
                   "command": f"{sys.executable} {guardia}"}]}]}})


def guardia_acepta(guardia: Path, orden: str) -> str | None:
    """La orden de medida la ejecuta este script, fuera de la sesión: pasa
    por la misma guardia que cualquier Bash del modelo."""
    ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": orden}})
    r = subprocess.run([sys.executable, str(guardia)], input=ev, text=True,
                       capture_output=True)
    return None if r.returncode == 0 else r.stderr.strip()


# ── las sesiones de Claude ─────────────────────────────────────────────────

class Claude:
    def __init__(self, args, guardia: Path, reg: Registro):
        self.args, self.reg = args, reg
        self.settings = ajustes(guardia)
        self.coste = 0.0
        self.medidas: Path | None = None    # la carpeta de la tarea en curso

    def __call__(self, nombre: str, prompt: str, cwd: Path, esquema: dict, *,
                 agente: str | None = None, sistema: str | None = None,
                 solo_lectura: bool = False,
                 reanudar: str | None = None, horas: float = 1.0,
                 esfuerzo: str = "high") -> dict:
        cmd = ["claude", "-p", prompt,
               "--output-format", "json",
               "--json-schema", json.dumps(esquema),
               "--settings", self.settings,
               "--permission-mode", "acceptEdits",
               "--permission-prompts", "none",
               # Cada herramienta, un argumento: como una sola cadena con
               # espacios no se lee como lista y no se permite ninguna.
               "--allowedTools", "Bash", "Read", "Glob", "Grep", "WebSearch",
               "WebFetch(domain:docs.wallpaperengine.io)",
               *(() if solo_lectura else ("Edit", "Write")),
               "--effort", esfuerzo,
               "--max-budget-usd", str(self.args.presupuesto)]
        if self.args.modelo:
            cmd += ["--model", self.args.modelo]
        # En `-p` la sesión acaba con el turno: quien lanza algo en segundo
        # plano y programa un despertador no vuelve nunca (el implementador
        # se quedó sin su medida así). Todo en primer plano.
        cmd += ["--disallowedTools", "ScheduleWakeup", "Monitor", "CronCreate",
                "CronDelete", "CronList", "RemoteTrigger", "PushNotification",
                *(("Edit", "Write", "NotebookEdit") if solo_lectura else ())]
        if agente:
            cmd += ["--agent", agente]
        if sistema:
            cmd += ["--append-system-prompt", sistema]
        if reanudar:
            cmd += ["--resume", reanudar]
        self.reg(f"  → {nombre} (cwd {cwd.name})")
        t0 = time.time()
        try:
            r = sh(cmd, cwd=cwd, timeout=int(horas * 3600),
                   env={"WE_BUCLE_RAIZ": str(cwd),
                        "WE_BUCLE_MEDIDAS": str(self.medidas or ""),
                        "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
                        "BASH_DEFAULT_TIMEOUT_MS": str(30 * 60_000),
                        "BASH_MAX_TIMEOUT_MS": str(60 * 60_000)})
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{nombre}: sin terminar en {horas} h")
        self.reg.guarda(f"{nombre}.stderr", r.stderr)
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            self.reg.guarda(f"{nombre}.stdout", r.stdout)
            raise RuntimeError(f"{nombre}: salida no es JSON (rc={r.returncode})")
        self.reg.guarda(f"{nombre}.json", out)
        self.coste += out.get("total_cost_usd") or 0
        self.reg(f"  ← {nombre}: {out.get('subtype')} en {time.time() - t0:.0f}s, "
                 f"{out.get('num_turns')} turnos, "
                 f"{len(out.get('permission_denials') or [])} bloqueos, "
                 f"${out.get('total_cost_usd') or 0:.2f}")
        if out.get("is_error"):
            raise RuntimeError(f"{nombre}: {out.get('subtype')} "
                               f"{str(out.get('result'))[:500]}")
        if not isinstance(out.get("structured_output"), dict):
            # Ha hecho el trabajo pero lo ha contado en texto: una sola
            # oportunidad de entregarlo por la vía del esquema, sin repetirlo.
            if nombre.endswith("-json") or not out.get("session_id"):
                raise RuntimeError(f"{nombre}: sin salida estructurada: "
                                   f"{str(out.get('result'))[:500]}")
            return self(f"{nombre}-json",
                        "Devuelve ya el resultado con la herramienta de salida "
                        "estructurada, ajustado exactamente al esquema. No "
                        "repitas el trabajo.", cwd, esquema, agente=agente,
                        sistema=sistema, solo_lectura=solo_lectura,
                        reanudar=out["session_id"], horas=0.25, esfuerzo="low")
        res = out["structured_output"]
        res["_session_id"] = out.get("session_id")
        return res


# ── copias de trabajo ──────────────────────────────────────────────────────
#
# Un CLON compartido y no un `git worktree`. El worktree enlazado guarda su git
# en REPO/.git, fuera del directorio de la sesión, y Claude Code pide
# aprobación para cualquier orden de git ahí dentro aunque Bash esté permitido:
# en `-p` nadie la da y al revisor se le denegó hasta un `git diff`. El clon
# tiene su propio .git (los objetos los comparte con --shared) y, de paso,
# ninguna sesión puede tocar las ramas del repositorio de verdad: lo que sale
# de un clon lo trae el orquestador con `trae_rama`.

def nuevo_worktree(nombre: str, commit: str) -> Path:
    ruta = CACHE / "wt" / nombre
    if ruta.exists():
        borra_worktree(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    git("clone", "-q", "--shared", "--no-checkout", str(REPO), str(ruta))
    git("checkout", "-q", "--detach", commit, cwd=ruta)
    # git es libre en el clon, pero un `git push` llegaría a REPO y metería
    # algo en una rama sin compuertas ni revisor: el clon no tiene adónde
    # empujar. Traer (fetch) sí puede.
    git("remote", "set-url", "--push", "origin", "SIN_PUSH_EN_EL_BUCLE", cwd=ruta)
    # La identidad puede estar solo en la configuración local de REPO, que un
    # clon no hereda: sin esto el primer commit falla.
    for clave in ("user.name", "user.email"):
        valor = git("config", clave, check=False)
        if valor:
            git("config", clave, valor, cwd=ruta)
    return ruta


def borra_worktree(ruta: Path) -> None:
    shutil.rmtree(ruta, ignore_errors=True)


def trae_rama(wt: Path, rama: str) -> None:
    """Copia la rama del clon al repositorio, antes de que el clon se borre."""
    git("fetch", "-q", str(wt), f"+refs/heads/{rama}:refs/heads/{rama}")


def construye(wt: Path, reg: Registro) -> str | None:
    """Compila lo que usan las compuertas. Devuelve el error o None."""
    for nombre, orden in (
            ("make build", "make build"),
            ("make glexec", "make glexec"),
            ("make psysprobe", "make psysprobe"),
            ("glslcheck", "mkdir -p obj && cc -O2 -o obj/glslcheck "
                          "tools/glslcheck.c -lEGL -lGLESv2")):
        r = sh(orden, cwd=wt, timeout=1800)
        if r.returncode:
            return f"{nombre} falla:\n{cola(r.stdout + r.stderr, 40)}"
    return None


# ── la luz del corpus ──────────────────────────────────────────────────────

def mide_luz(wt: Path, salida: Path, reg: Registro) -> dict:
    """Las 129 escenas, en Mesa (el driver del escritorio), bajo el cerrojo."""
    reg(f"  luz del corpus en {wt.name} …")
    with Cerrojo(CERROJO_CORPUS):
        r = sh([sys.executable, "tools/test_luminancia.py", "obj/glexec",
                "--guardar", str(salida)], cwd=wt, timeout=3600, env=MESA)
    reg.guarda(f"luz-{wt.name}.log", r.stdout + r.stderr)
    if not salida.exists():
        raise RuntimeError(f"test_luminancia no dejó medida:\n{cola(r.stdout + r.stderr)}")
    return json.loads(salida.read_text())


# La luz depende del ÁRBOL y del corpus, no del commit: tras una mezcla limpia
# el árbol de la base nueva es el del candidato, cuya luz ya se midió, y
# medirla otra vez eran seis minutos tirados en cada tarea. Por eso la caché
# va por árbol, y además vale la de un árbol que solo difiera en SIN_RENDER
# (la base que se mueve por un cambio en el propio bucle costaba doce).

_huella = None


def huella_corpus() -> str:
    """Cambia si cambia el corpus: otra escena, o un scene.pkg actualizado."""
    global _huella
    if _huella is None:
        sys.path.insert(0, str(REPO / "tools"))
        import hashlib
        import wepaths
        h = hashlib.sha256()
        for d in sorted(wepaths.we_workshop().iterdir()):
            pkg = d / "scene.pkg"
            if pkg.is_file():
                st = pkg.stat()
                h.update(f"{d.name} {st.st_size} {int(st.st_mtime)}\n".encode())
        _huella = h.hexdigest()[:8]
    return _huella


def ruta_luz(arbol: str) -> Path:
    return CACHE / "luz" / f"{arbol[:12]}-{huella_corpus()}.json"


def luz_conocida(arbol: str, cwd: Path, reg: Registro) -> dict | None:
    exacta = ruta_luz(arbol)
    if exacta.exists():
        reg(f"  luz reutilizada: el árbol {arbol[:12]} ya está medido")
        return json.loads(exacta.read_text())
    for otra in sorted((CACHE / "luz").glob(f"*-{huella_corpus()}.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True):
        r = sh(["git", "diff", "--name-only", otra.name[:12], arbol], cwd=cwd)
        if r.returncode:
            continue            # un árbol que este repositorio no conoce
        difiere = r.stdout.split()
        if all(f.startswith(SIN_RENDER) for f in difiere):
            reg(f"  luz reutilizada: el árbol {otra.name[:12]} solo difiere en "
                f"{len(difiere)} ficheros que no dibujan")
            datos = json.loads(otra.read_text())
            exacta.write_text(json.dumps(datos))
            return datos
    return None


def arbol_de(ref: str, cwd: Path = REPO) -> str:
    return git("rev-parse", f"{ref}^{{tree}}", cwd=cwd)


def referencia_luz(commit: str, reg: Registro) -> dict:
    arbol = arbol_de(commit)
    datos = luz_conocida(arbol, REPO, reg)
    if datos is not None:
        return datos
    reg(f"no hay referencia de luz para {commit[:12]}: se mide la base")
    wt = nuevo_worktree("_base", commit)
    try:
        err = construye(wt, reg)
        if err:
            raise RuntimeError(f"la BASE no compila, no hay con qué comparar:\n{err}")
        ruta_luz(arbol).parent.mkdir(parents=True, exist_ok=True)
        return mide_luz(wt, ruta_luz(arbol), reg)
    finally:
        borra_worktree(wt)


def compara_luz(base: dict, nueva: dict) -> list[str]:
    """Lo que ha empeorado. Las escenas que ya estaban mal en la base no
    cuentan: el bucle no tiene que arreglarlo todo para mezclar algo."""
    def apagada(v):
        if "media" not in v:
            return False
        if "razon" in v:
            return v["razon"] < 0.15
        return v["media"] < 8.0

    malas = []
    for k, v in sorted(nueva.items()):
        b = base.get(k)
        if b is None:
            continue
        if "error" in v and "error" not in b:
            malas.append(f"{k}: ya no renderiza ({v['error'][:120]})")
        elif apagada(v) and not apagada(b):
            malas.append(f"{k}: se ha apagado (media {b['media']} -> {v['media']})")
        elif ("media" in v and "media" in b and b["media"] > 1
              and v["media"] < b["media"] * (1 - CAIDA_LUZ)):
            malas.append(f"{k}: pierde luz {b['media']} -> {v['media']}")
    return malas


# ── las compuertas ─────────────────────────────────────────────────────────

def compuertas(wt: Path, base: str, impl: dict, guardia: Path, reg: Registro,
               intento: int, criterio: str, medidas: Path,
               cobertura: bool = True) -> tuple[bool, str]:
    informe: list[str] = []

    def mal(msg):
        informe.append("FALLO: " + msg)
        return False, "\n\n".join(informe)

    sh(["git", "add", "-A"], cwd=wt, check=True)
    cambios = git("diff", "--cached", "--name-only", base, cwd=wt).splitlines()
    reg(f"  compuertas: {len(cambios)} ficheros cambiados")
    if not cambios:
        return mal("no hay ningún cambio respecto a la base")
    tocadas = [c for c in cambios if c.startswith(PROHIBIDAS)]
    if tocadas:
        return mal(f"toca ficheros vedados: {tocadas}")
    if "NOTAS.md" not in cambios:
        return mal("NOTAS.md no cambia: la caza tiene que quedar anotada y el "
                   "pendiente tachado o actualizado")
    # Que haya una medida por punto del criterio no cuesta nada comprobarlo:
    # antes de compilar.
    lista = impl.get("medidas") or []
    if not lista:
        return mal("no hay medidas: una por cada punto del criterio de aceptación")
    pedidos = set(re.findall(r"\(([a-z])\)", criterio or ""))
    cubiertos = set()
    for m in lista:
        cubiertos |= set(re.findall(r"\(([a-z])\)", m.get("criterio", "")))
    faltan = sorted(pedidos - cubiertos)
    if faltan and cobertura:
        return mal("puntos del criterio de aceptación sin orden de medida: "
                   + ", ".join(f"({x})" for x in faltan))
    if ("tools/glexec.c" in cambios) != ("src/glexecutor.cpp" in cambios):
        informe.append("AVISO (para el revisor): cambia solo uno de los dos "
                       "ejecutores, glexec.c / glexecutor.cpp")

    err = construye(wt, reg)
    if err:
        return mal(err)
    informe.append("compila: make build, glexec, psysprobe, glslcheck")

    py = [c for c in cambios if c.endswith(".py") and (wt / c).exists()]
    if py:
        r = sh([sys.executable, "-m", "py_compile", *py], cwd=wt)
        if r.returncode:
            return mal(f"py_compile:\n{r.stderr}")

    r = sh([sys.executable, "tools/indice.py"], cwd=wt)
    m = re.search(r"(\d+) entradas, (\d+) cabeceras.*?(\d+) movidas, (\d+) sin casar",
                  r.stdout)
    if not m:
        return mal(f"tools/indice.py no da su resumen:\n{r.stdout}{r.stderr}")
    if int(m.group(3)) or int(m.group(4)):
        return mal(f"NOTAS-INDICE.md desfasado ({r.stdout.strip()}): falta `make indice`")
    rb = sh(f"git show {base}:NOTAS-INDICE.md | grep -c '^- `[0-9]'", cwd=wt)
    if int(m.group(1)) <= int(rb.stdout.strip() or 0):
        informe.append("AVISO (para el revisor): NOTAS-INDICE.md no tiene "
                       "ninguna entrada nueva")
    informe.append(f"índice al día: {r.stdout.strip()}")

    tests = list(TESTS_SIEMPRE)
    tests += [t for t, rutas in TESTS_SI_TOCA.items()
              if any(c.startswith(rutas) for c in cambios)]
    tests += sorted({Path(c).stem for c in cambios
                     if re.fullmatch(r"tools/test_\w+\.py", c)} - set(tests))
    for t in tests:
        argv = [sys.executable, f"tools/{t}.py"]
        if t == "test_wescene":
            argv += ["obj/glslcheck"]
        elif t == "test_weshader":
            assets = sh([sys.executable, "-c", "import sys; sys.path.insert(0,'tools');"
                         "import wepaths; print(wepaths.we_assets())"], cwd=wt).stdout.strip()
            argv += [f"{assets}/shaders", "obj/glslcheck"]
        reg(f"  {t} …")
        r = sh(argv, cwd=wt, timeout=1800)
        reg.guarda(f"{t}-{intento}.log", r.stdout + r.stderr)
        if r.returncode:
            return mal(f"{t} falla (rc={r.returncode}):\n{cola(r.stdout + r.stderr)}")
    informe.append(f"tests en verde: {', '.join(tests)}")

    # Cada punto del criterio, con su orden, y todas se vuelven a ejecutar
    # aquí (más abajo, tras compilar): lo que el implementador cuenta en
    # `medida` es texto, y en el rope dejó pasar una cifra que nadie midió.
    escribe_repetir(medidas, lista, wt)
    t0 = time.time()
    for k, m in enumerate(lista, 1):
        orden, etiqueta = m["orden"].strip(), m["criterio"].strip()
        veto = guardia_acepta(guardia, orden)
        if veto:
            return mal(f"medida {etiqueta}: orden vetada: {veto}")
        restante = MEDIDAS_MAX_S - (time.time() - t0)
        if restante < 30:
            return mal(f"las medidas tardan más de {MEDIDAS_MAX_S // 60} min")
        reg(f"  medida {etiqueta[:60]}: {orden[:120]}")
        # Sin el cerrojo del corpus: si la orden lo toma ella misma (como se
        # le pide al implementador para una pasada entera) se bloquearía.
        try:
            r = sh(orden, cwd=wt, timeout=int(min(900, restante)),
                   env={"WE_BUCLE_MEDIDAS": str(medidas)})
        except subprocess.TimeoutExpired:
            return mal(f"medida {etiqueta}: «{orden}» sin terminar a tiempo")
        reg.guarda(f"medida-{intento}-{k}.log", r.stdout + r.stderr)
        if r.returncode:
            return mal(f"medida {etiqueta}: «{orden}» sale con {r.returncode}:\n"
                       f"{cola(r.stdout + r.stderr)}")
        informe.append(f"medida {etiqueta} → 0\n  orden: {orden}\n"
                       f"  espera: {m.get('espera', '')}\n"
                       f"{cola(r.stdout + r.stderr, 20)}")

    ref = referencia_luz(base, reg)
    # El árbol del candidato tal como se confirmaría (el índice, tras add -A).
    arbol = git("write-tree", cwd=wt)
    nueva = luz_conocida(arbol, wt, reg)
    if nueva is None:
        ruta_luz(arbol).parent.mkdir(parents=True, exist_ok=True)
        nueva = mide_luz(wt, ruta_luz(arbol), reg)
    reg.guarda(f"luz-{intento}.json", nueva)
    malas = compara_luz(ref, nueva)
    if malas:
        return mal("la luz del corpus empeora respecto a la base:\n  "
                   + "\n  ".join(malas))
    informe.append(f"luz: {len(nueva)} escenas, ninguna empeora respecto a la base")
    return True, "\n\n".join(informe)


def escribe_repetir(medidas: Path, lista: list, wt: Path) -> None:
    """Un guion para repetir las medidas meses después, sin el bucle."""
    rama = git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt)
    lineas = ["#!/bin/sh",
              f"# Las medidas de la rama {rama}, tal como las pasó el orquestador.",
              f"# Se ejecutan desde un checkout de esa rama (o de donde se mezcló).",
              "set -e",
              f'export WE_BUCLE_MEDIDAS="{medidas}"']
    for m in lista:
        lineas += ["", f"echo {json.dumps('== ' + m['criterio'])}", m["orden"]]
    (medidas / "repetir.sh").write_text("\n".join(lineas) + "\n")
    (medidas / "repetir.sh").chmod(0o755)


# ── mezclar ────────────────────────────────────────────────────────────────

def donde_esta(rama: str) -> Path | None:
    """El worktree del REPOSITORIO que tiene la rama sacada, si lo hay."""
    actual = None
    for linea in git("worktree", "list", "--porcelain").splitlines():
        if linea.startswith("worktree "):
            actual = Path(linea.split(" ", 1)[1])
        elif linea == f"branch refs/heads/{rama}":
            return actual
    return None


def mezcla(rama: str, base: str, mensaje: str, reg: Registro) -> str | None:
    """Mezcla `rama` en `base` con --no-ff. Devuelve el error o None.

    Si alguien tiene `base` sacada con cambios sin confirmar, no se mezcla:
    pisarle el árbol a una persona es peor que esperar a la siguiente vuelta.
    """
    sitio = donde_esta(base)
    if sitio is not None:
        if git("status", "--porcelain", "--untracked-files=no", cwd=sitio):
            return f"{base} está sacada en {sitio} con cambios sin confirmar"
        r = sh(["git", "merge", "--no-ff", "-m", mensaje, rama], cwd=sitio)
        if r.returncode:
            sh(["git", "merge", "--abort"], cwd=sitio)
            return f"git merge falla:\n{r.stdout}{r.stderr}"
        return None
    viejo = git("rev-parse", base)
    r = sh(["git", "merge-tree", "--write-tree", base, rama], cwd=REPO)
    if r.returncode:
        return f"conflicto al mezclar:\n{r.stdout}"
    arbol = r.stdout.split()[0]
    nuevo = git("commit-tree", arbol, "-p", viejo, "-p", git("rev-parse", rama),
                "-m", mensaje)
    git("update-ref", f"refs/heads/{base}", nuevo, viejo)
    return None


def confirma(wt: Path, impl: dict) -> None:
    msg = impl["mensaje_commit"].strip()
    msg += ("\n\nHecho por el bucle autónomo (tools/bucle/).\n\n"
            "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>")
    sh(["git", "add", "-A"], cwd=wt, check=True)
    # La sesión puede haber confirmado ella misma: solo queda lo que no.
    if git("status", "--porcelain", cwd=wt):
        sh(["git", "commit", "-q", "-m", msg], cwd=wt, check=True)


# ── una tarea ──────────────────────────────────────────────────────────────

PROMPT_TRIAJE = """\
Elige la siguiente tarea del bucle autónomo.

Rama base: {base} ({commit}).
Tareas que el bucle ya ha intentado (no repitas las hechas; las bloqueadas
solo si su motivo ya no se aplica):
{historial}

{pista}
"""

PROMPT_IMPL = """\
Tarea del bucle autónomo:

{tarea}

Escenas del corpus con el caso: {escenas}
Criterio de aceptación: {criterio}

Carpeta para tus scripts de medida (se conserva con el registro de la tarea):
$WE_BUCLE_MEDIDAS = {medidas}
"""

PROMPT_REINTENTO = """\
El intento {n} no se ha aceptado. Motivos, todos a atender:

{motivos}

Corrige en este mismo clon y devuelve el JSON otra vez. Tus cambios siguen
aquí: los que pasaron las compuertas están confirmados (`git log`), el resto
sin confirmar (`git status`).
"""

PROMPT_REV = """\
Revisa la rama de esta tarea. Los cambios son `git diff {base}..HEAD` en este
directorio (y `git log {base}..HEAD`).

Tarea:
{tarea}

Lo que declara el implementador:
{impl}

Salida de las compuertas automáticas (ya han pasado). Las `medidas` las ha
vuelto a ejecutar el orquestador, una por una: que salgan con 0 no basta, juzga
si lo que imprimen demuestra el punto del criterio que dicen cubrir. Sus
scripts están en $WE_BUCLE_MEDIDAS = {medidas} (y `repetir.sh` las repite).
{compuertas}
"""


PROMPT_REV_DOC = """\
Revisa la rama de esta tarea, que ha quedado NO RESUELTA. No trae código: solo
documenta lo que se averiguó (`git diff {base}..HEAD` en este directorio). Si
apruebas, se mezcla como documentación y el próximo triador partirá de ella, así
que lo que decides es si es verdad y si se puede comprobar.

Tarea original:
{tarea}

Por qué no se resolvió, según el implementador:
{impl}

Salida de las compuertas (ya han pasado; las `medidas` las ha vuelto a
ejecutar el orquestador). Sus scripts están en $WE_BUCLE_MEDIDAS = {medidas}.
{compuertas}

Rechaza si:
- una afirmación no se puede comprobar con lo que hay en la rama o en
  $WE_BUCLE_MEDIDAS: direcciones del binario sin un script que las verifique,
  cifras del corpus sin el script que las cuenta. Ejecútalos tú.
- una cifra no coincide con lo que dan esos scripts;
- el pendiente queda tachado como si estuviera hecho, en vez de actualizado con
  lo averiguado y lo que falta;
- NOTAS.md propone una regla nueva sin decir qué la confirma y qué la refutaría.
Si apruebas, en `motivos` di también qué tarea nueva queda abierta, si alguna.
"""


def trae_base(args, wt: Path, reg: Registro) -> str | None:
    """Mezcla en la rama de la tarea lo que la base haya avanzado.

    Devuelve el commit nuevo de la base, o None si hay conflicto."""
    sh(["git", "fetch", "-q", "origin", args.base], cwd=wt, check=True)
    r = sh(["git", "merge", "--no-edit", "FETCH_HEAD"], cwd=wt)
    if r.returncode:
        sh(["git", "merge", "--abort"], cwd=wt)
        return None
    return git("rev-parse", args.base)


def documenta(args, claude: Claude, guardia: Path, estado: dict, reg: Registro,
              wt: Path, rama: str, tarea: dict, impl: dict, base_commit: str,
              medidas: Path, n: int) -> None:
    """Un «no resuelto» también puede dejar algo: lo averiguado.

    En `Emisor_Flags2` el implementador leyó en el binario que la hipótesis de
    la tarea era falsa, y por qué. Sin esto, esas 130 líneas de NOTAS se
    quedaban en una rama sin revisar y el triador siguiente no las veía. Si la
    rama solo toca documentación pasa por compuertas y por un revisor que
    juzga si lo escrito es verdad, y entra como «documentada». Si no, como
    antes: `no_resuelto`, con la rama guardada.
    """
    def sin_mezclar(motivo: str) -> None:
        apunta(estado, tarea, "no_resuelto", motivo=motivo, rama_sin_mezclar=rama,
               medidas=str(medidas))

    cambios = git("diff", "--name-only", base_commit, "HEAD", cwd=wt).split()
    if not cambios:
        return sin_mezclar(impl["resumen"])
    codigo = [c for c in cambios if c not in DOCUMENTACION]
    if codigo:
        reg(f"no se revisa como documentación: toca {len(codigo)} ficheros de código")
        return sin_mezclar(impl["resumen"])
    if git("rev-parse", args.base) != base_commit:
        nuevo = trae_base(args, wt, reg)
        if nuevo is None:
            return sin_mezclar(impl["resumen"] + "\n(conflicto con la base)")
        base_commit = nuevo
    reg(f"se revisa como documentación: {', '.join(cambios)}")
    texto_tarea = json.dumps({k: v for k, v in tarea.items() if not k.startswith("_")},
                             indent=1, ensure_ascii=False)
    texto_impl = json.dumps({k: v for k, v in impl.items() if not k.startswith("_")},
                            indent=1, ensure_ascii=False)
    ok, informe = compuertas(wt, base_commit, impl, guardia, reg, n,
                             tarea.get("criterio_aceptacion", ""), medidas,
                             cobertura=False)
    reg.guarda(f"compuertas-doc-{n}.txt", informe)
    if not ok:
        reg("  compuertas: FALLO")
        return sin_mezclar(impl["resumen"] + "\n\nCompuertas de la documentación:\n"
                           + informe[-1500:])
    reg("  compuertas: OK")
    confirma(wt, impl)
    cabeza = git("rev-parse", "HEAD", cwd=wt)
    rev = claude(f"revisor-{n}", PROMPT_REV_DOC.format(
        base=base_commit[:12], tarea=texto_tarea, impl=texto_impl,
        compuertas=informe, medidas=medidas), wt, ESQ_REV, agente="revisor",
        solo_lectura=True, horas=1)
    if git("rev-parse", "HEAD", cwd=wt) != cabeza or git("status", "--porcelain", cwd=wt):
        reg("  el revisor ha tocado el árbol: su veredicto no vale")
        return sin_mezclar(impl["resumen"])
    reg(f"  revisor: {rev['veredicto']}")
    if rev["veredicto"] != "APRUEBA":
        return sin_mezclar(impl["resumen"] + "\n\nDocumentación rechazada:\n"
                           + "\n".join(f"- {m}" for m in rev["motivos"]))
    if args.sin_mezclar:
        apunta(estado, tarea, "aprobada_sin_mezclar", rama_sin_mezclar=rama,
               motivo=impl["resumen"], observaciones=rev["motivos"])
        return None
    trae_rama(wt, rama)
    err = mezcla(rama, args.base,
                 f"Merge branch '{rama}' (documentada): {tarea['titulo']}", reg)
    if err:
        reg(f"documentación aprobada pero sin mezclar: {err}")
        apunta(estado, tarea, "aprobada_sin_mezclar", rama_sin_mezclar=rama,
               motivo=err, observaciones=rev["motivos"])
        return None
    apunta(estado, tarea, "documentada", motivo=impl["resumen"],
           observaciones=rev["motivos"], medidas=str(medidas))
    reg(f"MEZCLADA en {args.base} como documentación: {rama}")
    return None


def una_tarea(args, claude: Claude, guardia: Path, estado: dict, reg: Registro) -> bool:
    """Devuelve True si conviene seguir con otra tarea."""
    base_commit = git("rev-parse", args.base)
    wt = nuevo_worktree(f"tarea-{datetime.now():%Y%m%d-%H%M%S}", base_commit)
    rama = None
    try:
        historial = "\n".join(
            f"- [{t['resultado']}] {t['titulo']} ({t.get('seccion')})"
            + (f": {t['motivo'][:300]}" if t.get("motivo") else "")
            for t in estado["tareas"]) or "(ninguna)"
        pista = (f"Pista del operador: {args.pista}. Búscala primero."
                 if args.pista else "")
        tarea = claude("triador", PROMPT_TRIAJE.format(
            base=args.base, commit=base_commit[:12], historial=historial,
            pista=pista), wt, ESQ_TRIAJE, agente="triador", solo_lectura=True, horas=0.75,
            esfuerzo="medium")
        if not tarea.get("hay_tarea"):
            reg(f"el triador no encuentra tarea: {tarea.get('motivo_descarte')}")
            return False
        reg(f"tarea: {tarea['titulo']}  [{tarea['rama']}]")
        # El triador no debería escribir nada; si lo hizo, fuera.
        sh(["git", "reset", "-q", "--hard"], cwd=wt)
        sh(["git", "clean", "-qfd"], cwd=wt)

        medidas = reg.dir / "medidas"
        medidas.mkdir(exist_ok=True)
        claude.medidas = medidas
        rama = tarea["rama"]
        if git("rev-parse", "--verify", "-q", f"refs/heads/{rama}", check=False):
            rama = f"{rama}_{datetime.now():%Y%m%d%H%M}"
        git("switch", "-q", "-c", rama, cwd=wt)
        tarea["rama"] = rama
        texto_tarea = json.dumps({k: v for k, v in tarea.items()
                                  if not k.startswith("_")},
                                 indent=1, ensure_ascii=False)

        sistema = (REPO / "tools/bucle/implementador.md").read_text()
        sesion, motivos, impl = None, None, None
        for n in range(1, args.intentos + 1):
            reg(f"intento {n}/{args.intentos}")
            prompt = (PROMPT_REINTENTO.format(n=n - 1, motivos=motivos) if sesion
                      else PROMPT_IMPL.format(
                          tarea=texto_tarea,
                          escenas=", ".join(tarea.get("escenas") or []) or "?",
                          criterio=tarea.get("criterio_aceptacion"),
                          medidas=medidas))
            impl = claude(f"implementador-{n}", prompt, wt, ESQ_IMPL,
                          sistema=sistema, reanudar=sesion, horas=3)
            sesion = impl["_session_id"]
            if impl["estado"] == "no_resuelto":
                reg(f"el implementador no lo resuelve: {impl['resumen'][:300]}")
                if git("status", "--porcelain", cwd=wt):
                    confirma(wt, impl)
                documenta(args, claude, guardia, estado, reg, wt, rama, tarea,
                          impl, base_commit, medidas, n)
                return True

            ok, informe = compuertas(wt, base_commit, impl, guardia, reg, n,
                                         tarea.get("criterio_aceptacion", ""), medidas)
            reg.guarda(f"compuertas-{n}.txt", informe)
            if not ok:
                reg("  compuertas: FALLO")
                motivos = informe
                continue
            reg("  compuertas: OK")
            confirma(wt, impl)
            cabeza = git("rev-parse", "HEAD", cwd=wt)

            rev = claude(f"revisor-{n}", PROMPT_REV.format(
                base=base_commit[:12], tarea=texto_tarea,
                impl=json.dumps({k: v for k, v in impl.items()
                                 if not k.startswith("_")},
                                indent=1, ensure_ascii=False),
                compuertas=informe, medidas=medidas), wt, ESQ_REV, agente="revisor",
                solo_lectura=True, horas=1)
            tocado = (git("rev-parse", "HEAD", cwd=wt) != cabeza
                      or git("status", "--porcelain", cwd=wt))
            if tocado:
                sh(["git", "reset", "-q", "--hard", cabeza], cwd=wt)
                sh(["git", "clean", "-qfd"], cwd=wt)
                reg("  el revisor ha tocado el árbol: su veredicto no vale")
                motivos = "El revisor modificó el árbol; se repite la revisión."
                continue
            reg(f"  revisor: {rev['veredicto']}")
            if rev["veredicto"] != "APRUEBA":
                motivos = "\n".join(f"- {m}" for m in rev["motivos"])
                continue

            if args.sin_mezclar:
                apunta(estado, tarea, "aprobada_sin_mezclar", rama_sin_mezclar=rama,
                       observaciones=rev["motivos"])
                reg(f"aprobada; la rama {rama} queda sin mezclar (--sin-mezclar)")
                return True
            if git("rev-parse", args.base) != base_commit:
                # La base se ha movido mientras tanto: lo medido ya no vale.
                motivos = None
                reg("la base se ha movido: se trae y se repiten las compuertas")
                nuevo = trae_base(args, wt, reg)
                if nuevo is None:
                    apunta(estado, tarea, "bloqueada", rama_sin_mezclar=rama,
                           motivo="conflicto con la base al mezclar")
                    return True
                base_commit = nuevo
                ok, informe = compuertas(wt, base_commit, impl, guardia, reg, n,
                                         tarea.get("criterio_aceptacion", ""), medidas)
                if not ok:
                    motivos = informe
                    continue
            trae_rama(wt, rama)
            err = mezcla(rama, args.base,
                         f"Merge branch '{rama}': {tarea['titulo']}", reg)
            if err:
                apunta(estado, tarea, "aprobada_sin_mezclar", rama_sin_mezclar=rama,
                       motivo=err)
                reg(f"aprobada pero sin mezclar: {err}")
                return False
            apunta(estado, tarea, "hecha", observaciones=rev["motivos"],
                   medidas=str(medidas))
            reg(f"MEZCLADA en {args.base}: {rama}")
            return True

        apunta(estado, tarea, "bloqueada", rama_sin_mezclar=rama,
               motivo=(motivos or "")[:2000])
        reg(f"bloqueada tras {args.intentos} intentos; rama {rama} sin mezclar")
        return True
    finally:
        # Lo que no se ha mezclado se conserva como rama del repositorio, para
        # que una persona pueda mirarlo; el clon se borra igual.
        if rama and git("rev-parse", "--verify", "-q", f"refs/heads/{rama}",
                        cwd=wt, check=False):
            trae_rama(wt, rama)
        borra_worktree(wt)


def documenta_ejecucion(args, claude: Claude, guardia: Path, estado: dict,
                        reg: Registro) -> None:
    """`--documentar <ejecución>`: pasa por `documenta` una tarea que quedó
    no resuelta antes de que existiera ese camino, o cuya documentación se ha
    corregido a mano en su rama."""
    viejo = ESTADO_DIR / "ejecuciones" / args.documentar
    tarea = (json.loads((viejo / "triador.json").read_text()) or {}).get("structured_output")
    impls = sorted(viejo.glob("implementador-*.json"),
                   key=lambda p: int(re.search(r"-(\d+)", p.stem).group(1)))
    impl = json.loads(impls[-1].read_text()).get("structured_output") if impls else None
    if not tarea or not impl or impl.get("estado") != "no_resuelto":
        raise RuntimeError(f"{viejo.name}: no es una tarea no resuelta")
    entrada = next((t for t in reversed(estado["tareas"])
                    if t.get("titulo") == tarea["titulo"] and t.get("rama_sin_mezclar")), None)
    rama = entrada["rama_sin_mezclar"] if entrada else tarea["rama"]
    tarea["rama"] = rama
    reg(f"tarea: {tarea['titulo']}  [{rama}]")
    reg("intento 1/1")
    wt = nuevo_worktree(f"tarea-{datetime.now():%Y%m%d-%H%M%S}", git("rev-parse", rama))
    try:
        git("switch", "-q", "-c", rama, cwd=wt)
        medidas = viejo / "medidas"
        claude.medidas = medidas
        reg(f"el implementador no lo resuelve: {impl['resumen'][:300]}")
        base = git("merge-base", rama, args.base)
        documenta(args, claude, guardia, estado, reg, wt, rama, tarea, impl,
                  base, medidas, int(re.search(r"-(\d+)", impls[-1].stem).group(1)))
    finally:
        trae_rama(wt, rama)
        borra_worktree(wt)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="main")
    ap.add_argument("--tareas", type=int, default=1)
    ap.add_argument("--intentos", type=int, default=3)
    ap.add_argument("--pista")
    ap.add_argument("--modelo", help="alias o id del modelo; por defecto el de Claude Code")
    ap.add_argument("--presupuesto", type=float, default=25.0,
                    help="USD máximos por sesión")
    ap.add_argument("--sin-mezclar", action="store_true")
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("--documentar", metavar="EJECUCION",
                    help="revisar y mezclar como documentación una tarea no resuelta "
                         "(el nombre de su carpeta en ejecuciones/)")
    args = ap.parse_args()

    if args.estado:
        for t in carga_estado()["tareas"]:
            print(f"{t['fecha']}  {t['resultado']:22} {t['titulo']}  "
                  f"[{t.get('rama_sin_mezclar') or t.get('rama')}]")
        return 0

    reg = Registro(ESTADO_DIR / "ejecuciones" / f"{datetime.now():%Y%m%d-%H%M%S}")
    try:
        with Cerrojo(CACHE / "orquestador.lock", bloqueante=False):
            guardia = instala_guardia()
            claude = Claude(args, guardia, reg)
            estado = carga_estado()
            reg(f"bucle sobre {args.base} ({git('rev-parse', '--short', args.base)}), "
                f"{args.tareas} tarea(s), registros en {reg.dir}")
            if args.documentar:
                try:
                    documenta_ejecucion(args, claude, guardia, estado, reg)
                except Exception as e:                       # noqa: BLE001
                    reg(f"ERROR: {type(e).__name__}: {e}")
                args.tareas = 0
            for i in range(args.tareas):
                try:
                    if not una_tarea(args, claude, guardia, estado, reg):
                        break
                except Exception as e:                       # noqa: BLE001
                    reg(f"ERROR: {type(e).__name__}: {e}")
                    break
                args.pista = None       # la pista vale para la primera
            reg(f"fin; coste total ${claude.coste:.2f}")
    except BlockingIOError:
        print("ya hay un orquestador en marcha", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
