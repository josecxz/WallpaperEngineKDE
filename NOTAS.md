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
  werender.py                renderizador offline (escena -> PNG)
  glexec.c                   ejecutor de planes headless (EGL surfaceless)
  glslcheck.c                compila shaders con el driver real (EGL surfaceless)
  test_wetex.py              regresión de wetex
  test_wemdl.py              regresión del decodificador de mallas
  test_weglsl.py             valida la inferencia contra el corpus que compila
  test_weshader.py           regresión del traductor (combos por defecto)
  test_wescene.py            regresión end-to-end (combos reales)
  test_weparticles.py        contrato entre weparticles.py y weparticles.c
  test_luminancia.py         regresión de LUZ: renderiza y mide cuánta sale
src/
  glexecutor.cpp/.h          ejecutor de planes en vivo (port de glexec.c)
  weparticles.c/.h           simulador de partículas, COMPARTIDO por los dos
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

**La dirección concreta la pone nuestro ruido, no el wallpaper**, y eso no tiene
arreglo: el formato no trae ningún campo de dirección ---solo `scale`,
`speedmin`/`speedmax` y un `offset` que desplaza el punto de muestreo--- y WE no
publica su función de ruido. Lo que sí vuelve a depender del wallpaper es el
carácter del efecto. Si hiciera falta apuntar un penacho concreto, la palanca
del propio formato es ese `offset`: medido sobre este humo, (0,0,0) da −12,6°,
(5,0,0) da −48,5° y (10,10,0) da +120,5°.

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
| `right`/`up`/`forward` en `turbulentvelocityrandom` | 4 c/u | los ejes de la turbulencia |
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
3. **Texto** — 159 objetos en 28 escenas. Se lee el campo, no se rasterizan
   glifos. Los materiales de fuente MSDF, que faltaban, aparecieron al pasar a
   la instalación real.
4. **Reproducir vídeo** de verdad, en vez del fotograma congelado: 3 escenas
   con textura de vídeo y los 15 wallpapers de tipo vídeo de la biblioteca.
5. **Elegir la GPU que renderiza** (ver abajo).
6. ~~Reflejos y luces de tubo~~ **hecho**: el reflejo solo pedía la pirámide de
   mipmaps del buffer de escena, y el tubo venía en `controlpoint` desde el
   principio. Del sistema de iluminación quedan los **focos** y las
   **direccionales**, que el shader declara y la biblioteca no usa: sin una
   sola en el corpus no hay con qué verificar su orientación, así que una
   escena que traiga alguna se sigue dibujando plana.
7. **Audio reactivo**: `g_AudioSpectrum16/32/64` en 33 variantes de shader y
   `audioprocessing*` en ~50 usos de partícula.
8. **El puntero de verdad**: hoy se emite el centro fijo. Desbloquea el
   parallax y los 111 usos de `controlpointattract`.

Y un fallo de uso, sin arreglar: **cambiar el fondo con el escritorio tapado no
recarga el motor**. `recargar()` intercambia el plugin pero el `SceneView` no se
reinstancia, y hace falta reiniciar plasmashell. Visto con una escena en la que
la resolución no cambia nada, así que no es de la fase 2.

De partículas ya no queda vocabulario: los tres cabos —el corro, `remapvalue` y
`orientation`— están cerrados y contados arriba. Lo que sigue fuera de la
simulación son tres cosas, ninguna bloqueante:

- `controlpointattract` sobre puntos atados al cursor (**111 de 136 usos**):
  entra solo en cuanto el motor en vivo sepa dónde está el puntero. No es
  trabajo aparte.
- Un `rope` con `orientation: upright`, **1 sistema**: la anchura de la cinta la
  monta nuestro constructor de vértices, perpendicular al camino, y ese la
  quiere vertical.
- Dos emisores extra en **1 sistema**: WE permite varios y el corpus solo tiene
  ese; tomar el primero es preferible a sumarlos mal.

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
