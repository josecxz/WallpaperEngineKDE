# WallpaperEngine

Motor que ejecuta escenas de **Wallpaper Engine** de forma nativa como fondo de
KDE Plasma 6 / Wayland: lee el `scene.pkg` original, decodifica sus texturas,
traduce sus shaders a GLSL y ejecuta el grafo de render con OpenGL dentro de
plasmashell. No es un envoltorio: donde una capa **es** un vídeo lo decodifica
y lo reproduce, pero eso es una capa más dentro del grafo, no lo que hace.

- Qué hace y cómo se instala → `README.md`
- **Por qué** cada cosa es como es → `NOTAS.md` (3912 líneas, 136 secciones en
  orden cronológico). **No lo leas entero.** `NOTAS-INDICE.md` dice qué sección
  resuelve qué problema y en qué línea empieza; se lee el trozo con
  `sed -n '<línea>,+40p' NOTAS.md`. Tras editar NOTAS.md, `make indice`.

## Reglas que cuestan caro si se saltan

1. **Nada específico de un wallpaper.** Ni un caso especial por id de escena,
   por nombre de capa, ni un campo descartado porque «en esta escena estorba».
   Si no se entiende un caso, se deja escrito y no se toca. (`NOTAS.md:10`)
2. **El corpus son 129 escenas**, las de la instalación real de Steam que
   localiza `tools/wepaths.py`. Todo arreglo se mide sobre las 129, no sobre la
   que falla. Las cuentas «de 125» en NOTAS son de la biblioteca anterior.
3. **No iterar sobre plasmashell en vivo.** Recargar en bucle deja el
   escritorio caído (`start-limit-hit` de systemd, que parece un fallo del
   motor). Se itera con el renderizador offline y solo al final `make reload`.
4. **Las capturas de pantalla y `grabToImage` mienten**: dan falsos negativos.
   Lo que decide es `tools/test_luminancia.py`, que renderiza y mide la luz.
5. **Los dos ejecutores no usan el mismo driver.** El escritorio corre sobre
   **Mesa**; aquí el ICD por defecto es **NVIDIA** (`10_nvidia.json` va antes
   que `50_mesa.json`). Los tests de shader ya lo fuerzan con
   `__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json`;
   `werender.py` y `test_luminancia.py` **no**. Comparar los dos ejecutores sin
   igualar el driver inventa fallos que no existen.
6. **`plasmashell` cambia la locale.** Qt hace `setlocale(LC_ALL, "")` y este
   escritorio es `es_ES`: `strtof` en C lee `0.5` como `0`. Ninguna prueba
   offline lo ve, porque fuera de plasmashell la locale es `C`. (`NOTAS.md:970`)
7. **Instalar con `mv`, nunca con `cp`.** `cp` reescribe el inodo que
   plasmashell tiene mapeado y lo mata con `SIGBUS`. `make install` ya lo hace
   bien; no lo esquives copiando el `.so` a mano.

## La cadena

```
scene.pkg ──pkg_inspect──┬─ .tex  ──wetex────┐  (IS_VIDEO: el MP4 va tal cual)
                         ├─ .mdl  ──wemdl────┤
                         ├─ shader─weshader──┤  (weglsl: inferencia de tipos)
                         └─ scene.json─wescene┤  (grafo -> pases + recursos)
                                              ├─ weparticles ─> .psys
                                              ├─ wetext ─> atlas + quads
                                              │  (wescript: el reloj del script)
                                              ▼
                                     werender.py  (el hub: decide y resuelve)
                                              │
                                    plan.txt (con @TIME@)
                                    ┌─────────┴─────────┐
                            glexec.c (offline)   glexecutor.cpp (en vivo)
                                    ├──── src/weparticles.c ────┤  (compartidos)
                                    ├──── src/wevideo.c ────────┤
                                    └──── src/wereloj.c ────────┘
```

Un wallpaper de **tipo vídeo** (15 en la biblioteca) no pasa por el grafo: es un
MP4 y su plan lo escribe `plan_de_video()` directo —`canvas`, `video`, un
`object` y un pase con un quad—. `emit_plan` despacha solo, así que `wectl` no
tiene que saber de qué tipo es lo que pone.

`werender.py` (2589 líneas) es donde vive **lo que hay que decidir**: binding de
propiedades, uniforms del motor, resolución de bindings. Los ejecutores solo
ejecutan un plan ya resuelto. La implementación de referencia está en Python a
propósito; `src/` es el port a C++ de lo mismo.

**Regla de oro del reparto:** `glexec.c` y `glexecutor.cpp` enlazan **los
mismos** `src/weparticles.c`, `src/wevideo.c` y `src/wereloj.c`. Si tocas la
simulación, la decodificación de vídeo o la disposición de un reloj, tocas los
dos a la vez o divergen.

## Dónde vive cada cosa

| Archivo | Qué posee |
|---|---|
| `tools/wepaths.py` | localiza los assets de WE y el Workshop de Steam |
| `tools/pkg_inspect.py` | contenedor `scene.pkg` |
| `tools/wetex.py` | formato `.tex`: LZ4, DXT, mipmaps, sprite sheets, `IS_VIDEO` |
| `tools/wemdl.py` | mallas puppet `.mdl`: geometría, `MDLS` esqueleto, `MDAT` anclajes, `MDLA` animación |
| `tools/weshader.py` | dialecto de WE → GLSL: `#include`, `[COMBO]`, metadatos, restos de HLSL |
| `tools/weglsl.py` | inferencia de tipo y ancho sobre expresiones (para truncar como HLSL) |
| `tools/wescene.py` | grafo de escena → plan de pases; `AssetResolver`; visibilidad |
| `tools/weparticles.py` | sistemas de partículas → `.psys` (números ya resueltos) |
| `tools/wetext.py` | capas de texto → atlas de glifos + quads |
| `tools/wescript.py` | el JavaScript de una capa de texto → plantilla de reloj |
| `tools/wevideo.py` | cabecera MP4 (`tkhd`) y cómo encaja el vídeo en la pantalla |
| `tools/werender.py` | **el hub**: une todo, `--emit-plan`, renderiza a PNG |
| `src/sceneview.cpp` | `QQuickRhiItem`; `synchronize()` es el único punto sin carrera |
| `src/glexecutor.cpp` | ejecutor en vivo (port de `glexec.c`) |
| `src/escritorio.cpp` | le pregunta a KWin cuánta pantalla tapan las ventanas |
| `src/weparticles.c` | simulador, **compartido** por los dos ejecutores |
| `src/wevideo.c` | decodificador libav, **compartido** por los dos ejecutores |
| `src/wereloj.c` | rehace los quads de un reloj, **compartido** por los dos |
| `tools/wectl.py` | CLI de uso diario (`list`/`set`/`shuffle`/`start`/`stop`/`status`) |

## Comandos

`make build` y `make glexec` necesitan `libavformat`, `libavcodec`, `libavutil`
y `libswscale` (los `-devel`/`-dev` de ffmpeg): ahí vive la decodificación de
vídeo.

```sh
make build                     # modulo QML -> obj/libwallpaperenginerender.so
make install                   # + symlink del paquete + environment.d
make reload                    # reinstala TODO y reinicia plasmashell
make status                    # enlace, entorno y plugin activo
make glexec                    # obj/glexec  (ejecutor offline)
make psysprobe                 # obj/psysprobe (resume un .psys sin dibujarlo)
cc -O2 -o obj/glslcheck tools/glslcheck.c -lEGL -lGLESv2   # no hay target
make indice                    # recalcula las líneas de NOTAS-INDICE.md
```

Render offline de una escena (el bucle de iteración normal):

```sh
python3 tools/werender.py <dir_wallpaper> salida.png \
        [--time 0.0] [--frames N] [--pantalla 1920x1200] [--only-base] [--keep]
make plan WALLPAPER=<ruta>     # deja plan.txt en plugin/contents/scene/
```

## Qué prueba cada test, y qué oráculo usa

| Test | Oráculo |
|---|---|
| `test_wetex.py` / `test_wemdl.py` | decodifican toda la biblioteca sin error |
| `test_weglsl.py <dir> obj/glslcheck` | el corpus que **ya compila**: valida la inferencia sin tocar el traductor |
| `test_weshader.py $WE_ASSETS/shaders obj/glslcheck` | el driver real compila las variantes por defecto |
| `test_wescene.py obj/glslcheck` | end-to-end con los combos reales (~594 variantes); llama a `glslcheck --link`, así que comprueba enlace y no solo compilación |
| `test_werender.py` | matrices y luces que el plan pasa a un pase iluminado |
| `test_weparticles.py` | el contrato entre `weparticles.py` y `src/weparticles.c`, locale incluida |
| `test_wetext.py` | la unidad del punto, la caja y los quads, medidos contra el corpus |
| `test_wereloj.py` | el contrato entre `wetext`/`wescript` y `src/wereloj.c`, locale incluida |
| `test_wevideo.py` | `ffprobe` para las dimensiones y `ffmpeg` para los píxeles, sobre los 18 vídeos del corpus |
| `test_luminancia.py obj/glexec` | **el que decide**: renderiza y mide la luz. `--guardar luz.json` / `--referencia luz.json` caza regresiones |

`test_wescene` y `test_weshader` tardan; van con `timeout 1800`.

## Qué no soporta

Wallpapers de tipo web, audio (ni el reactivo ni la pista de los vídeos),
modelos 3D, focos y luces direccionales. El **bloom** sí, con la cadena LDR de
WE (`werender.py`, `_emit_bloom`); el camino HDR de nueve escenas usa esa misma
cadena porque no hay buffers en coma flotante. El vídeo se reproduce, pero
**solo por CPU**: no hay VAAPI ni NVDEC. De las 148 capas de texto con
JavaScript, 123 dan la hora en vivo (`tools/wescript.py` interpreta el script
y deduce la plantilla) y 25 se quedan con el texto literal: las que usan
`engine`, `import` o expresiones regulares, y las que no son un reloj.
