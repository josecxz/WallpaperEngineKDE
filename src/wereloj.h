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
 * `relojtab`, `relojglifo`, `relojkern`) y `resto` lo que va detrás del
 * identificador de malla. Devuelve 1 si la entendió. */
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

/* ── Hoja de sprites cuyo fotograma elige la hora ─────────────────────────
 *
 * Una capa de imagen con `SPRITESHEET` muestrea su hoja por
 * `g_Texture0Translation + u * g_Texture0Rotation.xy + v * g_Texture0Rotation.zw`.
 * Cuando un script de la capa pide el fotograma con `setFrame` y ese
 * fotograma depende solo de la hora, `tools/wescript.py` lo reduce a una tabla
 * de 24 filas y el plan la trae en el pase base con la hoja:
 *
 *   hojahora <volteada> <n> (<rx> <ry> <rz> <rw> <tx> <ty>) x n <f0> ... <f23>
 *
 * Los seis números de cada fotograma son los dos uniforms tal como los pone
 * WE, con la v hacia abajo. `volteada` dice si la textura se subió del revés
 * ---las de capa sí, ver `texture()` en werender.py---, y entonces los
 * uniforms que se suben no son esos sino su reflejo. */
typedef struct WeHoja WeHoja;

WeHoja *we_hoja_nueva(void);
void we_hoja_free(WeHoja *h);

/* Lee lo que va detrás de `hojahora`. Devuelve 1 si lo entendió. */
int we_hoja_linea(WeHoja *h, const char *resto);

/* Los uniforms de WE para la hora LOCAL de `cuando`, sin voltear. Devuelve 0
 * si la hoja no está completa. */
int we_hoja_uniforms_we(const WeHoja *h, time_t cuando,
                        float rotacion[4], float traslacion[2]);

/* Los que hay que subir: los de arriba, reflejados si la textura está
 * volteada. Es lo que llaman los dos ejecutores. */
int we_hoja_uniforms(const WeHoja *h, time_t cuando,
                     float rotacion[4], float traslacion[2]);

/* ── Hoja de sprites que corre por su `frame_time` ────────────────────────
 *
 * La que no mueve ningún script: WE la avanza con el mismo paso que acumula
 * `g_Time`, un fotograma tras otro según su duración, y del último vuelve al
 * 0. El plan la trae en el pase base, con la duración detrás de cada
 * fotograma:
 *
 *   hojatiempo <volteada> <n> (<rx> <ry> <rz> <rw> <tx> <ty> <dur>) x n
 *
 * Los seis números y `volteada` son como en `hojahora`. Una `WeHoja` leída
 * así no tiene tabla por hora: `we_hoja_uniforms` da 0 con ella, y al revés. */

/* Lee lo que va detrás de `hojatiempo`. Devuelve 1 si lo entendió. */
int we_hoja_tiempo_linea(WeHoja *h, const char *resto);

/* El fotograma que toca a los `segundos` de escena, o -1 si la hoja no es de
 * las que corren por tiempo. Para las pruebas. */
int we_hoja_fotograma_en(const WeHoja *h, double segundos);

/* Los uniforms que hay que subir a los `segundos` de escena ---el valor de
 * `g_Time`---, ya reflejados si la textura está volteada. Es lo que llaman
 * los dos ejecutores; devuelve 0 si la hoja no corre por tiempo. */
int we_hoja_tiempo_uniforms(const WeHoja *h, double segundos,
                            float rotacion[4], float traslacion[2]);

#ifdef __cplusplus
}
#endif

#endif
