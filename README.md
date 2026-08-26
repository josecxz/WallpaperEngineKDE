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
- **No dibuja lo que no se ve**: mide cuánta pantalla tapan las ventanas y para
  el motor cuando no queda fondo a la vista —también con dos ventanas en
  mosaico, donde ninguna está maximizada (98,2 % → 0,1 % de la GPU)—. Al
  destapar sigue donde estaba.

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

### Los shaders son de Wallpaper Engine, no de este repositorio

Aquí no hay ni un shader, y no va a haberlo. Los que ejecuta el motor salen
siempre de tu propia instalación, y tienen dos dueños distintos:

- **La librería común de Wallpaper Engine**, en `$WE_ASSETS/shaders`: 106
  ficheros `.vert`/`.frag` más 12 cabeceras `common_*.h` y las dos de `base/`.
  De ahí salen los `#include "common_vertex.h"`, `"common_fragment.h"` o
  `"base/model_vertex_v1.h"` que casi todas las escenas piden. Son propiedad de
  Wallpaper Engine.
- **Los shaders de cada escena**, dentro de su `scene.pkg`, propiedad de quien
  firmó ese wallpaper.

Al preparar un fondo, `tools/weshader.py` los lee de esos dos sitios y resuelve
los `#include` buscando **primero en el paquete de la escena y luego en la
librería común**: un wallpaper puede traer su versión de una cabecera y gana
sobre la compartida. Lo que aporta este proyecto es el traductor a GLSL, no el
material que traduce.

La consecuencia práctica es que **Wallpaper Engine tiene que estar ya instalado
en el PC**, con sus assets en disco. Sin ellos no hay nada que traducir y el
proceso corta antes de empezar:

```
$ python3 tools/wepaths.py
assets    no se encontro los assets de Wallpaper Engine.
Define WE_ASSETS con la ruta, por ejemplo:
  export WE_ASSETS=/ruta/a/steam_library/steamapps/common/wallpaper_engine/assets
```

Copiar los shaders sueltos de otro sitio tampoco vale: cada escena espera las
cabeceras de la versión de la librería con la que se publicó, y un `#include`
sin resolver tumba el pase entero. Y el GLSL que acaba en el plan de render es
una traducción de ese material, así que hereda su propiedad: se queda en
`plugin/contents/scene/` de tu máquina y no es redistribuible.

## Uso

```sh
wectl list [texto]      lista tus wallpapers; el * marca el preparado
wectl set <id|texto>    prepara uno y lo pone en el escritorio
wectl shuffle           pone uno al azar de toda la biblioteca
wectl shuffletime <t>    ajusta cada cuánto rota, sin cambiar el fondo
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

### Cambiar de fondo solo

```
$ wectl shuffle --cada 30m
al azar: Cyberpunk Fantasy  (2396319149)
quedan 124 de 125 antes de repetir
rotación activada: otro cada 30 min
```

`--cada` acepta `90s`, `30m`, `2h` o `1d` —un número suelto son minutos— e
instala un temporizador de usuario de systemd que sigue funcionando tras
reiniciar. `wectl shuffle --parar` lo apaga y `wectl status` dice cuánto queda
para el próximo.

Para cambiar solo la cadencia sin llevarte por delante el fondo que estás
mirando, `wectl shuffletime 10m`. El plazo lo cuenta systemd desde el último cambio,
así que al acortarlo puede tocar uno enseguida; el comando dice lo que va a
pasar de verdad.

**El mínimo es 1 minuto**, y no es arbitrario: preparar un wallpaper cuesta
desde 0,4 s hasta 18,2 s en esta biblioteca —el peor es uno de 65 pases y 196
assets que escribe 369 MB de plan—, así que un cambio completo se va a unos 20
s. Un minuto deja un factor 3 de margen para que un cambio no empiece con el
anterior a medias.

No es un sorteo cada vez: las escenas se reparten en una bolsa, así que **salen
todas antes de repetirse ninguna**. Si una no se deja preparar, pasa a la
siguiente en vez de dejarte sin cambio.

También se puede elegir desde *Clic derecho en el escritorio → Configurar
escritorio → Tipo de fondo: WallpaperEngine*.

### Cuando la escena no tiene la forma de tu pantalla

Casi ninguna la tiene: **la gran mayoría de las escenas están hechas en
16:9**, así que en un panel 16:10 se recorta el 10% del ancho, y una escena
vertical sobre uno horizontal pierde dos tercios. En la configuración del fondo
se elige qué hacer:

- **Cubrir** (por defecto): llena la pantalla y recorta lo que sobra.
- **Ver la escena entera**: se ve completa, con barras del color de fondo.
- **Estirar**: llena la pantalla deformando la escena.

Con *acercamiento* y los dos *recortes* se decide qué trozo se ve. Los recortes
se apagan cuando no hay nada que elegir: una escena más ancha que la pantalla se
recorta a lo ancho y ya se ve entera a lo alto.

Y el fondo se dibuja **a la resolución que vas a ver**, no al lienzo del autor.
El 72% de las escenas de esta biblioteca traen más píxeles de los que caben en
el panel —cuatro de ellas son de 7680x4320, que son 33 millones de puntos para
enseñar 2,3—. Dibujar solo los que se ven cuesta bastante menos, medido con el
mismo plan en la gráfica integrada:

```
Sci-Fi Cyber City, 75 pases, lienzo 4K   99,9 ms -> 36,3 ms por fotograma
la escena de 8K                          85,0 ms -> 12,2 ms
```

La imagen es la misma: de las 129 escenas renderizadas a las dos resoluciones,
128 difieren menos de un 2%. No hay nada que configurar; si no se puede
averiguar el tamaño de la pantalla, se dibuja al lienzo del autor como antes.

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
(50 pases, 12 mallas animadas) a la tasa de refresco del monitor. Los shaders
de las 129 escenas compilan **y enlazan**: los 3638 pares que salen de generar
sus planes, en las dos tarjetas de esta máquina. Hasta hace poco 82 de esos
pases se caían al enlazar —lo que tiene que casar ahí es la interfaz entre el
vértice y el fragmento— y su capa desaparecía sin un solo error.

Las superficies con mapa de normales y reflejo activado reflejan lo que hay
detrás, leyéndolo del fotograma ya compuesto con la nitidez que le toque a su
rugosidad. Son 7 pases en 3 escenas de esta biblioteca, y se nota sobre todo
donde el relieve es marcado.

Limitaciones conocidas:

- Las capas cuya textura es un **vídeo** se ven congeladas en su primer
  fotograma, no reproducidas. Son 3 escenas de 129.
- El parallax por mapa de profundidad se dibuja en reposo: el motor todavía no
  sabe dónde está el puntero, así que la escena se ve centrada.
- Luces puntuales y de tubo sí; focos y direccionales no, y una escena que
  traiga alguna se dibuja plana entera —iluminar a medias la deja más oscura
  que no iluminarla—.
- Las partículas se simulan (821 de los 823 sistemas del corpus), estelas
  incluidas, y con el vocabulario del formato cubierto entero. Los operadores
  que siguen al cursor quedan inactivos hasta que el motor sepa dónde está el
  puntero.
- Sin audio reactivo.

## Aviso

Este proyecto no distribuye contenido de Wallpaper Engine: ni shaders, ni
texturas, ni escenas. Lee los assets de tu propia instalación —ver
[Los shaders son de Wallpaper Engine](#los-shaders-son-de-wallpaper-engine-no-de-este-repositorio)—
y los wallpapers son propiedad de sus autores. Es una
implementación independiente, sin relación con Wallpaper Engine ni Kristjan
Skutta.
