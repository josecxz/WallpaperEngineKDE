# Notas técnicas — WallpaperEngine

Documentación detallada de los formatos de Wallpaper Engine tal como se han ido
descifrando, con las medidas que sostienen cada decisión y las hipótesis que se
probaron y descartaron. Es material de referencia para trabajar sobre el motor;
para empezar, ver [README.md](README.md).

Motor de animaciones para el escritorio, KDE Plasma 6 / Wayland.

## Regla de trabajo: nada específico de un wallpaper

Cuando un wallpaper sale mal, **el arreglo tiene que valer para todos**. Nunca
un caso especial por id de escena, por nombre de capa, ni un campo del formato
descartado porque «en esta escena estorba». Si la escena declara un dato, se
lee; si el resultado no cuadra, lo que falta es entender el mecanismo, no
esquivarlo.

Por qué, y no es una preferencia de estilo:

- **Un caso especial no se puede comprobar.** El criterio de este repositorio
  es medir sobre las 129 escenas. Una excepción para una escena no la puede
  validar el corpus: por construcción acierta en la única donde se probó y no
  dice nada de las otras 128.
- **Tapa la causa.** Pasa dos veces en estas notas y las dos veces salió caro:
  el fallo de enlace que ocultaba el desbordamiento de godrays, y la regla de
  «solo heredan los grupos», que era un parche a la mezcla del objeto. Las dos
  parecían correcciones y eran vendas; en cuanto se arregló lo de debajo, el
  parche estorbaba —ver [Compilar no es
  enlazar](#compilar-no-es-enlazar-82-pases-que-se-perdían-sin-decir-nada) y
  [Los recuadros
  negros](#los-recuadros-negros-una-capa-negra-de-verdad-compuesta-con-la-mezcla-que-no-era)—.
- **La biblioteca de cada uno es otra.** Este corpus son las escenas que hay en
  esta máquina. Un motor que necesite una excepción por escena no funciona en
  la biblioteca de nadie más, que es justo para lo que sirve el proyecto.

Qué hacer cuando no se entiende un caso: **dejarlo escrito y no tocarlo**. Es
lo que se hizo con la ondulación de `3299228616`, donde el barrido dice que
cuadraría ignorando el desplazamiento que la capa declara —y por eso
precisamente no se ignora—. Una diferencia documentada es información; un caso
especial que la esconde es deuda que ya no se ve.

Lo que sí es general, aunque salga de una sola escena: reponer un campo del
formato que no leíamos, implementar un modo de mezcla que la tabla de WE
define, o corregir una regla que se dedujo mal. Eso no es un caso especial: es
el mecanismo, y se mide sobre el corpus entero como todo lo demás.

## Regla de trabajo: `wectl` no crece por iniciativa propia

**No se añaden órdenes, opciones ni ajustes al CLI si no se han pedido.** Ni
como remate de un arreglo, ni como «la forma limpia» de exponer algo que se
acaba de tocar, ni porque el mando exista ya por dentro y falte solo la línea
que lo enseña.

De dónde sale la regla: pidiendo que los destellos de una escena se movieran
menos —ver [Los destellos de la
`City`](#los-destellos-de-la-city-qué-se-mueve-y-por-qué-no-se-toca-nada)—, se
montó un factor sobre el reloj de las partículas y **de paso** se le colgó un
`wectl calma` que nadie había pedido. Lo segundo fue una decisión de producto
tomada por el camino, y acabó llevándose por delante también a lo primero: se
retiraron los dos.

Por qué importa, y no es cuestión de gusto:

- **El CLI es la superficie de uso diario.** Cada orden nueva es vocabulario
  que hay que recordar, documentar y mantener, y una que se añade sola no ha
  pasado por la única pregunta que la justifica: si hace falta.
- **Un ajuste del CLI no se mide como se mide el motor.** El corpus dice si un
  campo del formato se lee bien; no dice si un comando sobra. Sin ese oráculo,
  lo único que queda es no inventarlo.
- **Lo de dentro y lo de fuera se retiran distinto.** Un mecanismo que vive en
  el plan se quita sin que nadie lo note; una orden publicada ya está en la
  memoria de quien la usó.

Qué sí se hace: dejar el mecanismo donde le toca —el plan, `werender.py`, los
ejecutores— y **decirlo**, para que quien manda decida si merece una orden.

## Estado

**El motor corre en vivo dentro de plasmashell**, partículas incluidas. Una
escena real de Wallpaper Engine se ejecuta con OpenGL sobre una textura que Qt
compone en su scene graph, detrás de los iconos del escritorio. Verificado en
Plasma 6.7.3 / Wayland: primero *LoL Warwick* con 24 pases, y ahora *Sentinel
Irelia* con 102 pases y 4 sistemas de partículas.

Aquí ponía «a 166 fps». Ese número era el del reloj de QML y no medía el motor
—ver [El HUD decía 166 fps con la GPU al 98 %](#el-hud-decía-166-fps-con-la-gpu-al-98-)—.
La biblioteca de referencia son **129 escenas** desde el 2026-08-24, cuando las
rutas pasaron a la instalación real de Wallpaper Engine; las cuentas «de 125»
que aparecen más abajo son medidas correctas de la biblioteca anterior.

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
wectl shuffle           pone uno al azar de toda la biblioteca
wectl start / stop      activa o para el motor
wectl status            que hay puesto y como va
```

`set` acepta el id de Workshop o parte del título, sin distinguir mayúsculas
ni acentos; si el texto es ambiguo lista los candidatos en vez de elegir por
su cuenta.

### Rotación: por qué es un temporizador y no una opción del plugin

`wectl shuffle --cada 30m` pone uno al azar y deja la rotación andando; con
`--parar` se apaga.

El sitio natural para un «cada x tiempo» sería la configuración del fondo, y no
puede estar ahí: **el QML no sabe generar planes**. Cambiar de wallpaper es
traducir shaders y decodificar texturas, o sea Python —entre 0,3 y 1,1 s por
escena, con hasta 108 MB de `.rgba`—, y el plugin solo sabe ejecutar un plan ya
resuelto. Así que la rotación es un temporizador de systemd **de usuario** que
llama a este mismo `wectl`; el plugin ni se entera, ve un plan nuevo y lo carga
igual que con `set`. Es de usuario y no del sistema porque sin sesión no hay
plasmashell a quien pedirle nada: `PartOf=graphical-session.target` lo para al
cerrar sesión y `OnUnitActiveSec` cuenta desde el cambio anterior, así que un
`set` a mano por medio no descuadra el reloj.

Dos decisiones que no son obvias:

- **Bolsa, no sorteo.** Sortear cada vez sobre las 125 escenas es lo evidente y
  lo peor: se repiten unas cuantas mientras otras no salen nunca. Con una bolsa
  que se rellena al vaciarse salen **todas** antes de repetirse ninguna, y al
  cambiar de vuelta se comprueba la costura para no ver dos veces seguidas la
  misma. La bolsa vive en `XDG_STATE_HOME` porque cada cambio es un proceso
  nuevo que lanza el temporizador y muere.
- **Sin lista negra.** Si una escena no se deja preparar se pasa a la siguiente
  —el usuario pidió un cambio— pero no se apunta como rota: una lista negra en
  disco envejece mal y se llevaría por delante lo que falló un día porque el
  disco estaba lleno. Volverá a intentarse dentro de 125 cambios.

### Cambiar la cadencia sin cambiar el fondo, y por qué el mínimo es 1 minuto

`wectl shuffletime <tiempo>` ajusta el intervalo y deja el wallpaper actual donde está.
Hasta ahora la única forma de tocarlo era `shuffle --cada`, que además cambia el
fondo al momento: para pasar de 30 a 10 minutos había que sacrificar el que
estabas mirando.

**El mínimo son 60 s, y sale de medir.** Preparar un wallpaper va de 0,4 s a
**18,2 s** (`2637739953`: 65 pases, 196 assets, 369 MB escritos), y el `wectl
set` completo llega a ~20 s. Un minuto deja un factor 3 sobre el peor caso.

Escribirlo destapó dos fallos que llevaban ahí desde el principio:

- **`enable --now` no reinicia un temporizador que ya está activo.** Seguía
  corriendo con los parámetros del fichero anterior, así que cambiar la cadencia
  no cambiaba nada hasta la siguiente sesión —y a `shuffle --cada` le pasaba
  igual—. Se ve en que el próximo disparo se quedaba 18 686 s en el pasado. Hace
  falta un `restart` explícito del `.timer`.
- **`NextElapseUSecMonotonic` mentía.** Esa propiedad conserva el disparo con el
  que se armó el temporizador la primera vez tras el arranque: con 5,9 h de
  uptime seguía diciendo «44 min». `list-timers --output=json` sí recalcula y da
  el instante en microsegundos desde la época, que es lo que se lee ahora.

El plan **no se escribe encima del que hay**. `emit_plan` numera los ficheros
por índice y no borra lo que sobra, así que un wallpaper de 20 pases sobre uno
de 113 dejaría 93 sin usar: con `set` a mano se nota poco, rotando por la
biblioteca entera el directorio crece hasta la unión de todas. Y si la
generación falla a medias, el escritorio se queda con medio plan. Se genera en
un directorio hermano y se cambia por un `rename`, igual que `install-qml` con
la biblioteca y por lo mismo.

Eso obligó a un cambio en `emit_plan`: el plan nombra sus assets por **ruta
absoluta**, así que hay que decirle dónde van a acabar y no dónde se están
escribiendo. Sin eso el motor arranca sin encontrar una sola textura —el primer
`shuffle` de verdad salió con `sistema de particulas no abre:
.../scene.nueva/s001.psys` y un lienzo vacío—, y es un fallo que ninguna prueba
offline habría visto, porque offline el directorio no se mueve nunca.

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
  wetext.py                  capas de texto -> atlas de glifos + quads
  wevideo.py                 cabecera MP4 y encaje del vídeo en la pantalla
  werender.py                renderizador offline (escena -> PNG)
  glexec.c                   ejecutor de planes headless (EGL surfaceless)
  glslcheck.c                compila shaders con el driver real (EGL surfaceless)
  test_wetex.py              regresión de wetex
  test_wemdl.py              regresión del decodificador de mallas
  test_weglsl.py             valida la inferencia contra el corpus que compila
  test_weshader.py           regresión del traductor (combos por defecto)
  test_wescene.py            regresión end-to-end (combos reales)
  test_weparticles.py        contrato entre weparticles.py y weparticles.c
  test_wetext.py             la unidad del texto, medida contra el corpus
  test_wevideo.py            contrato del vídeo, con ffmpeg de oráculo
  test_luminancia.py         regresión de LUZ: renderiza y mide cuánta sale
  indice.py                  recalcula las líneas de NOTAS-INDICE.md
src/
  glexecutor.cpp/.h          ejecutor de planes en vivo (port de glexec.c)
  weparticles.c/.h           simulador de partículas, COMPARTIDO por los dos
  wevideo.c/.h               decodificador libav, COMPARTIDO por los dos
  sceneview.cpp/.h           QQuickRhiItem que compone la escena
  escritorio.cpp/.h          le pregunta a KWin si muestra el escritorio
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

### Los uniforms de las cabeceras no existían

Un wallpaper salió con **el fondo entero en negro y solo las partículas
encima**. La traza por objeto lo situó al pase:

```
obj 18:  escena=rgb=183.81
obj 19:  escena=rgb=0.00      <-- aqui
```

El objeto 18 es un efecto a pantalla completa: lee la escena, la desenfoca
bajando a los buffers de cuarto de resolución y la reescribe con `blend none`.
Los cuatro pases se veían bien —183, 183, 183— y el último salía en **0**. Su
última línea:

```glsl
effect.rgb *= g_CompositeColor;
```

`g_CompositeColor` no se emitía nunca, así que GL lo daba a cero y el shader
multiplicaba por cero. No hay error, no hay aviso: hay una pantalla negra.

La causa es de una línea. Los metadatos de los uniforms se leían del `.frag` y
del `.vert` **sin expandir los `#include`**, y los uniforms comunes se declaran
en las cabeceras. Si no están en los metadatos no se emiten, y si no se emiten
GL los deja a cero —que casi nunca es su valor neutro—. Son exactamente cuatro
en todo Wallpaper Engine:

| uniform | tipo | defecto | cabecera |
|---|---|---|---|
| `g_CompositeColor` | vec3 | `1 1 1` | `common_composite.h` |
| `g_CompositeAlpha` | float | `1` | `common_composite.h` |
| `g_CompositeOffset` | vec2 | `0 0` | `common_composite.h` |
| `g_RefractAmount` | float | `0.05` | `common_particles.h` |

Y no era solo el defecto: los tres primeros llevan clave de material
(`compositecolor`, `compositealpha`, `compositeoffset`), así que **el valor que
declarara el wallpaper también se estaba ignorando**.

`2868108515` pasa de media 10,64 a 142,76 —de negro con partículas a la escena
completa—. En el plan de las 125 escenas cambian 105, y solo en líneas `u1f`,
`u2f` y `u3f`: no se mueve ni un pase ni un sampler. La mayoría no cambia de
píxel, porque un uniform que el shader no usa es inerte.

Lo que sí cambia de píxel es la refracción: `g_RefractAmount` valía 0, o sea
que los sprites de refracción no desplazaban nada. Ahora desplazan. En
`2587542891` aparecen gotas sobre el cristal que antes no estaban, y **si su
intensidad es la correcta no está verificado**: el preview es una imagen fija y
no las muestra.

### Las conversiones implícitas que quedaban

De 578 variantes reales compilaban 552. Las 26 que no eran **todas** el mismo
tipo de cosa: HLSL convierte solo y GLSL no. Agrupadas por causa, y con el
arreglo al lado:

| casos | qué pasaba | qué se hace |
|---|---|---|
| 4 | `if (u_flag)`, `INVERT ? a : b` con un escalar | envolver en `bool(...)` |
| 5 | `uint b = (a + 1) % RESOLUTION` | bajar los `uint` a `int` dentro de la expresión |
| 4 | `max(0, albedo.rgb)` | el literal toma el ancho: `max(vec3(0.0), …)` |
| 2 | `mix(vec4, vec3, float)` | truncar el argumento más ancho |
| 2 | `for (int i = u_MinFreq; …)` | el init de un `for` es una declaración más |
| 2 | `v_TexCoord += …` sobre un varying | copia local dentro de `main` |
| 1 | `vec3 color = 0.0` | difusión de escalar |
| 1 | `return 0` en función `float` | literal a flotante |
| 1 | `vec2 v[] = { … }` | `#extension GL_ARB_shading_language_420pack` |

Las seis siguientes pedían **truncar el operando más ancho de una operación
aritmética** —`v_TexCoord` es `vec4` y el shader lo resta a un `vec2`—, que es
la regla general de HLSL. Esa no se puede hacer por los bordes: hay que saber
dónde empieza y acaba cada operando, y eso lo sabe el parser y no una búsqueda
plana. `weglsl` gana un modo permisivo que, en vez de responder «no lo sé» ante
anchos distintos, anota **qué tramo de tokens** habría que recortar y sigue con
el ancho menor; `truncar()` reescribe con esos tramos. El modo va tras una
bandera a propósito: el `tipo()` de siempre tiene que seguir siendo estricto,
porque es lo que hace seguro todo lo que se apoya en él.

Las seis siguientes cayeron en una tanda, y una de ellas no era nuestra:

- **`in vec4 v_Size.xy;` lo escribe el autor.** `frame_builder` de `3562154287`
  declara `varying vec4 v_Size.xy;`, con swizzle en el nombre, que no es válido
  ni en HLSL ni en GLSL; el compilador de WE se lo traga. Se sanea la
  declaración: el tipo manda y el swizzle sobra.
- **Las macros no tenían tipo.** `#define pixelSize (1.0 / g_Texture0Resolution)`
  y luego `vec2 pixelStep = saturate(depth) * pixelSize`. Sin saber que
  `pixelSize` es vec4 no hay forma de ver que falta una truncación. `weglsl`
  tipa ahora las macros sin parámetros, en dos vueltas porque unas se apoyan en
  otras.
- **Asignaciones compuestas y con swizzle.** `albedo.rgb += …` manda tres
  componentes aunque `albedo` sea vec4, y `bar *= 0.7` con `bar` entero es
  `bar = int(float(bar) * 0.7)`: hacer la cuenta en entero dejaría la barra
  entera en vez de atenuada.
- **`pow` no tiene sobrecarga escalar.** `max(vec3, 0.0)` compila y
  `pow(vec3, 0.5)` no: hay que difundir el escalar.
- **Literales enteros dentro de la expresión.** El mismo modo permisivo del
  parser que anota recortes anota ahora promociones: `1 - u_BarSpacing` sale
  como `float(1) - u_BarSpacing`. Con expresión regular ya se intentó y costó 6
  variantes; con el parser se sabe qué operando es.

Queda **1**: `maskBokeh(v_TexCoord, …)` pasa un `vec4` donde la función declara
`vec2`. Truncarlo pide las firmas de los parámetros, y hoy la tabla de funciones
solo guarda el tipo de retorno.

Dos cosas que costaron, las dos por lo mismo —tocar texto sin mirar lo que
significa—:

- **Renombrar el varying para poder escribirlo.** Parecía lo simple: declarar
  `v_TexCoord_in` y copiarlo. Pero las etapas se casan **por nombre**, así que
  el fragment dejó de recibir lo que el vertex escribía, compiló igual y
  muestreó en (0, 0). En `3555933181` eso borró el personaje y las vidrieras y
  dejó solo la lluvia. La copia va dentro de `main` y la declaración no se toca.
- **Promocionar los enteros dentro de una expresión** con una expresión regular.
  Se llevó por delante 6 variantes que ya compilaban: convertía el exponente de
  un `1e-5` y los índices de array, y dejaba `None.0` donde el grupo no casaba.
  Solo se toca el argumento que **es** un literal pelado.

Resultado: **577 de 578 en Mesa, 576 en NVIDIA** (los drivers no fallan en la
misma). De nueve escenas
renderizadas antes y después, ocho salen idénticas al píxel y la novena
—`3597772384`— pierde una **banda negra** que le cruzaba la imagen: era un pase
que no compilaba y dejaba su buffer sin escribir.

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
| `instanceoverride` | 725 | 647 partículas y 64 ocultos, **cero imágenes**. **Implementado** con el sistema de partículas: `weparticles.cargar` lo aplica sobre el `.json` del emisor. |
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
- ~~1 variante de 578 no compila~~ **hecho**: era truncación en los argumentos
  de la llamada, no solo en las asignaciones. Compilan las 594 de la
  biblioteca nueva. Y **enlazan**, que es otra cosa y costó 82 pases más
  —ver [Compilar no es enlazar](#compilar-no-es-enlazar-82-pases-que-se-perdían-sin-decir-nada)—.

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
| inicializadores | 10 | los 10 |
| operadores | 13 | los 13 |
| renderers | 4 (`sprite` 586, `spritetrail` 145, `rope` 34, `ropetrail` 32) | los 4; `rope*` con cinta propia |
| shader | **1**: `genericparticle`, en los 823 | ya compilaba |

29 piezas cubren el 100% de los 823 sistemas, y **el vocabulario está cubierto
entero**. Se simulan **821**; los 2 restantes no declaran emisor o material.

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
  el punto al cursor, y 111 de los 136 usos apuntan justo ahí. Sin puntero el
  punto se queda en el origen y el operador deja de ser una interacción para
  ser un sumidero: la nube de 512 px de radio se apelotona en una bola de 64.
  Cuando el motor en vivo sepa dónde está el puntero, entra por ahí.
- **Las texturas de partícula se suben sin voltear.** En una capa normal el
  volteo se cancela con el de las UV; en un sprite que muestrea un *rectángulo*
  de una hoja no se cancela nada.

### Estelas: `spritetrail` no necesitaba historial

Las 211 estelas del corpus parecían un solo problema —guardar por dónde ha
pasado cada partícula— y no lo eran. El shader lo dice:

```glsl
#if TRAILRENDERER
    ComputeParticleTrailTangents(a_Position, in_ParticleVelocity, right, up);
#else
    ComputeParticleTangents(in_ParticleRotation, right, up);
#endif
```

`spritetrail` —**145 de los 211**— es el mismo quad de siempre, orientado por su
velocidad en vez de por su rotación y estirado a lo largo de ella:

```glsl
right = normalize(cross(eyeDirection, v));
up    = normalize(v) * max(minlength, min(|v| * length, maxlength));
```

La velocidad ya viajaba en el vértice (`a_TexCoordVec4C1.xyz`, para el combo
`THICKFORMAT`), así que no hubo que tocar ni el simulador ni el formato del
vértice: **el combo `TRAILRENDERER` y tres números en `g_RenderVar0`**.

Lo que sí hubo que interpretar es el `maxlength` por defecto, que solo aparece en
68 de los 145. El valor que sale de ahí no son píxeles: `ComputeParticlePosition`
escala los dos ejes por el tamaño de la partícula, así que es **el largo de la
estela en anchos de sprite**. Sin tope, un sistema con `length: 1` y partículas a
250 px/s pide 250 anchos: los copos de 16 px de `2868108515` salían con rastros
de 4092. Con el tope por defecto en 1 —«tan larga como ancha»— los tres grupos
del corpus caen a la vez en un rango creíble, y para los 17 sistemas que declaran
`length: 1` el único cambio visible pasa a ser la orientación, que es la lectura
más conservadora posible.

`tools/test_weparticles.py` mide ahora el largo de cada estela del corpus con la
velocidad que declara `velocityrandom`: 61 acotadas, mediana 13 anchos de sprite,
máximo 20. Un valor por defecto mal elegido no falla, dibuja.

### `rope` y `ropetrail`: la cinta sí pide historial

Los otros 66 son lo que parecía el problema entero: una cinta cosida por donde
ha pasado cada partícula. Van por **otro shader**, `genericropeparticle`, y ese
detalle no está en el material —los 66 declaran `genericparticle`, igual que los
sprites—, así que **quien elige el shader es el renderer, no el material**.

El shader pide un elemento por segmento, no por partícula:

```glsl
vec3 CPStart = startPosition - a_TexCoordVec4C1.xyz;
vec3 trailRightStart = cross(eyeDirection, trailDelta + CPStart);
position = mix(startPosition, endPosition, uvs.y) + right * ...
```

Es decir: cada quad lleva sus dos extremos **y los dos vecinos de fuera**, que
son los que dan la tangente en cada punto y hacen que la cinta gire suave en vez
de quebrarse. De ahí sale el formato de vértice nuevo, de 26 floats
(`weparticles.h`), y el historial en el simulador: un punto cada
`length / segments` segundos, guardando posición, tamaño, color y alfa **tal como
estaban al pasar por ahí** —si se calculan al dibujar, la cola sale de color
uniforme y se apaga de golpe—. Por eso la modulación de los operadores se
extrajo a `modula()`, que ahora usan los dos caminos.

Dos cosas se pierden por usar la ruta sin geometry shader, y las dos dejaron de
importar al guardar un punto por paso de simulación —lo de abajo—: **la curva**
(el geometry shader subdivide cada segmento con una Bézier, `subdivision`, y sin
él los puntos se unen con quads rectos) y **el deslizamiento de la textura**
(`g_RenderVar0.z` es un valor por fotograma y el plan solo lleva constantes, así
que la cinta avanza a saltos de un segmento). Con segmentos de 1/60 de segundo,
ni la flecha de la cuerda ni el salto llegan a un píxel.

Se ve en la escena de descargas de `1927028828`: antes salían **dos barras
blancas rectas y macizas** cruzando el mecha —cada partícula estirada por su
cuenta, geometría perfecta y resultado absurdo— y ahora son arcos que siguen el
recorrido.

Verificación sobre las 125 escenas: cambian **25 planes, y las 25 tienen cintas**;
de las 28 con `rope*`, las 3 que no cambian están explicadas —dos las traen
desactivadas por una opción del usuario (`trail`, `mousetrail`) y en la tercera el
renderer efectivo es otro—. Renderizadas seis de las más cargadas, ninguna se
mueve más de un 1% de sus píxeles salvo `3219398263`.

**Y esa destapó dos lecturas equivocadas**, las dos sobre cuánto se mueve una
partícula, que como sprite no se notaban y como cinta saltan a la vista.

**El `vortex` estaba inerte en 9 de sus 12 usos.** El operador gira la partícula
alrededor de un eje con un producto vectorial, y `axis` no se declara casi
nunca: con el eje a cero no mueve nada. Los 2 que sí lo declaran escriben
`0 0 1`, y la escena es plana, así que el eje por defecto es Z.

Pero ponerle el eje no bastaba: sumado a la velocidad, la partícula acumula
tangencial sin nada que la retenga y la órbita se abre en espiral —las cintas
de `3219398263` acababan cruzando el cielo entero—. Y **fijar** la velocidad
tampoco vale: con `speedouter: 0`, que es lo que declaran los pétalos de
`2788036464`, congelaría todo lo que cae fuera del radio. La lectura que
sostiene los cuatro grupos del corpus a la vez es **arrastre**: mueve la
posición y deja la velocidad como estaba.

Aquí conviene decir cómo casi se descarta. La versión de arrastre subía la media
de la escena de 85 a 110 y la di por peor sin mirarla; la imagen tenía las
estelas rodeando la esfera igual que el preview, y la media era más alta
justamente porque se concentran en un halo en vez de repartirse por el cielo.
La media es una cifra y una escena es una imagen.

**`length` no es el espaciado entre puntos de la cola.** Repartirlo
—`length / segments`— da 3 segundos por segmento en las `star trail` de
`3238423642`, que declaran `length: 30`: cada segmento se vuelve una cuerda
recta de cientos de píxeles y la escena se llena de líneas quebradas de colores
que su preview no tiene. Con **un punto por paso de simulación** las tres
escenas de referencia caen a la vez donde su preview dice: las estelas de
`3219398263` rodean la esfera, las descargas de `1927028828` siguen sus arcos y
las estrellas desaparecen. `length` queda como tope de la duración de la cola,
que en este corpus no llega a recortar a nadie.

Sobre los 821 sistemas: **754 quedan idénticos** y los 67 que cambian son los 66
de cinta más los del vórtice.

### Repartir por puestos: el rayo

`mapsequencebetweencontrolpoints` no es un parámetro, es otro modelo de
colocación: en vez de dejar la partícula donde cayó el emisor, la pone en un
**puesto** del camino que trazan los puntos de control. Los 11 usos del corpus
son el mismo preset —la `Discharge` de cinco escenas— con `count: 10` y
`limitbehavior: mirror`, y con cp0 en el origen y cp1 a (512, 512).

Sin él, las partículas se apelotonaban en los 64 px del emisor; con él salen
repartidas de esquina a esquina, que es lo que hace que un rayo parezca un rayo.
Lo que el emisor sorteó se conserva como sacudida alrededor del puesto.

### El corro, el ruido y una orientación que ya estaba bien

Los tres cabos que quedaban del vocabulario. Los tres se cerraron leyendo el
JSON con cuidado, y en dos de ellos **lo que bloqueaba era una lectura mía
equivocada**, no el formato.

**`mapsequencearoundcontrolpoint`, 3 sistemas.** La nota decía que uno apuntaba a
(0, −9999, 0) y que convenía entenderlo antes de conectarlo. Es falso: ese es el
**punto 1**, y ninguna de las tres piezas declara `controlpoint`, así que las
tres usan el **0**. A (0, −9999, 0) no apunta nadie en esas escenas. El susto era
de un campo que nadie lee.

Es el hermano del reparto por camino: aquel reparte por una recta y este por un
**corro**. El puesto no da posición —no hay campo de radio en ninguno de los tres
usos— sino un **ángulo**, y lo que se gira es la velocidad inicial: `count: 5`
con `speedmin = speedmax = (0, 100, 0)` son cinco chorros a 72°. El giro es
alrededor de Z por lo mismo que en el vórtice, porque la escena es plana.

`bounds` (`"0 1"`) y `limitbehavior` (`repeat`) son el corro entero y dar la
vuelta: los dos valores neutros. Se leen igual, para que el campo signifique algo
en vez de estar ignorado.

**`remapvalue`, 2 operadores en un sistema.** La lluvia de `3597772384`, que
**no tiene `velocityrandom`**: sin esta pieza las gotas nacían quietas y solo las
movía la gravedad, con la caja de velocidades que declara el autor sin usar. Dos
lecturas, las dos por la magnitud de los números:

- **La entrada es la fracción de vida, no la posición.** `transforminputscale`
  vale 10 y 8; sobre píxeles eso es ruido blanco por partícula, mientras que
  `turbulence` —que sí muestrea la posición— escala por 0.01. Sobre la vida, 10
  son diez unidades de ruido a lo largo de la gota.
- **`speed` multiplica y `velocity` fija.** El rango de `speed` es −5 a 7, cuyo
  centro es exactamente **1**: el neutro de un factor. Leerlo como rapidez
  absoluta dejaría las gotas a 1 px/s y volvería inútil al operador anterior, que
  es el único que da velocidad al sistema. Un autor no encadena dos operadores
  donde el segundo anula al primero.

`flags` (3 en uno, ausente en el otro) no se lee: con un solo uso de cada canal
no hay forma de saber si es él quien decide, y no el canal.

Esto **no se puede comprobar en un PNG**: la capa es sutil, las gotas que se ven
en el render son de otros sistemas de la escena y el diff entre antes y después
son 1702 píxeles de 8,3 millones. Lo que hay que mirar son las velocidades, y
para eso está `tools/psysprobe.c` —`make psysprobe`—, que corre el mismo
simulador sin GL de por medio. A los 10 s:

```
antes    velocidad media (0.0, -229.0)   max 480    x [-1984, 1954]
después  velocidad media (-4.4, -555.0)  max 3192   x [-2261, 1772]
```

La lectura está en las tres columnas. La media pasa a ser el **centro de la caja
declarada** (0, −550). El máximo, 3192, no cabe en la caja —cuya esquina son
1020 px/s—, así que solo se explica con el factor de ráfaga. Y la x de antes es
**exactamente la caja del emisor** (±2000), la firma de que no había ni una
pizca de velocidad lateral; ahora se sale de ella, que es la deriva de ±200 que
el JSON pedía.

Los pétalos de `2788036464` cuentan lo mismo: de rapidez media 26 y máximo 43,
todo gravedad, a media 57 y máximo 99 —los 100 px/s declarados—, y con la media
en x clavada en 0.0, que es lo que tiene que dar la suma de cinco chorros
repartidos en un corro.

**`orientation: fixed`, 1 sistema.** No había nada que hacer, y esa es la
conclusión. `ComputeParticleTrailTangents` calcula `right = cross(vista,
velocidad)` con la vista en −Z; el eje fijo del `spritetrail` de `Magic_Vortex`
es (0, 0, 1), o sea el mismo vector cambiado de signo, y eso da **el mismo quad
con la u espejada** sobre un halo con simetría de giro. Ya se estaba dibujando
así, en silencio.

Lo mismo vale para los otros dos valores del campo: `screen` orienta al plano de
pantalla y `upright` clava el eje vertical al del mundo, y sin rotación de cámara
los dos son el billboard que ya hacemos. `orientation` es, en una escena plana,
un campo sin efecto —salvo con un eje fijo que no sea paralelo a Z, que el corpus
no tiene, y ahí `_orientacion` sí avisa.

La excepción es la **cinta**: su anchura no la calcula el shader de WE sino
nuestro constructor de vértices, que la pone perpendicular al camino. El `rope`
de *Vapor 1* con `upright` sigue anotado, y es lo único del corpus que queda
fuera junto con un emisor extra en dos sistemas.

**Corregido después:** lo de la cinta era falso. Su anchura la calcula
`genericropeparticle.vert` con `g_OrientationForward`, y WE pone ese uniform con
la misma rutina para los cuatro renderers; con `upright`, en el corpus, sale la
base de siempre. Ver [`upright` en una
cinta](#upright-en-una-cinta-we-la-orienta-como-a-un-sprite-y-da-la-base-de-siempre).

**Verificación.** De los 823 sistemas, **819 dan un `.psys` idéntico byte a byte**
y los 4 que cambian son exactamente estos. Comparar el `.psys` antes que el PNG
es lo que hace la comprobación barata: es el contrato entero del sistema, y
generar los 823 cuesta segundos en vez de la media hora de renderizar el corpus
dos veces.

Sobre las 125 escenas renderizadas antes y después, **122 salen idénticas byte a
byte** y las que cambian son *Magic_Vortex* y la lluvia. Los dos sistemas de
pétalos no aparecen: sus objetos vienen con `visible: false` —son efectos de
cursor que el usuario enciende—, así que ahí la sonda es la única forma de verlos.

Queda un cabo que no es nuestro: **`3097749052` no renderiza igual dos veces**.
Renderizado dos veces con el mismo binario cambian 23 850 píxeles dentro de un
recuadro de 210×430, así que aparece como falso positivo en cualquier regresión
byte a byte. Es anterior a este trabajo y no tiene que ver con partículas.

El reparto por puestos se refactorizó para compartir el recorrido con el corro;
las dos escenas que lo usan —`1927028828` y `2658583633`— renderizan idénticas.

## La pausa mide cobertura, no una bandera

Preguntar «¿está maximizada la ventana activa?» falla en tres casos que se dan a
diario: **dos ventanas en mosaico** que entre las dos tapan la pantalla y
ninguna está maximizada ---un PDF y una consola, medido: el motor al **98,2%**
del i915 sin que se viera un píxel del fondo---, **una ventana pequeña activa
encima de una maximizada**, y **una redimensionada a mano** hasta cubrirlo todo.

Ahora se mide cuánta pantalla queda tapada: una rejilla de 32x18 sobre el área
útil, comprobando el **centro** de cada celda contra los rectángulos de las
ventanas visibles. El centro y no el solape: contar una celda por rozarla
inflaría la cobertura y pararía el fondo con una ventana pegada al borde. La
referencia es el área útil ---la pantalla menos los paneles, vía
`availableScreenRect` del containment--- porque el fondo bajo un panel opaco no
se ve; sin ella, una maximizada se queda en el 94% y el umbral habría que
aflojarlo hasta dejar pasar huecos de verdad. Se pausa por encima del **92%**.

**Dos condiciones, y cada una tapa el agujero de la otra**: la ventana activa
dice si estás mirando algo, y la cobertura si eso que miras deja ver el fondo.
Con la activa sola, el mosaico no paraba nada; con la cobertura sola, el
escritorio a la vista tampoco arrancaba.

### Lo que el modelo de tareas no dice, y cómo se supo

Instrumentando la decisión con el estado de cada ventana salieron dos hechos que
no se pueden deducir de la documentación:

- **Minimizar sí se marca.** Al minimizar de verdad, el modelo pasa a decir
  `Google Chrome MIN OCULTA`, así que la cobertura excluye esa ventana y el
  fondo despierta. Medido: **95,3%** del motor con todo minimizado.
- **«Mostrar el escritorio» no se marca.** KWin aparta las ventanas pero el
  modelo las sigue dando con su geometría intacta, sin `MIN` ni `OCULTA`, y
  encima conserva la ventana activa:

      CachyOS Hello [560,303 800x594]; Dolphin [480,0 960x1168];
      Google Chrome ACTIVA [0,0 1920x1168]; Konsole [0,0 1920x1168]; ...

  Con esos datos la cobertura sale del 100% y el fondo se queda congelado justo
  cuando lo estás mirando.

Por eso `src/escritorio.cpp` le pregunta a **KWin por D-Bus**
(`org.kde.KWin.showingDesktop` y su señal), que es quien lo sabe, y lo publica a
QML. Si KWin no responde ---otro compositor, D-Bus caído--- se queda en `false`
y el motor se comporta como antes. QML no habla D-Bus; por eso vive en el C++.

| situación | antes | ahora |
|---|---|---|
| PDF a media pantalla + consola detrás | 98,2% | **0,1%** |
| todo minimizado | — | **95,3%**, dibuja |
| KWin mostrando el escritorio | congelado | dibuja |

**Trampa que costó una medida engañosa:** plasmashell compila el QML al arrancar
y lo sirve de memoria, así que un cambio en un `.qml` **no se ve con `wectl
set`** ---hay que reiniciar la sesión, igual que con la `.so`---. Durante un rato
estuvimos midiendo la lógica vieja creyendo que era la nueva; lo delató que el
proceso llevaba dos días vivo y su caché de QML tenía esa misma fecha.

## No dibujar lo que no se ve

Un fondo tapado es el gasto más fácil de quitar, y no era pequeño: medido con
`/proc/<pid>/fdinfo` del i915, plasmashell pasa de **98,4 % a 0,0 %** del motor
de render de la Intel cuando el fondo se pausa.

Parar el reloj es lo único que hace falta. `SceneView` solo pide un fotograma
cuando `time` cambia, así que sin reloj no se ejecuta un solo pase; Qt sigue
componiendo la última textura, que no cuesta nada.

Quién decide es `plugin/contents/ui/VentanasEncima.qml`, con el modelo de
`org.kde.taskmanager` —el mismo del gestor de tareas— filtrado por pantalla,
escritorio virtual y actividad. **No se puede probar fuera de plasmashell**: en
Wayland ese modelo habla por `plasma-window-management`, que KWin solo expone a
clientes autorizados, y en un arnés suelto devuelve cero ventanas siempre.

Tres cosas salieron mal antes de dar con la buena, y las tres se ven desde el
HUD, que por eso muestra el estado, el reloj y el recuento de ventanas:

- **Pausar antes del primer fotograma deja el fondo NEGRO, no congelado.** Sin
  reloj no cambia `time`, sin cambio de `time` no hay `update()`, y el plan no
  llega a cargarse: basta arrancar la sesión con una ventana ya maximizada.
  `SceneView` expone ahora `dibujado`, y la pausa espera a que sea cierto.
- **`running` no es `paused`.** Parar la animación y volver a arrancarla la
  reinicia; el fondo se quedaba congelado al destapar el escritorio. Con
  `paused` el tiempo se queda quieto y al reanudar sigue donde estaba —que
  además protege al simulador de un salto de reloj.
- **«¿Hay alguna ventana maximizada?» es la pregunta equivocada.** Al llegar al
  escritorio con *Mostrar el escritorio*, minimizando o cambiando de escritorio
  virtual, esas ventanas **siguen siendo maximizadas** para KWin: el fondo se
  quedaba en pausa justo cuando hay que dibujarlo. La pregunta buena es qué
  estás mirando, o sea la ventana **activa**.

Un aviso sobre medir esto: btop y compañía dan el uso **global** de la GPU, no
el del fondo. Con la pausa funcionando, btop marcaba movimiento y el desglose
por proceso lo explicaba —Chrome al 56,7 %, plasmashell a cero—. Y ojo con
`fdinfo`: hay que sumar por **cliente DRM**, no por descriptor; un proceso abre
el mismo cliente varias veces.

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

## La turbulencia no turbulaba

El humo se abría como un pufo en todas direcciones en vez de salir del cañón, y
la dirección no la fija ningún campo de dirección: la fija el **campo de ruido**
de `turbulentvelocityrandom`, que da la velocidad inicial ---120 a 160 en el
humo de Sniper Girl, frente al ±50 de `velocityrandom`---.

El ruido del simulador tiene celda de **1 unidad**, y el `scale` que declara WE
no viene en esas unidades. Con los valores reales del corpus el emisor abarcaba
una **mediana de 102 celdas y hasta 750**: dos partículas nacidas juntas salían
en direcciones sin ninguna relación. Eso no es turbulencia, es una dirección al
azar por partícula, y de paso hacía que `scale` no cambiara nada en **128 de 140
sistemas**. Un campo del formato que nunca altera el resultado es la señal de
que se está leyendo mal.

Medido con `psysprobe`, la coherencia ---|velocidad media| / rapidez media--- del
humo de Sniper Girl era **0,08**. Con el factor sube a **0,72**: el chorro sale
del bocacho a −12,6° (hacia delante y algo abajo, +35 y −8 px de lienzo por
segundo ya con la rotación y la escala del objeto aplicadas).

**El factor está calibrado, no leído de WE.** La dirección que sale no depende
de él ---0,01, 0,05 y 0,1 dan los mismos −12,6°---; lo que cambia es cuánto se
abre el penacho, y ahí se eligió mirando: 0,01 deja las partículas tan paralelas
que se ven como una raya de humo, 0,1 lo abre de más. Sobre los 136 sistemas del
corpus con turbulencia, 0,05 reparte así: **57 en chorro (>0,7), 38 en penacho
(0,3–0,7) y 41 esparciéndose (<0,3)**, que es lo que dicta el `scale` y el tamaño
de cada emisor.

**La dirección concreta la pone nuestro ruido, no el wallpaper.** Aquí se
escribió que eso no tenía arreglo porque el formato no traía ningún campo de
dirección. **Corregido después:** sí lo trae. WE lee `forward` (defecto
`0 1 0`) y `right` (`0 0 1`), y no saca la dirección de un campo de ruido en el
espacio. Gira `forward` alrededor de `right` un ángulo que sale de un ruido en
el **tiempo**, y su `offset` es ese ángulo, no un desplazamiento del punto de
muestreo. `up` no lo lee. Está en [Los ejes de la
turbulencia](#los-ejes-de-la-turbulencia-forward-gira-alrededor-de-right-y-up-no-se-lee),
leído en `wallpaper64.exe`, y desde [La turbulencia con la regla de
WE](#la-turbulencia-con-la-regla-de-we-turbulentvelocityrandom-deja-de-muestrear-nuestro-ruido) es lo que se
aplica. Lo de abajo era la regla de aquí hasta entonces: el
rotacional de un ruido 3D, con `scale`, `speedmin`/`speedmax` y un `offset`
que desplaza el punto de muestreo. Con ella, lo que sí vuelve a depender del
wallpaper es el carácter del efecto. Si hiciera falta apuntar un penacho
concreto, la palanca del propio formato es ese `offset`: medido sobre este
humo, (0,0,0) da −12,6°, (5,0,0) da −48,5° y (10,10,0) da +120,5°.

El factor vive en `weparticles.py` y no en el `.c` por dos razones. La primera
es de reparto: convertir las unidades del formato es interpretar el formato, y
eso es trabajo de Python; el simulador ejecuta el número que le llega. La
segunda es práctica: **plasmashell conserva mapeada la `.so` con la que
arrancó**, así que un cambio en el `.c` no se ve hasta reiniciar la sesión,
mientras que uno que viaja en el plan entra con el siguiente `wectl set`.

Está calibrado, no leído de WE: se eligió para que la mediana del corpus caiga
en ~1 celda, que es donde la turbulencia se ve como turbulencia. Si hiciera
falta afinarlo es un solo número.

## Medir la luz, no solo que el plan se genere

`tools/test_luminancia.py` renderiza las 125 escenas y mide cuánta luz sale.
Existe porque el resto de la batería comprueba que el plan se genere y que los
shaders compilen, y con eso una escena puede quedarse **negra sin que nada
proteste**: las tres que rescató el arreglo del parallax llevaban meses así.

Mide tres cosas por escena, y las tres hacen falta:

- **media** — separa «negra» de «oscura pero viva».
- **p99** — una escena legítimamente nocturna tiene brillos; una rota es plana.
  Sin este dato, un cielo estrellado y un fallo se parecen.
- **fracción de píxeles bajo 8** — con la media sola, un destello en una esquina
  disimula un lienzo apagado.

**El criterio no es un umbral absoluto, y averiguarlo costó dos falsos
positivos.** Con un umbral en 25 caían 16 escenas; bajándolo a 8 quedaban seis,
y dos de ellas ---`Dark Queen [4K]` con 4,23 de media y `Samurai - Cyberpunk
2077` con 5,39--- **están perfectas**: son obras deliberadamente negras, con una
corona o un demonio encendidos sobre penumbra, y nuestro render coincide con el
preview del autor. Cualquier umbral absoluto que cace las rotas se lleva por
delante el arte oscuro, porque las rotas miden 0,00–4,07 y estas 4,23–5,39.

Lo que sí separa es comparar contra el **preview del autor**, que es un fotograma
de la escena tal como debe verse. La razón `nuestro / preview` deja los dos
grupos sin solapamiento:

| escena | nuestro | preview | razón | |
|---|---|---|---|---|
| `2968771936` | 0,00 | 144,63 | **0,00** | rota |
| `3577990983` | 1,95 | 68,07 | **0,03** | rota |
| `1518454472` | 3,88 | 70,09 | **0,06** | rota |
| `3624053922` | 4,07 | 70,67 | **0,06** | rota |
| `3459506773` | 4,23 | 11,32 | 0,37 | arte oscuro, correcta |
| `2311315748` | 5,39 | 21,29 | 0,25 | arte oscuro, correcta |

Se marca apagada por debajo del **15%** de su preview. El preview es material del
autor ---a veces un recorte o arte promocional en vez de una captura fiel---, así
que la razón es aproximada y el umbral, generoso; sin preview se cae al criterio
absoluto de media < 8. La mediana del corpus está en 74 de media.

Con ese criterio, tras el arreglo del parallax quedan **las cuatro escenas
negras ya conocidas y ninguna más**: las dos que el umbral absoluto señalaba de
más resultaron estar bien.

La referencia no se guarda en el repositorio, porque depende de qué wallpapers
tenga cada uno: se genera en local con `--guardar` y se compara contra sí misma
con `--referencia`. Y `--desde` reanaliza una medida ya hecha sin volver a
renderizar, que cuesta seis minutos.

## Tres escenas negras por un `normalize(0, 0)`

`云霓琼宇4K(有声)` (`3077334064`) se preparaba **sin una sola queja** ---11 pases,
cero shaders perdidos, cero texturas ausentes, ninguna nota--- y salía negra:
luminancia media 18 de 255. Es el tipo de fallo que la regresión no ve, porque
comprueba que el plan se genere, no que la imagen tenga luz.

Bisecando con `--passes`, hasta el 8 la escena está bien (83,2) y el pase 9 la
apaga. Ese pase es `depthparallax`, y su vértice hace esto **sin ninguna guarda
de combo**:

```glsl
mat3 rot = CAST3X3(g_EffectTextureProjectionMatrixInverse);
vec2 projectedDirX = mul(vec3(1.0, 0.0, 0.0), rot).xy;
projectedDirX = normalize(projectedDirX);
```

No emitíamos esa matriz, GL la da a cero, los ejes salen `(0,0)` y `normalize`
hace **0/0**. El NaN viaja por `v_ParallaxOffset` hasta las coordenadas de
muestreo del fragmento y Mesa devuelve negro. Es la misma familia que el NaN de
`g_TexelSize`: un uniforme sin emitir, una división indeterminada, y de ahí en
adelante manda el driver.

Se emiten ahora las dos matrices como **identidad** ---la escena es plana y mira
al lienzo de frente, igual que `g_Orientation*`--- y `g_ParallaxPosition` al
**centro**, que es el reposo mientras el motor no sepa dónde está el puntero.

Medido sobre las 125 escenas, siete declaran la matriz inversa sin recibirla, y
renderizando cada una con y sin el arreglo:

| escena | antes | después |
|---|---|---|
| `2810252468` | 11,3 | **64,7** |
| `3053927686` | 4,3 | **39,3** |
| `3077334064` | 18,0 | **83,1** |
| `2349856302` | 79,0 | 82,5 |
| `3237641967`, `3299228616`, `3555933181` | igual | la declaran en rama muerta |

**Tres escenas negras recuperadas**, y las dos primeras no estaban ni en la lista
de sospechosas.

Un aviso de método: al principio se leyó como un fallo de valores por defecto,
porque el plan emitía `g_Scale 1 0` y `g_Sensitivity 0` mientras el shader
declara `"1 1"` y `1`. **No lo era**: esos valores los pone el propio wallpaper
en su `constantshadervalues` (`{"center": 0.3, "scale": "1 0", "sens": 0}`), o
sea que el autor dejó el parallax con sensibilidad cero y el efecto no hace nada
tampoco en WE. Corregirlos por separado no cambiaba el negro; el NaN era todo.

## Imitar el humo de WE con una captura por oráculo

Una captura de *Wallpaper Engine* corriendo en Windows es el mejor oráculo que
ha tenido este proyecto: es la escena real, en movimiento, no un promo. Para que
sirva hay que saber qué trozo del lienzo enseña, y eso se localiza por
correlación normalizada barriendo tamaño y origen: la captura cubría
**2320x1380 desde (128, 0) con 0,927**, que es el recorte «cubrir» de un panel
16:10. A partir de ahí las dos imágenes se comparan píxel a píxel.

**Cuidado con medir sobre el arma.** La primera medida daba un trazo 3:1 con
pico 238, y era mentira: dos píxeles de desalineo convierten la silueta del
rifle en «humo». Enmascarando lo que no es fondo claro y ciñendo la caja al
bocacho, la voluta de WE resulta ser compacta ---unos 150x65 px de lienzo---,
centrada **87 px por detrás** del emisor y 15 por encima, con lóbulos visibles.

De ahí salieron dos fallos:

- **El ruido se muestreaba en coordenadas locales.** El simulador solo conoce la
  posición de la partícula dentro de su sistema, y todos nacen alrededor de su
  propio (0,0,0), así que **todos los sistemas del corpus muestreaban la misma
  zona del campo y salían en la misma dirección**, fuera cual fuera el
  wallpaper. Desplazando el muestreo por el origen del objeto ---dato del
  wallpaper--- cada sistema coge la suya y los dos humos de esta escena dejan de
  correr en paralelo. El penacho pasa de +30 px por delante del bocacho a −102
  por detrás, contra los −87 de WE.
- **El sprite se estiraba con la escala no uniforme del objeto.** La MVP escala
  x e y por separado (0,25 y 0,5 aquí) y eso convertía cada sprite en 150x300 px
  cuando **la voluta entera de WE mide 150x65**: el ancho ya coincidía ---es
  `size` por la escala en X--- y el alto no. Compensando el eje vertical en
  `g_OrientationUp`, el quad sale cuadrado y las posiciones siguen respetando la
  escala del autor. Afecta a **322 de los 823 objetos de partículas del corpus,
  en 61 escenas**.

Lo que sigue sin cuadrar es la dispersión: la nuestra se abre más. Con una vida
efectiva de ~2 s el parecido es notable, pero el preset declara 3–4 s y no hay
con qué justificar ignorarlo. La hipótesis pendiente es que WE recicle la
partícula más vieja al llenarse el cupo ---con `rate 10` y `maxcount 12` daría
1,2 s---, pero con 1,2 s el humo sale demasiado pequeño, así que no encaja del
todo y se queda anotada.

## El humo que no se apagaba

El humo de *Sniper Girl* salía como una neblina ancha que velaba el rifle,
cuando en Wallpaper Engine es una voluta compacta sobre la recámara. No era el
tamaño del sprite: 600 unidades por la escala 0,2 del objeto son 120 px de
lienzo, y la voluta del preview mide unos 60, que es una partícula al 40% de su
crecimiento. Lo que sobraba era **cuánto tiempo seguían viéndose las viejas**,
que son justo las más grandes porque `sizechange` las hace crecer con la edad.

El preset declara `alphafade` con solo `fadeintime`. Dábamos `fadeouttime = 1`
por defecto, que en nuestra implementación significa *no apagarse nunca*: cada
voluta moría a plena opacidad y con el tamaño máximo. El valor por defecto es
**0** —se apaga desde que nace—, y con eso el alfa dibuja una campana que
culmina a mitad de vida y se cierra al final.

**Cómo se comprobó, que es lo que hace la diferencia entre saberlo y suponerlo.**
El `preview.jpg` que sube el autor es un fotograma de WE, así que sirve de
oráculo si se sabe qué trozo del lienzo cubre. Se localiza por correlación
normalizada barriendo escala y desplazamiento: sale un recorte de **1040x1040
en (112, 384) con correlación 0,929**, o sea casi 1:1. Recortando nuestro render
por esa misma ventana las dos imágenes se comparan pixel a pixel, y ahí se ve
que con el apagado el arma queda nítida igual que en WE.

Se descartó una segunda lectura del campo ---que `fadeouttime` fuera la
DURACIÓN del apagado y no el instante en que empieza---. Para el caso omitido da
exactamente lo mismo, pero además reinterpretaría los 244 sistemas que sí lo
declaran, y no hay con qué comprobarlo: los valores más usados admiten las dos
lecturas sin chirriar, y entre los que usan valores bajos hay estelas de ratón y
gotas de lluvia, que con la lectura de duración se cortarían en seco. Cambiar
solo el valor por defecto toca **236 de los 480 `alphafade` del corpus, en 87
escenas**, y deja intactos los que declaran el campo.

De paso, el guardia `v[1] > 0` del simulador ignoraba un `fadeouttime`
declarado como 0. Es un preset en todo el corpus ---`shurikencursor_1`, que pide
`0.0` en los dos campos--- y no se apagaba pese a pedirlo. Ahora el guardia
admite el cero, que con el valor por defecto nuevo es además el caso común.

## El relleno a potencia de dos estaba en los píxeles

*Sniper Girl* salía en un recuadro que ocupaba parte de la pantalla, con el
resto negro y las partículas flotando por fuera. Parecía un fallo de encaje y
no lo era: el `.tex` del fondo es un contenedor de **4096x2048 con la imagen
real de 2560x1440 pegada a la esquina superior izquierda** y el resto a alfa
cero. Subíamos el contenedor entero, así que las UV 0..1 de la capa recorrían
también el relleno y la escena quedaba en **0,625 x 0,703** de su sitio ---los
dos cocientes `image_size / texture_size`, y exactamente el recuadro que se
veía---.

Las partículas no encogían porque su colocación no pasa por esa textura: por
eso el síntoma parecía de composición y no de textura.

La convención la documentan los propios shaders de WE:
`g_TextureNResolution = (texW, texH, imgW, imgH)`, y quien la respeta escala sus
UV con `.zw / .xy` (`genericimage4.vert:183`, `common_particles.h:71`). Nosotros
emitíamos el mismo par dos veces, o sea proporción 1.

**El arreglo es recortar, no pasar la proporción.** Recortar funciona con
cualquier shader: el que escala obtiene 1 y muestrea la textura entera, que ya
es la imagen; y el que no escala ---el pase base usa `a_TexCoord` tal cual---
también acierta. Pasar la proporción solo arregla a los primeros. Se recorta
antes del volteo, porque la imagen va arriba en el orden en que WE la guarda.

Medido sobre el corpus:

| | |
|---|---|
| texturas con `image_size` != `texture_size` | 939 de 1897 (49,5%), en 119 de 125 escenas |
| con el relleno **en los píxeles** (mipmap mayor que la imagen) | 335 |
| escenas que cambian de plan tras el arreglo | **40**, con 85 idénticas y **0 rotas** |
| VRAM de las texturas rellenadas | 2302 MiB → 1509 MiB (**34% menos**) |

**Recortar por la esquina superior izquierda es una suposición, así que se midió
antes de fiarse.** De las 335, las **253 con relleno grande** (>64 px en algún
eje) no tienen **ni un píxel** con estructura fuera del recorte: es relleno
plano y la imagen va pegada arriba a la izquierda. Las 82 restantes tienen
márgenes de 64 px o menos ---alineación de bloque BC--- y 62 sí llevan
contenido ahí, que es la continuación del borde que mete el compresor; también
ahí manda `image_size`, que es lo que WE muestrea. O sea que la suposición
falla en cero casos donde importaría.

El comentario de `info_textura` ya sabía del relleno pero daba por hecho que «lo
que subimos a GL es la imagen». Era verdad a medias: en unas texturas el mipmap
ya viene recortado y en otras no. Las dos formas se cubren con el mínimo entre
el mipmap y `image_size`, que es lo que acaba en la GPU.

## Encajar el lienzo en la pantalla

La escena se dibuja al tamaño del lienzo que declara su autor
(`orthogonalprojection`), no al de la pantalla, y los dos casi nunca coinciden.
Medido sobre las 125 escenas contra un panel de 1920x1200:

| | |
|---|---|
| escenas en 16:9 | **99 de 125** — contra un panel 16:10 son 10% del ancho recortado, 5% por lado |
| área recortada, mediana | 10,0% |
| lo peor | `2946362143` (564x1120) pierde el **68,6%**; `2866586232` (1440x2560) el 64,8% |
| lienzos mayores que la pantalla | **90 de 125**: 53 a 3840x2160 y 4 a **7680x4320**, 33,2 Mpx para enseñar 2,3 |

Hasta aquí el encaje era una línea: `glBlitFramebuffer` con
`scale = max(viewW/w, viewH/h)`, o sea recorte central, siempre y sin opción.
Ahora los tres modos —cubrir, entera con barras, estirar— salen de la misma
cuenta cambiando solo cómo se elige la escala, más un zoom y un desplazamiento
del recorte, todo desde la configuración del plugin.

Tres cosas que no son obvias:

- **Las barras las pinta el motor, no el QML de debajo.** El item se compone con
  `setAlphaBlending(false)` —que es lo que evita que los bordes de la escena se
  oscurezcan dos veces—, así que lo que el motor no pinte sale negro, no
  transparente: el `Rectangle` con el color de fondo no se ve nunca.
- **El recorte solo tiene un grado de libertad.** Con `cubrir`, una escena más
  ancha que la pantalla se recorta a lo ancho y se ve entera a lo alto: ahí el
  desplazamiento vertical no mueve nada, y por eso los deslizadores se apagan.
  Con zoom hay holgura en los dos ejes. La prueba de encaje comprueba las dos
  cosas, incluida la de que **no** se mueva cuando no debe.
- **Esto no bajaba lo que cuesta dibujar**, y esa era la fase que faltaba: se
  renderizaban los 8,3 Mpx del lienzo 4K para enseñar 2,3. Ya no —ver [Dibujar
  a la resolución que se ve](#dibujar-a-la-resolución-que-se-ve)—, pero el
  motivo por el que no bastaba con escalar en el ejecutor sigue en pie: la
  resolución es un parámetro del *plan*, porque `g_TexelSize`, `g_Screen` y los
  tamaños de buffer se hornean en Python.

El código nuevo no se ve hasta que plasmashell reinicia: `install-qml` instala
con un rename, así que el proceso sigue con el inodo viejo mapeado —que es
justo lo que evita el SIGBUS— y con él, con el `.so` anterior.

## La última variante que no compilaba: truncar también al llamar

Quedaba 1 de 594. El error:

```
albedo = vec4(maskBokeh(v_TexCoord, depth * 2.0 * strength), albedo.a);
error C7011: implicit cast from "vec4" to "vec2"
```

`v_TexCoord` es un `vec4` porque ese shader empaqueta más cosas en el `zw`, y
`maskBokeh` pide un `vec2`. HLSL trunca solo al pasar el argumento; GLSL lo
rechaza y se lleva el pase entero.

Ya existía `truncar_asignaciones` para el mismo problema en los inicializadores.
Faltaba el caso de los **argumentos de una llamada**, y se resuelve igual, con
la misma regla que hace segura a su hermana: **solo se toca cuando el ancho se
puede AFIRMAR** y es mayor que el del parámetro. `weglsl` devuelve `None` ante
la duda —incluidas las variables locales, que aquí no se siguen— y entonces el
argumento se deja como está.

Esa disciplina no es adorno. Un intento anterior de inferir anchos barriendo
identificadores con una expresión regular rompió 124 variantes, porque un
barrido plano cree que `dot(a, b)` es ancho. El oráculo es el corpus que ya
compila, y hay que pasarlo entero **antes** de dar el cambio por bueno.

Para saber qué espera cada parámetro se añadió `weglsl.tabla_de_parametros`,
que devuelve `None` en las posiciones que no sabe medir —un array, una
estructura, un tipo desconocido— para que el que llame las deje en paz.

**Resultado: 594/594 en Mesa, el 100 %.** Las cuatro escenas que incrustan ese
efecto recuperan su desenfoque bokeh; la media apenas se mueve porque un
desenfoque no cambia el brillo, pero dejan de omitir el pase.

Queda **una en NVIDIA**, que Mesa acepta: `step(0.5, nodeNum)` con `nodeNum`
declarado `in int` como parámetro de función. Para arreglarla harían falta dos
extensiones del parser —ámbito local de función, y una tabla de firmas de los
built-ins— y es una variante en el driver que no es el del escritorio.

## El `exponent` de los sorteos: leído, y la curva elegida mirando la vela

Los inicializadores aleatorios de una partícula declaran `min`, `max` y a veces
`exponent`. Nosotros leíamos los dos primeros y tirábamos el tercero: **96 usos
en la biblioteca**, repartidos por seis inicializadores —`alpharandom` 38,
`sizerandom` 33, `lifetimerandom` 15, `velocityrandom` 6, `colorrandom` 3,
`rotationrandom` 1—. Ignorarlo reparte plano lo que el autor pidió sesgado.

Los valores del corpus son todos enteros: 1 (la mitad, o sea neutro), 2, 3, 5 y
9. Así que 1 es el valor por defecto y el sesgo crece desde ahí.

Ahora viaja hasta el simulador y se aplica como `pow(t, exponent)` sobre el
sorteo. Cuidado con dos cosas al añadirlo, porque el `.psys` es una lista de
números sin nombres:

- **Va siempre, aunque valga 1.** Si un inicializador emitiera a veces dos
  floats y a veces tres, el lector en C no sabría dónde empieza la pieza
  siguiente. La prueba de contrato entre los dos lados lo caza al momento.
- **Los ajustes del objeto no deben tocarlo.** `size`, `alpha`, `speed`,
  `lifetime` y el tinte escalan los floats del inicializador; escalar el
  exponente por el tamaño de la capa no significa nada. Hay que dejarlo fuera a
  mano, y hay cuatro sitios donde se construye o se escala un inicializador.

### Lo que NO se pudo confirmar

**Confirmado después:** la documentación de WE dice que de `2` en adelante sesga hacia **Min**, que es `pow(t, e)`; ver [Los valores por defecto estaban en el binario](#los-valores-por-defecto-estaban-en-el-binario-el-giro-la-caja-el-ritmo-y-el-sesgo).

**La dirección del sesgo.** `pow(t, e)` apiña los valores cerca del MÍNIMO;
`1 - pow(1-t, e)` los apiña cerca del máximo. Se intentó decidir con tres
oráculos y ninguno sirve:

- La media del corpus no distingue: 23 escenas cambian y todas menos una lo
  hacen por menos del 1 %.
- Los textos de la aplicación solo dicen «Exponent», sin explicación.
- Una comparación A/B píxel a píxel sobre `2930166418` —`sizerandom` de 30 a 150
  con exponente 3, una escena bien renderizada— da 170,89 contra 170,96 de
  media, y las dos versiones difieren en el **0,25 % de los píxeles**. El
  preview del autor es un recorte más cerrado y tampoco decide.

Se eligió `pow(t, e)` por dos razones, y las dos son inferencia: es la
convención habitual para un exponente sobre un aleatorio de 0 a 1, y es la que
casa con la intención artística —`sizerandom` de 50 a 270 con exponente 2 en un
sistema llamado *rising debris* pide muchos cascotes pequeños y unos pocos
grandes, no al revés—.

**Efecto medido:** 23 escenas de 129 cambian, 22 de ellas por menos del 1 %. La
excepción es `3624053922`, que baja un 33 % —de 4,07 a 2,74— y la herramienta la
marca como regresión. Es el sesgo funcionando: su único sistema tiene
`sizerandom` de 50 a 270 con exponente 2, y llevar el tamaño medio de 160 a 123
píxeles quita en torno al 40 % de área. Esa escena ya estaba en la lista de las
cuatro negras —al 6 % de su preview— así que no sirve para juzgar la dirección.
Y dejó de contar como regresión sola: al arreglar su textura de vídeo pasó de
2,74 a 72,59, y sobre esa base el sesgo es ruido.

**Decidido:** se buscó la escena donde la diferencia se ve mejor —`3362719513`,
la de la vela, con `sizerandom` de 50 a 450 y exponente 5— probando las cuatro
candidatas del corpus con las dos curvas y quedándose con la que más píxeles
mueve (5,56 %, frente a menos del 1 % en las demás). Las formas de neón
alrededor de la vela salen muchas y pequeñas con `pow(t, e)`, y pocas y grandes
con la contraria. Revisado y aprobado el 2026-08-25: se queda `pow(t, e)`.

## Los uniforms que el motor rellena y nosotros no

El binario de WE lleva la **tabla de uniforms que su motor sabe rellenar**: 147
nombres. Cruzarla con el código VIVO de las 594 variantes del corpus ---no con
lo que declaran, que puede estar en una rama muerta--- deja 15 que se usan y
nunca emitíamos. Cero no es «sin valor»: es un valor, y a veces el peor.

| uniform | variantes | qué leía |
|---|---|---|
| `g_AudioSpectrum16/32/64` | 19 / 6 / 8 | ceros = silencio. Degradación honesta |
| **`g_PointerPosition`** | **14** | (0,0) = el cursor **clavado en la esquina** |
| `g_ModelViewProjectionMatrixInverse` | 5 | matriz a cero, con una división dentro |
| `g_EffectModelViewProjectionMatrix` | 4 | ídem |
| `g_LayerModelMatrix` | 3 | ídem |
| `g_Frametime` | 2 | 0 s por fotograma |

El audio no es un fallo: cero es silencio y es lo que hay hasta que exista el
subsistema. El puntero sí lo era, y se arregla como ya se arreglaba
`g_ParallaxPosition`: **el centro, `0.5 0.5`**, que es el reposo que el resto
del motor ya asume. Las tres matrices son la familia que nos ha mordido dos
veces —`normalize(0)` esperando— y las tres se derivan de lo que el plan ya
tiene:

- **`g_ModelViewProjectionMatrixInverse`** lleva el puntero de clip space al
  espacio local. Su única trampa es que `particle_mvp` aplana la fila z a
  propósito, lo que deja la matriz singular; para invertirla se le repone la
  identidad en esa fila, que es inofensivo porque quien lee la inversa no mira
  la z.
- **`g_EffectModelViewProjectionMatrix`** es dónde cae el fragmento en la
  PANTALLA, que no es dónde cae en el buffer de su capa: un pase de efecto
  dibuja a pantalla completa sobre su propio buffer y su MVP es la identidad.
  Se emite la matriz de colocación del objeto.
- **`g_LayerModelMatrix`** solo se lee por las longitudes de sus dos primeros
  ejes, y lo que se espera ahí es el **factor de escala** de la capa —1 cuando
  no está escalada—, porque multiplica una resolución. Va sin rotación a
  propósito: con nuestra convención de escribir las matrices por filas, `m[0]`
  en GLSL no es el eje sino la fila, y mezclar el giro daría una longitud que
  no es la escala. Nadie la multiplica, solo la mide.

Sobre las 129: **0 regresiones**, 8 escenas se mueven y ninguna más de 1,34 de
media —las que leían ceros—. Y las 594 variantes compilan igual.

### Lo que queda medido para después

El mismo cruce, aplicado a las partículas, dice que el **vocabulario está
completo**: 25 piezas distintas en 527 sistemas, las 25 implementadas. Lo que
falta son campos de piezas que sí leemos:

| campo | usos | qué se pierde |
|---|---|---|
| `exponent` en los seis inicializadores aleatorios | **96** | la forma de la distribución: el autor pide un sesgo y repartimos uniforme |
| `audioprocessing*` en 6 piezas | ~50 | reactividad al sonido |
| ~~`turbulentvelocityrandom` según la regla de WE (`forward`/`right`, `offset` como ángulo, fase, rapidez por defecto)~~ | 152 piezas en 66 escenas | **aplicado**: el inicializador entero se sustituyó por la regla leída, y la rapidez por defecto es 100–250 porque las 129 escenas son ortográficas. El aspecto solo lo respalda la lectura. Ver [La turbulencia con la regla de WE](#la-turbulencia-con-la-regla-de-we-turbulentvelocityrandom-deja-de-muestrear-nuestro-ruido) |
| ~~`flags` del SISTEMA, bit 0x4 («Perspective rendering»)~~ | 153 sistemas en 58 escenas | **aplicado**: la cámara en perspectiva que WE les pone en una escena ortográfica, leída en `wallpaper64.exe`, va en la MVP del pase. Ver [Partículas con perspectiva](#partículas-con-perspectiva-el-bit-0x4-del-flags-del-sistema-es-otra-cámara-no-otra-simulación) |
| `flags` del SISTEMA, bits 0x1 («worldspace») y 0x2 | 93 sistemas en 28 escenas / 89 en 32 | el 0x1 solo se nota si el objeto se mueve con el tiempo; el 0x2 no tiene casilla en el editor. Mismo sitio |
| `operation` en `remapvalue` | 2 | el modo del remapeo |
| `blendin/out` en `oscillatealpha` | 1 c/u | las ventanas de entrada y salida |

## El HUD decía 166 fps con la GPU al 98 %

Los dos números salían a la vez y no podían ser los dos ciertos. El HUD daba
**166 fps** mientras `/proc/<pid>/fdinfo`, sumando por cliente DRM, decía que
el fondo se comía el **98,1 %** del motor de render de la integrada.

El culpable era el propio HUD: su `fps` es `1 / clock.smoothFrameTime`, o sea
el reloj de QML, que late con el compositor. Y las llamadas a GL son
**asíncronas**: la CPU las encola y vuelve enseguida aunque la GPU se quede
atrás. Así que ese número medía a qué ritmo pedíamos fotogramas, nunca si el
motor llegaba a darlos.

Cronometrar la CPU alrededor del envío habría mentido igual. Lo único que lo
mide es preguntarle a la GPU, con `GL_TIME_ELAPSED`, y hacerlo **sin
esperarla**: dos objetos de consulta alternos, y en cada fotograma se lee el
del anterior. Preguntar por el de ahora obligaría a esperar a que la GPU
acabase —y esa espera es justo lo que falsearía la medida.

El resultado, en la misma escena y a la vez:

```
fps (reloj)  : 167.3
gpu          : 38.9 ms/fotograma  (26/s como mucho)
```

Esos 38,9 ms cuadran con los 41–45 que da el mismo plan cronometrado aparte con
el ejecutor offline. La diferencia entre 167 y 26 era el bulto que el HUD
tapaba.

Tres detalles que costaron un rato:

- **La medida se publica antes del corte por fase.** `synchronize()` tiene un
  `return` que solo deja pasar el fotograma en que cambia el estado; publicando
  después, el valor se mandaba una vez y nunca más, y el HUD decía «sin medida»
  mientras el motor ya tenía el número.
- **Abrir la consulta puede fallar callando.** Si el turno sigue en vuelo, o si
  hay otra `GL_TIME_ELAPSED` abierta —dibujamos dentro del `beginExternal()` de
  Qt, el contexto no es solo nuestro—, `glBeginQuery` da `GL_INVALID_OPERATION`
  y sin comprobarlo el turno se queda marcado como pendiente para siempre. Se
  cuentan los saltos y los fallos, que es lo que convierte un «sin medida» mudo
  en algo que se puede leer.
- **El primer parte no puede traer medida.** El diagnóstico de siempre sale en
  el fotograma 1, cuando la primera consulta aún está en vuelo por definición.
  Hay un segundo parte al fotograma 200.

## Dos `wectl` a la vez se pisaban

La rotación dispara `wectl shuffle` desde systemd —cada 60 s si se apura el
mínimo— y nada impedía que cayera encima de un `wectl set` a mano. Los dos
construían el plan en el **mismo** directorio, y el `rmtree` con que empieza uno
se llevaba los ficheros que el otro estaba escribiendo:

```
FileNotFoundError: .../plugin/contents/scene.nueva/p000.frag
```

Visto de verdad. El escritorio no se rompía —el plan viejo seguía en su sitio—
pero el cambio se perdía y el error no dice de qué va.

Ahora hay un cerrojo (`flock` sobre `.plan.lock`) que hace esperar al segundo en
vez de dejarle pisar, y el directorio de construcción lleva nombre único, así
que ni siquiera sin el cerrojo puede un proceso borrarle los ficheros a otro.
La prueba de `wectl` lanza dos `preparar` a la vez y comprueba que salen los
dos enteros; sin el cerrojo reproduce el `FileNotFoundError` exacto.

## Un sampler sin enlazar no lee negro

`3624164256` (Resident Evil 9) salía casi vacía: lluvia y niebla sobre negro,
sin calle, sin personaje. Con `--only-base` aparecía entera —68,17 de media
frente a 13,07 con todo puesto—, así que el contenido estaba bien y lo borraba
un pase.

Quitando un pase cada vez del plan y midiendo, el culpable salió a la primera:
el **parallax por profundidad**, no los godrays que parecían el sospechoso
—33 de las 129 escenas los usan y salen bien—.

La causa está en una línea de metadatos del shader:

```glsl
uniform sampler2D g_Texture1; // {"label":"depth_map","mode":"depth",
                              //  "format":"r8","default":"util/black"}
```

Ni la escena, ni el efecto, ni el material declaran esa textura: **la pone el
motor**, y cuando la capa no tiene mapa pintado pone `util/black` —profundidad
0, o sea sin desplazamiento—. Nosotros no poníamos nada, y ahí está el detalle
que engaña: **un sampler sin enlazar no lee negro**. Se queda con su valor por
defecto, que es 0, o sea la unidad de textura 0 —la del slot 0—, así que el
shader acababa usando *la propia imagen* como mapa de profundidad. El raymarch
de `ParallaxMapping` iba entonces a muestrear a cualquier parte y la capa
desaparecía.

Un `#if` mal resuelto o una matriz a cero se ven venir; esto no, porque el pase
compila, enlaza, dibuja y no da un solo error.

### El arreglo es general, y destapa 26 escenas

Se enlaza el `default` que declare el sampler siempre que el material no traiga
nada. Quedan fuera a propósito los `_rt_*` y los `_alias_*`: no son ficheros
sino buffers de subsistemas que este motor no tiene —sombras, reflejos, cookies
de luz— y fabricarlos vacíos es peor que dejarlos. El vocabulario real de
defaults de fichero es corto: `util/white`, `util/black`, `util/noise`,
`util/fur` y un gradiente de toon.

Sobre las 129 escenas: **0 regresiones** y **26 escenas cambian**, casi todas a
más luz porque aparece contenido que antes se destruía.

| escena | antes | después |
|---|---|---|
| 3624164256 | 14,45 | **71,20** |
| 2970694180 | 74,99 | 91,06 |
| 2220826239 | 21,89 | 37,30 |
| 3146507587 | 12,17 | 21,06 |
| 3775394622 | 62,41 | 68,89 |
| 3362719513 | 53,81 | 59,84 |
| 2946362143 | 21,34 | 27,19 |

Las cinco mayores están miradas contra su preview, no solo medidas: todas
dibujan la obra del autor. Las razones salen por debajo de 1 porque los
previews son recortes cerrados sobre el sujeto y nuestro render trae el encuadre
entero. `3146507587` es además la que un comentario del código daba por perdida
—«se desvanece a negro»—.

## El lunar negro del vinilo: la opacidad iba a un uniform que nadie lee

Con `3624164256` ya recuperada quedaba un disco negro y opaco en mitad del
personaje. La escena es un wallpaper de reproductor de música ---trae objetos
`Vinyl Disc`, `Album Art`, `Song Title`--- y el disco era la **sombra** del
vinilo, que el autor declara así:

```json
{ "name": "Vinyl Shadow", "alpha": 0.1, "color": "0.00000 0.00000 0.00000" }
```

Negro al 10 %. Salía al 100 %.

Ablatiendo por zona ---midiendo solo el rectángulo del lunar en vez de la imagen
entera--- salieron los dos pases que lo dibujaban, y de ahí a la causa: el plan
mandaba la opacidad del objeto en `g_Alpha`, y **ese nombre no lo lee ninguno de
los shaders de imagen**. `genericimage2` la lee de dos sitios, en ramas
excluyentes del mismo fichero:

```glsl
#ifndef VERSION
	color.rgb *= g_Brightness;
	color.a   *= g_UserAlpha;
#else
	color *= g_Color4;      // rgb Y alfa
#endif
```

El pase traía `#define VERSION 2`, o sea la segunda rama, donde el alfa viaja en
el `.w` de `g_Color4` --- que el plan escribía fijo a 1. Poner `g_Alpha` a 0, a
0.1 o a 1 daba exactamente la misma imagen: el uniform no lo leía nadie.

Ahora la opacidad se manda por los tres sitios. No se aplica dos veces, y no es
una suposición: en toda la librería no hay un solo `.frag` que lea dos de los
tres. `g_Color4` lo usan 5, `g_UserAlpha` 2, `g_Alpha` 6, y el único
solapamiento ---`genericimage2`, con `g_Color4` y `g_UserAlpha`--- son esas dos
ramas excluyentes.

### Alcance: 78 objetos en 18 escenas

Son los objetos del corpus con `alpha` distinto de 1, de 2093 en total. Medido
sobre las 129: **0 regresiones**, 9 escenas cambian y solo dos de forma
apreciable, las dos a MENOS luz porque sus capas translúcidas dejan de pintarse
opacas:

| escena | antes | después | qué se ve |
|---|---|---|---|
| 2533288714 | 139,98 | 112,40 | la bruma de la ciudad deja de velar la escena |
| 3237641967 | 91,11 | 78,93 | el halo rojo deja de ser un muro |

Las dos están miradas contra su preview, no solo medidas: siguen dibujando la
obra de su autor, con menos velo encima.

## El cuarto nombre del tinte: `g_Color`, y la ciudad que salía en siluetas

`2262142032` ---*Sci-Fi Cyber City*, 77 pases--- se dibujaba con el cielo negro
y la ciudad entera reducida a siluetas pálidas: las luces de las ventanas y los
neones caían donde tocaba y con su color, pero el atardecer, el planeta y la
bruma del fondo no estaban. Ninguna herramienta protestaba: 77 pases dibujados,
0 sin programa, 0 shaders perdidos, 0 texturas ausentes.

Cortando el plan por pases ---`werender.py --passes N`--- el corte es limpio y
no hace falta mirar mucho: con 2 pases la escena es **exacta al preview**, y con
3 es un rectángulo negro. El PNG lo dice hasta sin abrirlo, porque uno pesa
8,8 MB y el otro 37 KB.

El pase 3 es el base del objeto `Solid` ---`models/util/solidlayer.json`, la
capa blanca sobre la que el pase siguiente pinta las nubes---, y su fragmento es
`flat.frag` de la librería común, que entero es esto:

```glsl
uniform mediump float g_Alpha;
uniform mediump vec3  g_Color;

void main() {
	gl_FragColor = vec4(g_Color, g_Alpha);
}
```

El plan le mandaba `g_Alpha`, `g_Color4`, `g_Brightness` y `g_UserAlpha`. De los
cuatro, ese shader solo lee dos, y el que lleva el rgb ---`g_Color`, un `vec3`,
un quinto nombre que nadie emitía--- no iba. Sin asignar, GL da el uniform a
cero: **negro opaco a pantalla completa**, encima de un cielo que ya estaba bien
dibujado. El alfa sí llegaba, y por eso el quad tapaba en vez de desaparecer.

Es el mismo fallo que el del vinilo una capa más abajo: el tinte del objeto
viaja por tantos nombres como generaciones de shaders hay, y faltaba una. La
diferencia es que aquí el nombre que faltaba no llevaba la opacidad sino el
color, así que en vez de una capa demasiado opaca daba una capa negra.

### Alcance: 44 capas en 15 escenas, y 17 acertaban por casualidad

`g_Color` lo leen tres shaders de la librería común ---`flat`, `flatpoint` y
`editorsprite`--- y **nadie más**: ni uno de los shaders de las 129 escenas del
corpus lo menciona. Ninguno de los tres lee `g_Color4`, `g_Brightness` ni
`g_UserAlpha`, así que no hay doble aplicación posible; los tres sacan el alfa
de `g_Alpha`, que es un nombre distinto. La regla de la sección anterior sigue
en pie con el cuarto dentro: en toda la librería no hay un `.frag` que lea dos
de los cuatro.

De las 44 capas del corpus que usan esos shaders, **27 piden un color que no es
negro**. Las otras 17 querían negro de verdad y se veían bien por accidente ---
un `color: "0 0 0"` y un uniform sin asignar dan el mismo píxel---, que es
justo por lo que el fallo duró: en la mayoría de las escenas afectadas no se
notaba nada.

El brillo va multiplicado dentro del rgb en vez de aparte, porque estos tres
shaders no declaran `g_Brightness` y no hay otro sitio donde meterlo. No cambia
ningún píxel medible ---ninguna de las 44 capas trae brillo distinto de 1---
pero deja la semántica igual que en las otras generaciones.

Medido sobre las 129 escenas: **0 regresiones**, 6 escenas ganan luz y una
cambia −0,09 de media, que es el ruido de sus partículas ---no tiene ninguna
capa `flat`, y un `u3f` cuyo nombre el programa no declara es un no-op:
`glexec.c` hace `if (loc < 0) continue;`---.

| escena | antes | después | qué se ve |
|---|---|---|---|
| 2864255069 | 29,33 | 145,56 | el fondo amarillo de *Edgerunners*, que salía negro entero |
| 2262142032 | 21,82 | 81,07 | el atardecer, el planeta y la bruma; la ciudad deja de ser siluetas |
| 3237641967 | 95,43 | 117,85 | la salpicadura de sangre deja de ser una mancha negra |
| 2311315748 | 8,22 | 12,45 | `Circuit Glow` y `Big Pulse`, dos capas blancas que no encendían |
| 2867316322 | 158,21 | 161,20 | el morado del fondo, que era negro |
| 3624164256 | 71,21 | 71,69 | el `Mover` del reproductor |

Las dos primeras están miradas contra su preview, no solo medidas.

Vale la pena el detalle de `2311315748` ---*Samurai - Cyberpunk 2077*---: en la
sección de la regresión de luz figuraba como «arte oscuro, correcta» con razón
0,25 contra su preview. Lo era a medias: es una obra deliberadamente oscura Y
además le faltaban dos capas. Ahora va a 0,58. Una escena puede estar en la
lista de las oscuras por dos motivos a la vez, y el que sea legítima no
garantiza que no tenga nada roto encima.

## La función de iluminación no está en los assets

Ocho shaders de la librería común llaman a `PerformLighting_V1`, y ninguno la
define. Tampoco declara ninguno las dos arrays de luces que consume. Lo que sí
traen es una línea que no es GLSL:

```glsl
#require LightingV1
```

Ese `#require` es el hueco: WE inyecta ahí el módulo entero —función y
uniforms— antes de compilar. Nosotros borrábamos la directiva y el shader se
quedaba con una llamada a una función inexistente, así que el pase no
enlazaba. Por eso `LIGHTING` estaba apagado a la fuerza y las capas con luces
salían planas.

**El cuerpo no hubo que inventarlo.** WE deja la misma cuenta escrita a mano en
tres sitios de su propia librería, y entre los tres sale entera:

- `effects/fluidsimulation/…/fluidsimulation_combine.frag` hace el bucle de las
  cuatro luces desenrollado, en vez de llamar a la función. De ahí sale la
  forma: sumar por luz y dejar el ambiente aparte.
- `ComputePBRLightShadow` (`common_pbr_2.h`) es esta misma función con sombras,
  con la firma completa —radio, exponente, `specularTint`—. Se llama con
  `shadowFactor` a 1. Tiene que ser esta y no `ComputePBRLight`, porque el
  header que incluyen los ocho ya no define la segunda.
- `ComputeLightSpecular` (`common_fragment.h`), de la generación anterior, fija
  el exponente: atenúa el difuso con `lightAttn * lightAttn` sobre el mismo
  `saturate(1 - d/radio)`.

### El mismo color por dos caminos distintos

Conviven dos generaciones de shaders y cada una recibe las luces de una forma,
con **convenciones incompatibles** para el mismo dato:

| uniform | quién lo lee | atenuación | qué lleva el color |
|---|---|---|---|
| `g_LightsColorRadius[4]` | `generic4`, `foliage4`, `fur4`… | `saturate(1 - d/r)²` | color × intensidad |
| `g_LightsColorPremultiplied[3]` | `genericimage2`, `generic2`… | `1 / d²` | color × intensidad × **radio²** |

El `radio²` no es un ajuste: por ese camino el shader no recibe el radio, solo
divide por la distancia al cuadrado. Sin él, una luz de radio 1200 llega a su
propio borde con 0,7/1,44e6 y no se ve. Con él, a la distancia del radio la luz
vale exactamente su color.

El segundo además va **traspuesto**: los tres primeros colores en el `.rgb` de
cada elemento y el cuarto repartido por los tres `.w`. Así caben cuatro colores
en tres `vec4`.

### El mundo es el lienzo en píxeles

Las luces declaran su `origin` en las mismas unidades que los objetos: píxeles
del `orthogonalprojection`, con la z hacia el espectador. Una luz típica está a
343 o 500 px por delante del plano de la escena. No hay conversión de espacios
porque no hace falta ninguna; lo que hacía falta era emitir la matriz de mundo,
que hasta ahora solo se ponía para partículas —y con la matriz de recorte
dentro, que en ese espacio pone la luz a 500 pantallas de distancia.

### Tres uniforms que GL pone a cero sin decir nada

Encender el combo hace que el vértice tome un camino distinto, y ese camino usa
uniforms que el plan no emitía. GL no avisa: los da a cero y el resultado es
espectacular en las dos direcciones.

- **`g_ViewProjectionMatrix`** → **la escena entera en negro**. Con luz,
  `gl_Position = mul(worldPos, M_VP)` en vez de salir de la MVP. A cero, el
  quad colapsa a un punto y no se dibuja nada. No hay que inventarla: como
  `MVP = VP · Mundo` y las otras dos ya están, la que falta es
  `MVP · Mundo⁻¹`, exacta para capas, mallas y partículas por igual.
- **`g_NormalModelMatrix`** → primero NaN, y luego **el fondo en blanco puro**.
  Es un `mat3`, un tipo que el plan no sabía emitir; se añadió `umat3` a los dos
  ejecutores. Y tiene que ser **solo el giro**: la traspuesta de la inversa
  —lo que pide un normal bajo escala no uniforme— aquí es justo lo que no vale,
  porque el shader mete esa matriz en `BuildTangentSpace` y con ella arma la
  BASE en la que expresa la dirección a cada luz. Una base que encoge x e y por
  1/1920 no cambia hacia dónde apunta esa dirección, pero le cambia el módulo,
  y el módulo es la distancia de la que sale `color / d²`.
- **`g_LightAmbientColor`** → la capa en negro, porque el shader sustituye el
  color por `ambiente * albedo + luz`.

### O todas las luces, o ninguna

Ese `ambiente * albedo` es la razón de una regla que parece conservadora y no lo
es: **si una escena trae una luz que no sabemos poner, se dibuja plana entera**.
El ambiente OSCURECE la capa contando con que las luces devuelvan lo que quita,
así que iluminar a medias sale peor que no iluminar.

Medido en la única escena del corpus donde pasaba —3053927686, con una luz de
tubo y una puntual lejos—: encenderla a medias la bajaba de 39,31 a 11,52 de
media, con su preview en 89,99.

La regla sigue, pero ya no le toca a esa escena: el tubo resultó estar en el
`scene.json` y ahora se pone entero —ver [El tubo sí venía en la
escena](#el-tubo-sí-venía-en-la-escena-y-el-reflejo-solo-pedía-una-pirámide)—.
A quien le toca ahora es a los focos y las direccionales.

### El módulo de verdad está en el binario, y no es un fichero

`wallpaper64.exe` lleva el módulo `LightingV1` **como texto**, y eso explica por
qué no aparecía en los assets: **no es un shader, es un generador**. El motor lo
arma en tiempo de ejecución con las luces que tenga la escena — se ve en los
propios fragmentos, `uniform vec4 g_LPoint_Origin[` con el corchete abierto para
pegarle el número, y `const uint i = ` con el espacio final.

La firma real y el término por luz:

```glsl
vec3 PerformLighting_V1(vec3 worldPos, vec3 color, vec3 normal, vec3 viewVector,
                        vec3 specularTint, vec3 ambient, float roughness, float metallic)

light += ComputePBRLightShadow(normal, lightDelta, viewVector, color,
    g_LPoint_Color[i].rgb, g_LPoint_Color[i].w, g_LPoint_Origin[i].w,
    specularTint, ambient, roughness, metallic, 1.0);
```

Lo que confirma de la reconstrucción de arriba:

- **El sexto parámetro es `f0`, no el ambiente.** WE lo llama `ambient` en su
  propia firma, pero mira dónde acaba: en la novena posición de
  `ComputePBRLightShadow`, que es `baseReflectance`. El nombre es un despiste
  suyo, y los shaders que la llaman le pasan `f0`.
- El radio va en el `.w` del color y la posición en el `.xyz` del origen, con
  las arrays **dimensionadas por escena**, no `[4]` fijo. Las
  `g_LightsPosition[4]` que declaramos son de la generación anterior.

Y lo que corrige: **el exponente del decaimiento no es una constante**, viaja
con cada luz en el `.w` de su origen. Aquí estaba clavado a 2, deducido del
`lightAttn * lightAttn` de la generación vieja. Ahora viaja igual, en
`g_LightsExponent`, aunque el valor siga siendo 2: ninguna de las 9 luces del
corpus declara exponente y el campo `exponent` del formato es de color, no de
luces. La diferencia es que deja de ser una suposición metida en el shader y
pasa a ser un dato del plan, así que el día que se sepa de dónde leerlo es una
línea.

También sitúa lo que falta: WE cubre **puntuales, focos, tubo y direccionales**,
con sombras en cascada y *cookies* de color. Y su tabla de uniforms incluye
`g_PointerPosition` y `g_AudioSpectrum16/32/64`, que son los dos cabos que
bloquean el parallax con puntero y el audio reactivo.

**Dónde está la raya.** Ese generador es código de Wallpaper Engine. Leerlo para
comprobar que nuestra implementación independiente se comporta igual es lo que
hace cualquier proyecto de interoperabilidad; copiarlo al repositorio rompería
lo que promete el README —«aquí no hay ni un shader, y no va a haberlo»— y
además no serviría de nada, porque siendo un generador habría que reimplementarlo
igual. Nada de lo que hay en `weshader.py` sale de ahí: la reconstrucción es
anterior y se hizo desde los shaders de la propia librería.

### La función repuesta no la usa ninguna escena de esta biblioteca

Conviene decirlo claro: de los 6 pases que acaban iluminados en el corpus, los 6
van por el camino viejo, el de `g_LightsColorPremultiplied`. **Ninguno llama a
`PerformLighting_V1`.**

Eso dejaba la reconstrucción sin ejercitar de verdad: su cuerpo se compila en
todas las variantes —va fuera del `#if`— pero **la llamada de dentro de `main()`
no la compila nadie**, porque ninguna escena enciende el combo en esos ocho
shaders. Un cuerpo que nadie llama no prueba que la firma cuadre.

Así que `test_weshader.py` los traduce aparte con `LIGHTING` **encendido** y los
compila con el driver: los 8 de 8 pasan, y ahí sí se compila la llamada. Lo que
sigue sin estar verificado es la imagen —la fuerza del término, el `radio²`—,
no la sintaxis.

Esa prueba encontró de paso un agujero que no tenía nada que ver con la
iluminación, y que solo asoma con ella encendida:

```
fur4.frag : error C1503: undefined variable "TEX8FORMAT"
```

Un sampler con `"formatcombo": true` no se conforma con la textura: pide además
un `TEX<n>FORMAT` con **su** empaquetado, y lo usa como VALOR dentro del código
—`ConvertTextureFormat(TEX8FORMAT, ...)`—, no en un `#if`. Sin definirlo el
shader no compila, pero solo cuando esa línea está viva. Son 17 declaraciones en
la librería y **once de ellas son el slot 1, el mapa de normales**, que es justo
lo que enciende el camino de la iluminación. Ahora el combo se emite para todo
sampler que lo declare, sacando el formato de la textura que se vaya a enlazar
de verdad —la del material o la que el shader ponga por defecto—. Sobre las 129:
0 regresiones y 3 escenas que se mueven menos de medio punto.

Aun así tiene que estar. Sin ella, el combo no se puede encender en esos ocho
shaders: el pase no enlaza y se pierde entero, que es de donde venía la regla
anterior de apagar la iluminación a la fuerza. Cuando aparezca un wallpaper que
la use, lo que habrá que mirar es la fuerza del término, no si compila.

### Lo que se ve

9 luces en 5 wallpapers, todas puntuales menos ese tubo. En la escena de
referencia (2518601723, tres luces) son 2 pases de 21 los que se iluminan, y la
media pasa de 81,08 a 67,02 con el preview del autor en 60,80: la iluminación
la acerca al original en vez de alejarla.

En el corpus entero: 125/125 siguen renderizando, ninguna escena nueva en
negro, y las 578 variantes de shader compilan igual que antes (577 en Mesa, 576
en NVIDIA).

## El tubo sí venía en la escena, y el reflejo solo pedía una pirámide

Las dos cosas que quedaban del sistema de iluminación resultaron ser mucho más
pequeñas de lo que decían estas notas, y por el mismo motivo: se daba por
ausente un dato que sí estaba.

### La luz de tubo: `controlpoint` es el otro extremo

Estas notas decían que un `ltube` es «un segmento del que la escena solo
declara el centro, así que no hay forma de ponerla», y por eso una escena con
un tubo se dibujaba **plana entera**. No es así. El segundo extremo va en
`controlpoint`, relativo al origen y en el marco de la luz.

Lo que despista es que WE escribe la estructura completa en toda luz de la
generación nueva, use o no cada campo: la `lpoint` de esa misma escena trae
`controlpoint: "200 0 0"` idéntico, que es el valor por defecto del editor. Con
los dos juntos parece un campo decorativo. No lo es en la que sí es un tubo.

Y el shader nunca necesitó nada nuestro: `genericimage3` ---el único que usan
los dos pases iluminados de `3053927686`--- ya trae el bucle escrito:

```glsl
#if LIGHTS_TUBE
	vec3 lightDelta = PointSegmentDelta(worldPos, g_LTube_OriginA[l].xyz,
	                                    g_LTube_OriginB[l].xyz);
	light += ComputePBRLight(normal, lightDelta, ..., g_LTube_Color[l].rgb
	                         * g_LTube_Color[l].w * g_LTube_Color[l].w, ...);
#endif
```

Lo que faltaba eran los **combos que dimensionan sus arrays** ---`LIGHTS_POINT`,
`LIGHTS_TUBE`, uno por clase de luz--- y los uniforms correspondientes. Es
exactamente lo que hace ese generador que WE lleva en el binario: contar las
luces de la escena por clase y escribir el tamaño en el `#if`. Sin los combos,
las macros indefinidas valen 0 y **no se compila un solo bucle de luz**.

### La tercera convención para el mismo color

Ya había dos formas de mandar las luces; esta es la tercera, y no es una
alternativa a las otras: es la que leen los shaders con un array por clase.

| uniform | atenuación | qué lleva el color |
|---|---|---|
| `g_LightsColorRadius[4]` | `saturate(1 - d/r)²` | color × intensidad |
| `g_LightsColorPremultiplied[3]` | `1 / d²` | color × intensidad × **radio²** |
| `g_LPoint_Color[n]`, `g_LTube_Color[n]` | `1 / d²` | color × intensidad, y el **radio en el `.w`** |

La tercera es la segunda repartida distinto: el shader hace el `× radio²` él
mismo con ese `.w`. Cuál de las dos formas compila lo decide `SHADERVERSION`,
que es un contador de compilación de WE y no un dato de la escena; de la 62 en
adelante es la de arriba, y es la que emitimos porque es la que casa con
mandar el radio aparte.

### Los focos se quedan fuera a propósito

`genericimage3` declara también `LIGHTS_SPOT` y `LIGHTS_DIRECTIONAL`, y sería
una tentación rellenarlos. No se hace: su orientación sale de `angles` y **no
hay ni un foco ni una direccional en esta biblioteca** con la que comprobar el
mapeo. Escribirlos a ciegas cambiaría «la escena se dibuja plana» ---que se ve
y es honesto--- por «la escena se ilumina mal», que no se ve. La regla de o
todas las luces o ninguna sigue en pie para ellos.

### Lo que se ve, y lo que no

`3053927686` pasa de 32,62 a 31,88 de media. Es decir: **casi nada**, y hacia
abajo. Tiene explicación y conviene dejarla escrita para no volver a mirar aquí:
el ambiente de esa escena es 0,3, así que encender la iluminación quita el 70 %
del albedo contando con que las luces lo devuelvan, y las dos luces están a
1748 y 2000 px del plano ---con radios de 1000 y 963--- así que devuelven
aproximadamente eso mismo. El tubo, además, mide 186 px de largo a 1748 px de
distancia: `PointSegmentDelta` sobre un segmento así da casi lo mismo que una
puntual.

Y esa escena sigue al 0,35 de su preview por una razón que **no es la
iluminación**: sale en escala de grises. El preview es un atardecer azul y
rosa; lo nuestro es el mismo dibujo sin color. Eso es otro cabo, y el que de
verdad tiene esa escena.

## Reflejos: no era un subsistema, era un filtro

`REFLECTION` estaba forzado a cero con la nota de que «pide el fotograma ya
compuesto y mipmapeado en `_rt_MipMappedFrameBuffer`, que es otro subsistema».
El buffer ya existía ---el ejecutor resuelve ese nombre al acumulado de la
escena desde hace tiempo---, así que lo que faltaba era la pirámide y tres
cosas pequeñas:

- **Enlazar el sampler.** `g_Texture3` es oculto: el material no lo declara y
  su default lo nombra. Esa rama ya existía pero solo corría para partículas.
- **`g_Texture3MipMapInfo`**, el nivel más alto de la pirámide. El shader
  muestrea con `texSample2DLod(g_Texture3, uv, roughness * g_Texture3MipMapInfo)`:
  una superficie lisa lee el nivel 0 y una rugosa el último. En un lienzo 4K
  son 12 niveles, o sea 11.
- **Los uniforms del vértice.** El reflejo entra por el mismo
  `#if LIGHTING || REFLECTION` que la iluminación, así que quiere
  `g_ModelMatrix`, `g_ViewProjectionMatrix`, `g_NormalModelMatrix` y
  `g_EyePosition` aunque la escena no tenga una sola luz.

### El filtro no puede vivir en la textura

Aquí estuvo el fallo real, y no lo cazó la escena de reflejos sino el corpus.
`_rt_MipMappedFrameBuffer` y `_rt_FullFrameBuffer` son **el mismo buffer**, así
que dejarle a esa textura `GL_LINEAR_MIPMAP_LINEAR` se lo cambia también a
quien la lee por el otro nombre. Medido: **4 escenas que no tienen reflejos**
se movían hasta 10 puntos de luminancia y las cuatro se alejaban de su preview
---`2464842912` de 0,95 a 0,82--- porque algún pase que minifica el fondo
pasaba a leer un nivel borroso.

Se arregla con un *sampler object*, que ata el filtro a la unidad de textura y
deja la textura como estaba. La pirámide se regenera en cada lectura, porque
entre pase y pase se sigue dibujando sobre la escena.

### Lo que se ve

7 pases en 3 escenas encienden `REFLECTION`, y el bloque solo vive con
`NORMALMAP`: sin relieve no hay nada que reflejar, porque el término es
`(1 - dot(normal, (0,0,1)))` y una superficie de frente lo anula. Por eso el
efecto es desigual:

| escena | media | razón vs preview |
|---|---|---|
| `2533288714` (el EVA de Asuka) | 112,40 → 112,82 | 0,823 → 0,826 |
| `3097749052` | 38,13 → 38,18 | 0,983 → 0,985 |
| `2518601723` (Elden Ring) | sin cambio medible | — |

Las tres se acercan o se quedan igual. En el EVA cambia el 10 % de los píxeles
y el brillo cae justo sobre el blindaje, que es donde el mapa de normales tiene
relieve; en Elden Ring el mapa es tan suave que el reflejo se anula solo. Sobre
las 129 escenas: **3 cambian, 0 regresiones**, que son exactamente las que
tenían que cambiar.

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

## Mejora propuesta: generar un wallpaper desde un prompt

El motor come de un formato abierto, así que no hace falta una tubería nueva:
basta con **producir lo que ya sabe leer**. De los dos puntos de entrada
posibles, uno es claramente mejor.

- Generar el **plan de render** directamente es factible —es texto más blobs
  RGBA y GLSL— pero se salta todo lo que ya está resuelto.
- Generar una **escena en formato WE** (un directorio con `scene.json` y
  `materials/`) reutiliza el traductor de shaders, el decodificador de
  texturas, los sistemas de partículas y la librería de efectos del propio
  Wallpaper Engine que ya está en disco. Y el resultado funcionaría también en
  WE de verdad.

Que la tubería acepta un directorio suelto no es teoría: los wallpapers propios
de la aplicación vienen así, y `beach` renderiza a 0,87 de su preview.

### El camino mínimo

```
prompt -> imagen -> mapa de profundidad -> scene.json (capa + depthparallax
         [+ partículas]) -> tubería actual -> plan -> motor
```

Un wallpaper plano es una foto; lo que lo hace un wallpaper son capas que se
mueven a distinta velocidad. El atajo es que **`depthparallax` ya funciona** y
solo pide una textura de profundidad en `g_Texture1`: con estimación monocular
sobre la imagen generada, la escena reacciona al cursor sin separar capas a
mano.

### Lo que falta en este repositorio

- **Aceptar imágenes normales.** Las texturas se buscan siempre como
  `materials/<nombre>.tex` y no hay escritor de ese contenedor, así que un PNG
  generado no entra. Lo barato es aceptar `materials/<nombre>.png` cuando no
  exista el `.tex` —unas diez líneas entre `texture_path` y
  `Renderer.texture()`—; lo fiel sería escribir un `.tex` mínimo con el PNG
  embebido, variante que `wetex` ya sabe leer.
- **Saber dónde está el puntero.** Hoy se emite el centro fijo. Es el mismo
  cabo que desbloquea los 111 usos de `controlpointattract` de las partículas.

### Lo que el motor no puede dar, y conviene saber antes de diseñar el prompt

Texto (no se rasterizan glifos), audio reactivo, vídeo y modelos 3D. El
generador tiene que producir escenas **2D por capas**, que es justo lo que este
motor hace bien.

## Dibujar a la resolución que se ve

La escena se dibujaba al lienzo que eligió su autor y se encogía al final para
caber en la pantalla: **8,3 Mpx pintados para enseñar 2,3** en un panel de
1920x1200, dos de cada tres puntos a la basura. En esta biblioteca le pasa al
**72 % de las escenas**, con una razón mediana de **3,6x** y cuatro lienzos de
7680x4320 que pintan 33 Mpx.

Lo que lo impedía no era un número sino una **confusión**: `canvas` significaba
dos cosas a la vez.

- **El sistema de medida de la escena.** Dónde está cada capa, cuánto mide una
  malla, a qué distancia está una luz. Es del autor y no se toca.
- **A cuántos píxeles se dibuja.** De ahí salen los buffers y los uniforms que
  le dicen al shader cuánto mide un píxel.

Dividir el lienzo por dos dejaba una malla de 600 ocupando el doble de
pantalla, porque el mismo número la situaba. Separadas las dos, la mayor parte
del motor resulta ser **indiferente a la resolución**: la geometría se
normaliza a clip y eso no depende de cuántos puntos haya. Lo que sí escala es
corto y contable: los render targets, el buffer de cada capa, `g_Screen`,
`g_TexelSize` y el tamaño del destino. Y una pieza clave: **el ejecutor crea
todos sus buffers al tamaño de la línea `canvas` del plan**, así que ese único
número los arrastra.

El factor:

```
k = min(1, max(anchoPantalla/anchoLienzo, altoPantalla/altoLienzo))
```

El `max` es el que pide el modo «cubrir», el de por defecto y el que más
píxeles necesita, así que **un solo número vale para los tres modos de encaje**
y la resolución no queda atada al encaje —que hoy se cambia en caliente sin
regenerar el plan—. El `min` con 1 para no ampliar nunca por encima del lienzo
del autor: más puntos de los que él dibujó no añaden detalle.

Es opcional. Sin resolución todo se comporta como antes; `wectl` la detecta con
`kscreen-doctor` y toma el monitor **más grande**, porque el plan es uno solo y
lo comparten todas las pantallas.

### Lo medido

Cronometrando solo el ejecutor, en la integrada:

| escena | antes | después | |
|---|---|---|---|
| Elden Ring, 21 pases, 4K | 42,4 ms | 13,9 ms | **3,0x** |
| Sci-Fi Cyber City, 75 pases, 4K | 99,9 ms | 36,3 ms | **2,8x** — de 10 a 27 fps |
| la de 8K | 85,0 ms | 12,2 ms | **7,0x** — de 12 a 82 fps |

Y el corpus entero pasa de **849 Mpx a 318**, un 63 % menos.

**La imagen no cambia**, que es lo que había que demostrar: las 129 escenas
renderizadas a las dos resoluciones dan 0 errores y **128 de 129 con menos del
2 % de diferencia**. La única que se sale (2,8 %) es una escena casi negra,
donde cualquier cambio absoluto es relativo grande. Las de 8K difieren un 0,4 %
reduciendo los píxeles catorce veces.

En vivo el motor lo confirma:

```
GlExecutor: encaje=0 escena 2133x1200 -> se ve 1920x1200 desde (107,0)
```

Recorta 107 px por lado y pinta **píxel a píxel, sin escalar**.

Dos trampas al implementarlo, las dos de las que fallan callando: llamar
`self.render` al campo nuevo **pisa el método `render()`** del propio
renderizador, y el volcado final hay que reinterpretarlo con los píxeles de
dibujo y no con el lienzo de la escena.

## Compilar no es enlazar: 82 pases que se perdían sin decir nada

`test_wescene` compilaba las 594 variantes del corpus y daba 594/594. Pero un
vértice y un fragmento pueden compilar cada uno por su lado y **no poder
enlazarse**, porque lo que tiene que casar es la interfaz entre los dos. Ese
error no lo veía nadie: el motor se quedaba sin el pase y seguía.

`glslcheck` tiene ahora un modo `--link` que toma los pares y crea el programa
de verdad, con los mismos `glBindAttribLocation` que ata el motor. Sobre los 297
pares del corpus:

```
compilan   594/594  (100 %)
enlazan    283/297 en Mesa, 286/297 en NVIDIA   -> 14 variantes perdidas,
                                                   82 pases en los planes reales
```

Y no son los mismos en los dos drivers, que es lo que despista: Mesa se queja
de cosas que NVIDIA acepta, y como el escritorio corre sobre Mesa, la cuenta
que importa es la peor.

### La causa del grupo grande

Seis de los catorce son la familia de desenfoques gaussianos, con el mismo error:

```
error: array length mismatch between stages for variable v_TexCoord[N]
```

`godrays_gaussian.vert` declara `[COMBO] KERNEL` con `default: 1`; el `.frag`
**no lo declara**. Traduciendo cada etapa por su cuenta, el vértice sale con
`out vec2 v_TexCoord[7]` y el fragmento con `in vec2 v_TexCoord[13]`, porque una
macro indefinida vale 0 y ahí `#if KERNEL == 0` se cumple.

En WE un combo vale para el **programa**, no para una etapa: se declara una vez
y las dos mitades lo ven.

### El arreglo obvio parecía romper la imagen, y ya no

Prestarle a cada etapa el combo que consulta y no declara arregla el enlace.
La primera vez que se probó también **destrozaba la imagen** —72 escenas
cambiadas, 10 de las 14 que más se movían alejándose de su preview,
`2979320215` de 84,66 a 244,84 con su preview en 97,38, o sea blanco puro— y
por eso se revirtió, con la lectura de que el fallo de enlace estaba *tapando*
un segundo fallo en las cadenas de godrays y glow.

**Vuelto a medir hoy, eso no pasa.** Con el árbol actual, prestando combos:

```
                       antes    ahora
2979320215 (media)     83,66    83,49
escenas que cambian       —     44 de 129
la que más se mueve       —     ±6,09 sobre 255
regresiones (test_luminancia)   0
```

Ninguna se dispara, y probando además la regla cruda —empujar todos los
defaults de una etapa a la otra, que es lo que de verdad hay que evitar—
`2979320215` sale igual, en 83,49. O sea que el 244,84 no venía de la regla
sino de otra cosa del traductor, y lo más probable es que fuera
`varying_escribible`: sus tres fallos se arreglaron en esa misma sesión pero
**después** de revertir, y nadie volvió a medir con el préstamo puesto. Un
fragmento que escribe sobre un varying sin su copia local es exactamente el
tipo de cosa que descuadra un acumulador de glow.

Así que el préstamo entra. No es solo por los 8 pares que no enlazaban: la
mayoría de las escenas de godrays traen **su propia copia** del shader, con
`v_TexCoord` como `vec4` en las dos mitades, así que enlazaban de siempre —y
corrían mal—. `KERNEL` se declara solo en el vértice, con `default: 1` (7x7);
el fragmento se quedaba sin él, y una macro indefinida vale 0, que en ese
shader es el kernel de 13x13. El vértice calculaba los desplazamientos de 7
muestras y el fragmento leía 13. Ese es el desenfoque de más que se ve en
`2834359155` y `2645037214`: la mitad de un programa desenfocando más ancho de
lo que pedía la otra mitad.

### Tres causas, y ninguna era la que decían estas notas

Con `--link` sobre los 297 pares del corpus deduplicado, en los dos drivers:

```
             Mesa   NVIDIA
antes       283/297  286/297
ahora       297/297  296/297
```

Pero el 297 engaña, porque cuenta cada variante una vez y en el corpus se
repiten. Enlazando los **planes de verdad**, los 3638 pares que salen de
generar las 129 escenas:

```
antes    82 pares no enlazan, repartidos en 25 escenas
ahora    0, en Mesa y en NVIDIA
```

Ochenta y dos pases perdidos, no diez. `2242388122` perdía 8 de sus 62 y
`3462491575` 6 de 67.

Las 14 pérdidas de Mesa no eran las cuatro causas que decía la tabla anterior
sino tres, porque dos de las que parecían distintas eran la misma vista por dos
compiladores: lo que en Mesa sale como «`v_TexCoord` declarado vec4 y vec2» en
NVIDIA sale como `unknown semantics "ATTR0.xy"`, y son los mismos tres pares.

| causa | pares | de quién |
|---|---|---|
| un combo declarado en una etapa y consultado en la otra | 8 | de WE |
| un varying con tipo distinto en cada etapa | 3 | del autor |
| un uniform declarado y **sin usar**, con tipo distinto en cada etapa | 3 | del autor |

**El combo** es el grupo grande: 6 gaussianos, más `auto_sway` —que declara
`AA_VERSION` en el vértice y lo usa en el fragmento para elegir cuál de sus
tres `main` sobrevive, así que sin él el fragmento se quedaba literalmente sin
`main`— más el osciloscopio de `2799421411`, que declara `RESOLUTION` en el
fragmento y dimensiona con él un array de varyings en el vértice.

**El varying** es del autor y WE lo tolera porque HLSL enlaza por semántica:
el pixel shader puede declarar menos componentes de las que el vertex shader
escribe y se queda con las primeras. `rotate2d` trae `vec2` en el vértice y
`vec3` en el fragmento; el `test_shader` de `2844906964`, `vec4` y `vec2`.
Gana el vértice, que es quien produce, y los usos del fragmento son swizzles
que siguen valiendo. Comprobado: ninguno de los dos toca las componentes que
se van.

**El uniform** también es del autor, y las notas lo daban por nuestro: se
decía que las dos declaraciones las generaba el traductor en la sección de
uniforms izados. No es así —izar mueve la línea del autor, no inventa el
tipo—. `frame_builder` declara `uniform vec2 u_refResolution` en el vértice
con `default "512 512"` y `uniform float u_refResolution` en el fragmento con
`default 512`, y **el fragmento no lo usa para nada**. El enlazador compara
los uniform por nombre antes de tirar lo que no se usa, así que corta el
programa por una declaración muerta. Se quita: son 129 declaraciones de 4290
en todo el corpus, el 3 %, y una que no se usa no cambia un píxel.

Del uso hay que mirar el orden, que es donde estuvo la trampa: el fragmento de
`frame_builder` declara una variable local `res` mucho antes del
`#define res u_refResolution`, y contar apariciones sin mirar dónde caen
mantenía vivo justo el uniform que sobra. Y del alias valen **todas** sus
definiciones: `genericimage4` define `M_MDL` como `g_AltModelMatrix` y como
`g_ModelMatrix`, y quedarse con la primera borraba la otra —la del pase base
de casi toda imagen—.

### Y lo que parecía un límite de hardware: `GLSL` sin definir

El osciloscopio fallaba con `insufficient contiguous locations`, que parece un
límite de hardware y no lo es. WE define `GLSL` o `HLSL` según a qué backend
compila; nosotros no definíamos ninguno, así que todo `#ifdef GLSL` caía al
`#else`, o sea a la rama de D3D. Ahí el array de audio se dimensiona con
`RESOLUTION` —32 vec4— en vez de con los 28 de la rama de GLSL, y con los tres
varyings de siempre se pasa del máximo. Con `GLSL` definido caben.

Son 18 ficheros de los assets de WE los que preguntan por uno de los dos, y
solo uno pregunta por `GLSL`: `puppettexturechannels`, que en la rama de D3D
indexa una matriz con un flotante, cosa que GLSL rechaza —así que esa también
se arregla sola—. Los otros 17 preguntan por `HLSL`, que se queda sin definir
a propósito: sus ramas invierten la Y de las texturas. Los que lo usan de
verdad son los shaders de taller, como el osciloscopio.

### Lo que queda

Nada en los planes reales: 3638 pares, cero fallos, en los dos drivers. En el
corpus deduplicado queda uno, y no es de enlace: la variante de `auto_sway` con
`NODE_COUNT 5` **no compila** en NVIDIA, con `ambiguous overloaded function
reference "step(float, int)"`. Es la conversión implícita de HLSL que NVIDIA no
hace al resolver sobrecargas, y para arreglarla haría falta una tabla de firmas
de los built-ins. En Mesa —el driver del escritorio— compila y enlaza, y con
los combos que el motor le pone de verdad ni siquiera aparece.

Y la red que dejó pasar todo esto ya está puesta: `test_wescene` enlazaba cero
pares y ahora enlaza los 297, con los mismos `glBindAttribLocation` que ata el
motor. Compilar las dos mitades por separado nunca iba a ver un fallo de
interfaz.

## Vídeo en el motor: qué haría falta

> **Resuelto.** Lo que sigue es el estado de entonces, y las dudas que plantea
> están decididas en [Vídeo de
> verdad](#vídeo-de-verdad-un-decodificador-compartido-y-dos-entregas-distintas).
> Dos correcciones a lo que se creía aquí: las escenas con textura de vídeo son
> **tres**, no dos, y el fotograma congelado ya no existe.

Dos de las cuatro escenas negras del corpus lo eran por lo mismo: su capa
principal no es una imagen, es un **MP4 entero dentro del `.tex`**. El
contenedor lo marca con `IS_VIDEO` y `wetex` se niega a leerlo como píxeles
—con razón: hacerle caso al `format` de la cabecera da ruido en vez de un
error—. La capa se quedaba sin textura, y una capa de fondo sin textura no se
ve.

El apaño actual es **congelar el primer fotograma** con `ffmpeg`. Sube
`2968771936` de 0,00 a 132,13 y `3624053922` de 4,07 a 72,59, las dos a menos
de un 10 % de su preview. Pero es una imagen quieta.

Son **3 escenas de 129** con textura de vídeo. Reproducirlo de verdad abriría
además los **15 wallpapers de tipo vídeo** de la biblioteca, que hoy no se
tocan.

### Lo que hay que resolver antes de intentarlo

- **Quién decodifica.** O se enlaza `libavcodec`/`libavformat` en el ejecutor,
  o se lee de una tubería de `ffmpeg`. Lo primero mete una dependencia nativa
  nueva en el plugin; lo segundo mete un proceso por capa de vídeo.
- **Dónde.** El decodificado NO puede ir en el hilo de render: son 39 ms por
  fotograma de presupuesto en la escena 4K de referencia —medidos con el
  cronómetro de GPU— y un H.264 de 2560x1440 no cabe ahí. Hace falta un hilo
  aparte con una cola de fotogramas y subida asíncrona (PBO).
- **El reloj.** El motor tiene `g_Time`, pero un vídeo necesita el suyo: tasa
  propia, bucle, y qué hacer cuando el reloj del fondo se pausa. La pausa por
  cobertura tiene que parar también el decodificador, o el ahorro de GPU se lo
  come la CPU.
- **La memoria.** El MP4 de `3624053922` son 12 MB; cada fotograma decodificado
  a RGBA son 14 MB. Con doble búfer y varias capas eso se nota, y el trabajo de
  las potencias de dos ya nos enseñó que la VRAM es un recurso escaso aquí.
- **El plan.** Hoy una textura es `tex <id> <fichero> <w> <h>`, un RGBA crudo
  que el ejecutor sube una vez. Una capa de vídeo necesita otra clase de
  entrada —algo como `video <id> <fichero> <fps>`— y que el ejecutor sepa que
  esa textura cambia cada fotograma.

Mientras tanto, el fotograma congelado cuesta una llamada a `ffmpeg` en tiempo
de generación del plan y no añade ninguna dependencia en ejecución. Si `ffmpeg`
no está, se queda como estaba: sin textura.

## Las dos escenas negras eran dos campos leídos de más

Ninguna de las dos era un fallo de render. Las dos eran el mismo tipo de error
en dos sitios distintos: **`value` no es el valor**. En el formato de WE hay
campos que llegan como un objeto con un `value` dentro, y ese `value` es la
copia que el campo tenía **en el instante en que el autor guardó la escena**.
Quien manda es otra cosa. `is_visible` ya lo sabía para el campo `visible`; el
resto del motor no.

### `1518454472`: la Miku salía roja donde va cian

El primer sitio son las propiedades configurables. Un campo puede venir como

```json
{"user": "neon_2", "value": "1 0 0"}
```

y el color de verdad está en la propiedad `neon_2` del `project.json`, que en
esa escena vale `0 1 1`. Rojo y cian son **complementarios**, y eso es lo que
delata que no era un problema de brillo sino de leer el campo equivocado: si
fuera el brillo saldría el mismo tono más apagado, no el opuesto.

Medido en el corpus: **450 campos atados a una propiedad, 92 con la copia
desfasada, en 22 escenas.** Casi todos son constantes de material (77) y el
resto colores y escalas de objeto. Se resuelve al cargar la escena, en un solo
sitio, y se sustituye únicamente la copia: quien lea `user` sigue viendo lo
mismo. Si `user` no nombra una propiedad conocida ---hay wallpapers donde es a
su vez un objeto--- la copia se queda.

Efecto: 7 escenas cambian, 5 se acercan a su preview y 2 se alejan.

### `3577990983`: un telón de entrada que no se levantaba

El segundo sitio son las animaciones, y aquí la escena no estaba «rota»: estaba
**tapada**. Una capa de color sólido negro, a pantalla completa, con el `alpha`
animado:

```
c0: fotograma 0 -> 1,  fotograma 60 -> 1,  fotograma 90 -> 0
options: {fps: 30, length: 90, mode: "single"}
```

Es un fundido de entrada de tres segundos. WE lo guardó con la copia en `1`, o
sea opaco, así que sin evaluar la curva ese telón se quedaba puesto para
siempre. La escena salía negra menos un ramo de flores que se dibuja encima de
él, y esa flor suelta sobre negro era toda la pista que había.

Encontrarlo costó cortar el plan objeto a objeto: la escena sube hasta 45 de
luminancia y **el objeto 28 de 30 la deja en cero**. Ese objeto es un
`solidlayer` de un solo pase, sin samplers, con `g_Color4 0 0 0 1` y mezcla
`translucent`: un rectángulo negro opaco sobre todo lo demás.

Ahora se evalúa la curva. La interpolación es lineal: los fotogramas clave
traen además tiradores de bézier en `front` y `back` y no se usan, porque sobre
una rampa de fundido cambian la forma, no si acaba encendida o apagada.

**El plan es una foto, y eso decide a qué instante se hornea.** El motor repite
el plan cada fotograma cambiando solo `g_Time`, así que un campo animado se
queda donde se hornee. Para el renderizador offline es el instante que le
pidas. Para el plan del escritorio es el **reposo**, no el instante 0: en el 0
el telón está opaco, y hornearlo ahí habría dejado el fondo negro en vivo
exactamente igual que antes. Pasada su duración, una curva `single` ---33 de
las 51 del corpus, y todas las de entrada--- ya vale su valor definitivo. Las
`loop` y `mirror` quedan congeladas en ese instante, que es lo único que un
plan estático puede dar; hoy tampoco se movían.

### Lo que se llevó por delante

No solo las dos que se buscaban:

| escena | media | razón vs preview |
|---|---|---|
| `3577990983` | 1,95 → **45,22** | 0,029 → 0,664 |
| `3285617191` | 20,60 → **56,76** | 0,198 → 0,544 |
| `3053927686` | 31,88 → **48,50** | 0,354 → 0,539 |
| `1518454472` | 3,88 → 6,26 | 0,055 → 0,089 |

`3285617191` no estaba en ninguna lista: se daba por oscura y era otro campo
animado. Y `3053927686` es la escena de la luz de tubo, que se quedó en el 0,35
después de ponerle la luz entera; sube al 0,54 sola, así que su problema
tampoco era la iluminación.

De las 129: **3 escenas cambian por la animación y las 3 se acercan a su
preview, 0 regresiones**. Las apagadas bajan de 2 a 1.

### La que queda es bloom, y es un subsistema

`1518454472` ya sale con los tonos correctos ---los contornos cian y el «01»
rojo, como su preview--- pero mucho más apagada, y lo que le falta tiene
nombre: la escena declara `bloom: true` con `bloomstrength: 5.0` y
`bloomthreshold: 0.0`. Ese resplandor es la mitad del wallpaper.

No es una escena: **34 de las 129 encienden el bloom del motor**. Es un pase
final de post-proceso ---umbral de brillo, cadena de desenfoques a resolución
decreciente y suma sobre la escena ya compuesta--- que hay que meter en el plan
y en los dos ejecutores. Hay autores que lo montan a mano como cadena de
efectos, y ese camino ya funciona: el propio `3577990983` trae uno de 18 pases
del taller. Lo que falta es el del motor.

## Los recuadros negros: una capa negra de verdad, compuesta con la mezcla que no era

Tres escenas del corpus tenían un rectángulo pintado encima que no está en su
preview: el velo de `3053927686`, el recuadro negro de la esquina inferior
izquierda de Lonely Cat (`3299228616`) y un rombo negro girado en mitad de
`2413651762`. Son el mismo fallo.

### La capa no está rota: es negra a propósito

`ripple1440p`, la de Lonely Cat, tiene una textura de 2560x1440 cuyo RGB medio
es **3,8 sobre 255 y cuyo alfa es 255 en todos los píxeles**. Es negra y opaca
de verdad. Lo que la hace invisible en WE es el `colorBlendMode` del objeto, que
vale 9 —*add*—: sumar negro no aporta nada. Nosotros solo tratábamos el modo 31
y componíamos el resto con alfa normal, así que esa capa pintaba su rectángulo
allá donde cayera.

La tabla está en `ApplyBlending`, en `common_blending.h`, y va del 1 al 32.
En el corpus se usan 79 veces:

| modo | usos | qué es |
|---|---|---|
| 31 | 42 | el aditivo de WE, `A + B*opacity` |
| 6, 10 | 14 | lighten / max |
| 11 | 8 | overlay |
| 9 | 6 | add |
| 7 | 3 | screen |
| resto | 6 | softlight, colorburn, glow, luminosity… |

Se traducen los que el hardware sabe hacer con `glBlendFunc` **y cuyo elemento
neutro es el negro**, que es con lo que arranca el buffer del objeto: 31, 9, 7,
6 y 10, o sea 65 de los 79. `multiply` y `darken` también los sabe hacer el
hardware y quedan fuera aposta: multiplicarían igual donde la capa es
transparente y apagarían la escena entera fuera de ella.

### Por qué no se hace donde lo hace WE

WE no lo hace al componer, lo hace **dentro del pase base**: el shader trae el
bloque

```glsl
gl_FragColor.rgb = ApplyBlending(BLENDMODE, screen.rgb, gl_FragColor.rgb,
                                 gl_FragColor.a);
gl_FragColor.a   = screen.a;
```

con `screen` muestreado de `_rt_FullFrameBuffer` en `v_ScreenCoord`. Se probó y
no vale aquí, y la razón es de arquitectura: **los pases de un objeto corren en
el espacio de la capa**, y la colocación se aplica una sola vez al componerlo.
Dentro del pase, `gl_Position` no es la pantalla, así que `v_ScreenCoord`
apunta a cualquier sitio. Medido, por ese camino las cuatro escenas salen
desbordadas —`3299228616` al 71 % de píxeles saturados—. Queda escrito por si
algún día los pases se dibujan en coordenadas de pantalla.

### El alfa hay que premultiplicarlo a mano

`screen` y `max` mezclan con el destino ignorando el alfa de la fuente, y el
buffer de una capa con efectos **no viene premultiplicado**: los pases de
efecto escriben con la mezcla apagada, o sea crudo, así que puede haber color
vivo donde el alfa vale cero. Sin premultiplicar, esos dos modos lo cuelan
igual. El shader de composición —el único que el motor lleva dentro— lo hace
ahora cuando toca.

### Y entonces la regla de la herencia se cae sola

Estas notas decían que solo heredan la transformación los hijos de un GRUPO,
porque en Lonely Cat heredar de la imagen de fondo llevaba varias capas al
centro y tapaba la escena. Era cierto, y la causa era esta: la capa que tapaba
era `ripple1440p`, el rectángulo negro. Colocarla bien la hacía **más grande**,
así que parecía que la culpa era de heredar.

Con la mezcla puesta, el balance se da la vuelta. Sobre las 9 escenas con hijos
de una capa que dibuja, heredar siempre mejora 7 y empata en 2:

| escena | sin heredar | heredando |
|---|---|---|
| `3299228616` (Lonely Cat) | 0,541 | **0,790** |
| `2867316322` | 1,111 | 1,036 |
| `3462491575` | 1,157 | 1,104 |
| `3238423642` | 0,826 | 0,850 |

Es la misma lección de los pases que no enlazaban: el parche tapaba el fallo, y
en cuanto el fallo se arregla el parche estorba. Ahora hereda todo hijo, que es
lo que significa `parent`.

### La invisibilidad no bajaba por la cadena de padres

Apagar un grupo tiene que apagar lo que cuelga de él, que es para lo que sirve
agrupar. Mirábamos solo el campo `visible` de cada objeto.

Lonely Cat lo enseña de golpe: trae la escena **seis veces, una por idioma**, y
apaga cinco *por el padre*. Sus hijos —campos de estrellas, destellos, la
ondulación del agua— no dicen nada de si se ven, así que se dibujaban los seis
juegos. De 125 objetos que parecían visibles, solo **18** lo están de verdad:
107 de más. De ahí la nevada de puntos blancos que su preview no tiene, y los
anillos de agua duros, que eran seis ondulaciones apiladas.

En el corpus son **150 objetos de más en 4 escenas**: `3299228616` (107),
`3238423642` (30), `3597772384` (12) y `3462491575` (1).

Ojo con la medida: `test_luminancia` marca `3299228616` como regresión, de 70,81
a 50,07. Es la corrección funcionando —quitar cinco campos de estrellas quita
luz— y su preview tampoco sirve de juez: es un recorte central cuadrado de
256x256, o sea la zona más brillante. Que la razón baje ahí no dice nada.

### Lo que NO era: la Y del hijo

Con las estrellas arregladas, la ondulación del agua sigue naciendo más abajo
que en el preview. La tentación es invertir la Y del `origin` relativo, y está
comprobado que no:

- El reloj lo desmiente. Sus hijos declaran desplazamientos de +656 a +873 y
  salen ARRIBA, igual que en el preview. Invirtiendo la Y se van al borde de
  abajo.
- La colocación sigue el dato: `ripple1440p` declara `origin` (9,86, −221,11)
  bajo un padre en (1920, 1080), o sea (1929,9, 858,9), 221 px por debajo del
  centro. Eso es lo que se dibuja.

Así que lo que queda de diferencia está DENTRO de la capa, en su cadena de
efectos ---`waterflow`, `waterripple` y sobre todo `perspective`, que trae
`bottom: -0.49`---, no en dónde se pone el rectángulo. Los cuatro uniforms de
la perspectiva se emiten bien (`g_Bottom -0.49`, modo UV). Aislando la capa,
su energía cae centrada al 34 % de la altura y el rectángulo está al 60 %: la
perspectiva la mueve, y cuánto debería moverla no se ha podido confirmar.
Queda abierto.

### Lo que se ve

Los tres rectángulos desaparecen. Las ondas de Lonely Cat salen del centro
—alrededor del gato, como en su preview— y la lluvia de `3053927686` cubre la
pantalla en vez de una esquina.

Sobre las 129: **12 escenas cambian, 6 se acercan a su preview, 5 se alejan y 0
regresiones.** Las que se alejan lo hacen por arriba, de razones ya por encima
de 1: son capas de brillo que antes aportaban de menos.

La excepción a vigilar es `2413651762`, que pasa de 0,66 a 1,39. Ahí el rombo
negro desaparece —eso está claro— pero la escena queda lavada y **su preview no
sirve para juzgarlo**: es un retrato de cerca y lo nuestro es el plano ancho, o
sea que la razón no compara lo mismo ni antes ni ahora.

## Un punto son 4,137 unidades de lienzo, y eso no lo dice el formato

Una capa de texto es el único objeto de una escena que **no trae ni geometría
ni material**. Trae una cadena, el nombre de una fuente, un `pointsize` y una
caja. Quien la dibuja es `shaders/font`, que muestrea un atlas de glifos con
`a_TexCoord` —exactamente el mismo layout de vértice que una malla puppet— y
usa la cobertura como alfa sobre `g_Color4`. Así que todo el trabajo estaba en
fabricar ese atlas y esos vértices; y de todo el trabajo, lo que costó fue una
constante.

### La unidad no está en el formato, pero la caja sí

`pointsize` está en puntos y `size` en unidades de lienzo. Cuánto mide un punto
no aparece por ninguna parte del `scene.json`, y adivinarlo por la vía de las
DPI da candidatos plausibles y todos distintos: 96/72 = 1,333, 300/72 = 4,167.

El oráculo es el corpus. WE guarda en `size` la caja que él mismo calculó al
autoajustar la capa, así que **la caja es la respuesta ya escrita** y solo hay
que despejar:

    size = extensión_del_texto × K + 2 × padding

Medido sobre las capas cuya fuente viene EN el wallpaper —las `systemfont_*` no
valen, porque aquí se sustituyen y las métricas ya no son las del autor—, K
sale **4,137**, y sale igual en un lienzo de 564×1120 y en uno de 3840×2160: es
una constante, no una proporción de la pantalla. Dos cadenas del mismo
wallpaper, de 23 y 34 caracteres, dan 4,1371 y 4,1368; la relación es
proporcional pura y no esconde término independiente. No es 4,167, que sería
300 DPI limpios: está a 0,7 %, y las medidas concuerdan entre sí a 0,1 %.

Que el `padding` va **sin escalar** lo dice `3237641967`, que tiene la misma
cadena con la misma fuente y `padding` 0 y 3: la caja mide 252 y 258, dos veces
tres más.

Con eso puesto, volver a calcular la caja de las 76 capas con fuente propia
reproduce la que guardó WE: mediana 1,015 de ancho y 0,997 de alto, y **52 de
las 76 caen en el intervalo del 1,0**.

Las 24 de la cola no contradicen la constante: son capas cuya caja ya no mide
ese texto. Unas traen un marcador —`<Date>`, `<Clock>`, `Text Layer`— en vez de
la cadena que WE midió. Otras conservan la caja de antes de cambiar de fuente,
y se reconocen: `3329533084` dibuja su reloj en Alcubierre y sigue declarando
una caja de **156 de alto**, que es exactamente la del reloj que WE trae de
fábrica en Consolas. Ahí el dato viejo es la caja, no la fuente.

### Por línea, no por glifo

El atlas se rasteriza **por línea**. Es menos código y mejor tipografía: PIL
—FreeType con HarfBuzz debajo— resuelve kerning, ligaduras y shaping de una
vez, y una capa de texto del corpus tiene como mucho dos líneas. Rasterizar
glifo a glifo obligaría a reimplementar esa parte, y saldría peor.

El tamaño de rasterizado no es el final sino el doble. No es lujo: la capa se
dibuja primero en un buffer del tamaño del lienzo entero, con su rectángulo
estirado dentro —un cuadro de 365 unidades ocupa los 3840 px de ancho—, y al
componer se vuelve a encoger. Ese ida y vuelta son dos remuestreos bilineales,
y con el atlas a tamaño final el texto sale lavado.

### Tres sitios de donde sale una fuente, y uno no está aquí

De los 167 objetos, **47 traen la fuente dentro de su propio `scene.pkg`**
(`fonts/workshop/<id>/…`), 37 la toman de la instalación de WE y **83 piden una
del sistema**: `systemfont_consolas` y `systemfont_arial`, que son fuentes de
Windows. Para esas 83 se pregunta a fontconfig, que devuelve el sustituto
—Arial cae en Liberation Sans, que es métricamente compatible—. Las 167
resuelven.

Pero el sustituto no tiene las métricas del original, y ahí la caja deja de
cuadrar: esas 83 capas salen un 17 % más anchas y un 55 % más altas que el
`size` que WE calculó. Como el buffer del objeto *es* esa caja, sin más el
texto saldría cortado. Se arregla con el `margins` que ya usan las mallas
deformadas: agranda el buffer sin mover ni reescalar la capa, solo le da sitio.

### El ejecutor no se entera de que hay texto

Ni una línea de C ni de C++. Los quads salen con el layout de una malla puppet
—vec3 posición + vec2 UV, en unidades de capa respecto a su centro— y viajan
por la directiva `mesh` que ya existía; el atlas es una textura corriente que
se enlaza en `g_Texture0`. Es el mismo reparto de siempre: Python resuelve, el
ejecutor ejecuta.

La única sutileza es la mezcla, y es la de las partículas otra vez. El pase
dibuja los glifos sobre el buffer VACÍO del objeto y ese buffer se compone
después, así que con la mezcla corriente el alfa se eleva al cuadrado. En un
glifo eso solo toca el borde antialiaseado —el interior vale 1— pero es justo
donde vive la forma de la letra. Con `premul_alpha` en el pase y modo 2 al
componer, que es lo que ya hacían las partículas, sale entero.

### Lo que la distribución ahorró

Mirar los valores y no los recuentos quita más trabajo del que deja:

| campo | usos | qué hay de verdad |
|---|---|---|
| `horizontalalign` | 167 | **156 dicen `center`**, 8 `left`, 3 `right` |
| `verticalalign` | 167 | **164 dicen `center`** |
| `anchor` | 150 | 140 `none` y 9 `center`, que es lo que ya hace la colocación; queda **1** capa con `left` sin tratar |
| `opaquebackground` | 167 | **falso o ausente en los 167**: el pase de fondo (`fontbackground`, shader `flat`) no lo pide nadie |
| `blockalign` | 128 | falso en los 128 |
| `spacing` | 21 | `"0 0"` en los 21 |
| `maxrows` | 149 | 1 en los 149 |
| `limitwidth` | 149 | cierto en 14 — el único que obliga a partir líneas |

Sobre los shaders el añadido es exactamente el que cabía esperar: de 3512 a
**3581 pases** (+69, los objetos de texto visibles), de 580 a **582 variantes**
—`font.vert` y `font.frag`— y de 290 a **291 pares**, y el nuevo enlaza en los
dos drivers.

### Lo que se ve

Sobre las 129: **25 escenas cambian, 0 regresiones y 0 dejan de renderizar.**
Las 26 que llevan alguna capa de texto dibujable —contadas por separado, sin
mirar la luminancia— son exactamente las que se mueven, salvo `2968771936`,
cuyo texto va a `pointsize` 5 y no llega a mover la media de un 4K. Suben 24 y
baja una, `3237641967`, que es lo que tiene que pasar: su reloj lleva debajo
una segunda capa de texto NEGRA que hace de sombra. En *Lonely Cat* salen el reloj y
`Monday, September 17` sobre el agua; en la Makima de *Chainsaw Man*, el `DAY`
en Anurati con su sombra roja desplazada, que es una segunda capa de texto
debajo de la primera, y el `<Date>` de la esquina, que es el marcador que
guardó el autor y no una fecha.

### Y el muro: 148 de los 167 son JavaScript

Lo que se dibuja no es lo que el autor quiso, y no por un fallo de render.
**148 de los 167 objetos traen el texto en un script**, y 133 de esos llaman a
`new Date`: son relojes y fechas. Son 51 scripts distintos, casi todos copias
de media docena de paquetes del taller.

Sin motor de scripting lo que se dibuja es su `value`, la copia que el autor
tenía en pantalla al guardar —`"12:34"` en 57 de ellos, `"2021 | 02 | 01 |
Monday"` en 29, y `<Date>` de marcador en 15—. La tipografía sale bien; la hora
está congelada, y en la mitad de las capas ni siquiera es una hora.

Eso convierte «texto» y «scripting» en dos cosas distintas, y esta era la
primera. La segunda es un intérprete de ES6 con la API del motor
(`engine.registerAudioBuffers`, `createScriptProperties`, `engine.frametime`) y
entra en la lista de lo que queda.
## El puppet se quedaba en reposo: el campo de la cabecera es un desplazamiento

Un `.mdl` de puppet encadena bloques: geometría, `MDLS` (esqueleto) y `MDLA`
(animación). Tras el esqueleto, `parse_animations` no encontraba `MDLA` en **58
de los 95 puppets** de esta biblioteca, avisaba de «bytes sin identificar» y el
puppet se dibujaba **en su postura de reposo**.

Y la postura de reposo no es la imagen que se ve. En estos wallpapers el autor
dibuja la pieza colgante apartada en la textura y son los huesos los que la
llevan a su sitio, así que sin animación se queda donde la dibujó:

- `3775394622`: la columna vertebral dorada del casco de Agamenón, aparcada
  contra el borde derecho del lienzo en vez de colgando del penacho.
- `3238423642`: **la cabeza del personaje flotando suelta en la esquina
  superior izquierda**, separada del cuerpo.

La causa es un campo mal interpretado. La cabecera de `MDLS` es `magic` + `u32`,
y ese `u32` estaba documentado aquí como «tamaño restante». No lo es: es el
**desplazamiento absoluto del bloque siguiente**. Dos medidas lo fijan, y
ninguna sale de suponer nada:

- En los 37 puppets que sí funcionaban, el campo coincide **exacto** con la
  posición donde termina de recorrer la lista de huesos.
- En 89 de los 95, el byte al que apunta es `MDLA` o `MDAT`. En el que falta,
  apunta al final del fichero: ese puppet no trae animación y es correcto.

O sea que detrás de la lista de huesos hay otro bloque, de tamaño distinto en
cada fichero, que el recorrido no salta. Ya se había tropezado con él y se
parcheó con una constante —`13 + 80 * huesos`— medida sobre las seis mallas
donde se vio. La constante cuadraba en esas seis y en ninguna más; el bloque no
tiene tamaño fijo. Siguiendo el campo no hace falta interpretarlo.

La regla vale para toda la cadena, no solo para `MDLS`. En
`2867316322/puppet_puppet.mdl`: `MDLS` → 15106, ahí hay un `MDAT0001` cuyo campo
dice 15198, ahí hay `MDLA0006`, y el suyo dice 17495, que es el último byte del
fichero. Así que `parse_animations` salta cualquier bloque que no sepa leer por
su propio campo, en vez de conocerlos de antemano.

**54 puppets de 11 escenas recuperan su animación**; de 37 animados se pasa a 91
de 95.

### Y entonces `mirror` deja de ser un detalle

Los dos ejecutores dan por hecho que **la última clave repite la primera**: por
eso el periodo son `nkeys - 1` intervalos. Las pistas de modo `loop` cumplen eso
—60 de 74 exactamente, y las 14 restantes por debajo de 0,08—. Las de modo
`mirror` **no lo cumplen ninguna**: son las 47 del corpus y acaban lejos de donde
empiezan, hasta 13,34 unidades en el brazo de `2868108515`. Se reproducen yendo
y volviendo, no en bucle.

Reproducirlas como bucle da un tirón en cada vuelta, y hasta ahora casi no se
notaba porque la mayoría de esas pistas ni se leían. Se hornea la ida y vuelta
**en Python**, no en el ejecutor: las claves salen al plan en el orden en que se
reproducen —`0..K-1`, `K-2..1`, `0`, que son `2K-1` con la última igual a la
primera— y la duración va doblada. El ejecutor sigue haciendo lo único que sabe,
y no hay una regla nueva que dos implementaciones puedan entender distinto.

Queda un `single` en el corpus, que WE reproduce una vez y se para; nosotros lo
repetimos.

### Lo medido

Las 129 escenas, luminancia media sobre 6 fotogramas: **ninguna regresión**.
De las 11 escenas con puppets recuperados, las dos que más cambian son
`3050043876` (23,4 % de los píxeles: el pelo, que ahora ondea) y `3238423642`
(16,0 %: la cabeza, que vuelve al cuerpo). Las dos coinciden ahora con la vista
previa de su autor.
## La capa `passthrough` se componía en su rectángulo del editor

`composelayer`, `fullscreenlayer` y `projectlayer` son capas de utilidad: leen
`_rt_FullFrameBuffer` y operan sobre el fotograma entero. Su modelo lo dice
—`"passthrough": true`— y `wescene` ya lo anotaba en `_passthrough`. **Nadie
leía esa marca.** El objeto se componía con su `origin` y su `size`, y como el
pase base había dibujado el fotograma completo dentro de su buffer, el resultado
era el fotograma entero **encogido dentro de un rectángulo**.

Que el rectángulo no pinta nada no es deducción, lo dicen sus dos shaders:

- `passthrough.vert`, sin el combo `TRANSFORM`, hace `gl_Position =
  vec4(a_Position, 1.0)`: ni toca la MVP.
- `composelayer.vert` construye el vértice desde las UV, `position.xy * 2.0 -
  1.0`, que es la pantalla entera pase lo que pase.

El `size` y el `origin` de esas capas son el asa con la que el autor las agarra
en el editor, y nada más. Hasta ahora colaban porque **las que no declaran
ninguno de los dos caían al lienzo por la rama del valor por defecto**: acertaba
por accidente, y solo mientras el autor no tocara el rectángulo.

En el corpus hay **85 capas passthrough; 32 de ellas, en 21 escenas, declaran un
rectángulo que no es el lienzo**. Ahí es donde salían los recuadros:

- `1173201544`: un `Fullscreen` de 1624x696 con origen en (0, 0) sobre un lienzo
  de 2500x1200 —la escena entera metida en la esquina inferior izquierda—.
- `2537500835`: dos `composelayer` de 1920x540 y uno de 800x800, que son las dos
  bandas horizontales y el recuadro del centro.
- `2396319149` y `3555933181` no salían con recuadro sino con el encuadre
  cambiado y medio fotograma reventado de luz; los dos coinciden ahora con la
  vista previa del autor.
- `2162986216` traía un `composelayer` de **4x4 píxeles**: el fotograma entero
  aplastado en cuatro píxeles.

### Lo medido

Las 129 escenas, media de luminancia sobre 6 fotogramas, contra la medida previa
al arreglo: **una sola escena cambia**, `3555933181`, de 114,77 a 81,14. Y baja
porque antes estaba mal: el `composelayer` desplazado le blanqueaba la mitad
izquierda. La imagen nueva es la que cuadra con la vista previa que publicó su
autor.

**Esto era la mitad de la historia**, y la otra mitad tardó en aparecer: el
`gl_Position` de `composelayer.vert` ignora la MVP, cierto, pero su
`v_ScreenCoord` **no**, y de ahí sale lo que muestrea. Con la colocación en
identidad se queda el fotograma entero en vez del trozo que hay bajo su
rectángulo, y eso es lo que desliza el fondo de *Lonely Cat*. Ver [el fondo de
*Lonely Cat* se
desliza](#el-fondo-de-lonely-cat-se-desliza-y-las-dos-mitades-de-un-arreglo).
## `254 - 255` no es −1: el flujo se invertía donde la máscara satura

Un mapa de flujo de WE guarda un vector por píxel en RG, centrado en 0.498. Su
buffer y el nuestro no tienen la V en el mismo sentido, así que al subirlo hay
que **negar la componente vertical**, que sobre el byte es espejarla alrededor
de 127: `G' = 254 - G`.

Esa resta iba en `uint8`. Y en `uint8`, `254 - 255` no vale −1: **da la vuelta y
vale 255**. O sea que el único valor que no se espejaba era justo el saturado, y
salía con el signo cambiado: `+1.004` donde tocaba `−0.996`.

No es un píxel raro. Estas máscaras están pintadas con brocha y **saturan en
casi toda el área pintada**: 285306 de los 518400 píxeles del mapa de
`2095917182`, y seis máscaras del corpus están al 100 %. Lo que se veía era el
contorno donde la máscara pasa de 254 a 255 dibujado como una **grieta dura**,
con la imagen arrastrada hacia un lado a un lado de la línea y hacia el otro al
otro. En `2095917182` recortaba el oleaje siguiendo el perfil de la máscara y
además empujaba la arena fuera del buffer por arriba, que es de donde salían las
rayas verticales del borde superior. En `1527827385` no era una línea sino un
desgarro: partes del casco se movían al revés que sus vecinas y las gafas salían
partidas con un escalón en medio.

El barrido sobre las 129 escenas: **53 de las 305 texturas de flujo distintas
traen píxeles con G=255, repartidas en 30 escenas**. No son solo `waterflow`;
la mayoría son máscaras de `shake`, que usa el mismo tipo de mapa.

El arreglo es hacer la cuenta en `int16` y recortar a [0, 255]. Que un mapa
sature no tiene nada de excepcional —significa «aquí el flujo va a tope»—, y era
exactamente el caso que el tipo no aguantaba.

## Vídeo de verdad: un decodificador compartido, y dos entregas distintas

El [apaño de congelar el primer fotograma](#vídeo-en-el-motor-qué-haría-falta)
se retira. El MP4 viaja entero en el plan y lo decodifica `src/wevideo.c`, que
enlazan **los dos ejecutores** —la misma regla que `weparticles.c`—.

Y el corpus no eran dos escenas, eran **tres**: `3053927686` también lleva un
MP4 dentro del `.tex` y nunca había aparecido en estas notas porque su capa de
vídeo es una lluvia gris sobre negro, no un fondo. Contarlas bien costó un
barrido de los 129 `scene.pkg`, no de los que se sabían.

### Por qué libav y no una tubería de `ffmpeg`

La duda que dejaron abierta estas notas. La decide una cuenta:

| | RGBA por la tubería |
|---|---|
| 3840×2160 @60 (cuatro del corpus) | **1,99 GB/s** |
| 1920×1080 @30 | 249 MB/s |

Y encima un fondo necesita **bucle y pausa**, y por tubería eso solo se hace
matando el proceso y relanzándolo. Con `libavformat`/`libavcodec`/`libswscale`
el coste es una dependencia de enlace más en el plugin; a cambio, el consumidor
no copia nada.

### Los dos modos no son un lujo: son dos requisitos incompatibles

`wevideo.c` entrega el mismo fotograma por dos caminos, y quitar uno rompe algo:

- **`WEVIDEO_EXACTO`** decodifica dentro de la llamada hasta el instante pedido.
  Lo necesita el offline: `werender.py` renderiza **un** instante y lo repite N
  veces para que converjan los efectos temporales, así que las N repeticiones
  tienen que dar el mismo fotograma. Con un decodificador asíncrono,
  `test_luminancia` mediría lo que tardó el disco.
- **`WEVIDEO_HILO`** decodifica por delante a un anillo y **nunca bloquea**. Lo
  necesita el vivo: el presupuesto del hilo de render son 39 ms por fotograma en
  la escena 4K de referencia, y un H.264 de 2160p no cabe ahí.

Medido con el consumidor pidiendo a 60 Hz:

```
2560×1440 @29,97   30,0 fotogramas nuevos/s   wevideo_frame: 0,008 ms medio
3840×2160 @60      57,4 fotogramas nuevos/s   wevideo_frame: 0,007 ms medio
1920×1080 @30      29,8 fotogramas nuevos/s   wevideo_frame: 0,032 ms el peor
```

Es decir: en el hilo de render el vídeo cuesta **una centésima de milisegundo**
y una subida de textura. Todo lo caro pasa en el otro hilo.

**La pausa sale gratis y no por casualidad.** Si el reloj del motor se para
—plasmashell pausa el fondo cuando las ventanas lo tapan—, el instante pedido
deja de avanzar, el consumidor deja de consumir, el anillo se llena y el hilo
productor se duerme en su condición. Sin eso, el ahorro de GPU de la pausa se lo
comería la CPU decodificando lo que nadie ve.

### El bucle de seeks que dejaba el vídeo clavado

El fallo que no se veía en una prueba corta. El consumidor pide rebobinar cuando
el fotograma que tiene queda a más de medio segundo del instante pedido. Pero
**un seek cae en el fotograma clave anterior**, y con un GOP largo eso puede
estar segundos atrás: el productor publicaba desde ahí, el consumidor lo veía
todavía más lejos y pedía otro seek. Y otro.

Se ve solo si el reloj **arranca lejos de cero**, que es justo lo que pasa
cuando el escritorio despausa tras media hora tapado:

```
arranque en t=3000 s     0,2 fotogramas nuevos/s   <- clavado
tras el arreglo         28,8 fotogramas nuevos/s
```

El arreglo es que el productor decodifique **en vacío** hasta pisar el instante
pedido antes de publicar nada, y que el rebobinado tenga tres estados y no dos:
sin él, el consumidor volvía a pedir mientras el productor aún estaba saltando.

### Y el fichero no siempre empieza en cero

`Mass Effect Andromeda [No Arrow].mp4` arranca en `start_time = 0,0333`. Los pts
se comparaban crudos contra el instante pedido, así que el vídeo iba **un
fotograma desfasado** y, peor, el bucle se desplazaba esa cantidad en cada
vuelta. Ahora todos los pts salen ya restado el arranque: la línea de tiempo que
ve el resto del motor empieza en 0 y el bucle cierra exacto sobre la duración.

Lo delató el oráculo, no la vista: diferencia máxima de 85 sobre 255 con una
media de 0,4, que es la firma de «otro fotograma» y no la de «otro color».

### Nueve fondos negros por un espacio en el nombre

Los 15 wallpapers de tipo vídeo salían… nueve de ellos en negro. No era el
decodificador: **el plan es un texto que se parte por espacios**, en los dos
ejecutores, y `AKALI BIKE.mp4` o `Mass Effect Andromeda [No Arrow].mp4` dejaban
la ruta truncada en el primer espacio.

Nueve de quince es exactamente la fracción de nombres con espacio. El resto de
los assets del plan nunca lo había sufrido porque **sus nombres los genera
`werender.py`** —`tex000.rgba`, `p001.frag`—; el MP4 de un wallpaper de vídeo es
el primer asset que se nombraba tal cual venía de la biblioteca. Se enlaza con
un nombre generado (`video.mp4`) y no se copia: los del corpus van de 9 MB a
560 MB.

### Lo que había que decidir, y dónde se decidió

- **Sin mipmaps en una textura de vídeo.** Regenerar la pirámide de un 2160p en
  cada fotograma cuesta más que decodificar. Y hay una trampa: con
  `GL_LINEAR_MIPMAP_LINEAR` y la pirámide sin construir, la textura queda
  **incompleta y se muestrea negra** —el síntoma que se venía a arreglar—.
- **El volteo, con paso negativo.** Las texturas de WE se guardan con el origen
  arriba y las UV de GL van al revés; `werender.py` ya voltea las que decodifica
  en Python. Un fotograma llega igual, así que swscale escribe desde la última
  fila con paso negativo: copiar el buffer para darle la vuelta serían otros
  33 MB por fotograma a 4K.
- **BT.709 cuando el fichero lo dice, y también cuando calla.** Por defecto
  swscale asume BT.601 y todo el corpus es HD o mayor: leído como 601, un 709
  vira los verdes y los tonos de piel. Cinco de los 15 wallpapers **no declaran**
  su espacio de color; ahí se decide por altura —a partir de 720 líneas, 709—,
  que es lo que hace `mpv` y lo que de verdad traen los H.264 en HD. Es una
  convención, no un hecho del fichero, y por eso está escrito aquí.
- **El anillo se dimensiona por memoria, no por fotogramas.** A 4K un RGBA son
  33 MB. Con el tope en 64 MB, un 1080p tiene cuatro huecos y un 2160p dos, que
  es lo justo para que el hilo no se quede sin trabajo.

### Los wallpapers de tipo vídeo salen casi gratis

Los 15 que no son una escena sino un MP4 y nada más. No tienen `scene.pkg`, ni
grafo, ni shaders, así que `wectl` ni los listaba. Con el decodificador ya
puesto, lo único que les faltaba era un plan, y su plan es el más corto que este
motor puede escribir: `canvas`, `video`, un `object` y un pase con un quad.

Encajan **cubriendo** la pantalla, no cabiendo en ella: un fondo con franjas
negras no es un fondo. El quad se pasa de la pantalla y el recorte lo hace el
viewport, que es exacto y gratis.

Las dimensiones se leen de la caja `tkhd` del MP4 en Python y no preguntándole a
`ffprobe`: el apaño anterior ataba la generación del plan a que hubiera un
binario de ffmpeg en el PATH, y ahora que decodifica `libavcodec` dentro del
motor, volver a necesitar el ejecutable para leer dos enteros sería un paso
atrás.

### El oráculo: pixel a pixel contra ffmpeg

Una capa de vídeo no falla de forma ruidosa. Del revés, con los colores virados
o congelada, el plan se genera igual y el ejecutor no se queja: sale una imagen.
Así que `test_wevideo.py` no opina, compara:

- las dimensiones que saca `wevideo.dimensiones` de las cajas del MP4 contra
  `ffprobe`, en los 18 vídeos de la biblioteca: **18/18**;
- el fotograma que entrega el arnés contra el que saca `ffmpeg` en ese mismo
  instante, **pixel a pixel**: **54/54** —que es lo que ata a la vez el volteo,
  el espacio de color, el rango y el instante elegido: los cuatro pueden
  equivocarse en silencio—;
- que el modo exacto sea determinista y que el bucle cierre.

A los cinco ficheros que no declaran espacio de color se le pone a `ffmpeg` la
**misma** matriz que elige el motor. Si no, el test acusaría de fallo de
decodificación lo que es una convención distinta, y dejaría de mirar lo que sí
importa.

### Lo medido sobre las 129

`test_luminancia` con referencia contra la medida de antes del cambio:

```
129/129 renderizan     regresiones: 0
124 de 128 escenas dan EXACTAMENTE la misma luz que antes
```

Las que se mueven son las tres de vídeo:

| escena | congelado | reproduciendo |
|---|---|---|
| `2968771936` (3840×2160 @60) | 132,13 | **133,32** |
| `3053927686` (1920×1080 @30) | 57,83 | **58,54** |
| `3624053922` (2560×1440 @29,97) | 72,59 | **72,58** |

La cuarta que cambia, `3097749052` (+0,27), **no tiene vídeo**: repetida tres
veces da 37,86 / 37,86 / 38,11 por su cuenta. Es indeterminismo que ya estaba.

Y los 15 wallpapers de tipo vídeo, que antes ni se listaban, renderizan los 15.

> Un aviso de método, pagado aquí: la primera pasada dio una escena que «no
> renderiza» con `OSError`. No era el cambio —`2242388122` mide 113,41 antes y
> 113,41 después—, era `/tmp` lleno por correr dos trabajos pesados a la vez.
> `/tmp` es un tmpfs de 7,7 GB y una pasada de las 129 no deja sitio para otra.

### Lo que sigue sin estar

- **El audio.** Dos de las tres escenas con textura de vídeo traen pista AAC y
  los wallpapers de vídeo también; no se reproduce ninguna.
- **Decodificación por hardware.** Todo va por CPU. Un 2160p@60 se sostiene
  —57,4 de 60 fotogramas—, pero es trabajo que VAAPI o NVDEC harían casi gratis.
- **El `.tex` de vídeo con relleno a potencia de dos.** Ninguno del corpus lo
  tiene: los tres declaran el mismo tamaño que su MP4. Se le pide a swscale el
  tamaño de la imagen y ya, pero no está probado contra un caso real porque no
  lo hay.

## Lo siguiente

Por orden de lo que más se nota:

1. ~~Los pases que no enlazan~~ **hecho**: los 297 pares del corpus enlazan en
   Mesa, el driver del escritorio, y 296 en NVIDIA —al que le falta uno que
   tampoco compila—. Y el fallo que el enlace supuestamente tapaba en godrays
   y glow no aparece al volver a medirlo; ver [Compilar no es
   enlazar](#compilar-no-es-enlazar-82-pases-que-se-perdían-sin-decir-nada).
2. ~~Las 2 escenas negras~~ **hecho**: ninguna era un fallo de render, las dos
   leían la copia de un campo en vez del campo —ver [Las dos escenas
   negras](#las-dos-escenas-negras-eran-dos-campos-leídos-de-más)—. Queda
   `1518454472` apagada, y lo que le falta es **bloom**: 34 escenas de 129
   lo encienden y es un pase de post-proceso que no tenemos.
3. ~~Texto~~ **hecho**: se rasteriza y se dibuja, con las 167 capas del corpus
   resolviendo su fuente y la caja reproducida a 1,015 de ancho y 0,997 de
   alto —ver [Un punto son 4,137 unidades de
   lienzo](#un-punto-son-4137-unidades-de-lienzo-y-eso-no-lo-dice-el-formato)—.
   Lo que queda de esas capas ya no es texto sino **scripting**: 148 de las 167
   traen la cadena en un script de ES6 y 133 llaman a `new Date`, así que se
   dibuja la copia que guardó el autor y el reloj sale congelado. Hace falta un
   intérprete con la API del motor, y con él entran también los otros campos
   con script —origin en 23 capas, scale en 22— y el resto de la escena.
4. ~~Reproducir vídeo~~ **hecho**: `src/wevideo.c` lo decodifica con libav y lo
   comparten los dos ejecutores; las 3 escenas con textura de vídeo se mueven y
   los 15 wallpapers de tipo vídeo entran en la biblioteca —ver [Vídeo de
   verdad](#vídeo-de-verdad-un-decodificador-compartido-y-dos-entregas-distintas)—.
   Queda el **audio** (pista AAC en dos de las tres escenas y en los 15
   wallpapers) y la **decodificación por hardware**: hoy todo va por CPU.
5. **Elegir la GPU que renderiza** (ver abajo).
6. ~~Reflejos y luces de tubo~~ **hecho**: el reflejo solo pedía la pirámide de
   mipmaps del buffer de escena, y el tubo venía en `controlpoint` desde el
   principio. Del sistema de iluminación quedan los **focos** y las
   **direccionales**, que el shader declara y la biblioteca no usa: sin una
   sola en el corpus no hay con qué verificar su orientación, así que una
   escena que traiga alguna se sigue dibujando plana.
7. **Audio reactivo**: `g_AudioSpectrum16/32/64` en 33 variantes de shader y
   `audioprocessing*` en ~50 usos de partícula.
8. ~~El puntero de verdad~~ **hecho**: el ratón llega a la escena por la misma
   puerta que el reloj ---marcadores en la plantilla del plan--- y mueve los
   123 sistemas de partículas que lo persiguen en 46 escenas, más
   `g_PointerPosition`, `g_PointerPositionLast` y `g_ParallaxPosition`; ver
   [El ratón entra en la
   escena](#el-ratón-entra-en-la-escena-un-puntero-cuatro-consumidores). Queda
   la **cámara**: `cameraparallax` mueve cada capa según su profundidad en 29
   escenas y falta el número que lleva su `amount` a píxeles.

Y un fallo de uso, sin arreglar: **cambiar el fondo con el escritorio tapado no
recarga el motor**. `recargar()` intercambia el plugin pero el `SceneView` no se
reinstancia, y hace falta reiniciar plasmashell. Visto con una escena en la que
la resolución no cambia nada, así que no es de la fase 2.

De partículas ya no queda vocabulario: los tres cabos —el corro, `remapvalue` y
`orientation`— están cerrados y contados arriba. Lo que sigue fuera de la
simulación son tres cosas, ninguna bloqueante:

- ~~`controlpointattract` sobre puntos atados al cursor (**111 de 136 usos**)~~
  **hecho**: entró con el puntero, como estaba previsto.
- ~~Un `rope` con `orientation: upright`, **1 sistema**: la anchura de la cinta
  la monta nuestro constructor de vértices, perpendicular al camino, y ese la
  quiere vertical.~~ **cerrado sin cambio de render**: la anchura la pone
  `g_OrientationForward`, y con `upright` WE da la misma base que ya se emite.
  Ver [`upright` en una
  cinta](#upright-en-una-cinta-we-la-orienta-como-a-un-sprite-y-da-la-base-de-siempre).
- ~~Dos emisores extra en **1 sistema**: WE permite varios y el corpus solo tiene
  ese; tomar el primero es preferible a sumarlos mal.~~ **hecho**: con la
  biblioteca de 129 son **2 sistemas en 2 escenas**, y ahora emiten por los dos
  al mismo depósito. Ver [Varios
  emisores](#varios-emisores-emiten-todos-al-mismo-deposito).

### Los 19 wallpapers que trae la aplicación: 7 servirían

La instalación de Wallpaper Engine trae los suyos en
`projects/defaultprojects`, sin empaquetar —`scene.json` suelto, sin
`scene.pkg`—, y las herramientas no los ven porque filtran justo por ese
fichero. Suena a deuda de dos líneas; medido, no compensa:

| | |
|---|---|
| escenas 2D ortográficas, que este motor dibuja | **7** — beach, deep_space, dino_run, eagleflag, razer_bedroom, razer_vortex, shimmering_particles |
| con modelos o cámara 3D | **5** — arsenal, demon_core, dna_fragment, neon_sunset, retro |
| no cargan: su escena no se llama `scene.json` | **4** — audiophile, fantasticcar, ricepod, techno (el nombre está en el campo `file` de `project.json`) |
| no son escenas | **3** — dos web de Corsair y una aplicación de Unity |

`beach` renderiza a 0,87 de su preview, o sea bien. `demon_core` sale **negro
entero** y `neon_sunset` casi: los dos declaran modelos y **no** traen
`orthogonalprojection`, que es sobre lo que está construido todo este motor
—lienzo plano, capas, sin cámara ni profundidad—.

Así que enchufarlos hoy ofrecería siete wallpapers de demo de marca y otros
nueve que salen negros. La plomería que falta no es el filtro por `scene.pkg`
sino un segundo origen de wallpapers y el campo `file`; y lo que de verdad
desbloquearía el resto es el soporte de modelos, que es otro subsistema.

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

## El anillo del vórtice, y las dos velocidades que faltaban

Capturas del escritorio de Windows con el WE de verdad —el mejor oráculo que ha
tenido este motor, por encima del `preview.jpg`, porque es la misma escena a la
misma resolución— pusieron tres cosas encima de la mesa a la vez. Las tres
salieron de `3219398263`, la del agujero negro, donde el cielo se llenaba de
**anillos blancos concéntricos** que en WE no existen.

### La tangente es una cuerda: el radio crecía solo

El `vortex` [se dejó como campo de arrastre](#el-vortex-estaba-inerte-en-9-de-sus-12-usos)
—mueve la posición y no toca la velocidad—, y eso sigue siendo lo correcto. Lo
que estaba mal era **cómo** la movía: un paso recto sobre la tangente no es un
arco, es una **cuerda**, y cada paso deja la partícula más lejos del eje.

Con las 2500 unidades por segundo a radio 256 del preset `magic_vortex_1`, el
paso de 1/60 s mide 41,7 unidades y el radio pasa de 256 a `√(256² + 41,7²)`
cada vez: **de 256 a 424 en una sola vida**, un 65 %. Por eso lo que se veía no
era un anillo sino una espiral gorda repetida por 256 partículas.

Se cambia por un giro de Rodrigues alrededor del eje, con el mismo ritmo
angular —la velocidad que pide el campo es lineal, o sea ángulo por radio— y el
radio exacto. Es un arreglo de integración, no de lectura del formato: vale sea
cual sea lo que signifiquen `speedinner` y `speedouter`.

### `distanceouter` es hasta dónde llega, no dónde se satura

Aun con el radio quieto seguía sobrando un anillo entero. El preset declara
`distanceinner: 0`, `distanceouter: 32` y emite a **256**: interpolando y
saturando, toda partícula del sistema cae en el extremo y gira a 2500
unidades/s, que a radio 256 son 9,8 rad/s —vuelta y media por vida—.

La captura dice otra cosa. Las estelas de WE son **rayas cortas y radiales**:
medida sobre la del ángulo superior izquierdo, va de (307, 217) a (440, 140) en
la pantalla, o sea una pendiente de −30°; el radio desde el origen del sistema
—(1920, 1016) del lienzo— cae a −33° y la tangente a +57°. Es radial, no
tangencial: **ahí el vórtice no actúa**.

Así que `distanceouter` acota el alcance del campo, y fuera de él el operador no
hace nada. Sobre los cinco usos del corpus solo cambia a dos: los otros tres
—`Cherry_Blossoms_2` con `speedouter: 0`, `deku-circular_star_trail` con
`distanceouter: 7000` sobre un emisor de 1600, y el `vortex` sin distancias de
`Stars_copy1`— ya daban cero fuera del radio por su cuenta.

### El emisor tenía una velocidad y nadie la leía

Y si el vórtice no las mueve, algo tiene que hacerlo. Lo tenía delante:
`sphererandom` declara `speedmin: 128, speedmax: 128` y `weparticles.py` no
leía ese campo. Las partículas **nacían quietas**.

Cuadra con la medida: la cola de cinta son 8 puntos a 1/60 s, o sea 0,117 s; a
128 unidades/s y escala 5 del objeto son 75 px de lienzo, y las rayas de la
captura miden entre 72 y 90.

En el corpus lo declaran **20 emisores, y en 12 de ellos es la única velocidad
que hay** —no traen `velocityrandom`—. Todos son esferas menos uno, así que la
dirección es la normal: la que ya sorteó la posición. Los dos floats van al
final de la línea `emit` a propósito, para que un ejecutor anterior lea sus 18
y se salte estos dos en vez de descolocarse; importa porque plasmashell
conserva mapeada la `.so` con la que arrancó.

**No** se escala con el `speed` del `instanceoverride`, que sigue tocando solo a
`velocityrandom`: con el 0,3 que declara este objeto las rayas medirían 22 px y
la captura las tiene a 75.

### Lo medido sobre las 129

Una pasada de luminancia antes y otra después: **cambian 8 escenas y solo dos de
forma apreciable**. `3219398263` baja de 100,72 a 62,51 —es el arreglo: dejar de
pintar un anillo blanco saturado por medio cielo *tiene* que bajar la media, y
[ya pasó antes con esta misma escena](#el-vortex-estaba-inerte-en-9-de-sus-12-usos)—.
La otra es `3577990983`, y es del arreglo de la homografía que viene ahora.

## La homografía salía transpuesta: `m[i][j]` no es lo mismo en los dos lenguajes

La segunda captura, la del reloj de `3029745918`, tenía la hora del sitio y del
tamaño equivocados. El tamaño lo explicaba el efecto `perspective` de la capa,
que sí se aplicaba; el sitio, no.

`common_perspective.h` construye la matriz **por índices** —`m[0][1] = ...`— y
es el **único fichero del corpus que lo hace**: todos los demás usan el
constructor. Y ahí los dos lenguajes no dicen lo mismo: `m[i][j]` es
fila-columna en HLSL y **columna-fila** en GLSL. Escrita igual, sale
transpuesta.

En todo lo demás la convención aguanta sola, y conviene entender por qué: las
matrices que suben por uniform se escriben **por filas** y GL las lee **por
columnas**, así que la variable del shader acaba siendo la misma matriz que ve
HLSL y `mul(v, M)` —o sea `v * M`— da lo que da allí. Una matriz construida
DENTRO del shader no pasa por esa subida y se queda del otro lado.

Transponer una homografía no es un detalle cosmético: conserva la parte lineal
—por eso la hora salía del tamaño correcto— y **cambia de sitio la traslación**.

Se arregla en el traductor, devolviendo `transpose(m)` en `squareToQuad`, y
alcanza a los **10 efectos que incluyen ese header**: `perspective`, `clouds`,
`reflection`, `swing`, `lightshafts`, `watercaustics`, `waterwaves`,
`cursorripple`, `fluidsimulation` e `iris`. Sobre las 129 mueve la luz de una
sola escena, `3577990983`, de 46,31 a 40,96: sus cinco `waterwaves` dejan de
sembrar el cielo de rayas verticales blancas que su preview no tiene.

## Una capa de texto se ancla por su alineación, no por su centro

Y el resto del desplazamiento del reloj era del otro lado. Una capa de imagen
dice a qué punto de su rectángulo se refiere `origin` con `alignment`; una capa
de texto **no trae `alignment`** —ninguno de los 172 del corpus— sino
`horizontalalign` y `verticalalign`, y hacen exactamente lo mismo.

El reloj dice `horizontalalign: right`: su hora acaba EN el origen, y aquí salía
media caja —646 px de lienzo— más a la derecha, encima del coche.

Se traducen los dos campos a un `alignment` equivalente para que el
desplazamiento lo siga haciendo un solo sitio. Solo mueve a **12 de los 172**:
11 declaran `horizontalalign` distinto de `center` —8 `left` y 3 `right`— y 3
declaran `verticalalign` —2 `top` y 1 `bottom`—; los demás dicen `center`, que
es lo que el cálculo ya asumía. Ocho de los doce son los títulos de canción y
artista de los dos wallpapers con reproductor, que se guardan vacíos y no
dibujan nada; los que sí se ven son los dos relojes.

Con las dos cosas puestas, y forzando la misma cadena que la captura para poder
superponerlas, la hora cae a **17 px de pantalla** de donde WE la pone, sobre
1918 de ancho.

### Y lo que faltaba: la hora era la del autor

La posición ya es la de WE; el **contenido** no lo era. `3029745918` calcula su
hora con un script de JavaScript y aquí se dibujaba el `value` que el autor
tenía en pantalla al guardar —"12:00"—: 148 de las 172 capas de texto traen
script y 133 llaman a `new Date`.

Lo que se pensó entonces, y que resultó ser la mitad de la historia: un reloj no
necesita un motor de JavaScript, necesita un atlas con el alfabeto en vez de con
la cadena congelada, una directiva en el plan con el formato, y que el ejecutor
rehaga los quads —lo mismo que ya hace `skinMeshes` con las mallas puppet, y en
los dos ejecutores a la vez, como siempre—. La otra mitad, la de deducir ese
formato sin ejecutar JavaScript, está en
[la sección siguiente](#la-hora-de-verdad-interpretar-el-script-sin-un-motor-de-javascript).

## La hora de verdad: interpretar el script sin un motor de JavaScript

La capa de reloj ya cae donde WE la pone, pero enseñaba las 12:00 del día que
el autor guardó el wallpaper. La cadena no está en la escena: está en un
`export function update(value)` que la calcula con `new Date()`. Son **148 de
las 172 capas de texto** del corpus, y **133 llaman a `new Date`**.

### Por qué no vale con ejecutarlo una vez

Y por qué no vale un motor de JavaScript, aunque lo hubiera: ejecutar el script
al preparar el plan cambia una hora congelada de 2021 por una congelada de hoy.
El plan es una **foto** —el ejecutor lo repite cada fotograma cambiando solo
`g_Time`— así que lo que tiene que viajar en él no es la cadena sino el
**formato**, y el ejecutor rellenarlo con su reloj. Eso parte el trabajo en
tres, y los tres tienen que decir lo mismo:

```
wescript.py   el JavaScript  -> la plantilla («%H:%M») y sus tablas de nombres
wetext.py     la plantilla   -> un atlas con el ALFABETO y las métricas
wereloj.c     la plantilla   -> los quads, cada minuto, en LOS DOS ejecutores
```

### Un intérprete, no un motor

En esta máquina no hay `node`, ni `qjs`, ni `deno`, ni un intérprete de
JavaScript en Python; y meter uno como dependencia de un fondo de escritorio no
sale a cuenta. Tampoco hace falta: el vocabulario de los **51 scripts
distintos** es diminuto y cerrado. Sale de contarlo, no de suponerlo:

| | |
|---|---|
| palabras clave | `if`/`else`, `let`/`var`/`const`, `for`, `while`, `switch`/`case`/`break`, `return`, `new`, `typeof` |
| métodos | `slice` 52, `toString` 30, `getMonth` 53, `getDate` 47, `getHours` 33, `getDay` 28, `getFullYear` 27, `getMinutes` 18, `getSeconds` 17, `padStart` 1 |

Un léxico, un parser de precedencia y un evaluador de árbol: 129 de los 148
salen. Los 19 que no son los que usan `engine` (el objeto global de WE, 5),
`import` (2), una expresión regular literal (1) y ocho que ni siquiera exportan
`update`.

Lo que más costó no fue el intérprete sino **`createScriptProperties()`**. Es
una cadena de `.addCheckbox({...}).addText({...}).finish()` que declara las
propiedades **con su valor por defecto**, y la escena solo guarda en
`scriptproperties` las que el usuario tocó. Sin construir esa cadena, un
`if (!scriptProperties.use24hFormat)` lee `undefined` y da la vuelta al reloj.
Con ella, el salto fue de **6 scripts a 129**.

### Deducir el formato: cortar siete muestras a la vez

Con el intérprete se puede preguntar qué escribe el script en cualquier
instante. Falta pasar de eso a una plantilla, y ahí hay dos maneras de
equivocarse.

La primera es **deducirla de una sola cadena**: en `21:46` el `21` puede ser la
hora, el día o el mes. La segunda es **diferenciar dos cadenas cortas**:
`SequenceMatcher` empareja el `2` de `21:46` con el de `16:22` y se lleva por
delante los dos puntos, que es el único carácter que de verdad era literal. Con
eso el barrido bajó de 82 formatos a 23.

Lo que funciona es cortar **siete muestras a la vez**, con vuelta atrás: un
campo solo vale si encaja en las siete, y un literal solo vale si las siete
traen el mismo carácter. Las siete no comparten ni hora, ni minuto, ni día, ni
mes, ni año, e incluyen los sitios donde un formato se rompe —la medianoche y
el mediodía del reloj de 12 horas, y los valores de una sola cifra, que separan
el campo rellenado con ceros del que no—.

### Los nombres no se adivinan: se reconocen

`Friday, November 19` necesita una tabla de siete palabras y otra de doce, y en
esta biblioteca las hay en inglés, español, francés, ruso, vietnamita y chino.
No se traducen: **están escritas en el script**, como literales de cadena, y lo
que hay que hacer es reconocer cuál va con cuál.

Se barre el campo y se mira qué literal del script aparece en la salida. Con
**una** muestra por valor no basta: barriendo los doce meses el día de la
semana también cambia, y `Wednesday` sale en marzo y en ningún otro mes igual
que `March`. Con **tres** muestras por valor —años y días distintos— el nombre
del mes es el único literal que está en las tres. Eso subió de 82 a 124.

El tercer campo de tabla no tiene equivalente en `strftime` y lleva código
propio: la franja del día. `2821288001` escribe `晚上` de siete a once de la
noche, y como tabla de 24 horas cae sola.

### Lo que da la garantía es la comprobación, no la deducción

Nada de lo anterior decide nada por su cuenta. Un formato solo se declara si
**reproduce lo que devuelve el script en ~1050 instantes** repartidos por
cuatro años, que recorren las 24 horas en punto y en su último segundo, los
doce meses, los siete días y un bisiesto. Con una sola diferencia se descarta y
la capa se queda con su cadena congelada, que es exactamente lo que hacía
antes. Por eso esto no puede empeorar ninguna escena: o acierta o no toca nada.

Ahí se cayó `2946362143`, y por un motivo que conviene tener escrito: su tabla
de días empieza el sábado por `\n`. Es un reloj de **dos líneas** y la
disposición del ejecutor es de una, así que se descarta a propósito en vez de
dibujarlo en el renglón que no es.

### El alfabeto, y lo que se pierde

`wetext` rasteriza el texto **por línea** —PIL resuelve kerning, ligaduras y
shaping de una vez— y con un reloj no hay línea que rasterizar. Así que la ruta
del reloj rasteriza **glifo a glifo**: un atlas con cada carácter que la
plantilla puede llegar a escribir, que para `%H:%M` son once y para la fecha
más larga del corpus 47, más lo que mide cada uno.

Se pierde el kerning. Con dígitos no se nota —las cifras de una fuente de
reloj son tabulares— y está medido: la misma cadena por las dos rutas da los
mismos avances hasta el último decimal en la fuente de `3029745918`. En un
nombre de mes sí podría notarse, y queda escrito por si algún día se ve
apretado.

La malla se reserva para el **peor caso** de la plantilla, porque el búfer se
pide una vez y la cadena cambia; los glifos que sobran salen degenerados. Y se
hornea con la hora de generación del plan, para que un ejecutor que no sepa de
relojes siga dibujando algo en vez de un rectángulo vacío.

### Y la locale, otra vez

`wereloj.c` lee sus métricas del plan con `strtof`, y `strtof` mira
`LC_NUMERIC`. Dentro de plasmashell, que es `es_ES`, `0.899` se lee como `0` y
el alfabeto entero se va a cero **sin un solo error por medio**: es el mismo
agujero por el que [se cayeron las partículas](#y-luego-en-el-escritorio). La
cura es la misma —`uselocale` para este hilo y solo la parte numérica— y
`test_wereloj.py` lo comprueba con la locale puesta, que es la única manera de
que la prueba pruebe algo.

### Lo medido sobre las 129

**123 capas de reloj en 20 escenas** dan la hora de verdad. Las dos mitades
—`quads_de_reloj` en Python y `we_reloj_vertices` en C— coinciden en las 123,
en seis instantes que cruzan la medianoche, el cambio de mes y un 29 de
febrero, y con las locales `C` y `es_ES` las dos.

Las 25 capas con script que se quedan sin reloj están contadas arriba: 19 que
el intérprete no cubre, una de dos líneas y cinco que no son un reloj —un
contador de fps, un `undefined` y tres títulos de canción vacíos—.

## `wectl list` dice de qué tipo es cada wallpaper

La lista enseñaba id y título, y con eso no se distingue una escena de un
vídeo —que se preparan por caminos completamente distintos— ni se entiende por
qué falta uno que sí está instalado.

El tipo lo declara `project.json`, y **hay que normalizarlo**: 24 de los 148
lo escriben con mayúscula inicial. Contarlo tal cual parte la biblioteca en
seis tipos en vez de tres.

| | |
|---|---|
| `scene` | **129** — las del corpus |
| `video` | **15** |
| `web` | **4** — no se ponen |

### Enseñar también los que no se pueden poner

`biblioteca()` solo devolvía lo que el motor sabe poner, así que los cuatro
`web` no salían en la lista. Y ahí está el problema: **un wallpaper que no
aparece no se distingue de uno que no está instalado**, que es justo la duda
de quien no encuentra el suyo.

Así que `list` pasa a enseñar el inventario entero con su tipo, y el pie dice
cuáles no se pueden poner. Pero **`set` y `shuffle` siguen viendo solo los
144 que funcionan**: por eso son dos funciones y no una —`inventario()` y
`biblioteca()`—, porque son dos preguntas distintas y mezclarlas dejaría a la
rotación eligiendo un `web` cada pocas vueltas.

De ahí sale un cabo que había que atar: `set` sobre un `web` respondía «ningún
wallpaper coincide», y desde que la lista los enseña eso es **falso**. Ahora
dice el motivo —`es de tipo web, y este motor no pone los de ese tipo`—, y lo
dice tanto por id como por título.

### El que no es un wallpaper

`2336642563` es el único directorio sin `type`, y no es que le falte: trae
`category: Asset`. Es un paquete de materiales que otros wallpapers importan
—`contents/` con `materials`, `models`, `particles` y `shaders`—, no un fondo.
Antes se caía de la lista por no tener `scene.pkg`, que era la razón
equivocada; ahora se cae por no ser un wallpaper, que es la buena.

## Las estrellas no parpadeaban: `colorrandom` sin `max` sortea hasta negro

Otra captura del escritorio de Windows, esta de `2821288001` —la *City*—, con
dos quejas: los destellos redondos salen **más gordos y más duros** que en WE, y
por la parte de arriba cruza una **lluvia de estrellas fugaces** que allí no
está. Son dos fallos distintos con la misma captura por oráculo.

El oráculo se monta restando: se renderiza la escena **solo con el fondo** —el
resto de objetos invisibles— y se resta de la captura. El fondo de esta escena
no se mueve (`t=20` y `t=27` dan el mismo píxel), así que lo que queda es
exactamente lo que WE añade encima: sus partículas, y su *bloom*. Alineado 1:1
en (106, 0), que es el recorte «cubrir» de un 16:9 en un panel 16:10; se
comprueba que la captura es nativa y no un reescalado midiendo el gradiente
medio —4,266 contra 4,248 del render propio, y 3,522 si se baja y se sube a 2x—.

### El tamaño del sprite: el brillo explicaba una parte, no toda

La primera sospecha fue que el quad saliera al doble. Se descartó con el rayo
—`lightning1` declara `size` 800–1000 y el nuestro sale de 129 px de ancho, el
de la captura mide 92— pero **ese descarte no vale**, y conviene dejarlo escrito
antes de que alguien se apoye en él: el rayo nuestro sale de **451x129** y el de
WE de **92x251**, o sea *girado 90°*, y encima son fotogramas distintos de una
hoja de 64. Comparar el 129 con el 92 supone que los ejes se corresponden, y no
se corresponden. El rayo no decide nada; hay un cabo suelto en la orientación de
la hoja de sprites y otro en el tamaño. Ver «Pendiente».

**Cerrado:** no era la hoja sino el giro. `rotationrandom` vacío gira una vuelta entera; ver [Los valores por defecto estaban en el binario](#los-valores-por-defecto-estaban-en-el-binario-el-giro-la-caja-el-ritmo-y-el-sesgo).

Lo que sí explicaba una buena parte era el **brillo**. En la misma ventana de 1400x1060:

| | luz añadida | píxeles > +30 | > +100 | > +200 |
|---|---|---|---|---|
| WE | 4,69 M | 28 897 | 883 | **30** |
| nosotros | 1,79 M | 17 322 | 5 354 | **448** |

WE mete **más** luz total y **quince veces menos** píxeles saturados: la reparte,
nosotros la concentramos. Un `halo_6` es un disco de alfa 255 plano, así que a
alfa alto son 8 px de blanco puro —el «destello gordo y duro»—, y al bajarlo se
queda en la punta, que es el punto pequeño y nítido de la captura.

### La pista estaba en un campo escrito de más

`shootingstarglow.json` declara `colorrandom` con `min` **y** `max`, los dos
`255 255 255`. Escribir un campo redundante no tiene sentido… salvo que no sea
redundante. Y no lo es: en el corpus **158 objetos de 47 escenas** escriben
`max` igual a `min`, y nadie repite eso 158 veces por gusto. Lo escriben porque
es la única forma de pedir un color **constante**.

Luego el defecto de `max` no es `min`, que es lo que hacíamos: es **negro**. Sin
`max` el sorteo va del color declarado a cero con [el factor único de siempre](#decisiones-que-son-lecturas-no-hechos),
o sea el mismo tono a un brillo cualquiera. Es justo lo que hace parpadear un
campo de estrellas, y lo que separa los `Star_0N` del autor —que solo declaran
`min`— de su propio `shootingstarglow`, que declara los dos.

Con eso, los píxeles saturados pasan de 448 a **63** (WE: 30) y los de más de
+100 de 5 354 a **1 868** (WE: 883). Toca a **160 objetos de 22 escenas**.

### El ritmo implícito estaba en el extremo, y se comía el `instanceoverride`

**Sustituido:** el motor de WE da `rate` 10 cuando falta; ver [Los valores por defecto estaban en el binario](#los-valores-por-defecto-estaban-en-el-binario-el-giro-la-caja-el-ritmo-y-el-sesgo).

La lluvia de fugaces es otra cosa. `Shooting_Star_01` no declara `rate`, y
[el ritmo implícito](#el-reparto) lo estimaba como `maxcount / vida`: el ritmo
exacto que deja el depósito **lleno**, o sea 35 estrellas a la vez para siempre.
La captura de WE enseña menos de diez.

Ese «lleno» es el extremo, no la costumbre. Medido sobre los **961 emisores del
corpus que sí declaran ritmo**, la mediana de `rate · vida / maxcount` es
**0,48** y solo uno de cada cuatro llega a saturar. Las propias plantillas de WE
lo dicen: `example.json` sostiene 80 de 500 y `examplecursoravoid` 800 de 1000.
`maxcount` es un tope de seguridad, no la densidad buscada.

Y de paso, el `rate` del `instanceoverride` **se perdía**: se multiplicaba sobre
el cero del preset —0 × 1,2 sigue siendo 0— y después esta función lo
sobrescribía. Son 12 de los 72 emisores sin ritmo.

Con la ocupación típica y el factor recuperado, la *City* pasa de 31 fugaces
vivas a 19. Que el campo falte no es descuido del autor: `ember_small` y
`dust_motes_0`, **plantillas del propio WE**, tampoco lo traen.

### Lo medido sobre las 129

Cambian **42 escenas**, casi todas por debajo del 1 %, y **cero regresiones**.
La única que se mueve de verdad es `2868108515` —*god of war ragnarok*, con 25
copias del mismo sistema blanco—, que baja de 133,30 a 113,34: frente a su
`preview.jpg`, que es un fotograma de WE, pasa de **1,425 a 1,212**. Era la
escena más sobreexpuesta del corpus y ahora lo es menos.

### La otra mitad era el bloom

La resta contra la captura enseña un **halo suave alrededor de todo lo
brillante**, bordes de edificio incluidos, y el fondo propio es idéntico y
estático: ese halo no es nuestro. Es el *bloom*, que esta escena declara
—`bloom: true`, `bloomstrength 2.0`, `bloomthreshold 0.65`— y que el motor no
implementaba. Lo pide una escena de cada cuatro: **33 de las 129**.

## El bloom son tres shaders de WE y un objeto más

No hubo que escribir GLSL: los tres shaders están en los assets de WE y los
traduce el mismo `weshader` que todo lo demás. Lo único que había que deducir
es **la cadena** —qué lee cada uno y a qué resolución escribe— y eso lo dicen
sus nombres:

```
escena  --downsample_quarter_bloom-->  Quarter   umbral, saturación, fuerza
Quarter --downsample_eighth_blur_v-->  Eighth    13 taps en X
Eighth  --blur_h_bloom-------------->  Eighth    13 taps en Y
Eighth  --composición--------------->  pantalla  se SUMA a la escena
```

(La `h` de `blur_h_bloom` desenfoca en Y y la `v` de `downsample_eighth_blur_v`
en X. Los nombres están cambiados en WE; manda el código.)

### `g_TexelSize` es el texel de PANTALLA, y lo dice la captura

La única incógnita real era a qué se ata `g_TexelSize`, porque los dos
desenfoques espacian sus taps `g_TexelSize * 8.0` y de ahí sale todo el radio.
Tres lecturas posibles —texel del buffer que lee, del que escribe, o de la
pantalla— y una diferencia de 8x entre la primera y la última.

Lo decide la medida. Correlando la diferencia contra la captura con el mismo
umbral desenfocado a varias sigmas, el máximo cae **limpio en 16 px**:

| sigma | 4 | 8 | 12 | **16** | 24 | 32 | 64 | 128 |
|---|---|---|---|---|---|---|---|---|
| correlación | 0,291 | 0,349 | 0,381 | **0,395** | 0,387 | 0,356 | 0,191 | 0,025 |

Y 16 px es exactamente lo que sale del texel de pantalla: espaciado `8 · 1/W`,
o sea 8 px, que además es **un texel justo del buffer Eighth** donde trabajan
los dos desenfoques —el kernel queda bien muestreado, no a saltos—, y 13 taps
gaussianos sobre ese espaciado dan sigma ≈ 2 espaciados. Las tres cosas cuadran
a la vez, que es lo que separa una lectura de una coincidencia. Es además el
valor que `werender.py` ya emitía para el resto de la escena.

### El umbral va DESPUÉS de promediar, y eso se ve

`downsample_quarter_bloom` promedia sus cuatro taps y **luego** aplica el
umbral. No es un detalle de orden: un píxel brillante suelto se promedia con
sus vecinos oscuros, baja del umbral y no aporta halo. Por eso el bloom de WE
rodea zonas brillantes —un rótulo de neón, una nube— y no puntos sueltos, y por
eso simularlo umbralizando a resolución completa daba de más.

### No hay que tocar los ejecutores

Va como **un objeto más**, el último: sus pases escriben en buffers con nombre
y el último deja el halo en el buffer del objeto, que se compone sumando
(`aditivo 3`, o sea `glBlendFunc(GL_ONE, GL_ONE)`). Ni `glexec.c` ni
`glexecutor.cpp` se enteran de que eso es bloom; los buffers se llaman
`...Quarter` y `...Eighth` porque de ahí sacan su resolución los dos, que ya
sabían hacerlo.

El único GLSL escrito a mano del renderizador es la suma final —WE la hace
dentro de su motor, así que no hay nada que traducir—, y escribe **alfa cero**
a propósito: el modo 3 suma los cuatro canales, y sumar alfa volvería opaca la
escena entera.

### Lo medido sobre las 129

| | la City contra la captura | |
|---|---|---|
| | luz añadida | píxeles > +200 |
| Wallpaper Engine | 4,69 M | 30 |
| antes de esta sesión | 1,79 M | 448 |
| con `colorrandom` y el ritmo | 0,83 M | 63 |
| **con bloom** | **4,25 M** | **65** |

Sobre el corpus cambian **39 escenas** —las 33 que lo declaran, más seis que se
mueven ±0,14, que es el ruido de repetición que ya tenían—. Frente al
`preview.jpg` de cada autor, que es un fotograma de WE, la mediana de
`|razón − 1|` baja de **0,171 a 0,135**: 24 escenas se acercan y 10 se alejan
—todas las que ya estaban por encima de 1 por otro motivo—.

Y `test_luminancia` pasa **por primera vez sin escenas apagadas**:
`1518454472` sube de 6,26 a 16,77 de media —razón 0,089 → 0,239— y deja de
estar por debajo del 15 % de su preview. Llevaba marcada toda la sesión.

**Lo que se deja fuera a propósito.** Nueve de las 33 declaran además
`hdr: true`, con su propio juego de parámetros (`bloomhdrthreshold`,
`bloomhdrscatter`, `bloomhdriterations`). Ese camino pide un buffer en coma
flotante y una pirámide de iteraciones, y aquí se les aplica la cadena LDR con
sus parámetros LDR: es lo que hay sin buffers HDR, y ninguna de las nueve
empeora.

## Pendiente: tres cabos de las partículas, medidos y sin cerrar

Anotado a propósito para retomarlo en frío. Los tres salen de comparar
`2821288001` contra la captura de Windows, y los tres tienen ya la medida hecha:
lo que falta es la lectura del formato que los explique, no volver a medir.

### 1. Los destellos: NO es el tamaño, y el factor 0,5 está probado y descartado

A ojo los puntos redondos salen más gordos que en WE, y es verdad. Lo que **no**
es verdad es que sea un problema de escala, y conviene dejarlo cerrado porque es
la trampa obvia.

**El oráculo, que ya no depende de una captura suelta.** El `preview.jpg` que
sube el autor es un fotograma de WE. Localizado por correlación normalizada
—barriendo lado y origen del recorte— cubre **1720x1720 del lienzo desde
(1060, 220)**, o sea escala 0,5023, con correlación **0,982**. A partir de ahí
las dos imágenes se comparan a la misma escala restando el fondo. Es
reproducible sin nada externo.

Medido así, con el fondo restado y el mismo umbral en las dos:

| manchas redondas (px) | <3 | 3–4 | 5–6 | 7–8 | 9–11 | grandes |
|---|---|---|---|---|---|---|
| WE (captura) | 1 | **26** | 1 | 1 | 3 | 23, 39, 51 |
| nosotros | 0 | 0 | 8 | 11 | 4 | 21, 36 |
| nosotros x0,5 | 0 | 5 | 9 | 0 | 0 | 34 |

Y por sistema, aislando cada uno sobre el mismo fondo:

| sistema | textura | `size` | ancho medido |
|---|---|---|---|
| `Star_01` | `halo` (gaussiana ancha) | 15–20 | 4–6 px |
| `Star_02` / `Star_06` | `halo_6` (**disco plano**) | 14–18 | 6–8 px |
| `Star_04` | estrella de 4 puntas | 150–180 | 25–31 px |

**Tres cosas que descartan el factor de escala:**

1. **Los sprites grandes ya coinciden.** `Star_04` sale de 25–31 px y las manchas
   grandes de WE miden 23–51. Un factor global movería también estos, y los
   sacaría de rango: probado, se quedan en 34 y pierden una de las tres.
2. **El camino de geometry shader no dobla nada.** Era la sospecha buena —WE en
   Windows usa GS y nosotros la ruta sin GS— pero `genericparticle.geom` llama a
   la **misma** `ComputeParticlePosition` con `sprite ∈ {0,1}²`. El quad mide
   `size` por los dos caminos.
3. **La forma de la distribución no es la de un reescalado.** WE tiene un pico
   estrecho en 3–4 px y un HUECO en 5–8. Multiplicar por 0,5 desplaza nuestra
   campana pero no la estrecha: quedan 5 en 3–4 y 9 en 5–6 donde WE tiene 26 y 1.
   Un factor mueve una población; aquí faltan manchas de un tipo que no
   producimos.

Así que el diámetro nuestro no está mal: **falta la población pequeña**.

### 1a. Descartado: no es la resolución, y cuidado con medir anchos

Sospecha razonable —que el sprite no se adapte a la resolución de la pantalla y
por eso se vea gordo—. **No es.** Renderizando `Star_01` aislado a cuatro
resoluciones, el área encendida va como el cuadrado de la escala con razón
**1,00** en las cuatro: el sprite escala exacto.

Y una trampa de método que estuvo a punto de colar lo contrario. La primera
medida fue la MEDIANA DEL ANCHO de las manchas, y daba 16,2 / 9,0 / 8,1 / 6,0
unidades de lienzo al bajar la resolución —o sea, aparentemente, un sprite que
no encoge—. Es un artefacto: a baja resolución quedan pocas manchas por encima
del umbral y la mediana de un puñado de enteros pequeños es ruido. **El área
sobre todo el cuadro no tiene ese problema y es la que decide.**

El camino en vivo tampoco escala: con `FitMode` en cubrir y un lienzo de
2133x1200 sobre una vista de 1920x1200, `qMax(1920/2133, 1200/1200)` da 1,0, o
sea recorte 1:1 sin estirar. Lo que ve plasmashell es lo mismo que el render
offline, recortado.

### 1b. Lo que falta son los sistemas HIJOS

De dónde salen esos cientos de puntitos de 3–4 px, brillantes y con un halo
tenue alrededor: de `shootingstarglow`, que `Star_04` cuelga como hijo
`eventspawn` con `maxcount: 500`. Su textura es `halo_4`, y `halo_4` es
justo eso —un **núcleo brillante que ocupa el 8 % de la textura** sobre una
meseta tenue—. A `size` 100–150 el quad mide 50–75 px y el núcleo **3–5 px**:
exactamente el pico de WE, con su halo tenue explicando de paso por qué el
resto de la mancha no llega al umbral.

Y no los dibujamos: `weparticles.py` recorre `children` para el censo pero solo
emite un `.psys` por objeto de la escena. En el corpus son **232 sistemas con
hijos en 61 escenas** —69 `eventfollow`, 23 `eventspawn`, 34 `static` y 286 sin
`type`—, o sea uno de cada cinco.

**Cómo cerrarlo.** Es un subsistema, no un ajuste: hace falta que un sistema
pueda emitir otro en la muerte (`eventspawn`), pegado a la partícula viva
(`eventfollow`) o clavado al emisor (`static`), y que cada hijo tenga su propio
pase con su material. El reparto natural es el de siempre —`weparticles.py`
resuelve el hijo como un `.psys` más y `werender.py` le da su pase—, y lo que
hay que decidir es de dónde saca el hijo su origen en cada uno de los tres
modos. Empezar por `eventspawn`, que es el de esta escena y el que no necesita
seguir a nada.

### 2. La lluvia de estrellas sale toda del mismo punto

En la captura las fugaces entran por sitios distintos del cielo; aquí salen
todas del mismo. La causa está a la vista en el preset: el emisor de
`Shooting_Star_01` es un `boxrandom` con `origin: "-250 250 0"` y **sin
`distancemax`**, así que la caja mide cero y las partículas nacen todas en el
mismo punto.

Son **30 emisores de 7 escenas** los que no declaran `distancemax`, contra 1060
que sí. Que WE lo omita quiere decir que su defecto no es cero —igual que pasó
con [`rate`](#el-ritmo-implicito-estaba-en-el-extremo-y-se-comia-el-instanceoverride)
y con [`max` de `colorrandom`](#la-pista-estaba-en-un-campo-escrito-de-mas)—, y
el patrón se repite: **el campo que falta no vale cero, vale el defecto del
editor**. Aquí ni siquiera hace falta adivinar el número exacto para mejorar:
cualquier caja no degenerada reparte la lluvia.

**Cómo cerrarlo.** Mirar la distribución de `distancemax` declarado en los otros
1060 emisores del mismo tipo, y ver si los 30 sin declarar comparten preset con
alguno que sí lo declare —que es como se cazó lo del `rate`—.

### 3. La estela es corta y gorda; debería ser fina y larga

Dos cosas distintas, y la segunda tiene el culpable localizado:

- **Gorda**: es el punto 1. El ancho de una cinta es `2 · size` por la escala
  del objeto; con `size` 3–5 y escala 3 salen 10–17 px de lienzo donde WE
  enseña 1,5 de FWHM.
- **Corta**: `_cinta` deja la cola en `CINTA_PUNTOS = 8` pasos, o sea 0,13 s,
  cuando el preset declara `length: 0.4` —24 pasos a 60 Hz—. El `min()` de
  `_cinta` deja ganar al defecto de `segments` sobre el `length` declarado.
  **68 de las 74 cintas del corpus no declaran `segments`**, y 30 de ellas sí
  declaran `length` (0,2 / 0,4 / 0,5 / 0,6 / 3 / 30). O sea: el campo que el
  autor escribe lo pisa el defecto del campo que no escribe.

**Cómo cerrarlo.** Es el más barato de los tres y el más contenido: cuando no
hay `segments`, la cola debería salir de `length`, no de un 8 fijo. Sube el
coste de simulación de 68 sistemas, así que hay que mirar el tope de 32 pasos y
medirlo con `test_luminancia` antes y después.

## El lienzo del autor no es un límite de resolución: 38 escenas salían ampliadas

Síntoma: en el escritorio los destellos se ven **más gordos y más juntos** que
en el render offline de la misma escena. La sospecha razonable —que algo no se
adapte a la resolución— resultó ser cierta, pero no donde se buscaba.

Lo dice el diario del propio motor en vivo, que ya traza el encaje:

```
escena 1280x720  -> se ve 1152x720  -> destino 1920x1200   x1,67
escena 1024x1024 -> se ve 1024x640  -> destino 1920x1200   x1,88
escena 1920x1080 -> se ve 1728x1080 -> destino 1920x1200   x1,11
escena 2133x1200 -> se ve 1920x1200 -> destino 1920x1200   x1,00
```

Las tres primeras se dibujan a un lienzo **más pequeño que la pantalla** y el
blit final las amplía. Todo sale más gordo y más borroso, y las partículas más
juntas porque se ve menos escena en el mismo panel.

La causa era un `min(1.0, ...)` en `resolucion_de_dibujo`, puesto con este
razonamiento: *«pintar más puntos de los que dibujó el autor no añade detalle,
solo gasto»*. **Es falso.** El lienzo de WE es un ESPACIO DE COORDENADAS, no un
raster: una escena de lienzo 1280x720 lleva texturas de 4K, shaders, partículas
y texto, y su detalle no acaba en 720 líneas. WE dibuja a la resolución de la
pantalla y usa el lienzo solo para colocar.

Quitando el tope, el factor sigue bajando para las escenas grandes —que es para
lo que se puso, y sigue valiendo: el 72 % de la biblioteca pinta de más— y ahora
también sube para las pequeñas.

### Lo medido

**38 de las 129** tenían el lienzo más pequeño que un panel de 1920x1200:
mediana x1,11 y hasta x3,40. Renderizadas las 38 a resolución de pantalla:
**38 OK, 0 con problema** —ninguna falla, ninguna sale negra y todas dan
exactamente el tamaño esperado—. La más extrema, `2946362143`, pasa de un
lienzo de 564x1120 a dibujar 1920x3813 y sigue tardando 0,8 s.

`test_luminancia` sale igual, y conviene saber **por qué no vale como oráculo
aquí**: construye `Renderer(esc, glexec, 4.0)` sin resolución de pantalla, así
que dibuja al lienzo del autor y este camino no se ejercita. Sus cifras salen
idénticas línea a línea, lo cual es correcto y no es evidencia. La media de
luminancia además es casi invariante a la resolución: lo que cambia es la
nitidez, y eso no lo mide.

### Lo que NO explica

La City (`2821288001`) tiene lienzo 3840x2160, o sea que ya se dibujaba a
2133x1200 y **no se ampliaba**. Su diámetro de destello sigue donde estaba; ver
«Pendiente». Este arreglo explica el síntoma en el escritorio para 38 escenas,
no para esa.

## Sistemas hijos: `eventspawn`

Un preset de partículas puede colgar otro en `children`. El caso de la `City`:
`Star_04` cuelga `shootingstarglow` con `type: "eventspawn"`, o sea **el hijo
estalla donde muere cada partícula del padre**. En el corpus hay 232 sistemas
con hijos en 61 escenas —69 `eventfollow`, 23 `eventspawn`, 34 `static` y 286
sin `type`—; aquí se implementa **solo `eventspawn`**.

### El hijo es un objeto hermano, no un pase más del padre

`shootingstarglow` trae su propio material, su propia textura (`halo_4`) y su
propia mezcla. Eso no cabe dentro del pase del padre, así que `wescene` lo
devuelve como un **objeto hermano** —misma colocación, dibujado justo detrás— y
de ahí en adelante el resto del motor no tiene que saber que es un hijo: se le
arma su `.psys`, su pase y su composición como a cualquier otro.

Lo único que los ata es una línea nueva del plan:

```
psyspadre <hijo> <padre> <ráfaga>
```

### La lectura del formato

- **El depósito sale de `children`, la ráfaga del preset.** `shootingstarglow`
  declara `maxcount: 4` y la entrada de `children` dice `maxcount: 500`. Son dos
  cosas distintas y encajan: el preset describe UN estallido —4 partículas, con
  `instantaneous`— y la entrada dice cuántas caben entre todos los estallidos a
  la vez. Leerlo al revés daría 500 partículas por muerte.
- **El emisor libre del hijo se apaga.** Un hijo `eventspawn` solo nace por
  evento. `shootingstarglow` ya trae `rate: 0`, pero `Flare` no declara ritmo y
  [el ritmo implícito](#el-ritmo-implicito-estaba-en-el-extremo-y-se-comia-el-instanceoverride)
  le daría uno: emitiría por su cuenta además de por evento.

### Por qué se simulan en tándem, y no uno detrás de otro

Es la decisión que cuesta si se hace mal. Los dos son sistemas separados y cada
ejecutor los actualiza por su lado, así que la tentación es que el padre apunte
sus muertes en una cola y el hijo la vacíe en su propio `update`.

No vale: la primera llamada del padre **recupera hasta 60 s de golpe**, y esas
muertes llegarían todas juntas. El hijo estallaría entero en un solo instante en
vez de repartido por el tiempo, y con el depósito lleno de partículas de la
misma edad, que además morirían a la vez.

Así que el padre lo lleva de la mano: su `we_psys_update` da el paso de los dos
—muertes de ESE paso, estallidos de ESE paso, y luego el paso del hijo—, y el
`update` del hijo se limita a rehacer sus vértices. Con eso el resultado no
depende de en qué orden dibuje el plan ni de cuántas veces se llame.

Como todo eso vive en `src/weparticles.c`, que enlazan los dos ejecutores,
`glexec.c` y `glexecutor.cpp` solo tienen que **parsear una línea y llamar a
`we_psys_seguir`**. Ni uno ni otro sabe qué es un hijo.

### Lo medido

Sonda directa sobre el par de la `City` —cargar los dos `.psys`, atarlos y
avanzar—: el hijo pasa de 0 partículas a **60–92 en régimen**, que es lo que
predice la cuenta (35 padres de vida 4–8 s son ~5,8 muertes/s, por 4 de ráfaga,
por 3 s de vida del hijo).

**10 escenas del corpus** tienen hijos `eventspawn`, con 17 sistemas entre
todas: las 10 renderizan, ninguna sale negra. `test_weparticles` y
`test_werender` pasan. `test_luminancia` no se mueve —6 escenas cambian ±0,2,
que es su ruido de repetición— y **eso no es evidencia**: mide a `t=4,0`, y con
padres de vida 4–8 s apenas ha muerto ninguno. Por eso se valida aparte.

### Lo que NO arregla

La distribución de manchas de la `City` sigue sin cuadrar con la captura de WE.
Con los hijos dibujando, las manchas redondas pasan de 23 a 74 —van en la
dirección buena— pero siguen cayendo en 5–8 px donde WE tiene su pico en 3–4, y
las grandes suben de 7 a 14 contra las 7 de WE. Los hijos aportan halos anchos y
suaves, no los núcleos pequeños y duros que se ven en la captura. El cabo del
diámetro sigue abierto; ver «Pendiente».

`eventfollow` (69 usos) y `static` (34) siguen sin implementar. `eventfollow`
necesita que el hijo siga a una partícula VIVA, o sea un vínculo por partícula y
no por muerte, que es otro estado.

**Esta sección leía `eventspawn` al revés.** Lo que describe —el hijo que
estalla donde muere el padre— es `eventdeath`, un cuarto tipo que el corpus no
usa; `eventspawn` estalla donde NACE. Y las 286 entradas sin `type` son
`static`. Ver [Los hijos de un
sistema](#los-hijos-de-un-sistema-cuatro-tipos-y-eventspawn-estaba-leído-al-revés).

## `distancemax` sin declarar no es cero: la lluvia salía toda del mismo punto

Las estrellas fugaces de la `City` entraban **todas por el mismo punto de
arriba** en vez de nacer repartidas y cruzar el fondo. La causa estaba a la
vista en el preset: el emisor de `Shooting_Star_01` es un `boxrandom` con
`origin: "-250 250 0"` y **sin `distancemax`**, así que la caja medía cero y
todas nacían en el mismo sitio.

Es el tercer campo de esta sesión con el mismo patrón —después de
[`rate`](#el-ritmo-implicito-estaba-en-el-extremo-y-se-comia-el-instanceoverride)
y del [`max` de `colorrandom`](#la-pista-estaba-en-un-campo-escrito-de-mas)—:
**lo que WE omite no vale cero, vale el defecto del editor.**

### Por qué 512

Dos pruebas independientes, las dos dentro del propio formato:

- **El corpus escribe `distancemax: 0` ciento cincuenta y tres veces.** Nadie
  escribe un campo 153 veces si es lo que sale por defecto. Igual que los 158
  `max` iguales al `min` de `colorrandom`.
- **`exampleturbolence.json`, que trae el propio WE, declara `distancemin: 256`
  y omite el máximo.** Con cero, el mínimo sería mayor que el máximo. Sea cual
  sea el defecto, tiene que ser **≥ 256**.

Y 512 es el valor más declarado del corpus —195 usos, por delante del 0— y el
que llevan `example.json`, `starfield`, `fog1`, `fog2`, `lightning1`,
`fireflies` y `powerup`, todos de WE. Toca a **6 presets-emisor en 7 escenas**.

### Lo medido, y lo que queda torcido

Aislando las fugaces de la `City` sobre su fondo:

| | píxeles de estela | ocupan |
|---|---|---|
| antes (caja de 0) | 1810 | x 404 px de ancho, y **desde el borde 0** |
| con 512 | 269 | x 573 px, y de 162 a 1086 |

O sea: dejan de pegarse al borde de arriba y nacen repartidas por una banda
diagonal que cruza el cuadro, que es el comportamiento que pide la captura.

**Lo que no cuadra todavía**, y conviene dejarlo escrito: salen pocas. La caja
local queda en ±512 x ±2560 —`directions: "1 5 0"` multiplica los semiejes— y
con la escala 3 del objeto eso es una banda de ±1536 x ±7680, cuando la escena
mide 3840x2160. Cerca del 75 % de las fugaces nace fuera del lienzo y no llega a
verse.

**Resuelto:** el defecto de `distancemax` es `256 256 0` y no 512, y el resto de fugaces fuera es lo que pide el preset; ver [Los valores por defecto estaban en el binario](#los-valores-por-defecto-estaban-en-el-binario-el-giro-la-caja-el-ritmo-y-el-sesgo).

Ese `1 5 0` es el **único `directions` mayor que 1 de todo el corpus** en un
emisor de caja: los otros 52 lo omiten (40), lo ponen a `1 1 1` (4) o lo usan
para APLANAR (`1 0.1 0`, `1 0 0`). Así que o el defecto de `distancemax` no es
el mismo para caja y esfera, o `directions` no multiplica los semiejes de una
caja como creemos. Las dos lecturas encajan con todo lo demás y una sola captura
no las separa; queda anotado antes que resuelto.

## La cola de una cinta sale de `length`, no de un 8 fijo

Las estrellas fugaces salían con la estela **corta y gorda** donde WE la enseña
fina y larga. El grosor era [el sprite al doble](#1-los-destellos-no-es-el-tamano-y-el-factor-05-esta-probado-y-descartado);
lo corto tenía culpable propio, y es el mismo patrón otra vez pero al revés: **un
defecto pisando un campo declarado.**

`_cinta` tomaba los puntos de la cola de `segments`, con un 8 por defecto, y
luego los acotaba con `min(32, puntos, length/paso)`. Ese `min` hacía que el 8
del campo AUSENTE ganara al `length` que el autor sí escribe: `Shooting_Star_01`
pide `length: 0.4` ---24 pasos a 60 Hz--- y se quedaba en 8, o sea 0,13 s de
cola en vez de 0,4.

No es un caso raro: **68 de las 74 cintas del corpus no declaran `segments`**, y
30 de ellas sí declaran `length` (0,2 / 0,4 / 0,5 / 0,6 / 3 / 30). El propio
`shootingstar.json` de WE es una de ellas: `length: 0.2`, sin `segments`.

Ahora, sin `segments`, la cola sale de `length`. La fugaz pasa de 8 a 24 puntos
y los píxeles de estela de 269 a 1146. Sobre las 129: **0 regresiones**, y solo
6 escenas mueven la luz, todas por debajo de 0,36 y hacia arriba.

## `gravity` es una aceleración, y lo demuestran los fuegos artificiales

Con la lluvia ya repartida y la cola larga quedaba una petición: que las fugaces
**no cayeran en parábola sino recto**. No se hace, y conviene dejar escrito por
qué, porque la tentación de tocar `movement` va a volver.

`fireworks1.json`, de WE, lanza sus partículas a `(±1000, 2500..3500)` con
`gravity: "0 -1000 0"`. Eso solo describe un fuego artificial si `gravity` es
una **aceleración**: como velocidad constante, la carga subiría para siempre a
2000 y no habría arco. Lo mismo dicen `dripping_water` ---gota que acelera--- y
los pares `rain_screen` / `rain_screen_4k`, que doblan la gravedad al doblar el
lienzo.

Y el propio preset lo confirma desde el otro lado: `Shooting_Star_01` declara
`gravity: "50 -50 0"`, que no es «hacia abajo» en ninguna parte… hasta que se
gira con los −45° del objeto, y entonces sale **vertical en el lienzo**. Es lo
que escribe un autor cuando la gravedad se aplica en coordenadas LOCALES y
quiere que se vea cayendo. O sea que aplicarla en local, como hacemos, es lo que
el valor del autor da por hecho.

Así que la parábola es lo que declaran el preset y el `shootingstar.json` del
propio WE. Enderezarla sería contradecir el formato.

**Lo que sí hace que la parábola CANTE** es la densidad. `shootingstar.json` de
WE declara `rate: 0.2` con `maxcount: 16`: 0,6 partículas vivas de media, o sea
una fugaz de vez en cuando. Nuestro [ritmo implícito](#el-ritmo-implicito-estaba-en-el-extremo-y-se-comia-el-instanceoverride)
le da 4,48/s al preset del autor, que son ~19 a la vez: veinte arcos
simultáneos se leen como una lluvia parabólica; uno se lee como una estrella
fugaz. La ocupación de la plantilla de WE es `0,2·3/16 = 0,037`, muy por debajo
del 0,48 que usamos. Es un cabo que este preset señala y que merece medirse
aparte.

## El personaje calvo: el rig tenía un bloque con nombres que nadie leía

`3462491575` (Arknights, dos personajes) salía con la cabeza de Kal'tsit
convertida en un manchón de piel: sin pelo, sin cara, sin orejas. No faltaba
ningún pase —`sin_shader: 0`, `sin_textura: 0`, 73 pases dibujados— y las
texturas del pelo estaban decodificadas y enlazadas. **El pelo se dibujaba, 826
px por debajo de la cabeza.**

Lo dice el propio `scene.json`: siete capas de esa escena declaran un campo que
no aparecía en ninguna parte del proyecto.

```
id= 1637 nombre='头发'  attachment='头发'  parent=1607 (身体)
id=  863 nombre='眼睛'  attachment='头发'  parent=1547 (身体)
id= 7426 nombre='右臂'  attachment='右臂'  parent=1547 (身体)
```

`attachment` significa que la capa **no cuelga del origen de su padre sino de
un punto con nombre del rig puppet del padre**, y que su `origin` es relativo a
ese punto. Sin resolverlo, `transform_absoluto` componía el `origin` a secas y
la capa caía donde cayera.

### Dónde estaba el nombre

En el esqueleto no. Los huesos del MDLS traen un campo de texto detrás de la
matriz, pero lo que hay ahí no es un nombre:

```json
{"a":null,"lamax":null,"lamin":null,"rax":null,"ray":null,"raz":null,
 "tm":100.0,"tp":"1017.82239 0.00000 0.00000"}
```

son los límites de la articulación. El nombre está en un bloque que
`parse_skeleton` ya se saltaba —su cabecera devuelve el desplazamiento del
siguiente y el recorrido pasa de largo— y que `parse_animations` cruzaba sin
mirar para llegar al MDLA:

```
char[]     "MDAT000N" terminado en nul
u32        desplazamiento ABSOLUTO del bloque siguiente
u16        numero de anclajes
por anclaje:
    u16        indice del hueso del que cuelga
    char[]     nombre, terminado en nul
    float[16]  matriz local respecto a ese hueso
```

El recuento es **u16 y no u32**: con u32 el primer anclaje empieza dos bytes
tarde y el nombre sale descuadrado. Lo confirman dos medidas que no salen del
propio bloque: el recorrido termina EXACTO en el desplazamiento que declara la
cabecera en los cuatro puppets del corpus que lo traen, y los nombres que salen
son los mismos que citan sus escenas —`头发`, `右臂`, `听诊器`—.

En las 129: **4 puppets de 85** traen MDAT, con 5 puntos de anclaje, y los
citan **16 capas de 4 escenas**. Ninguna cuelga de otra colgada, así que basta
un anclaje por objeto.

### Por qué no basta con hornearlo

El punto se calcula como un vértice más: es `attachment.matrix · G_hueso` en
reposo, y deformarlo es la misma cuenta que hace el skinning (`p · M`). La
tentación es hornearlo en la matriz del `object` y acabar, y para el fotograma
offline vale. **No vale en vivo, porque el hueso se mueve:**

| escena | anclaje | recorrido en la animación |
|---|---|---|
| 3462491575 | `头发` | 15 × 25 px |
| 3097749052 | `Attachment` | **158** × 14 px |
| 3238423642 | `Attachment1` | **151 × 285 px** |

Con 285 px de recorrido, hornear deja la capa despegada en cuanto arranca la
animación. El giro sí es despreciable —2,5° como mucho en todo el corpus—, así
que el seguimiento es **solo traslación**.

### El reparto

El plan lleva la posición ya horneada dentro de la matriz del `object` (con eso
el fotograma sale bien por sí solo) y una directiva que deja lo justo para
rehacerla:

```
anclaje <malla> <hueso> <px> <py> <bx> <by> <e00> <e01> <e10> <e11>
```

`(px,py)` es el punto en reposo, `(bx,by)` dónde cayó al hornear, y la 2×2
lleva el desplazamiento a clip space con la escala y el giro de los ancestros
ya dentro. El ejecutor skinnea el punto en el instante que toca, resta la base
y lo suma a la traslación de la colocación. Offline los dos instantes son el
mismo y **no suma nada**, que es la propiedad que hace el cambio seguro: el
camino que ya funcionaba no se mueve.

La fase y la interpolación las elige `mesh_clave` / `meshKey`, la misma función
que usa el skinning de la malla. Si cada uno eligiera su clave, la capa colgada
se separaría de la malla justo al interpolar.

Medido de punta a punta: con el plan horneado en t=0 y `meshtime 15` —el
instante de máximo recorrido— el ejecutor mueve el pelo −15/−25 px, contra los
−15,16/−25,07 que predice el hueso.

## `step(0.5, nodeNum)`: la norma lo admite y NVIDIA no

La misma escena perdía 5 pases más, y esto es un fallo distinto y de otro
tipo. El shader del taller `auto_sway.vert` escribe, tal cual lo dejó su autor:

```glsl
void preCalcNode(in int nodeNum, ...)
    prevMotionRadian *= step(0.5, nodeNum);
```

En HLSL el `int` promociona solo. En GLSL 330 la conversión también está en la
norma y **Mesa la acepta**; el compilador de NVIDIA la corta:

```
0(833) : error C1101: ambiguous overloaded function reference "step(float, int)"
    (0) : ps gp5 ... lowp float step(lowp float, lowp float)
    (0) : ps gp5 ... mediump float step(mediump float, mediump float)
```

Le estorban sus propias sobrecargas con calificador de precisión. Es justo la
trampa de la regla 5: este equipo es híbrido —el escritorio va por Intel/Mesa y
el render offline por NVIDIA—, así que el fallo **solo se veía offline** y
podría haberse leído como un fallo de la escena.

`literales_de_llamada` ya hacía esta promoción, pero solo sobre **literales
enteros pelados**; aquí el argumento es una variable. Se amplía a cualquier
argumento cuyo tipo AFIRME el parser que es entero, con dos cautelas:

- la tabla de tipos es aparte de la que usa la truncación (`tipos_por_nombre`),
  para que ninguna decisión que ya funciona se mueva;
- e incluye los **parámetros de función** —donde vive `nodeNum`— dejando fuera
  los nombres que cambian de tipo entre ámbitos: quien lee esto envuelve la
  expresión en un constructor, y hacerlo con el tipo del otro ámbito no
  compila.

`_FUNC_RE` no valía para leer los parámetros porque exige la llave en la misma
línea, y las tres funciones largas de `auto_sway` la traen en la siguiente. Se
usa un patrón propio en vez de ampliar el suyo: de `_FUNC_RE` cuelgan
`tabla_de_funciones` y `tabla_de_parametros`, y darle por conocido el tipo de
retorno de funciones que hoy no lo están movería truncaciones en todo el
corpus.

Sobre las 129: **582/582 variantes compilan y 291/291 enlazan en los dos
drivers**, y la inferencia sigue con 0 incorrectas.

## Un puntero donde hacía falta una lista: el hijo `eventspawn` congelado

`we_psys_seguir` colgaba el hijo del padre con `padre->hijo = hijo`. Con dos
hijos el segundo **pisaba** al primero, y el primero no se quedaba
simplemente sin padre: se quedaba en el peor sitio posible. Su `padre` seguía
apuntando al de antes, así que su propio `we_psys_update` salía por
`construye(s)` sin dar un paso —esa es justo la señal de «no doy pasos por mi
cuenta»— y ya no lo apuntaba nadie que se los diera. Y `_emit_psys` le había
puesto el ritmo de emisión a cero, porque quien lo emite es el evento. Capa
vacía para siempre.

Lo delata `Flare_(Parent).json` de `2937370591`, la única del corpus con dos
hijos sobre el mismo padre; su plan sale con las dos líneas:

```
psyspadre 2 1 500
psyspadre 3 1 500
```

Ahora `hijo` es la cabeza de una lista y cada hijo apunta al siguiente por
`hermano`. Se añade por la cola para que estallen en el orden en que el plan
los declara. Las muertes del padre se vacían **cuando ya las han visto todos**,
no dentro del bucle: si no, el primero se las llevaría y el segundo no
estallaría nunca. Y el paso es recursivo, porque un hijo puede tener hijos
suyos y el `update` de un sistema con padre no da pasos por su cuenta —sería el
mismo congelamiento por otro camino—; `we_psys_seguir` rechaza los ciclos, así
que termina.

**Por qué no lo cazó la regresión de luz.** El hijo aporta 3.034 píxeles sobre
un lienzo de 2 Mpx y la escena es clara: la media pasa de 200,971 a 200,982.
Once milésimas. La prueba de luz separa «negra» de «viva», y esto no apaga
nada, solo borra un destello. En el corpus son 10 escenas con hijos
`eventspawn` y **una sola** con más de uno, así que el camino de un hijo
—idéntico bit a bit al de antes— cubría a las otras nueve.

## Los destellos de la `City`: qué se mueve, y por qué no se toca nada

La petición era concreta: que los destellos de la `City` (`2821288001`) se
movieran «más suave y reducido». Lo primero fue medir **qué** se mueve ahí,
porque a ojo es un cielo entero temblando y no se distingue una causa de otra.
Diferencia de dos fotogramas separados 0,5 s: cientos de puntos que parpadean y
cinco trazos que cruzan. Desglosado por sistema:

| lo que se mueve | cuántos | cómo |
|---|---|---|
| `Star_01`, `Star_04`, `Star_05` | ~900 | **no se desplazan**: `oscillatealpha` los lleva de alfa 0,2 a 1,0 con periodo 2,1 s |
| `Star_02`, `Star_06` | 170 | `turbulence` 100–170 con máscara `0.5 0.5 0`; medido con `psysprobe`, 52–65 px/s de media y picos de 320 |
| `Shooting_Star_01` | ~20 a la vez | 100–250 px/s; su emisor **no declara `rate`** y el ritmo implícito le da 4,48/s |

### Los dos candidatos a fallo, y por qué ninguno lo era

Esta es la parte que se queda, porque son dos lecturas del formato zanjadas con
medida y no hay que volver a plantearlas.

**`turbulence` como aceleración.** Es sospechoso que el operador acumule
velocidad (`vel += c·speed·dt`) mientras el inicializador `turbulentvelocityrandom`
usa los MISMOS `speedmin`/`speedmax` sobre el MISMO campo de ruido para fijarla
(`vel += c·speed`): dos unidades para el mismo par de campos. Y en el corpus
**60 de las 86 turbulencias no llevan rozamiento**, así que la velocidad hace un
paseo aleatorio en vez de estabilizarse. Pero las dos plantillas de la propia
WE ---`exampleturbolence.json` y `exampleturbolence3d.json`--- acompañan su
`turbulence` de un `movement` con `drag: 4`, que es justo lo que hace falta para
que una aceleración tenga velocidad terminal (1000/4 = 250 px/s). Si fuera una
velocidad, ese rozamiento sobraría en las dos. **Se queda como está.**

**El ritmo implícito.** Era el candidato bueno ---es el cabo abierto de «`gravity`
es una aceleración»--- y tampoco: de los **42 emisores del corpus sin `rate`**,
33 son `dust_motes_0` (18) y `ember_small` (15), plantillas de WE para polvo y
brasas, que piden el depósito lleno y no vacío. Bajar la ocupación global para
calmar una escena apagaría esas. El 0,48 de hoy es la mediana de los 486
emisores que sí lo declaran y sigue siendo la mejor estimación que hay.

O sea: **City es así de movida por diseño**, y por la regla 1 no se toca por su
id. No hay nada que arreglar aquí.

### Lo que se probó y se retiró: frenar el reloj de la simulación

Queda escrito porque está medido y porque la vía es la única sensata si algún
día se pide: **un factor sobre el reloj de las partículas**, no sobre sus
números. Escalar velocidades obliga a decidir qué pasa con las aceleraciones
---la gravedad va con el cuadrado del tiempo, así que un factor plano deforma
la parábola---; escalar la emisión cambia la densidad que eligió el autor. El
reloj no: con `k = 0,5` se llega al mismo estado en el doble de tiempo y, como
la vida también se escala, hay **las mismas partículas a la vez**. Un `.psys`
calmado y uno normal serían el mismo fichero, porque lo único que cambia es el
instante que se le pasa a `we_psys_update`.

Medido antes de retirarlo, con pares de fotogramas separados 1/30 s **en los
mismos instantes de simulación** y sumando la luz que cambia fuera de los
píxeles que anima el shader: **x1,00 / x0,55 / x0,26** para `k` 1, 0,5 y 0,25.
Y `k = 0,5` en `t = 40` daba el mismo fotograma que `k = 1` en `t = 20`, con la
única diferencia de los píxeles del reloj de la escena, que da la hora de
verdad. La trampa de método, por si se repite: comparar los mismos instantes de
PANTALLA en vez de los de SIMULACIÓN sale sin orden ---0,25 se movía más que
0,5--- porque con el reloj frenado la escena sigue llenando los depósitos, y un
sistema que nace es mucho más cambio por fotograma que uno en régimen.

**Nada de esto está en el árbol.** Se implementó como una línea `ritmoparticulas
<k>` en el plan, con los dos ejecutores multiplicando por ella, y se retiró
entera a petición del usuario junto con el `wectl calma` que la exponía: la
escena no tiene ningún fallo que arreglar y el mando no se había pedido. De ahí
salió la [regla 8](#regla-de-trabajo-wectl-no-crece-por-iniciativa-propia).

## La turbulencia, a la mitad: una desviación pedida, no un arreglo

Sobre la escena de arriba se pidió que **los destellos que derivan aceleraran
menos**. Antes de tocar nada había que descartar que estuviéramos leyendo mal el
campo, porque el síntoma es idéntico en los dos casos.

**No lo estábamos.** `turbulence` acumula velocidad ---`vel += rotacional(ruido)
· speed · máscara · dt`---, así que `speedmin`/`speedmax` son una **aceleración
en px/s²**, y la pregunta es si el campo que los multiplica está normalizado: si
no lo estuviera, el número del autor no sería la magnitud que dice ser sino esa
magnitud por un factor que no declara nadie. Medido sobre **1,28 M de muestras**
del propio `rotacional`, muestreado como lo muestrea la simulación (`scale`
0,0005 y el tiempo por `timescale`):

| | RMS | máximo |
|---|---|---|
| \|rotacional\| en 3D | 1,217 | 2,681 |
| \|rotacional\| en el plano XY, que es lo que deja la máscara | **0,980** | 2,454 |

O sea que el campo ya viene normalizado en el plano donde actúa, y con la
máscara `0.5 0.5 0` de esta escena la aceleración RMS es exactamente
`speed · 0,5` = 50–85 px/s². Y cuadra con lo que se mide en la simulación: la
rapidez media en régimen era 62,7 px/s, que es el mismo número, porque el campo
se renueva cada segundo ---celda temporal de 1 s--- y la partícula no llega a
acumular más de un empujón.

Así que no había nada que corregir: **el cambio es una preferencia**, y se hace
donde se pueda revertir con un solo número.

### `FACTOR_TURBULENCIA = 0.5`

Multiplica `speedmin`/`speedmax` al escribir el `.psys`. Tres decisiones:

- **Solo el operador**, no `turbulentvelocityrandom`. El inicializador fija la
  velocidad de salida de los chorros de humo y su coherencia está calibrada
  aparte —ver [La turbulencia no
  turbulaba](#la-turbulencia-no-turbulaba)—; meterle mano de paso habría
  cambiado el penacho de Sniper Girl sin que nadie lo pidiera.
- **En `weparticles.py` y no en el `.c`**, por lo mismo que `ESCALA_RUIDO`:
  convertir las unidades del formato es interpretar, que es trabajo de Python, y
  además así el cambio viaja en el plan en vez de esperar a que plasmashell
  suelte la `.so` que tiene mapeada.
- **Un solo número y con el motivo escrito al lado.** Esto es una divergencia
  deliberada del valor del autor: quien lo lea dentro de un año tiene que poder
  distinguirla de un fallo, y volver al original es poner 1.0.

Alcance: **86 operadores en 48 escenas** de las 129.

### Lo medido, antes y después

Siguiendo cada partícula por vecino más próximo durante 90 s ---los vértices
vienen compactados, así que el índice no identifica a la partícula--- y contando
solo vidas completas en régimen:

| sistema | | rapidez media | camino en su vida | desplazamiento neto |
|---|---|---|---|---|
| `Star_02` | antes | 62,7 px/s | 376 px | 311 px |
| | después | **31,4 px/s** | **188 px** | **154 px** |
| `Star_06` | antes | 60,7 px/s | 364 px | 296 px |
| | después | 30,4 px/s | 182 px | 148 px |
| `Star_03` | antes | 45,5 px/s | 271 px | 226 px |
| | después | 22,8 px/s | 136 px | 113 px |

Escala limpia con el factor, que es lo que se pedía comprobar: la vida medida no
se mueve (5,98 s contra los 5,99 de antes, con `lifetimerandom 5 7`), así que lo
único que cambia es cuánto se desplazan.

Lo que **no** cambia: el número de partículas, su tamaño, su parpadeo, ni el
carácter del campo ---mismas celdas de 2000 px y de 1 s, o sea que siguen
derivando en grupo y girando cada segundo---. Solo van más despacio.

## El ratón entra en la escena: un puntero, cuatro consumidores

Hasta aquí el puntero era una constante. `g_PointerPosition` se emitía en
`0.5 0.5` con un comentario que decía «hasta que el motor sepa dónde está el
ratón de verdad», y los operadores de partícula que tiran de un punto de
control atado al cursor se **descartaban** en Python, porque sin ratón ese
punto se queda en el origen del sistema y el operador deja de ser una
interacción para convertirse en un sumidero: con `scale -500` y `drag 2.5` la
nube de 512 px de radio se apelotona en una bola de 64.

Lo que había que decidir era **por dónde entra** un dato que cambia cada
fotograma y que el plan —que es una foto— no puede llevar horneado.

### Quién lo mira, contado antes de escribir nada

| consumidor | cuánto | dónde |
|---|---|---|
| puntos de control atados al cursor (`flags & 1`) | **123 sistemas en 46 escenas** | `controlpointattract`, 111 de sus 136 usos |
| `cameraparallax` de la escena | 29 escenas | mueve la **cámara**, no está hecho |
| efecto `depthparallax` (`g_ParallaxPosition`) | 6 usos en 6 escenas | |
| efecto `cursorripple` (`g_PointerPosition` + `Last`) | 6 usos en 1 escena | |
| efecto `xray` (`g_PointerPosition`) | 1 uso | |

Las partículas son el consumidor grande —46 escenas de 129— y por eso son las
que deciden el diseño. Los tres efectos son 13 pases en 8 escenas.

### El puntero viaja como el tiempo: un marcador en la plantilla

El plan ya tenía exactamente este problema resuelto para el reloj: el cuerpo
lleva `@TIME@` y lo sustituye quien dibuja —Python offline, el ejecutor en
vivo—. El puntero usa la misma puerta, con tres pares de marcadores:

```
u2f g_PointerPosition     @PUNTERO_X@ @PUNTERO_Y@
u2f g_PointerPositionLast @PUNTERO_ANT_X@ @PUNTERO_ANT_Y@
u2f g_ParallaxPosition    @PARALLAX_X@ @PARALLAX_Y@
```

Y dos directivas nuevas en la cabecera:

```
parallax <retardo>                    segundos que tarda el parallax en llegar
psyspuntero <id> <7 floats>           afín: pantalla -> espacio de ESE sistema
```

`psyspuntero` es el reparto de siempre. Las partículas viven en píxeles de su
sistema y el ratón llega en coordenadas de pantalla; quien sabe dónde cae el
sistema en el lienzo es Python, así que resuelve la afín —la inversa de
`particle_world`, aplanada a `x = a·u + b·v + c`— y los dos ejecutores solo
multiplican. Se emite únicamente para los 123 sistemas que la necesitan.

**Sin ratón no es ratón en el centro.** Son dos estados distintos y confundirlos
cuesta el efecto: con el puntero clavado en el centro, las luciérnagas de 46
escenas se apelotonan ahí desde el primer fotograma. Así que `we_psys_puntero`
acepta `NULL` —«ahora mismo no hay»— y con él los operadores del cursor no
actúan, que es exactamente lo que se veía antes de este cambio. Offline es el
estado por defecto y `--puntero <u> <v>` es lo que lo enciende.

### De dónde sale el ratón en el escritorio

Un `MouseArea` con `hoverEnabled` habría recibido el hover **y los clics**, y
un fondo que se queda los clics del escritorio no es un fondo. `HoverHandler`
solo mira: no acepta botones, no es `blocking`, y el menú contextual, la
selección con recuadro y los iconos siguen funcionando igual.

Lo que da y lo que no: mientras el ratón está sobre una ventana, el fondo **no
recibe nada**. No es una carencia de la implementación sino de la posición: en
Wayland un cliente solo ve el puntero cuando está encima de él. La respuesta
es quedarse con la última posición conocida —no inventarse un movimiento que
no ha ocurrido, que en el efecto de ondulación sería un latigazo por la
pantalla— y decir que ya no hay ratón para los puntos de control. Wallpaper
Engine, en Windows, lee el cursor global y sigue el ratón por debajo de las
ventanas; esto es lo más parecido que se puede saber desde aquí.

### La pantalla no es la escena

El item ocupa la pantalla entera pero la escena casi nunca: 99 de las 129
escenas son 16:9 y el encaje `Cubrir` recorta lo que sobra. Así que el píxel
bajo el ratón **no** es el píxel de escena que hay debajo, y convertir uno en
otro es el mismo cálculo del blit final del revés. Estaba escrito dentro de
`render()`, mezclado con el blit; se ha sacado a `encajado()` para poder
hacerlo al principio del fotograma, que es cuando el puntero hace falta. Con
el cálculo duplicado, un encaje con recorte movía la escena y no el ratón.

### La `y` del uniform, que es donde estaba la trampa

`g_PointerPosition` va en coordenadas de **pantalla con la y hacia abajo**, y
no hay que voltearla. La duda es legítima porque los shaders de WE hacen la
suya: `cursorripple` y `xray` escriben `pointer.y = 1.0 - pointer.y` con el
comentario *«flip pointer screen space Y to match texture space Y»*, y
`depthparallax` no voltea el puntero sino la coordenada de textura,
`vec2(v_TexCoord.z, 1.0 - v_TexCoord.w)`. Los dos dicen lo mismo: el espacio
del puntero es el contrario al de textura.

Y cuál es el nuestro ya estaba decidido y escrito, en el preámbulo que
`weshader.py` le pone a cada shader: **compilamos la rama `GLSL`**, y es la de
`HLSL` la que invierte la Y de las texturas. Con la rama GLSL, la `v` crece
hacia arriba y `1 - v` es la pantalla con la y hacia abajo, que es justo lo que
Qt entrega. Sin flip.

Lo que **no** se ha podido comprobar contra una imagen: los efectos que lo
leen no dejan rastro medible offline. `cursorripple` es una simulación de
fluido que arranca de `length(g_PointerPosition - g_PointerPositionLast)`, o
sea del **movimiento**, y offline el puntero está quieto por definición; se
forzó a mano una diferencia de 0,2 en el plan de `3299228616` y sus 264 pases
dieron 0 píxeles de cambio, así que su cadena necesita algo más que un
fotograma. El `xray` de `3237641967` tampoco cambia nada visible: su halo se
multiplica por el alfa de la textura de mezcla. Lo que sí está medido es el
camino de las partículas, que no pasa por ninguna coordenada de textura.

### Lo que sí se midió

`psysprobe` acepta ahora la posición del ratón, y con ella la nube se va donde
se le dice. Sobre `1779280331`, la escena con más sistemas atraídos del corpus
(16), poniendo el puntero en `0.2 0.25` de la pantalla:

| | centro de la nube, en su sistema | de vuelta a pantalla |
|---|---|---|
| `s000` | (539, −199) | u=0,223 v=0,278 |
| `s001` | (−514, 201) | u=0,243 v=0,257 |
| `s002` | (−434, 133) | u=0,225 v=0,266 |

Cada sistema tiene su propio origen, su escala y su giro —el primero está
rotado 180°, por eso su `a` es negativa— y los tres acaban en el mismo sitio de
la pantalla, que es lo que había que comprobar. La ida y vuelta contra
`particle_world` es exacta en los 16.

Y en la imagen, que es lo que decide. `2078213130` —cuatro sistemas atraídos,
ni una capa de reloj que ensucie la comparación— renderizada con el puntero en
`0.2 0.75` y sin puntero: los 7921 píxeles que se **encienden** caen centrados
en `u=0,238 v=0,735`. La luz media no se mueve (70,19 contra 70,21): las mismas
partículas, en otro sitio.

En vivo, con el arnés QML moviendo el puntero por su cuenta (no hay ratón que
mover en una prueba automática), la traza dice lo mismo fotograma a fotograma:
`vista(0.100,0.150) -> escena(0.100,0.150) -> sistema(24.9,529.8)`.

Y dentro de plasmashell, que es la única pregunta que el arnés no contesta —si
los eventos de hover llegan al fondo o se los queda alguien por el camino—, el
aviso de una sola línea que se emite la primera vez que el ratón pisa el
escritorio:

```
SceneView: ... particulas 16 sistemas / 0 piezas sin soporte / 16 siguen al raton
GlExecutor: el raton entra en el fondo por (0.196, 0.961)
```

Con `Halo Infinite Hologram Explosion` puesto, que son 16 sistemas de 16. El
`HoverHandler` recibe sin quitarle nada al escritorio.

Y el contrato Python↔C tiene su prueba en `test_weparticles.py`: un sistema con
la marca puesta, simulado 10 s, con el puntero en (400, −300) y sin él.

```
  sin puntero  centro (-7, 14)     a 514 px del destino
  con puntero  centro (412, -309)  a 15 px del destino
```

Son las dos averías posibles a la vez: que la marca no viaje en la línea `cp`,
y que el simulador no la mire. Las dos se ven igual en un PNG —una nube más
pequeña de lo que debería— y ninguna falla sola.

### Lo que la regresión dice: 0 regresiones y una reordenación honesta

Las 129, antes y después, con el puntero apagado —que es el estado por defecto
offline—: **0 apagadas, 0 regresiones, 0 que no renderizan**, y la única
sospechosa es la misma de siempre (`3459506773`, al 0,37 de su preview).

Once escenas dan un número distinto, y ninguna se mueve más de 0,25 sobre 255.
Las once tienen una capa de texto, o sea un reloj, y las dos pasadas se
tomaron con seis minutos de diferencia; eso explica las cuatro que no tienen
ni un sistema de partículas atado al cursor. Pero no explica `2078213130`, que
tiene cuatro sistemas de cursor y ni una capa de texto, así que se midió
aparte:

| | luz media | píxeles que cambian más de 4/255 |
|---|---|---|
| dos renders del código nuevo | idénticos | 0 |
| nuevo contra anterior | 70,245 contra 70,243 | 10591 de 2 073 600 |

La causa es conocida y no es un fallo: el operador del cursor ahora **ocupa un
puesto** en la lista de operadores del sistema, y las fases aleatorias por
partícula se derivan del ÍNDICE del operador —`azar_fijo(semilla, j * 4)`—, así
que los que van detrás de él vuelven a sortear su fase. Misma nube, mismos
números, otro reparto de fases. Es el precio de que el operador exista en el
fichero aunque no actúe, y la alternativa —no escribirlo cuando no hay ratón—
no vale: si hay ratón o no es cosa del fotograma, no del plan.

### `g_ParallaxPosition` es el puntero con retardo, y nada más

Es un uniform distinto de `g_PointerPosition` y la diferencia es el retardo:
`cameraparallaxdelay`, que 108 de las 129 escenas dejan en 0,1 s y que **cuatro
de las seis** que usan el efecto de profundidad suben a 2 s. Un parallax que va
pegado al ratón no es el que esos autores pidieron, así que el suavizado es
exponencial —`1 - exp(-dt/retardo)`, para que el tiempo de llegada no dependa
del refresco— y vive solo en el ejecutor en vivo: offline no hay trayectoria
que suavizar.

Lo que **no** lleva es `cameraparallaxamount` ni `cameraparallaxmouseinfluence`,
y el corpus es quien lo dice: dos de las seis escenas con `depthparallax`
declaran `cameraparallaxamount: 0`. Si el amount escalara este uniform, esas
dos habrían puesto un efecto marcado como *expensive* sobre una entrada muerta.
El efecto ya trae sus propios mandos —`g_Scale`, `g_Sensitivity`, `g_Center`—:
la fuerza es cosa suya, no de la cámara.

**Corregido después**, leyendo el motor: no es el puntero con retardo sino el
punto P de la cámara partido por el lienzo, y sí lleva
`cameraparallaxmouseinfluence` —lo que no lleva es el amount—. Las dos escenas
de amount 0 son justo las de influencia negativa. Ver [`g_ParallaxPosition` es
el punto P de la
cámara](#g_parallaxposition-es-el-punto-p-de-la-cámara-no-el-puntero-con-retardo).

### Lo que queda, medido

- **La cámara**. `cameraparallax` está en 29 escenas de 129 y mueve cada capa
  según su `parallaxDepth` (1459 objetos en 116 escenas lo declaran). No se ha
  hecho porque falta el número que convierte «amount 0,5» en píxeles, y ese no
  sale ni del formato ni de los shaders: sale de comparar con WE corriendo.
  Escribirlo a ojo movería 29 escenas en una dirección que nadie ha medido.
  **Hecho después**, leyendo la fórmula en el motor; ver [El parallax de
  cámara](#el-parallax-de-cámara-la-fórmula-estaba-en-el-motor-y-mueve-las-capas-también-en-reposo).
- **El emisor que nace en el cursor**: 25 emisores del corpus llevan
  `flags: 2` y 23 de ellos están en sistemas que ya tienen un punto atado al
  cursor. Apunta a «emite donde el ratón» —el preset `trail_1` de WE es una
  estela que sale del puntero, con `distancemax: 0` y ese flag—, pero en 14 de
  los 25 el punto del cursor es el 1 y no el 0, así que «emite en el punto 0»
  no lo explica. Sin una lectura que cubra los 25 no se toca.
  **Leído después en el motor**: `flags: 2` no coloca nada —es una partícula
  por fotograma—, y lo que lleva la estela al cursor es que **todo** emisor
  emite en su punto de control. Sigue sin hacerse; ver [`flags: 2` no coloca
  el
  emisor](#flags-2-no-coloca-el-emisor-es-una-partícula-por-fotograma-y-al-cursor-lo-lleva-el-punto-de-control).
- **El puntero por debajo de las ventanas**, que en Wayland pide otra fuente
  distinta de los eventos del propio fondo.

## El fondo de *Lonely Cat* se desliza, y las dos mitades de un arreglo

**Síntoma, tal como se ve:** en `3299228616` (*Lonely Cat*) el fondo entero
resbala hacia arriba sin parar y hay una banda dura en el 18 % superior con un
trozo de la parte de abajo. De paso, las olas y el gato dejan de cuadrar: lo
que se dibuja **antes** de cierta capa se desliza y lo que se dibuja **después**
—estrellas, luciérnagas— se queda quieto.

No tiene nada que ver con el puntero: el desplazamiento sale de `g_Time` y
llevaba ahí desde siempre.

### El oráculo: el preview del autor no se mueve

`preview.gif` son 38 fotogramas de 40 ms renderizados por Wallpaper Engine.
Correlación de fase contra el primero: **(0, 0) en los 38**. El nuestro, medido
igual sobre seis renders a 0,15 s de distancia:

| t | 8,00 | 8,15 | 8,30 | 8,45 | 8,60 | 8,75 |
|---|---|---|---|---|---|---|
| desplazamiento (px de 360) | 0 | −1 | −2 | −3 | −5 | −6 |

Unos 2,2 % de la altura por segundo. En una pantalla de 1200 px son 27 px/s, y
eso es lo que se ve moverse.

### Quién lo mueve

Volcando el compuesto pase a pase y correlacionando cada volcado entre los dos
instantes, el desplazamiento aparece **de golpe en un único pase**: el 25, con
`|dif|` de 11,96 cuando ninguno de los anteriores pasa de 4.

Ese pase es el efecto `scroll` (`speedy 0.15`) de la capa **`Bar 3`**, que es un
***composelayer***: una capa que no dibuja nada propio, solo coge el fotograma
ya compuesto (`_rt_FullFrameBuffer`) para que sus efectos lo transformen. Sus
dos efectos:

| efecto | visible | |
|---|---|---|
| `Simple_Audio_Bars` | `barstyle == 3` | **apagado**: el valor por defecto es 1 |
| `scroll` | siempre | encendido |

Sin el efecto de barras, lo que queda es *coge todo el fondo, despláza­lo y
píntalo encima*. El `frac()` del shader envuelve el desplazamiento, y ahí está
la banda.

Quitando del plan el bloque de esa capa, la escena cuadra con el preview:
desplazamiento (−2, +8) sobre 256 px, que es la propia animación del agua.

### La causa: la identidad que le damos a una capa passthrough

`_colocacion` trata las capas *passthrough* poniéndoles origen en el centro y
tamaño de lienzo, así que su colocación sale **identidad**. Para
`fullscreenlayer` y `projectlayer` es correcto —su shader ni mira la MVP— pero
`composelayer.vert` **sí la mira**, y para lo más importante:

```glsl
v_ScreenCoord = mul(vec4(a_Position, 1.0), g_ModelViewProjectionMatrix).xyw;
...
gl_Position = vec4(a_TexCoord * 2.0 - 1.0, 0.0, 1.0);   // el quad, pantalla entera
```
```glsl
vec2 texCoord = v_ScreenCoord.xy / v_ScreenCoord.z * 0.5 + 0.5;
gl_FragColor = texSample2D(g_Texture0, texCoord);       // el fondo, por la MVP
```

O sea: el quad es la pantalla entera, pero **lo que muestrea sale de la MVP**.
Con la identidad copia el fotograma ENTERO en vez del trozo que hay bajo su
rectángulo, y encima se compone sobre todo el lienzo en vez de dentro de él.

### Por qué el arreglo son dos mitades y ninguna vale sola

Probado parcheando el plan a mano, sobre esta escena:

| variante | resultado |
|---|---|
| como está hoy | el fondo entero desplazado, con la banda |
| **solo** componer en el rectángulo | el fotograma entero **encogido dentro del rectangulito** |
| MVP real en el pase base **+** componer en el rectángulo | **cuadra con el preview** |

La segunda fila es exactamente el síntoma que dejó escrito [La capa
`passthrough` se componía en su rectángulo del
editor](#la-capa-passthrough-se-componía-en-su-rectángulo-del-editor) y por el
que se puso la identidad:
se probó componer en el rectángulo sin arreglar la otra mitad, y con el buffer
lleno del fotograma entero no podía salir otra cosa. Las dos juntas se explican
solas: coge el trozo bajo el rectángulo, agrándalo al buffer, aplica los
efectos, devuélvelo al rectángulo. Sin efectos es la identidad, que es justo
por lo que una capa así es invisible cuando no la usa nadie.

### Alcance, medido sobre las 129

| capas passthrough visibles | 85 en 41 escenas |
|---|---|
| con shader `composelayer` | 45 |
| con shader `passthrough` | 40 |
| **con rectángulo distinto del lienzo** | **29** |
| de ellas, `composelayer` | 27, en 18 escenas |
| de ellas, `passthrough` | 2, en 2 escenas |

Las otras 56 son del tamaño del lienzo: para ellas el rectángulo **es** la
identidad y el arreglo no las tocaría. (Aquella sección contaba 32 en 21
escenas; era la biblioteca anterior, la de 125.) Las dos de shader `passthrough` hay que
mirarlas aparte, porque ese shader no usa la MVP para muestrear y componerlo en
su rectángulo le encogería el contenido.

**Arreglado el 2026-08-31.** `_colocacion` ya no fuerza identidad para un
`composelayer` con rectángulo propio ---sigue forzándola para `passthrough`,
que no mira la MVP--- y el pase BASE de un `composelayer` deja de emitir
`g_ModelViewProjectionMatrix` a identidad: lleva la MVP real
(`object_mvp`), la misma con la que se compone después. Las dos mitades caen
solas de ahí, porque pasan a ser el mismo cálculo que ya usa cualquier otra
capa; no hizo falta tocar `layer_size` ---el buffer de trabajo del objeto es
del tamaño del lienzo en los dos ejecutores, `compo[]`/`m_compo[]`, y eso no
cambia--- ni el shader.

Medido sobre las 129 con `test_luminancia`: 129/129 renderizan, 0 apagadas, 0
regresiones (umbral del 25%), la misma sospechosa de siempre
(`3459506773`). 13 escenas mueven su luminancia media más de 0,05; en las
otras 12 la razón contra el preview se queda igual o mejora. La única que se
mueve de verdad es `3521337568`, de 0,795 a 0,668 ---empeora el número, pero
es la mitad de la historia: antes un `composelayer earth composition` con
efectos `fisheye`+`blend`+`tint` llenaba el lienzo entero con un planeta
ovalado del tamaño de la pantalla; con el arreglo es un cuarto creciente
pequeño arriba a la izquierda, que es lo que enseña el preview del autor. La
razón cae porque la imagen correcta es más oscura, no porque este peor.
`3299228616` (Lonely Cat) no mueve su luminancia media en absoluto ---el agua
sigue teniendo el mismo brillo medio--- pero la correlación de fase entre dos
fotogramas a 0,75 s ya no tiene el desplazamiento (−36 px) de antes: sale
(0, 0), como el preview.

## Los hijos de un sistema: cuatro tipos, y `eventspawn` estaba leído al revés

Hasta aquí solo se dibujaba un tipo de hijo, `eventspawn`, y se leía como «el
hijo estalla donde muere cada partícula del padre». Los otros dos tipos que
aparecían en el corpus —`eventfollow` y `static`— se quedaban fuera, y las
entradas sin `type` se contaban aparte como si fueran otra cosa.

### El oráculo: lo que la propia aplicación dice y trae

Esta vez no hizo falta deducir el formato de los valores. La interfaz de WE
(`locale/ui_en-us.json`) nombra **cuatro** tipos —`Event follow`, `Event
spawn`, `Event death` y el estático— y el editor de partículas enlaza su
documentación (`docs.wallpaperengine.io/en/scene/particles/component/children`),
que dice de cada uno:

| tipo | documentación de WE |
|---|---|
| `static` | «se crea una vez en el origen del sistema» |
| `eventfollow` | «se crea varias veces y sigue a partículas individuales» |
| `eventspawn` | «se crea **a la vez que nacen** las partículas de este sistema» |
| `eventdeath` | «se crea cuando una partícula llega al final de su vida» |

Y de los campos de la entrada: `maxcount` es «el número máximo de sistemas
hijos», solo relevante en los de evento; `probability` la de que el evento lo
cree; `origin`, `angles` y `scale` la colocación del hijo.

O sea: **lo que estaba implementado como `eventspawn` era `eventdeath`**. Los
presets de WE lo confirman sin ambigüedad: `fireworks1` y `fireworks2` cuelgan
su estallido con `eventdeath` —la carga sube y revienta al apagarse— y
`spark.json` sus chispas con `eventspawn`. En el corpus no hay ni un
`eventdeath`; en los presets de WE, 25.

### Sin `type` es `static`

286 entradas del corpus no declaran tipo. Son `static`, y lo dicen dos cosas:

- `ember.json`, de WE, cuelga `emberglow` sin tipo; y los presets que el editor
  guardó con **todos** los campos escritos (`thunderbolt`, `snowstorm`) dicen
  `type: "static"` junto con el resto de valores por defecto —`maxcount: 10`,
  `probability: 1.0`, `angles: "0 0 0"`—. Es el mismo patrón de siempre: el
  campo que falta vale el defecto del editor.
- En el corpus pasa lo mismo con el mismo par: `ember` → `emberglow` va sin
  tipo en unas escenas y con `static` y todos los defectos en `3462491575`.

Así que `static` no eran 34 entradas en 1 escena sino **320 en 51**, y
`maxcount` sin declarar vale 10.

### Qué es cada uno, en el motor

- **`static`** es un sistema independiente con su propio emisor —los 320
  declaran `rate`, ninguno `instantaneous`—. No hay nada que atar en el
  simulador: basta con colocarlo. Se coloca con el mecanismo de los grupos de
  la escena: el objeto hijo declara `parent` y su `origin` y `scale` son los
  de la entrada, relativos al padre. Así hereda también lo que mueva al padre.
- **`eventspawn` / `eventdeath`**: cada nacimiento o muerte del padre crea una
  instancia del hijo, que suelta su `instantaneous` ahí mismo. Las 8 entradas
  del corpus que no lo declaran —seis con `rate`, dos sin nada— siguen
  soltando su `maxcount` entero, que es lo que hacían antes: qué hace en WE una
  instancia con `rate` clavada en un punto —¿emite para siempre?— no se sabe.
- **`eventfollow`**: cada partícula del padre que nace se lleva una instancia
  si queda alguna libre (`maxcount` de la entrada a la vez); la instancia
  suelta su `instantaneous` al empezar y luego emite a su `rate` **donde esté
  la partícula**, hasta que muere.

Lo que emite un `eventfollow` **no se queda pegado** a la partícula: nace en
su sitio y desde ahí va por su cuenta. Es una lectura y no un hecho, y la dan
los nombres de los presets de WE que lo usan —`firefliestrail`,
`poweruptrails`—: con las partículas pegadas no habría estela, habría un
enjambre viajando con la luciérnaga.

En los tres de evento el depósito es el `maxcount` del preset por el número de
instancias, y el `rate` es el **declarado**: el implícito
([el ritmo implícito](#el-ritmo-implicito-estaba-en-el-extremo-y-se-comia-el-instanceoverride))
es una estimación para un sistema que emite solo, y aquí es el de cada
instancia.

### El reparto

Igual que con el primer hijo: `wescene._hijos` devuelve cada hijo como un
objeto hermano, `werender` le arma su `.psys` y su pase, y la línea del plan
crece con lo que el simulador necesita saber:

```
psyspadre <hijo> <padre> <rafaga> <modo> <instancias> <probabilidad> <ex> <ey> <ez>
```

`modo` es 0 muerte, 1 nacimiento, 2 seguir. La escala de la entrada va al
final porque el hijo se dibuja con ella encima de la del padre: la posición
del evento, que llega en el espacio del padre, se divide por ella para caer en
su sitio. Una línea de tres campos —un plan anterior— sigue valiendo y es la
de la muerte, que es lo que significaba.

En `src/weparticles.c`, todas las partículas nacen ahora por un único sitio,
`nace()`, que es quien anota los nacimientos para los hijos. Por eso un hijo
de nacimiento ve los de su padre vengan de donde vengan: del emisor, del
estallido del arranque, o de un evento de SU padre. Esto último hace falta: 165
entradas `static` del *spawner* de Matrix —una partícula que cae por columna—
cuelgan cada una una estela `eventfollow`, o sea nietos (y una más, de lluvia).

Un hijo atado no emite nunca por su cuenta: lo decide el simulador
(`!s->padre`), no el `rate` a cero que antes ponía Python, porque ahora ese
`rate` hace falta para seguir.

### Lo que se deja fuera, a propósito

- **`angles` de la entrada.** Hay uno distinto de cero en el corpus
  (`0 0 -50`, en un `eventfollow`) y no se sabe en qué unidad está: el resto
  del formato guarda radianes, y −50 rad tiene poca pinta de ser lo que el
  autor tecleó.
- **`controlpointstartindex`** («el punto de control del hijo que se
  sobrescribe con las posiciones del padre») y **`flags`** de la entrada. El
  primero aparece una vez en el corpus (en un `eventfollow`, con 2) y el
  segundo nunca con un valor distinto de 0; en los presets de WE los dos los
  usa el rayo `thunderbolt`. Sin un caso en el corpus no hay con qué medirlos.
- **`inheritvaluefromevent`** e **`inheritinitialvaluefromevent`**, las piezas
  que copian color, velocidad o tamaño de la partícula del padre: cero usos en
  el corpus.
- El `instanceoverride` del padre se copia al hijo, como ya se hacía: el autor
  ajusta el sistema como un todo, y escalar las brasas sin escalar su halo los
  descuadraría. También es una lectura.

### Lo medido

En el corpus, con las capas invisibles fuera: **182 hijos `static` en 51
escenas**, **76 `eventfollow` en 19** —34 de ellos nietos— y los mismos 17
`eventspawn` en 9 escenas de antes. Unos 275 en 60 escenas.

**La prueba de contrato** (`test_weparticles.py`, «los hijos de evento»): un
padre de partículas que se alejan a 60 px/s y un hijo de emisor puntual con
0,2 s de vida.

```
  eventfollow  escala 1    padre 8  hijo 16   a 5.0 px de su particula
  eventfollow  escala 2.5  padre 8  hijo 16   a 5.0 px de su particula
  eventspawn   a los 3 s: 3 particulas
  eventdeath   a los 3 s: 0, a los 9 s: 3
```

Y se comprobó que la prueba muerde: con la escala de la entrada sin aplicar en
el simulador, la estela con escala 2,5 queda a **460 px** de su partícula y la
prueba falla.

**Sobre una escena real**, las luciérnagas de `2078213130`: 12 vivas y 79
partículas de estela a 14,7 px de media de la más cercana, ninguna a más de
100.

**`test_luminancia` sobre las 129**, contra una referencia sacada de `main` con
el mismo driver: 129/129 renderizan, **0 apagadas, 0 regresiones**, y las
mismas sospechosas que antes. 16 escenas mueven su media más de 0,25; 14 suben,
que es lo esperable al aparecer partículas que no se dibujaban, y ninguna pasa
de +3,2 (`2710814362`). En `1120440003` lo que aparece es el halo cálido de
`emberglow` dentro de la ciudad, que es lo que enseña su preview. En la `City`
(`2821288001`), la escena donde se estudió `eventspawn`, la media no se mueve
(83,09 contra 83,10).

**`test_wescene`**: 582/582 variantes compilan y 291/291 pares enlazan, en Mesa
y en NVIDIA. Son las mismas cifras de antes: los hijos usan `genericparticle`
con combinaciones que el corpus ya pedía.

Esto último **no dice** que los destellos de la `City` estén ahora bien: sus
hijos pasan de estallar al morir la estrella a hacerlo al nacer, y el cabo del
diámetro de los destellos ([Lo que NO arregla](#lo-que-no-arregla)) sigue
abierto. Lo que sí dice es que el arreglo no apaga ni ensucia nada.

## Los valores por defecto estaban en el binario: el giro, la caja, el ritmo y el sesgo

Cuatro cabos abiertos de las partículas —el sentido del sesgo de `exponent`,
la hoja de sprites del rayo «girada 90°», el 75 % de las estrellas fugaces que
nacía fuera del lienzo y la densidad de esas mismas fugaces— se revisaron
juntos. Uno lo cerró la documentación de WE; los otros tres, **el código del
propio motor**.

### El sesgo de `exponent`: confirmado, no se toca nada

La documentación de los inicializadores
(`docs.wallpaperengine.io/en/scene/particles/component/initializer`) lo dice
igual en los seis: «un valor de `1` es el equilibrio entre **Max** y **Min**;
hacia `0` sesga hacia **Max**, y de `2` en adelante hacia **Min**». Es
exactamente `mezcla(min, max, pow(t, e))`, que es lo que se eligió por
inferencia en [Lo que NO se pudo confirmar](#lo-que-no-se-pudo-confirmar). Y
ningún `exponent` del corpus baja de 1, así que no hay caso dudoso.

### Dónde guarda WE sus valores por defecto, y cómo se leen

Los binarios —el motor, `wallpaper64.exe`, y el editor,
`bin/wallpaperui.exe`— tienen los defectos de los campos de partícula
**escritos como texto** (`256 256 0`, `0 0 6.28318530717`…) en la misma zona de
la tabla de cadenas que los nombres de campo. La proximidad sola solo da
candidatos, porque el orden no casa uno a uno. Lo que da certeza es mirar
**qué código usa cada cadena**:

```sh
objdump -h wallpaper64.exe                      # .rdata, para pasar de cadena a dirección
objdump -d --no-show-raw-insn -M intel wallpaper64.exe > we.asm
```

Cada cadena de valor por defecto se usa **una sola vez** en todo el motor, y
siempre con el mismo patrón: el lector de una pieza carga el nombre del campo,
pregunta al JSON si está y, si no, inserta el valor. Por ejemplo, en el lector
del emisor:

```
lea  rax, "256 256 0"
lea  rdx, "distancemax"
call ...                 ; lee el campo, con ese valor si falta
```

Y a qué pieza pertenece cada lector lo dice la fábrica: compara el `name` del
JSON con cada nombre de pieza y llama a su lector justo después. Así quedan
atadas, sin deducir nada:

| pieza | campo | defecto de WE | aquí antes |
|---|---|---|---|
| `sphererandom`, `boxrandom` | `rate` | **10** (los bits `0x4024000000000000`) | ritmo implícito |
| ídem | `distancemax` | **`256 256 0`** | 512 |
| ídem | `directions` | **`1 1 0`** | `1 1 1` |
| ídem | `distancemin` | `0 0 0` | igual |
| `rotationrandom` | `max` | **`0 0 6.28318530717`** | `0 0 0` |
| `angularvelocityrandom` | `min` / `max` | **`0 0 -5` / `0 0 5`** | `0 0 0` |
| `velocityrandom` | `min` / `max` | `-32 -32 0` / `32 32 0` | `0 0 0`, pero el corpus siempre los declara |

Lo cuadran además las escenas de muestra que WE trae para cada pieza
(`assets/scenes/particleelementpreviews/`): las de `rotationrandom` y
`angularvelocityrandom` llevan la pieza **vacía**, que solo enseña algo si su
defecto no es cero.

### La «hoja girada» del rayo era un giro, y afecta a 66 escenas

`lightning1` lleva un `rotationrandom` sin `min` ni `max`. Leído como cero,
todos los rayos salían horizontales; el 451x129 nuestro contra el 92x251 de WE
que dejó apuntado [El tamaño del
sprite](#el-tamaño-del-sprite-el-brillo-explicaba-una-parte-no-toda) no era una
hoja leída al revés sino un rayo que en WE estaba girado y aquí no. Son **112
`rotationrandom` vacíos en 66 escenas**; los 39 que solo declaran `max` siguen
igual. Y 18 `angularvelocityrandom` vacíos en 15 escenas, que ahora giran.

### La caja es `256 256 0`, y el 40 % que sigue fuera es del preset

[`distancemax` sin declarar no es
cero](#distancemax-sin-declarar-no-es-cero-la-lluvia-salía-toda-del-mismo-punto)
fijó 512 por ser el valor más declarado del corpus. El motor dice `256 256 0`,
que cumple con lo justo la cota que aquella sección dejó (≥ 256, por
`exampleturbolence`).

Con la colocación real de las fugaces de la `City` —origen, giro de −45°,
escala 3 y su `directions: "1 5 0"`— y su movimiento, simulado:

| caja | nacen dentro del lienzo | llegan a cruzarlo |
|---|---|---|
| 512 | 12,6 % | **27,7 %** |
| 256 | 28,9 % | **59,5 %** |

El 40 % que sigue sin cruzarlo no es una lectura equivocada. `directions`
multiplica los semiejes —lo dice la documentación del emisor— y `distancemax`
**es** el semieje: la muestra de `rain_splashes` escala su objeto solo en x, a
0,275 sobre un lienzo de 256, que con 512 de semieje da ±141 px —el ancho del
lienzo con un 10 % de margen—; con 512 de tamaño total cubriría la mitad
central, y nadie elegiría esa escala. Así que es lo que pide el preset: una
banda de unos 7.700 px en una escena de 3.840.

### El ritmo: 10 por segundo, no el 48 % del depósito

Ni la documentación, ni los presets, ni las 49 escenas de muestra omiten `rate`
una sola vez; el motor sí lo dice: 10. Eso sustituye al [ritmo
implícito](#el-ritmo-implicito-estaba-en-el-extremo-y-se-comia-el-instanceoverride),
que deducía el ritmo de `maxcount` y la vida para sostener el 48 % del
depósito. Son 68 sistemas en 35 escenas, y con 10 por segundo las partículas
vivas a la vez suben en 42 y bajan en 13:

| preset | vivas antes | vivas con 10/s |
|---|---|---|
| `Shooting_Star_01` (`City`) | ~20 | 35, el depósito lleno |
| `ember_small` (28 sistemas) | ~19 | 40 |
| `dust_motes_0` (29 sistemas) | ~123 | ~130 |
| `new_particle_systemmn_nm` | ~544 | ~115 |

En la `City` esto da **más** fugaces, no menos, al revés de lo que perseguía el
ritmo implícito («una captura de WE enseña menos de diez»). Esa captura no se
guardó y se midió con la caja a cero; contra el código del motor, manda el
código. De paso deja de recibir ritmo el único sistema que declaraba `rate: 0`
con un estallido `instantaneous`: el implícito no distinguía «sin declarar» de
«cero».

### `directions` es `1 1 0`

Sin declarar, el motor crea `1 1 0`. Solo cambia la z de las partículas, que el
dibujo aplana, pero la z entra en el campo de ruido de la turbulencia.

### Lo medido

Las cinco, una a una sobre las 129 con `test_luminancia`, cada pasada contra la
anterior y la primera contra `main`:

| pasada | regresiones | escenas que mueven su media > 0,25 |
|---|---|---|
| giro por defecto | 0 | 4 (3 se acercan a su preview) |
| caja de 256 | 0 | 0 |
| velocidad angular ±5 | 0 | 1 |
| ritmo 10 | 0 | 1 (se acerca) |
| `directions` `1 1 0` | 0 | 1 |
| **las cinco contra `main`** | **0** | 3 (2 se acercan; ninguna más de 0,6) |

La que se mueve sola en tres pasadas, `3097749052`, sube o baja 1,2–1,8 con
cambios que no tienen que ver entre sí: es un sistema grande que cambia de
sorteo, no un efecto; contra `main` queda en +0,57 y más cerca de su preview.

La luminancia media apenas ve nada de esto, y es lo esperable: los cinco
redistribuyen partículas. Lo que se ve es la imagen de la `City` en cuatro
instantes: en `main` los rayos salen siempre horizontales y casi ninguna fugaz
cruza el recorte; con los cambios los rayos salen girados —uno casi vertical,
como el de la captura de WE— y las fugaces cruzan la escena en diagonal. El
cambio de ritmo, en cambio, no se distingue a ojo en las escenas de brasas,
polvo y fugaces a tamaño de pantalla: lo respalda el código del motor, no la
imagen.

## El parallax de cámara: la fórmula estaba en el motor, y mueve las capas también en reposo

`cameraparallax` estaba apuntado como lo que faltaba del ratón, con un bloqueo
escrito en [Lo que queda, medido](#lo-que-queda-medido): «falta el número que
convierte `amount 0,5` en píxeles, y ese no sale ni del formato ni de los
shaders: sale de comparar con WE corriendo». Salió de una tercera parte: del
código del motor, leído igual que [los valores por defecto de las
partículas](#los-valores-por-defecto-estaban-en-el-binario-el-giro-la-caja-el-ritmo-y-el-sesgo).

### Cómo se encontró

El lector de `general` registra cada campo en una tabla de propiedades con su
desplazamiento dentro de la estructura de ajustes de la escena:
`cameraparallaxamount` en `+0x334`, `cameraparallaxdelay` en `+0x338`,
`cameraparallaxmouseinfluence` en `+0x33c`. El constructor pone `+0x334` y
`+0x33c` a 0,5, que son los defectos del corpus. Con los desplazamientos, las
lecturas: dos funciones de la escena (`0x140189…`, `0x14018b…`). Y los campos
de la capa salen de su propia tabla: `origin` en `+0x128`, `scale` en `+0x134`,
`angles` en `+0x140`, `parallaxDepth` en `+0x170`.

### Lo que hace WE

Cada fotograma calcula un punto P del lienzo, en píxeles y con la y hacia
arriba:

```
objetivo.x = ancho × (0,5·(1 − m) + ratón.x·m)
objetivo.y = alto  × (0,5·(1 − m) + (1 − ratón.y)·m)        m = mouseinfluence
P ← P + (objetivo − P) × min(1, (1 − delay/3) × 10 × dt)
```

y, antes de dibujar cada objeto, le aplica a su matriz una traslación previa
en el lienzo —sin filtro por tipo: imágenes, texto y partículas—:

```
amount × parallaxDepth_raíz × (origin_raíz − P)
```

con el `origin` y la profundidad del antepasado **raíz** (el código sube por
`parent` hasta él), así que un grupo se mueve entero.

Hay otra lectura de los mismos campos con un filtro de tipos y una tabla hash;
tiene toda la pinta de ser la detección del objeto bajo el cursor, no el
dibujo, y no se ha usado.

### La sorpresa: con el ratón en el centro, las capas ya están desplazadas

Con el ratón en el centro P es el centro del lienzo, pero `origin − P` no es
cero para una capa fuera del centro: se aleja de él en proporción a su
distancia y a su profundidad. El parallax de WE no solo mueve la escena con el
ratón; también **abre la composición en reposo**, y es lo que el autor ve en el
editor (`camerapreview`, encendido en 126 de 128 escenas).

Comprobado contra el preview de `2262142032` antes de escribir una línea, en un
recorte situado a mano:

| capa | predicción | en el preview de WE |
|---|---|---|
| el reloj | −98, +17 px | ≈ −106, +30 px |
| el letrero «RU» | fuera del cuadro | no está |

### Cómo está hecho aquí

El desplazamiento se parte en dos términos:

- `a·d·(origin − C)`, con C el centro: el de reposo. Es fijo, así que lo hornea
  `parallax_de_camara` en `werender.py` como `_paralaje` de cada raíz, y lo
  suma `transform_absoluto` al `origin` de la raíz. De ahí cuelga todo —las
  matrices, las partículas, el puntero de cada sistema, los anclajes— sin
  tocar nada más, y sale igual offline que en vivo.
- `a·d·(C − P)`: el del ratón. No depende del `origin`, solo de `a·d`, que el
  plan lleva en una línea nueva tras cada `object`:

```
parallax <retardo> <influencia>      cabecera; la influencia es nueva
paralaje <a·dx> <a·dy>               tras el `object` de cada capa con profundidad
```

  Los dos ejecutores la suman a la colocación del objeto, como ya hacía el
  `anclaje`: en clip son `2·k·(0,5 − P/lienzo)`. Offline P sale del `--puntero`,
  sin suavizar; sin puntero es el centro y no suma nada. En vivo lleva el
  suavizado de WE, que con el retardo de 2 s de cuatro escenas llega siete
  veces antes que la exponencial que había.

En las imágenes la colocación lleva la capa entera y no hay recorte. En
partículas y texto la colocación es la identidad y lo que se traslada es su
buffer, del tamaño del lienzo: en el borde se pierde lo que haya fuera, como
mucho unos 240 px a 1920 con el ratón en una esquina.

### Lo medido

- **`test_luminancia` sobre las 129**, contra la de `main`: 0 apagadas, 0
  regresiones. Siete escenas mueven su media más de 0,25; la mayor,
  `2250845956`, baja 2,25.
- **Correlación con el preview** en las 29 escenas con el parallax encendido,
  buscando el recorte del preview a varias escalas: 4 se acercan más de 0,01
  —`2250845956` +0,067, la misma que bajaba de luz; `3462491575` +0,042,
  `3097749052` +0,034, `3082427731` +0,011—, 2 se alejan —`2810252468` −0,025,
  que es su texto de créditos, apagado en el preview, cayendo sobre la
  nebulosa; `2317494988` −0,021, sin decidir a ojo— y 23 no cambian: capas
  centradas o sin profundidad. Es una medida ruidosa —un texto con otra hora
  ya la baja— y sirve de apoyo, no de juez.
- **`test_werender`**: `prueba_parallax_de_camara`, que falla si el
  desplazamiento en reposo no se aplica.
- **Offline con `--puntero`**, en `2262142032`: con el ratón a la izquierda la
  escena va a la derecha y al revés.

### Lo que queda

- ~~**`g_ParallaxPosition`**. Lo más probable es que WE suba el P normalizado de
  arriba —con la influencia y la y hacia arriba—, y aquí se sube el ratón con
  retardo y la y hacia abajo. El nombre del uniform es el `0x6b` de su tabla,
  pero el `switch` que lo sube va por tabla de saltos y no se ha encontrado. No
  se toca sin eso: lo usan 6 escenas con `depthparallax`.~~ **Hecho**: era eso,
  y con `cameraparallax` apagado se queda en el centro; ver
  [`g_ParallaxPosition` es el punto P de la
  cámara](#g_parallaxposition-es-el-punto-p-de-la-cámara-no-el-puntero-con-retardo).
- **`escena[+0xf0/+0xf4]`**, un término que WE suma al objetivo y que aquí se
  toma como cero; y una marca de la escena que invierte la x.
- ~~**`camerashake`**, 6 escenas~~ **hecho**: [El temblor de
  cámara](#el-temblor-de-cámara-también-estaba-en-el-motor-y-no-es-ruido). Y
  `escena[+0xf0/+0xf4]` resultó ser el ojo de la cámara: ahora lleva el
  temblor. El `eye` que algunas escenas declaran fuera del origen no llega:
  [WE lo pone a
  cero](#el-eye-de-la-cámara-no-llega-al-parallax-we-lo-pone-a-cero-en-las-escenas-ortográficas).

## `upright` en una cinta: WE la orienta como a un sprite, y da la base de siempre

Quedaba en [Lo siguiente](#lo-siguiente) un `rope` con `orientation: upright`
—*Vapor 1*, el objeto 445 de `2870014907`, con `subdivision: 2`— apuntado como
lo único de `orientation` que no se dibujaba bien, con este argumento: «la
anchura de la cinta la monta nuestro constructor de vértices, perpendicular al
camino». **Era falso.** `construye_cinta` (`src/weparticles.c`) solo pasa
extremos y puntos de control; la anchura la calcula el vértice de WE,
`genericropeparticle.vert`, en la ruta sin geometry shader que usamos:

```glsl
vec3 eyeDirection = mul(g_OrientationForward, CAST3X3(g_ModelMatrixInverse));
vec3 trailRightStart = cross(eyeDirection, trailDelta + CPStart);
```

Así que la pregunta era la de cualquier sprite: qué `g_Orientation*` pone el
motor con `upright`. Se leyó en `wallpaper64.exe` con el método de [los valores
por defecto](#dónde-guarda-we-sus-valores-por-defecto-y-cómo-se-leen).

### El lector: tres modos y una base

`orientation` (`.rdata 0x14048fb70`) solo lo usa una función, `0x1401c22e0`, y
la llaman las cuatro fábricas de renderer —`sprite` en `0x1401cc5f5`,
`spritetrail` en `0x1401cfe61`, `rope` en `0x1401cff73`, `ropetrail` en
`0x1401d00ff`—, cada una justo después de reservar su bloque (tipo 1 a 4 en el
primer byte; la carga útil empieza en `+4`). Lo que guarda en la carga útil:

| campo | dónde | qué |
|---|---|---|
| modo | `+0x08` | `upright` → 1 (`0x1401c262b`), `fixed` → 2 (`0x1401c2682`), cualquier otro → 0; el defecto es la cadena `screen` (`0x14048fb64`), y `camera` no se compara: cae en 0 |
| `axis` | `+0x0c` | normalizado; si es nulo o falta, **(0, 1, 0)** (`0x1401c277f`) |
| derecha, arriba | `+0x18`, `+0x24` | una base ortonormal a partir de `axis` |
| `flags` | `+0x30` | un byte |

El modo además pasa al material de la cinta como combo `ORIENTATION`
(`0x1401d2b55`), pero solo lo lee `genericropeparticle.geom`, el geometry
shader, que no usamos.

### La rutina que pone los tres uniforms, igual para los cuatro renderers

El bucle de dibujo del sistema (`0x1402368ef`) recorre los bloques y, sea cual
sea el tipo, llama a `0x1402298b0(contexto, carga útil)` antes de dibujar. Esa
función escribe tres vectores en el contexto: `+0x184` (`forward`), `+0x190`
(`right`) y `+0x19c` (`up`) —el orden de los ids `0x1d`, `0x1e`, `0x1f` que la
tabla de uniforms da a `g_OrientationForward`, `Right` y `Up`, y el `fixed`
copia `axis` a `+0x184`—. Con `c` la dirección de la vista (`contexto+0x160`;
`+0x16c` y `+0x178` son la derecha y el arriba de la vista, que
`0x140256899` invierte y restaura) y `M` la matriz del objeto:

- **modo 0** (`0x140229c35`): `forward = −c`; `up` = eje Y del objeto (`M` por
  (0, 1, 0)) si `flags & 1` es 0, o el arriba de la vista si es 1; y `up` se
  ortogonaliza contra `forward`.
- **modo 1, `upright`** (`0x140229ab8`): `up` = `axis` llevado por `M` si
  `flags & 1` es 0, o (0, 1, 0) del mundo si es 1 (`0x140229b39`); luego
  `right = c × up` y `forward = right × up`.
- **modo 2, `fixed`** (`0x140229a87`): `forward` y `up` salen de la carga útil.

Y al final (`0x140229d55`), para los tres: los dos vectores se llevan al espacio
del objeto, `right = up × forward`, y **los tres se normalizan**.

### Por qué en el corpus no cambia nada

`(c × u) × u = u·(c·u) − c·|u|²`. Si `u` es perpendicular a la vista, eso es
`−c` escalado: el `forward` de `upright` es el de `screen`, y tras normalizar la
base es la misma, la canónica que el plan ya emite (`forward` 0 0 1, `right` 1 0
0, `up` en Y). Solo se tuerce si el `up` efectivo tiene componente a lo largo de
la vista.

*Vapor 1* no tiene `flags` ni `axis`: su `up` es el eje Y del objeto, y el
objeto solo gira en Z (`angles 0 0 1.47345`). La cámara de la escena mira de
`eye 0 0 0` a `center 0 0 −1` con `up 0 1 0`. Perpendicular: **sin efecto**.
Los otros tres `upright` del corpus, los sprites de `Rain_Splash` en
`2464842912`, llevan `flags: 1`, y su `up` es el del mundo: también.

Tampoco hay diferencia entre `rope` y `ropetrail` aquí: los dos pasan por la
misma `0x1402298b0`.

### Lo hecho

`_orientacion` (`tools/weparticles.py`) deja de tratar la cinta como excepción
y aplica la regla leída a los cuatro renderers: `upright` solo avisa si el `up`
efectivo tiene z —sin `flags & 1` y con un `axis` con z—, y `fixed` si el eje no
es Z. El `cinta` solo cambia el nombre del aviso. No se toca ni el plan ni los
ejecutores.

Una salvedad que el corpus no ejercita: la regla mira `axis` y `flags`, no el
giro del objeto. Un objeto girado en x o en y llevaría el `up` fuera del plano
aunque `axis` no tuviera z; en el corpus los cuatro `upright` cuelgan de objetos
que solo giran en z (`angles 0 0 0` los de `Rain_Splash`, `0 −0 1.47345` el de
*Vapor 1*).

### Lo medido

Todo desde la raíz del repositorio, con la rama base (`Bucle_Autonomo`)
extraída aparte con `git archive HEAD tools | tar -x -C /tmp/cu/base_src`.

- **El censo de `orientation` y los avisos**, sobre cada renderer de los
  sistemas de las 129 escenas (`/tmp/cu/censo.py <raíz>`):

  ```python
  import sys; sys.path.insert(0, sys.argv[1] + '/tools')
  from collections import Counter; import wepaths, weparticles as w; from wescene import AssetResolver
  n, av = Counter(), Counter()
  for d in sorted(d for d in wepaths.we_workshop().iterdir() if (d / 'scene.pkg').is_file()):
      r = AssetResolver.for_wallpaper(d, wepaths.we_assets())
      for o in r.read_json('scene.json').get('objects', []):
          for e in (r.read_json(o['particle']).get('renderer') or []) if o.get('particle') else []:
              n[e.get('orientation')] += 1; a = w._orientacion(e, e.get('name') in ('rope', 'ropetrail')); av[a] += bool(a)
  print(dict(n), {k: v for k, v in av.items() if k})
  ```

  Da **771 renderers sin campo, 38 `screen`, 4 `upright` y 1 `fixed`** en las
  dos ramas —las cifras del docstring de `_orientacion`, que antes decía 722 sin
  campo, la cuenta de la biblioteca anterior—. Avisos: en la base, 1
  (`estela upright`, `2870014907`); ahora, **0**. Los tres `upright` de
  `Rain_Splash_copy2.json` en `2464842912` (`flags: 1`, `axis 0 0 1`) eran el
  control: no avisaban antes y no avisan ahora.
- **Planes y `.psys` de las 129, byte a byte.** Cada escena se emite con
  `werender.py <escena> --emit-plan /tmp/cu/out/<id>` —la MISMA ruta en las dos
  ramas, porque el plan nombra sus assets por ruta absoluta—, se hace
  `sha256sum` de `plan.txt` y de cada `.psys`, y se borra el directorio. Ocho
  escenas en paralelo con `xargs -P 8` y `timeout 900` por escena: unos 50 s
  la pasada. Resultado: **129 de 129 escenas emitidas en las dos ramas, ninguna
  falla ni se agota; 1131 de 1131 ficheros idénticos** (129 `plan.txt` y 1002
  `.psys`). El sistema de *Vapor 1* tampoco cambia: la marca de soporte parcial
  vive solo en `sin_soporte`, en Python, y no llega ni al `.psys` ni al plan.
  Una segunda pasada de la base da los mismos 1131 sha256, así que la
  comparación no tiene ruido.
- **`2870014907` renderizada** con `--time 2 --frames 120` y Mesa
  (`__EGL_VENDOR_LIBRARY_FILENAMES=…/50_mesa.json`): el PNG es idéntico con
  `cmp` entre base y rama. Lo único que cambia en la salida es la cuenta
  `psys_parcial`, de 1 a 0.
- **`test_luminancia.py obj/glexec --referencia`** contra la referencia del
  bucle (`luz-a7f291acc0fe.json`): 129/129 renderizadas, **0 regresiones**, 0
  apagadas.
- **`test_weparticles`**: la prueba nueva, `prueba_orientacion`, son 14 casos
  de la regla, cada uno como sprite y como cinta, y además el recorrido del
  corpus falla si un renderer vuelve a dar aviso de orientación. Con el
  `_orientacion` de la base fallan 9 casos y el aviso de *Vapor 1*: 10
  discrepancias, código 1.

## El temblor de cámara: también estaba en el motor, y no es ruido

Quedaba al final de [El parallax de
cámara](#el-parallax-de-cámara-la-fórmula-estaba-en-el-motor-y-mueve-las-capas-también-en-reposo):
`general.camerashake`, con `camerashakeamplitude`, `camerashakespeed` y
`camerashakeroughness`, no se leía. Nueve escenas lo declaran y seis lo
encienden una vez resuelta la propiedad de usuario —`1692307745`,
`2930166418` y `3146507587` con `true` literal; `2970694180`, `3053927686` y
`3238423642` con `{user, value: true}`—; esas seis se dibujaban con la cámara
quieta. Las otras tres —`1518454472`, `2311315748` y `2968771936`, esta con un
`script` en el campo— lo tienen en `false` por su propiedad.

### Cómo se encontró

Con el método de [Dónde guarda WE sus valores por
defecto](#dónde-guarda-we-sus-valores-por-defecto-y-cómo-se-leen), sobre
`wallpaper64.exe`:

- **Los campos.** Las cadenas están en `.rdata` (`camerashake` en
  `0x14048e918`, `camerashakespeed` en `0x14048e900`, `…amplitude` en
  `0x14048e998`, `…roughness` en `0x14048e980`). El lector de `general` las
  registra en `0x14019ae14..0x14019b05d`, justo antes de `cameraparallax*`:
  `camerashakespeed` en **`+0x328`**, `camerashakeamplitude` en **`+0x32c`** y
  `camerashakeroughness` en **`+0x330`**, los tres float. `camerashake` es de
  los de accesor propio (`0x14019c620`, `0x14019c830`): el **bit 7 de
  `+0xe0`**.
- **Los defectos**, en el constructor de la escena (`0x140186c90`):
  `0x140186f84..0x140186f9a` ponen velocidad **3**, amplitud **0,5** y
  rugosidad **1**. El corpus los declara siempre.
- **Quién los lee.** Una sola función lee los tres: **`0x140199580`**. La
  llaman los tres caminos de la actualización de la cámara, `0x1401891a0`
  (`0x140189420`, `0x14018949f`, `0x140189a6f`), los tres detrás de un `jns`
  sobre el byte bajo de `+0xe0`, que es el bit 7. Recibe el **ojo** (`+0xf0`)
  y el **centro** (`+0xfc`) de la cámara y les suma el mismo vector: mueve la
  cámara entera, no cada capa, y no mira `parallaxDepth`.
- **El reloj** es `[[escena+0xd8]+0x130]`. Al construir la escena se le pasa
  `renderizador+0x10` (`0x140181b82`), así que es `renderizador+0x140`: el
  float del doble `+0x148`, que suma el dt de cada fotograma (`0x14017fcca`),
  se pone a 0 al cargar la escena (`0x140181b2a`) y vuelve a 0 a los 432000 s.
  Los segundos de la escena.
- **La proyección.** El bit 3 de `+0xe0` es `orthogonalprojection`
  (`0x1401875df`), y `+0x354`/`+0x358` son su ancho y su alto
  (`0x14018759e`, `0x1401875c0`).
- **Las funciones de la CRT**: `0x14041a2e0` es `cosf` (cerca de 0 devuelve
  la constante 1), `0x14041a9c0` es `sinf` (devuelve x) y `0x14041e350`,
  `powf`. Las constantes: 3,0 en `0x140492830`, 0,1 en `0x140492654`, 1,333 en
  `0x140492728`, 0,001 en `0x140492608` y 1,0 en `0x140492704`.

### Lo que hace WE

```
s = velocidad² · t                         t: segundos de escena
v = (cos s, sin 1,333·s, sin s)
ortográfica: v.z = 0 y k = 0,1·amplitud · 0,1·alto     (alto: +0x358)
si no:                 k = 0,1·amplitud                (unidades de mundo)
r = rugosidad³;  si r > 0,001 y r ≠ 1:  v = v/|v| · |v|^r
ojo += k·v;  centro += k·v
```

Tres cosas que no se habrían adivinado midiendo:

- **No es ruido.** Es una curva de Lissajous determinista, sin semilla: lo que
  da WE en el segundo t es lo que da aquí en el segundo t. El riesgo de no poder
  igualar el generador no existe.
- **La «rugosidad» no añade aspereza.** Solo deforma la norma: con r³ entre
  0,001 y 1 la acerca a 1, y con 0 o con 1 no toca nada. Cinco de las seis
  escenas usan 0 o 1; solo `3238423642` la nota, con 0,92.
- **En t = 0 la cámara ya está movida** `k` hacia la derecha (cos 0 = 1). Con
  la amplitud mayor del corpus, 0,5 sobre un lienzo de 2160, son 10,8 px; |v|
  llega a √2, unos 15 px.

Y una cuarta que cierra un cabo de la sección anterior: la `escena[+0xf0]` que
WE suma al objetivo del parallax (`0x140189c18`) **es el ojo de la cámara**.
Con el temblor el ojo se mueve, así que el punto P del parallax se corre lo
mismo que la cámara.

### Cómo está hecho aquí

- `temblor_de_camara` (`werender.py`) resuelve `camerashake` como `visible`
  —manda la propiedad del usuario, no la copia— y escala la amplitud con el
  alto del lienzo, que es el de `orthogonalprojection`. Sin
  `orthogonalprojection` no se emite: no hay cámara en perspectiva en este
  motor y en el corpus no hay ninguna escena así que tiemble.
- El plan lleva dos líneas nuevas, solo en las escenas que tiemblan:

```
temblor <ax> <ay> <velocidad> <rugosidad>   cabecera; k/ancho y k/alto
tiembla                                     tras el `object` de cada capa
```

- La curva vive una vez, en **`src/wetemblor.c`**, y la enlazan los dos
  ejecutores. `glexec.c` la evalúa en el instante del plan (`meshtime`);
  `glexecutor.cpp`, con su reloj, cada fotograma, antes que el puntero. Los dos
  restan el resultado de la colocación de cada capa con `tiembla`, y lo suman
  al punto P de las que llevan `paralaje`: offline también sin ratón, y en
  vivo dentro del objetivo, antes del suavizado, que es donde lo suma WE.
- **Las `passthrough` no tiemblan.** Las que no son `composelayer` no miran la
  MVP: leen y escriben el fotograma entero, que ya viene movido. Las
  `composelayer` leen lo que tienen debajo con la MVP horneada en el plan, que
  no tiembla. Con `tiembla` también en ellas, el contenido se iba **el doble**:
  21,7 px donde la cámara mueve 10,8 en `2970694180`, `3053927686` y
  `3146507587`, las tres con una `composelayer` a pantalla completa. Si se
  quedan quietas, lo que leen ya está movido y queda en su sitio; lo único que
  se retrasa es el marco del efecto, como mucho la amplitud.

Se descartó mover la imagen final entera: habría arrastrado también el grano,
la viñeta y demás capas de postproceso, que en WE no se mueven. Y dejaba el
parallax sin su parte del temblor.

### Lo medido

- **Planes de las 144 carpetas** (129 escenas y 15 vídeos), emitidos con
  `werender.emit_plan(dir, tmp, ruta_final=Path('/RUTA'))` en la base y en la
  rama y comparados con `cmp`: **138 idénticos byte a byte**, incluidas las tres
  apagadas. Cambian solo las seis encendidas, y solo porque se añaden líneas: una
  `temblor` y 8, 14, 39, 26, 15 y 40 `tiembla` (de 9, 14, 41, 31, 18 y 42
  `object`), en el orden de la lista de arriba.
- **El desplazamiento**, con `werender.py <dir> out.png --time t` en Mesa, a
  t = 0; 0,5 y 1. Se mide por correlación de fase, con un paso bajo para que el
  grano de película —idéntico en las dos imágenes— no tire del pico a cero, y
  con el pico buscado a ±25 px. Entre la base y la rama **en el mismo instante**
  la única diferencia es el temblor, y da (px de PNG, x a la derecha, y hacia
  abajo; predicción / medida):

| escena | t = 0 | t = 0,5 | t = 1 |
|---|---|---|---|
| `1692307745` | −1,94, 0 / −1,96, 0 | −1,08, +1,88 / −1,07, +1,88 | +0,74, +0,98 / +0,75, +0,98 |
| `2930166418` | −3,46, 0 / −3,45, 0 | −2,51, +2,92 / −2,51, +2,93 | −0,20, +3,12 / −0,19, +3,11 |
| `2970694180` | −10,80, 0 / −10,79, 0 | −10,00, +5,33 / −9,98, +5,33 | −7,72, +9,27 / −7,73, +9,26 |
| `3053927686` | −10,80, 0 / −11,61, 0 | −9,53, +6,56 / −10,23, +7,00 | −6,01, +10,42 / −6,45, +11,09 |
| `3146507587` | −10,80, 0 / −10,81, 0 | −9,48, +6,68 / −9,48, +6,68 | −5,84, +10,50 / −5,84, +10,50 |
| `3238423642` | −7,99, 0 / −8,00, 0 | −5,39, +6,86 / −5,40, +6,87 | +0,35, +6,96 / +0,34, +6,96 |

  Entre t = 0 y t = 0,5 de una misma rama se mezcla la animación propia de cada
  escena —la base ya se mueve hasta 8 px en `2970694180`—. Lo que aporta el
  temblor, (rama − base), es lo predicho: por ejemplo +1,34, +6,65 frente a
  +1,32, +6,68 en `3146507587`, y +2,60, +6,85 frente a +2,60, +6,86 en
  `3238423642`. En las **tres apagadas** los PNG de la rama son idénticos a
  los de la base a los tres instantes, y su desplazamiento entre 0 y 0,5 es el
  mismo que tenían.
- **`test_luminancia.py obj/glexec --referencia`** contra la de la base, las
  dos bajo el cerrojo y en Mesa: 129/129, **0 apagadas, 0 regresiones**. Las
  seis escenas mueven su media 0,39 como mucho (`2930166418`); las de plan
  idéntico, 0,13 como mucho, que es el ruido de relojes y vídeos entre dos
  pasadas.
- **`test_werender`**: `prueba_temblor_de_camara` fija la escala de la
  amplitud, el apagado —también cuando lo apaga una propiedad cuya copia dice
  `true`—, la curva de `src/wetemblor.c` compilada contra valores calculados a
  mano con la forma de arriba, y el plan de `1692307745` (con la línea
  `temblor 0.0010125 0.0018 1.4 1` y sus `tiembla`) y de `2968771936` (sin
  ninguna). Falla quitando la línea del plan, quitando la comprobación de
  `camerashake`, y con 1,3 en vez de 1,333 en la curva.

### Lo que queda

- **`3053927686` sale un 7 % largo** (11,6 px donde la fórmula da 10,8). El
  paralaje acoplado de sus capas, con `amount × depth` de 0,02 como mucho,
  explica un 2 %. Tiene una `composelayer` a pantalla completa con
  `depthparallax`, que deforma lo que lee según un mapa de profundidad que no
  tiembla; no se ha aislado.
- **El marco de las `composelayer` que no cubren la pantalla** se queda quieto
  cuando en WE se mueve con la cámara. Solo es visible en su borde, y como
  mucho en la amplitud. La de `3238423642` es de 2000×2000.
- **Una escena en perspectiva que tiemble** no se emite. No hay ninguna en el
  corpus.
- ~~**El `eye` declarado fuera del origen** —`2311315748` lo tiene en
  (57,1, −80,6)— también entra en el objetivo del parallax y aquí no se suma.~~
  **Cerrado sin cambiar el render**: [El `eye` de la cámara no llega al
  parallax](#el-eye-de-la-cámara-no-llega-al-parallax-we-lo-pone-a-cero-en-las-escenas-ortográficas).
  El cargador lo pone a cero en las escenas ortográficas sin `paths`
  (`0x14018866b`), que son las 47 que lo declaran; al objetivo solo llega el
  temblor, que ya se suma.

## Varios emisores: emiten todos, al mismo depósito

Un sistema de WE puede declarar más de un emisor en `emitter`, y aquí solo
emitía el primero: `weparticles.py` anotaba el resto como `emitter extra` y el
`.psys` llevaba una sola línea `emit`. «Lo siguiente» contaba 1 sistema, con la
biblioteca de 125; con la de 129 son **2 sistemas en 2 escenas**, y en los dos
el segundo emisor es una `sphererandom` **sin un solo campo**:

| escena | objeto | preset | emisores | override |
|---|---|---|---|---|
| `2367577039` | Fog 2 | `particles/presets/fog2.json` | `sphererandom` rate 1, `distancemax` 512 + `sphererandom` vacío | `rate` 0,5 |
| `3238423642` | reactive Stars | `particles/workshop/2365221023/Stars_copy1.json` | `boxrandom` rate 40, `distancemax` `1000 500 0` + `sphererandom` vacío | `rate` 0,5 (propiedad), `count` 0,19 |

### Lo leído y lo supuesto

**Leído:** que cada emisor tiene sus propios campos y que el que no declara
nada sale de los defectos del lector del emisor —`distancemax` `256 256 0`,
`directions` `1 1 0` y 10 por segundo, los de [los valores por
defecto](#los-valores-por-defecto-estaban-en-el-binario-el-giro-la-caja-el-ritmo-y-el-sesgo)—,
porque son los mismos dos lectores (`sphererandom` y `boxrandom`) los que se
desensamblaron. Así que el segundo emisor de los dos casos es una esfera de 256
en el origen del objeto, a 10/s.

**Supuesto, no leído en el binario:**

- **El `rate` del `instanceoverride` multiplica a CADA emisor.** Es un solo
  factor por objeto y es la única lectura que deja la proporción entre emisores
  como la puso el autor del preset. Con 0,5, los dos segundos emisores emiten
  a 5/s.
- **El depósito es uno**: `maxcount` está en la raíz del sistema, no en el
  emisor, y todos sueltan al mismo. Cuando está lleno, los emisores se atienden
  **en orden** en cada paso, así que el primero ocupa antes los huecos que se
  liberan. El orden también es un supuesto.
- `instantaneous` y `duration` van por emisor: el estallido de cada uno ocupa
  los huecos que siguen a los del anterior, y cada uno deja de emitir a su
  `duration`.
- Un **hijo de evento** se sigue colocando con su primer emisor y emitiendo a
  su `rate` (el `eventfollow`). Ningún hijo del corpus tiene dos.

El `audioprocessingmode` de los dos emisores de `Stars_copy1` se ignora, igual
que antes con el primero: no hay audio.

### Lo hecho

- `weparticles.py`: `Sistema.emisores` es una lista de `(forma, 20 floats)` y
  `escribir` saca una línea `emit` por emisor, en el orden del JSON. Un sistema
  de un solo emisor sale byte a byte igual. Hasta `MAX_EMISORES` (4); el que
  sobre se sigue anotando como `emitter extra`, y `test_weparticles` lo cuenta
  como fallo.
- `src/weparticles.c`, que enlazan los dos ejecutores: un array `Emisor em[4]`
  con forma, campos y **crédito propio**, que reemplaza a los campos sueltos del
  sistema. `emite`/`nace` reciben el emisor; cada partícula guarda cuál la soltó
  solo para contarlas (`we_psys_emisores`, `we_psys_vivas`, que usan
  `psysprobe` y la prueba). Un `.psys` de un solo `emit` se lee igual que antes.
  Al revés no: un `.so` anterior que lea uno de los dos `.psys` nuevos se queda
  con la **última** línea `emit`, o sea solo con la esfera vacía, hasta el
  `make reload`. Afecta a esos dos sistemas y a nada más.
- `werender.py` toma la ráfaga del hijo del primer emisor, como hacía.

### Lo medido

- **Censo**: `test_weparticles.py` sobre las 129 — 842 sistemas,
  `varios_emisores 2`, y la lista de piezas fuera de la simulación queda
  **vacía** (antes, `emitter extra:sphererandom` 2).
- **Los `.psys` de las 129**, con `cargar` + `escribir` para cada objeto con
  partículas y sus hijos (1414 ficheros, semilla fija), en la base y en la
  rama, con `diff -rq`: **1412 idénticos**; los dos que cambian son `fog2` y
  `Stars_copy1`, y solo por una línea añadida, la misma en los dos:
  `emit sphererandom 5 0 0 0 256 256 0 1 1 0 0 0 0 0 0 0 0 0 0 0`.
- **El simulador con un emisor no cambia**: `psysprobe` de la base y de la rama
  sobre los 1414 `.psys` de la base, a t = 3 y t = 20 —16 068 líneas de
  posiciones, velocidades y cuentas—: idénticas.
- **`psysprobe` sobre `Stars_copy1`** (depósito 95): a t = 3, 10 y 30, emisor 0
  44, 42 y 44 vivas; emisor 1, 14, 11 y 12. No se llena, así que no hay robo.
  **Sobre `fog2`** (depósito 20) sí lo hay: a t = 10, 2 del primero y **17 del
  segundo**. A 0,5/s con 3–5 s de vida el primero sostenía unas 2; el segundo,
  a 5/s, llena el resto. La niebla pasa de dos sprites sueltos por un óvalo de
  512 a un velo concentrado en el centro del objeto. Es lo que sale de los
  supuestos de arriba; no hay captura de Windows con que confirmarlo.
- **Contrato Python↔C** (`prueba_emisores` en `test_weparticles.py`): un preset
  con una caja de 100 px de semieje en x = 2000 a 30/s y una esfera vacía, con
  `rate` 0,5. Python da ritmos 15 y 5 y los defectos en la esfera; el C, a los
  10 s, **149 en la caja y 49 en la esfera, 0 fuera**, y con `maxcount 40`,
  30 + 10. Igual con `LC_ALL=C` y `es_ES.utf8`. Falla con el C de la base
  (no tiene `we_psys_emisores`) y con el Python de la base (`emisores` no
  existe).
- **`test_luminancia.py obj/glexec --referencia`** contra la base, las dos en
  Mesa y bajo el cerrojo: 129/129, **0 apagadas, 0 regresiones**.
  `3238423642` se queda en 32,32 (cambian 142 000 píxeles: las estrellas del
  segundo emisor, rojas y con alfa 0,4, y el reloj). `2367577039` baja de 67,49
  a 64,96, p99 de 242,3 a 228,7: el velo de niebla acerca todo a su color —los
  píxeles por debajo de 40 suben de 32,5 a 32,9 y los de más de 140 bajan de
  197,9 a 182,6—. Por eso «más partículas» no da más luz aquí. Las otras siete
  que se mueven tienen `.psys` y plan idénticos; la mayor es `3097749052`,
  36,52 → 35,08, que ya cambia entre dos renders del mismo binario.

## `flags: 2` no coloca el emisor: es una partícula por fotograma, y al cursor lo lleva el punto de control

**De dónde se partía.** El preset `trail_1` —el «Mouse Trail» del Workshop:
`sphererandom` con `distancemax: 0` y `flags: 2`, renderer `rope`, sin
velocidad, y el punto de control 0 con `flags: 1`— dibuja aquí la estela
clavada en el `origin` del objeto en vez de seguir al ratón. `weparticles.py`
no lee el `flags` del emisor y `src/weparticles.c` suelta cada partícula
alrededor del origen del sistema. La hipótesis a comprobar era «`flags & 2`: el
emisor se coloca en un punto de control». Encajaba con las 34 apariciones del
corpus (15 escenas), porque en todas las que no tienen el cursor en el punto 0,
ese punto coincide con el origen.

**La lectura la refuta.** El bit no coloca nada. Lo que coloca el emisor es
otra cosa, y vale para **todos** los emisores, lleven el bit o no. Así que no
se ha tocado el render: implementar «el bit 2 coloca» haría lo correcto en 11
emisores por la razón equivocada y dejaría fuera a los 6 que hacen lo mismo
sin el bit.

### Lo que hace WE, con direcciones

Se lee con el método de [los valores por
defecto](#dónde-guarda-we-sus-valores-por-defecto-y-cómo-se-leen) sobre el
`wallpaper64.exe` instalado. Cada fila se puede repetir con
`objdump -d --no-show-raw-insn -M intel --start-address=<dir> --stop-address=<dir+16> wallpaper64.exe`,
y `verifica_exe.sh` las comprueba todas: las cinco cadenas y 57 instrucciones,
una a una. Ese script y `censo_cp_emisor.py` no están en el repositorio: viven
con las medidas de la tarea, en
`~/.local/state/wallpaperengine-bucle/ejecuciones/20261004-211604/medidas/`,
y se ejecutan desde la raíz del repositorio (`sh …/verifica_exe.sh
[wallpaper64.exe]`, `python3 …/censo_cp_emisor.py`); `repetir.sh`, al lado,
pasa todas las medidas de la tarea.

| qué | dónde | lo que hace |
|---|---|---|
| bloques del emisor | `0x1401d83b0` / `0x1401d8450` | cada pieza va en un bloque con cabecera de 16 bytes: tipo **1** `sphererandom` (`0x1401d83ba`), **2** `boxrandom` (`0x1401d845a`) |
| lector común | `0x1401c1c70` | `rate` → `+0x00`, `instantaneous` → `+0x34`; **`flags` (`.rdata 0x14048f4cc`) → `+0x3c`** (`0x1401c1d35`). Lo llaman los dos (`0x1401c61d6`, `0x1401c691e`) |
| `controlpoint` en la esfera | `0x1401c5fb9..0x1401c600d` | **existe**: se lee como entero, se topa a **7** (`cmovb`, `0x1401c600a`) y va a `+0xe0` |
| `controlpoint` en la caja | `0x1401c6889..0x1401c6915` | lo mismo, a `+0x98` |
| su defecto | `0x1401b98b1` / `0x1401b98be` | el que inserta el lector si falta: **0** |
| `origin` | `+0x60` en los dos | (caja: `0x1401c6773`) |
| emisión, bit 1 | `0x140237b05..0x140237b2c` | `test BYTE PTR [r15+0x4c],0x2` —`+0x4c` del bloque es `+0x3c` del emisor— y, si está, la cuenta de este paso es **`min(cuenta, 1)`**. El crédito ya se ha descontado entero (`0x140237b19`), así que lo que sobra **se pierde**, no se aplaza |
| centro de la esfera | `0x140237c18..0x140237c82` | con el bloque de tipo 1, `índice = [r15+0xf0]` (el `controlpoint`), registro de punto de **0xd0** bytes, y centro = **punto.`+0x30` + `origin`** (`0x140237c54`, `0x140237c65`). No mira el bit 1. Sí lee el byte de `flags` (`movzx edi,BYTE PTR [r15+0x4c]`, `0x140237c2e`) para quedarse con el **bit 0** (`0x140237cbd`), que toca el sorteo y no el centro (fila siguiente) |
| bit 0: `sign` | `0x1401c6001..0x1401c61ed`, `0x140237ee0..0x140237f18` | el lector de la esfera lee `sign` (`.rdata 0x14048f49c`, `0x1401c6001`), guarda `sign < 0` en `+0x80` y `sign ≠ 0` en `+0x90` (`0x1401c6167`, `0x1401c613f`), y si `|sign|²` pasa de `FLT_EPSILON` pone el bit 0 (`0x1401c61ed`). En la emisión, con el bit (`test dil,dil`, `0x140237ee0`), a cada eje con `sign ≠ 0` cuyo signo no coincide se le cambia el signo (`[r15+0x90]`/`[r15+0xa0]`, por −1). Lo encienden 41 de las 1146 esferas del corpus; aquí `sign` ya viaja en la línea `emit`, y no se ha cotejado con esta lectura |
| giro con el punto | `0x140237c42..0x140237c5f`, `0x140237cc6..0x140237ce3`, `0x140237f24..0x140237f60` | carga las filas `+0x00`, `+0x10`, `+0x20` del registro del punto. `r12b = (controlpoint ≠ 0) ‖ ([sistema+0x20] & 1)`; si es cierto, el sorteo **se multiplica por esas filas** —y su cuarta componente por la fila `+0x30`— antes de sumar el centro. Si no, va tal cual (`0x140237f65`) |
| nacimiento | `0x140237f72` / `0x140237f7c` | posición = sorteo de la esfera (girado o no) + ese centro, a los arrays de x, y, z del sistema |
| centro de la caja | `0x14023847f..0x1402384ea` | tipo 2: `índice = [r15+0xa8]` (`+0x98`), `origin.x + punto.x` en `0x1402384c2`, igual en y, z |
| el punto, cada fotograma | `0x14022e3e0` | recorre los puntos: `flags` del punto en `+0xc0` (`0x14022e461`); con **`flags & 1`** (`0x14022e472`) lleva el ratón a la escena, lo pasa por la matriz del sistema según `[sistema+0x20] & 1` (`0x14022e4e5`; `r14` es el sistema, cuyos puntos están en `+0x400`, `0x14022e450`) y lo escribe en **`+0x30`** (`0x14022e656`). Antes copia la matriz base del punto, `+0x80..+0xb0`, sobre `+0x00..+0x30` (`0x14022e47b..0x14022e4ae`), así que sus filas de giro son las de esa matriz base |

Así que, en WE:

- **Todo emisor emite alrededor de su punto de control**, el que diga su
  `controlpoint` (0 por defecto, 7 como mucho), más su `origin`. Un punto
  atado al cursor se mueve cada fotograma con el ratón, y el emisor con él.
  Eso es lo que hace de `trail_1` una estela.
- **`flags & 2` es «una por fotograma»**: con el bit, el emisor suelta como
  mucho una partícula por paso y tira el resto del crédito. En una cinta
  —`rope` une partículas sucesivas— da un punto por fotograma, que es lo que
  necesita un rastro continuo.
- `flags & 4` es la emisión periódica (`minperiodicdelay` y compañía,
  `0x140237a15`), y el bit 0 lo pone el propio lector de la esfera cuando su
  `sign` no es nulo (`0x1401c61ed`): con él, la emisión fuerza el signo del
  sorteo eje a eje (`0x140237ee0..0x140237f18`), no toca el centro. En el
  JSON del corpus el `flags` de los emisores solo vale 0 (1380) o 2 (34); el
  bit 0 se lo enciende el lector a 41 esferas por su `sign`.
- **El sorteo también gira con el punto**, no solo se traslada: si el emisor
  tiene `controlpoint ≠ 0`, o el sistema tiene el bit 0 de `+0x20`, el vector
  sorteado se multiplica por las filas `+0x00`, `+0x10`, `+0x20` del registro
  del punto antes de sumarle el centro (`0x140237cc6..0x140237ce3`,
  `0x140237f24..0x140237f60`). Su cuarta componente multiplica además la fila
  `+0x30`, la posición; no se ha leído si vale 0. ~~Para qué sirve el bit de
  `+0x20` del sistema, qué campo del JSON lo enciende, no se ha leído~~: es
  el bit 0x1 del `flags` del SISTEMA, la casilla «worldspace» del editor
  (leído después: el `flags` va al descriptor+0x8 y de ahí a sistema+0x20;
  ver [Partículas con
  perspectiva](#partículas-con-perspectiva-el-bit-0x4-del-flags-del-sistema-es-otra-cámara-no-otra-simulación)).
  Es el mismo que decide si el ratón pasa por la matriz del sistema
  (`0x14022e4e5`). En el corpus solo un emisor tiene `controlpoint ≠ 0`,
  `shurikencursor_1`, y con `distancemax: 0`.
- Al punto atado al cursor, WE le escribe **el ratón tal cual**: el `offset`
  del punto no se suma. Aquí `we_psys_puntero` sí lo suma, pero las 303
  apariciones de puntos atados al cursor del corpus declaran `0 0 0`, así que
  no cambia nada.

### El corpus con la regla leída

`censo_cp_emisor.py`, sobre las 129 (presets, hijos y el `controlpointN` del
`instanceoverride`):

| | emisores | escenas |
|---|---|---|
| `sphererandom` + `boxrandom` (1146 esferas) | 1414 | 109 |
| con `flags & 2` | 34 | 15 |
| con su punto de control **atado al cursor** | **17** | **12** |
| — de ellos con `flags & 2` | 11 | 8 |
| — **sin** `flags & 2` | **6** | **5** |
| con su punto quieto pero con `offset` ≠ 0 | 0 | 0 |
| que declaran `controlpoint` | 5 (valores 0 y 1) | 4 |

Los 1414 son emisores `sphererandom`/`boxrandom` contados en el JSON; que
coincidan con los 1414 `.psys` de [varios emisores](#varios-emisores-emiten-todos-al-mismo-depósito)
no quiere decir que sean lo mismo: aquellos son ficheros, uno por objeto con
partículas y por hijo, y aquí se cuentan emisores de esos dos tipos.

Los seis sin el bit son lo que tumba la hipótesis desde el corpus, sin
necesidad del binario: `mouse_trail_1`, `shurikencursor_1` (de
`3238423642`, que declara **`controlpoint: 1`** y tiene el cursor justo en el
1), dos `Cherry_Blossoms_2`, `new_particle_system_6` y
`new_particle_system_copy1`. Son efectos de cursor que hoy nacen en el origen
igual que `trail_1`. Las 12 escenas son `1507488058 1571201795 1670374509
1811999326 2556172772 2710814362 2788036464 2821288001 2864647826 3082427731
3238423642 3462491575`. Los `vapor`, `shootingstar` y `短` no cambian con
ninguna de las dos lecturas: su punto es el 0, quieto y en el origen.

Del tope de una por fotograma: de los 34 con el bit, 10 piden más de 30 por
segundo y 1 más de 60 (el máximo, 70/s). `trail_1` pide 32. Cuánto recorta
depende de los fps a los que corra WE, que el usuario elige.

### Lo que queda, para hacerlo bien

Es una tarea distinta de la que se pidió, y su criterio no es «solo cambian
los sistemas con `flags & 2`», sino «solo cambian los 17 emisores con su punto
atado al cursor»:

1. `weparticles.py` lee `controlpoint` (entero, defecto 0, tope 7) y lo lleva
   al `.psys`, al final de la línea `emit` para que un `.so` anterior lo
   ignore. `src/weparticles.c` centra `emite` en `cp[controlpoint]` además de
   `origin`. Los puntos quietos del corpus valen 0, así que eso no mueve
   ningún sistema sin cursor. Además, WE **gira** el sorteo con la matriz del
   punto cuando `controlpoint ≠ 0` o el sistema lleva el bit 0 de `+0x20`
   (tabla, «giro con el punto»); hace falta para `shurikencursor_1`
   (`controlpoint: 1`), aunque con su `distancemin`/`distancemax` a 0 el
   radio del sorteo es 0. Lo que sí tiene es `speedmin`/`speedmax` 100: las
   mismas filas se guardan también en la pila (`[rbp-0x78]..[rbp-0x58]`,
   `0x140237cac..0x140237d16`), y si la velocidad de salida gira con ellas
   **no se ha leído**. El punto atado al cursor gira con su matriz base
   (`+0x80..+0xb0`), que tampoco se ha leído de dónde sale. Ojo con los repartos por puestos
   (`mapsequence*`), que ya sustituyen el origen del emisor por un punto: hay
   que ver si en WE se suman o se pisan.
2. **Sin ratón**: hoy un punto atado al cursor se queda en su `offset` hasta
   que llega el puntero. Mantenerlo así hace que `test_luminancia`, sin
   `--puntero`, no cambie; es lo coherente con [«sin ratón» no es «ratón en el
   centro»](#el-puntero-viaja-como-el-tiempo-un-marcador-en-la-plantilla). Lo
   que WE pone antes del primer movimiento no se ha leído.
3. `flags & 2`, una por fotograma, por separado. En el simulador, el paso es
   fijo (`1/60`) y no el fotograma, así que hay que decidir a qué se ata el
   tope.
4. Cómo une WE las partículas de un `rope` (si es una cinta por partícula, como
   aquí, o una que cose las partículas sucesivas) **no se ha leído**. Con
   `trail_1` importa: sus partículas nacen quietas, y una cinta por partícula
   quieta no dibuja nada aunque nazca en el cursor.

### Lo medido

- `verifica_exe.sh`: las cinco cadenas y las 57 instrucciones de la tabla,
  cada una en su dirección. **62 ok, 0 fallos.**
- `censo_cp_emisor.py`: las cifras de la tabla del corpus, los valores de
  `flags`, los ritmos, los offsets de los puntos atados al cursor, las 41 de
  1146 esferas con `sign` no nulo y el único emisor con `controlpoint ≠ 0`.
- El render no cambia: ni `tools/*.py`, ni `src/`, ni `tools/*.c` tienen diff
  contra la base. `test_weparticles.py` pasa entero sobre las 129, con la
  lista de piezas fuera de la simulación vacía.

## Los ejes de la turbulencia: `forward` gira alrededor de `right`, y `up` no se lee

**De dónde se partía.** `weparticles.py` lee de `turbulentvelocityrandom` solo
`scale`, `timescale`, `speedmin`/`speedmax`, `phasemax` y `offset`, y tira
`forward`, `right`, `up` y `phasemin`. Cinco ficheros del corpus declaran algún
eje, en tres escenas: `smoke2` (1877658892, tres objetos), `smoke1`
(2250845956) y `Flare_Flame`, `Flare_Sparks` y `Flare_Smoke` (2937370591).
[La turbulencia no turbulaba](#la-turbulencia-no-turbulaba) decía que el
formato no traía ningún campo de dirección, y la tabla de cadenas del motor
decía lo contrario. La tarea era leer qué hace WE con ellos y aplicarlo a
nuestro ruido. **La lectura da la regla entera, pero no se aplica**, porque
WE no tiene nuestro ruido: su regla no se monta encima del simulador de hoy,
lo sustituye, y con eso cambiarían también las 147 piezas que no declaran
ningún eje. De la regla quedan fuera una rama de audio, que aquí no tiene
soporte, y dos preguntas abiertas: de dónde sale el booleano de la rapidez
por defecto y qué es `[obj+0x130]`.

### Lo leído, con direcciones

Con el método de [Dónde guarda WE sus valores por
defecto](#dónde-guarda-we-sus-valores-por-defecto-y-cómo-se-leen). La fábrica
compara el nombre (`0x1401c8748`) y reserva un bloque de **tipo 9** y `0x64`
bytes (`0x1401d8847`), con los datos desde el byte 4. Antes de leer nada,
inserta los defectos que falten (`0x1401c8782` → `0x1401bb030`):

| campo | defecto | dónde se inserta | dónde se guarda (datos / bloque) |
|---|---|---|---|
| `speedmin` | **0,5**, o **100** con un booleano de la fábrica | `0x1401bb060` / `0x1401bb056` | `+0x0` / `+0x4` |
| `speedmax` | **1**, o **250** con el booleano | `0x1401bb134` / `0x1401bb12a` | `speedmax − speedmin` en `+0x4` / `+0x8` (`0x1401c8b19`) |
| `phasemin` | 0 | `0x1401bb240` | `+0x8` / `+0xc` |
| `phasemax` | **0,1** | `0x1401bb2e4` | `phasemax − phasemin` en `+0xc` / `+0x10` (`0x1401c8899`) |
| `timescale` | 1 | `0x1401bb30f` | `+0x10` / `+0x14` |
| `scale` | **1** | `0x1401bb326` | `+0x14` / `+0x18` |
| `offset` | 0, **escalar** | `0x1401bb33d` | `+0x18` / `+0x1c` |
| `forward` | **`0 1 0`** (`0x14048f6d0`) | `0x1401bb34f` | `+0x1c..+0x24` / `+0x20` (`0x1401c88f4`, `0x1401c8a05`, `0x1401c8a17`) |
| `right` | **`0 0 1`** (`0x14048f6e0`) | `0x1401bb365` | `+0x28..+0x30` / `+0x2c` (`0x1401c89fe`, `0x1401c8b1e`, `0x1401c8b30`) |
| `up` | — | — | **no se lee**: ni el lector (`0x1401c873d..0x1401c8b60`) ni los defectos (`0x1401bb030..0x1401bb38c`) citan la cadena `up` (`0x14048e5ec`) |

El booleano llega a la fábrica desde la pila (`0x1401c701b`, `[rbp+0x2238]`),
y de dónde sale no se ha leído.

### La regla

La aplica el inicializador `0x14023b340`. Despacha por el tipo del bloque
(`0x14023b5c0`, tabla en `0x14023fa78`) y el tipo 9 cae en `0x14023bdbc`:

```
a     = phasemax − phasemin                           0x14023bdc0
a    *= audio(bloque + 0x44)     si su modo no es 0   0x14023bdcc..0x14023bddc
u     = sorteo uniforme                               0x14023bdf3
fase  = phasemin + u · a                              0x14023bdfb, 0x14023bdff
θ     = π · scale · snoise1((fase + [obj+0x130]) · timescale) + offset
                                                      0x14023be04..0x14023be42
G     = rotate(I, θ, right / |right|)                 0x14023be5e
v     = M · (G · forward) · (speedmin + u' · ancho)   0x14023be84, 0x14023bed8,
                                                      0x14023bef9
vel  += v                                             0x14023bf0d
```

- **La rama de audio.** El caso 9 empieza mirando el dword de bloque+0x44
  (`cmp DWORD PTR [rdx],r13d` en `0x14023bdcc`, con `rdx = r14+0x44` y
  `r13d = 0` desde `0x14023b37e`). Si no es 0, llama a `0x14022a8a0`
  (`0x14023bdd4`) y multiplica el ancho de la fase por lo que devuelve
  (`mulss xmm6,xmm7` en `0x14023bddc`). Ese bloque+0x44, datos+0x40, lo
  rellena el lector común de los `audioprocessing*` (`0x1401c1e20`): el de la
  turbulencia lo llama en `0x1401c8b5b` con `rcx = datos+0x40` (`0x1401c8b23`).
  Guarda el `audioprocessingmode` en +0 (`0x1401c2168`), el exponente en +4
  (`0x1401c2222`), los `audioprocessingbounds` en +8/+0xc (`0x1401c21f8`,
  `0x1401c2205`) y la banda de frecuencias en +0x10/+0x14 (`0x1401c2246`).
  Si el modo falta, el lector inserta un 0 (`0x1401c1e83`, con `r15 = 0`
  desde `0x1401c1e4c`), y la pieza no pasa por esta rama.
- `0x14022a8a0` despacha por el modo (`0x14022a8b5`) y saca el máximo de las
  bandas, entre esas dos frecuencias, del array de floats de `[obj+0x2d0]`. El
  modo 1 lo saca de la primera mitad (`0x14022aa36`); el 2, de la segunda, 16
  floats después (`0x14022a9b7`); y el 3, de la suma de las dos
  (`0x14022a903`, `0x14022a909`), multiplicada por 0,5 (`0x14022a97c`).
  Después lo lleva a [0, 1] entre los dos `bounds` (`0x14022aaa5`), lo suaviza
  con x²·(3 − 2x) (el 3, de `0x140492830`, en `0x14022aaca`) y lo eleva al
  exponente (`0x14022aaf2`, la llamada a `0x14041e350`). El resultado vuelve a
  quedar en [0, 1]. Dos cosas son inferencia y no lectura. Que `[obj+0x2d0]`
  sea el espectro de audio lo dicen los nombres de los campos, no quién
  escribe el array. Y que `0x14041e350` sea `powf` lo dicen sus argumentos.
- **La reactividad al audio no está soportada**, porque el motor no tiene
  audio (CLAUDE.md, «Qué no soporta»). La regla de aquí **omite esta rama** y
  equivale al modo 0. En el corpus la usan 2 piezas, las dos con
  `audioprocessingmode: 3`: `wildfire.json` (1444777554) y `Stars_copy1.json`
  (3238423642). Ninguna de las 5 con ejes la usa (`censo_turbvel.py`).
- `snoise1` (`0x14027b090`) es el ruido simplex 1D de siempre: la tabla de
  Perlin en `0x140484f40` y el factor 0,395. Se muestrea en el **tiempo**,
  no en la posición. Las partículas que nacen a la vez salen casi paralelas,
  y el chorro serpentea al pasar los segundos. Que `[obj+0x130]` sea el reloj
  del sistema lo dice el uso, no una lectura: es también una de las entradas
  de `remapvalue` (`0x14023d219`).
- `right` se **normaliza** (`glm::rotate`, con la raíz y la división en
  `0x1401e25b0`) y `forward` **no**. La norma de `forward` escala la
  velocidad: `smoke1`, con `0 0.25 0`, sale a la cuarta parte de su
  `speedmin`/`speedmax`, y `Flare_Sparks`, con `0 0 0`, no recibe ninguna
  velocidad de esta pieza. Su `up 0 100 0` no multiplica nada porque no se
  lee, y el `right 10 0 1` de `Flare_Smoke` es solo una dirección.
- `offset` es un **ángulo** que se suma a θ, no un desplazamiento del punto de
  muestreo.
- `M` (`r15`, el tercer argumento: `0x14023b364`) es la misma matriz por la que
  pasa `velocityrandom` (tipo 7, `0x14023bbaf`): el giro del objeto lo trata
  igual en las dos piezas.

`verifica_exe.sh` comprueba las 18 cadenas, las 9 constantes, la tabla de
permutación, la entrada de la tabla de saltos, los dos tramos sin `up`, el
tramo en el que `r13` sigue valiendo 0 y 122 instrucciones, cada una en su
dirección.

### Por qué no se aplica

**Aplicado después**, con los dos cabos leídos: el booleano es «la escena es
ortográfica» y `[obj+0x130]` son los segundos de la escena. Ver [La turbulencia
con la regla de WE](#la-turbulencia-con-la-regla-de-we-turbulentvelocityrandom-deja-de-muestrear-nuestro-ruido).

La identidad implícita de hoy no es el defecto de WE. Hoy, sin ejes, cada
partícula sale por el rotacional de un ruido 3D evaluado en su posición,
desplazado por el sitio del objeto (`desplazar_ruido`). En WE, sin ejes, todas
salen por `forward = (0, 1, 0)` girado ±π·`scale` alrededor de z. Además, hay
otras cuatro diferencias que solo se ven al leer la pieza entera
(`censo_turbvel.py`, 152 piezas en 66 escenas):

- `offset`: 97 piezas lo declaran (−0,5 ×45, 3 ×34, −0,1 ×14, 0 ×3 y 0,5 ×1),
  todas como escalar. Hoy se reparte a los tres ejes del punto de muestreo y
  en WE es un giro en radianes.
- `speedmin`/`speedmax`: 53 piezas no declaran el primero y 50 el segundo, y
  esas 50 no declaran ninguno de los dos. Hoy faltan como 0, así que esas 50
  no dan velocidad; en WE valen 0,5–1 o 100–250, según el booleano.
- `phasemax`: 117 no lo declaran (WE, 0,1). `timescale` y la fase no se usan
  hoy en el inicializador.
- `scale`: solo 1 pieza no lo declara (WE, 1; aquí, 0,01).

Aplicar los ejes solo a los cinco que los declaran daría dos semánticas para
la misma pieza: un `forward: "0 1 0"` escrito se comportaría distinto que uno
omitido, que vale lo mismo. Sería un caso especial por campo presente, que
tapa la causa en vez de arreglarla. Hacerlo bien es **sustituir el
inicializador** por la regla de arriba en las 152 piezas, y eso es otra tarea,
con otro criterio: cambian las 66 escenas, no tres. Lo que haría falta:

1. Python lleva al `.psys` todo lo leído (`forward`, `right`, la fase, la
   rapidez con sus defectos y el `offset` como ángulo) y deja de desplazar el
   punto de muestreo. El simulador hace el giro con el ruido 1D, sembrado como
   el resto.
2. Decidir qué hacer con `ESCALA_RUIDO` y `desplazar_ruido`, que con la regla
   de WE no tienen sentido.
3. Leer el booleano de la rapidez por defecto y confirmar `[obj+0x130]`. La
   rama de audio se queda fuera, como el modo 0, mientras no haya audio.
4. Un oráculo: con 66 escenas, la regla leída sola no basta para validar el
   aspecto del humo.

### Lo medido

`rumbo_turbvel.py` aísla la pieza: deja en cada `.psys` solo
`lifetimerandom` y `turbulentvelocityrandom`, sin operadores, y le pasa
`psysprobe` en t = 1, 2 y 3. Al lado pone la regla de arriba por Monte Carlo,
con el ruido del exe y suponiendo que `[obj+0x130]` es el instante de
nacimiento. El rumbo está en grados, en el marco del sistema (y hacia arriba),
y `c` es la coherencia, |media| / rapidez media. La rama no toca el render,
así que la columna de la rama es la de la base:

| fichero | `.psys` | base = rama, rumbo (c), t = 1 / 2 / 3 | regla de WE, rumbo (c), t = 1 / 2 / 3 |
|---|---|---|---|
| `smoke2` | 1877658892/s000 | −163,2 (0,86) / −163,2 (0,86) / −163,2 (0,86) | 97,6 (1,00) / 94,1 (1,00) / 93,5 (1,00) |
| `smoke2` | 1877658892/s001 | 105,7 (0,97) / 105,5 (0,97) / 105,4 (0,97) | 97,6 (1,00) / 94,0 (1,00) / 93,4 (1,00) |
| `smoke2` | 1877658892/s002 | 45,7 (0,51) / 46,1 (0,50) / 45,8 (0,50) | 97,6 (1,00) / 94,0 (1,00) / 93,4 (1,00) |
| `smoke1` | 2250845956/s002 | 60,4 (0,88) / 60,2 (0,88) / 60,5 (0,88) | 94,9 (1,00) / 93,5 (1,00) / 92,8 (1,00) |
| `Flare_Flame` | 2937370591/s003 | 64,3 (0,34) / 64,2 (0,34) / 65,3 (0,35) | 1,3 (0,13) / 82,4 (1,00) / 81,1 (0,85) |
| `Flare_Sparks` | 2937370591/s002 | 175,6 (0,75) / −178,6 (0,55) / 161,7 (0,75) | sin velocidad: `forward 0 0 0` |
| `Flare_Smoke` | 2937370591/s004 | 59,0 (0,56) / 58,7 (0,55) / 58,9 (0,55) | 57,1 (0,74) / 62,9 (0,93) / 63,0 (0,95) |

De las 18 medidas con rumbo en la regla, **12 caen hoy a más de ±15°**. Los
tres objetos que comparten `smoke2` salen hoy en tres direcciones, porque cada
uno muestrea otro trozo del ruido, y en WE salen los tres hacia arriba.

- `verifica_exe.sh`: **154 ok, 0 fallos**.
- `planes_iguales.sh`, contra la base 78e0665 sobre las 129: **1131 de 1131
  idénticos** (`plan.txt` y `.psys`), y `psysprobe` en t = 2 y 5 da lo mismo en
  **2004 de 2004**. El único diff de código es el comentario de
  `ESCALA_RUIDO` en `weparticles.py`, que repetía la frase equivocada, y su
  AST es idéntico al de la base (`sin_cambio_render.sh`).
- `censo_turbvel.py`: las cifras de arriba. `censo_campos_psys.py` del triador
  sigue dando los 5 ficheros.
- Los scripts están en
  `~/.local/state/wallpaperengine-bucle/ejecuciones/20261006-134236/medidas/`,
  con su `repetir.sh`.

## El `eye` de la cámara no llega al parallax: WE lo pone a cero en las escenas ortográficas

Quedaba al final de [El temblor de
cámara](#el-temblor-de-cámara-también-estaba-en-el-motor-y-no-es-ruido): WE
suma al objetivo P del parallax el ojo de la cámara (`escena+0xf0`,
`0x140189c18`), y aquí no se sumaba el `eye` que 47 escenas declaran fuera del
origen. Once de ellas tienen
`cameraparallax`, y el término que faltaría, `−amount·parallaxDepth·eye`,
llegaba a 105 px de lienzo en `2109934461`, 75 en `3521337568`, 66 en
`3082427731` y 56 en `2262142032`. El orden era leer primero y aplicar después.
**La lectura dice que no hay nada que aplicar:** el cargador de la escena lee
el `eye` y, unas instrucciones más abajo, lo pone a cero si la escena es
ortográfica y no tiene `paths`. Las 47 lo son y ninguna los tiene. El ojo que
llega a P es (0, 0) más el temblor, que es justo lo que ya se hacía. No cambia
el render; cambian un comentario y una prueba.

### Lo leído, con direcciones

Con el método de [Dónde guarda WE sus valores por
defecto](#dónde-guarda-we-sus-valores-por-defecto-y-cómo-se-leen). La escena
guarda **dos** cámaras: la **declarada** (`+0x118` ojo, `+0x124` centro,
`+0x130` up), que sale del json, y la **vigente** (`+0xf0`, `+0xfc`, `+0x108`),
que se rehace cada fotograma y es la que lee el parallax.

- **Las cadenas**, en `.rdata`: `camera` en `0x14048e4d0`, `eye` en
  `0x14048e59c`, `center` en `0x14048e594`, `up` en `0x14048e5ec`, `paths` en
  `0x14048e5e4` y `orthogonalprojection` en `0x1404890c0`.
- **El constructor** (`0x140186c90`) pone las dos cámaras en (2, 2, 2): la
  vigente en `0x140186db3`, la declarada en `0x140186ded`.
- **El cargador** es la misma función, partida en cuatro fragmentos
  encadenados de `.pdata` (`0x140186c90..0x140188816`). Guarda el nodo
  `camera` en la pila (`0x140187440`; ese `[rbp+0xf0]` es un local, no la
  escena). Con `orthogonalprojection` —`auto`, o un ancho y un alto que no sean
  los dos cero— enciende el bit 3 de `+0xe0` (`0x140187565`, `0x1401875df`).
  Después lee `eye` como cadena de tres números a `+0x118/+0x11c/+0x120`
  (`0x1401882fe`, `0x140188307`, `0x140188310`), `center` a `+0x124`
  (`0x1401883f9`), `up` a `+0x130` (`0x1401884f3`) y `paths`, si es un array,
  al vector `+0x310` (`0x140188597`).
- **Y lo borra.** En `0x140188648..0x140188692`: si el bit 3 está encendido y
  `+0x310` está vacío, ojo (0, 0, 0), centro (0, 0, −1) y up (0, 1, 0)
  (`0x14018866b` es el `mov QWORD PTR [r14+0x118],r15` con `r15` a cero). En
  todo el cargador `escena+0x118` se escribe tres veces: el defecto, el json y
  este cero.
- **Cada fotograma** (`0x1401891a0`) la cámara vigente sale de uno de tres
  sitios. Si hay un **objeto cámara** visible (más abajo), de su matriz
  (`0x1401892df`). Si no, y no hay `paths`, se copia la declarada
  (`0x14018942e..0x14018944a`: `+0xf0 ← +0x118`, `+0xfc ← +0x124`) y le suma el
  temblor (`0x14018949f`). Con `paths`, se interpolan.
- **El objetivo**: `x += [+0xf0]` en `0x140189c18` e `y += [+0xf4]` en
  `0x140189c24`, los dos con signo más y la y hacia arriba como el resto de la
  fórmula (`1 − raton.y`, `0x140189b95`); P queda en `+0x340/+0x344`. Con un ojo
  vigente no nulo, el término sería `−a·d·ojo` en el lienzo, con la y hacia
  arriba, que es lo que suponía la tarea. Pero ese ojo es cero.

El mismo cero contesta lo que la tarea dejaba fuera: el `eye` declarado
tampoco traslada la vista en una escena ortográfica. Cuadra con el preview de
`2821288001`, ojo en (841, 277), que sale centrado en el lienzo ([Pendiente:
tres cabos de las
partículas](#pendiente-tres-cabos-de-las-partículas-medidos-y-sin-cerrar)).

### Lo que dicen los previews

Se comprobó la hipótesis contra el preview de las once antes de descartarla:
`ncc_preview.py` busca el mejor encaje de cada preview (o del primer fotograma
del GIF) en el render a 1280 de ancho, barriendo escala y posición, y lo hace
con la base, con la rama y con el `eye` sumado en memoria. La rama da el mismo
PNG que la base en las once. Con el `eye`:

| escena | base = rama | con el `eye` | escena | base = rama | con el `eye` |
|---|---|---|---|---|---|
| `2109934461` | 0,9906 | 0,9858 | `2250845956` | 0,9549 | 0,9547 |
| `3521337568` | 0,8602 | 0,8522 | `2317494988` | 0,9018 | 0,9057 |
| `3082427731` | 0,8044 | 0,8042 | `2319253136` | 0,9338 | 0,9282 |
| `2262142032` | 0,8066 | 0,8208 | `2557734973` | 0,9619 | 0,9595 |
| `2810252468` | 0,8351 | 0,8174 | `1173201544` | 0,9533 | 0,9417 |
| `2311315748` | 0,8124 | 0,8124 | **media** | **0,8923** | **0,8893** |

Empeora en siete y mejora en `2262142032` (+0,014) y `2317494988` (+0,004);
en `2311315748` la diferencia está en la quinta cifra. La que más discrimina
es `2109934461`, con profundidades de 1 a 0,32 entre sus capas y hasta 71 px
de desplazamiento relativo: empeora. Es una medida ruidosa —`1173201544`
baja 0,012 con 2 px de diferencia—, de apoyo; manda el código.

La pista que traía la tarea, el reloj de `2262142032`, tampoco decide.
`reloj_2262.py`, con la hora congelada a la del preview (17:38), encaja el
preview y busca después el reloj alrededor de donde ese encaje lo pone: queda
a (+22,8, +11,7) px de lienzo en la base, |d| = 25,7, y a (+15,4, +1,1), |d| =
15,5, con el `eye`. Pero el reloj y el fondo tienen la misma profundidad, 1, y
el `eye` los mueve juntos: la mejora sale del encaje global (escala 0,970 →
0,980), no del reloj. Que el preview de esta escena encaje mejor movido no se
ha explicado; un preview es una captura del autor, quizá desde el editor, y
nada dice que el editor cargue la escena igual.

### Cómo queda aquí

- `parallax_de_camara` (`werender.py`) dice por qué no suma el `eye`, con las
  dos direcciones.
- `prueba_parallax_de_camara` (`test_werender.py`) declara ahora la escena
  ortográfica y con el `eye` en (200, 40): si alguien lo suma, la raíz se va a
  (700, 80) en vez de (900, 100) y la prueba falla.

### Lo medido

Contra la base `d01ed59`, con los scripts de
`~/.local/state/wallpaperengine-bucle/ejecuciones/20261007-171029/medidas/`:

- `verifica_ojo.sh`: **86 ok, 0 fallos**: las cadenas, los fragmentos de
  `.pdata`, cada instrucción citada arriba y el recuento de escrituras.
- `censo_orto.py`: de las **47** escenas con `eye` fuera del origen, **47**
  ortográficas, **0** con `paths` y **1** con objeto cámara, `3521337568`.
- `planes_ojo.py`, las 129 con la hora congelada (`hora.py`, porque los
  relojes de texto se resuelven al emitir): **129 de 129 planes idénticos** y
  ninguna línea cambiada en las once. Con el `eye` sumado cambiarían entre 6
  (`2311315748`) y 348 (`2262142032`) líneas en cada una, así que la
  comparación lo habría visto.
- `paralaje_ojo.py`: las **137 raíces** con profundidad de las once dan
  `_paralaje(rama) − _paralaje(base)` = −a·d·ojo vigente con error 0, y el ojo
  vigente es (0, 0) en diez; en `3521337568` es el del objeto cámara, que no se
  emula, y la diferencia también es 0.
- `luz_11.py`: `test_luminancia` (`mide`, `preview` e `informe` del test) sobre
  las once, la rama contra la base: la misma media en las once, 0 apagadas, 0
  regresiones. Las 118 restantes tienen el plan idéntico.
- `guarda_test.sh`: `test_werender` pasa, y con el `eye` sumado falla con la
  raíz en (700, 80).

### Lo que queda

- **Los objetos cámara.** Un objeto con `camera` de texto —`3521337568` y
  `3462491575` lo tienen, `"default"`, con `path` a un
  `scripts/camera_paths_*.json` vacío y `origin` o `zoom` animados— es un objeto
  cámara: el cargador de objetos lo crea (`0x140190693`, `0x360` bytes) y lo
  mete en `escena+0x1f8` (`0x140190722`). Si está visible, con sus padres, la
  cámara vigente sale de su matriz (`0x1401892df..0x140189361`) y no de la
  declarada: mueve la vista y el P del parallax. Aquí no se lee. `3521337568`
  es una de las once, y en ella el ojo que llega a P no es cero; no se sabe
  cuánto vale.
- **Las escenas con `paths`** conservan el `eye` y lo interpolan. No hay
  ninguna en el corpus.

## La turbulencia con la regla de WE: `turbulentvelocityrandom` deja de muestrear nuestro ruido

[Los ejes de la
turbulencia](#los-ejes-de-la-turbulencia-forward-gira-alrededor-de-right-y-up-no-se-lee)
leyó la regla entera del inicializador y no la aplicó. La razón era que no se
monta encima del ruido 3D de aquí: lo sustituye, en las 152 piezas de 66
escenas. El síntoma seguía ahí. Los tres objetos que comparten `smoke2`
(1877658892) salían en tres direcciones (−163°, 105° y 46°) y la regla los manda
a los tres hacia arriba. Además, 12 de las 18 medidas de rumbo caían a más de
±15°. Para aplicarla faltaban dos lecturas: de dónde sale el booleano de la
rapidez por defecto y qué es `[obj+0x130]`. De la primera dependían las 50 piezas
sin `speedmin` ni `speedmax`, que hoy no dan velocidad y con la regla dan
0,5–1 o 100–250. Si el booleano no se dejaba leer, no se aplicaba nada.

### El booleano es «la escena es ortográfica»

Con el método de [Dónde guarda WE sus valores por
defecto](#dónde-guarda-we-sus-valores-por-defecto-y-cómo-se-leen):

- **En la fábrica.** La fábrica de partículas (`0x1401c5490`) guarda su primer
  argumento en `[rsp+8]`. Con `rbp = rsp − 0x2210` tras el `push`
  (`0x1401c54a0`), ese hueco es `[rbp+0x2220]`, y de ahí sale `r14`
  (`0x1401c579b`). `[r14]` es el **contexto** del renderizador. En `0x1401c5b75`
  la fábrica llama a `0x14010daa0` con él, y lo que devuelve va a `[rbp+0x2238]`
  (`0x1401c5b7e`). Nada más escribe ahí antes de `0x1401c701b`.
- **El bit.** `0x14010daa0` es `([contexto+0x118] >> 10) & 1`.
- **Quién lo pone.** Ese bit lo apaga (`0x1401872ca`) y lo enciende
  (`0x14018768a`) el cargador de la escena, y son las dos únicas instrucciones
  del binario que lo tocan. Lo enciende si está encendido el bit 3 de
  `escena+0xe0`, el de la proyección ortográfica. El contexto es el cuarto
  argumento del cargador: `[rsp+0x20]`, que es `[rbp+0x1e8]` y pasa a `r13`
  (`0x1401872ad`) y a `escena+0xd8` (`0x140186d13`).
- **Cuándo es ortográfica** (`0x1401874ec..0x1401875df`).
  `orthogonalprojection` tiene que ser un objeto. Con `auto` a true lo es
  (`0x140187565`). Si no, `width` y `height` tienen que ser números y **los
  dos** distintos de cero: con el ancho a cero apaga el bit (`0x1401875cb`), y
  con el alto a cero también. Lo que se dijo en [el `eye` de la
  cámara](#el-eye-de-la-cámara-no-llega-al-parallax-we-lo-pone-a-cero-en-las-escenas-ortográficas),
  «que no sean los dos cero», era impreciso, aunque no cambiaba nada allí. Sin
  el campo, el constructor deja `+0xe0 = 0x26`, sin el bit (`0x140186d1f`).
- **Las 129 escenas del corpus son ortográficas**: 128 con ancho y alto
  distintos de cero y una con `auto`. El defecto es **100–250** en todas.

### `[obj+0x130]` son los segundos de la escena

- **Es el mismo contexto.** El `obj` del inicializador es `[instancia]`
  (`0x14023b361`, `0x14023bdf8`), y el sorteo lo usa con `+0x20` y `+0x1cd0`
  (`0x14023b367`). Esos dos campos los rellena el constructor `0x14017c6d0`:
  `+0x20 = 0` y `+0x24 = 1`, el rango del sorteo, y `+0x1cd0 = 624`, el índice
  del generador (`0x14017d523`). Lo llaman los dos sitios que crean el
  renderizador, con `renderizador+0x10` (`0x140110ae1`, `0x14012b8b8`). Es el
  mismo puntero que el renderizador le pasa al cargador de la escena
  (`0x140181b82`). El contexto de la fábrica tiene el `+0x1510` que escriben ese
  constructor (`0x14017d014`) y el cargador (`0x1401872e8`). Las tres funciones
  ven el mismo objeto.
- **El reloj.** `contexto+0x130` es `renderizador+0x140`. Cada fotograma el
  renderizador suma el dt a un doble en `+0x148` (`0x14017fcca`) y deja su float
  en `+0x140` (`0x14017fce5`). Pasados 432 000 s lo vuelve a 0 (`0x14017fcef`),
  y al cargar la escena también (`0x140181b2a`, `0x140181b31`). Es el reloj que
  [el temblor](#el-temblor-de-cámara-también-estaba-en-el-motor-y-no-es-ruido)
  ya había leído como `[[escena+0xd8]+0x130]`.
- **Y WE le da nombre.** `remapinitialvalue` busca su `input` en una tabla de
  20 nombres (`0x140484e80`, `0x140260f50`) y despacha por el índice
  (`0x14023ce53`, saltos en `0x14023fab8`). El 9 es `runtime`, y su caso lee
  `[contexto+0x130]` (`0x14023d219`). El 11, `particlesystemtime`, lee
  `[instancia+0x3f0]` (`0x14023d230`): el reloj **del sistema** es otro campo.

Aquí el reloj de la escena es el `t` que recibe `we_psys_update`. Mientras el
arranque recupera `starttime`, vale de −`starttime` a 0. Qué reloj ven en WE
las partículas de esos segundos no está leído. Es la única suposición del port,
y solo toca a los sistemas con `starttime`.

### Cómo queda aquí

- **`weparticles.py`.** `_init_turbvel` escribe 13 floats: rapidez mínima y
  máxima, fase mínima y máxima, `timescale`, `scale`, `offset` (un ángulo),
  `forward[3]` y `right[3]`, con los defectos leídos. La rapidez por defecto la
  decide `wescene.ortografica(general)`, que `werender` le pasa a `cargar`. `up`
  y la rama de audio se ignoran: las 2 piezas con `audioprocessingmode: 3` se
  tratan como modo 0.
- **`src/weparticles.c`.** `gira_turbulenta` usa `snoise1`, portado de
  `0x14027b090` con la tabla de Perlin y el 0,395, y gira con Rodrigues:
  `right` normalizado y `forward` sin normalizar. Lo de `glm::rotate` está
  comprobado. El giro es el positivo, porque la fila 1 de la columna 0 es
  `x·y·(1 − c) + z·sen` (`0x1401e2653`). Y `0x140184440` es `M·v`, no `v·M`. La
  matriz del emisor no se aplica, igual que en `velocityrandom`: la velocidad
  vive en el espacio del sistema. El reloj de la escena viaja en `s->reloj`, y
  los hijos de evento lo heredan del padre. Con un `right` nulo WE dividiría por
  cero; aquí no gira, y el corpus no tiene ninguno. Lo enlazan `glexec.c` y
  `glexecutor.cpp`.
- **`desplazar_ruido` desaparece**, porque con la regla no hay punto de
  muestreo que desplazar. **`ESCALA_RUIDO` se queda solo para el operador
  `turbulence`**, que no se toca. El factor se calibró para esta pieza con
  nuestro ruido, cuando la coherencia del humo de Sniper Girl pasó de 0,08 a
  0,72. El operador lo comparte desde entonces, y su número se queda como está.

### Lo que cambia en el aspecto

Con la regla, las partículas que nacen a la vez salen paralelas y el chorro
serpentea con los segundos. El penacho que se abría era de nuestro ruido 3D.
`coherencia_turbvel.py` pasa `psysprobe` en t = 2 por los 271 `.psys` con la
pieza, enteros, con todas sus piezas, y los reparte como [La turbulencia no
turbulaba](#la-turbulencia-no-turbulaba):

| | chorro (c > 0,7) | penacho (0,3–0,7) | esparcido (< 0,3) | quietos (rapidez < 1) |
|---|---|---|---|---|
| base `a81d43a` | 114 | 73 | 80 | 4 |
| rama | **269** | 0 | 1 | 1 |

En el humo de Sniper Girl (1160677675), `s002` pasa de c = 0,27 a 0,98 y de 27,1
a 175,2 de rapidez. Es una de las 50 piezas sin rapidez declarada. El único
oráculo del aspecto es la lectura: ningún preview de humo se ha comparado, y la
regresión de luz solo caza apagados.

### Lo medido

Contra la base `a81d43a` y con Mesa, con los scripts de
`~/.local/state/wallpaperengine-bucle/ejecuciones/20261007-182522/medidas/`
(`repetir.sh`):

- **`verifica_exe.sh`**: **254 ok, 0 fallos**, los 154 de antes y 100 nuevos.
  Los nuevos cubren las direcciones de las dos secciones de arriba, el recuento
  de quién toca el bit 10, los 256 bytes de la tabla de permutación, que son los
  de Perlin, y el signo del giro.
- **`rumbo_turbvel.py --ejes`**: aísla la pieza con solo `lifetimerandom`, sin
  operadores y con la rapidez de salida del emisor a 0, y compara su rumbo con
  la regla por Monte Carlo. psysprobe se promedia sobre 32 semillas. Hace falta:
  `Flare_Flame` en t = 1 tiene unas 8 partículas vivas con c = 0,13, y ahí el
  rumbo de una sola siembra es ruido. **18 de 18** quedan a ≤ 15°, y la que más
  se aparta lo hace por 1,6°. Con la semilla del plan son 17 de 18, porque
  `Flare_Flame` en t = 1 da 22,2° contra 1,0°. Con el mismo script, la base da
  **6 de 18**.

  | fichero | `.psys` | rama, t = 1 / 2 / 3 | regla, t = 1 / 2 / 3 |
  |---|---|---|---|
  | `smoke2` | 1877658892/s000, s001, s002 | 97,5 / 94,0 / 93,4 | 97,6 / 94,0–94,1 / 93,4–93,5 |
  | `smoke1` | 2250845956/s002 | 91,5 / 91,7 / 91,8 | 91,5 / 91,6 / 91,8 |
  | `Flare_Flame` | 2937370591/s003 | −0,6 / 82,4 / 81,1 | 1,0 / 82,4 / 81,1 |
  | `Flare_Smoke` | 2937370591/s004 | 57,2 / 63,0 / 63,0 | 57,2 / 63,0 / 63,0 |

- **`rumbo_turbvel.py --sparks`**: `Flare_Sparks` (`forward 0 0 0`) da rapidez
  media **0 / 0 / 0**. En la base daba 73,5 / 75,4 / 75,2.
- **`rumbo_turbvel.py --sin-rapidez`**: las **50** piezas sin `speedmin` ni
  `speedmax`, aisladas igual, en t = 2. De los 98 `.psys` que las llevan,
  **95** quedan a ±10 % de 175.
- **`planes_iguales.py`**, las 129 con la hora congelada. Las **63** sin la
  pieza salen idénticas byte a byte. En las **66** con ella, el `plan.txt` es
  idéntico y las únicas líneas distintas son las 295
  `init turbulentvelocityrandom`. Los otros 513 `.psys` de esas escenas no
  cambian.
- **`test_weparticles.py`**: la prueba 9 nueva pasa, también con
  `LC_ALL=es_ES.UTF-8`. Cubre los defectos y `ortografica`, y pasa por el
  simulador cinco ráfagas con la fase y la rapidez fijas: los ejes por defecto,
  el `offset` como ángulo, el `right` sin normalizar, el reloj con `starttime`
  y el `forward` nulo. `mutacion_giro.sh` comprueba que la prueba falla sin el
  giro (8 discrepancias), sin el `offset` en el ángulo (2) y con el reloj del
  sistema (2).
- **`luz_turbvel.py`**: las 66 con la pieza, rama contra base: **66 de 66**
  renderizadas, 0 apagadas y 0 regresiones. La media se mueve entre −0,7 %
  (2658583633) y +9,7 % (3050043876); 3097749052 da entre −0,6 % y −0,9 %
  según la pasada, porque su base no es estable. La pasada de las 129 de
  `test_luminancia.py` contra una referencia de main da 129 renderizadas, 0
  apagadas y 0 regresiones.
- **`compila.sh`**: `make glexec psysprobe build` sin errores ni avisos en
  `src/weparticles.c`, y la tabla de `snoise1` está en `obj/glexec`, en
  `obj/psysprobe` y en la `.so`.

## `g_ParallaxPosition` es el punto P de la cámara, no el puntero con retardo

Quedaba en [Lo que queda](#lo-que-queda-1) del parallax de cámara: «lo más
probable es que WE suba el P normalizado —con la influencia y la y hacia
arriba—, y aquí se sube el ratón con retardo y la y hacia abajo», sin tocar
porque el `switch` que sube el uniform `0x6b` iba por una tabla de saltos que
nadie había encontrado. El corpus ya apuntaba a eso: de las 6 escenas con
`depthparallax`, `3077334064` y `3624164256` declaran
`cameraparallaxamount: 0` y aun así ajustan `cameraparallaxmouseinfluence`
(−0,2 y −0,27). Con amount 0 la cámara no se mueve; esa influencia solo pinta
algo si llega a `g_ParallaxPosition`. Es justo el argumento que [la sección
del puntero](#g_parallaxposition-es-el-puntero-con-retardo-y-nada-más) usaba
al revés —«si el amount lo escalara, esas dos habrían puesto un efecto caro
sobre una entrada muerta»—: lo que llega no es el amount, es la influencia.

La lectura lo confirma y además dice algo que la hipótesis no traía: con
`cameraparallax` apagado el uniform se queda en el centro, no sigue al ratón.

### Lo leído, con direcciones

Con el método de [Dónde guarda WE sus valores por
defecto](#dónde-guarda-we-sus-valores-por-defecto-y-cómo-se-leen). Las comprueba
todas `verifica_exe.sh`.

- **El nombre y su índice.** La cadena está en `.rdata`, `0x14048dad0`. Un
  inicializador estático arma la tabla nombre → índice de los uniforms del
  motor: `0x140003f0f` pone `0x6b` y `0x140003f17` carga la cadena
  (`g_PointerPosition` es el `0x69`, `0x140003ecf`). Al enlazar un shader, el
  nombre se busca en esa tabla (`0x1400db7c7`; `0x8c` es «no es del motor»,
  `0x1400db7d0`) y el índice se guarda como WORD en la lista de uniforms del
  pase (`0x1400dbc9b`).
- **El `switch`.** Cada pase recorre esa lista en `0x1400d83b3`: índice ≤ `0x8f`
  (`0x1400d8355`, `0x1400d83b8`) y salto de dos niveles, una tabla de bytes en
  `0x1400daaac` y otra de destinos en `0x1400da984` (`0x1400d83c1`,
  `0x1400d83ca`, `jmp rcx` en `0x1400d83d5`). Para `0x6b` el byte es `0x34` y
  el destino `0x1400d9e90`; para `0x69`, `0x32` y `0x1400d9df8`. Por eso no
  aparecía buscando un `cmp eax, 0x6b`: el `switch` compara con el tope y
  salta por la tabla.
- **El caso.** `0x1400d9e90..0x1400d9ea1`: toma el contexto de render
  (`[r14+0x8]`) y copia **ocho bytes de `contexto+0x9c`** al buffer de
  uniforms. El de `g_PointerPosition` copia `contexto+0x8c`, el ratón
  (`0x1400d9e02`).
- **Quién escribe `contexto+0x9c`.** El constructor del contexto lo pone a
  cero (`0x14017c78b`). El cargador de la escena, a **(0,5, 0,5)** al terminar
  de cargar, haya parallax o no (`0x1401886e3..0x1401886f4`). Y la
  actualización de la cámara (`0x1401891a0`), cada fotograma, pero **solo si
  `cameraparallax` está encendido**: `test [escena+0xe0], 0x100` en
  `0x140189b42`, y con el bit apagado salta a `0x140189cf3` sin tocarlo. Que
  el bit 8 de `+0xe0` es `cameraparallax` lo dice el lector de `general`: la
  cadena (`0x140488ae0`, cargada en `0x14019b0c8`) se registra en `+0xe0`
  (`0x14019b0e5`) con un accesor (`0x14019c850`) que hace `bts ecx, 8`
  (`0x14019c889`). No hay más escrituras de `+0x9c` en ese contexto.
- **Lo que escribe la cámara.** Es la P de [Lo que hace
  WE](#lo-que-hace-we): el objetivo con `m = mouseinfluence`
  (`0x140189b6f`), el ratón acotado a [0, 1] (`0x140189b8d`), la y como
  `1 − ratón.y` (`0x140189b95`), más el ojo (`0x140189c18`, `0x140189c24`),
  suavizada con `min(1, (1 − delay/3)·10·dt)` (`0x140189c3b`) y guardada en
  `escena+0x340/0x344` (`0x140189c79`, `0x140189c84`). Justo después la parte
  por el alto y el ancho del lienzo (`0x140189c98`, `0x140189ca9`), la acota a
  [0, 1] (`0x140189cba`) y la escribe en `contexto+0x9c` y `+0xa0`
  (`0x140189cbe`, `0x140189cc6`).

Queda así:

```
cameraparallax apagado:   g_ParallaxPosition = (0,5, 0,5), siempre
encendido:                g_ParallaxPosition = clamp(P / lienzo, 0, 1)
    P/lienzo = (0,5·(1 − m) + ratón.x·m,  0,5·(1 − m) + (1 − ratón.y)·m) + ojo/lienzo
```

con la y hacia **arriba**, la influencia, el suavizado de la cámara y, en
reposo, el centro. Sin `amount`, que no entra en P.

Dos marcas de `contexto+0x118` tocan el cálculo y no se sabe quién las pone:
con `0x200200` la influencia vale 0 (`0x140189b67`, `0x140189b7a`); con
`0x800` la x del ratón se voltea para P (`0x140189bac`) y la del uniform se
vuelve a voltear al escribirla (`0x140189cd5..0x140189cea`). Esa segunda es la
«marca que invierte la x» que quedaba apuntada, y para este uniform se anula:
`1 − (0,5·(1 − m) + (1 − x)·m)` es otra vez `0,5·(1 − m) + x·m`, sin el ojo.
Ninguna se modela.

### Lo que cambia en el corpus

Las 6 escenas con `depthparallax` tienen `cameraparallax` encendido —en
`2810252468` y `3624164256` por una propiedad del usuario que vale `true`—, así
que en las 6 pasa a valer la regla. Con el ratón en (0,2, 0,3) de la pantalla:

| escena | m | antes | ahora |
|---|---|---|---|
| `2349856302`, `3053927686` | 1 | (0,2, 0,3) | (0,2, 0,7) |
| `2810252468` | 0,7 | (0,2, 0,3) | (0,29, 0,64) |
| `3775394622` | 0,5 | (0,2, 0,3) | (0,35, 0,6) |
| `3077334064` | −0,2 | (0,2, 0,3) | (0,56, 0,46) |
| `3624164256` | −0,27 | (0,2, 0,3) | (0,581, 0,446) |

En las dos de influencia negativa el efecto iba en x al revés y, en las dos
direcciones, más fuerte de lo que pidió el autor: cinco veces en
`3077334064` (1/0,2) y 3,7 en `3624164256` (1/0,27). En las de influencia 1
la x ya estaba bien y la y iba al revés.
Con el ratón en el centro las seis dan (0,5, 0,5), antes y ahora.

### Cómo está hecho aquí

- **`posicion_de_parallax`** (`werender.py`) es la regla sin suavizar y sin el
  ojo. La usa `_fotograma` para poner `@PARALLAX_X/Y@` con el `--puntero`, y
  la influencia sale de la línea `parallax` del plan, redondeada igual que la
  lee el ejecutor.
- **`emit_pass`** decide el caso apagado: si la escena no tiene
  `cameraparallax` y el shader del pase lee `g_ParallaxPosition`, escribe
  `u2f g_ParallaxPosition 0.5 0.5` sin marcadores. En los pases que no lo leen
  se deja la línea como estaba; el valor ahí no pinta nada y así los planes de
  las escenas sin el efecto no cambian. En el corpus ningún pase cae en ese
  caso.
- **En vivo** (`glexecutor.cpp`), `@PARALLAX_X/Y@` es `m_camara` acotado a
  [0, 1]: el mismo P que ya movía las capas con `paralaje`, con su suavizado y
  el temblor. La exponencial propia `1 − exp(−dt/retardo)` y `m_parallax`
  desaparecen. Con el retardo de 2 s de cuatro de las seis escenas el efecto
  llega ahora 6,7 veces antes (3,33 por segundo contra 0,50); en
  `3053927686`, con 0,55 s, 4,5 veces (8,17 contra 1,82), y en `3624164256`,
  con 0,11 s, casi igual (9,63 contra 9,09).
- `glexec.c` no cambia: offline los marcadores los pone Python.

### Lo medido

Contra la base `afd62c6` y con Mesa, con los scripts de
`~/.local/state/wallpaperengine-bucle/ejecuciones/20261007-231823/medidas/`
(`repetir.sh`):

- **`verifica_exe.sh`**: **57 ok, 0 fallos**: la cadena, el índice `0x6b`, el
  enlace, el `switch` con sus dos tablas leídas byte a byte, el caso, el
  constructor, el cargador, el bit de `cameraparallax` y la actualización de
  la cámara hasta las dos escrituras.
- **`parallax_plan.py`**: arma el plan de fotograma de las 6 escenas con
  cuatro posiciones del ratón —sin puntero, (0,2, 0,3), (0,8, 0,9) y
  (0,1, 0,75)— y compara el `u2f g_ParallaxPosition` de los pases que lo leen
  con la regla calculada aparte desde el `scene.json` y el `project.json`:
  **24 de 24** a 1e-4, las dos de influencia negativa incluidas. Imprime
  también, por escena, la influencia, el ritmo del suavizado de WE contra el
  de la exponencial que había y la amplitud del temblor.
- **`test_werender.py`**: `prueba_posicion_de_parallax`, nueva, mira la
  función, el plan de `3077334064` y `3624164256` y `3624164256` con la
  propiedad que enciende su parallax a `false`, que tiene que dar el centro.
  `mutaciones_e.sh` la pasa sin tocar (pasa), quitando la influencia (falla,
  4 quejas) y con la y al revés (falla, 6 quejas).
- **`planes_iguales.py`**: las 129 con `--emit-plan`, sin puntero y con la
  hora congelada: **1131 de 1131** ficheros idénticos (129 `plan.txt` y
  1002 `.psys`), también en las seis del efecto: sin ratón el valor es el
  centro, como antes.
- **`test_luminancia.py obj/glexec --referencia`** con una referencia de main
  (`luz_main.json`), Mesa en las dos pasadas: **129/129** renderizadas,
  **0 apagadas, 0 regresiones**. 118 dan la misma media; las 11 que cambian
  son todas escenas con reloj (`reloj` en el plan), y la pasada no congela la
  hora. Las seis del efecto, idénticas: sin ratón el plan no cambia.
  `luz_f.sh` reanaliza las dos pasadas y renderiza además las seis con el
  ratón en (0,2, 0,3), base contra rama: ninguna apagada; la media se mueve
  entre −2,5 (`2349856302`, de 90,05 a 87,54) y +0,97 (`3624164256`).
- `make build` y `make glexec` sin errores ni avisos nuevos.

### Lo que queda

- **El ojo, offline.** WE suma a P el ojo de la cámara, que en estas escenas
  solo lleva el temblor. En vivo entra, porque `m_camara` ya lo lleva; offline
  no, porque `_fotograma` lo pone Python y la curva vive en `src/wetemblor.c`.
  De las seis solo `3053927686` tiembla, con 10,8 px de amplitud: hasta
  0,0028 del ancho y 0,005 del alto en el uniform.
- **Las marcas `0x200200` y `0x800` de `contexto+0x118`**, de origen sin leer.
- **Que se vea en el escritorio**: el efecto se mueve ahora con la influencia
  y la y del autor, y en las de 2 s llega mucho antes. Ningún oráculo offline
  lo dice; hay que mirarlo en vivo.

## El parallax sigue al ratón en tiempo real: el cursor lo da KWin, y el retardo de WE se queda para el temblor

Visto en el escritorio con `2220826239` (parallax de cámara, retardo 1,8,
influencia −0,69): la escena no seguía al ratón; había que esperar segundos y
luego saltaba de golpe. Dos causas, y la que importaba no era la primera que
se arregló.

### La que importaba: al fondo no le llegaba el ratón

Medido con un registro temporal en `synchronize()` (sincronías y posiciones
nuevas por segundo): el motor dibujaba a ~42 fps con 23,5 ms de GPU, pero le
llegaban **de 1 a 5 posiciones por segundo**, con huecos de hasta 576 ms, todas
con y ≈ 0,96 —pegadas al panel— y con `hovered` siempre a false. Moviendo el
ratón por el centro de la pantalla no llegaba nada.

- Primero se colgó el `HoverHandler` de la raíz de la ventana en vez de la
  escena: la capa de iconos de Plasma es hermana de encima y acepta el hover,
  y en Qt 6 el hover aceptado no baja a los hermanos, solo sube a los
  ancestros (comprobado con `qmltestrunner`: el handler de la escena, 0
  eventos; el de la raíz, 20 de 20). **No cambió nada en el escritorio**: la
  misma medida, 1 a 5 por segundo y `hovered` a false.
- La pila de KWin lo explica: cuatro ventanas maximizadas (1920×1168) encima
  del escritorio. Con «Mostrar el escritorio» KWin las aparta, pero a la
  ventana del escritorio el puntero casi no le llega. Ningún arreglo dentro de
  plasmashell puede con eso: en Wayland una ventana ve el ratón cuando el
  compositor se lo da.

Wallpaper Engine en Windows lee el cursor **global**. Aquí lo tiene KWin:
`CursorKWin` (`src/escritorio.cpp`) carga al arrancar un script de KWin
(`wallpaperengine-cursor`, escrito en `$XDG_RUNTIME_DIR`) que escucha
`workspace.cursorPosChanged` y llama por D-Bus a `posicion(x, y)` del objeto
`/WallpaperEngine/Cursor` de esta conexión —como mucho cada 8 ms y siempre con
la última—. `SceneView` lo pasa a su pantalla y, desde la primera posición,
ignora el `HoverHandler`, que queda de respaldo si KWin no responde. Ojo: KWin
manda **enteros** (`cursorPos` es un `QPoint`); con solo la firma `(dd)` D-Bus
no casaba ningún slot. Están las dos.

Medido después, en el escritorio y con la misma escena: **18 a 40 posiciones
nuevas por segundo** moviendo el ratón —el ritmo de los fotogramas, ~41—, por
toda la pantalla y con `presente=1`. Y el fondo sigue al ratón también por
debajo de las ventanas, como en WE: para los 123 sistemas de partículas que lo
persiguen, «presente» es ahora «en esta pantalla».

### La otra: el retardo de WE

Con el ratón llegando, la cámara seguía yendo **detrás** de él por el
suavizado que se copió de WE (`(1 − delay/3)·10·dt`, sección de
`cameraparallax`), y su respuesta a un salto del ratón es esta:

| | 95 % del camino, a 60 fps |
|---|---|
| WE, `cameraparallaxdelay` 0,1 (108 de las 129) | 300 ms |
| WE, `cameraparallaxdelay` 2 (4 de las 6 con `depthparallax`) | 883 ms |
| ahora: exponencial de 25 ms | 83 ms (63 % en 25 ms) |

Es una **decisión del usuario, no una lectura del motor** (2026-10-08): el
parallax tiene que seguir al ratón en tiempo real y suave, aunque WE lo
retrase. Así que en vivo el punto de la cámara se parte en dos:

- **la parte del ratón** (centro y ratón según la influencia) lleva solo
  `1 − exp(−dt/0,025)`, independiente de los FPS. Lo justo para que los
  eventos del ratón, que no llegan al ritmo del refresco, no hagan temblar la
  escena;
- **la parte del temblor** (`camerashake`) sigue con el suavizado de WE y el
  retardo de la escena. El filtro es lineal: suavizar las dos por separado y
  sumarlas deja el temblor de las 6 escenas exactamente como estaba.

`g_ParallaxPosition` sale del mismo punto, así que el `depthparallax` también
deja de ir retrasado. Offline no cambia nada: allí el punto es el `--puntero`,
sin suavizar, y `glexec.c` ya ignoraba el retardo. Está en `avanzaPuntero`
(`src/glexecutor.cpp`), con `RATON_TAU`. Lo que no se mide offline: cómo se
siente en el escritorio.

## Partículas con perspectiva: el bit 0x4 del `flags` del sistema es otra cámara, no otra simulación

**De dónde se partía.** El JSON de cada sistema de partículas trae un `flags`
de nivel de SISTEMA que se descartaba entero: `weparticles.py` solo leía el de
los puntos de control y el del renderer. Lo encienden presets como
`snowperspective`, `rainperspective`, `snowstorm`, `ash`, `leaves1..5` o
`starfield`, y **todos** se mueven en z —por el emisor (`distancemax` ×
`directions` con componente z), por la velocidad o por la gravedad—. Con la
proyección ortográfica de siempre esa z no contaba: la nieve salía plana y el
`starfield` de `1927028828`, cuyas estrellas solo avanzan en z, no se veía.

### Qué bit es cuál: la tabla del editor

El editor registra cada casilla del sistema con su máscara y su cadena de
locale (`bin/wallpaperui.exe`, `0x1401b6cb5..0x1401b6e10`):

| máscara | dirección | cadena (`.rdata`) | en el corpus |
|---|---|---|---|
| `0x1` | `0x1401b6cb5` | `ui_editor_properties_worldspace` (`0x140ada440`) | 93 sistemas en 28 escenas |
| `0x2` | — | no tiene casilla | 89 sistemas en 32 escenas |
| `0x4` | `0x1401b6cff` | `ui_editor_properties_perspective`, «Perspective rendering» (`0x140ad8488`) | **153 sistemas en 58 escenas** |
| `0x8` | `0x1401b6d32` | `ui_editor_properties_disable_color_overrides` (`0x140ada410`) | 0 |
| `0x10` | `0x1401b6dfe` | `..._disable_speed_overrides` (`0x140ada4c0`) | 0 |
| `0x20` | `0x1401b6d65` | `..._disable_count_overrides` (`0x140ada490`) | 0 |
| `0x40` | `0x1401b6d98` | `..._disable_lifetime_overrides` (`0x140ada460`) | 0 |
| `0x80` | `0x1401b6dcb` | `..._disable_size_overrides` (`0x140ada4f0`) | 0 |

La casilla de perspectiva solo se ofrece si la escena es ortográfica (el bit 3
de `[[rsi+0x10]+0x140]`, `0x1401b6cdb..0x1401b6cde`). En el corpus el `flags`
del sistema vale 0, 1, 2, 3, 4, 6 o 7: ningún bit de los «overrides».

### Lo que hace WE, con direcciones

Se lee con el método de [los valores por
defecto](#dónde-guarda-we-sus-valores-por-defecto-y-cómo-se-leen) sobre el
`wallpaper64.exe` instalado. `verifica_perspectiva.sh` comprueba cada fila,
instrucción a instrucción —121 comprobaciones en el motor y 28 en el editor—;
vive con las medidas de la tarea, en
`~/.local/state/wallpaperengine-bucle/ejecuciones/20261008-135219/medidas/`,
y se ejecuta desde la raíz del repositorio (`sh …/verifica_perspectiva.sh
[a|b]`). `repetir.sh`, al lado, pasa todas las medidas.

| qué | dónde | lo que hace |
|---|---|---|
| lector del sistema | `0x1401c5490` | `r13` es el descriptor (`0x1401c54eb`). Lee `flags` (`.rdata 0x14048f4cc`, `0x1401c55e4`) como entero (`0x1401c56e4`), se queda con el **byte bajo** (`movzx`, `0x1401c56e9`), 0 si falta, y lo guarda en **descriptor+0x8** (`0x1401c56f0`) |
| creación | `0x14022cc5a..0x14022cc8f` | descriptor de 0x1e0 bytes, lo rellena el lector y `0x1401c4220` lo copia a **sistema+0x18**: el `+0x8` pasa a **sistema+0x20** (`0x1401c423d`/`0x1401c4240`) |
| dibujo del sistema | `0x1402366f0` | `[sistema+0x20] & 1` («worldspace», `0x14023670c`) cambia la matriz de modelo por la del contexto `+0xaf0`. Y **`([sistema+0x20] >> 2) & 1`** (`0x140236761..0x140236767`): con el bit apila la vista (`[ctx+0x38]`, `0x14023677f`) y la proyección (`[ctx+0x40]`, `0x1402367b3`), llama a `0x1401e5b60` (`0x1402367d8`) y al acabar las desapila (`0x140236ac6..0x140236add`). Los hijos se dibujan después, cada uno con su bit (`0x140236bb7`) |
| la cámara nueva | `0x1401e5b60` | fov = `[ctx+0x110]`, en radianes. **`d = 1 / (tan(fov/2) · P[1][1])`** con P la proyección vigente, la ortográfica de la escena (`0x1401e5b93..0x1401e5bb4`). Lejano **max(15000, d + 1000)** (`0x1401e5ba0..0x1401e5bc8`), cercano **5** (`0x1401e5c20`). La vista pierde el centro de la ventana ortográfica —`[ctx+0x84] · [ctx+0xf8]` en x, `[ctx+0x88] · [ctx+0xfc]` en y (`0x1401e5bd3..0x1401e5c1b`)— y su z pasa a ser **−d** (`0x1401e5c28`). Aspecto `[ctx+0x74] / [ctx+0x78]` (`0x1401e5c2d..0x1401e5c39`), y la proyección la hace la entrada **+0x10 del dispositivo** (`0x1401e5c47`). Con `[ctx+0x118] & 0x800` niega la fila x (espejo global; no se emite) |
| el dispositivo | vtable `0x140485b90` | `+0x10` es `0x14009a360`: `XMMatrixPerspectiveFovRH` de DirectXMath (sus `assert`, `0x14009a3b8`; la fila de w `(0, 0, 0, −1)`, `0x14009a5db`) con la **z invertida**: `cerca / (lejos − cerca)` (`0x14009a513..0x14009a527`) y `· lejos` (`0x14009a57b`), el cercano a 1 y el lejano a 0. `+0x18` es la ortográfica, `0x14009a630` |
| el contexto | `0x14017c6d0` | pilas de modelo, vista y proyección en `+0x30`, `+0x38`, `+0x40` (`0x14017c723..0x14017c739`). Su tamaño de destino, en float, en `+0x74`/`+0x78` (`0x14017f222`/`0x14017f22d`, vistos desde 0x10 bytes antes: allí su dispositivo `+0x1518` es `+0x1528`) |
| ancho y alto | `0x1401875df..0x1401875fb` | el cargador marca la escena como ortográfica (bit 3 de `+0xe0`, ver `wescene.ortografica`) y pone el ancho y el alto de `orthogonalprojection`, enteros, en `[ctx+0x84]`/`[ctx+0x88]` |
| la cámara ortográfica | `0x140183d57..0x140183e95` | cada fotograma: el centro de la ventana, en fracción del lienzo, a `[ctx+0xf8]`/`[ctx+0xfc]` (`0x140183d96`, `0x140183dc1`) —0,5 sin márgenes—, **el fov efectivo de la escena en radianes a `[ctx+0x110]`** (`0x140183dc9..0x140183dd9`) y `OffCenter(izq, der, abajo, arriba, nearz, farz)` del dispositivo `+0x18` (`0x140183e95`) |
| qué fov | `0x140189271..0x1401892c4` | el fov efectivo (`escena+0x148`) es **`perspectiveoverridefov` (`+0x144`) si la escena es ortográfica** y `fov` (`+0x140`) si no. En una ortográfica el nodo de cámara no lo pisa (`0x1401893b9`). Se acota a **[0,1, 179,9]** (`0x140189b12..0x140189b4c`) |
| sus defectos | `0x140186d5c..0x140186d72` | el constructor de la escena: `fov` 50, **`perspectiveoverridefov` 95**. Los campos de `general`: `fov` → `+0x140` (`0x14019aa21`), `perspectiveoverridefov` → `+0x144` (`0x14019aaa5`), `nearz` → `+0x14c`, `farz` → `+0x150` |
| en el editor | `0x1401aa34d..0x1401aa4a8` | el «FOV» de las opciones de cámara edita `perspectiveoverridefov` en una escena ortográfica y `fov` en una en perspectiva |

Así que, para un sistema con el bit en una escena ortográfica de alto `h`:

- el ojo está a **`d = h / (2 tan(fov/2))`** del lienzo, la distancia a la que
  el alto del lienzo llena el fov, y mira a su centro;
- `fov` es `perspectiveoverridefov`, 95° si no se declara (46 de las 58
  escenas; de las demás, 6 declaran 95, 4 90 y 2 30:
  `censo_perspectiva_escena.py`, abajo);
- **el plano z = 0 cae en el mismo píxel que en ortográfico**, y lo que tiene
  z positiva **se acerca al ojo**: posición respecto al centro y tamaño se
  multiplican por `d / (d − z)`. Con `z ≥ d − 5` queda detrás del plano
  cercano y el recorte lo tira. La z crece hacia el espectador porque la
  cámara de estas escenas mira hacia −z: en las 129, `center` está una unidad
  por debajo de `eye` en z (`censo_perspectiva_escena.py`).

### Cómo está hecho aquí

No hay que tocar C. El vértice de partícula de WE (`genericparticle.vert`)
arma el quad en el espacio del sistema y lo proyecta con
`g_ModelViewProjectionMatrix`, así que una matriz proyectiva completa basta
para que lo cercano salga más grande y apartado; los dos ejecutores la
heredan del plan.

- `weparticles.py` lee el bit en `Sistema.perspectiva` y escribe
  `perspectiva 1` al final del `.psys`, solo cuando está. El simulador no la
  usa, y `we_psys_load` se salta en silencio las palabras que no conoce: un
  `.so` anterior lee el fichero igual.
- `werender.py`: `fov_de_perspectiva(general)` y
  `particle_mvp_perspectiva`, que es `proyección · vista · particle_world` con
  las cuentas de arriba; `emit_pass` la usa en vez de `particle_mvp` para esos
  pases si la escena es ortográfica. La z de recorte va con la convención de
  GL y no con la z invertida de WE: cambia la profundidad, que aquí no se
  prueba; x, y, w y los planos de recorte son los mismos.
- `obj/psysprobe` da ahora también el rango en z.

La nieve de `1237434258` (`snowperspective`: `distancemax 900`, `directions
0.6 0.03 1`, `sign 0 0 1`) tiene a los 10 s 299 copos con z de 1 a 717, y con
un lienzo de 992 de alto y 95° (no declara `perspectiveoverridefov`) el ojo
está a 454,5: 48 de los 299 quedan detrás del plano cercano, y los que se le
acercan crecen hasta 6,4 veces (`tamano_copos.py`, abajo). Que en WE se vea
igual lo respalda solo la lectura: no se ha comparado con WE corriendo.

### Lo medido

Todo con las medidas de la tarea (`repetir.sh` las pasa todas):

- **Direcciones**: `verifica_perspectiva.sh`, 149 comprobaciones —121 en
  `wallpaper64.exe`, 28 en `wallpaperui.exe`—, 0 fallos. Con tres
  expectativas cambiadas a propósito (una instrucción, una constante y una
  cadena), falla en esas tres y solo en esas.
- **El bit llega donde debe** (`planes_perspectiva.py <repo> c`): el censo
  cuenta 153 sistemas con el bit en 58 escenas, y los planes de la rama
  llevan 140 `.psys` con `perspectiva 1`. Los 13 que faltan son los que
  `werender` no dibuja por visibilidad: 6 con `visible: false` (`ash` en
  `2128224409` y dos en `2527248676`, tres `leaves5` en `2870014907`), 2
  `rainperspective` de `2658583633` atados a `rainatmosphereonoff`, apagado,
  y en `3238423642` el `star trail-W` atado a una propiedad apagada, sus dos
  hijos `star trail-R`/`-G` que heredan su invisibilidad, y los dos presets
  del «Getsuga Tenshou Mouse Trail», cuyo `visible` es una condición sobre
  `cursortrail` con la copia a false.
  Ningún `.psys` de main lleva la línea.
- **Sin el bit no cambia nada** (`planes_perspectiva.py <repo> d`): las 71
  escenas sin ningún sistema con el bit dan planes, `.psys`, texturas y
  shaders **idénticos byte a byte** a los de main, y en las 58 solo cambian
  los `.psys` marcados (una línea más al final) y las matrices de los pases
  que los dibujan —la MVP y la `g_ModelMatrix`, la `g_ViewProjectionMatrix`
  y la inversa que salen de ella—. Ojo al repetirlo: los relojes hornean en
  el plan la hora a la que se emite, y sin fijarla un minuto que cambia entre
  main y la rama daba `text*.bin` distintos; la medida emite con
  `datetime.now()` fijo.
- **El contrato** (`prueba_particulas_en_perspectiva` en
  `test_werender.py`): en z = 0 la partícula cae en el mismo píxel que en
  ortográfico (tres puntos, fov 95 y 30, objeto girado, escalado y con
  `origin` en z), a z ≠ 0 posición y tamaño van por `d / (d − z)`, detrás del
  ojo w < 0, el fov por defecto y su cota, y el plan del `starfield` lleva
  `perspectiva 1` y MVP proyectiva justo en el mismo `.psys`, y el de
  `1828218519`, sin el bit, ninguna de las dos. Con
  `particle_mvp_perspectiva` devolviendo la ortográfica falla con 11
  problemas.
- **La cámara del corpus** (`censo_perspectiva_escena.py <repo>/tools`): 58
  escenas y 153 sistemas con el bit; `perspectiveoverridefov` sin declarar en
  46 escenas, 95 en 6, 90 en 4 y 30 en 2; renderers: 117 `sprite`, 30
  `spritetrail`, 3 `rope` y 3 `ropetrail`; y en las 129 escenas `center`
  menos `eye` en z vale −1.
- **Los copos** (`tamano_copos.py <repo> 10`): la escena tiene un lienzo de
  992 de alto y 95°, así que el ojo está a 454,5; a los 10 s hay 299 copos con
  z de 1 a 717, 48 de ellos detrás del plano cercano. Simulados con el
  simulador de los ejecutores y proyectados con la MVP del plan, en main 226
  copos en el lienzo, todos a 1,000 px por unidad de tamaño, coeficiente de
  variación del tamaño proyectado 0,514; en la rama 132 delante del ojo, de
  1,001 a 6,410 px por unidad (Spearman con z 1,000) y coeficiente de
  variación 0,642.
- **La luz** (`luz_g.py`, sobre `luz_main.json` y `luz_rama.json`, las dos
  pasadas de `test_luminancia.py` con Mesa): 129/129 renderizan, 0 apagadas, 0
  regresiones. Dentro de las 58 cambian 27, entre −1,3 % (`3362719513`) y
  +1,2 % (`1927028828`, las estelas del `starfield`). Fuera de las 58 cambian
  seis, como mucho 0,18 de media (una solo en el p99), y las seis son
  escenas con reloj; repetidas con la hora fija —`datetime.now()` en Python
  y `time()` en `glexec` con un `LD_PRELOAD`—, main y la rama dan la misma
  luz en las seis.
- `test_weparticles.py` y `test_werender.py` pasan enteros; `make build` y
  `make glexec` compilan.

Las tres escenas de muestra a `--time 10`: en `1237434258` los pétalos y los
copos cercanos salen más grandes y variados; en `2114511766` (hojas) apenas
cambia; en `1927028828` aparecen las estelas radiales que salen del centro,
que en main no se veían.

### Lo que queda

- **El bit 0x1, «worldspace»** (93 sistemas en 28 escenas): es el
  `[sistema+0x20] & 1` que [`flags: 2` no coloca el
  emisor](#flags-2-no-coloca-el-emisor-es-una-partícula-por-fotograma-y-al-cursor-lo-lleva-el-punto-de-control)
  dejó sin saber qué campo lo encendía. Al dibujar cambia la matriz de modelo
  por la del contexto `+0xaf0` (`0x14023670c..0x140236748`); al emitir gira
  el sorteo con el punto de control, y al mover el punto del cursor lo pasa
  por la matriz del sistema. Solo se nota si el objeto se mueve con el
  tiempo, y offline eso pasa en 2 objetos con `origin`/`angles` por script.
  No se ha tocado.
- **El bit 0x2** (89 sistemas en 32 escenas): no tiene casilla en el editor
  y no se ha buscado dónde lo prueba el motor.
- **Lo que esta cámara no lleva**: los márgenes de la ventana ortográfica
  (`[ctx+0xf8]` es 0,5 sin ellos; salen del zoom y del parallax, que aquí se
  aplican al componer), el espejo `[ctx+0x118] & 0x800`, y el aspecto, que en
  WE es el del destino (`[ctx+0x74]/[ctx+0x78]`) y aquí el del lienzo: son el
  mismo si WE dibuja la escena a su tamaño, y eso no se ha leído.
- **Las estelas y las cintas** (30 `spritetrail` y 6 `rope`/`ropetrail` de los
  153, según `censo_perspectiva_escena.py`) orientan su anchura con
  `g_EyePosition`, que sigue siendo el ojo ortográfico: si WE les da el de
  esta cámara no se ha leído. Los pases iluminados tampoco cambian el ojo.
- La turbulencia (`turbulentvelocityrandom`) ya distingue ortográfica de
  perspectiva por ESCENA (el bit 3 de `+0xe0`), no por este bit, y no se ha
  tocado.
