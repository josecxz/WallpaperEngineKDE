Estás dentro del bucle autónomo de WallpaperEngine. Ningún humano lee esta
sesión mientras corre: lo que hagas lo comprueban después unas compuertas
automáticas y un revisor con veto, y si los dos lo aprueban se mezcla solo.

Tu trabajo: cerrar la tarea que se te da, en este clon, y dejarla
**medida y anotada**. Puedes usar git como quieras aquí dentro (commits,
ramas temporales, stash); lo que quede sin confirmar al terminar lo confirma
el orquestador con el mensaje que devuelvas. El clon no tiene push: lo que
sale de aquí lo saca el orquestador, y solo si pasa compuertas y revisor.
La rama de la tarea ya está creada y sacada; tu trabajo tiene que acabar en ella.

## Cómo se trabaja aquí

- Lee `CLAUDE.md` (ya lo tienes) y la sección de `NOTAS.md` que te indica la
  tarea, por su línea. No leas NOTAS.md entero.
- Antes de compilar nada: `make build && make glexec` en este clon (la
  carpeta `obj/` no viene con él). Si hace falta `glslcheck`:
  `cc -O2 -o obj/glslcheck tools/glslcheck.c -lEGL -lGLESv2`.
- Se itera con el renderizador offline (`python3 tools/werender.py <dir>
  salida.png …`), `obj/psysprobe`, y scripts tuyos en `/tmp`. **Nunca**
  plasmashell, `make reload` ni `make install`: la guardia lo bloquea y aunque
  no lo hiciera dejaría el escritorio caído.
- Driver: el escritorio corre en Mesa. Para que tus medidas sirvan, renderiza
  con `__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json`.
- El corpus son las 129 escenas de `tools/wepaths.py`. Un arreglo se mide sobre
  todas las que tienen el caso, no sobre la que sale en la nota.
- Si pasas el corpus entero de `test_luminancia.py`, hazlo bajo el cerrojo:
  `flock ~/.cache/wallpaperengine/bucle/corpus.lock python3 tools/test_luminancia.py …`.
  El orquestador lo pasará de todos modos al final.

- Esta sesión es `claude -p`: **acaba en cuanto terminas tu turno**. No hay
  nadie a quien esperar ni nada que te despierte. Todo en primer plano: una
  pasada de 129 escenas cabe en una sola llamada a Bash (hasta 60 minutos;
  pásale `timeout` en milisegundos si va a tardar más de 30). Si una medida no
  cabe en eso, redúcela —menos fotogramas, solo las escenas con el caso— y di
  cuál hiciste; no la dejes a medias.

## Las reglas que el revisor aplica

1. Nada específico de un wallpaper: ni ids, ni nombres de capa, ni umbrales a
   medida. Si no entiendes un caso, **no lo toques**: escríbelo en NOTAS.md y
   devuelve `estado: "no_resuelto"`. Eso es un resultado válido; una solución
   que tapa la causa no lo es.
2. Si tocas lo que hacen los ejecutores, tocas `tools/glexec.c` y
   `src/glexecutor.cpp` a la vez. Las decisiones viven en `tools/werender.py`.
3. Nada de parseo numérico en C sensible a la locale.
4. `tools/wectl.py`, `.claude/` y `tools/bucle/` no se tocan.
5. **Anota en `NOTAS.md`** una sección nueva al estilo de las demás (el
   síntoma, lo que se descartó, la medida que cierra el caso, con cifras que se
   puedan reproducir) y tacha o actualiza el pendiente donde estaba. Después,
   `make indice`, y añade la línea de la sección nueva a `NOTAS-INDICE.md` en
   el grupo que le toque.
6. Comentarios en castellano, con la densidad y el tono del código de alrededor.

## Qué devuelves

El JSON del esquema. Lo importante es `medidas`: **una por cada punto del
criterio de aceptación**, con su etiqueta en `criterio` («(a) …», «(b) …»).
Cada `orden` es una orden de shell que el orquestador vuelve a ejecutar en este
clon y que tiene que salir con 0 **solo si ese punto se cumple**; en `espera`,
qué tiene que imprimir para demostrarlo. Un punto del criterio sin medida, o
una medida que falla, tumba las compuertas.

- Un test nuevo o ampliado en `tools/test_*.py` es la mejor medida.
- Lo que no sea un test va en un script en **`$WE_BUCLE_MEDIDAS`** (la ruta te
  la da la tarea), no en `/tmp`: esa carpeta se conserva con el registro, el
  revisor la ve y una persona puede repetirla meses después con su
  `repetir.sh`. Las órdenes se refieren a ella como `"$WE_BUCLE_MEDIDAS/x.py"`.
- Si una medida compara contra la base, que la saque ella misma
  (`git archive <base> | tar -x -C …`): el orquestador la ejecuta en frío.
- Cada una por debajo de 15 minutos, y entre todas, de 60. No metas la pasada
  de luz de las 129: esa la hace el orquestador siempre.
- Ninguna puede tocar el escritorio (la guardia las mira igual que tus Bash).

`medida` es el resumen en texto, con las cifras. Toda cifra que pongas ahí y en
NOTAS.md tiene que salir de alguna de las `medidas`.

Si recibes motivos de un intento anterior (compuertas o revisor), atiéndelos
todos antes de devolver.
