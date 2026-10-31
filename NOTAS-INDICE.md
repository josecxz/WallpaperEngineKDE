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
- `3968` **Elegir la GPU que renderiza** — la iGPU se come el 49,6 %; los dos caminos para mover el fondo a la dedicada y el riesgo que puede tumbar el segundo.
- `10203` **El fondo en la dedicada: el plan en otra GPU y el fotograma por la CPU** — la sonda del dmabuf dice que no; el plan en otro contexto del mismo hilo, leído por la CPU: la integrada de 33 ms a 1,2 ms por fotograma y 148 planes sin diferencias.
- `10210` **La sonda: NVIDIA no escribe nada que la integrada sepa leer** — la textura sale en bloques y Mesa la rechaza; un dmabuf LINEAR, NVIDIA solo lo muestrea. La CPU: 1,2 + 2,0 ms a 2560×1440.
- `10229` **El camino: otro contexto en el mismo hilo** — libglvnd reparte GL por hilo; qué GPU se elige, qué estado EGL se guarda (la API también) y por qué `~SceneRenderer` libera en el contexto propio.
- `10318` **El mando: `wectl gpu`, en caliente** — `DedicatedGpu` por la API de Plasma; el plan se suelta y se recarga en la otra GPU sin reiniciar, y los dos fallos que eso destapó (sampler y consultas que sobrevivían al contexto, contadores que se sumaban).
- `10348` **¿Duerme la dedicada? Steam, btop y el audio HDMI** — la carga de btop con el fondo tapado era Steam y el propio btop (NVML la despierta); la dedicada no se suspende nunca por `audio-fix.conf` (`power_save=0` del audio HDMI). Y el driver no suelta sus descriptores hasta que muere el proceso.
- `10586` **El fondo en Hyprland: el mismo módulo como superficie layer-shell** — `hyprland/main.qml` pide una capa `background` por monitor con `layer-shell-qt`; la pausa y el cursor salen del IPC de Hyprland (`src/hyprland.cpp`), el plan se recarga al cambiar el fichero y `recargar()` de `wectl` no busca plasmashell si el fondo de Hyprland está vivo.
- `10596` **El anfitrión** — una `Window` por monitor con `org.kde.layershell` (`LayerBackground`, cuatro anclas, `exclusionZone: -1`); se muestra ya configurada. Medido: nivel 0 bajo waybar, plan en NVIDIA y composición en Intel.
- `10613` **La pausa y el cursor: el IPC de Hyprland** — `.socket2.sock` dispara la revisión de `j/monitors` + `j/clients` con la rejilla de `VentanasEncima`; `j/cursorpos` cada 16 ms, asíncrono, solo sin pausa. El espacio especial abierto tapa el monitor.
- `10644` **Cambiar de plan sin plasmashell** — `Loader` + `VigiaArchivo` (inodo y fecha, porque `wectl` renombra el directorio); `shuffle` probaba cinco escenas por tick hasta que `recargar()` aprendió a ver el pid del fondo de Hyprland.
- `10664` **`wectl` en Hyprland** — las mismas órdenes; el fondo es la unidad transitoria `wallpaperengine-hyprland` porque un hijo del servicio oneshot de la rotación moriría con él; `gpu` reinicia la unidad y se guarda en `~/.config/wallpaperengine/hyprland.json`.
- `10697` **Dos monitores: las dos capas iban al primero** — layer-shell-qt elige monitor con `LayerShell.Window.screen`, no con `Window.screen`, y `Qt.application.screens` da `QQuickScreenInfo`: `Hyprland.pantalla` busca el `QScreen` por nombre. Probado con HDMI y con una salida `headless` en caliente.
- `10727` **Un wallpaper distinto en cada pantalla** — `wectl pantallas mismo|independiente` (solo Hyprland): un plan por monitor en `plugin/contents/pantallas/`, `VigiaArchivo.existe` para caer al compartido, `shuffle` reparte de la misma bolsa y `set` pone el mismo en todas.
- `10734` **Cómo** — `preparar` con destino, `--planes` en el anfitrión, el `Loader` que solo recarga el plan de su monitor y el `existe` hacia abajo cuando `set` borra los propios.
- `10761` **La resolución, que en Hyprland no se leía** — sin `kscreen-doctor` los planes salían al lienzo del autor (hasta 7680×4320); ahora `hyprctl -j monitors`, y cada plan propio a su monitor.
- `10799` **La vara de medir del rendimiento** — `WE_MEDIDAS` en el motor (fotogramas ejecutados, CPU, GPU y copia por intervalo, en sumas crudas) y `tools/medir_vivo.py` (escena fija, sin pausa, `fdinfo` del i915; la NVIDIA no publica `fdinfo`). Ruido medido, regla del 10 % y la línea de base.
- `10806` **Qué vale y qué no** — el fps del HUD no; el cronómetro sí pero salía una vez; `fdinfo` solo para la integrada; nadie contaba los fotogramas ejecutados.
- `10820` **Los dos instrumentos** — la línea `SceneView: medida` y el medidor externo; y el fallo de las dos pantallas con el mismo nombre.
- `10842` **El ruido** — tres medidas de `2788165557`: fps < 0,5 %, CPU/GPU por fotograma hasta 8 %. Un cambio cuenta si pasa del 10 % en tres medidas.
- `10860` **La línea de base** — 163 fps en eDP-1, 110 % de un núcleo, y la copia entre GPUs pesa más que dibujar el plan.

## CLI, rotación y rutas

- `177` **El CLI — `tools/wectl.py`** — `list`/`set`/`shuffle`/`start`/`stop`/`status`; `set` acepta id de Workshop o parte del título.
- `193` **Rotación: por qué es un temporizador y no una opción del plugin** — por qué el «cada x tiempo» no vive en la configuración del fondo.
- `222` **Cambiar la cadencia sin cambiar el fondo, y por qué el mínimo es 1 minuto** — `shuffletime`, y de dónde sale el suelo del intervalo.
- `2242` **Dos `wectl` a la vez se pisaban** — la rotación por systemd cayendo encima de un `set` a mano: los dos construían el plan en el mismo directorio.
- `274` **Dónde está Wallpaper Engine** — el orden de búsqueda de `wepaths.py`: variables de entorno, luego las bibliotecas declaradas en Steam.
- `3944` **Los 19 wallpapers que trae la aplicación: 7 servirían** — vienen sin empaquetar (`scene.json` suelto) y las herramientas filtran justo por `scene.pkg`.

- `4303` **`wectl list` dice de qué tipo es cada wallpaper** — el `type` de `project.json`, normalizado: 24 de 148 lo escriben con mayúscula.
- `4319` **Enseñar también los que no se pueden poner** — un wallpaper que no aparece no se distingue de uno que no está instalado.
- `4337` **El que no es un wallpaper** — `2336642563` trae `category: Asset`: es un paquete de materiales, no un fondo.
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
- `4914` **El personaje calvo: el rig tenía un bloque con nombres que nadie leía** — `attachment` cuelga una capa de un hueso del padre; el nombre está en el bloque `MDAT`, que se saltaba entero.
- `4936` **Dónde estaba el nombre** — el campo de texto del hueso son los límites de la articulación; el formato de `MDAT` y por qué el recuento es u16.
- `4971` **Por qué no basta con hornearlo** — el hueso se mueve hasta 285 px, así que los ejecutores rehacen la traslación por fotograma.
- `9885` **La Vi sin piernas: tres lectores que se quedaban cortos** — `3047352572`: un rectángulo negro, piezas sueltas y un pase perdido; tres arreglos de lectura y la cabeza, que queda abierta.
- `9893` **1. El rectángulo negro: un `.mdl` sin esqueleto** — el formato `0x0000000f` es `0x0180000f` sin huesos ni pesos: 12 campos por vértice.
- `9907` **2. Las piezas sueltas: la cola de cada animación crece con la versión** — 4, 9, 10, 34 y 35 bytes según el `MDLA`; y la animación la elige `animationlayers` por su identificador, no `anims[0]`.
- `9931` **3. Un pase que no compilaba: los combos de `// [COMBO]` existen siempre** — la copia vieja de `pulse` pregunta `#ifndef AUDIOPROCESSING`; WE define los de directiva a 0, los de sampler no.
- `9947` **Lo que NO se arregló: la cabeza** — efectos antes o después de deformar: la Vi pide después y la cabeza del dragón antes; se deja como estaba.
- `10016` **La cabeza de la Vi: los efectos de un puppet van sobre la textura y se deforma al final** — las máscaras de la Vi y del dragón solo tienen sentido sobre la textura; un pase final deforma la malla.
- `10024` **Lo que lo decide: qué tapa cada máscara en la textura** — la de la Vi, la cabeza pintada en el cuerpo; la del dragón, un párpado suelto salvo el ojo.
- `10044` **Por qué la primera prueba pareció decir lo contrario** — el pase final sin mezcla: un párpado transparente sobrescribía la cabeza del dragón.
- `10058` **El binario no lo resolvía** — `_rt_imageLayerAlbedo_` es del camino de la iluminación, no del orden de efectos y deformación.
- `10068` **El reparto** — solo `werender`: malla en reposo en el pase base y un `passthrough` con la mezcla del pase base al final.

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
- `5013` **`step(0.5, nodeNum)`: la norma lo admite y NVIDIA no** — promocionar el argumento entero que no es un literal, y por qué la tabla de tipos va aparte de la de truncación.

- `4089` **La homografía salía transpuesta: `m[i][j]` no es lo mismo en los dos lenguajes** — el único header que construye una matriz por índices, y los 10 efectos que lo incluyen.
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
- `5471` **El fondo de *Lonely Cat* se desliza, y las dos mitades de un arreglo** — un `composelayer` que se queda el fotograma entero y lo desplaza; el mismo fallo explica la banda de arriba y que las olas no cuadren con el gato.
- `5482` **El oráculo: el preview del autor no se mueve** — 0 px en los 38 fotogramas de WE contra 2,2 % de altura por segundo en el nuestro.
- `5495` **Quién lo mueve** — el volcado pase a pase señala uno solo: el `scroll` de una capa cuyo efecto de barras está apagado por una propiedad de usuario.
- `5518` **La causa: la identidad que le damos a una capa passthrough** — `composelayer.vert` dibuja pantalla completa pero muestrea POR LA MVP, y se la damos identidad.
- `5539` **Por qué el arreglo son dos mitades y ninguna vale sola** — la tabla de las tres variantes, y por qué la que se probó en su día tenía que fallar.
- `5559` **Alcance, medido sobre las 129** — 29 capas de 85 tienen rectángulo distinto del lienzo; 27 son `composelayer` en 18 escenas. Arreglado: `_colocacion` ya no fuerza identidad en `composelayer`, y su pase base lleva la MVP real.
- `9521` **Las capas giradas giran en píxeles del lienzo: `object_mvp` y `we_giro_coloca`** — `object_mvp` giraba después de pasar a clip y estiraba en x por ancho/alto toda capa girada de un lienzo no cuadrado; ahora es D · R · E como `object_world` y `particle_mvp`, y `we_giro_coloca` gira por D · R(Δ) · D⁻¹ con el lienzo de la escena, que la línea `giro` lleva detrás porque `canvas` es la resolución de dibujo redondeada. Cambian las colocaciones de las 22 escenas del censo y nada más.
- `9537` **Lo que cambia** — `object_mvp`, la VP de una capa iluminada que pasa a ser la ortográfica, el lienzo de la escena en la línea `giro` y en el `WeGiro` que leen los dos ejecutores, y el `g_EffectModelViewProjectionMatrix` inerte de las partículas.
- `9570` **Lo que se descartó** — girar en píxeles solo las agujas, sacar la proporción de `canvas` (2,0e-5 y 6,3e-5 en vivo), y conservar la fórmula vieja para las partículas.
- `9585` **Lo medido** — 722 capas a 4,4e-16 de ortográfica · mundo y 63 giradas en 22 escenas; el C a 4,1e-8 en tres lienzos y dos locales, y a 1,1e-7 con el plan a 1920x1200 y 1366x768; 46 planes idénticos, 22 con colocaciones distintas y 61 solo con líneas inertes; la aguja de las 03:00 a −0,11 % y +0,28 % de su `size · scale` (main, +77,5 %); 0 regresiones de luz.
- `9649` **Lo que queda** — un autor que compensara la deformación, y lo que WE pone en el uniform de efecto de una partícula.

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
- `10118` **El cielo de After Sunset: `LightingV1` por clase, el exponente de cada luz y el fondo opaco** — `3210875135`: cielo gris plano y cuadrados; tres causas generales.
- `10124` **1. El cielo sin luz: `LightingV1` no sabía de tubos** — la reconstrucción tenía cuatro puntuales fijas; ahora un array por clase, como el generador del binario.
- `10143` **2. El cielo oscuro: `exponent` es de la luz** — el lector de WE lo guarda en `[luz+0x2e8]`; 1,06 en vez de 2 fijo.
- `10153` **3. Los cuadrados: el fotograma empezaba transparente** — `clearcolor` opaco; el `blur` divide por el alfa y cada sprite dejaba su quad.
- `10172` **Y lo que no era un fallo: la intro** — un `color_grading` con fundido de entrada de 5 s.
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
- `4016` **El anillo del vórtice, y las dos velocidades que faltaban** — una captura del escritorio de Windows como oráculo; tres cosas mal a la vez en la misma escena.
- `4024` **La tangente es una cuerda: el radio crecía solo** — un 65 % por vida; se arregla girando la posición, no empujándola.
- `4041` **`distanceouter` es hasta dónde llega, no dónde se satura** — la medida que lo decide es la PENDIENTE de las estelas: radiales, no tangenciales.
- `4060` **El emisor tenía una velocidad y nadie la leía** — `speedmin`/`speedmax` de `sphererandom`: la única velocidad de 12 sistemas del corpus.
- `4345` **Las estrellas no parpadeaban: `colorrandom` sin `max` sortea hasta negro** — el oráculo se monta restando el fondo a la captura; dos fallos distintos con la misma medida.
- `4360` **El tamaño del sprite: el brillo explicaba una parte, no toda** — por qué el rayo NO sirve de contraste, y qué queda abierto.
- `4385` **La pista estaba en un campo escrito de más** — 158 objetos escriben `max` igual a `min`; por eso el defecto de `max` es negro y no `min`.
- `4402` **El ritmo implícito estaba en el extremo, y se comía el `instanceoverride`** — `maxcount/vida` deja el depósito lleno, que es el percentil 76 del corpus, no la costumbre.
- `4433` **La otra mitad era el bloom** — el halo que la resta enseña alrededor de todo lo brillante; lo piden 33 de las 129.


- `5093` **Los destellos de la `City`: qué se mueve, y por qué no se toca nada** — el desglose de lo que se mueve en una escena de destellos: ~900 parpadean sin desplazarse, 170 derivan y 20 fugaces cruzan.
- `5107` **Los dos candidatos a fallo, y por qué ninguno lo era** — `turbulence` como aceleración la respaldan las plantillas de WE con su `drag: 4`; el ritmo implícito no se puede bajar sin apagar el polvo y las brasas.
- `5133` **Lo que se probó y se retiró: frenar el reloj de la simulación** — la vía medida (x1,00 / x0,55 / x0,26) por si algún día se pide, y la trampa de comparar por el reloj de pantalla.

- `5161` **La turbulencia, a la mitad: una desviación pedida, no un arreglo** — el rotacional del ruido tiene RMS 0,980, así que `speed` ya era la aceleración: bajarla es preferencia, y vive en `FACTOR_TURBULENCIA`.
- `5190` **`FACTOR_TURBULENCIA = 0.5`** — por qué solo el operador y no el inicializador, por qué en Python y no en el `.c`, y a cuántas escenas alcanza.
- `5209` **Lo medido, antes y después** — camino y desplazamiento neto por vida, siguiendo cada partícula por vecino más próximo.

- `6751` **Los ejes de la turbulencia: `forward` gira alrededor de `right`, y `up` no se lee** — leído en `wallpaper64.exe` y sin aplicar: WE no muestrea un campo en el espacio, gira `forward` (`0 1 0`) alrededor de `right` (`0 0 1`) un ángulo de ruido 1D en el tiempo; cambiaría las 152 piezas, no solo las 5 con ejes.
- `6768` **Lo leído, con direcciones** — bloque de tipo 9; defectos y desplazamientos de cada campo (rapidez 0,5–1 o 100–250, `phasemax` 0,1, `scale` 1, `offset` escalar); `up` no aparece ni en el lector ni en los defectos.
- `6792` **La regla** — θ = π·`scale`·snoise1((fase + reloj)·`timescale`) + `offset`; `right` normalizado, `forward` no (`0 0 0` da velocidad nula); la misma matriz que `velocityrandom`. Con `audioprocessingmode` distinto de 0 (2 piezas), el audio multiplica el ancho de la fase: se omite, no hay audio.
- `6861` **Por qué no se aplica** — el defecto de WE no es la identidad de hoy, y `offset`, la rapidez y la fase tampoco casan; aplicarlo solo a los que declaran ejes darían dos semánticas para la misma pieza. Lo que haría falta para sustituir el inicializador; hecho después.
- `6672` **Lo medido** — rumbo de la pieza aislada, hoy contra la regla: 12 de 18 fuera de ±15°; 1131 de 1131 planes idénticos en las 129 y `verifica_exe.sh` 154 ok.
- `7077` **La turbulencia con la regla de WE: `turbulentvelocityrandom` deja de muestrear nuestro ruido** — la regla leída sustituye al inicializador en las 152 piezas; `ESCALA_RUIDO` queda solo para el operador y `desplazar_ruido` desaparece.
- `7091` **El booleano es «la escena es ortográfica»** — bit 10 de `[contexto+0x118]`, que el cargador enciende con `orthogonalprojection`; las 129 lo son, así que la rapidez por defecto es 100–250.
- `7120` **`[obj+0x130]` son los segundos de la escena** — el mismo contexto en `renderizador+0x10`; el reloj que suma el dt y que `remapinitialvalue` llama `runtime`.
- `7031` **Cómo queda aquí** — 13 floats en el `.psys`, `wescene.ortografica`, `snoise1` y Rodrigues en el `.c`, el reloj de la escena en `s->reloj`.
- `7173` **Lo que cambia en el aspecto** — lo que nace a la vez sale paralelo: 269 de 271 sistemas en chorro, contra 114.
- `7039` **Lo medido** — 18 de 18 rumbos a ≤ 15° (la base, 6), Flare_Sparks quieto, 95 de 98 a ±10 % de 175, planes idénticos fuera de la pieza, `verifica_exe.sh` 254 ok.

## Bloom

- `4441` **El bloom son tres shaders de WE y un objeto más** — la cadena no había que escribirla, había que deducirla de los nombres.
- `4458` **`g_TexelSize` es el texel de PANTALLA, y lo dice la captura** — tres lecturas posibles con un factor 8 entre ellas; el radio medido cae limpio en 16 px.
- `4479` **El umbral va DESPUÉS de promediar, y eso se ve** — por qué el bloom de WE rodea zonas brillantes y no puntos sueltos.
- `4487` **No hay que tocar los ejecutores** — va como un objeto más que se compone sumando; los buffers ya sabían sacar su resolución del nombre.
- `4501` **Lo medido sobre las 129** — 39 escenas, la mediana contra el preview de 0,171 a 0,135, y la primera pasada sin escenas apagadas.

## Resolución

- `4668` **El lienzo del autor no es un límite de resolución: 38 escenas salían ampliadas** — el `min(1.0, ...)` hacía que el blit final las agrandara; el diario del motor en vivo lo traza.
- `4698` **Lo medido** — 38 de 129, mediana x1,11 y hasta x3,40; y por qué `test_luminancia` no vale como oráculo aquí.
- `4713` **Lo que NO explica** — la City ya se dibujaba 1:1; su destello sigue pendiente.

## Sistemas hijos

- `4720` **Sistemas hijos: `eventspawn`** — 232 sistemas con hijos en 61 escenas; aquí solo el que estalla donde muere el padre.
- `4728` **El hijo es un objeto hermano, no un pase más del padre** — trae su propio material, así que se devuelve como objeto y se ata con `psyspadre`.
- `4742` **La lectura del formato** — el depósito sale de `children` y la ráfaga del preset; el emisor libre del hijo se apaga.
- `4754` **Por qué se simulan en tándem, y no uno detrás de otro** — una cola diferida haría estallar el sistema entero de golpe tras una recuperación de 60 s.
- `4774` **Lo medido** — 0 a 60–92 partículas; 10 escenas, 17 hijos; y por qué `test_luminancia` no vale como oráculo aquí.
- `4787` **Lo que NO arregla** — las manchas van de 23 a 74 pero siguen en 5–8 px donde WE tiene el pico en 3–4.
- `5058` **Un puntero donde hacía falta una lista: el hijo `eventspawn` congelado** — con dos hijos el segundo pisaba al primero y lo dejaba sin dar pasos; una escena del corpus.
- `5600` **Los hijos de un sistema: cuatro tipos, y `eventspawn` estaba leído al revés** — lo que se había implementado como `eventspawn` era `eventdeath`; `static` y `eventfollow` entran.
- `5607` **El oráculo: lo que la propia aplicación dice y trae** — la interfaz de WE nombra cuatro tipos y su documentación los define; los fuegos artificiales usan `eventdeath`.
- `5632` **Sin `type` es `static`** — `ember` → `emberglow` va sin tipo y con `static` más todos los defectos: 320 entradas en 51 escenas, no 34.
- `5647` **Qué es cada uno, en el motor** — `static` es un sistema colocado con `parent`; los de evento sueltan su `instantaneous`; `eventfollow` emite donde está su partícula y deja estela.
- `5680` **El reparto** — la línea `psyspadre` con modo, instancias, probabilidad y escala; `nace()` como único punto de nacimiento, y por qué hacen falta los nietos.
- `5707` **Lo que se deja fuera, a propósito** — `angles` de la entrada, `controlpointstartindex`, `flags` y las piezas `inherit*`: sin caso en el corpus con el que medirlos.
- `5725` **Lo medido** — 275 hijos en 60 escenas; la prueba de contrato y que muerde; 0 regresiones sobre las 129.
- `9173` **La instancia de un hijo de evento: lo leído en wallpaper64.exe** — un `eventspawn`/`eventdeath` con `rate` emite para siempre donde lo creó el evento, sin ráfaga si no declara `instantaneous`, y solo hay `maxcount` de la entrada a la vez; 9 entradas en 4 escenas.
- `9195` **Lo leído, con direcciones** — tope de instancias, posición fija, emisión, apagado del emisor, liberación de la instancia y los defectos (`rate` 10, `instantaneous` 0).
- `9247` **Lo que se descartó** — «emite hasta que muere la partícula» es solo de `eventfollow`; no se satura porque el tope de instancias corta.
- `9258` **El reparto** — sin campo nuevo: ráfaga 0 sin `instantaneous` en `werender.py`, y las `Instancia` de `fijas` en `weparticles.c`.
- `9272` **Lo medido** — 55/55 direcciones; la prueba de contrato muerde; `Flare_Smoke` de 3063 a 206 vivas; 125/125 planes idénticos; 0 regresiones de luz.
- `9328` **Lo que queda** — el tope de instancias de los hijos solo `instantaneous`, el puesto de `eventfollow` que se libera antes que en WE, `delay` y emisión periódica.

## Emisores

- `4806` **`distancemax` sin declarar no es cero: la lluvia salía toda del mismo punto** — el tercer campo con el mismo patrón; 6 presets-emisor en 7 escenas.
- `4819` **Por qué 512** — el corpus escribe el 0 explícito 153 veces y `exampleturbolence` obliga a que el defecto sea ≥256.
- `4834` **Lo medido, y lo que queda torcido** — dejan de pegarse al borde, pero el 75 % nace fuera por el `directions: "1 5 0"`.
- `6359` **Varios emisores: emiten todos, al mismo depósito** — 2 sistemas en 2 escenas, con un segundo `sphererandom` vacío; una línea `emit` por emisor y un crédito por emisor en `src/weparticles.c`.
- `6372` **Lo leído y lo supuesto** — los defectos del segundo emisor son los leídos; que el `rate` del override multiplique a cada uno y que el depósito sea común, supuesto.
- `6401` **Lo hecho** — `Sistema.emisores`, `Emisor em[4]` y `we_psys_vivas`; un `.psys` de un emisor sale y se lee igual.
- `6418` **Lo medido** — 1412 de 1414 `.psys` idénticos y el simulador idéntico sobre ellos; `fog2` se llena con el segundo emisor; 0 regresiones.
- `6455` **`flags: 2` no coloca el emisor: es una partícula por fotograma, y al cursor lo lleva el punto de control** — la hipótesis del rastro del ratón, refutada en `wallpaper64.exe`; el render no se toca.
- `6473` **Lo que hace WE, con direcciones** — `flags` en `+0x3c`, `controlpoint` (defecto 0, tope 7) en `+0xe0`/`+0x98`, el bit 1 como `min(cuenta, 1)` y el centro de emisión en el punto de control, con o sin el bit; el bit 0 es `sign` y el sorteo gira con el punto si `controlpoint ≠ 0`.
- `6538` **El corpus con la regla leída** — 17 emisores con el punto atado al cursor en 12 escenas, 6 de ellos sin el bit (`mouse_trail_1`, `shurikencursor_1` con `controlpoint: 1`); 0 con offset.
- `6572` **Lo que queda, para hacerlo bien** — leer `controlpoint` y centrar `emite` en su punto, girando el sorteo con la matriz del punto; sin ratón, el offset; el tope de una por fotograma, sin leer; la unión del `rope`, cerrada después.
- `6610` **Lo medido** — `verifica_exe.sh` (5 cadenas y 57 instrucciones, 0 fallos), `censo_cp_emisor.py` y ningún diff en el render.
- `6621` **Todo emisor nace en su punto de control, primer trozo: la traslación** — `controlpoint` al final de `emit` solo si no es 0, y `emite` centra en `cp[controlpoint]` + `origin`; los hijos colgados y los repartos por puestos, como estaban.
- `6634` **Lo hecho** — `_punto_del_emisor`, `Emisor.punto`, el centro de las cintas en `psysprobe` y la prueba 10 de `test_weparticles.py`, en `C` y `es_ES`.
- `6672` **Lo medido** — de 2414 `.psys` cambia una línea; planes idénticos; los 17 nacen en el puntero; 2414 sondas sin ratón y 2388 con él, idénticas; 0 regresiones de luz.
- `6731` **Lo que queda fuera** — el giro del sorteo con el punto, el tope de `flags & 2`, el cosido del `rope` (cerrado después), el punto antes del primer movimiento y `mapsequence*`.

## Cintas y movimiento

- `4861` **La cola de una cinta sale de `length`, no de un 8 fijo** — el defecto de `segments` pisaba el campo declarado; 68 de 74 cintas.
- `4882` **`gravity` es una aceleración, y lo demuestran los fuegos artificiales** — por qué no se endereza la caída, y qué hace que la parábola cante.
- `6045` **`upright` en una cinta: WE la orienta como a un sprite, y da la base de siempre** — la anchura de la cinta la pone `g_OrientationForward`, no nuestro constructor; cierra el último aviso de `orientation` del corpus.
- `6064` **El lector: tres modos y una base** — `0x1401c22e0`, compartido por las cuatro fábricas de renderer; `axis` nulo es (0, 1, 0).
- `6083` **La rutina que pone los tres uniforms, igual para los cuatro renderers** — `0x1402298b0`: `screen`, `upright` y `fixed`, y la normalización final.
- `6105` **Por qué en el corpus no cambia nada** — `(c × u) × u` es `−c` si `u` no tiene z; *Vapor 1* y los `Rain_Splash` con `flags: 1`.
- `6122` **Lo hecho** — `_orientacion` con una sola regla para sprites y cintas; ni plan ni ejecutores.
- `6136` **Lo medido** — 0 avisos (antes 1); 1131 de 1131 `plan.txt` y `.psys` idénticos en las 129; PNG idéntico; 0 regresiones.
- `7677` **Cómo cose WE un `rope`: una sola cinta que une las partículas vivas, de la más vieja a la más nueva** — `rope` no es una cinta por partícula: une las vivas en el orden en que nacieron, y su fábrica no lee ni `length` ni `segments`.
- `7689` **Lo que hace WE, con direcciones** — bloque de tipo 3 frente a 4, la rama `0x1402369ed` del bucle de dibujo, el constructor `0x140230919` y la lista `sistema+0x218`, que crece al nacer y se compacta al morir.
- `7729` **Lo hecho** — `orden` y `construye_cuerda` en `src/weparticles.c`, sin duplicados con un `instantaneous` repetido; `cinta 1 0 0` en el `.psys`; el plan solo cambia en el `g_RenderVar0` del `rope`; la prueba 11 de `test_weparticles.py`.
- `7756` **Lo medido** — 71 de 71 en el binario; `6·(N−1)` vértices, cosidos y en orden de nacimiento; 113 planes y 964 `.psys` idénticos, y en las 16 con `rope` solo 38 líneas `g_RenderVar0`; 0 regresiones de luz en las 16.
- `7799` **Lo que queda fuera** — `trailLength` en régimen, `uvscrolling`, la cuerda con dos puntos en el mismo sitio, el tope de `flags & 2` y la curva (hecha después).
- `8176` **La curva de un `rope`: la Bézier de `subdivision`, hecha en la CPU** — `subdivision` (4 si falta, topado a 32) es el `TRAILSUBDIVISION` del `.geom`; `construye_cuerda` parte cada tramo en `sub + 1` subquads con su curva, su ancho y su UV.
- `8188` **Lo que hace WE, con direcciones** — los defectos del `rope` en `0x1401c0c90` (`subdivision` 4, `uvsmoothing` verdadero), el tope en `0x1401cffbd` y el combo en `0x1401d2aa2`.
- `8207` **El `.geom`, y cómo se lleva al quad sin geometry shader** — controles `fin − R(inicio)` e `inicio + R(fin)`, tamaño `|R|`, y `trailLength`/`trailPosition` que dan la UV de WE en cada punto.
- `8246` **Lo hecho** — `_subdivision` y el cuarto número de `cinta`; `tramo_curvo` y el búfer con `sub + 1`; el plan no cambia; la prueba 12.
- `8262` **Lo medido** — 65 de 65 en el binario; la curva a 3e-06 del `.geom`; con 0, la cuerda de main byte a byte; 113 planes y 964 `.psys` idénticos; *Vapor* cambia un 1,145 % de los píxeles con flechas de menos de una unidad; 0 regresiones.
- `8327` **Lo que queda fuera** — `ropetrail`, el ojo en perspectiva, `uvsmoothing` verdadero por defecto y el tramo que da media vuelta.

## El ratón

- `5232` **El ratón entra en la escena: un puntero, cuatro consumidores** — quién lo mira (46 escenas de partículas, 29 de cámara, 13 pases de efecto) y por dónde entra un dato que cambia cada fotograma.
- `5245` **Quién lo mira, contado antes de escribir nada** — la tabla que decide el diseño: las partículas son el consumidor grande.
- `5258` **El puntero viaja como el tiempo: un marcador en la plantilla** — `@PUNTERO_X@`, `psyspuntero` con la afín ya resuelta, y por qué «sin ratón» no es «ratón en el centro».
- `5290` **De dónde sale el ratón en el escritorio** — `HoverHandler` y no `MouseArea`, para no quedarse los clics; y lo que Wayland no da.
- `5306` **La pantalla no es la escena** — el encaje recorta, así que el píxel bajo el ratón no es el píxel de escena; `encajado()` sacado del blit.
- `5316` **La `y` del uniform, que es donde estaba la trampa** — los flips de los shaders de WE y la rama `GLSL` que ya estaba elegida; sin flip.
- `5342` **Lo que sí se midió** — tres sistemas con origen, escala y giro distintos cayendo en el mismo punto de la pantalla; y el contrato Python↔C.
- `5394` **Lo que la regresión dice: 0 regresiones y una reordenación honesta** — las 129 antes y después; las once que cambian son relojes, menos una, y esa cambia porque el operador nuevo mueve las fases.
- `5420` **`g_ParallaxPosition` es el puntero con retardo, y nada más** — por qué no lleva `amount` ni `mouseinfluence`: dos escenas con el efecto declaran amount 0. Corregido después: es el P de la cámara, con la influencia.
- `5444` **Lo que queda, medido** — la cámara (falta el número que lleva `amount` a píxeles), el emisor con `flags: 2` y el puntero bajo las ventanas.

## La cámara

- `5919` **El parallax de cámara: la fórmula estaba en el motor, y mueve las capas también en reposo** — `cameraparallax` en 29 escenas, leído en `wallpaper64.exe` en vez de medido contra WE corriendo.
- `5928` **Cómo se encontró** — la tabla de propiedades de `general` y la de la capa dan los desplazamientos; de ahí, las lecturas.
- `5939` **Lo que hace WE** — el punto P entre el centro y el ratón, su suavizado, y la traslación `amount × depth × (origin − P)` con la raíz.
- `5964` **La sorpresa: con el ratón en el centro, las capas ya están desplazadas** — comprobado contra el preview de `2262142032`: el reloj a unos 10 px y el letrero que WE deja fuera.
- `5980` **Cómo está hecho aquí** — el término en reposo horneado en `transform_absoluto`; el del ratón en la línea `paralaje` de los dos ejecutores.
- `6008` **Lo medido** — 0 regresiones; correlación con el preview: 4 se acercan, 2 se alejan, 23 igual.
- `6026` **Lo que queda** — `g_ParallaxPosition` (ya hecho), `escena[+0xf0]`, la marca que invierte la x y `camerashake` (ya hecho).
- `6186` **El temblor de cámara: también estaba en el motor, y no es ruido** — `camerashake` en 6 escenas: una curva de Lissajous determinista leída en `0x140199580`, que mueve la cámara entera; línea `temblor` y `src/wetemblor.c` en los dos ejecutores.
- `6198` **Cómo se encontró** — `+0x328/+0x32c/+0x330` y el bit 7 de `+0xe0` en el lector de `general`; los defectos en el constructor; el reloj es el del renderizador.
- `6234` **Lo que hace WE** — `velocidad² · t`, `(cos s, sin 1,333·s)`, la amplitud por `0,01 × alto`; la rugosidad solo deforma la norma; y `escena[+0xf0]` es el ojo.
- `6262` **Cómo está hecho aquí** — `temblor` en la cabecera, `tiembla` por capa, acoplado al punto del parallax; por qué las `passthrough` se quedan quietas (con ellas se movía el doble).
- `6295` **Lo medido** — 138 de 144 planes idénticos; desplazamiento medido contra predicho a ±0,1 px en cinco escenas; 0 regresiones.
- `6339` **Lo que queda** — `3053927686` un 7 % largo, el marco de las `composelayer` pequeñas y el `eye` fuera del origen (cerrado).
- `6938` **El `eye` de la cámara no llega al parallax: WE lo pone a cero en las escenas ortográficas** — leído en `wallpaper64.exe` antes de aplicarlo: el cargador borra el `eye` del json en las 47 escenas que lo declaran; no cambia el render.
- `6768` **Lo leído, con direcciones** — la cámara declarada (`+0x118`) y la vigente (`+0xf0`), el cero de `0x14018866b`, de dónde sale el ojo cada fotograma y la suma en `0x140189c18`.
- `6998` **Lo que dicen los previews** — con el `eye` sumado la correlación empeora en 7 de 11; el reloj de `2262142032` mejora, pero por el encaje global.
- `7031` **Cómo queda aquí** — un comentario en `parallax_de_camara` y `prueba_parallax_de_camara` con el `eye` declarado.
- `6902` **Lo medido** — `verifica_ojo.sh` sin fallos, 129 planes idénticos, 137 raíces sin cambio y la luz de las once igual.
- `7063` **Lo que queda** — los objetos cámara (`3521337568`) y las escenas con `paths`.
- `7244` **`g_ParallaxPosition` es el punto P de la cámara, no el puntero con retardo** — el `switch` de uniforms encontrado en `wallpaper64.exe` (índice `0x6b`, tabla de dos niveles): `clamp(P/lienzo)` con la influencia y la y hacia arriba, y el centro si `cameraparallax` está apagado; en vivo sale de `m_camara`.
- `7262` **Lo leído, con direcciones** — la tabla de nombres, el enlace, el `switch` y su caso (`0x1400d9e90`, `contexto+0x9c`), el 0,5 del cargador, el bit 8 de `+0xe0` y la escritura en `0x140189cbe`.
- `7325` **Lo que cambia en el corpus** — las 6 con `depthparallax`; las dos de influencia negativa iban en x al revés y entre 3,7 y cinco veces más fuertes.
- `7345` **Cómo está hecho aquí** — `posicion_de_parallax` en `_fotograma`, el centro sin marcadores en los pases que lo leen con el parallax apagado, y `m_camara` acotado en vivo.
- `7191` **Lo medido** — 57 direcciones sin fallos, 24 de 24 valores contra la regla, la prueba que cae sin la influencia y con la y al revés, 1131 ficheros idénticos sin ratón.
- `7402` **Lo que queda** — el ojo (el temblor) no entra offline, las marcas `0x200200` y `0x800` del contexto, y verlo en el escritorio.
- `7414` **El parallax sigue al ratón en tiempo real: el cursor lo da KWin, y el retardo de WE se queda para el temblor** — al fondo le llegaban 1–5 posiciones/s (ventanas maximizadas apiladas; el hover no llega a plasmashell); `CursorKWin` pide el cursor global a KWin por D-Bus: 18–40/s. Y la parte del ratón de `m_camara` con 25 ms en vez del retardo de WE (decisión del usuario).
- `7421` **La que importaba: al fondo no le llegaba el ratón** — 1–5 posiciones/s pegadas al panel con ~42 fps; el `HoverHandler` en la raíz no bastó; `CursorKWin` y su script de KWin (enteros por D-Bus): 18–40/s en toda la pantalla.
- `7457` **La otra: el retardo de WE** — 300–883 ms hasta el 95 % con `(1 − delay/3)·10·dt`; la parte del ratón a 25 ms, la del temblor con el de WE.
- `7487` **Partículas con perspectiva: el bit 0x4 del `flags` del sistema es otra cámara, no otra simulación** — «Perspective rendering» en 153 sistemas de 58 escenas: leída en `wallpaper64.exe` la cámara que WE les pone en una escena ortográfica (ojo a `alto / (2 tan(fov/2))`, `perspectiveoverridefov` o 95°, cercano 5); va en la MVP del pase, sin tocar C.
- `7498` **Qué bit es cuál: la tabla del editor** — `wallpaperui.exe`: 0x1 worldspace, 0x4 perspectiva, 0x8..0x80 «disable overrides» (ninguno en el corpus); el 0x2 no tiene casilla.
- `7518` **Lo que hace WE, con direcciones** — `flags` → descriptor+0x8 → sistema+0x20; el `>> 2 & 1` del dibujo, `0x1401e5b60`, la `PerspectiveFovRH` de z invertida del dispositivo y de dónde salen fov, centro y aspecto.
- `7345` **Cómo está hecho aquí** — `perspectiva 1` al final del `.psys`, `particle_mvp_perspectiva` en `werender.py`; los ejecutores heredan la matriz.
- `7366` **Lo medido** — 149 direcciones sin fallos; 140 `.psys` marcados de 153 (13 invisibles); 71 escenas idénticas a main; los copos de 1,0 a 6,4 px por unidad; luz sin regresiones (los relojes, con la hora fija).
- `7402` **Lo que queda** — el bit 0x1 (worldspace) y el 0x2; márgenes, espejo y aspecto del destino; el ojo de las estelas y las cintas.

## Valores por defecto de las partículas

- `5768` **Los valores por defecto estaban en el binario: el giro, la caja, el ritmo y el sesgo** — cuatro cabos de partículas: uno lo cierra la documentación y tres el código del motor de WE.
- `5776` **El sesgo de `exponent`: confirmado, no se toca nada** — la documentación dice que de 2 en adelante sesga hacia Min: es `pow(t, e)`.
- `5786` **Dónde guarda WE sus valores por defecto, y cómo se leen** — desensamblar `wallpaper64.exe`: cada defecto se carga junto a su campo, y la fábrica dice de qué pieza es; la tabla completa.
- `5830` **La «hoja girada» del rayo era un giro, y afecta a 66 escenas** — `rotationrandom` vacío gira de 0 a 2π (112 sistemas); `angularvelocityrandom` vacío, ±5 (18).
- `5840` **La caja es `256 256 0`, y el 40 % que sigue fuera es del preset** — las fugaces que cruzan pasan del 28 % al 60 %; `distancemax` es el semieje, lo dice la muestra de `rain_splashes`.
- `5864` **El ritmo: 10 por segundo, no el 48 % del depósito** — sustituye al ritmo implícito en 68 sistemas; en la `City`, más fugaces y no menos.
- `5887` **`directions` es `1 1 0`** — solo cambia la z, que entra en el ruido de la turbulencia.
- `5892` **Lo medido** — cinco pasadas, 0 regresiones; `3097749052` se mueve por sorteo; los rayos girados y las fugaces cruzando en la `City`.

## Pendiente

- `4528` **Pendiente: tres cabos de las partículas, medidos y sin cerrar** — el diámetro del destello, la lluvia que sale de un punto y la estela corta.
- `4534` **1. Los destellos: NO es el tamaño, y el factor 0,5 está probado y descartado** — el `preview.jpg` como oráculo a 0,982; los sprites grandes ya coinciden.
- `4580` **1a. Descartado: no es la resolución, y cuidado con medir anchos** — el área va como la escala²; la mediana de anchos a baja resolución es ruido.
- `4599` **1b. Lo que falta son los sistemas HIJOS** — `halo_4` con núcleo del 8 % explica el pico de 3–4 px; 232 sistemas con hijos en 61 escenas.
- `4629` **2. La lluvia de estrellas sale toda del mismo punto** — `boxrandom` sin `distancemax`: el mismo patrón que `rate` y que el `max` de `colorrandom`.
- `4649` **3. La estela es corta y gorda; debería ser fina y larga** — el defecto de `segments` pisa el `length` que el autor sí escribe; 68 cintas de 74.

## Texto

- `3374` **Un punto son 4,137 unidades de lienzo, y eso no lo dice el formato** — una capa de texto es el único objeto sin geometría ni material.
- `3384` **La unidad no está en el formato, pero la caja sí** — adivinar por DPI da candidatos plausibles y todos distintos; de dónde sale el número bueno.
- `3419` **Por línea, no por glifo** — menos código y mejor tipografía: PIL resuelve kerning, ligaduras y shaping de una vez.
- `3432` **Tres sitios de donde sale una fuente, y uno no está aquí** — 47 dentro del `scene.pkg`, 37 de la instalación de WE, 83 del sistema.
- `3447` **El ejecutor no se entera de que hay texto** — ni una línea de C: los quads viajan por la directiva `mesh` que ya existía.
- `3462` **Lo que la distribución ahorró** — mirar los valores y no los recuentos quita más trabajo del que deja.
- `3482` **Lo que se ve** — 25 escenas cambian, 0 regresiones.
- `3495` **Y el muro: 148 de los 167 son JavaScript** — 133 llaman a `new Date`: son relojes y fechas, y el texto dibujado no es el que el autor quiso.
- `4117` **Una capa de texto se ancla por su alineación, no por su centro** — no trae `alignment`: trae `horizontalalign` y `verticalalign`, y dicen lo mismo.
- `4139` **Y lo que faltaba: la hora era la del autor** — lo que se pensó entonces, que resultó ser la mitad de la historia.
- `4154` **La hora de verdad: interpretar el script sin un motor de JavaScript** — el plan es una foto, así que lo que viaja en él es el FORMATO, no la cadena.
- `4161` **Por qué no vale con ejecutarlo una vez** — cambiaría una hora congelada de 2021 por una congelada de hoy; el reparto en tres piezas.
- `4176` **Un intérprete, no un motor** — el vocabulario de los 51 scripts, contado; y `createScriptProperties()`, que llevó de 6 a 129.
- `4205` **Deducir el formato: cortar siete muestras a la vez** — las dos maneras de equivocarse: una sola cadena es ambigua y diferenciar cadenas cortas miente.
- `4224` **Los nombres no se adivinan: se reconocen** — están escritos en el script; hacen falta TRES muestras por valor o se cuela el campo vecino.
- `4241` **Lo que da la garantía es la comprobación, no la deducción** — ~1050 instantes; con una diferencia se descarta y la capa no se toca.
- `4257` **El alfabeto, y lo que se pierde** — rasterizar glifo a glifo en vez de por línea, y el kerning que eso cuesta.
- `4278` **Y la locale, otra vez** — `strtof` dentro de plasmashell deja el alfabeto a cero sin un solo error por medio.
- `7822` **Relojes de varias líneas: el salto viaja al plan y `wereloj` apila renglones** — el `SATURDAY` de `2946362143` empieza por `\n`; la ruta del reloj apila renglones como la estática, de 123 a 124 relojes.
- `7833` **Lo que cambia** — el `\n` escapado en el plan, el `espaciado` al final de la línea `reloj`; el atlas de los relojes de una línea no cambia.
- `7860` **Lo que se descartó** — la caja del quad engaña: `getbbox` de Pillow cuenta el espacio final; se compara la tinta. Y `dayFormat`, sin tocar.
- `7944` **El tope del atlas de un reloj: el renglón que se escribe y un alto máximo** — el tope de ancho estimaba una `W` por glifo y dejaba la 217 de `2946362143` a 160 px de em; ahora se mide renglón a renglón (11 capas suben, ninguna baja) y hay un tope de alto de 16384.
- `7958` **Lo que cambia** — avances glifo a glifo sobre `Formato.cadenas()`, al px de partida; `ALTO_ATLAS_MAX` rebaja la em si la columna se pasa (en el corpus, ninguna).
- `7984` **Lo que se descartó** — medir con `getlength` del renglón, que mete un kerning que el reloj no dibuja; y un tope de alto de 8192, que ya bajaría un atlas de main de 9053 px.
- `7998` **Lo medido** — 218,3 → 278,1 MB de atlas a 1920x1200 (+50,0 en `3462491575`); el más alto, 10550 px frente a los 16384 de Mesa, también en 4K; luz sin regresiones con la hora fija.
- `8078` **Desestructurar, `Boolean` y `engine.registerAsset`: seis relojes más** — tres huecos de JavaScript en `wescript`, ninguno propio de una escena; de 124 a 130 relojes, y `engine` solo con `registerAsset`.
- `8099` **Lo que cambia** — el patrón `[a, , c]` en las declaraciones, `Boolean` como `!!v` y un `Motor` cuyo único miembro devuelve un recurso opaco.
- `8122` **Lo que se descartó** — un `engine` permisivo: el contador de fps de `3238423642` suma `engine.frametime` y pasaría por reloj.
- `8131` **Lo medido** — el listado de main a la rama son seis líneas añadidas; `tools/test_wescript.py`; luz sin regresiones con la hora fija y nada fuera de las tres escenas se mueve.
- `8168` **Lo que sigue sin reloj** — `import`, la expresión regular, los otros miembros de `engine` y la `Date` de `3597772384`, que lanza «a número».
- `8791` **El kerning de los relojes: los pares del alfabeto viajan al plan** — la pluma glifo a glifo perdía hasta 0,368 em en 27 capas de 11 escenas; los pares del alfabeto van al plan (`relojkern`) y `wereloj.c` los suma: 0 em contra raqm en los 130 relojes.
- `8811` **Lo que cambia** — `_pares_del_alfabeto` y `_plumas` en `wetext`, la línea `relojkern` aparte para que un ejecutor viejo la salte, y `wereloj.c` leyéndola bajo la locale C.
- `8837` **Lo que se descartó** — HarfBuzz en el ejecutor; el miedo a los espacios (el 0,368 em de «| S A T U R D A Y |» son pares letra-espacio); ligaduras, que en el corpus no hay.
- `8850` **Lo medido** — 0 em en ancho, pluma y origen; 117 planes idénticos y 12 con pares, donde además solo cambia la caja del reloj; luz sin regresiones con la hora fija; ningún aviso nuevo.
- `8345` **Una hoja de sprites cuyo fotograma elige la hora: el indicador AM/PM** — un script de `visible` llama a `setFrame` con la hora; `wescript` da la tabla de 24, el plan lleva la hoja y `wereloj.c` pone los uniforms en los dos ejecutores. Solo cambia `3299228616`.
- `8363` **El censo** — 39 scripts con `setFrame` fuera del texto y por qué solo 30 dependen de la hora; las 56 capas con hoja animada en 10 escenas, 37 con `SPRITESHEET` (53 contando las que lo declaran en minúsculas) y 12 de varias imágenes.
- `8399` **Lo que cambia** — `thisLayer.getTextureAnimation().setFrame`, la línea `hojahora`, y el volteo: los uniforms de WE no se suben tal cual sobre una textura volteada.
- `8436` **Lo que se descartó** — encender `SPRITESHEET` o reproducir por `frame_time` las hojas sin script, y reconocer el script por su texto.
- `8445` **Lo medido** — 09:00 y 15:00 con `es_ES` a 1e-6; de las 129 solo cambia un plan; el recorte de la capa difiere entre AM y PM en la rama y es idéntico en main.
- `8482` **Lo que queda** — ~~reproducir por `frame_time` y si WE enciende `SPRITESHEET` solo~~, hecho en el trozo siguiente; ~~las de varias imágenes~~, hechas las 7 sin script; `setFrame` movido por clics.
- `8501` **Los combos van en mayúsculas y la hoja corre por `frame_time`: lo leído en wallpaper64.exe** — el censo buscaba `SPRITESHEET` y 16 capas lo declaran como `spritesheet`; WE pasa los nombres de combo por `toupper` y avanza la hoja con el paso de `g_Time`. Las 4 hojas de una imagen sin script de `2262142032` corren; las de varias imágenes, quietas en el fotograma 0.
- `8524` **Lo leído, con direcciones** — `toupper` en el lector de pases (`0x140154480`); el avance al enlazar la textura (`0x14015f0d0`), desde el fotograma 0, con el paso de `g_Time`; `spritesheetrefreshsync` solo duerme hasta el próximo fotograma; `frame_time` 0, uno por fotograma de render.
- `8586` **Lo que cambia** — `_combos_en_mayusculas` en `wescene`, `mueve_la_hoja` en `wescript`, el fotograma 0 y la línea `hojatiempo` en `werender`, y `we_hoja_tiempo_uniforms` en los dos ejecutores con `g_Time`.
- `8621` **Lo que se descartó** — normalizar solo `spritesheet`, imitar el paso a paso de WE, medir en el `origin` de la capa y el perfil de luminancia.
- `8639` **Lo medido** — 60 comprobaciones del binario; 34 planes cambian, cada uno con su causa; 34 → 54119 en el recorte de la 389 y el fotograma que toca; 0 regresiones de luz, y las caídas son el `color` y el `alpha` que `VERSION` aplica.
- `8701` **Lo que queda** — ~~la textura por `image_id`~~, hecha para las 7 sin script; el `alpha` que el valor por defecto del material pisa sin `VERSION`; `setFrame` por clics.
- `9018` **Las hojas de varias imágenes eligen la textura por `image_id`: lo leído en wallpaper64.exe** — WE parte cada fotograma por el tamaño de SU imagen y al enlazar pone en el sampler la imagen del fotograma; la línea `hojaimagenes` lleva la textura de cada uno y `we_hoja_tiempo_textura` la elige en los dos ejecutores. Corren las 7 capas sin script de `2262142032`, `2229352184` y `2220826239`.
- `9038` **Lo leído, con direcciones** — el `image_id` en `+4` del registro del fotograma y la división por el ancho y alto de su imagen (`0x14015e4b6..0x14015e4eb`); el avance lo apunta en `textura+0x98` (`0x14015f2e8`) y el enlace lo lee (`0x1400ee8f0`).
- `9073` **Lo que cambia** — `texture(imagen=)` y `linea_hojaimagenes` en `werender`, `lee_por_tiempo` con siete u ocho números en `wereloj.c`, y `g_Texture0` rebindeado en `glexec.c` y `glexecutor.cpp`.
- `9098` **Lo que se descartó** — una línea hermana detrás de `hojatiempo`, que un ejecutor viejo correría sobre la imagen 0; un atlas; partir por el tamaño de la imagen 0.
- `9116` **Lo medido** — 29 comprobaciones del binario; las 7 capas con su textura por fotograma; 3 planes cambian de 129; 128 → 106680 en el recorte de la 983; el `glexec` de main con el plan nuevo, igual que main; 0 regresiones de luz.
- `9162` **Lo que queda** — las 5 de `3577990983`, que mueve un script y pesan 1,1 GB en RGBA; `g_Texture0Resolution` por imagen.
- `8714` **Los puntos de un efecto van en la v de WE: la espiral de dragones de Karma** — un `center` con `"position": true` se subía sin voltear y el `spin` de `2637739953` giraba alrededor de un punto cerca del borde de abajo; ahora se escribe `1 − v`.
- `8731` **Lo que cambia** — el volteo en el bucle de constantes de `werender`, y `es_punto`: solo lo que el shader usa entero, porque `u_FixedSize` lleva la marca y es una proporción.
- `8753` **Lo que se descartó** — voltear todo `"position": true` y separar por la `label`.
- `8762` **Lo medido** — 15 planes y 54 centros cambian; 0 regresiones de luz en las 15; los `godrays` de `2645037214` salen ya del orbe y el farol.
- `8783` **Lo que queda** — el sentido de giro de cualquier ángulo de un efecto, que el volteo invierte y no se ha comprobado contra WE.
- `8885` **El cursor aparta: `controlpointattract` leído en wallpaper64.exe** — la regla del simulador era una deducción y estaba al revés en las dos cosas: WE solo actúa DENTRO de `threshold`, con caída lineal, y la `scale` negativa empuja. Las luciérnagas de Karma que perseguían el ratón ahora lo esquivan.
- `8896` **Lo leído, con direcciones** — la fábrica (`0x1401cc9d3`, bloque de tipo `0xa`), los defectos 512/512 o 20/5 con el booleano de la escena, el operador en `0x140241554`, `flags & 2` y `flags & 1`, y el tiempo `t` con el que se integra.
- `8947` **El corpus con la regla leída** — 109 de los 111 usos sobre el cursor tienen `scale` negativa; 13 sin `threshold`, uno sin `scale`, 6 con un `origin` que WE no lee.
- `8958` **Lo que cambia** — `_op_atrae` con los defectos de WE, `OP_ATRAE` a 4 floats, y `prueba_cursor`, que medía el fallo como si fuera lo correcto.
- `8980` **Lo medido** — la prueba nueva contra `main` (3 frente a 3384 en el hueco); 172 líneas de `.psys` en 39 escenas; 0 regresiones de luz; el vórtice de `3219398263` que no hacía nada.
- `9005` **Lo que queda** — el factor de tiempo `F` sin identificar, el `drag` lineal de WE, y `flags & 1`.
- `9348` **Las agujas de un reloj analógico: `angles` con `engine.timeOfDay`** — `wescript` reduce el script a `A · frac(B · tod) + C` en grados y lo comprueba evaluándolo; la línea `giro` y `src/wegiro.c`, nuevo y compartido, giran la colocación con la hora en los dos ejecutores. Las tres agujas de `2396319149` se mueven; solo cambia su plan.
- `9380` **Lo que cambia** — `engine.timeOfDay`, `giro_por_hora`, `--hora` y `@HORA@`, grados frente a radianes, y por qué el giro reproducía la deformación del ángulo estático (63 capas en 22 escenas), ya quitada en los dos sitios.
- `9434` **Lo que se descartó** — reconocer el texto del script, girar en píxeles solo las agujas o en el espacio del quad, y dar `timeOfDay` solo a `angles`.
- `9449` **Lo medido** — 3 de 7 scripts aceptados; 0 grados en 7200 `tod`; 128/128 planes idénticos y tres líneas `giro` añadidas; el C a 0 grados en `C` y `es_ES`; 0,0000 y 0,0001 de 255 contra el `angles` estático; 0 → 42193 entre las 03:00 y las 09:00; 0 regresiones de luz.
- `9500` **Lo que queda** — ~~la deformación del ángulo estático~~ (hecha), los otros cuatro `angles` (el seno, hecho), la fracción de segundo de `timeOfDay` sin leer en el motor, y los hijos de una capa girada.
- `9657` **Un campo que oscila con `engine.runtime`: el vaivén de `angles` y de `origin`** — `wescript` da `Math.sin`, `Math.cos` y `engine.runtime`, y `vaiven_de` reduce cada componente a `K + A · sin(ω · t + φ)` y lo comprueba evaluándolo; la línea `vaiven` y `src/wegiro.c` mueven la colocación con el tiempo de `g_Time` en los dos ejecutores. Se balancea el parche de `3050043876` y sube y baja el gotero de `3521337568`; las dos capas con hijos de `3577990983` no.
- `9690` **Lo que cambia** — `vector_en`, la ω por la identidad de `f(t ± h)`, la comprobación, la línea con los ejes de clip y el 1 + k del parallax en reposo de una raíz, y el giro con `we_giro_coloca`.
- `9747` **Lo que se descartó** — reconocer el texto, mover también a los hijos, otra cuenta para el giro, sumar el `origin` sin el parallax en reposo (92406 píxeles contra el estático) y mover el `g_EffectModelViewProjectionMatrix`, inerte aquí.
- `9774` **Lo medido** — 2 de 430 campos con forma, error 0; 131/133 planes idénticos y una línea añadida en cada una de las otras dos; 0 píxeles a t = 0 y contra el estático; 20,5 unidades y 3,00°; el C a 0 en `C` y `es_ES`; 0 regresiones de luz.
- `9863` **Lo que queda** — las capas con hijos, el glitch y el `Math.random` de `engine.runtime`, el pivote de una capa con `alignment`, los uniforms con la MVP del objeto y el arranque de `engine.runtime`.
- `10437` **Los scripts que colocan: un valor que no cambia se evalúa una vez** — `valor_fijo_de` evalúa al cargar el script que da siempre lo mismo (`engine.canvasSize`, `Vec3`, `init`) y lo pone en el `value`; el widget de `3462491575` deja de amontonarse. Un script con sucesos (`media*`, `cursor*`, `applyUserProperties`) no se evalúa.
- `10467` **Lo que cambia** — `canvasSize`, `new Vec2/Vec3`, el espacio duro, `valor_fijo`, `_es_suceso`, `_hornear_scripts_fijos`, y el deslizador atado a la `scale` de una capa repartido en las tres componentes.
- `10509` **Lo que se descartó** — repartir el deslizador en constantes de shader (`0.3 1`), evaluar con sucesos (8 colores negros) y `applyUserProperties` con `screenResolution`.
- `10527` **Lo medido** — 20 de 186 campos en 2 escenas; 174/174 formas idénticas; solo cambian los objetos esperados; `定位` idéntica píxel a píxel; 0 regresiones de luz.
- `10567` **Lo que queda** — los 34 hijos sin `origin` que van al centro, `getParent`, `applyUserProperties` al cargar, el rebote por fotograma de `2262142032` y el deslizador en un shader.

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
