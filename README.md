# WallpaperEngine

Fondos de escritorio animados para **KDE Plasma 6 / Wayland**, capaces de
ejecutar escenas de [Wallpaper Engine](https://store.steampowered.com/app/431960/)
de forma nativa.

No es un reproductor de vídeo ni un envoltorio: lee el `scene.pkg` original,
decodifica sus texturas, traduce sus shaders a GLSL y ejecuta el grafo de
render completo con OpenGL, dentro del propio plasmashell.

```
SceneView: backend OpenGL, plan con 50 pases, lienzo 2560x1440,
           mallas 12 subidas / 12 pases las piden / 12 animadas
```

## Qué hace

- **Escenas de Wallpaper Engine** con sus capas, efectos y shaders originales.
- **Animación por huesos** (*puppet warp*): personajes que respiran, telas que
  ondean, parpadeos.
- **Integrado en Plasma** como plugin de fondo: respeta el z-order, la
  opacidad y los iconos del escritorio.
- **Sin reiniciar nada**: cambiar de fondo, pararlo o arrancarlo es inmediato.
- **No dibuja lo que no se ve**: con una ventana maximizada delante el motor se
  para (98,4 % → 0,0 % de la GPU) y al volver sigue donde estaba.

No soporta wallpapers de tipo vídeo ni web, ni audio reactivo.

## Instalación

Requiere Qt 6, OpenGL, Python 3 con NumPy y Pillow, y una instalación de
Wallpaper Engine (por Steam o Proton) de la que leer los assets.

```sh
make build && make install
ln -s "$PWD/tools/wectl.py" ~/.local/bin/wectl
```

El motor necesita saber dónde está tu biblioteca. Normalmente la encuentra
sola; si no, díselo una vez:

```fish
set -Ux WE_ASSETS   /ruta/steam_library/steamapps/common/wallpaper_engine/assets
set -Ux WE_WORKSHOP /ruta/steam_library/steamapps/workshop/content/431960
```

`python3 tools/wepaths.py` dice qué ha encontrado o qué le falta.

## Uso

```sh
wectl list [texto]      lista tus wallpapers; el * marca el preparado
wectl set <id|texto>    prepara uno y lo pone en el escritorio
wectl start / stop      activa o para el motor
wectl status            qué hay puesto y cómo va
```

```
$ wectl set jeanne
preparando: Jeanne d'Arc | Fate Series  (2788165557)
  pases: 23
  canvas: (3840, 2160)
puesto en el escritorio: Jeanne d'Arc | Fate Series
```

`set` acepta el id de Workshop o parte del título, sin distinguir mayúsculas
ni acentos. Si el texto es ambiguo, lista los candidatos.

También se puede elegir desde *Clic derecho en el escritorio → Configurar
escritorio → Tipo de fondo: WallpaperEngine*.

## Cómo funciona

El trabajo se reparte en dos mitades, y esa separación es la decisión de
diseño central del proyecto:

**Python decide.** `tools/` lee el contenedor, decodifica texturas, traduce
shaders, resuelve el grafo de la escena y hornea las animaciones. El resultado
es un **plan de render**: un fichero de texto con la lista de pases, sus
uniforms ya resueltos y las mallas ya deformadas.

**C++ ejecuta.** `src/` carga ese plan una vez y lo repite cada fotograma. No
parsea nada, no reserva memoria, no busca por nombre. Solo enlaza y dibuja.

La única excepción son las partículas, que llevan estado propio y hay que
integrarlas en cada fotograma. Ahí el reparto se mantiene igual —Python resuelve
el sistema a números en un fichero `.psys`— y la simulación vive en un `.c`
**compartido por los dos ejecutores**, para que no puedan divergir.

La ventaja práctica es que casi todo se puede depurar sin tocar el escritorio:
`tools/werender.py` ejecuta el mismo plan headless y vuelca un PNG.

```
scene.pkg ─┬─ pkg_inspect ─ contenedor
           ├─ wetex ─────── texturas
           ├─ weshader ──── shaders → GLSL
           ├─ wemdl ─────── mallas y huesos
           ├─ weparticles ─ sistemas de partículas
           └─ wescene ───── grafo de la escena
                              ↓
                         plan de render
                              ↓
                   glexec (offline)  /  glexecutor (en vivo)
                              └── src/weparticles.c ──┘
                                  (el mismo simulador en los dos)
```

## Estructura

```
src/          motor C++: plugin QML de Plasma y ejecutor OpenGL
tools/        herramientas Python: formatos, plan y CLI
plugin/       paquete de fondo de Plasma (KPackage)
NOTAS.md      documentación técnica de los formatos
```

## Estado

Funciona sobre escenas reales de la biblioteca, incluidas algunas complejas
(50 pases, 12 mallas animadas) a la tasa de refresco del monitor.

Limitaciones conocidas:

- 1 de 578 variantes de shader no llegan a compilar en el driver y su pase se
  omite. Normalmente cuesta una capa, pero si la que cae es la capa base se
  lleva todo lo que colgaba de ella.
- Sin sistema de iluminación: los materiales con luces se dibujan planos.
- Las partículas se simulan (821 de los 823 sistemas del corpus), estelas
  incluidas. Los operadores que siguen al cursor quedan inactivos.
- Sin audio reactivo.

## Aviso

Este proyecto no distribuye contenido de Wallpaper Engine. Lee los assets de
tu propia instalación, y los wallpapers son propiedad de sus autores. Es una
implementación independiente, sin relación con Wallpaper Engine ni Kristjan
Skutta.
