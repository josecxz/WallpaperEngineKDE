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
 *   giro <a> <b> <c> <base> <hora> <ancho> <alto>
 *
 * `base` es el ángulo propio con que se horneó la colocación del `object`,
 * también en grados (el `angles.z` de `scene.json`, que va en radianes, ya
 * pasado). `hora` es el marcador `@HORA@`: offline lo pone `werender` con la
 * hora fijada o la de ahora; en vivo no se lee, la da el reloj. `ancho` y
 * `alto` son el lienzo de la ESCENA, enteros, en el que `object_mvp` horneó
 * la colocación y en cuyos píxeles se gira. No son los de la línea `canvas`:
 * esa es la resolución de dibujo, redondeada, y en vivo su proporción no es
 * la del lienzo.
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
    int ancho, alto;    /* el lienzo de la escena; 0 si la línea no lo trae */
} WeGiro;

/* Lee lo que va detrás de `giro`, con la locale numérica sujeta a `C`.
 * Devuelve 1 si entendió los cuatro primeros números; la hora es opcional
 * (un `@HORA@` sin sustituir deja `con_hora` a 0), y el lienzo también (una
 * línea sin él deja `ancho` y `alto` a 0). */
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
 * `origin` de la capa. El giro es en píxeles del lienzo de la escena, como el
 * de `object_mvp`, con el `ancho` y el `alto` de la línea. Sin ellos ---un
 * plan de antes de que `object_mvp` girara en píxeles--- gira en clip, que es
 * como se horneó esa colocación. */
void we_giro_coloca(const WeGiro *g, double grados, float m[16]);

/* Un campo que oscila con el tiempo de escena: el vaivén.
 *
 * Cuando el `update` del `angles` o del `origin` de una capa solo depende de
 * `engine.runtime`, `tools/wescript.py` (`vaiven_de`) reduce cada componente
 * que cambia a
 *
 *     v = k + a · sin(w · t + fase)        con t en segundos de escena
 *
 * en las unidades del script, y `tools/werender.py` escribe detrás del
 * `object` de la capa, una por componente,
 *
 *   vaiven angles <k> <a> <w> <fase> <base> <t> <ancho> <alto>
 *   vaiven origin <k> <a> <w> <fase> <base> <t> <ex> <ey>
 *
 * `base` es lo que ya lleva horneado la colocación: el ángulo propio en
 * grados, o esa componente del `origin` en unidades de lienzo. `t` es el
 * marcador `@TIME@`; offline lo pone `werender`, en vivo no se lee y vale el
 * tiempo que el ejecutor da a `g_Time`. Detrás, en `angles`, el lienzo de la
 * escena en el que se gira, como en `giro`; en `origin`, lo que se mueve en
 * clip la traslación por cada unidad de esa componente. */
typedef struct {
    int angulo;         /* 1 en `angles` (la z), 0 en `origin` */
    double k, a, w, fase;
    double base;
    double t;           /* el del plan, si `con_tiempo` */
    int con_tiempo;
    double p[2];        /* `angles`: ancho y alto; `origin`: ex y ey */
} WeVaiven;

/* Lee lo que va detrás de `vaiven`, con la locale numérica sujeta a `C`.
 * Devuelve 1 si entendió el campo, los cinco números y lo de detrás; el
 * tiempo puede llegar como `@TIME@` sin sustituir, y deja `con_tiempo` a 0. */
int we_vaiven_linea(WeVaiven *v, const char *resto);

/* `k + a · sin(w · t + fase)`. Es la cuenta de `wescript.valor_del_vaiven`. */
double we_vaiven_valor(const WeVaiven *v, double t);

/* Lleva la colocación `m` del `object` del valor horneado al del instante
 * `t`. En `angles` gira la parte lineal con `we_giro_coloca`, en píxeles del
 * lienzo y sobre el `origin`; en `origin` suma a la traslación lo que se haya
 * movido la componente. */
void we_vaiven_coloca(const WeVaiven *v, double t, float m[16]);

#ifdef __cplusplus
}
#endif

#endif
