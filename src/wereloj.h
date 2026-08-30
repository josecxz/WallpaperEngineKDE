/* Capas de reloj: rehacer los quads de una cadena que cambia con la hora.
 *
 * Lo comparten los DOS ejecutores, igual que `weparticles.c` y `wevideo.c`:
 * el de `tools/glexec.c` y el que corre dentro de plasmashell. Si se toca la
 * disposición hay que tocarla aquí y no en uno de los dos.
 *
 * Quien deduce la plantilla es `tools/wescript.py`, interpretando el
 * JavaScript de la capa; quien rasteriza el alfabeto y calcula las métricas es
 * `tools/wetext.py`. Esto solo rellena la plantilla con el reloj del sistema y
 * escribe vértices.
 */
#ifndef WERELOJ_H
#define WERELOJ_H

#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct WeReloj WeReloj;

WeReloj *we_reloj_nuevo(void);
void we_reloj_free(WeReloj *r);

/* Lee una directiva del plan. `kw` es la palabra clave (`reloj`, `relojfmt`,
 * `relojtab`, `relojglifo`) y `resto` lo que va detrás del identificador de
 * malla. Devuelve 1 si la entendió. */
int we_reloj_linea(WeReloj *r, const char *kw, const char *resto);

/* Cuántos vértices ocupa la malla: siempre los mismos, para que el búfer se
 * reserve una vez. Los glifos que sobran salen degenerados. */
int we_reloj_nvertices(const WeReloj *r);
int we_reloj_nindices(const WeReloj *r);

/* Cada cuántos segundos cambia lo que se dibuja (60 sin segundos, 1 con). */
float we_reloj_periodo(const WeReloj *r);

/* Escribe `we_reloj_nvertices()` vértices de 5 floats (xyz + uv) con la hora
 * LOCAL de `cuando`. Devuelve 0 si el reloj no está completo. */
int we_reloj_vertices(const WeReloj *r, time_t cuando, float *verts);

/* La cadena que se dibujaría en ese instante. Para las pruebas. */
int we_reloj_texto(const WeReloj *r, time_t cuando, char *salida, int tope);

#ifdef __cplusplus
}
#endif

#endif
