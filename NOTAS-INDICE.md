# Índice de `NOTAS.md`

`NOTAS.md` son 6524 líneas en orden **cronológico**: cada sección es una caza
—el síntoma, las hipótesis descartadas y la medida que cerró el caso—. Ese
orden es parte del valor y por eso no se trocea el fichero; lo que faltaba era
poder entrar por tema.

Este índice agrupa las secciones por subsistema y da la línea donde empieza
cada una. **Leer solo el trozo que hace falta:**

```sh
sed -n '1862,1899p' NOTAS.md      # "El humo que no se apagaba"
grep -n '^#\{2,3\} ' NOTAS.md     # si un número no cuadra, el título manda
make indice                       # reescribe los números desde NOTAS.md
```

---

## Empezar aquí

- `10` **Regla de trabajo: nada específico de un wallpaper** — por qué un caso especial por escena no se puede validar y siempre tapa la causa. Léelo antes de arreglar nada.
- `47` **Regla de trabajo: `wectl` no crece por iniciativa propia** — el CLI no se amplía si no se pide; de dónde salió la regla y por qué un comando no se puede medir como se mide el motor.
- `77` **Estado** — qué corre hoy en vivo, sobre qué versión de Plasma, y por qué el corpus pasó de 125 a 129 escenas.
- `352` **Estructura** — el árbol del repositorio con una línea por fichero.
- `1414` **Uso** — `make install` / `reload` / `status`, y cómo activar el plugin sin pasar por la GUI.
- `3852` **Lo siguiente** — la lista de pendientes por impacto, con lo ya hecho tachado.

## Arquitectura y plataforma

- `325` **Decisión de arquitectura: por qué un plugin QML y no layer-shell** — las dos rutas de Wayland probadas empíricamente y por qué `wlr-layer-shell` quedó descartada en KWin.
- `98` **El motor en C++ — `src/`** — QRhi no acepta GLSL en texto y nuestros shaders se generan en ejecución: de ahí `beginExternal()` y el backend obligatorio OpenGL. Incluye las tres cosas que costaron (framebuffer de Qt, `mv` en vez de `cp`, `Q_ARG` guarda un puntero).
- `1439` **Notas de plataforma** — `Screen.refreshRate` llega `undefined`; `FrameAnimation` late en el hilo de render y se para solo cuando Qt deja de componer.
- `311` **Hito 0 (completado)** — el primer color sólido detrás de los iconos, con el reloj sincronizado al refresco.
- `2784` **Nota de rendimiento para el port a C++** — qué extensiones de compresión de textura expone esta GPU.
- `3973` **Elegir la GPU que renderiza** — la iGPU se come el 49,6 %; los dos caminos para mover el fondo a la dedicada y el riesgo que puede tumbar el segundo.
- `10219` **El fondo en la dedicada: el plan en otra GPU y el fotograma por la CPU** — la sonda del dmabuf dice que no; el plan en otro contexto del mismo hilo, leído por la CPU: la integrada de 33 ms a 1,2 ms por fotograma y 148 planes sin diferencias.
- `10226` **La sonda: NVIDIA no escribe nada que la integrada sepa leer** — la textura sale en bloques y Mesa la rechaza; un dmabuf LINEAR, NVIDIA solo lo muestrea. La CPU: 1,2 + 2,0 ms a 2560×1440.
- `10245` **El camino: otro contexto en el mismo hilo** — libglvnd reparte GL por hilo; qué GPU se elige, qué estado EGL se guarda (la API también) y por qué `~SceneRenderer` libera en el contexto propio.
- `10334` **El mando: `wectl gpu`, en caliente** — `DedicatedGpu` por la API de Plasma; el plan se suelta y se recarga en la otra GPU sin reiniciar, y los dos fallos que eso destapó (sampler y consultas que sobrevivían al contexto, contadores que se sumaban).
- `10364` **¿Duerme la dedicada? Steam, btop y el audio HDMI** — la carga de btop con el fondo tapado era Steam y el propio btop (NVML la despierta); la dedicada no se suspende nunca por `audio-fix.conf` (`power_save=0` del audio HDMI). Y el driver no suelta sus descriptores hasta que muere el proceso.
- `10602` **El fondo en Hyprland: el mismo módulo como superficie layer-shell** — `hyprland/main.qml` pide una capa `background` por monitor con `layer-shell-qt`; la pausa y el cursor salen del IPC de Hyprland (`src/hyprland.cpp`), el plan se recarga al cambiar el fichero y `recargar()` de `wectl` no busca plasmashell si el fondo de Hyprland está vivo.
- `10612` **El anfitrión** — una `Window` por monitor con `org.kde.layershell` (`LayerBackground`, cuatro anclas, `exclusionZone: -1`); se muestra ya configurada. Medido: nivel 0 bajo waybar, plan en NVIDIA y composición en Intel.
- `10629` **La pausa y el cursor: el IPC de Hyprland** — `.socket2.sock` dispara la revisión de `j/monitors` + `j/clients` con la rejilla de `VentanasEncima`; `j/cursorpos` cada 16 ms, asíncrono, solo sin pausa. El espacio especial abierto tapa el monitor.
- `10660` **Cambiar de plan sin plasmashell** — `Loader` + `VigiaArchivo` (inodo y fecha, porque `wectl` renombra el directorio); `shuffle` probaba cinco escenas por tick hasta que `recargar()` aprendió a ver el pid del fondo de Hyprland.
- `10680` **`wectl` en Hyprland** — las mismas órdenes; el fondo es la unidad transitoria `wallpaperengine-hyprland` porque un hijo del servicio oneshot de la rotación moriría con él; `gpu` reinicia la unidad y se guarda en `~/.config/wallpaperengine/hyprland.json`.
- `10713` **Dos monitores: las dos capas iban al primero** — layer-shell-qt elige monitor con `LayerShell.Window.screen`, no con `Window.screen`, y `Qt.application.screens` da `QQuickScreenInfo`: `Hyprland.pantalla` busca el `QScreen` por nombre. Probado con HDMI y con una salida `headless` en caliente.
- `10743` **Un wallpaper distinto en cada pantalla** — `wectl pantallas mismo|independiente` (solo Hyprland): un plan por monitor en `plugin/contents/pantallas/`, `VigiaArchivo.existe` para caer al compartido, `shuffle` reparte de la misma bolsa y `set` pone el mismo en todas.
- `10750` **Cómo** — `preparar` con destino, `--planes` en el anfitrión, el `Loader` que solo recarga el plan de su monitor y el `existe` hacia abajo cuando `set` borra los propios.
- `10777` **La resolución, que en Hyprland no se leía** — sin `kscreen-doctor` los planes salían al lienzo del autor (hasta 7680×4320); ahora `hyprctl -j monitors`, y cada plan propio a su monitor.
- `10815` **La vara de medir del rendimiento** — `WE_MEDIDAS` en el motor (fotogramas ejecutados, CPU, GPU y copia por intervalo, en sumas crudas) y `tools/medir_vivo.py` (escena fija, sin pausa, `fdinfo` del i915; la NVIDIA no publica `fdinfo`). Ruido medido, regla del 10 % y la línea de base.
- `10822` **Qué vale y qué no** — el fps del HUD no; el cronómetro sí pero salía una vez; `fdinfo` solo para la integrada; nadie contaba los fotogramas ejecutados.
- `10836` **Los dos instrumentos** — la línea `SceneView: medida` y el medidor externo; y el fallo de las dos pantallas con el mismo nombre.
- `10858` **El ruido** — tres medidas de `2788165557`: fps < 0,5 %, CPU/GPU por fotograma hasta 8 %. Un cambio cuenta si pasa del 10 % en tres medidas.
- `10880` **La línea de base** — 163 fps en eDP-1, 110 % de un núcleo, y la copia entre GPUs pesa más que dibujar el plan.
- `10896` **El tope de fotogramas** — `SceneView.fpsMax` (60 por defecto en Plasma y Hyprland): sin tope la NVIDIA gastaba 52 W y el proceso 110 % de un núcleo; con 60, 23–37 W y 66 %; con 30, 20 W.
- `10902` **El tope** — `setTime` solo pide fotograma tras `0,9/fpsMax`, para que el paso sea siempre el mismo número de latidos; Qt no compone sin nosotros (`fdinfo` lo confirma).
- `2885` **Lo medido** — la tabla por tope; 55 y no 60 porque el reloj late a 165 Hz; la NVIDIA bimodal a 60; el coste por fotograma sube al bajar fps, así que «% ocupada» no mide consumo y los vatios sí.
- `10955` **La copia entre GPUs, sin esperar** — `glReadPixels` síncrono era 3,1 ms de 5 por fotograma: anillo de dos PBO con valla y mapeo persistente, se presenta el anterior. CPU del proceso de 65 % a 28 %; un fotograma de retraso.
- `10962` **El cambio** — asíncrono solo con el reloj avanzando (en pausa, síncrono, si no se vería el anterior para siempre); sube desde el puntero del PBO, sin `memcpy`.
- `10983` **Que lo que se ve es lo que se dibujó** — 950/950 fotogramas iguales byte a byte; la prueba con `static` fallaba porque cada pantalla tiene su hilo de render.
- `2885` **Lo medido** — `leer` de 3,11 a 0,03 ms; la «subida» de la integrada, corregida después: no existe; la NVIDIA igual.
- `11014` **Los 2,5 puntos de la integrada** — no existían: nueve medidas intercaladas de síncrona/PBO/PBO+copia dan lo mismo en la integrada; era una línea de base suelta. La integrada baila de 570 a 870 MHz y ±10 %. Desde aquí, antes y después intercalados.
- `11019` **Las hipótesis** — frecuencia, memoria de origen u otro trabajo; `medir_vivo` guarda ahora MHz y RC6 de la integrada.
- `2885` **Lo medido** — la tabla de los tres modos; copiar el PBO a un búfer propio cuesta 13 puntos de CPU.
- `11059` **De paso, para el punto 3** — HDMI-A-3 cuelga de la NVIDIA: su fotograma va y vuelve por la integrada sin necesidad.
- `11066` **Dos monitores: lo que cuesta cada pantalla, y lo que no es nuestro** — la segunda pantalla suma casi entera en el proceso (+13 % CPU, +370 MiB); el HDMI en la NVIDIA le cuesta a Hyprland el 40 % de la integrada. Cerrado medido, sin cambiar el motor.
- `11071` **Lo que faltaba en la vara de medir** — Hyprland (CPU, i915, pmon), VRAM, `--sin-fondo` y `--solo` en el anfitrión; y zsh, que no parte `$x`.
- `2885` **Lo medido** — la tabla por pantalla y sin fondo.
- `11111` **Qué se puede hacer, y qué se hizo** — dibujar una vez para las dos solo vale en modo `mismo`; no se hizo.
- `11127` **Las lecturas de diagnóstico, y lo que sí se pagaba en cada fotograma** — ninguna `glReadPixels` corre en marcha; sí 46 `qgetenv` y 14 `glGetUniformLocation` por fotograma, ahora leídos al cargar. Dentro del ruido.
- `11132` **Lo que hay** — las cinco lecturas y a qué variable obedecen; las consultas por fotograma no esperan a la GPU.
- `11144` **Lo que sí se pagaba, aunque poco** — el cerrojo del entorno disputado por dos hilos, y la búsqueda de `src` por nombre.
- `2885` **Lo medido** — A/B intercalado cambiando el `.so`: 1–3 % menos, dentro del ruido.
- `11170` **Los uniforms constantes, una vez al cargar** — un programa por pase conserva sus uniforms: `resolve` sube las constantes y los samplers una vez y el bucle solo `g_Time` y los marcados (227 → 14 llamadas por fotograma). ~4 % de CPU, dentro del ruido.
- `11177` **Por qué se puede** — sin programas compartidos; los valores solo se escriben al leer el plan; las hojas ya iban aparte.
- `11193` **Comprobado que el render no cambia** — `glGetUniform*` al fotograma 100 en 12 escenas: cero distintos. Los 16 «distintos» de Sci-Fi City eran uniforms duplicados en el plan (`g_UserAlpha` dos veces por pase) y los de las hojas.
- `2885` **Lo medido** — A/B intercalado: ~4 % menos, dentro del ruido.
- `11232` **Los pasos de la simulación** — el resto del tramo era un paso entero más: 2 pasos por fotograma a 55 fps (1,32 a 60). Ahora `round(dt/PASO)` pasos iguales: Voyage de 20–24 a 14–17 ms de CPU por fotograma; 0 regresiones de luz en 133 escenas.
- `11236` **Dónde mirar** — `particulas_ms` y `particulas_subir_ms` en `WE_MEDIDAS`; las escenas con más partículas.
- `11247` **Lo que hacía Voyage** — banco + `gprof`: la turbulencia es el 80 % (12 ruidos × 8 hashes por partícula y paso), y había dos pasos por fotograma.
- `11260` **El resto que costaba un paso entero** — la tabla de pasos por cadencia; pasos iguales en vez de acumular; las cintas graban por tiempo y no cambian.
- `2885` **Lo medido** — banco, `test_weparticles`, `test_luminancia` con referencia, y en vivo intercalado.
- `3072` **Lo que queda** — EVA es subir vértices (resuelto después, instanciando); Voyage ya la limita la NVIDIA (28 ms de GPU con dos pantallas, ~60 W).
- `11323` **Las partículas, instanciadas** — un registro de 15 floats por partícula en vez de 6 vértices de 17; el shader se reescribe con una macro `a_TexCoordVec4` sobre `gl_VertexID`. EVA de 83 % a 48 % de CPU, Voyage de 47 a 53 fps; PNG offline idénticos. Los planes viejos hay que regenerarlos.
- `11329` **Por qué tanto** — 408 bytes por partícula donde bastan 60; los tres caminos.
- `10750` **Cómo** — `weparticles`, los dos ejecutores, `instanciar_particula` en `werender.py` y los lectores; los 814 sprites del corpus usan `genericparticle`.
- `11370` **Comprobado** — PNG idénticos byte a byte en 5 escenas, `test_weparticles` y `test_luminancia` sin regresiones.
- `2885` **Lo medido** — la tabla de EVA y Voyage; baja también la GPU.
- `11393` **Dos medidas que se contaminaban** — la rotación arrancaba el fondo normal en medio de una medida; `medir_vivo` para ahora el temporizador.
- `11405` **El vídeo, al tamaño al que se ve** — convertir YUV→RGBA costaba más que decodificar, y el plan pedía el vídeo nativo: ahora el tamaño con que cubre la pantalla. *Home* 4K de 180 % a 140 % de CPU y la NVIDIA de 34 a 19 W.
- `11411` **Dónde se va** — `ffmpeg -benchmark`: decodificar frente a convertir, en tres vídeos.
- `10962` **El cambio** — `wevideo.tamano_textura`, nunca más que el nativo; solo los wallpapers de vídeo, no las capas `IS_VIDEO`.
- `11370` **Comprobado** — 15 vídeos offline: 9 idénticos, 6 de 4K a 37–45 dB. `test_wevideo` falla en *Pattern* (`3047352572`) desde antes de este cambio.
- `2885` **Lo medido** — intercalado tres y tres.
- `3072` **Lo que queda** — conversión en la GPU, VAAPI, y el vídeo decodificado dos veces con dos pantallas.
- `11486` **Los relojes, el texto y la hora en cada fotograma** — ya estaba bien: los relojes se rehacen por tramo. *Lonely Cat* con 58 relojes, 1,58 ms por fotograma; *Arknights* (144 pases, 71 sistemas) es la escena para el punto 6.
- `11507` **La pausa en Hyprland** — llega a cero: el proceso al 0,1 %, la integrada a 0 y la NVIDIA a 2,9 W y 210 MHz, igual que sin fondo. Los «2 W de más» del tope eran un artefacto de una medida corta. Queda ocupada la VRAM (~500 MiB).
- `11538` **El objeto que no dibuja no se compone** — `beginObject` limpiaba los dos buffers del ping-pong y bastaba uno; un objeto vacío se componía igual. *Arknights* 14 % menos de CPU, PNG idénticos. Lo grande queda: cada capa se dibuja a tamaño de lienzo (63 W).
- `11545` **Dónde va la CPU de `render()`** — `render_ms`, `previo_ms` y `objetos_ms` en `WE_MEDIDAS`.
- `11552` **Lo que se hacía de más** — el `glClear` del buffer que limpia el primer pase, y la composición de un objeto transparente.
- `11370` **Comprobado** — PNG idénticos en 6 escenas; `3047352572` no es determinista ni sin el cambio (su vídeo *Pattern*).
- `2885` **Lo medido** — intercalado tres y tres en *Arknights*.
- `11590` **Lo que queda, y es lo grande** — buffers de objeto del tamaño de su capa; y una caché de estado de GL.
- `11606` **Partículas directas y buffers del tamaño de la capa** — lo grande del punto 6. *Arknights*: NVIDIA de 63,5 a 38 W, GPU de 6,7 a 2,9 ms por fotograma; `test_luminancia` sin regresiones.
- `11615` **Un sistema de partículas de un solo pase va directo a la escena** — `directo` en `object`; sumar o superponer sprites da lo mismo que componer su buffer. Si el programa lee la escena con un sampler activo lo decide el ejecutor, no el plan. 92 de 133 idénticas.
- `11647` **El buffer de cada objeto, del tamaño al que se ve** — `<w> <h>` en `object`: ×2 lo que ocupa en pantalla, tope el lienzo, 4 lienzos de pares extra. Por qué ×2: a 1:1 sale blanda (nitidez 13,25 → 10,32; ×2 12,73).

## CLI, rotación y rutas

- `177` **El CLI — `tools/wectl.py`** — `list`/`set`/`shuffle`/`start`/`stop`/`status`; `set` acepta id de Workshop o parte del título.
- `193` **Rotación: por qué es un temporizador y no una opción del plugin** — por qué el «cada x tiempo» no vive en la configuración del fondo.
- `222` **Cambiar la cadencia sin cambiar el fondo, y por qué el mínimo es 1 minuto** — `shuffletime`, y de dónde sale el suelo del intervalo.
- `2242` **Dos `wectl` a la vez se pisaban** — la rotación por systemd cayendo encima de un `set` a mano: los dos construían el plan en el mismo directorio.
- `274` **Dónde está Wallpaper Engine** — el orden de búsqueda de `wepaths.py`: variables de entorno, luego las bibliotecas declaradas en Steam.
- `3949` **Los 19 wallpapers que trae la aplicación: 7 servirían** — vienen sin empaquetar (`scene.json` suelto) y las herramientas filtran justo por `scene.pkg`.

- `4308` **`wectl list` dice de qué tipo es cada wallpaper** — el `type` de `project.json`, normalizado: 24 de 148 lo escriben con mayúscula.
- `4324` **Enseñar también los que no se pueden poner** — un wallpaper que no aparece no se distingue de uno que no está instalado.
- `4342` **El que no es un wallpaper** — `2336642563` trae `category: Asset`: es un paquete de materiales, no un fondo.
## Pausa por oclusión, resolución y rendimiento

- `1318` **La pausa mide cobertura, no una bandera** — preguntar «¿está maximizada?» falla en tres casos diarios; medir cuánta pantalla queda a la vista, no.
- `1340` **Lo que el modelo de tareas no dice, y cómo se supo** — dos hechos sobre minimizar y el estado de las ventanas que no están en la documentación.
- `1375` **No dibujar lo que no se ve** — 98,4 % → 0,0 % del motor de render al pausar, medido con `/proc/<pid>/fdinfo`.
- `2197` **El HUD decía 166 fps con la GPU al 98 %** — el reloj de QML medía la composición de Qt, no el motor. Por qué el número del HUD no vale como medida.
- `2844` **Dibujar a la resolución que se ve** — 8,3 Mpx pintados para enseñar 2,3; el lienzo del autor casi nunca es el de la pantalla.
- `2885` **Lo medido** — el cronómetro del ejecutor, escena por escena, antes y después.
- `1999` **Encajar el lienzo en la pantalla** — cómo se ajusta `orthogonalprojection` al panel, medido sobre el corpus.

## Formatos: contenedor, texturas, mallas

- `394` **Formatos de Wallpaper Engine** — por qué la implementación de referencia está en Python y qué significa «especificación ejecutable».
- `400` **`scene.pkg` — `tools/pkg_inspect.py`** — la tabla de entradas, con los offsets relativos al FIN de la tabla y no al fichero.
- `409` **`.tex` — `tools/wetex.py`** — contenedores `TEXB0001`–`0004`, formatos, LZ4 de bloque, mipmaps y sprite sheets animados.
- `1951` **El relleno a potencia de dos estaba en los píxeles** — un `.tex` de 4096x2048 con la imagen en una esquina; parecía un fallo de encaje y no lo era.
- `451` **`.mdl` — `tools/wemdl.py`** — mallas puppet: geometría, `MDLS` esqueleto, `MDLA` animación.
- `3511` **El puppet se quedaba en reposo: el campo de la cabecera es un desplazamiento** — 58 de 95 puppets no encontraban `MDLA` y se quedaban quietos.
- `3552` **Y entonces `mirror` deja de ser un detalle** — los dos ejecutores dan por hecho que la última clave repite la primera; en modo `mirror` no.
- `3571` **Lo medido** — las 129 escenas tras recuperar los puppets: ninguna regresión.
- `4926` **El personaje calvo: el rig tenía un bloque con nombres que nadie leía** — `attachment` cuelga una capa de un hueso del padre; el nombre está en el bloque `MDAT`, que se saltaba entero.
- `4948` **Dónde estaba el nombre** — el campo de texto del hueso son los límites de la articulación; el formato de `MDAT` y por qué el recuento es u16.
- `4983` **Por qué no basta con hornearlo** — el hueso se mueve hasta 285 px, así que los ejecutores rehacen la traslación por fotograma.
- `9901` **La Vi sin piernas: tres lectores que se quedaban cortos** — `3047352572`: un rectángulo negro, piezas sueltas y un pase perdido; tres arreglos de lectura y la cabeza, que queda abierta.
- `9909` **1. El rectángulo negro: un `.mdl` sin esqueleto** — el formato `0x0000000f` es `0x0180000f` sin huesos ni pesos: 12 campos por vértice.
- `9923` **2. Las piezas sueltas: la cola de cada animación crece con la versión** — 4, 9, 10, 34 y 35 bytes según el `MDLA`; y la animación la elige `animationlayers` por su identificador, no `anims[0]`.
- `9947` **3. Un pase que no compilaba: los combos de `// [COMBO]` existen siempre** — la copia vieja de `pulse` pregunta `#ifndef AUDIOPROCESSING`; WE define los de directiva a 0, los de sampler no.
- `9963` **Lo que NO se arregló: la cabeza** — efectos antes o después de deformar: la Vi pide después y la cabeza del dragón antes; se deja como estaba.
- `10032` **La cabeza de la Vi: los efectos de un puppet van sobre la textura y se deforma al final** — las máscaras de la Vi y del dragón solo tienen sentido sobre la textura; un pase final deforma la malla.
- `10040` **Lo que lo decide: qué tapa cada máscara en la textura** — la de la Vi, la cabeza pintada en el cuerpo; la del dragón, un párpado suelto salvo el ojo.
- `10060` **Por qué la primera prueba pareció decir lo contrario** — el pase final sin mezcla: un párpado transparente sobrescribía la cabeza del dragón.
- `10074` **El binario no lo resolvía** — `_rt_imageLayerAlbedo_` es del camino de la iluminación, no del orden de efectos y deformación.
- `10084` **El reparto** — solo `werender`: malla en reposo en el pase base y un `passthrough` con la mezcla del pase base al final.

## Vídeo

- `3657` **Vídeo de verdad: un decodificador compartido, y dos entregas distintas** — el MP4 viaja entero en el plan y lo decodifica `src/wevideo.c`, que enlazan los dos ejecutores.
- `3668` **Por qué libav y no una tubería de `ffmpeg`** — 4K60 en RGBA por una tubería son 2 GB/s, y el bucle y la pausa solo se harían matando el proceso.
- `3682` **Los dos modos no son un lujo: son dos requisitos incompatibles** — el offline necesita el mismo fotograma al repetir; el vivo, no bloquear nunca. Con las medidas de coste.
- `3712` **El bucle de seeks que dejaba el vídeo clavado** — el seek cae en el fotograma clave anterior y el consumidor volvía a pedir; solo se ve si el reloj arranca lejos de cero.
- `3732` **Y el fichero no siempre empieza en cero** — `start_time` desfasaba un fotograma y desplazaba el bucle en cada vuelta.
- `3743` **Nueve fondos negros por un espacio en el nombre** — el plan se parte por espacios; el MP4 es el primer asset nombrado tal cual venía de la biblioteca.
- `3757` **Lo que había que decidir, y dónde se decidió** — mipmaps, volteo con paso negativo, BT.709 cuando el fichero calla, y el tamaño del anillo.
- `3778` **Los wallpapers de tipo vídeo salen casi gratis** — los 15 que no son una escena: plan sintético de un quad, y encaje que cubre en vez de caber.
- `3795` **El oráculo: pixel a pixel contra ffmpeg** — 54/54 fotogramas idénticos y 18/18 dimensiones; y por qué se le fija a ffmpeg la misma matriz de color.
- `3814` **Lo medido sobre las 129** — 0 regresiones, 124 de 128 escenas con la luz exacta de antes; y el falso positivo por llenar `/tmp`.
- `3841` **Lo que sigue sin estar** — audio, decodificación por hardware y el `.tex` de vídeo con relleno que el corpus no tiene.
- `3087` **Vídeo en el motor: qué haría falta** — el estado de ANTES, ya resuelto; se conserva por el orden cronológico.
- `3110` **Lo que hay que resolver antes de intentarlo** — las dudas que planteaba, todas decididas arriba.

## Shaders: dialecto, compilación, enlace

- `1451` **Dialecto de shader — `tools/weshader.py`** — las cuatro capas encima del GLSL: `#include`, `[COMBO]`, metadatos JSON en los uniforms, restos de HLSL.
- `700` **Tres fallos que se veían como uno** — el bokeh que tapaba la escena de Asuka eran tres causas independientes y solo una se parecía al síntoma.
- `731` **El escaneo de no-soportados corría demasiado pronto** — 17 escenas negras, 16 por una sola causa.
- `769` **Los uniforms de las cabeceras no existían** — fondo entero en negro y solo las partículas encima.
- `819` **Las conversiones implícitas que quedaban** — las 26 variantes que no compilaban eran todas lo mismo: HLSL convierte solo y GLSL no.
- `2040` **La última variante que no compilaba: truncar también al llamar** — la 1 de 594, y por qué la truncación necesita un parser y no un regex.
- `2916` **Compilar no es enlazar: 82 pases que se perdían sin decir nada** — un vértice y un fragmento pueden compilar por su lado y no poder enlazarse.
- `2937` **La causa del grupo grande** — la familia de desenfoques gaussianos y el `KERNEL` que cada etapa declara distinto.
- `2953` **El arreglo obvio parecía romper la imagen, y ya no** — prestarle a cada etapa el combo que consulta, y por qué la primera vez destrozó 72 escenas.
- `2991` **Tres causas, y ninguna era la que decían estas notas** — el desglose con `--link` sobre los 297 pares, en los dos drivers.
- `3056` **Y lo que parecía un límite de hardware: `GLSL` sin definir** — WE define `GLSL` o `HLSL` según el backend; nosotros ninguno, así que todo `#ifdef GLSL` caía al lado equivocado.
- `3072` **Lo que queda** — cero fallos en los planes reales; la única variante que NVIDIA rechaza y Mesa acepta.
- `5025` **`step(0.5, nodeNum)`: la norma lo admite y NVIDIA no** — promocionar el argumento entero que no es un literal, y por qué la tabla de tipos va aparte de la de truncación.

- `4094` **La homografía salía transpuesta: `m[i][j]` no es lo mismo en los dos lenguajes** — el único header que construye una matriz por índices, y los 10 efectos que lo incluyen.
## Grafo de escena y composición

- `1504` **Grafo de escena — `tools/wescene.py`** — una escena no es una lista de capas: es un grafo con recursos nombrados. La cadena completa para pintar una sola imagen.
- `1569` **Renderizador offline — `tools/werender.py` + `tools/glexec.c`** — el reparto: la inteligencia en Python, la ejecución en C.
- `1623` **Composición de capas** — los dos niveles de buffer: el par ping-pong del objeto y el buffer de escena.
- `1656` **Transformación por objeto** — `origin`, `size`, `scale`, `angles`; el pase base recibe MVP y los de efecto son post-proceso a pantalla completa.
- `1668` **Visibilidad condicional** — `visible: {"user": ..., "value": ...}`; ignorarlo dibuja capas que el autor dejó apagadas.
- `1679` **Render targets incorporados** — `_rt_FullFrameBuffer` y `_rt_MipMappedFrameBuffer` son nombres reservados, no buffers nuevos.
- `1692` **`copybackground` no significa "empieza desde el fondo"** — interpretarlo mal recomponía el fondo nueve veces sobre sí mismo.
- `3578` **La capa `passthrough` se componía en su rectángulo del editor** — `composelayer`/`fullscreenlayer`/`projectlayer` operan sobre el fotograma entero y nadie leía el flag.
- `3612` **Lo medido** — una sola escena cambia, y baja porque antes estaba mal.
- `3234` **Los recuadros negros: una capa negra de verdad, compuesta con la mezcla que no era** — tres rectángulos pintados encima que no están en el preview.
- `3241` **La capa no está rota: es negra a propósito** — RGB medio 3,8 y alfa 255; lo que la hace invisible en WE es el `colorBlendMode`.
- `3268` **Por qué no se hace donde lo hace WE** — WE mezcla dentro del pase base con `ApplyBlending`, no al componer.
- `3287` **El alfa hay que premultiplicarlo a mano** — `screen` y `max` ignoran el alfa de la fuente y el buffer de una capa con efectos no viene premultiplicado.
- `3296` **Y entonces la regla de la herencia se cae sola** — el «solo heredan los grupos» era un parche a la mezcla del objeto, y estorbaba en cuanto se arregló lo de debajo.
- `3318` **La invisibilidad no bajaba por la cadena de padres** — apagar un grupo tiene que apagar lo que cuelga; Lonely Cat trae la escena seis veces, una por idioma.
- `3338` **Lo que NO era: la Y del hijo** — la tentación de invertir la Y del `origin` relativo, comprobada y descartada.
- `3359` **Lo que se ve** — los tres rectángulos desaparecen y las ondas salen del centro.
- `5483` **El fondo de *Lonely Cat* se desliza, y las dos mitades de un arreglo** — un `composelayer` que se queda el fotograma entero y lo desplaza; el mismo fallo explica la banda de arriba y que las olas no cuadren con el gato.
- `5494` **El oráculo: el preview del autor no se mueve** — 0 px en los 38 fotogramas de WE contra 2,2 % de altura por segundo en el nuestro.
- `5507` **Quién lo mueve** — el volcado pase a pase señala uno solo: el `scroll` de una capa cuyo efecto de barras está apagado por una propiedad de usuario.
- `5530` **La causa: la identidad que le damos a una capa passthrough** — `composelayer.vert` dibuja pantalla completa pero muestrea POR LA MVP, y se la damos identidad.
- `5551` **Por qué el arreglo son dos mitades y ninguna vale sola** — la tabla de las tres variantes, y por qué la que se probó en su día tenía que fallar.
- `5571` **Alcance, medido sobre las 129** — 29 capas de 85 tienen rectángulo distinto del lienzo; 27 son `composelayer` en 18 escenas. Arreglado: `_colocacion` ya no fuerza identidad en `composelayer`, y su pase base lleva la MVP real.
- `9536` **Las capas giradas giran en píxeles del lienzo: `object_mvp` y `we_giro_coloca`** — `object_mvp` giraba después de pasar a clip y estiraba en x por ancho/alto toda capa girada de un lienzo no cuadrado; ahora es D · R · E como `object_world` y `particle_mvp`, y `we_giro_coloca` gira por D · R(Δ) · D⁻¹ con el lienzo de la escena, que la línea `giro` lleva detrás porque `canvas` es la resolución de dibujo redondeada. Cambian las colocaciones de las 22 escenas del censo y nada más.
- `9552` **Lo que cambia** — `object_mvp`, la VP de una capa iluminada que pasa a ser la ortográfica, el lienzo de la escena en la línea `giro` y en el `WeGiro` que leen los dos ejecutores, y el `g_EffectModelViewProjectionMatrix` inerte de las partículas.
- `9585` **Lo que se descartó** — girar en píxeles solo las agujas, sacar la proporción de `canvas` (2,0e-5 y 6,3e-5 en vivo), y conservar la fórmula vieja para las partículas.
- `9600` **Lo medido** — 722 capas a 4,4e-16 de ortográfica · mundo y 63 giradas en 22 escenas; el C a 4,1e-8 en tres lienzos y dos locales, y a 1,1e-7 con el plan a 1920x1200 y 1366x768; 46 planes idénticos, 22 con colocaciones distintas y 61 solo con líneas inertes; la aguja de las 03:00 a −0,11 % y +0,28 % de su `size · scale` (main, +77,5 %); 0 regresiones de luz.
- `9664` **Lo que queda** — un autor que compensara la deformación, y lo que WE pone en el uniform de efecto de una partícula.

## Escenas negras y capas perdidas

- `1776` **Medir la luz, no solo que el plan se genere** — por qué existe `test_luminancia.py`: una escena puede quedarse negra sin que nada falle.
- `1826` **Tres escenas negras por un `normalize(0, 0)`** — se preparaba sin una sola queja y salía a 18 de 255.
- `2262` **Un sampler sin enlazar no lee negro** — Resident Evil 9 salía casi vacía; con `--only-base` aparecía entera.
- `2292` **El arreglo es general, y destapa 26 escenas** — enlazar el `default` que declare el sampler, y qué queda fuera a propósito.
- `2320` **El lunar negro del vinilo: la opacidad iba a un uniform que nadie lee** — la sombra del disco, opaca en mitad del personaje.
- `2358` **Alcance: 78 objetos en 18 escenas** — los objetos con `alpha` distinto de 1, medidos sobre las 129.
- `2373` **El cuarto nombre del tinte: `g_Color`, y la ciudad que salía en siluetas** — el atardecer y el planeta perdidos en *Sci-Fi Cyber City*.
- `2410` **Alcance: 44 capas en 15 escenas, y 17 acertaban por casualidad** — quién lee `g_Color` de verdad: tres shaders de la librería común y nadie más.
- `3135` **Las dos escenas negras eran dos campos leídos de más** — el mismo error en dos sitios: **`value` no es el valor**.
- `3144` **`1518454472`: la Miku salía roja donde va cian** — el color de verdad está en la propiedad del `project.json`, no en el `value`.
- `3166` **`3577990983`: un telón de entrada que no se levantaba** — la escena no estaba rota, estaba tapada por una capa negra con el `alpha` animado.
- `3201` **Lo que se llevó por delante** — las escenas que cambiaron además de las dos buscadas.
- `3220` **La que queda es bloom, y es un subsistema** — sale con los tonos correctos pero apagada; `bloom: true` no está implementado.
- `3627` **`254 - 255` no es −1: el flujo se invertía donde la máscara satura** — negar la V de un mapa de flujo sobre el byte, no sobre el entero.

## Iluminación y reflejos

- `2454` **La función de iluminación no está en los assets** — ocho shaders llaman a `PerformLighting_V1` y ninguno la define.
- `2484` **El mismo color por dos caminos distintos** — dos generaciones de shaders con convenciones **incompatibles** para el mismo dato.
- `2503` **El mundo es el lienzo en píxeles** — las luces declaran su `origin` en las unidades de los objetos; no hay conversión de espacios.
- `2512` **Tres uniforms que GL pone a cero sin decir nada** — encender el combo cambia el camino del vértice y el plan no emitía lo que ese camino usa.
- `2534` **O todas las luces, o ninguna** — si una escena trae una luz que no sabemos poner, se dibuja plana entera: el ambiente oscurece contando con que las luces devuelvan.
- `2550` **El módulo de verdad está en el binario, y no es un fichero** — `LightingV1` va como texto dentro de `wallpaper64.exe`: no es un shader, es un generador.
- `2601` **La función repuesta no la usa ninguna escena de esta biblioteca** — los 6 pases iluminados del corpus van por el camino viejo.
- `2643` **Lo que se ve** — 9 luces en 5 wallpapers; la media de la escena de referencia contra el preview del autor.
- `10134` **El cielo de After Sunset: `LightingV1` por clase, el exponente de cada luz y el fondo opaco** — `3210875135`: cielo gris plano y cuadrados; tres causas generales.
- `10140` **1. El cielo sin luz: `LightingV1` no sabía de tubos** — la reconstrucción tenía cuatro puntuales fijas; ahora un array por clase, como el generador del binario.
- `10159` **2. El cielo oscuro: `exponent` es de la luz** — el lector de WE lo guarda en `[luz+0x2e8]`; 1,06 en vez de 2 fijo.
- `10169` **3. Los cuadrados: el fotograma empezaba transparente** — `clearcolor` opaco; el `blur` divide por el alfa y cada sprite dejaba su quad.
- `10188` **Y lo que no era un fallo: la intro** — un `color_grading` con fundido de entrada de 5 s.
- `2654` **El tubo sí venía en la escena, y el reflejo solo pedía una pirámide** — las dos cosas que quedaban eran mucho más pequeñas de lo que decían estas notas.
- `2660` **La luz de tubo: `controlpoint` es el otro extremo** — estas notas decían que no había forma de ponerla; el segundo extremo sí está en el formato.
- `2690` **La tercera convención para el mismo color** — la que leen los shaders con un array por clase.
- `2707` **Los focos se quedan fuera a propósito** — no hay ni un foco ni una direccional en esta biblioteca con la que comprobarlo.
- `2716` **Lo que se ve, y lo que no** — casi nada, y hacia abajo; por qué, para no volver a mirar aquí.
- `2732` **Reflejos: no era un subsistema, era un filtro** — `REFLECTION` estaba forzado a cero por un buffer que ya existía.
- `2751` **El filtro no puede vivir en la textura** — `_rt_MipMappedFrameBuffer` y `_rt_FullFrameBuffer` son **el mismo buffer**.
- `2765` **Lo que se ve** — 7 pases en 3 escenas; el bloque solo vive con `NORMALMAP`.

## Partículas

- `948` **Sistemas de partículas** — el primer subsistema con estado que avanza con el reloj, y por qué eso no puede vivir en Python.
- `969` **El reparto** — `weparticles.py` resuelve y escribe un `.psys`; `weparticles.c` simula y no conoce Wallpaper Engine.
- `988` **Verificación** — la regresión de render, y qué reparto hay que mirar de verdad.
- `1004` **Y luego, en el escritorio** — 17 de 42 piezas «sin soporte» con el mismo `.so`: era **`LC_NUMERIC`**. El arreglo es `uselocale`, no `setlocale`.
- `1033` **Lo que costó encontrar** — cinco fallos, **ninguno en la simulación**: alfa, formato de textura, recorte.
- `1065` **Decisiones que son lecturas, no hechos** — `colorrandom` con un solo factor, y otras lecturas del formato que podrían ser otras.
- `1083` **Estelas: `spritetrail` no necesitaba historial** — las 211 estelas del corpus parecían un problema y el shader dice que no.
- `1122` **`rope` y `ropetrail`: la cinta sí pide historial** — van por `genericropeparticle`, y eso no está en el material.
- `1200` **Repartir por puestos: el rayo** — `mapsequencebetweencontrolpoints` no es un parámetro, es otro modelo de colocación.
- `1212` **El corro, el ruido y una orientación que ya estaba bien** — tres cabos cerrados leyendo el JSON con cuidado; en dos, lo que bloqueaba era una lectura equivocada.
- `1720` **La turbulencia no turbulaba** — aquí la dirección la fija el campo de ruido; lo de que el formato no trae dirección está corregido después: WE gira `forward` alrededor de `right`.
- `1874` **Imitar el humo de WE con una captura por oráculo** — cómo se localiza qué trozo del lienzo enseña una captura para que sirva de referencia.
- `1914` **El humo que no se apagaba** — una neblina ancha donde WE tiene una voluta compacta; no era el tamaño del sprite.
- `2078` **El `exponent` de los sorteos: leído, y la curva elegida mirando la vela** — 96 usos en la biblioteca que se estaban tirando.
- `2101` **Lo que NO se pudo confirmar** — la dirección del sesgo, con los tres oráculos que se intentaron y por qué ninguno sirve.
- `4021` **El anillo del vórtice, y las dos velocidades que faltaban** — una captura del escritorio de Windows como oráculo; tres cosas mal a la vez en la misma escena.
- `4029` **La tangente es una cuerda: el radio crecía solo** — un 65 % por vida; se arregla girando la posición, no empujándola.
- `4046` **`distanceouter` es hasta dónde llega, no dónde se satura** — la medida que lo decide es la PENDIENTE de las estelas: radiales, no tangenciales.
- `4065` **El emisor tenía una velocidad y nadie la leía** — `speedmin`/`speedmax` de `sphererandom`: la única velocidad de 12 sistemas del corpus.
- `4350` **Las estrellas no parpadeaban: `colorrandom` sin `max` sortea hasta negro** — el oráculo se monta restando el fondo a la captura; dos fallos distintos con la misma medida.
- `4365` **El tamaño del sprite: el brillo explicaba una parte, no toda** — por qué el rayo NO sirve de contraste, y qué queda abierto.
- `4390` **La pista estaba en un campo escrito de más** — 158 objetos escriben `max` igual a `min`; por eso el defecto de `max` es negro y no `min`.
- `4407` **El ritmo implícito estaba en el extremo, y se comía el `instanceoverride`** — `maxcount/vida` deja el depósito lleno, que es el percentil 76 del corpus, no la costumbre.
- `4438` **La otra mitad era el bloom** — el halo que la resta enseña alrededor de todo lo brillante; lo piden 33 de las 129.


- `5105` **Los destellos de la `City`: qué se mueve, y por qué no se toca nada** — el desglose de lo que se mueve en una escena de destellos: ~900 parpadean sin desplazarse, 170 derivan y 20 fugaces cruzan.
- `5119` **Los dos candidatos a fallo, y por qué ninguno lo era** — `turbulence` como aceleración la respaldan las plantillas de WE con su `drag: 4`; el ritmo implícito no se puede bajar sin apagar el polvo y las brasas.
- `5145` **Lo que se probó y se retiró: frenar el reloj de la simulación** — la vía medida (x1,00 / x0,55 / x0,26) por si algún día se pide, y la trampa de comparar por el reloj de pantalla.

- `5173` **La turbulencia, a la mitad: una desviación pedida, no un arreglo** — el rotacional del ruido tiene RMS 0,980, así que `speed` ya era la aceleración: bajarla es preferencia, y vive en `FACTOR_TURBULENCIA`.
- `5202` **`FACTOR_TURBULENCIA = 0.5`** — por qué solo el operador y no el inicializador, por qué en Python y no en el `.c`, y a cuántas escenas alcanza.
- `5221` **Lo medido, antes y después** — camino y desplazamiento neto por vida, siguiendo cada partícula por vecino más próximo.

- `6763` **Los ejes de la turbulencia: `forward` gira alrededor de `right`, y `up` no se lee** — leído en `wallpaper64.exe` y sin aplicar: WE no muestrea un campo en el espacio, gira `forward` (`0 1 0`) alrededor de `right` (`0 0 1`) un ángulo de ruido 1D en el tiempo; cambiaría las 152 piezas, no solo las 5 con ejes.
- `6780` **Lo leído, con direcciones** — bloque de tipo 9; defectos y desplazamientos de cada campo (rapidez 0,5–1 o 100–250, `phasemax` 0,1, `scale` 1, `offset` escalar); `up` no aparece ni en el lector ni en los defectos.
- `6804` **La regla** — θ = π·`scale`·snoise1((fase + reloj)·`timescale`) + `offset`; `right` normalizado, `forward` no (`0 0 0` da velocidad nula); la misma matriz que `velocityrandom`. Con `audioprocessingmode` distinto de 0 (2 piezas), el audio multiplica el ancho de la fase: se omite, no hay audio.
- `6873` **Por qué no se aplica** — el defecto de WE no es la identidad de hoy, y `offset`, la rapidez y la fase tampoco casan; aplicarlo solo a los que declaran ejes darían dos semánticas para la misma pieza. Lo que haría falta para sustituir el inicializador; hecho después.
- `6684` **Lo medido** — rumbo de la pieza aislada, hoy contra la regla: 12 de 18 fuera de ±15°; 1131 de 1131 planes idénticos en las 129 y `verifica_exe.sh` 154 ok.
- `7089` **La turbulencia con la regla de WE: `turbulentvelocityrandom` deja de muestrear nuestro ruido** — la regla leída sustituye al inicializador en las 152 piezas; `ESCALA_RUIDO` queda solo para el operador y `desplazar_ruido` desaparece.
- `7103` **El booleano es «la escena es ortográfica»** — bit 10 de `[contexto+0x118]`, que el cargador enciende con `orthogonalprojection`; las 129 lo son, así que la rapidez por defecto es 100–250.
- `7132` **`[obj+0x130]` son los segundos de la escena** — el mismo contexto en `renderizador+0x10`; el reloj que suma el dt y que `remapinitialvalue` llama `runtime`.
- `7043` **Cómo queda aquí** — 13 floats en el `.psys`, `wescene.ortografica`, `snoise1` y Rodrigues en el `.c`, el reloj de la escena en `s->reloj`.
- `7185` **Lo que cambia en el aspecto** — lo que nace a la vez sale paralelo: 269 de 271 sistemas en chorro, contra 114.
- `7051` **Lo medido** — 18 de 18 rumbos a ≤ 15° (la base, 6), Flare_Sparks quieto, 95 de 98 a ±10 % de 175, planes idénticos fuera de la pieza, `verifica_exe.sh` 254 ok.

## Bloom

- `4446` **El bloom son tres shaders de WE y un objeto más** — la cadena no había que escribirla, había que deducirla de los nombres.
- `4463` **`g_TexelSize` es el texel de PANTALLA, y lo dice la captura** — tres lecturas posibles con un factor 8 entre ellas; el radio medido cae limpio en 16 px.
- `4484` **El umbral va DESPUÉS de promediar, y eso se ve** — por qué el bloom de WE rodea zonas brillantes y no puntos sueltos.
- `4492` **No hay que tocar los ejecutores** — va como un objeto más que se compone sumando; los buffers ya sabían sacar su resolución del nombre.
- `4506` **Lo medido sobre las 129** — 39 escenas, la mediana contra el preview de 0,171 a 0,135, y la primera pasada sin escenas apagadas.

## Resolución

- `4680` **El lienzo del autor no es un límite de resolución: 38 escenas salían ampliadas** — el `min(1.0, ...)` hacía que el blit final las agrandara; el diario del motor en vivo lo traza.
- `4710` **Lo medido** — 38 de 129, mediana x1,11 y hasta x3,40; y por qué `test_luminancia` no vale como oráculo aquí.
- `4725` **Lo que NO explica** — la City ya se dibujaba 1:1; su destello sigue pendiente.

## Sistemas hijos

- `4732` **Sistemas hijos: `eventspawn`** — 232 sistemas con hijos en 61 escenas; aquí solo el que estalla donde muere el padre.
- `4740` **El hijo es un objeto hermano, no un pase más del padre** — trae su propio material, así que se devuelve como objeto y se ata con `psyspadre`.
- `4754` **La lectura del formato** — el depósito sale de `children` y la ráfaga del preset; el emisor libre del hijo se apaga.
- `4766` **Por qué se simulan en tándem, y no uno detrás de otro** — una cola diferida haría estallar el sistema entero de golpe tras una recuperación de 60 s.
- `4786` **Lo medido** — 0 a 60–92 partículas; 10 escenas, 17 hijos; y por qué `test_luminancia` no vale como oráculo aquí.
- `4799` **Lo que NO arregla** — las manchas van de 23 a 74 pero siguen en 5–8 px donde WE tiene el pico en 3–4.
- `5070` **Un puntero donde hacía falta una lista: el hijo `eventspawn` congelado** — con dos hijos el segundo pisaba al primero y lo dejaba sin dar pasos; una escena del corpus.
- `5612` **Los hijos de un sistema: cuatro tipos, y `eventspawn` estaba leído al revés** — lo que se había implementado como `eventspawn` era `eventdeath`; `static` y `eventfollow` entran.
- `5619` **El oráculo: lo que la propia aplicación dice y trae** — la interfaz de WE nombra cuatro tipos y su documentación los define; los fuegos artificiales usan `eventdeath`.
- `5644` **Sin `type` es `static`** — `ember` → `emberglow` va sin tipo y con `static` más todos los defectos: 320 entradas en 51 escenas, no 34.
- `5659` **Qué es cada uno, en el motor** — `static` es un sistema colocado con `parent`; los de evento sueltan su `instantaneous`; `eventfollow` emite donde está su partícula y deja estela.
- `5692` **El reparto** — la línea `psyspadre` con modo, instancias, probabilidad y escala; `nace()` como único punto de nacimiento, y por qué hacen falta los nietos.
- `5719` **Lo que se deja fuera, a propósito** — `angles` de la entrada, `controlpointstartindex`, `flags` y las piezas `inherit*`: sin caso en el corpus con el que medirlos.
- `5737` **Lo medido** — 275 hijos en 60 escenas; la prueba de contrato y que muerde; 0 regresiones sobre las 129.
- `9188` **La instancia de un hijo de evento: lo leído en wallpaper64.exe** — un `eventspawn`/`eventdeath` con `rate` emite para siempre donde lo creó el evento, sin ráfaga si no declara `instantaneous`, y solo hay `maxcount` de la entrada a la vez; 9 entradas en 4 escenas.
- `9210` **Lo leído, con direcciones** — tope de instancias, posición fija, emisión, apagado del emisor, liberación de la instancia y los defectos (`rate` 10, `instantaneous` 0).
- `9262` **Lo que se descartó** — «emite hasta que muere la partícula» es solo de `eventfollow`; no se satura porque el tope de instancias corta.
- `9273` **El reparto** — sin campo nuevo: ráfaga 0 sin `instantaneous` en `werender.py`, y las `Instancia` de `fijas` en `weparticles.c`.
- `9287` **Lo medido** — 55/55 direcciones; la prueba de contrato muerde; `Flare_Smoke` de 3063 a 206 vivas; 125/125 planes idénticos; 0 regresiones de luz.
- `9343` **Lo que queda** — el tope de instancias de los hijos solo `instantaneous`, el puesto de `eventfollow` que se libera antes que en WE, `delay` y emisión periódica.

## Emisores

- `4818` **`distancemax` sin declarar no es cero: la lluvia salía toda del mismo punto** — el tercer campo con el mismo patrón; 6 presets-emisor en 7 escenas.
- `4831` **Por qué 512** — el corpus escribe el 0 explícito 153 veces y `exampleturbolence` obliga a que el defecto sea ≥256.
- `4846` **Lo medido, y lo que queda torcido** — dejan de pegarse al borde, pero el 75 % nace fuera por el `directions: "1 5 0"`.
- `6371` **Varios emisores: emiten todos, al mismo depósito** — 2 sistemas en 2 escenas, con un segundo `sphererandom` vacío; una línea `emit` por emisor y un crédito por emisor en `src/weparticles.c`.
- `6384` **Lo leído y lo supuesto** — los defectos del segundo emisor son los leídos; que el `rate` del override multiplique a cada uno y que el depósito sea común, supuesto.
- `6413` **Lo hecho** — `Sistema.emisores`, `Emisor em[4]` y `we_psys_vivas`; un `.psys` de un emisor sale y se lee igual.
- `6430` **Lo medido** — 1412 de 1414 `.psys` idénticos y el simulador idéntico sobre ellos; `fog2` se llena con el segundo emisor; 0 regresiones.
- `6467` **`flags: 2` no coloca el emisor: es una partícula por fotograma, y al cursor lo lleva el punto de control** — la hipótesis del rastro del ratón, refutada en `wallpaper64.exe`; el render no se toca.
- `6485` **Lo que hace WE, con direcciones** — `flags` en `+0x3c`, `controlpoint` (defecto 0, tope 7) en `+0xe0`/`+0x98`, el bit 1 como `min(cuenta, 1)` y el centro de emisión en el punto de control, con o sin el bit; el bit 0 es `sign` y el sorteo gira con el punto si `controlpoint ≠ 0`.
- `6550` **El corpus con la regla leída** — 17 emisores con el punto atado al cursor en 12 escenas, 6 de ellos sin el bit (`mouse_trail_1`, `shurikencursor_1` con `controlpoint: 1`); 0 con offset.
- `6584` **Lo que queda, para hacerlo bien** — leer `controlpoint` y centrar `emite` en su punto, girando el sorteo con la matriz del punto; sin ratón, el offset; el tope de una por fotograma, sin leer; la unión del `rope`, cerrada después.
- `6622` **Lo medido** — `verifica_exe.sh` (5 cadenas y 57 instrucciones, 0 fallos), `censo_cp_emisor.py` y ningún diff en el render.
- `6633` **Todo emisor nace en su punto de control, primer trozo: la traslación** — `controlpoint` al final de `emit` solo si no es 0, y `emite` centra en `cp[controlpoint]` + `origin`; los hijos colgados y los repartos por puestos, como estaban.
- `6646` **Lo hecho** — `_punto_del_emisor`, `Emisor.punto`, el centro de las cintas en `psysprobe` y la prueba 10 de `test_weparticles.py`, en `C` y `es_ES`.
- `6684` **Lo medido** — de 2414 `.psys` cambia una línea; planes idénticos; los 17 nacen en el puntero; 2414 sondas sin ratón y 2388 con él, idénticas; 0 regresiones de luz.
- `6743` **Lo que queda fuera** — el giro del sorteo con el punto, el tope de `flags & 2`, el cosido del `rope` (cerrado después), el punto antes del primer movimiento y `mapsequence*`.

## Cintas y movimiento

- `4873` **La cola de una cinta sale de `length`, no de un 8 fijo** — el defecto de `segments` pisaba el campo declarado; 68 de 74 cintas.
- `4894` **`gravity` es una aceleración, y lo demuestran los fuegos artificiales** — por qué no se endereza la caída, y qué hace que la parábola cante.
- `6057` **`upright` en una cinta: WE la orienta como a un sprite, y da la base de siempre** — la anchura de la cinta la pone `g_OrientationForward`, no nuestro constructor; cierra el último aviso de `orientation` del corpus.
- `6076` **El lector: tres modos y una base** — `0x1401c22e0`, compartido por las cuatro fábricas de renderer; `axis` nulo es (0, 1, 0).
- `6095` **La rutina que pone los tres uniforms, igual para los cuatro renderers** — `0x1402298b0`: `screen`, `upright` y `fixed`, y la normalización final.
- `6117` **Por qué en el corpus no cambia nada** — `(c × u) × u` es `−c` si `u` no tiene z; *Vapor 1* y los `Rain_Splash` con `flags: 1`.
- `6134` **Lo hecho** — `_orientacion` con una sola regla para sprites y cintas; ni plan ni ejecutores.
- `6148` **Lo medido** — 0 avisos (antes 1); 1131 de 1131 `plan.txt` y `.psys` idénticos en las 129; PNG idéntico; 0 regresiones.
- `7689` **Cómo cose WE un `rope`: una sola cinta que une las partículas vivas, de la más vieja a la más nueva** — `rope` no es una cinta por partícula: une las vivas en el orden en que nacieron, y su fábrica no lee ni `length` ni `segments`.
- `7701` **Lo que hace WE, con direcciones** — bloque de tipo 3 frente a 4, la rama `0x1402369ed` del bucle de dibujo, el constructor `0x140230919` y la lista `sistema+0x218`, que crece al nacer y se compacta al morir.
- `7741` **Lo hecho** — `orden` y `construye_cuerda` en `src/weparticles.c`, sin duplicados con un `instantaneous` repetido; `cinta 1 0 0` en el `.psys`; el plan solo cambia en el `g_RenderVar0` del `rope`; la prueba 11 de `test_weparticles.py`.
- `7768` **Lo medido** — 71 de 71 en el binario; `6·(N−1)` vértices, cosidos y en orden de nacimiento; 113 planes y 964 `.psys` idénticos, y en las 16 con `rope` solo 38 líneas `g_RenderVar0`; 0 regresiones de luz en las 16.
- `7811` **Lo que queda fuera** — `trailLength` en régimen, `uvscrolling`, la cuerda con dos puntos en el mismo sitio, el tope de `flags & 2` y la curva (hecha después).
- `8190` **La curva de un `rope`: la Bézier de `subdivision`, hecha en la CPU** — `subdivision` (4 si falta, topado a 32) es el `TRAILSUBDIVISION` del `.geom`; `construye_cuerda` parte cada tramo en `sub + 1` subquads con su curva, su ancho y su UV.
- `8202` **Lo que hace WE, con direcciones** — los defectos del `rope` en `0x1401c0c90` (`subdivision` 4, `uvsmoothing` verdadero), el tope en `0x1401cffbd` y el combo en `0x1401d2aa2`.
- `8221` **El `.geom`, y cómo se lleva al quad sin geometry shader** — controles `fin − R(inicio)` e `inicio + R(fin)`, tamaño `|R|`, y `trailLength`/`trailPosition` que dan la UV de WE en cada punto.
- `8260` **Lo hecho** — `_subdivision` y el cuarto número de `cinta`; `tramo_curvo` y el búfer con `sub + 1`; el plan no cambia; la prueba 12.
- `8276` **Lo medido** — 65 de 65 en el binario; la curva a 3e-06 del `.geom`; con 0, la cuerda de main byte a byte; 113 planes y 964 `.psys` idénticos; *Vapor* cambia un 1,145 % de los píxeles con flechas de menos de una unidad; 0 regresiones.
- `8341` **Lo que queda fuera** — `ropetrail`, el ojo en perspectiva, `uvsmoothing` verdadero por defecto y el tramo que da media vuelta.

## El ratón

- `5244` **El ratón entra en la escena: un puntero, cuatro consumidores** — quién lo mira (46 escenas de partículas, 29 de cámara, 13 pases de efecto) y por dónde entra un dato que cambia cada fotograma.
- `5257` **Quién lo mira, contado antes de escribir nada** — la tabla que decide el diseño: las partículas son el consumidor grande.
- `5270` **El puntero viaja como el tiempo: un marcador en la plantilla** — `@PUNTERO_X@`, `psyspuntero` con la afín ya resuelta, y por qué «sin ratón» no es «ratón en el centro».
- `5302` **De dónde sale el ratón en el escritorio** — `HoverHandler` y no `MouseArea`, para no quedarse los clics; y lo que Wayland no da.
- `5318` **La pantalla no es la escena** — el encaje recorta, así que el píxel bajo el ratón no es el píxel de escena; `encajado()` sacado del blit.
- `5328` **La `y` del uniform, que es donde estaba la trampa** — los flips de los shaders de WE y la rama `GLSL` que ya estaba elegida; sin flip.
- `5354` **Lo que sí se midió** — tres sistemas con origen, escala y giro distintos cayendo en el mismo punto de la pantalla; y el contrato Python↔C.
- `5406` **Lo que la regresión dice: 0 regresiones y una reordenación honesta** — las 129 antes y después; las once que cambian son relojes, menos una, y esa cambia porque el operador nuevo mueve las fases.
- `5432` **`g_ParallaxPosition` es el puntero con retardo, y nada más** — por qué no lleva `amount` ni `mouseinfluence`: dos escenas con el efecto declaran amount 0. Corregido después: es el P de la cámara, con la influencia.
- `5456` **Lo que queda, medido** — la cámara (falta el número que lleva `amount` a píxeles), el emisor con `flags: 2` y el puntero bajo las ventanas.

## La cámara

- `5931` **El parallax de cámara: la fórmula estaba en el motor, y mueve las capas también en reposo** — `cameraparallax` en 29 escenas, leído en `wallpaper64.exe` en vez de medido contra WE corriendo.
- `5940` **Cómo se encontró** — la tabla de propiedades de `general` y la de la capa dan los desplazamientos; de ahí, las lecturas.
- `5951` **Lo que hace WE** — el punto P entre el centro y el ratón, su suavizado, y la traslación `amount × depth × (origin − P)` con la raíz.
- `5976` **La sorpresa: con el ratón en el centro, las capas ya están desplazadas** — comprobado contra el preview de `2262142032`: el reloj a unos 10 px y el letrero que WE deja fuera.
- `5992` **Cómo está hecho aquí** — el término en reposo horneado en `transform_absoluto`; el del ratón en la línea `paralaje` de los dos ejecutores.
- `6020` **Lo medido** — 0 regresiones; correlación con el preview: 4 se acercan, 2 se alejan, 23 igual.
- `6038` **Lo que queda** — `g_ParallaxPosition` (ya hecho), `escena[+0xf0]`, la marca que invierte la x y `camerashake` (ya hecho).
- `6198` **El temblor de cámara: también estaba en el motor, y no es ruido** — `camerashake` en 6 escenas: una curva de Lissajous determinista leída en `0x140199580`, que mueve la cámara entera; línea `temblor` y `src/wetemblor.c` en los dos ejecutores.
- `6210` **Cómo se encontró** — `+0x328/+0x32c/+0x330` y el bit 7 de `+0xe0` en el lector de `general`; los defectos en el constructor; el reloj es el del renderizador.
- `6246` **Lo que hace WE** — `velocidad² · t`, `(cos s, sin 1,333·s)`, la amplitud por `0,01 × alto`; la rugosidad solo deforma la norma; y `escena[+0xf0]` es el ojo.
- `6274` **Cómo está hecho aquí** — `temblor` en la cabecera, `tiembla` por capa, acoplado al punto del parallax; por qué las `passthrough` se quedan quietas (con ellas se movía el doble).
- `6307` **Lo medido** — 138 de 144 planes idénticos; desplazamiento medido contra predicho a ±0,1 px en cinco escenas; 0 regresiones.
- `6351` **Lo que queda** — `3053927686` un 7 % largo, el marco de las `composelayer` pequeñas y el `eye` fuera del origen (cerrado).
- `6950` **El `eye` de la cámara no llega al parallax: WE lo pone a cero en las escenas ortográficas** — leído en `wallpaper64.exe` antes de aplicarlo: el cargador borra el `eye` del json en las 47 escenas que lo declaran; no cambia el render.
- `6780` **Lo leído, con direcciones** — la cámara declarada (`+0x118`) y la vigente (`+0xf0`), el cero de `0x14018866b`, de dónde sale el ojo cada fotograma y la suma en `0x140189c18`.
- `7010` **Lo que dicen los previews** — con el `eye` sumado la correlación empeora en 7 de 11; el reloj de `2262142032` mejora, pero por el encaje global.
- `7043` **Cómo queda aquí** — un comentario en `parallax_de_camara` y `prueba_parallax_de_camara` con el `eye` declarado.
- `6914` **Lo medido** — `verifica_ojo.sh` sin fallos, 129 planes idénticos, 137 raíces sin cambio y la luz de las once igual.
- `7075` **Lo que queda** — los objetos cámara (`3521337568`) y las escenas con `paths`.
- `7256` **`g_ParallaxPosition` es el punto P de la cámara, no el puntero con retardo** — el `switch` de uniforms encontrado en `wallpaper64.exe` (índice `0x6b`, tabla de dos niveles): `clamp(P/lienzo)` con la influencia y la y hacia arriba, y el centro si `cameraparallax` está apagado; en vivo sale de `m_camara`.
- `7274` **Lo leído, con direcciones** — la tabla de nombres, el enlace, el `switch` y su caso (`0x1400d9e90`, `contexto+0x9c`), el 0,5 del cargador, el bit 8 de `+0xe0` y la escritura en `0x140189cbe`.
- `7337` **Lo que cambia en el corpus** — las 6 con `depthparallax`; las dos de influencia negativa iban en x al revés y entre 3,7 y cinco veces más fuertes.
- `7357` **Cómo está hecho aquí** — `posicion_de_parallax` en `_fotograma`, el centro sin marcadores en los pases que lo leen con el parallax apagado, y `m_camara` acotado en vivo.
- `7203` **Lo medido** — 57 direcciones sin fallos, 24 de 24 valores contra la regla, la prueba que cae sin la influencia y con la y al revés, 1131 ficheros idénticos sin ratón.
- `7414` **Lo que queda** — el ojo (el temblor) no entra offline, las marcas `0x200200` y `0x800` del contexto, y verlo en el escritorio.
- `7426` **El parallax sigue al ratón en tiempo real: el cursor lo da KWin, y el retardo de WE se queda para el temblor** — al fondo le llegaban 1–5 posiciones/s (ventanas maximizadas apiladas; el hover no llega a plasmashell); `CursorKWin` pide el cursor global a KWin por D-Bus: 18–40/s. Y la parte del ratón de `m_camara` con 25 ms en vez del retardo de WE (decisión del usuario).
- `7433` **La que importaba: al fondo no le llegaba el ratón** — 1–5 posiciones/s pegadas al panel con ~42 fps; el `HoverHandler` en la raíz no bastó; `CursorKWin` y su script de KWin (enteros por D-Bus): 18–40/s en toda la pantalla.
- `7469` **La otra: el retardo de WE** — 300–883 ms hasta el 95 % con `(1 − delay/3)·10·dt`; la parte del ratón a 25 ms, la del temblor con el de WE.
- `7499` **Partículas con perspectiva: el bit 0x4 del `flags` del sistema es otra cámara, no otra simulación** — «Perspective rendering» en 153 sistemas de 58 escenas: leída en `wallpaper64.exe` la cámara que WE les pone en una escena ortográfica (ojo a `alto / (2 tan(fov/2))`, `perspectiveoverridefov` o 95°, cercano 5); va en la MVP del pase, sin tocar C.
- `7510` **Qué bit es cuál: la tabla del editor** — `wallpaperui.exe`: 0x1 worldspace, 0x4 perspectiva, 0x8..0x80 «disable overrides» (ninguno en el corpus); el 0x2 no tiene casilla.
- `7530` **Lo que hace WE, con direcciones** — `flags` → descriptor+0x8 → sistema+0x20; el `>> 2 & 1` del dibujo, `0x1401e5b60`, la `PerspectiveFovRH` de z invertida del dispositivo y de dónde salen fov, centro y aspecto.
- `7357` **Cómo está hecho aquí** — `perspectiva 1` al final del `.psys`, `particle_mvp_perspectiva` en `werender.py`; los ejecutores heredan la matriz.
- `7378` **Lo medido** — 149 direcciones sin fallos; 140 `.psys` marcados de 153 (13 invisibles); 71 escenas idénticas a main; los copos de 1,0 a 6,4 px por unidad; luz sin regresiones (los relojes, con la hora fija).
- `7414` **Lo que queda** — el bit 0x1 (worldspace) y el 0x2; márgenes, espejo y aspecto del destino; el ojo de las estelas y las cintas.

## Valores por defecto de las partículas

- `5780` **Los valores por defecto estaban en el binario: el giro, la caja, el ritmo y el sesgo** — cuatro cabos de partículas: uno lo cierra la documentación y tres el código del motor de WE.
- `5788` **El sesgo de `exponent`: confirmado, no se toca nada** — la documentación dice que de 2 en adelante sesga hacia Min: es `pow(t, e)`.
- `5798` **Dónde guarda WE sus valores por defecto, y cómo se leen** — desensamblar `wallpaper64.exe`: cada defecto se carga junto a su campo, y la fábrica dice de qué pieza es; la tabla completa.
- `5842` **La «hoja girada» del rayo era un giro, y afecta a 66 escenas** — `rotationrandom` vacío gira de 0 a 2π (112 sistemas); `angularvelocityrandom` vacío, ±5 (18).
- `5852` **La caja es `256 256 0`, y el 40 % que sigue fuera es del preset** — las fugaces que cruzan pasan del 28 % al 60 %; `distancemax` es el semieje, lo dice la muestra de `rain_splashes`.
- `5876` **El ritmo: 10 por segundo, no el 48 % del depósito** — sustituye al ritmo implícito en 68 sistemas; en la `City`, más fugaces y no menos.
- `5899` **`directions` es `1 1 0`** — solo cambia la z, que entra en el ruido de la turbulencia.
- `5904` **Lo medido** — cinco pasadas, 0 regresiones; `3097749052` se mueve por sorteo; los rayos girados y las fugaces cruzando en la `City`.

## Pendiente

- `11722` **Pendiente: lo que queda de la auditoría de rendimiento** — restos del punto 6 (`g_TexelSize`, buffers `_rt_Half…` del lienzo, caché de estado de GL), puntos 11 a 17, y el vídeo *Pattern* (`3047352572`), ya resuelto.
- `11727` **Restos del punto 6** — revisados: caché de estado descartada, `g_TexelSize` y `_rt_…` por capa sin tocar, buffers declarados arreglados.
- `11733` **11. El IPC de Hyprland** — hecho: medido, no se cambia.
- `11741` **12. Que la NVIDIA pueda dormir** — la parte del motor, hecha; la del sistema, abierta.
- `11750` **13. Tiempo de `wectl set` y `shuffle`** — hecho: 3,5 veces más rápido.
- `11757` **14. Tamaño del plan en disco** — hecho: −29 % con las texturas de uno y dos canales; DXT tal cual, descartado.
- `11764` **15. Tiempo de carga en el motor** — medido: subir texturas es el 75–80 %; `glProgramBinary`, descartado.
- `11771` **16. Recarga del plan** — medido y arreglado en Hyprland: la escena nueva se carga debajo; Plasma, sin tocar.
- `11778` **17. Resolución del plan (verificar, no rehacer)** — verificado en Hyprland: las 148 a 1,00; Plasma girado y dos monitores, sin probar.
- `11786` **Fuera de la lista** — el vídeo *Pattern* (`3047352572`): hecho, y no era el vídeo.
- `11792` **Las tablas de glexec y el paso de swscale** — `3047352572` salía de dos maneras al azar y `test_wevideo` fallaba en *Pattern*: dos fallos sin relación.
- `11800` **El render no determinista: `textures[64]`** — `MAX_TEX` 64 y 96 texturas: `tex:80` leía punteros de `videos[]` (ASLR). Topes holgados y rebasarlos aborta; `3097749052` deja de salir en silueta negra. Lo cazó ASan+UBSan, no la bisección.
- `11855` **`test_wevideo`: el paso de swscale con ffmpeg 9** — con paso `w*4` swscale deja columnas sin escribir o escribe fuera del hueco (en vivo, cada fotograma). Filas a múltiplo de 64 bytes y `GL_UNPACK_ROW_LENGTH`.
- `11880` **El IPC de Hyprland, medido** — ~100 µs de Hyprland por petición; `activewindow` se repite con cada cambio de título. Preguntar el cursor solo si el plan lo lee (64 de 133 no lo leen) no mejora nada en vivo, intercalado A/B: se deshizo. El microbenchmark prometía medio punto que no apareció.
- `11885` **Cuánto cuesta cada petición** — cliente sintético a 62/s: +0,5–0,75 puntos de Hyprland, 0,35 ms de latencia.
- `11900` **Cuántas hay** — 62/s de cursor; la revisión, ~1/s por monitor por los `activewindow` repetidos.
- `11912` **Lo que se probó: preguntar el cursor solo si el plan lo lee** — criterio (uniforms vivos, `psyspuntero`, `paralaje`; la línea `parallax` no vale), 64/133 sin ratón, y la medida A/B que lo descarta.
- `11948` **La NVIDIA en pausa, medida** — 0 interrupciones de la NVIDIA en pausa, igual que sin fondo; el hilo de render no se despierta. Queda retenido el contexto y su VRAM, sin medir si impide dormir.
- `11977` **Lo del sistema, para cuando se aborde** — `Runtime D3 status: Disabled by default`: falta `NVreg_DynamicPowerManagement`; con `audio-fix.conf` y lo no identificado, tres causas, ninguna del motor.
- `11990` **Los puntos 13 a 15: el plan, su tamaño y su carga** — los tres eran bytes de textura y Python lento.
- `11996` **13. Lo que tarda `emit_plan`** — LZ4 en C, traducciones recordadas, `inv(G)` una vez, `bincount`: corpus 319 → 90 s, planes idénticos. El `TypeError` tragado por `emit_pass` que borró todos los pases.
- `12038` **15. Qué pesa en el `init`** — desglose por fases en el registro; subir texturas es el 75–80 %, compilar casi nada.
- `12060` **14. Qué ocupa el plan, y lo que se hizo** — DXT es el 9 % de los bytes; R8/RG88 expandidas a RGBA el 28 %. `canales_de` y `GL_R8`/`GL_RG8` con swizzle: −29 % de bytes, −12–33 % de `init`, −165 MiB de VRAM, imagen idéntica.
- `12095` **Fuera de estos puntos** — los cuatro fallos de `test_wectl`, ya arreglados: ver «El test que cambiaba el fondo».
- `12101` **La resolución, verificada** — las 148 en vivo a 1,00 en el blit final; lo que sobra es el recorte de «cubrir» (mediana ×1,11, verticales hasta ×3,18).
- `12119` **Lo que no se ha podido probar aquí** — Plasma no mira la rotación del panel; con dos monitores habría que tomar el máximo por dimensión y no el de más área; escala fraccionaria sin ver.
- `12140` **Los restos del punto 6** — los tres pendientes del punto 6, revisados.
- `12142` **La caché de estado de GL: no compensa** — un programa por pase y destinos que no se repiten: lo evitable es <1 % de la CPU.
- `12152` **`g_TexelSize`: no se toca** — la única medida contra WE cuadra con el texel de pantalla; para los efectos de capa no hay oráculo.
- `12163` **Los `_rt_…` por capa: poco, y sin oráculo** — 1,6 % de los píxeles del corpus; cambiaría la imagen.
- `12172` **Lo que sí: los buffers que declara cada efecto** — `fbos.scale` no se leía; los efectos del Workshop (`bokeh_blur`, un `bloom` en cadena) salían a lienzo completo. Línea `rt` en el plan; 4 escenas cambian, `2867316322` −14 % de GPU y −4 W.
- `12210` **La recarga del plan** — punto 16, medido en vivo con la hora en cada mensaje.
- `12216` **Lo que costaba** — el `Loader` destruía la escena al instante: 27–501 ms de pantallazo, casi todo el `init` de la nueva; la otra GPU solo 7–15 ms.
- `12239` **El cambio: la nueva se carga debajo** — dos huecos en `hyprland/main.qml`; relevo al `dibujado` de la nueva; la vieja se queda congelada, sin negro.
- `12259` **Lo que queda** — Plasma recarga saliendo a otro plugin, sin medir; el fondo que ya corría sigue con el QML viejo hasta reiniciarlo.
- `12269` **El test que cambiaba el fondo** — `test_wectl` escribía en el plan real (`destino: Path = ESCENA` se fija al importar) y `aplicar` le borraba los planes por monitor; desde `513ca75`. `destino=None`, `PANTALLAS` redirigido y guardas sobre los planes reales.
- `12299` **Lo que queda de las partículas, revisado** — los «Lo que queda» de partículas contados en el corpus: el tope de `flags & 2` cambia un emisor, el de instancias 5 destellos en 4 escenas, `mapsequence` no distingue; `uvsmoothing`, leído después y sin efecto.
- `12324` **`uvsmoothing`: leído, y en este binario no hace nada** — la rama depende de `[sistema+0x1bc]`·`[sistema+0x1c0]`, que solo pone a cero el constructor: `trailLength` = vivas y `trailPosition` = `k`, como aquí. Sin cambio de render.
- `12333` **Lo que hace el constructor de `rope`** — `A = [+0x1c0]·count`, `B = [+0x1bc]·lifetime` del override (`objeto+0x778`); en régimen `L = A·B − 1` y desfase `saturate((B − edad)·A) − 1`. `+0x258` edad, `+0x260` vida.
- `12354` **Por qué `A` y `B` valen 0** — ninguna escritura directa, desde otra base, indexada ni por copia; solo se leen en `0x1402309b5`.
- `12377` **Lo que no se ha podido descartar** — un puntero a miembro; si existiera, se vería en las estelas del ratón (`particle/drop`).
- `12387` **Y de paso** — `count` del override multiplica al ritmo `A` en WE; aquí solo a `maxcount`. `trailLength` en régimen, cerrado.
- `4533` **Pendiente: tres cabos de las partículas, medidos y sin cerrar** — cerrados los tres en secciones posteriores; lo que dejaron abierto, en «Lo que queda de las partículas, revisado».
- `4546` **1. Los destellos: NO es el tamaño, y el factor 0,5 está probado y descartado** — el `preview.jpg` como oráculo a 0,982; los sprites grandes ya coinciden.
- `4592` **1a. Descartado: no es la resolución, y cuidado con medir anchos** — el área va como la escala²; la mediana de anchos a baja resolución es ruido.
- `4611` **1b. Lo que falta son los sistemas HIJOS** — `halo_4` con núcleo del 8 % explica el pico de 3–4 px; 232 sistemas con hijos en 61 escenas.
- `4641` **2. La lluvia de estrellas sale toda del mismo punto** — `boxrandom` sin `distancemax`: el mismo patrón que `rate` y que el `max` de `colorrandom`.
- `4661` **3. La estela es corta y gorda; debería ser fina y larga** — el defecto de `segments` pisa el `length` que el autor sí escribe; 68 cintas de 74.

## Texto

- `3374` **Un punto son 4,137 unidades de lienzo, y eso no lo dice el formato** — una capa de texto es el único objeto sin geometría ni material.
- `3384` **La unidad no está en el formato, pero la caja sí** — adivinar por DPI da candidatos plausibles y todos distintos; de dónde sale el número bueno.
- `3419` **Por línea, no por glifo** — menos código y mejor tipografía: PIL resuelve kerning, ligaduras y shaping de una vez.
- `3432` **Tres sitios de donde sale una fuente, y uno no está aquí** — 47 dentro del `scene.pkg`, 37 de la instalación de WE, 83 del sistema.
- `3447` **El ejecutor no se entera de que hay texto** — ni una línea de C: los quads viajan por la directiva `mesh` que ya existía.
- `3462` **Lo que la distribución ahorró** — mirar los valores y no los recuentos quita más trabajo del que deja.
- `3482` **Lo que se ve** — 25 escenas cambian, 0 regresiones.
- `3495` **Y el muro: 148 de los 167 son JavaScript** — 133 llaman a `new Date`: son relojes y fechas, y el texto dibujado no es el que el autor quiso.
- `4122` **Una capa de texto se ancla por su alineación, no por su centro** — no trae `alignment`: trae `horizontalalign` y `verticalalign`, y dicen lo mismo.
- `4144` **Y lo que faltaba: la hora era la del autor** — lo que se pensó entonces, que resultó ser la mitad de la historia.
- `4159` **La hora de verdad: interpretar el script sin un motor de JavaScript** — el plan es una foto, así que lo que viaja en él es el FORMATO, no la cadena.
- `4166` **Por qué no vale con ejecutarlo una vez** — cambiaría una hora congelada de 2021 por una congelada de hoy; el reparto en tres piezas.
- `4181` **Un intérprete, no un motor** — el vocabulario de los 51 scripts, contado; y `createScriptProperties()`, que llevó de 6 a 129.
- `4210` **Deducir el formato: cortar siete muestras a la vez** — las dos maneras de equivocarse: una sola cadena es ambigua y diferenciar cadenas cortas miente.
- `4229` **Los nombres no se adivinan: se reconocen** — están escritos en el script; hacen falta TRES muestras por valor o se cuela el campo vecino.
- `4246` **Lo que da la garantía es la comprobación, no la deducción** — ~1050 instantes; con una diferencia se descarta y la capa no se toca.
- `4262` **El alfabeto, y lo que se pierde** — rasterizar glifo a glifo en vez de por línea, y el kerning que eso cuesta.
- `4283` **Y la locale, otra vez** — `strtof` dentro de plasmashell deja el alfabeto a cero sin un solo error por medio.
- `7836` **Relojes de varias líneas: el salto viaja al plan y `wereloj` apila renglones** — el `SATURDAY` de `2946362143` empieza por `\n`; la ruta del reloj apila renglones como la estática, de 123 a 124 relojes.
- `7847` **Lo que cambia** — el `\n` escapado en el plan, el `espaciado` al final de la línea `reloj`; el atlas de los relojes de una línea no cambia.
- `7874` **Lo que se descartó** — la caja del quad engaña: `getbbox` de Pillow cuenta el espacio final; se compara la tinta. Y `dayFormat`, sin tocar.
- `7958` **El tope del atlas de un reloj: el renglón que se escribe y un alto máximo** — el tope de ancho estimaba una `W` por glifo y dejaba la 217 de `2946362143` a 160 px de em; ahora se mide renglón a renglón (11 capas suben, ninguna baja) y hay un tope de alto de 16384.
- `7972` **Lo que cambia** — avances glifo a glifo sobre `Formato.cadenas()`, al px de partida; `ALTO_ATLAS_MAX` rebaja la em si la columna se pasa (en el corpus, ninguna).
- `7998` **Lo que se descartó** — medir con `getlength` del renglón, que mete un kerning que el reloj no dibuja; y un tope de alto de 8192, que ya bajaría un atlas de main de 9053 px.
- `8012` **Lo medido** — 218,3 → 278,1 MB de atlas a 1920x1200 (+50,0 en `3462491575`); el más alto, 10550 px frente a los 16384 de Mesa, también en 4K; luz sin regresiones con la hora fija.
- `8092` **Desestructurar, `Boolean` y `engine.registerAsset`: seis relojes más** — tres huecos de JavaScript en `wescript`, ninguno propio de una escena; de 124 a 130 relojes, y `engine` solo con `registerAsset`.
- `8113` **Lo que cambia** — el patrón `[a, , c]` en las declaraciones, `Boolean` como `!!v` y un `Motor` cuyo único miembro devuelve un recurso opaco.
- `8136` **Lo que se descartó** — un `engine` permisivo: el contador de fps de `3238423642` suma `engine.frametime` y pasaría por reloj.
- `8145` **Lo medido** — el listado de main a la rama son seis líneas añadidas; `tools/test_wescript.py`; luz sin regresiones con la hora fija y nada fuera de las tres escenas se mueve.
- `8182` **Lo que sigue sin reloj** — `import`, la expresión regular, los otros miembros de `engine` y la `Date` de `3597772384`, que lanza «a número».
- `8806` **El kerning de los relojes: los pares del alfabeto viajan al plan** — la pluma glifo a glifo perdía hasta 0,368 em en 27 capas de 11 escenas; los pares del alfabeto van al plan (`relojkern`) y `wereloj.c` los suma: 0 em contra raqm en los 130 relojes.
- `8826` **Lo que cambia** — `_pares_del_alfabeto` y `_plumas` en `wetext`, la línea `relojkern` aparte para que un ejecutor viejo la salte, y `wereloj.c` leyéndola bajo la locale C.
- `8852` **Lo que se descartó** — HarfBuzz en el ejecutor; el miedo a los espacios (el 0,368 em de «| S A T U R D A Y |» son pares letra-espacio); ligaduras, que en el corpus no hay.
- `8865` **Lo medido** — 0 em en ancho, pluma y origen; 117 planes idénticos y 12 con pares, donde además solo cambia la caja del reloj; luz sin regresiones con la hora fija; ningún aviso nuevo.
- `8360` **Una hoja de sprites cuyo fotograma elige la hora: el indicador AM/PM** — un script de `visible` llama a `setFrame` con la hora; `wescript` da la tabla de 24, el plan lleva la hoja y `wereloj.c` pone los uniforms en los dos ejecutores. Solo cambia `3299228616`.
- `8378` **El censo** — 39 scripts con `setFrame` fuera del texto y por qué solo 30 dependen de la hora; las 56 capas con hoja animada en 10 escenas, 37 con `SPRITESHEET` (53 contando las que lo declaran en minúsculas) y 12 de varias imágenes.
- `8414` **Lo que cambia** — `thisLayer.getTextureAnimation().setFrame`, la línea `hojahora`, y el volteo: los uniforms de WE no se suben tal cual sobre una textura volteada.
- `8451` **Lo que se descartó** — encender `SPRITESHEET` o reproducir por `frame_time` las hojas sin script, y reconocer el script por su texto.
- `8460` **Lo medido** — 09:00 y 15:00 con `es_ES` a 1e-6; de las 129 solo cambia un plan; el recorte de la capa difiere entre AM y PM en la rama y es idéntico en main.
- `8497` **Lo que queda** — ~~reproducir por `frame_time` y si WE enciende `SPRITESHEET` solo~~, hecho en el trozo siguiente; ~~las de varias imágenes~~, hechas las 7 sin script; `setFrame` movido por clics.
- `8516` **Los combos van en mayúsculas y la hoja corre por `frame_time`: lo leído en wallpaper64.exe** — el censo buscaba `SPRITESHEET` y 16 capas lo declaran como `spritesheet`; WE pasa los nombres de combo por `toupper` y avanza la hoja con el paso de `g_Time`. Las 4 hojas de una imagen sin script de `2262142032` corren; las de varias imágenes, quietas en el fotograma 0.
- `8539` **Lo leído, con direcciones** — `toupper` en el lector de pases (`0x140154480`); el avance al enlazar la textura (`0x14015f0d0`), desde el fotograma 0, con el paso de `g_Time`; `spritesheetrefreshsync` solo duerme hasta el próximo fotograma; `frame_time` 0, uno por fotograma de render.
- `8601` **Lo que cambia** — `_combos_en_mayusculas` en `wescene`, `mueve_la_hoja` en `wescript`, el fotograma 0 y la línea `hojatiempo` en `werender`, y `we_hoja_tiempo_uniforms` en los dos ejecutores con `g_Time`.
- `8636` **Lo que se descartó** — normalizar solo `spritesheet`, imitar el paso a paso de WE, medir en el `origin` de la capa y el perfil de luminancia.
- `8654` **Lo medido** — 60 comprobaciones del binario; 34 planes cambian, cada uno con su causa; 34 → 54119 en el recorte de la 389 y el fotograma que toca; 0 regresiones de luz, y las caídas son el `color` y el `alpha` que `VERSION` aplica.
- `8716` **Lo que queda** — ~~la textura por `image_id`~~, hecha para las 7 sin script; el `alpha` que el valor por defecto del material pisa sin `VERSION`; `setFrame` por clics.
- `9033` **Las hojas de varias imágenes eligen la textura por `image_id`: lo leído en wallpaper64.exe** — WE parte cada fotograma por el tamaño de SU imagen y al enlazar pone en el sampler la imagen del fotograma; la línea `hojaimagenes` lleva la textura de cada uno y `we_hoja_tiempo_textura` la elige en los dos ejecutores. Corren las 7 capas sin script de `2262142032`, `2229352184` y `2220826239`.
- `9053` **Lo leído, con direcciones** — el `image_id` en `+4` del registro del fotograma y la división por el ancho y alto de su imagen (`0x14015e4b6..0x14015e4eb`); el avance lo apunta en `textura+0x98` (`0x14015f2e8`) y el enlace lo lee (`0x1400ee8f0`).
- `9088` **Lo que cambia** — `texture(imagen=)` y `linea_hojaimagenes` en `werender`, `lee_por_tiempo` con siete u ocho números en `wereloj.c`, y `g_Texture0` rebindeado en `glexec.c` y `glexecutor.cpp`.
- `9113` **Lo que se descartó** — una línea hermana detrás de `hojatiempo`, que un ejecutor viejo correría sobre la imagen 0; un atlas; partir por el tamaño de la imagen 0.
- `9131` **Lo medido** — 29 comprobaciones del binario; las 7 capas con su textura por fotograma; 3 planes cambian de 129; 128 → 106680 en el recorte de la 983; el `glexec` de main con el plan nuevo, igual que main; 0 regresiones de luz.
- `9177` **Lo que queda** — las 5 de `3577990983`, que mueve un script y pesan 1,1 GB en RGBA; `g_Texture0Resolution` por imagen.
- `8729` **Los puntos de un efecto van en la v de WE: la espiral de dragones de Karma** — un `center` con `"position": true` se subía sin voltear y el `spin` de `2637739953` giraba alrededor de un punto cerca del borde de abajo; ahora se escribe `1 − v`.
- `8746` **Lo que cambia** — el volteo en el bucle de constantes de `werender`, y `es_punto`: solo lo que el shader usa entero, porque `u_FixedSize` lleva la marca y es una proporción.
- `8768` **Lo que se descartó** — voltear todo `"position": true` y separar por la `label`.
- `8777` **Lo medido** — 15 planes y 54 centros cambian; 0 regresiones de luz en las 15; los `godrays` de `2645037214` salen ya del orbe y el farol.
- `8798` **Lo que queda** — el sentido de giro de cualquier ángulo de un efecto, que el volteo invierte y no se ha comprobado contra WE.
- `8900` **El cursor aparta: `controlpointattract` leído en wallpaper64.exe** — la regla del simulador era una deducción y estaba al revés en las dos cosas: WE solo actúa DENTRO de `threshold`, con caída lineal, y la `scale` negativa empuja. Las luciérnagas de Karma que perseguían el ratón ahora lo esquivan.
- `8911` **Lo leído, con direcciones** — la fábrica (`0x1401cc9d3`, bloque de tipo `0xa`), los defectos 512/512 o 20/5 con el booleano de la escena, el operador en `0x140241554`, `flags & 2` y `flags & 1`, y el tiempo `t` con el que se integra.
- `8962` **El corpus con la regla leída** — 109 de los 111 usos sobre el cursor tienen `scale` negativa; 13 sin `threshold`, uno sin `scale`, 6 con un `origin` que WE no lee.
- `8973` **Lo que cambia** — `_op_atrae` con los defectos de WE, `OP_ATRAE` a 4 floats, y `prueba_cursor`, que medía el fallo como si fuera lo correcto.
- `8995` **Lo medido** — la prueba nueva contra `main` (3 frente a 3384 en el hueco); 172 líneas de `.psys` en 39 escenas; 0 regresiones de luz; el vórtice de `3219398263` que no hacía nada.
- `9020` **Lo que queda** — el factor de tiempo `F` sin identificar, el `drag` lineal de WE, y `flags & 1`.
- `9363` **Las agujas de un reloj analógico: `angles` con `engine.timeOfDay`** — `wescript` reduce el script a `A · frac(B · tod) + C` en grados y lo comprueba evaluándolo; la línea `giro` y `src/wegiro.c`, nuevo y compartido, giran la colocación con la hora en los dos ejecutores. Las tres agujas de `2396319149` se mueven; solo cambia su plan.
- `9395` **Lo que cambia** — `engine.timeOfDay`, `giro_por_hora`, `--hora` y `@HORA@`, grados frente a radianes, y por qué el giro reproducía la deformación del ángulo estático (63 capas en 22 escenas), ya quitada en los dos sitios.
- `9449` **Lo que se descartó** — reconocer el texto del script, girar en píxeles solo las agujas o en el espacio del quad, y dar `timeOfDay` solo a `angles`.
- `9464` **Lo medido** — 3 de 7 scripts aceptados; 0 grados en 7200 `tod`; 128/128 planes idénticos y tres líneas `giro` añadidas; el C a 0 grados en `C` y `es_ES`; 0,0000 y 0,0001 de 255 contra el `angles` estático; 0 → 42193 entre las 03:00 y las 09:00; 0 regresiones de luz.
- `9515` **Lo que queda** — ~~la deformación del ángulo estático~~ (hecha), los otros cuatro `angles` (el seno, hecho), la fracción de segundo de `timeOfDay` sin leer en el motor, y los hijos de una capa girada.
- `9672` **Un campo que oscila con `engine.runtime`: el vaivén de `angles` y de `origin`** — `wescript` da `Math.sin`, `Math.cos` y `engine.runtime`, y `vaiven_de` reduce cada componente a `K + A · sin(ω · t + φ)` y lo comprueba evaluándolo; la línea `vaiven` y `src/wegiro.c` mueven la colocación con el tiempo de `g_Time` en los dos ejecutores. Se balancea el parche de `3050043876` y sube y baja el gotero de `3521337568`; las dos capas con hijos de `3577990983` no.
- `9705` **Lo que cambia** — `vector_en`, la ω por la identidad de `f(t ± h)`, la comprobación, la línea con los ejes de clip y el 1 + k del parallax en reposo de una raíz, y el giro con `we_giro_coloca`.
- `9762` **Lo que se descartó** — reconocer el texto, mover también a los hijos, otra cuenta para el giro, sumar el `origin` sin el parallax en reposo (92406 píxeles contra el estático) y mover el `g_EffectModelViewProjectionMatrix`, inerte aquí.
- `9789` **Lo medido** — 2 de 430 campos con forma, error 0; 131/133 planes idénticos y una línea añadida en cada una de las otras dos; 0 píxeles a t = 0 y contra el estático; 20,5 unidades y 3,00°; el C a 0 en `C` y `es_ES`; 0 regresiones de luz.
- `9878` **Lo que queda** — las capas con hijos, el glitch y el `Math.random` de `engine.runtime`, el pivote de una capa con `alignment`, los uniforms con la MVP del objeto y el arranque de `engine.runtime`.
- `10453` **Los scripts que colocan: un valor que no cambia se evalúa una vez** — `valor_fijo_de` evalúa al cargar el script que da siempre lo mismo (`engine.canvasSize`, `Vec3`, `init`) y lo pone en el `value`; el widget de `3462491575` deja de amontonarse. Un script con sucesos (`media*`, `cursor*`, `applyUserProperties`) no se evalúa.
- `10483` **Lo que cambia** — `canvasSize`, `new Vec2/Vec3`, el espacio duro, `valor_fijo`, `_es_suceso`, `_hornear_scripts_fijos`, y el deslizador atado a la `scale` de una capa repartido en las tres componentes.
- `10525` **Lo que se descartó** — repartir el deslizador en constantes de shader (`0.3 1`), evaluar con sucesos (8 colores negros) y `applyUserProperties` con `screenResolution`.
- `10543` **Lo medido** — 20 de 186 campos en 2 escenas; 174/174 formas idénticas; solo cambian los objetos esperados; `定位` idéntica píxel a píxel; 0 regresiones de luz.
- `10583` **Lo que queda** — los 34 hijos sin `origin` que van al centro, `getParent`, `applyUserProperties` al cargar, el rebote por fotograma de `2262142032` y el deslizador en un shader.
- `12396` **El audio en silencio: la plantilla de WE de respuesta al audio, evaluada sin música** — sin música WE ejecuta el script con los buffers a cero; `Interprete(silencio=True)` en `valor_fijo_de` y un número en un `Vec3` repartido (lo dice la documentación de `update`). 19 `scale` de la plantilla al 80–90 %; cambian `3462491575` y `3810943704`.
- `12403` **Lo que había en el corpus** — 26 campos con `registerAudioBuffers`, 19 de ellos la plantilla `script_factor_audio_response.js` en `scale`; da `value.x · minvalue` en silencio.
- `12423` **Lo que se ha comprobado antes de tocarlo** — el número a `Vec3(n, n, n)`, en docs.wallpaperengine.io (no leído en el binario); los tamaños 16/32/64, en `scenescript64.dll`.
- `7847` **Lo que cambia** — `silencio` y `_buffers_en_silencio`, `AUDIO_RESOLUTION_*`, `frametime` solo si se da, `_componentes` reparte el número.
- `2885` **Lo medido** — entran exactamente las 19; solo cambian dos planes; un buffer de 1744×1680 pasa a pantalla completa por el reparto del presupuesto; luz 129,65 → 129,48 y 47,39 → 47,86.
- `3072` **Lo que queda** — los visualizadores de barras con `createLayer` (en silencio, en WE no se ven) y el `scale` de audio de `2262142032`; el valor de `init`, hecho después.
- `12493` **`parseFloat`, los hijos de un `origin` que oscila y lo que devuelve `init`** — `parseFloat` e `isNaN` en el intérprete; cada capa lleva las líneas `vaiven` de sus antepasados, sin tocar C. 5365 y 31 de `3577990983` se mueven con sus hijos.
- `12498` **Las capas con hijos** — un `origin` traslada todo su subárbol igual y `we_vaiven_coloca` ya suma: `_vaiven_del_origin` por cada antepasado. El `angles` no se hereda.
- `2885` **Lo medido** — `prueba_vaiven_de_hijos` a 9,7e-14 de `object_mvp`; solo cambia el plan de `3577990983`, con 10 líneas; hay que medir después de su telón de entrada.
- `12533` **Lo que devuelve `init`** — `valor_fijo` lo aplica; sin `update`, el campo se queda en eso. No mueve nada del corpus.
- `3072` **Lo que queda** — los hijos partícula de la capa 31, y `visible` con `init` a `false`: `media_cover` de `3555933181` pinta su relleno, pendiente de leer `applyUserProperties` al cargar.

## Inventario del formato: qué leemos y qué no

- `892` **Qué campos del formato leemos y cuáles no** — cada clave que aparece en `scene.json` cruzada contra lo que el código busca por nombre.
- `902` **Colocación y geometría** — la lección de método: **el recuento bruto engaña**, hay que mirar la distribución de valores.
- `920` **Lo que sí falta, medido** — la lista de huecos reales, con lo ya hecho tachado.
- `2139` **Los uniforms que el motor rellena y nosotros no** — los 147 nombres de la tabla del binario cruzados con el código VIVO de las 594 variantes.
- `2181` **Lo que queda medido para después** — el vocabulario de partículas está completo; lo que falta son campos de piezas que sí leemos.

## Propuestas sin empezar

- `2797` **Mejora propuesta: generar un wallpaper desde un prompt** — el motor come de un formato abierto, así que basta con producir lo que ya sabe leer.
- `2814` **El camino mínimo** — prompt → imagen → mapa de profundidad → `scene.json` por capas.
- `2827` **Lo que falta en este repositorio** — no hay escritor de `.tex`, así que un PNG generado no entra.
- `2838` **Lo que el motor no puede dar, y conviene saber antes de diseñar el prompt** — audio reactivo, vídeo y modelos 3D.
