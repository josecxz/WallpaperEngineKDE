# Índice de `NOTAS.md`

`NOTAS.md` son 3700 líneas en orden **cronológico**: cada sección es una caza
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
- `47` **Estado** — qué corre hoy en vivo, sobre qué versión de Plasma, y por qué el corpus pasó de 125 a 129 escenas.
- `322` **Estructura** — el árbol del repositorio con una línea por fichero.
- `1375` **Uso** — `make install` / `reload` / `status`, y cómo activar el plugin sin pasar por la GUI.
- `3788` **Lo siguiente** — la lista de pendientes por impacto, con lo ya hecho tachado.

## Arquitectura y plataforma

- `295` **Decisión de arquitectura: por qué un plugin QML y no layer-shell** — las dos rutas de Wayland probadas empíricamente y por qué `wlr-layer-shell` quedó descartada en KWin.
- `68` **El motor en C++ — `src/`** — QRhi no acepta GLSL en texto y nuestros shaders se generan en ejecución: de ahí `beginExternal()` y el backend obligatorio OpenGL. Incluye las tres cosas que costaron (framebuffer de Qt, `mv` en vez de `cp`, `Q_ARG` guarda un puntero).
- `1400` **Notas de plataforma** — `Screen.refreshRate` llega `undefined`; `FrameAnimation` late en el hilo de render y se para solo cuando Qt deja de componer.
- `281` **Hito 0 (completado)** — el primer color sólido detrás de los iconos, con el reloj sincronizado al refresco.
- `2728` **Nota de rendimiento para el port a C++** — qué extensiones de compresión de textura expone esta GPU.
- `3871` **Elegir la GPU que renderiza** — la iGPU se come el 49,6 %; los dos caminos para mover el fondo a la dedicada y el riesgo que puede tumbar el segundo.

## CLI, rotación y rutas

- `147` **El CLI — `tools/wectl.py`** — `list`/`set`/`shuffle`/`start`/`stop`/`status`; `set` acepta id de Workshop o parte del título.
- `163` **Rotación: por qué es un temporizador y no una opción del plugin** — por qué el «cada x tiempo» no vive en la configuración del fondo.
- `192` **Cambiar la cadencia sin cambiar el fondo, y por qué el mínimo es 1 minuto** — `shuffletime`, y de dónde sale el suelo del intervalo.
- `2190` **Dos `wectl` a la vez se pisaban** — la rotación por systemd cayendo encima de un `set` a mano: los dos construían el plan en el mismo directorio.
- `244` **Dónde está Wallpaper Engine** — el orden de búsqueda de `wepaths.py`: variables de entorno, luego las bibliotecas declaradas en Steam.
- `3847` **Los 19 wallpapers que trae la aplicación: 7 servirían** — vienen sin empaquetar (`scene.json` suelto) y las herramientas filtran justo por `scene.pkg`.

- `4188` **`wectl list` dice de qué tipo es cada wallpaper** — el `type` de `project.json`, normalizado: 24 de 148 lo escriben con mayúscula.
- `4204` **Enseñar también los que no se pueden poner** — un wallpaper que no aparece no se distingue de uno que no está instalado.
- `4222` **El que no es un wallpaper** — `2336642563` trae `category: Asset`: es un paquete de materiales, no un fondo.
## Pausa por oclusión, resolución y rendimiento

- `1279` **La pausa mide cobertura, no una bandera** — preguntar «¿está maximizada?» falla en tres casos diarios; medir cuánta pantalla queda a la vista, no.
- `1301` **Lo que el modelo de tareas no dice, y cómo se supo** — dos hechos sobre minimizar y el estado de las ventanas que no están en la documentación.
- `1336` **No dibujar lo que no se ve** — 98,4 % → 0,0 % del motor de render al pausar, medido con `/proc/<pid>/fdinfo`.
- `2145` **El HUD decía 166 fps con la GPU al 98 %** — el reloj de QML medía la composición de Qt, no el motor. Por qué el número del HUD no vale como medida.
- `2788` **Dibujar a la resolución que se ve** — 8,3 Mpx pintados para enseñar 2,3; el lienzo del autor casi nunca es el de la pantalla.
- `2829` **Lo medido** — el cronómetro del ejecutor, escena por escena, antes y después.
- `1951` **Encajar el lienzo en la pantalla** — cómo se ajusta `orthogonalprojection` al panel, medido sobre el corpus.

## Formatos: contenedor, texturas, mallas

- `364` **Formatos de Wallpaper Engine** — por qué la implementación de referencia está en Python y qué significa «especificación ejecutable».
- `370` **`scene.pkg` — `tools/pkg_inspect.py`** — la tabla de entradas, con los offsets relativos al FIN de la tabla y no al fichero.
- `379` **`.tex` — `tools/wetex.py`** — contenedores `TEXB0001`–`0004`, formatos, LZ4 de bloque, mipmaps y sprite sheets animados.
- `1903` **El relleno a potencia de dos estaba en los píxeles** — un `.tex` de 4096x2048 con la imagen en una esquina; parecía un fallo de encaje y no lo era.
- `421` **`.mdl` — `tools/wemdl.py`** — mallas puppet: geometría, `MDLS` esqueleto, `MDLA` animación.
- `3455` **El puppet se quedaba en reposo: el campo de la cabecera es un desplazamiento** — 58 de 95 puppets no encontraban `MDLA` y se quedaban quietos.
- `3496` **Y entonces `mirror` deja de ser un detalle** — los dos ejecutores dan por hecho que la última clave repite la primera; en modo `mirror` no.
- `3515` **Lo medido** — las 129 escenas tras recuperar los puppets: ninguna regresión.
- `4781` **El personaje calvo: el rig tenía un bloque con nombres que nadie leía** — `attachment` cuelga una capa de un hueso del padre; el nombre está en el bloque `MDAT`, que se saltaba entero.
- `4803` **Dónde estaba el nombre** — el campo de texto del hueso son los límites de la articulación; el formato de `MDAT` y por qué el recuento es u16.
- `4838` **Por qué no basta con hornearlo** — el hueso se mueve hasta 285 px, así que los ejecutores rehacen la traslación por fotograma.

## Vídeo

- `3593` **Vídeo de verdad: un decodificador compartido, y dos entregas distintas** — el MP4 viaja entero en el plan y lo decodifica `src/wevideo.c`, que enlazan los dos ejecutores.
- `3604` **Por qué libav y no una tubería de `ffmpeg`** — 4K60 en RGBA por una tubería son 2 GB/s, y el bucle y la pausa solo se harían matando el proceso.
- `3618` **Los dos modos no son un lujo: son dos requisitos incompatibles** — el offline necesita el mismo fotograma al repetir; el vivo, no bloquear nunca. Con las medidas de coste.
- `3648` **El bucle de seeks que dejaba el vídeo clavado** — el seek cae en el fotograma clave anterior y el consumidor volvía a pedir; solo se ve si el reloj arranca lejos de cero.
- `3668` **Y el fichero no siempre empieza en cero** — `start_time` desfasaba un fotograma y desplazaba el bucle en cada vuelta.
- `3679` **Nueve fondos negros por un espacio en el nombre** — el plan se parte por espacios; el MP4 es el primer asset nombrado tal cual venía de la biblioteca.
- `3693` **Lo que había que decidir, y dónde se decidió** — mipmaps, volteo con paso negativo, BT.709 cuando el fichero calla, y el tamaño del anillo.
- `3714` **Los wallpapers de tipo vídeo salen casi gratis** — los 15 que no son una escena: plan sintético de un quad, y encaje que cubre en vez de caber.
- `3731` **El oráculo: pixel a pixel contra ffmpeg** — 54/54 fotogramas idénticos y 18/18 dimensiones; y por qué se le fija a ffmpeg la misma matriz de color.
- `3750` **Lo medido sobre las 129** — 0 regresiones, 124 de 128 escenas con la luz exacta de antes; y el falso positivo por llenar `/tmp`.
- `3777` **Lo que sigue sin estar** — audio, decodificación por hardware y el `.tex` de vídeo con relleno que el corpus no tiene.
- `3031` **Vídeo en el motor: qué haría falta** — el estado de ANTES, ya resuelto; se conserva por el orden cronológico.
- `3054` **Lo que hay que resolver antes de intentarlo** — las dudas que planteaba, todas decididas arriba.

## Shaders: dialecto, compilación, enlace

- `1412` **Dialecto de shader — `tools/weshader.py`** — las cuatro capas encima del GLSL: `#include`, `[COMBO]`, metadatos JSON en los uniforms, restos de HLSL.
- `670` **Tres fallos que se veían como uno** — el bokeh que tapaba la escena de Asuka eran tres causas independientes y solo una se parecía al síntoma.
- `701` **El escaneo de no-soportados corría demasiado pronto** — 17 escenas negras, 16 por una sola causa.
- `739` **Los uniforms de las cabeceras no existían** — fondo entero en negro y solo las partículas encima.
- `789` **Las conversiones implícitas que quedaban** — las 26 variantes que no compilaban eran todas lo mismo: HLSL convierte solo y GLSL no.
- `1992` **La última variante que no compilaba: truncar también al llamar** — la 1 de 594, y por qué la truncación necesita un parser y no un regex.
- `2860` **Compilar no es enlazar: 82 pases que se perdían sin decir nada** — un vértice y un fragmento pueden compilar por su lado y no poder enlazarse.
- `2881` **La causa del grupo grande** — la familia de desenfoques gaussianos y el `KERNEL` que cada etapa declara distinto.
- `2897` **El arreglo obvio parecía romper la imagen, y ya no** — prestarle a cada etapa el combo que consulta, y por qué la primera vez destrozó 72 escenas.
- `2935` **Tres causas, y ninguna era la que decían estas notas** — el desglose con `--link` sobre los 297 pares, en los dos drivers.
- `3000` **Y lo que parecía un límite de hardware: `GLSL` sin definir** — WE define `GLSL` o `HLSL` según el backend; nosotros ninguno, así que todo `#ifdef GLSL` caía al lado equivocado.
- `3016` **Lo que queda** — cero fallos en los planes reales; la única variante que NVIDIA rechaza y Mesa acepta.
- `4880` **`step(0.5, nodeNum)`: la norma lo admite y NVIDIA no** — promocionar el argumento entero que no es un literal, y por qué la tabla de tipos va aparte de la de truncación.

- `3987` **La homografía salía transpuesta: `m[i][j]` no es lo mismo en los dos lenguajes** — el único header que construye una matriz por índices, y los 10 efectos que lo incluyen.
## Grafo de escena y composición

- `1465` **Grafo de escena — `tools/wescene.py`** — una escena no es una lista de capas: es un grafo con recursos nombrados. La cadena completa para pintar una sola imagen.
- `1530` **Renderizador offline — `tools/werender.py` + `tools/glexec.c`** — el reparto: la inteligencia en Python, la ejecución en C.
- `1584` **Composición de capas** — los dos niveles de buffer: el par ping-pong del objeto y el buffer de escena.
- `1617` **Transformación por objeto** — `origin`, `size`, `scale`, `angles`; el pase base recibe MVP y los de efecto son post-proceso a pantalla completa.
- `1629` **Visibilidad condicional** — `visible: {"user": ..., "value": ...}`; ignorarlo dibuja capas que el autor dejó apagadas.
- `1640` **Render targets incorporados** — `_rt_FullFrameBuffer` y `_rt_MipMappedFrameBuffer` son nombres reservados, no buffers nuevos.
- `1653` **`copybackground` no significa "empieza desde el fondo"** — interpretarlo mal recomponía el fondo nueve veces sobre sí mismo.
- `3522` **La capa `passthrough` se componía en su rectángulo del editor** — `composelayer`/`fullscreenlayer`/`projectlayer` operan sobre el fotograma entero y nadie leía el flag.
- `3556` **Lo medido** — una sola escena cambia, y baja porque antes estaba mal.
- `3178` **Los recuadros negros: una capa negra de verdad, compuesta con la mezcla que no era** — tres rectángulos pintados encima que no están en el preview.
- `3185` **La capa no está rota: es negra a propósito** — RGB medio 3,8 y alfa 255; lo que la hace invisible en WE es el `colorBlendMode`.
- `3212` **Por qué no se hace donde lo hace WE** — WE mezcla dentro del pase base con `ApplyBlending`, no al componer.
- `3231` **El alfa hay que premultiplicarlo a mano** — `screen` y `max` ignoran el alfa de la fuente y el buffer de una capa con efectos no viene premultiplicado.
- `3240` **Y entonces la regla de la herencia se cae sola** — el «solo heredan los grupos» era un parche a la mezcla del objeto, y estorbaba en cuanto se arregló lo de debajo.
- `3262` **La invisibilidad no bajaba por la cadena de padres** — apagar un grupo tiene que apagar lo que cuelga; Lonely Cat trae la escena seis veces, una por idioma.
- `3282` **Lo que NO era: la Y del hijo** — la tentación de invertir la Y del `origin` relativo, comprobada y descartada.
- `3303` **Lo que se ve** — los tres rectángulos desaparecen y las ondas salen del centro.

## Escenas negras y capas perdidas

- `1728` **Medir la luz, no solo que el plan se genere** — por qué existe `test_luminancia.py`: una escena puede quedarse negra sin que nada falle.
- `1778` **Tres escenas negras por un `normalize(0, 0)`** — se preparaba sin una sola queja y salía a 18 de 255.
- `2210` **Un sampler sin enlazar no lee negro** — Resident Evil 9 salía casi vacía; con `--only-base` aparecía entera.
- `2240` **El arreglo es general, y destapa 26 escenas** — enlazar el `default` que declare el sampler, y qué queda fuera a propósito.
- `2268` **El lunar negro del vinilo: la opacidad iba a un uniform que nadie lee** — la sombra del disco, opaca en mitad del personaje.
- `2306` **Alcance: 78 objetos en 18 escenas** — los objetos con `alpha` distinto de 1, medidos sobre las 129.
- `2321` **El cuarto nombre del tinte: `g_Color`, y la ciudad que salía en siluetas** — el atardecer y el planeta perdidos en *Sci-Fi Cyber City*.
- `2358` **Alcance: 44 capas en 15 escenas, y 17 acertaban por casualidad** — quién lee `g_Color` de verdad: tres shaders de la librería común y nadie más.
- `3079` **Las dos escenas negras eran dos campos leídos de más** — el mismo error en dos sitios: **`value` no es el valor**.
- `3088` **`1518454472`: la Miku salía roja donde va cian** — el color de verdad está en la propiedad del `project.json`, no en el `value`.
- `3110` **`3577990983`: un telón de entrada que no se levantaba** — la escena no estaba rota, estaba tapada por una capa negra con el `alpha` animado.
- `3145` **Lo que se llevó por delante** — las escenas que cambiaron además de las dos buscadas.
- `3164` **La que queda es bloom, y es un subsistema** — sale con los tonos correctos pero apagada; `bloom: true` no está implementado.
- `3563` **`254 - 255` no es −1: el flujo se invertía donde la máscara satura** — negar la V de un mapa de flujo sobre el byte, no sobre el entero.

## Iluminación y reflejos

- `2402` **La función de iluminación no está en los assets** — ocho shaders llaman a `PerformLighting_V1` y ninguno la define.
- `2432` **El mismo color por dos caminos distintos** — dos generaciones de shaders con convenciones **incompatibles** para el mismo dato.
- `2451` **El mundo es el lienzo en píxeles** — las luces declaran su `origin` en las unidades de los objetos; no hay conversión de espacios.
- `2460` **Tres uniforms que GL pone a cero sin decir nada** — encender el combo cambia el camino del vértice y el plan no emitía lo que ese camino usa.
- `2482` **O todas las luces, o ninguna** — si una escena trae una luz que no sabemos poner, se dibuja plana entera: el ambiente oscurece contando con que las luces devuelvan.
- `2498` **El módulo de verdad está en el binario, y no es un fichero** — `LightingV1` va como texto dentro de `wallpaper64.exe`: no es un shader, es un generador.
- `2549` **La función repuesta no la usa ninguna escena de esta biblioteca** — los 6 pases iluminados del corpus van por el camino viejo.
- `2587` **Lo que se ve** — 9 luces en 5 wallpapers; la media de la escena de referencia contra el preview del autor.
- `2598` **El tubo sí venía en la escena, y el reflejo solo pedía una pirámide** — las dos cosas que quedaban eran mucho más pequeñas de lo que decían estas notas.
- `2604` **La luz de tubo: `controlpoint` es el otro extremo** — estas notas decían que no había forma de ponerla; el segundo extremo sí está en el formato.
- `2634` **La tercera convención para el mismo color** — la que leen los shaders con un array por clase.
- `2651` **Los focos se quedan fuera a propósito** — no hay ni un foco ni una direccional en esta biblioteca con la que comprobarlo.
- `2660` **Lo que se ve, y lo que no** — casi nada, y hacia abajo; por qué, para no volver a mirar aquí.
- `2676` **Reflejos: no era un subsistema, era un filtro** — `REFLECTION` estaba forzado a cero por un buffer que ya existía.
- `2695` **El filtro no puede vivir en la textura** — `_rt_MipMappedFrameBuffer` y `_rt_FullFrameBuffer` son **el mismo buffer**.
- `2709` **Lo que se ve** — 7 pases en 3 escenas; el bloque solo vive con `NORMALMAP`.

## Partículas

- `918` **Sistemas de partículas** — el primer subsistema con estado que avanza con el reloj, y por qué eso no puede vivir en Python.
- `939` **El reparto** — `weparticles.py` resuelve y escribe un `.psys`; `weparticles.c` simula y no conoce Wallpaper Engine.
- `958` **Verificación** — la regresión de render, y qué reparto hay que mirar de verdad.
- `974` **Y luego, en el escritorio** — 17 de 42 piezas «sin soporte» con el mismo `.so`: era **`LC_NUMERIC`**. El arreglo es `uselocale`, no `setlocale`.
- `1003` **Lo que costó encontrar** — cinco fallos, **ninguno en la simulación**: alfa, formato de textura, recorte.
- `1035` **Decisiones que son lecturas, no hechos** — `colorrandom` con un solo factor, y otras lecturas del formato que podrían ser otras.
- `1050` **Estelas: `spritetrail` no necesitaba historial** — las 211 estelas del corpus parecían un problema y el shader dice que no.
- `1089` **`rope` y `ropetrail`: la cinta sí pide historial** — van por `genericropeparticle`, y eso no está en el material.
- `1167` **Repartir por puestos: el rayo** — `mapsequencebetweencontrolpoints` no es un parámetro, es otro modelo de colocación.
- `1179` **El corro, el ruido y una orientación que ya estaba bien** — tres cabos cerrados leyendo el JSON con cuidado; en dos, lo que bloqueaba era una lectura equivocada.
- `1681` **La turbulencia no turbulaba** — la dirección no la fija ningún campo de dirección, la fija el campo de ruido.
- `1826` **Imitar el humo de WE con una captura por oráculo** — cómo se localiza qué trozo del lienzo enseña una captura para que sirva de referencia.
- `1866` **El humo que no se apagaba** — una neblina ancha donde WE tiene una voluta compacta; no era el tamaño del sprite.
- `2030` **El `exponent` de los sorteos: leído, y la curva elegida mirando la vela** — 96 usos en la biblioteca que se estaban tirando.
- `2053` **Lo que NO se pudo confirmar** — la dirección del sesgo, con los tres oráculos que se intentaron y por qué ninguno sirve.
- `3914` **El anillo del vórtice, y las dos velocidades que faltaban** — una captura del escritorio de Windows como oráculo; tres cosas mal a la vez en la misma escena.
- `3922` **La tangente es una cuerda: el radio crecía solo** — un 65 % por vida; se arregla girando la posición, no empujándola.
- `3939` **`distanceouter` es hasta dónde llega, no dónde se satura** — la medida que lo decide es la PENDIENTE de las estelas: radiales, no tangenciales.
- `3958` **El emisor tenía una velocidad y nadie la leía** — `speedmin`/`speedmax` de `sphererandom`: la única velocidad de 12 sistemas del corpus.
- `4230` **Las estrellas no parpadeaban: `colorrandom` sin `max` sortea hasta negro** — el oráculo se monta restando el fondo a la captura; dos fallos distintos con la misma medida.
- `4245` **El tamaño del sprite: el brillo explicaba una parte, no toda** — por qué el rayo NO sirve de contraste, y qué queda abierto.
- `4268` **La pista estaba en un campo escrito de más** — 158 objetos escriben `max` igual a `min`; por eso el defecto de `max` es negro y no `min`.
- `4285` **El ritmo implícito estaba en el extremo, y se comía el `instanceoverride`** — `maxcount/vida` deja el depósito lleno, que es el percentil 76 del corpus, no la costumbre.
- `4314` **La otra mitad era el bloom** — el halo que la resta enseña alrededor de todo lo brillante; lo piden 33 de las 129.

## Bloom

- `4322` **El bloom son tres shaders de WE y un objeto más** — la cadena no había que escribirla, había que deducirla de los nombres.
- `4339` **`g_TexelSize` es el texel de PANTALLA, y lo dice la captura** — tres lecturas posibles con un factor 8 entre ellas; el radio medido cae limpio en 16 px.
- `4360` **El umbral va DESPUÉS de promediar, y eso se ve** — por qué el bloom de WE rodea zonas brillantes y no puntos sueltos.
- `4368` **No hay que tocar los ejecutores** — va como un objeto más que se compone sumando; los buffers ya sabían sacar su resolución del nombre.
- `4382` **Lo medido sobre las 129** — 39 escenas, la mediana contra el preview de 0,171 a 0,135, y la primera pasada sin escenas apagadas.

## Resolución

- `4543` **El lienzo del autor no es un límite de resolución: 38 escenas salían ampliadas** — el `min(1.0, ...)` hacía que el blit final las agrandara; el diario del motor en vivo lo traza.
- `4573` **Lo medido** — 38 de 129, mediana x1,11 y hasta x3,40; y por qué `test_luminancia` no vale como oráculo aquí.
- `4588` **Lo que NO explica** — la City ya se dibujaba 1:1; su destello sigue pendiente.

## Sistemas hijos

- `4595` **Sistemas hijos: `eventspawn`** — 232 sistemas con hijos en 61 escenas; aquí solo el que estalla donde muere el padre.
- `4603` **El hijo es un objeto hermano, no un pase más del padre** — trae su propio material, así que se devuelve como objeto y se ata con `psyspadre`.
- `4617` **La lectura del formato** — el depósito sale de `children` y la ráfaga del preset; el emisor libre del hijo se apaga.
- `4629` **Por qué se simulan en tándem, y no uno detrás de otro** — una cola diferida haría estallar el sistema entero de golpe tras una recuperación de 60 s.
- `4649` **Lo medido** — 0 a 60–92 partículas; 10 escenas, 17 hijos; y por qué `test_luminancia` no vale como oráculo aquí.
- `4662` **Lo que NO arregla** — las manchas van de 23 a 74 pero siguen en 5–8 px donde WE tiene el pico en 3–4.
- `4925` **Un puntero donde hacía falta una lista: el hijo `eventspawn` congelado** — con dos hijos el segundo pisaba al primero y lo dejaba sin dar pasos; una escena del corpus.

## Emisores

- `4675` **`distancemax` sin declarar no es cero: la lluvia salía toda del mismo punto** — el tercer campo con el mismo patrón; 6 presets-emisor en 7 escenas.
- `4688` **Por qué 512** — el corpus escribe el 0 explícito 153 veces y `exampleturbolence` obliga a que el defecto sea ≥256.
- `4703` **Lo medido, y lo que queda torcido** — dejan de pegarse al borde, pero el 75 % nace fuera por el `directions: "1 5 0"`.

## Cintas y movimiento

- `4728` **La cola de una cinta sale de `length`, no de un 8 fijo** — el defecto de `segments` pisaba el campo declarado; 68 de 74 cintas.
- `4749` **`gravity` es una aceleración, y lo demuestran los fuegos artificiales** — por qué no se endereza la caída, y qué hace que la parábola cante.

## Pendiente

- `4409` **Pendiente: tres cabos de las partículas, medidos y sin cerrar** — el diámetro del destello, la lluvia que sale de un punto y la estela corta.
- `4415` **1. Los destellos: NO es el tamaño, y el factor 0,5 está probado y descartado** — el `preview.jpg` como oráculo a 0,982; los sprites grandes ya coinciden.
- `4461` **1a. Descartado: no es la resolución, y cuidado con medir anchos** — el área va como la escala²; la mediana de anchos a baja resolución es ruido.
- `4480` **1b. Lo que falta son los sistemas HIJOS** — `halo_4` con núcleo del 8 % explica el pico de 3–4 px; 232 sistemas con hijos en 61 escenas.
- `4504` **2. La lluvia de estrellas sale toda del mismo punto** — `boxrandom` sin `distancemax`: el mismo patrón que `rate` y que el `max` de `colorrandom`.
- `4524` **3. La estela es corta y gorda; debería ser fina y larga** — el defecto de `segments` pisa el `length` que el autor sí escribe; 68 cintas de 74.

## Texto

- `3318` **Un punto son 4,137 unidades de lienzo, y eso no lo dice el formato** — una capa de texto es el único objeto sin geometría ni material.
- `3328` **La unidad no está en el formato, pero la caja sí** — adivinar por DPI da candidatos plausibles y todos distintos; de dónde sale el número bueno.
- `3363` **Por línea, no por glifo** — menos código y mejor tipografía: PIL resuelve kerning, ligaduras y shaping de una vez.
- `3376` **Tres sitios de donde sale una fuente, y uno no está aquí** — 47 dentro del `scene.pkg`, 37 de la instalación de WE, 83 del sistema.
- `3391` **El ejecutor no se entera de que hay texto** — ni una línea de C: los quads viajan por la directiva `mesh` que ya existía.
- `3406` **Lo que la distribución ahorró** — mirar los valores y no los recuentos quita más trabajo del que deja.
- `3426` **Lo que se ve** — 25 escenas cambian, 0 regresiones.
- `3439` **Y el muro: 148 de los 167 son JavaScript** — 133 llaman a `new Date`: son relojes y fechas, y el texto dibujado no es el que el autor quiso.
- `4015` **Una capa de texto se ancla por su alineación, no por su centro** — no trae `alignment`: trae `horizontalalign` y `verticalalign`, y dicen lo mismo.
- `4037` **Y lo que faltaba: la hora era la del autor** — lo que se pensó entonces, que resultó ser la mitad de la historia.
- `4052` **La hora de verdad: interpretar el script sin un motor de JavaScript** — el plan es una foto, así que lo que viaja en él es el FORMATO, no la cadena.
- `4059` **Por qué no vale con ejecutarlo una vez** — cambiaría una hora congelada de 2021 por una congelada de hoy; el reparto en tres piezas.
- `4074` **Un intérprete, no un motor** — el vocabulario de los 51 scripts, contado; y `createScriptProperties()`, que llevó de 6 a 129.
- `4098` **Deducir el formato: cortar siete muestras a la vez** — las dos maneras de equivocarse: una sola cadena es ambigua y diferenciar cadenas cortas miente.
- `4117` **Los nombres no se adivinan: se reconocen** — están escritos en el script; hacen falta TRES muestras por valor o se cuela el campo vecino.
- `4134` **Lo que da la garantía es la comprobación, no la deducción** — ~1050 instantes; con una diferencia se descarta y la capa no se toca.
- `4148` **El alfabeto, y lo que se pierde** — rasterizar glifo a glifo en vez de por línea, y el kerning que eso cuesta.
- `4167` **Y la locale, otra vez** — `strtof` dentro de plasmashell deja el alfabeto a cero sin un solo error por medio.

## Inventario del formato: qué leemos y qué no

- `862` **Qué campos del formato leemos y cuáles no** — cada clave que aparece en `scene.json` cruzada contra lo que el código busca por nombre.
- `872` **Colocación y geometría** — la lección de método: **el recuento bruto engaña**, hay que mirar la distribución de valores.
- `890` **Lo que sí falta, medido** — la lista de huecos reales, con lo ya hecho tachado.
- `2089` **Los uniforms que el motor rellena y nosotros no** — los 147 nombres de la tabla del binario cruzados con el código VIVO de las 594 variantes.
- `2131` **Lo que queda medido para después** — el vocabulario de partículas está completo; lo que falta son campos de piezas que sí leemos.

## Propuestas sin empezar

- `2741` **Mejora propuesta: generar un wallpaper desde un prompt** — el motor come de un formato abierto, así que basta con producir lo que ya sabe leer.
- `2758` **El camino mínimo** — prompt → imagen → mapa de profundidad → `scene.json` por capas.
- `2771` **Lo que falta en este repositorio** — no hay escritor de `.tex`, así que un PNG generado no entra.
- `2782` **Lo que el motor no puede dar, y conviene saber antes de diseñar el prompt** — audio reactivo, vídeo y modelos 3D.
