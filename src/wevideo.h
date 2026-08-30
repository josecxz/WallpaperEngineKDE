/* Decodificador de video, COMPARTIDO por los dos ejecutores.
 *
 * Misma regla que `weparticles.c`: `tools/glexec.c` (offline) y
 * `src/glexecutor.cpp` (en vivo) enlazan este mismo fichero. Si la decodifica
 * viviera dos veces, el render offline dejaria de predecir lo que hace el
 * escritorio, y es el offline el que decide (`test_luminancia.py`).
 *
 * Hay dos sitios de donde sale un video en este motor:
 *   - una capa cuyo `.tex` no lleva pixeles sino un MP4 entero (IS_VIDEO),
 *   - un wallpaper de tipo `video`, que es un MP4 y nada mas.
 * A este modulo le da igual cual: recibe una ruta a un fichero de video y
 * entrega fotogramas RGBA del tamano que se le pida.
 *
 * DOS MODOS, y la diferencia no es un capricho:
 *
 *   `WEVIDEO_EXACTO`   decodifica en la propia llamada hasta el instante
 *                      pedido. Es lo que necesita el offline: `werender.py`
 *                      renderiza UN instante y lo repite N veces para que
 *                      converjan los efectos temporales, asi que las N
 *                      repeticiones tienen que dar el MISMO fotograma. Un
 *                      decodificador asincrono ahi haria que la medida de
 *                      luminancia dependiera de cuanto tardo el disco.
 *
 *   `WEVIDEO_HILO`     un hilo decodifica por delante a un anillo y la
 *                      llamada nunca bloquea. Es lo que necesita el vivo: el
 *                      presupuesto del hilo de render son 39 ms por fotograma
 *                      en la escena 4K de referencia y un H.264 de 2160p no
 *                      cabe ahi.
 *
 * Cuando el reloj del motor se para --- plasmashell pausa el fondo si las
 * ventanas lo tapan --- el instante pedido deja de avanzar, el anillo se llena
 * y el hilo se bloquea solo. Eso es deliberado: si el decodificador siguiera,
 * el ahorro de GPU de la pausa se lo comeria la CPU.
 */
#ifndef WEVIDEO_H
#define WEVIDEO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct WeVideo WeVideo;

enum { WEVIDEO_EXACTO = 0, WEVIDEO_HILO = 1 };

/* Abre `ruta` y deja listo el decodificador. `ancho`/`alto` son los del
 * destino: el escalado lo hace swscale, asi que la textura de GL se crea una
 * vez con ese tamano y no cambia aunque el video venga a otra resolucion ---
 * que pasa: el `.tex` declara un tamano y el MP4 de dentro puede traer otro.
 * Con 0 en los dos se usa el tamano nativo del video.
 *
 * Devuelve NULL si no se puede abrir. El motivo se consulta con
 * `wevideo_error(NULL)`, que guarda el ultimo fallo de apertura. */
WeVideo *wevideo_open(const char *ruta, int ancho, int alto, int modo);

void wevideo_close(WeVideo *v);

/* Deja en `*rgba` el fotograma que toca en el segundo `t` del reloj del motor,
 * en bucle sobre la duracion del video. El puntero es valido hasta la
 * siguiente llamada a esta funcion sobre el mismo `v`.
 *
 * Devuelve 1 si el fotograma es DISTINTO del entregado la vez anterior, 0 si
 * es el mismo (y entonces no hace falta volver a subirlo a la GPU: a 30 fps
 * sobre una pantalla a 60 eso es la mitad de las subidas) y -1 si no hay
 * ningun fotograma todavia. */
int wevideo_frame(WeVideo *v, double t, const uint8_t **rgba);

int wevideo_ancho(const WeVideo *v);
int wevideo_alto(const WeVideo *v);
double wevideo_duracion(const WeVideo *v);

/* Ultimo error. Con `v` NULL, el ultimo fallo de apertura. */
const char *wevideo_error(const WeVideo *v);

#ifdef __cplusplus
}
#endif

#endif
