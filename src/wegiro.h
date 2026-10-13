/* Una capa que gira con la hora: las agujas de un reloj analógico.
 *
 * Lo comparten los DOS ejecutores, igual que `weparticles.c`, `wevideo.c`,
 * `wereloj.c` y `wetemblor.c`: lo enlazan `tools/glexec.c` (offline) y
 * `src/glexecutor.cpp` (en vivo). Si se toca la cuenta, se toca aquí.
 *
 * Quien lee el script es `tools/wescript.py` (`giro_por_hora`): cuando el
 * `update` de un `angles` solo depende de `engine.timeOfDay`, lo reduce a
 *
 *     z = a · frac(b · hora) + c        en GRADOS, con hora en [0, 1)
 *
 * y `tools/werender.py` escribe detrás del `object` de la capa
 *
 *   giro <a> <b> <c> <base> <hora>
 *
 * `base` es el ángulo propio con que se horneó la colocación del `object`,
 * también en grados (el `angles.z` de `scene.json`, que va en radianes, ya
 * pasado). `hora` es el marcador `@HORA@`: offline lo pone `werender` con la
 * hora fijada o la de ahora; en vivo no se lee, la da el reloj.
 */
#ifndef WEGIRO_H
#define WEGIRO_H

#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    double a, b, c;     /* la forma, en grados */
    double base;        /* el ángulo horneado en la colocación, en grados */
    double hora;        /* la del plan, si `con_hora` */
    int con_hora;
} WeGiro;

/* Lee lo que va detrás de `giro`, con la locale numérica sujeta a `C`.
 * Devuelve 1 si entendió los cuatro primeros números; la hora es opcional
 * (un `@HORA@` sin sustituir deja `con_hora` a 0). */
int we_giro_linea(WeGiro *g, const char *resto);

/* `a · frac(b · hora) + c`, en grados. Es la cuenta de
 * `wescript.grados_del_giro`, con el mismo `fmod`. */
double we_giro_grados(const WeGiro *g, double hora);

/* `engine.timeOfDay` en ese instante: la hora LOCAL como fracción del día,
 * con la fracción de segundo. Que WE la dé con fracción no está leído en el
 * motor; ver NOTAS. */
double we_hora_del_dia(time_t segundos, long nanosegundos);

/* Gira la colocación `m` del `object` (16 floats, por filas, como la escribe
 * `object_mvp`) para que lleve el ángulo `grados` en vez de `base`. Solo
 * cambia la parte lineal 2x2: la traslación ---el `origin`, y lo que sumen
 * después el parallax o el temblor--- se queda, así que gira sobre el
 * `origin` de la capa. El giro es en píxeles del lienzo, como el de
 * `object_mvp`, y para eso pide `aspecto`, el ancho entre el alto del lienzo
 * (los dos enteros de la línea `canvas`). */
void we_giro_coloca(const WeGiro *g, double grados, double aspecto,
                    float m[16]);

#ifdef __cplusplus
}
#endif

#endif
