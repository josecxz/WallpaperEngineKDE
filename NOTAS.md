# Notas técnicas — WallpaperEngine

Documentación detallada de los formatos de Wallpaper Engine tal como se han ido
descifrando, con las medidas que sostienen cada decisión y las hipótesis que se
probaron y descartaron. Es material de referencia para trabajar sobre el motor;
para empezar, ver [README.md](README.md).

Motor de animaciones para el escritorio, KDE Plasma 6 / Wayland.

## Estado

**El motor corre en vivo dentro de plasmashell**, partículas incluidas. Una
escena real de Wallpaper Engine se ejecuta con OpenGL sobre una textura que Qt
compone en su scene graph, detrás de los iconos del escritorio. Verificado en
Plasma 6.7.3 / Wayland: primero *LoL Warwick* con 24 pases a 166 fps, y ahora
*Sentinel Irelia* con 102 pases y 4 sistemas de partículas.

```
SceneView: backend OpenGL, plan con 102 pases, lienzo 2560x1440, init 119 ms,
uniforms 311 activos / 1376 descartados, mallas 12 subidas / 12 pases las
piden / 12 animadas, particulas 4 sistemas / 0 piezas sin soporte
SceneView: destino=17 tam=1920x1200 glError=0x0 compo_medio=85.7 targets=13
```

### El motor en C++ — `src/`

`SceneView` es un `QQuickRhiItem`: Qt le da una textura propia y la compone
como un nodo más, así que el z-order, la opacidad y el redimensionado siguen
funcionando solos.

**La restricción que define el diseño:** QRhi no acepta GLSL en texto, quiere
shaders horneados con `qsb` en tiempo de compilación. Nuestros shaders se
generan **en ejecución** —hasta leer el `scene.json` no se sabe qué combos
pide cada pase—, así que la ruta normal de QRhi no sirve. La salida es
`QRhiCommandBuffer::beginExternal()` / `endExternal()`, que permite emitir
llamadas nativas de OpenGL dentro del pase. Por eso `glexec.c` se reaprovecha
casi entero como `src/glexecutor.cpp`.

Dos consecuencias: el backend de RHI **tiene que ser OpenGL** (se comprueba
en `render()` y se avisa si no), y hay que enlazar contra API versionada
(`/usr/include/qt6/QtGui/<version>/QtGui/rhi/`), sin garantía de
compatibilidad entre versiones menores de Qt.

Notas de C++ tras revisión:

- `GlExecutor` posee handles de GL y los libera en el destructor: copia y
  movimiento están **borrados** (regla de cinco). Sin eso, una copia accidental
  provocaba doble destrucción.
- El destructor **comprueba que haya contexto GL activo** antes de llamar a
  `glDelete*`; sin contexto avisa y deja que el driver recupere los handles al
  cerrar, en vez de incurrir en comportamiento indefinido.
- Los punteros de error son opcionales de verdad (`= nullptr` y comprobados).
- La cabecera no falsifica los tipos de GL: usa `GlName`/`GlLocation` en vez de
  declarar `GLuint`/`GLint` en el ámbito global de un fichero que no incluye GL.
- Índices de contenedor en `qsizetype`, no `int`.
- `planSource` es `QUrl`, que es lo que QML entrega con `Qt.resolvedUrl()`;
  antes era `QString` y había que recortar `file://` a mano.
- Los slots que usa el hilo de render son privados: siguen siendo invocables
  por nombre y no ensucian la API que ve QML.
- Los logs del compilador se leen con su longitud real en vez de truncarse en
  un `char[4096]`.

Tres cosas que costaron:

- **Escribir en el framebuffer de Qt, no en uno propio.** El primer intento
  envolvía `colorTexture()` en un FBO nuestro; el área del item salía negra
  aunque `glGetError()` no reportara nada. Abrir el pase de Qt
  (`beginPass`) y consultar `GL_DRAW_FRAMEBUFFER_BINDING` dentro de
  `beginExternal()` funciona y no asume nada sobre cómo Qt monta el target.
- **Instalar con `mv`, nunca con `cp`.** plasmashell moría con
  `SIGBUS / BUS_ADRERR` y la traza apuntaba a nuestro `.so`, lo que parecía un
  problema de ciclo de vida en Qt. No lo era: `cp` trunca y reescribe **el
  mismo inodo**, y plasmashell tiene esa biblioteca mapeada en memoria; sus
  páginas de código quedan inválidas y el proceso muere en cuanto vuelve a
  ejecutar cualquier cosa de ella. Instalar en un temporal y renombrar deja el
  inodo viejo vivo mientras alguien lo tenga mapeado. (`-Wl,-z,nodelete` está
  puesto porque es buena práctica en un plugin QML, pero no fue lo que
  arregló esto.)
- **`Q_ARG` guarda un puntero, no una copia.** En Qt 6 la macro expande a
  `std::addressof(value)`. Pasarle el temporal que devuelve un getter
  (`Q_ARG(QString, m_exec.title())`) deja el evento en cola apuntando a
  memoria muerta; la cadena llega con puntero nulo y longitud no nula y Qt
  aborta con `ASSERT: "str || !len"` en `qstringview.h`. Hay que ligar el
  valor a una variable con nombre antes.
- **Dependencias de cabecera automáticas (`-MMD -MP`).** Declararlas a mano
  era incompleto: `moc_sceneview.o` no dependía de `glexecutor.h` aunque lo
  incluye vía `sceneview.h`. Una compilación incremental podía enlazar
  objetos que veían layouts distintos de la misma clase — fallos que
  desaparecen tras un `make clean` y por eso cuestan mucho de diagnosticar.
- **`synchronize()` es obligatorio.** El render corre en otro hilo; es el
  único punto en que ambos están parados. El estado del item se copia ahí, y
  el estado hacia QML se manda con `invokeMethod(..., QueuedConnection)`.

La construcción del plan sigue en Python: `tools/werender.py --emit-plan`
resuelve el grafo, traduce los shaders y decodifica las texturas una vez, y
deja un plan-plantilla con `@TIME@` sin sustituir. El ejecutor de C++ lo
repite cada fotograma poniendo el tiempo del `FrameAnimation`.

```sh
sudo pacman -S cmake        # NO hace falta: se compila con make + moc
make build && make install
```

### El CLI — `tools/wectl.py`

El uso diario no pasa por `make`:

```sh
wectl list [texto]      lista la biblioteca; el * marca la escena preparada
wectl set <id|texto>    prepara un wallpaper y lo pone en el escritorio
wectl start / stop      activa o para el motor
wectl status            que hay puesto y como va
```

`set` acepta el id de Workshop o parte del título, sin distinguir mayúsculas
ni acentos; si el texto es ambiguo lista los candidatos en vez de elegir por
su cuenta.

Todo pasa por la **API de scripting de Plasma via D-Bus**, que aplica el
cambio en caliente. Es la diferencia con `make reload`, que reinicia
plasmashell entero: ahí se pierden las ventanas de un vistazo, tarda segundos
y —probando varios wallpapers seguidos— agota el límite de arranques de
systemd y deja el escritorio caído. Con D-Bus el PID de plasmashell no cambia.

Cambiar el fichero del plan no basta para que Plasma lo relea: no lo vigila, y
volver a poner el mismo plugin tampoco dispara nada. `wectl set` sale al
plugin de imagen y vuelve, que es lo que fuerza la recarga.

```sh
ln -s "$PWD/tools/wectl.py" ~/.local/bin/wectl    # para tenerlo en el PATH
```

### Dónde está Wallpaper Engine

Las herramientas de `tools/` necesitan los assets de WE y el contenido de
Workshop. `tools/wepaths.py` los busca en este orden: las variables
`WE_ASSETS` / `WE_WORKSHOP`, luego las bibliotecas declaradas en
`libraryfolders.vdf`, y por último las ubicaciones habituales de Steam
(incluido el flatpak).

La detección automática **no siempre basta**: una instalación copiada a mano
puede no figurar en `libraryfolders.vdf`, que es el caso de la máquina donde
se desarrolló esto. En ese caso hay que definirlas:

```fish
set -Ux WE_ASSETS   /ruta/steam_library/steamapps/common/wallpaper_engine/assets
set -Ux WE_WORKSHOP /ruta/steam_library/steamapps/workshop/content/431960
```

`python3 tools/wepaths.py` imprime lo que ha encontrado, o qué variable falta.
`make plan` sin `WALLPAPER` lista los wallpapers disponibles.

Nota: `make install` deja el módulo QML en `~/.local/lib/qt6/qml`, que Qt no
escanea por defecto. Sin `QML_IMPORT_PATH` plasmashell carga el fondo, falla
el `import` y se queda en negro con un `module … is not installed` en el
journal como único rastro. Por eso `make install-env` (incluido en `install`)
escribe `~/.config/environment.d/50-wallpaperengine.conf`, que el gestor de
usuario de systemd lee al iniciar sesión.

Ese fichero **es la instalación permanente**: sobrevive a reinicios. Añade la
ruta con la forma `${QML_IMPORT_PATH:+:${QML_IMPORT_PATH}}`, que respeta un
valor previo y no deja un separador suelto cuando no lo hay. Pero systemd solo
lo lee al iniciar sesión, así que `make reload` inyecta además la variable en
el gestor ya arrancado con `systemctl --user set-environment` para no tener que
cerrar sesión.

Se aprendió por las malas: tras reiniciar la máquina el fondo desapareció, y
la causa no fue el motor sino que `set-environment` solo vive en la sesión.

### Hito 0 (completado)

Pintó un color sólido detrás de los iconos del escritorio, con un reloj de
frames sincronizado al refresco de la pantalla.

Verificado en Plasma 6.7.3 / KWin 6.7.3 (Wayland), eDP-1 @ 1920x1200 165 Hz:

```
superficie   : 1920x1200 lógicos
dpr          : 1.00
fps (suave)  : 167.0
fps (crudo)  : 165.9      <- enganchado al panel de 165 Hz
```

## Decisión de arquitectura: por qué un plugin QML y no layer-shell

Se probaron empíricamente las dos rutas viables en Wayland.

**`wlr-layer-shell-unstable-v1`, capa `background` — DESCARTADA.**
KWin implementa el protocolo y acepta la superficie sin error (`swaybg`
registra `Found config * for output eDP-1` y no falla), pero el *desktop
containment* de plasmashell es opaco y se dibuja por encima. Medido:

| | color en pantalla |
|---|---|
| antes de `swaybg -c '#FF00FF'` | RGB(44, 47, 48) |
| después | RGB(45, 48, 49) |

Cero magenta: la superficie existe pero queda tapada. Esta ruta sirve para
Hyprland / Sway / Niri, no para KDE.

**Plugin de wallpaper de Plasma (QML) — ELEGIDA.**
Da gratis el z-order correcto, multimonitor, hotplug, escalado fraccional,
la UI de configuración integrada en Ajustes del Sistema, y —crítico para
el parallax del hito 6— eventos de ratón, que una layer surface de fondo
no puede recibir sin robarle los clics al escritorio.

Consecuencia de diseño: el núcleo del motor debe quedar agnóstico de la
capa de presentación, con backends finos por escritorio. Hoy solo existe
el de Plasma.

## Estructura

```
plugin/
  metadata.json              paquete KPackage (Plasma/Wallpaper)
  contents/
    ui/main.qml              el render
    media/warwick.mp4        bucle pre-renderizado de la escena de referencia
    ui/config.qml            UI de configuración (propiedades cfg_*)
    config/main.xml          esquema KConfigXT
tools/
  pkg_inspect.py             lector del contenedor scene.pkg
  wetex.py                   decodificador del formato .tex
  weshader.py                traductor del dialecto de shader a GLSL
  weglsl.py                  inferencia de tipo y ancho sobre expresiones GLSL
  wemdl.py                   decodificador de mallas .mdl
  wescene.py                 grafo de escena -> plan de render
  weparticles.py             sistemas de partículas -> fichero .psys
  werender.py                renderizador offline (escena -> PNG)
  glexec.c                   ejecutor de planes headless (EGL surfaceless)
  glslcheck.c                compila shaders con el driver real (EGL surfaceless)
  test_wetex.py              regresión de wetex
  test_wemdl.py              regresión del decodificador de mallas
  test_weglsl.py             valida la inferencia contra el corpus que compila
  test_weshader.py           regresión del traductor (combos por defecto)
  test_wescene.py            regresión end-to-end (combos reales)
  test_weparticles.py        contrato entre weparticles.py y weparticles.c
src/
  glexecutor.cpp/.h          ejecutor de planes en vivo (port de glexec.c)
  weparticles.c/.h           simulador de partículas, COMPARTIDO por los dos
  sceneview.cpp/.h           QQuickRhiItem que compone la escena
  plugin.cpp, qmldir         registro del módulo QML
```

## Formatos de Wallpaper Engine

Implementación de referencia en `tools/`, en Python a propósito: fijar un
formato desconocido pide iteración rápida y verificación visual. Es la
especificación ejecutable a portar a C++ para el motor.

### `scene.pkg` — `tools/pkg_inspect.py`

```
u32 len + char[len]    version, "PKGV0016"
u32                    numero de entradas
por entrada: u32 len + char[len] ruta, u32 offset, u32 size
...blobs...            offsets relativos al FIN de la tabla, no al fichero
```

### `.tex` — `tools/wetex.py`

Contenedores `TEXB0001`–`TEXB0004`, formatos RGBA8888 / R8 / RG88 / R16F /
RG1616F / DXT1 / DXT3 / DXT5, compresión LZ4 de bloque, mipmaps y sprite
sheets animados (`TEXS0001`–`TEXS0003`).

Cuatro detalles que no se deducen leyendo un solo fichero y rompen el
parseo si se asumen mal:

- **`TEXB0002` no lleva `freeImageFormat`**; solo `TEXB0003` en adelante.
  Asumirlo desplaza un `uint32` y revienta todas las texturas de partículas.
- **`TEXB0004` añade un `uint32` reservado** tras `freeImageFormat`.
- **Solo `TEXS0003` lleva el tamaño del gif**, y como enteros, no floats.
- **El flag `0x20` (`IS_VIDEO`) significa que el payload es un MP4 entero**,
  no píxeles. La cabecera sigue declarando un `format` de píxel que hay que
  ignorar. Es el peor de los cuatro porque falla en silencio: si el MP4 pesa
  más que `width*height*bpp`, se decodifica como ruido sin dar error. Por eso
  `wetex` comprueba además la caja `ftyp` de ISO-BMFF y no solo el flag.

Estado de validación (`python3 tools/test_wetex.py [--workshop]`):

- **1897/1897 texturas de las 125 escenas suscritas + 283/283 de los assets
  de WE, todas consumiendo el fichero hasta el último byte.** Cero bytes
  sobrantes en las 2180. Ese criterio fue el que destapó los cuatro
  detalles de arriba; "se ve bien" no habría detectado ninguno.
- Cobertura real del corpus: contenedores `TEXB0001` (3), `TEXB0002` (20),
  `TEXB0003` (1713), `TEXB0004` (161); formatos RGBA8888 (1036), R8 (553),
  RG88 (188), DXT5 (115), DXT1 (4), DXT3 (1). Las cuatro versiones y los
  tres DXT aparecen en datos reales.
- 6099 mipmaps decodificados, de los cuales **641 DXT contrastados pixel a
  pixel** contra el decodificador DDS de PIL, que es código independiente:
  diferencia máxima de 1 por canal, que es redondeo de paleta interpolada
  permitido por la spec de D3D, no un fallo.
- 3 texturas de vídeo (MP4) detectadas y separadas; 28 LUT 3D omitidos.
- Textura principal de un wallpaper real (1920×1080 RGBA8888, 5 mipmaps)
  idéntica al `preview.jpg` oficial.

**Sin soportar a propósito:** los LUT 3D de `materials/lut/` (28 ficheros,
flag `IS_VOLUME 0x40`) tienen un layout de mipmap propio aún sin resolver.
`read_texture` lanza `TexError` en vez de devolver píxeles basura. No hace
falta ninguno para renderizar una escena; son para corrección de color.

### `.mdl` — `tools/wemdl.py`

Las mallas *puppet*. Un objeto con `puppet` no se dibuja sobre un quad: trae
una malla propia cuyos vértices se deforman por huesos. Sin ella la capa se
coloca por `origin` y acaba donde el autor no la puso.

```
char[]   magic "MDLV00NN" terminado en nul
byte[12] constantes, idénticas en las 6 versiones observadas
char[]   ruta del material, terminada en nul
byte[]   relleno según versión
u32      campo de serialización (0, o 0x01800009 en 0016)
u32      TAMAÑO EN BYTES del bloque de vértices
vértices
u32      TAMAÑO EN BYTES del bloque de índices
u16[]    índices
...      bloques MDLS (esqueleto) y MDLA (animación), sin decodificar
byte[]   relleno a cero; algunos exportadores rellenan a 1 MiB
```

Los dos tamaños son **en bytes, no en elementos**. Leerlos como número de
elementos desborda el fichero, y ése fue el primer indicio de que iban así.

Vértice de 52 bytes, 13 campos de 4:

| Campos | Tipo | Contenido |
|---|---|---|
| 0–2 | `float3` | posición (`z` siempre 0: mallas planas) |
| 3–6 | `u32 × 4` | índices de hueso |
| 7–10 | `float4` | pesos, suman 1 |
| 11–12 | `float2` | UV |

Que 3–6 son enteros se ve en un vértice atado al hueso 6: como flotante ese
patrón de bits es un denormal (8e-45), no un 6. Y que 7–10 son los pesos lo
confirma que **sumen 1 en los 19 462 vértices** del corpus, con desviación
máxima 1.19e-07 — el epsilon del `float`.

**Validación** (`tools/test_wemdl.py`): 42 de 84 mallas decodifican, 21 758
vértices y 40 185 triángulos, y las 42 cierran exactamente sobre un bloque
`MDLS`/`MDLA` — ni un byte de basura tras la geometría.

#### Esqueleto (MDLS) y animación (MDLA)

Detrás de la geometría van los huesos y sus pistas. Los dos bloques repiten el
mismo patrón que la geometría: un prefijo **por registro**, no uno por bloque.

```
MDLS: por hueso   u8 relleno, u32 (=1), i32 padre, u32 (=64), float[16], nombre
MDLA: por animación   u32 id, u32 (=0), nombre, modo, f32 duración,
                      u32 fotogramas, u32 (=0), u32 pistas
      por pista       u32 (=0), u32 TAMAÑO EN BYTES, float[]  (9 por clave)
      u32 (=0) cierra la animación
```

Las claves son `posición(3)`, `rotación(3)`, `escala(3)`, y siempre hay
`fotogramas + 1`: la última repite la primera para cerrar el bucle, así que el
periodo son `claves - 1` intervalos.

Tres errores costaron aquí, y los tres eran el mismo malentendido — leer un
prefijo una vez cuando iba por registro. El último solo se ve con **dos**
animaciones: el `u32` de cierre se lo come el relleno final cuando hay una
sola, y con dos la segunda arranca cuatro bytes antes. Da una duración de
1e28 y pistas de 4 MB, que es lo que delató el fallo.

#### El bloque intermedio de MDLA0003

Seis mallas del corpus parecían no tener animación: tras el esqueleto no había
tag `MDLA` sino cientos de bytes que tampoco eran relleno. Sí la tienen —
detrás de un bloque intermedio cuyo tamaño sale exacto en las seis:

```
12 bytes      cabecera
por hueso     76 b = 3 float + una matriz 4x4 (rotación y traslación,
              mismo layout de vector-fila que el resto del formato)
u32[huesos]   lista de índices 0,1,2…
1 byte        relleno
              -> aquí empieza "MDLA0003"
```

El ajuste `offset = 13 + 80·huesos` encaja en los seis ficheros, con recuentos
de 1 a 5 huesos. No hace falta interpretar el contenido para leer la animación
que va detrás, y `MDLA0003` resultó tener **exactamente la misma estructura**
que `MDLA0001`: en `SWORD_puppet.mdl`, duración 60 s, 120 fotogramas y una
pista de 4356 b = 121 claves = fotogramas + 1.

De ahí sale también un modo de reproducción que no aparecía en el resto del
corpus: además de `loop`, existe **`mirror`** (5 animaciones).

**Validación:** 41 de 42 esqueletos decodifican su animación y las 41 cierran
sobre relleno a cero, con el número de pistas igual al de huesos y todos los
tamaños múltiplos exactos de 36.

El único que falta es `devushka…_puppet.mdl`, y es otro formato: **MDLA0002**,
que intercala metadatos JSON de eventos entre animaciones
(`{"hashKey":"object:3287","frame":1,"name":"e"}`). Su primera animación
decodifica bien (4 pistas de 33 claves); la segunda necesita saltar ese JSON.

#### Skinning

`v' = Σ_j w_j · (v · A_j · inv(B_j))`, con matrices de **vector-fila** (`v·M`),
igual que la MVP.

El orden importa y **no es el de la fórmula de libro** (`inv(B)·A`, llevar el
vértice al espacio del hueso y de ahí al animado). Los dos dan identidad en la
clave de reposo, así que esa prueba no los distingue; lo que los separa es
cuánto deforman la malla:

| arista estirada, percentiles 1–99 | `inv(B)·A` | `A·inv(B)` |
|---|---|---|
| estandarte | [0.625, 1.633] | **[0.946, 1.044]** |
| brazo del estandarte | [0.711, 1.200] | **[0.991, 1.010]** |
| `jdarcjik` (un hueso por vértice) | [1.000, 1.000] | [1.000, 1.000] |

Con `inv(B)·A` cada hueso gira alrededor de **su** pivote. Los del brazo están
a 880 unidades, giran solidarios (correlación 0.992) y aun así sus dos
transformaciones difieren en una traslación: al mezclarlas los vértices se van
al punto medio y la malla encoge hasta 0.686. Eso se veía como un brazo que se
deforma al bascular el estandarte.

Como las matrices de reposo son **traslaciones puras** —solo el pivote, la
parte lineal es identidad—, `A·inv(B)` equivale a rotar sobre el origen de la
capa y trasladar por `(a − b)`. La capa bascula rígida.

**No hay que componer con el hueso padre.** Es lo contrario de lo que dicta el
reflejo, así que conviene dejar por qué: las pistas ya vienen en espacio
global. El `parent` del MDLS describe la jerarquía, pero no se aplica al
evaluar.

Dos pruebas, y la segunda es la que manda:

- Padre e hijo rotan casi lo mismo (0.2160 y 0.2153 en el estandarte). Con
  pistas locales, un hijo que acompaña a su padre tendría rotación local casi
  nula; que iguale al padre significa que ya la lleva dentro.
- Componer duplica el desplazamiento: 415 → 821, 57 → 137, 271 → 545. Un
  factor dos limpio no es movimiento que faltaba, es el mismo giro aplicado
  dos veces. En pantalla el estandarte se salía de la mano.

Ese segundo dato lo leí al revés la primera vez —vi «aparece el movimiento que
faltaba» donde ponía «se aplica dos veces»— y costó un render roto. Duplicar
limpio es una firma, no una mejora: si un cambio multiplica una magnitud por
un entero exacto, sospechar de doble aplicación antes que de acierto.

#### Pesos suavizados

El `.mdl` trae pesos casi binarios: en Jeanne, **384 de 431 vértices están
atados a un solo hueso con peso 1**. Esa atadura dura desgarra la costura
entre una región que rota y otra que no, y concentra toda la cizalla del
skinning lineal en unas pocas aristas.

`_smooth_weights` difunde el campo de pesos sobre la conectividad de la malla
—promedia cada vértice con sus vecinos y renormaliza— antes de subirlo. El
centro de cada región apenas cambia, así que se conserva lo que definió el
artista; solo se ablandan las fronteras, que es donde está el problema.

Con 40 iteraciones (el valor por defecto; `WE_PUPPET_SMOOTH` lo cambia, 0 lo
desactiva), medido como aristas que se estiran o encogen más de un 35%:

| capa | sin suavizar | suavizado | percentiles 1–99 |
|---|---|---|---|
| estandarte | 170 | **2** | [0.578, 1.915] → [0.892, 1.097] |
| brazo del estandarte | 42 | **7** | [0.711, 1.200] → [0.786, 1.183] |
| Jeanne | 63 | **17** | [0.782, 1.677] → [0.905, 1.228] |
| `jdarcjik` | 0 | 0 | sin cambio |

`jdarcjik` es el control: todos sus vértices pesan un único hueso, así que
suavizar no puede alterarlo, y en efecto no lo altera.

#### Margen de capa

El buffer de un objeto **es** su rectángulo, así que la geometría que se sale
al deformarse se recorta contra el borde. Medido, las cuatro mallas de Jeanne
se salen al animarse:

| capa | rectángulo (medio) | animado | margen |
|---|---|---|---|
| brazo del estandarte | 376 × 574 | **604** × 544 | 1.69 |
| `jdarcjik` | 1758 × 974 | **2100** × 311 | 1.26 |
| Jeanne | 2100 × 1114 | 1261 × **1247** | 1.18 |
| estandarte | 2100 × 1114 | **2319** × 868 | 1.16 |

Se veía como el guantelete de Jeanne desapareciendo al llegar el brazo a su
punto más alto. El margen se **mide** por capa en vez de fijar una constante,
para no gastar resolución de buffer donde no hace falta, y se aplica en dos
sitios que se cancelan: dividiendo la MVP del pase base y multiplicando la
matriz de colocación. La capa acaba en el mismo sitio y del mismo tamaño.

Hay una segunda mitad sin la cual esto rompe el parpadeo: las máscaras de los
efectos están pintadas sobre el rectángulo de la capa y se muestrean con
`a_TexCoord` sobre **todo** el buffer. Si el buffer crece, la máscara se
estira. Se rellenan con el mismo margen —borde a 0 en las de opacidad, a 127
(el neutro) en las de flujo— para que la parte pintada siga cubriendo
exactamente la capa. Verificado: a t=0.70 los ojos abiertos, a t=1.00
cerrados, igual que antes del cambio.

#### Warp MLS: probado y descartado

La hipótesis era que WE no hace skinning por pesos sino un warp suave global
(*moving least squares* rígido), lo que explicaría un brazo rígido sin
costuras. Se implementó y se midió. **No se sostiene.**

MLS necesita correspondencias de puntos, y aquí los pivotes no se mueven
—solo rotan—, así que se generan handles virtuales alrededor de cada pivote y
se transforman con la matriz del hueso. Por vértice se resuelve el mejor
ajuste rígido ponderado (Procrustes 2D), que no admite escala y por tanto no
puede encoger la malla.

Por distorsión de arista parecía ganar de calle: Jeanne pasaba de 39 aristas
rotas (LBS crudo) y 17 (LBS suavizado) a **0**, con el estirón máximo de
4.417 → 1.102. Pero esa métrica no distingue "no se deforma" de "se mueve
todo junto", y era lo segundo:

| punto | LBS suavizado | MLS por distancia |
|---|---|---|
| guantelete alzado | 100 px | 67 px |
| cadera | 4 px | **87 px** |
| pierna | 0 px | **155 px** |
| puño bajo | 0 px | **171 px** |

Los pesos por distancia reparten mal porque los tres pivotes de Jeanne están
apiñados en el hombro: un vértice lejano recibe peso casi igual de los tres y
acaba con la transformación promedio. La pierna y el puño, que el artista ató
a un hueso estático, se van con el brazo.

Con los pesos del artista en vez de por distancia, MLS empata con LBS
suavizado en Jeanne (13 aristas rotas frente a 17) y empeora en el estandarte
(117 frente a 2). No compensa.

**Conclusión:** la flexión del brazo está en los datos, no en el método. Ningún
algoritmo de deformación la elimina sin mover lo que debe quedarse quieto.

Lo que **no** arregla: el brazo de Jeanne lo mueven dos huesos con el pivote
en el hombro, a 124 px uno de otro, rotando cantidades distintas (0.4706 y
0.3697). Eso es una flexión real en los datos, no un artefacto del método;
ningún esquema de pesos la elimina. El brazo sigue doblándose donde no hay
articulación.

Las matrices se hornean en `werender.py` y viajan en el plan ya resueltas, 12
flotantes por hueso y clave (la columna que falta es siempre `(0,0,0,1)`). Los
dos ejecutores solo hacen la suma ponderada: sin trigonometría, sin jerarquía
y sin posibilidad de discrepar entre ellos. Renderizado a `t=15` s, el
horneado en Python y el de `glexec` dan `max=1/255` de diferencia — el
redondeo entre `float64` y `float32`, nada más.

**Sin soportar a propósito:** MDLV0017, 0019 y 0023 (42 ficheros) sitúan el
bloque en otro sitio y usan un stride mayor que el corpus no determina: 40 y
80 encajan igual de bien y el rango de las UV no desempata. Se rechazan con
error explícito en vez de adivinar. Las cuatro capas de Jeanne son MDLV0013,
así que no bloquean.

### Tres fallos que se veían como uno

El wallpaper de Asuka (`2533288714`) salía como un bokeh que tapaba la escena.
Eran tres causas independientes, y solo la última se parecía al síntoma:

**1. `visible` mal interpretado.** La forma `{"user": "flare", "value": false}`
no es una condición contra la que comparar: `value` es una **copia** del valor
que tenía la propiedad al guardar la escena, y quien manda es la propiedad.
Leerlo como condición invierte el resultado justo cuando la copia vale
`false`: la capa `Fullscreen` se dibujaba *precisamente por estar apagada*.
Corregirlo cambia el estado de 124 capas y efectos en el corpus.

**2. `colorBlendMode` ignorado.** Es del objeto y dice cómo se combina la capa
con lo que hay detrás. El modo 31 —44 de los 91 usos del corpus— es
`A + B*opacity`: aditivo puro, exactamente `glBlendFunc(GL_SRC_ALPHA, GL_ONE)`.
La suciedad de lente, un bokeh claro sobre negro, se componía con mezcla
normal y tapaba la escena entera en vez de aportar solo sus brillos.

Va al **componer** el objeto sobre la escena, no en el pase base: el pase base
dibuja sobre el buffer vacío del objeto, donde la mezcla no significa nada.

**3. El combo `LIGHTING` sin sistema de luces.** Los objetos `light` de la
escena no se renderizan ni alimentan uniforms. El material compila igual, pero
recibe luz cero y sale **negro**: el EVA entero desaparecía. Desactivar el
combo da la capa plana —sin luces ni reflejos—, que es pobre pero reconocible.
Afecta a 8 pases de material en todo el corpus.

De paso, `alpha`, `brightness` y `color` del objeto estaban fijos a neutro en
los uniforms; en el corpus hay 67, 68 y 133 objetos respectivamente que los
declaran distintos.

### El escaneo de no-soportados corría demasiado pronto

Una regresión sobre las 125 escenas dejó ver la consecuencia mayor de no tener
iluminación: **17 escenas renderizaban completamente negras**, y 16 de ellas
por una única causa. Los 108 pases que perdían fallaban todos con
`PerformLighting_V1: funcion de iluminacion no presente en los assets`.

El traductor **no resuelve los `#if`**: los emite y los evalúa el driver con
los `#define` que van delante. Está bien para generar código, pero el escaneo
de `UNSUPPORTED` miraba el texto entero, incluidas las ramas que nunca se iban
a compilar. Y las llamadas a `PerformLighting_V1` viven dentro de
`#if LIGHTING`, el combo que el motor **ya desactiva**. Se abortaba el shader
por una rama condenada; con él se caía la capa base y todo lo que colgaba.

El arreglo es evaluar las condicionales antes de decidir: `eval_conditional`
reproduce la semántica del GLSL de escritorio —macro sin definir vale 0 dentro
de un `#if`— y `strip_dead_branches` recorta las ramas muertas. Ante cualquier
expresión que no se entienda devuelve `None` y la rama se da por viva, que es
el lado seguro: conserva el comportamiento anterior en vez de suponer que el
código dudoso no se compila. La expresión se evalúa con `ast`, aceptando solo
nodos aritméticos y lógicos; sin `Name` ni `Call`, así que lo que no se haya
sustituido se rechaza en vez de evaluarse a ciegas.

Al traducir, apareció detrás una quinta capa sobre GLSL: `#require LightingV1`,
que declara una dependencia de un módulo del motor y el driver rechaza como
directiva desconocida. Se emite siempre a nivel superior aunque lo que la
necesita esté dentro de un `#if`, así que no sirve para decidir nada y se
elimina. En el corpus solo existe esa, en 8 shaders.

Resultado sobre las 125 escenas: los pases descartados en traducción pasan de
**127 a 0**, las escenas negras de **17 a 4**, y ninguna imagen empeora —111
quedan idénticas byte a byte. Los pases que aún se pierden (154 de 2718, un
5,7%, en 48 escenas) ya no caen en la traducción sino al compilar en el driver.

Rescatada no es lo mismo que correcta: de las 13, algunas salen bien (Lucy,
Makima) y otras destapan bugs propios —el de Arknights dibuja las capas en
mosaico, con costuras rectangulares.

## Qué campos del formato leemos y cuáles no

Inventario sobre las 125 escenas, cruzando cada clave que aparece en
`scene.json` contra lo que el código busca por nombre. Sirve para separar «el
motor es genérico» —lo es: cero identificadores de wallpaper en código
ejecutable— de «el motor entiende el formato», que es otra cosa.

Los campos de **efecto y pase están cubiertos**: solo quedan `username`
(cosmético) y `usertextures` (2 escenas). El hueco está en los objetos.

### Colocación y geometría

Aquí la lección de método es que **el recuento bruto engaña y hay que mirar la
distribución de valores**. Estos cinco campos suman 4000 apariciones y casi
todas son el valor por defecto o pertenecen a un subsistema que no existe:

| campo | apariciones | qué resultó ser |
|---|---|---|
| `alignment` | 448 | 397 dicen `center`, que es lo que ya hacíamos. **Implementado**: quedan 24 capas visibles reales. |
| `locktransforms` | 1293 | Aparece en objetos de **sonido** (56) y **luz** (7). Un campo que se aplica a un sonido no es una transformación: es el candado del editor. Nada que hacer. |
| `instanceoverride` | 725 | 647 partículas y 64 ocultos, **cero imágenes**. Bloqueado tras el sistema de partículas. |
| `parallaxDepth` | 1425 | También en sonidos (57). Es profundidad relativa a la cámara; sin movimiento de cámara no desplaza nada. Bloqueado tras la cámara. |
| `perspective` | 425 | **423 son `False`.** Los dos `True` del corpus son las capas de personaje de Jeanne y de Lucy, las dos con malla puppet. Jeanne renderiza bien sin leerlo. |
| `anchor`, `horizontalalign`, `verticalalign` | 159 cada uno | 153, 152 y 156 son el valor neutro. Además son de **texto**, que no rasterizamos. |

Conclusión: el bloque de colocación **está terminado con `alignment`**. Lo que
queda no son campos ignorados sino campos cuyo subsistema no existe todavía.

### Lo que sí falta, medido

- ~~Capas de composición~~ **hecho**: una capa puede leer el buffer de otra por
  `_rt_imageLayerComposite_<id>_a|_b`. Cuando el id es el suyo propio significa
  su par ping-pong --- 86 de las 122 referencias del corpus, y ya funcionaba.
  Cuando apunta a otra capa es una composición leyendo a sus fuentes, y esas
  fuentes suelen estar marcadas invisibles: 36 referencias en 9 escenas, 33 de
  ellas a capas ocultas. Ahora esas capas se dibujan a su buffer sin componerse
  sobre la escena. Se ve en True Damage Ahri, cuya esfera pasa de un borrón
  claro a la orbe con estructura que enseña el preview.

  Queda un cabo suelto: en Lucy la Tierra sigue sin verse, pero no por el
  mecanismo --- sus fuentes renderizan con contenido real --- sino porque la
  capa de composición cae casi entera por encima del lienzo (`ty = 1.45` con
  semialtura 1.39), arrastrada por la escala 2.5 del grupo que la contiene.
- ~~Mallas puppet sin decodificar~~ **hecho**: las seis versiones del corpus se
  leen. Las mallas que las escenas usan pasan de 43 a 92 y las omitidas de 49 a
  0. Se ve sobre todo en Lucy, que recupera pelo y chaqueta, y en demon-hunter,
  donde los rectángulos negros pasan a seguir la silueta del personaje --- esa
  capa sigue saliendo negra, pero ya por otro motivo.
- ~~Partículas~~ **hecho**: 823 sistemas en 106 escenas, de los que 821 se
  simulan. Ver la sección siguiente.
- **Texto**: 159 objetos en 28 escenas; leemos el campo, no dibujamos glifos.
- **Shaders**: 31 variantes de 556 no compilan; 21 son conversiones implícitas
  de HLSL.

## Sistemas de partículas

Es el primer subsistema con **estado que avanza con el reloj**. El resto del
motor resuelve el grafo una vez y el ejecutor solo dibuja; aquí hay que
integrar velocidades fotograma a fotograma, y eso no puede vivir en Python
porque el plan se genera una vez y se ejecuta miles de veces.

El vocabulario resultó **cerrado y pequeño**, que es lo que hizo el trabajo
abordable. Censo de las 125 escenas:

| categoría | nombres distintos | cobertura |
|---|---|---|
| emisores | 2 (`sphererandom` 607, `boxrandom` 216) | los 2 |
| inicializadores | 10 | los 8 mayores = 99% |
| operadores | 13 | los 12 mayores |
| renderers | 4 (`sprite` 586, `spritetrail` 145, `rope` 34, `ropetrail` 32) | dibujados como sprite |
| shader | **1**: `genericparticle`, en los 823 | ya compilaba |

29 piezas cubren el 100% de los 823 sistemas. Se simulan **821**; los 2
restantes no declaran emisor o material.

### El reparto

`tools/weparticles.py` lee el JSON, resuelve nombres y valores por defecto y
escribe un `.psys`: una lista plana de piezas con sus parámetros ya en números.
`src/weparticles.c` simula; no conoce Wallpaper Engine, solo ejecuta las piezas
que le llegan.

**Ese .c se compila tal cual en los dos ejecutores** —`tools/glexec.c` y
`src/glexecutor.cpp`—, que es la única forma de que la simulación no diverja
entre el render offline y el escritorio. Es la lección de
`divergencia-en-vivo-motion-blur` aplicada por construcción en vez de a
posteriori.

El fichero `.psys` no lleva nombres de campo, solo números en un orden
convenido. `tools/test_weparticles.py` lee las tablas del propio `.c` y
comprueba, sobre los 6476 parámetros del corpus, que los dos lados cuentan lo
mismo. Sin eso una divergencia no falla: rellena con ceros y simula algo
parecido pero equivocado.

### Verificación

Regresión de render sobre las 125 escenas, comparando contra el árbol anterior:
**0 fallos, 0 cambios de tamaño**, 98 escenas cambian y 27 quedan idénticas. Lo
que hay que mirar no es ese reparto sino este: **las 27 escenas sin partículas
salen byte a byte iguales**. Los modos de mezcla nuevos son exclusivos de las
partículas justamente para que eso se cumpla.

De las escenas CON partículas, siete tampoco cambian, y las siete están
explicadas: dos tienen sistemas intermitentes —un rayo de 0,2 s de vida a 2 por
segundo— que en el instante muestreado no tenían ninguna partícula viva, y las
otras cinco están tapadas por capas negras que ya salían negras antes.

`tools/test_weparticles.py` valida además los 6476 parámetros del corpus contra
las tablas del `.c`.

### Y luego, en el escritorio

Con todo eso verde, el primer arranque dentro de plasmashell dijo:

```
particulas 4 sistemas / 17 piezas sin soporte
```

17 de 42 piezas, y todas soportadas. El mismo `.so`, cargado con `dlopen` desde
un programa suelto y leyendo los mismos ficheros, decía 0.

La diferencia era **`LC_NUMERIC`**. `strtof` mira la locale, Qt hace
`setlocale(LC_ALL, "")` al arrancar y este escritorio tiene `es_ES`: con
separador decimal coma, `0.88235` se lee como `0` y ahí se para. La pieza se
queda corta de floats y `we_psys_load` la descarta —por diseño, más vale
descartarla que leer los campos corridos—, así que el fallo salía **contado
como "sin soporte"**, que es justo lo que uno da por conocido y no mira. Las 17
eran exactamente las piezas con decimales; las de valores enteros pasaban.

Fuera de plasmashell no se ve: un binario en C que nunca llama a `setlocale` se
queda en la locale `C`. Por eso el renderizador offline, la regresión de las 125
escenas y la prueba de contrato daban todos verde. **El único ejecutor afectado
era el que no se había ejercitado nunca.**

El arreglo es `uselocale` con una locale `C` solo numérica y solo en ese hilo,
durante el parseo. No sirve `setlocale` global: se llevaría por delante el
formato de números del resto de plasmashell. La prueba nueva compila el lector y
lo corre dos veces, con `LC_ALL=C` y con la primera locale de coma instalada.

### Lo que costó encontrar

Cinco fallos, ninguno en la simulación:

- **El alfa se elevaba al cubo.** Un sprite se mezcla con los demás dentro del
  buffer del objeto, y ese buffer se compone después sobre la escena
  multiplicando otra vez por su alfa. El borde de un halo, con alfa 7/255,
  acababa en 2·10⁻⁵. Solo sobrevivía el núcleo opaco: las luciérnagas de 80 px
  se dibujaban como puntos de 2 px, con la geometría perfecta. Se arregla con
  dos modos de mezcla y dos de composición nuevos (`premul_*`), que **solo usan
  las partículas**: así el corpus que ya funcionaba no se toca.
- **`TEX0FORMAT`.** Las texturas `RG88`/`R8` guardan el gris en R y el **alfa en
  G o en R**, y `ConvertTexture0Format` las desempaqueta si el motor le dice el
  formato. Sin decírselo, los haces de luz salían como barras rojas macizas
  cruzando la pantalla. Los `FORMAT_*` del shader coinciden número a número con
  `wetex.TexFormat`.
- **`instanceoverride`.** Lo llevan **725 de los 823 objetos**, porque los
  sistemas son presets compartidos y cada escena los ajusta desde el editor. Son
  factores, no valores: llegan a 200 en `count` y a 50 en `lifetime`.
  Ignorarlos no da un resultado parecido, da otro.
- **El sampler oculto de refracción.** 89 pases activan `REFRACT` y su albedo es
  blanco opaco **a propósito**: toda la imagen sale de deformar lo que hay
  detrás, leído de `_rt_FullFrameBuffer` por un sampler que el material no
  declara y que solo aparece como `default` en los metadatos. Sin enlazarlo, la
  lluvia de un wallpaper salía como cuadrados blancos macizos.
- **El recorte en z.** La turbulencia sin máscara empuja también en z, y esa z
  está en píxeles: valores de 10 o 20 salen del rango de recorte [-1,1] y GL
  descarta el triángulo entero. Dos antorchas se simulaban perfectamente y no
  dibujaban un solo píxel, sin un error de por medio. La matriz de partículas
  aplana z a cero; la prueba de profundidad está desactivada en todo el motor,
  así que no se pierde nada.

### Decisiones que son lecturas, no hechos

- **`colorrandom` usa un único factor** para las tres componentes, no uno por
  componente. El preset de luciérnagas declara `min (246,207,135)` y
  `max (0,0,0)`: por componente salen rojos y verdes puros —parecían luces de
  navidad—, y con un factor único salen todas del mismo ámbar a distinto brillo.
- **`controlpointattract` sobre un punto con `flags & 1` no actúa.** Ese bit ata
  el punto al cursor, y 106 de los 136 usos apuntan justo ahí. Sin puntero el
  punto se queda en el origen y el operador deja de ser una interacción para
  ser un sumidero: la nube de 512 px de radio se apelotona en una bola de 64.
  Cuando el motor en vivo sepa dónde está el puntero, entra por ahí.
- **Las texturas de partícula se suben sin voltear.** En una capa normal el
  volteo se cancela con el de las UV; en un sprite que muestrea un *rectángulo*
  de una hoja no se cancela nada.

### Lo que queda

- Las estelas (`spritetrail`, `rope`, `ropetrail`: 211 sistemas) se dibujan como
  sprites sueltos. La geometría de la estela pide el historial de posiciones de
  cada partícula, que hoy no se guarda.
- `mapsequencebetweencontrolpoints` y `mapsequencearoundcontrolpoint` (14
  sistemas) reparten las partículas por una ruta de puntos de control: es otro
  modelo de emisión, no un parámetro.
- `remapvalue`, 2 sistemas.

## Uso

```sh
make install    # modulo QML + symlink del paquete + environment.d
make reload     # reinicia plasmashell; hace falta, cachea el QML compilado
make status     # comprueba enlace, entorno y plugin activo
make uninstall
```

`make install` es lo único que hace falta en una máquina nueva: instala el
módulo QML, enlaza el paquete del wallpaper (symlink, para edición en vivo) y
escribe el `environment.d`. Todas las rutas salen de `$HOME`/`$XDG_CONFIG_HOME`
y `$(CURDIR)`, así que no hay nada codificado a la máquina de desarrollo.

Activar sin pasar por la GUI:

```sh
qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript '
var ds = desktops();
for (var i = 0; i < ds.length; i++) ds[i].wallpaperPlugin = "org.jose.wallpaperengine";
'
```

Volver al wallpaper de siempre: el mismo script con `"org.kde.image"`.

## Notas de plataforma

- `Screen.refreshRate` llega `undefined` dentro del `WallpaperItem` (por eso
  el HUD muestra `n/d`). Si más adelante hace falta el refresco real para
  limitar FPS, sacarlo de `kscreen-doctor -o` o de KWin por D-Bus.
- `FrameAnimation` late en el hilo de render de Qt, una vez por frame
  compuesto. Cuando el escritorio queda oculto Qt deja de componer y el
  reloj se detiene solo: pausa por oclusión sin escribir lógica de pausa.
  Es el equivalente a `wl_surface.frame`.
- Las animaciones se derivan de `elapsedTime` (segundos), nunca de un
  contador de frames, para que la velocidad no dependa del refresco.

### Dialecto de shader — `tools/weshader.py`

Los shaders de WE parecen GLSL pero llevan cuatro capas encima: `#include`,
directivas `// [COMBO]` que generan variantes, metadatos JSON en el
comentario de cada uniform, y restos de HLSL. Ningún fichero declara
`#version` y todos usan `varying`/`attribute`: la cabecera la pone el motor.

Las 31 funciones que WE inyecta (`texSample2D`, `mul`, `CAST4`, `frac`,
`saturate`…) no están definidas en ningún sitio de la instalación. La lista
no es una suposición: sale de cruzar todas las llamadas del corpus contra
todo lo definido en los headers; lo que queda sin definir es, por
eliminación, lo que aporta el motor.

**La decisión que más pesa: se apunta a GLSL 330 core, no a GLSL ES.**
Medido, no supuesto — el mismo corpus con un objetivo y con el otro:

| Objetivo | Mesa | NVIDIA |
|---|---|---|
| `#version 320 es` | 71.2 % | 71.3 % |
| `#version 330 core` | **96.5 %** | **96.5 %** |

GLSL ES prohíbe la conversión implícita `int`→`float` de la que dependen
estos shaders por venir de HLSL, y reserva `sample`, que se usa como nombre
de variable. El de escritorio permite las dos cosas desde la 1.20. Además
es lo que usan Qt6 y KWin en escritorio Linux.

Otros dos arreglos con impacto medible:

- **Izado de uniforms.** Los shaders ponen `#include` arriba y los `uniform`
  después, pero las funciones del header ya usan `g_Texture0`; GLSL exige
  declarar antes de usar. Solo se izan los de nivel superior: uno dentro de
  un `#if` depende de su combo y sacarlo lo activaría siempre.
- **Combos desde los uniforms.** No solo vienen de las directivas `[COMBO]`;
  también de la clave `combo` en los metadatos de un uniform. `MASK` es el
  caso típico. Cualquier condicional que siga sin definir se fija a 0, que
  es lo que significa "combo no asignado".

Estado de validación (`tools/test_weshader.py`, compilando con el driver
real vía `tools/glslcheck.c` sobre un contexto EGL surfaceless):

- **2186/2266 shaders compilan en Mesa y 2187/2266 en NVIDIA (96.5 %).**
- **Los 30 shaders del wallpaper de referencia compilan, ninguno falla.**
- Por wallpaper, que es lo que de verdad cuenta porque hacen falta todos:
  **78 de 109 (71.6 %) compilan enteros**, y la mayoría de los restantes
  fallan por un único shader.

**Lo que falta para el 100 %** es una pasada con análisis de tipos que
inserte casts explícitos: lo que queda son truncamientos implícitos de HLSL
(`vec4` → `vec2`) y sobrecargas que GLSL no tiene (`pow(vec3, float)`).
Sobrecargar el builtin no sirve: en GLSL declarar `pow` oculta el original y
la llamada interna se vuelve recursiva. Cuatro de los fallos ni siquiera son
nuestros — son shaders del Workshop con los `#if` descuadrados en origen.

### Grafo de escena — `tools/wescene.py`

Una escena no es una lista de capas: es un grafo de render con recursos
nombrados. Pintar **una sola imagen** pasa por esta cadena:

```
scene.json  objects[].image = "models/X.json"
  -> model.material         = "materials/X.json"
    -> material.passes[].shader   -> shaders/<name>.vert + .frag
    -> material.passes[].textures -> materials/<name>.tex
    -> material.passes[].combos   -> variantes del shader
```

y encima cada objeto lleva una cadena de efectos, donde cada efecto es a su
vez una lista de pases con render target y bindings de entrada. Los `passes`
que trae el objeto en `scene.json` **no son los pases**: son *overrides*
posicionales sobre los del `effect.json`. Confundirlos es el error fácil.

El wallpaper de referencia resuelve a **25 pases de render para una única
imagen**, con buffers intermedios (`_rt_HalfCompoBuffer1`,
`_rt_QuarterCompoBuffer2`) y targets generados por objeto con el id
incrustado (`_rt_imageLayerComposite_128_b`).

Hay un tipo de pase que no es de shader: `{"command": "copy", "source":…,
"target":…}` es un blit entre render targets.

Estado de validación (`tools/test_wescene.py`):

- **125/125 escenas resuelven** el grafo completo: 2036 objetos, 3471 pases.
- **2812 referencias de textura, todas resueltas.** Cero sin encontrar.
- **576/628 (91.7 %) de las variantes de shader que las escenas piden de
  verdad compilan** en Mesa, 577/628 (91.9 %) en NVIDIA.

Esa última cifra es más exigente que la de `test_weshader.py`: allí se
compila con los combos por defecto, aquí con los combos reales de cada pase,
que es lo que acaba en la GPU. La diferencia destapó dos bugs que la prueba
anterior no podía ver.

**Bug 1 — CRLF.** Los shaders extraídos de un `scene.pkg` conservan CRLF, y
leerlos como bytes no aplica la traducción de saltos de línea que sí hace
`read_text()`. Las expresiones del traductor anclan en `$`, que no admite el
`\r` previo: el mismo shader se resolvía bien desde disco y se quedaba sin
resolver desde el paquete. Coste: 142 `#include` sin expandir, 50 % de tasa
de compilación.

**Bug 2 — semántica de los combos a 0.** Un combo apagado no se traduce como
`#define X 0`, se traduce como *no definir la macro*. Con `#ifdef X` —que
solo mira si existe, no su valor— definirla a 0 **activa** la rama que
debería quedar fuera. Eso metía una declaración con `BONECOUNT` en
`genericimage2.vert`, el pase base de prácticamente toda imagen. Pero
omitirla sin más rompe los shaders que usan el combo *como valor* en el
código (`ApplyBlending(BLENDMODE, …)`): hay que mirar cómo lo consulta cada
shader. Con la regla afinada: 88.1 % → 91.7 %, y los tres `genericimage`
compilando.

**El tipo de objeto va por valor, no por clave.** Un sistema de partículas se
declara con `image: null`, `model: null` y `particle: "..."` a la vez.
Comprobar solo si la clave existe lo clasificaba como imagen vacía: 112
objetos del corpus estaban mal contados y generaban 115 falsas "referencias
sin resolver". Lo destapó probar un wallpaper al azar, no el de referencia.

**Sin modelar todavía:** jerarquía de objetos. 69 objetos del corpus llevan
clave `parent` y son nodos de transformación puros; hoy se clasifican como
`unknown` y no se les aplica la transformación del padre.

### Renderizador offline — `tools/werender.py` + `tools/glexec.c`

Ejecuta una escena de verdad y vuelca un PNG. La inteligencia está en Python
(grafo, traducción de shaders, decodificación de texturas, binding de
propiedades); `glexec` solo ejecuta un plan ya resuelto sobre un contexto EGL
surfaceless con OpenGL 3.3 core.

El **binding de propiedades** —último subsistema pendiente del inventario—
sale de los metadatos: cada uniform declara con qué entrada de
`constantshadervalues` se enlaza (`material`) y qué valor usar si el pase no
la trae (`default`).

```sh
cc -O2 -o /tmp/glexec tools/glexec.c -lEGL -lGL
python3 tools/werender.py <dir_wallpaper> salida.png --frames 6 --time 3.7
```

Los 25 pases del wallpaper de referencia se ejecutan y el resultado muestra
los efectos aplicados. Tres bugs que solo aparecen ejecutando de verdad:

**Orden de bindeo del FBO.** Los render targets se crean bajo demanda, y
crearlos implica bindear su FBO para limpiarlo. Al resolverlos *dentro* del
bucle de samplers, el `glDrawArrays` posterior escribía en el buffer recién
creado en vez de en el destino del pase. Los once primeros pases se libraban
porque creaban sus targets antes del bind.

**Mezcla en pases de post-proceso.** Los pases de efecto limpian el destino a
`(0,0,0,0)` y escriben la pantalla entera. Con la mezcla de GL activa sale
`dstA = srcA²`, así que el alfa se hundía pase a pase — 255 → 104 → 42 → 7 → 0
— y el RGB detrás. El `blending` del material describe cómo compone el
*shader* (combo `BLENDMODE`), no el estado de GL.

**FBOs `unique` instanciados.** Los buffers marcados `"unique": true` en el
`effect.json` se instancian por objeto: el `effect.json` los nombra genéricos
(`_rt_FullCompoBuffer1`) y el `scene.json` referencia la instancia
(`_rt_FullCompoBuffer1_128_145`). Sin traducir entre ambos, el motion blur
escribía su historia en un buffer y la leía de otro: nunca convergía.

Los efectos temporales necesitan varios fotogramas para converger; con
`--frames 6` el motion blur recupera el alfa a 255. En un solo fotograma su
buffer de historia está vacío por definición, igual que en WE.

**Combos de máscara.** Un combo declarado en los metadatos de un sampler se
activa cuando ese slot está realmente enlazado en el pase. Sin esa regla la
máscara de un efecto se ignora y el efecto se aplica a la imagen entera: el
`pulse` de la escena de referencia hacía oscilar el brillo del wallpaper
completo casi al doble. Medido sobre 6 fotogramas, la variación de brillo
medio pasó de **52.9 a 0.2** al aplicarla. Solo se ve renderizando una
secuencia: en un fotograma aislado la imagen parece plausible.

`render_sequence()` genera un bucle animado (`--frames`, warmup incluido para
que converjan los efectos temporales). El vídeo del plugin son 180 fotogramas
a 30 fps.

### Composición de capas

Hay dos niveles de buffer: el **par ping-pong del objeto** (donde corre su
cadena de efectos) y el **buffer de escena**, donde cada objeto se compone
encima del anterior. Antes solo existía el primero y cada pase limpiaba su
destino, así que un objeto borraba al anterior: **solo se veía la última
capa**. De las 125 escenas suscritas, 69 (55 %) tienen dos o más capas y 41
tienen seis o más.

El plan lleva una marca `object <copybackground>` por objeto:

- al abrirla, el objeto arranca vacío, o **desde una copia de la escena** si
  el objeto declara `copybackground` — que es lo que necesitan las capas de
  post-proceso, las que se llaman *"Post-Processing Layer"* o *"Warstwa
  pełnej kompozycji"* y antes leían un buffer recién limpiado y salían negras;
- al cerrarla, el objeto se compone sobre la escena con mezcla.

Componer exige dibujar (`glBlitFramebuffer` no mezcla), así que el motor
lleva **un** shader propio, el único que no viene del plan.

Un plan generado antes de existir estas marcas se trata como un solo objeto,
para no dejarlo en negro.

Medido sobre la muestra aleatoria de cinco que destapó el problema:

| Wallpaper | Capas | Antes | Ahora |
|---|---|---|---|
| Jinx | 6 | solo el bokeh | completo |
| Jeanne d'Arc | 9 | negro | con contenido |
| Ryomen Sukuna | 11 | negro | con contenido |
| kumo desu ga | 1 | correcto | correcto (sin regresión) |
| La Ferrari | 3 | solo la carretera | completo |

### Transformación por objeto

Cada objeto declara `origin`, `size`, `scale` y `angles` en píxeles de lienzo.
El pase base recibe una MVP que mapea el quad (-1..1) a ese rectángulo; los
pases de efecto son post-proceso a pantalla completa y se quedan con la
identidad. El shader hace `mul(vec4(a_Position,1), g_ModelViewProjectionMatrix)`
—convención de vector-fila de HLSL—, así que el array de 16 floats que se sube
es la matriz escrita por filas.

Comprobación útil: una capa cuyo `size` es el lienzo y cuyo `origin` es el
centro produce exactamente la identidad.

### Visibilidad condicional

Un objeto o un efecto puede declarar `visible: {"user": "propiedad", "value": X}`:
solo se dibuja si esa propiedad configurable del wallpaper vale lo indicado.
Ignorarlo hacía renderizar capas y efectos que el autor dejó apagados —
**559 pases de 3471 en el corpus, un 16 % del trabajo de render**.

`user` no siempre es el nombre de una propiedad: en 8 wallpapers es a su vez
un objeto. Ante una forma que no se entiende se opta por dibujar, que es el
fallo menos destructivo.

### Render targets incorporados

`_rt_FullFrameBuffer` y `_rt_MipMappedFrameBuffer` no son buffers de un
efecto: son nombres reservados de WE para "el fotograma compuesto hasta
ahora". Crearlos como buffers nuevos los dejaba vacíos para siempre, así que
cualquier capa que los muestreara —las de composición completa— leía
transparente. Se aliasan al buffer de escena, igual que
`_rt_imageLayerComposite_*` se aliasa al par ping-pong del objeto.

Los destinos usan índices con dos valores especiales (`kCompo`, `kScene`) y un
único `resolveTarget()`, en vez de comparar contra `-1` repartido por el
código.

### `copybackground` no significa "empieza desde el fondo"

En Jeanne **los nueve objetos** lo declaran, no solo la capa de composición.
Interpretarlo como "copia la escena dentro del objeto" hacía recomponer el
fondo nueve veces sobre sí mismo. Cada objeto arranca transparente y aporta
solo lo suyo; la mezcla ocurre una vez, al componerlo sobre la escena. Los
efectos que necesitan el fondo lo leen del buffer de escena por su nombre.

Resultado sobre la escena que destapó el problema (borde vertical duro en la
zona del artefacto, cuanto más bajo mejor):

| | antes | después |
|---|---|---|
| Jeanne d'Arc | 32.1 | **13.2** (artefacto ausente) |
| Jinx | — | 5.3 (sin cambio) |
| La Ferrari | — | 8.1 (sin cambio) |
| kumo desu ga | — | 15.0 (sin cambio) |


**Sin implementar:** partículas (los 7 sistemas del wallpaper de referencia no
se dibujan), audio (`g_AudioSpectrum*` a cero), y transformaciones de objeto
—la MVP es la identidad y todo se dibuja como quad a pantalla completa, así
que no hay parallax ni posicionado de capas.

**Fuga de temporales:** `werender.py` crea un directorio en `/tmp` por
ejecución y no lo borra. Con escenas 4K son cientos de MB cada una; conviene
`rm -rf /tmp/werender-*` tras una tanda.

## Nota de rendimiento para el port a C++

La GPU de esta máquina (Intel Raptor Lake, Mesa) expone
`GL_EXT_texture_compression_s3tc`, `GL_ARB_texture_compression_bptc` y
`GL_EXT_texture_compression_rgtc`.

Es decir: **el motor no debe decodificar DXT.** Los bloques BC se suben tal
cual con `glCompressedTexImage2D` — cuatro veces menos VRAM, cero coste de
CPU y el filtrado lo hace el sampler. Lo que hay que portar a C++ es el
*parser* (cabecera, mipmaps, LZ4) y los formatos sin comprimir. Los
decodificadores BC de `wetex.py` son para tooling y validación, no para el
camino caliente del render.

## Lo siguiente

Por orden de lo que más se nota:

1. **Estelas de partículas** — 211 de 823 sistemas (`spritetrail`, `rope`,
   `ropetrail`) se dibujan como sprites sueltos. Hace falta guardar el historial
   de posiciones de cada partícula y generar la cinta a partir de él.
2. **Las 2 escenas negras y los 26 shaders de 578 que no compilan.** Poca
   anchura, pero cuando cae la capa base se lleva la escena entera.
3. **Texto** — 159 objetos en 28 escenas. Se lee el campo, no se rasterizan
   glifos.
4. **Elegir la GPU que renderiza** (ver abajo).
5. **Iluminación**: los materiales con luces se dibujan planos.
6. `mapsequence*` (14 sistemas) y `remapvalue` (2).

`controlpointattract` sobre puntos atados al cursor (106 de 136 usos) entra solo
en cuanto el motor en vivo sepa dónde está el puntero; no es trabajo aparte.

### Elegir la GPU que renderiza

En un portátil híbrido el fondo se dibuja hoy en la iGPU, que es la que lleva el
panel. Medido con `/proc/<pid>/fdinfo` del i915, sobre *Sentinel Irelia* a
2560×1440 con 102 pases:

```
plasmashell: 2.99 s de GPU en 6.0 s  ->  49.6 % del motor de render Intel
```

La mitad de la iGPU ocupada en continuo, compitiendo con todo lo demás y
comiendo ancho de banda de memoria compartida con la CPU.

Que la dedicada acepta el trabajo está comprobado en el arnés, forzándolo con
`__NV_PRIME_RENDER_OFFLOAD=1` y el ICD de NVIDIA en
`__EGL_VENDOR_LIBRARY_FILENAMES`:

```
sin arnés   0 %,  2.6 W,  41 MiB
con arnés  37 %, 27.4 W, 443 MiB     (3 fds sobre /dev/dri/renderD128)
```

Un cliente Qt/Wayland se puede forzar a la dedicada y KWin lo compone desde la
integrada sin caerse. Falta comprobar que los píxeles salen bien: los `qInfo`
del `SceneView` no llegan a la terminal en el arnés.

**La restricción de diseño:** la GPU se elige *por proceso* —la escoge libglvnd
al cargar el driver EGL— y el `SceneView` dibuja dentro del contexto de
plasmashell con `beginExternal()`. Así que hay dos caminos y no son variantes
del mismo:

- **Conmutador de proceso.** `wectl gpu intel|nvidia` escribe un drop-in de
  systemd para `plasma-plasmashell.service` con esas variables y lo reinicia; el
  mismo ajuste desde el config del plugin. Un día de trabajo. Mueve plasmashell
  **entero** a la dedicada y cuesta ~24 W constantes, que en batería no salen.
- **Renderizador aparte.** `glexec` ya renderiza offscreen con EGL surfaceless:
  que dibuje sobre un buffer GBM de la dedicada, exporte el fd dmabuf y
  plasmashell lo importe como textura con `EGL_EXT_image_dma_buf_import`. Solo
  se mueve el fondo, el shell se queda donde está y la dedicada duerme cuando el
  fondo no se ve. Semana larga, y **con un riesgo que puede tumbarlo**: que Mesa
  no pueda importar el dmabuf que exporta NVIDIA. Se resuelve con una sonda de
  ~150 líneas antes de comprometerse.
