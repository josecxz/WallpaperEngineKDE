/* Ver `wegiro.h`. Compartido por los dos ejecutores. */

/* `uselocale`, `newlocale` y `localtime_r` son POSIX, no C11: con -std=c11 a
 * secas el compilador no ve sus declaraciones. */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include "wegiro.h"

#include <locale.h>
#include <math.h>
#include <stdlib.h>

int we_giro_linea(WeGiro *g, const char *resto)
{
    if (!g || !resto)
        return 0;

    /* La misma guarda que `we_reloj_linea`: con la locale del escritorio,
     * es_ES, `strtod` leería `0.5` como `0`. */
    locale_t loc_c = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
    locale_t previa = loc_c ? uselocale(loc_c) : (locale_t)0;

    double v[5];
    int leidos = 0;
    const char *p = resto;
    char *fin;
    while (leidos < 5) {
        double x = strtod(p, &fin);
        if (fin == p)
            break;
        v[leidos++] = x;
        p = fin;
    }

    if (loc_c) {
        uselocale(previa);
        freelocale(loc_c);
    }
    if (leidos < 4)
        return 0;
    g->a = v[0];
    g->b = v[1];
    g->c = v[2];
    g->base = v[3];
    g->con_hora = leidos == 5 && v[4] >= 0.0 && v[4] < 1.0;
    g->hora = g->con_hora ? v[4] : 0.0;
    return 1;
}

double we_giro_grados(const WeGiro *g, double hora)
{
    return g->a * fmod(g->b * hora, 1.0) + g->c;
}

double we_hora_del_dia(time_t segundos, long nanosegundos)
{
    struct tm t;
    if (!localtime_r(&segundos, &t))
        return 0.0;
    /* Un segundo intercalar (`tm_sec` 60) no pasa de las 23:59:59,999. */
    double s = t.tm_hour * 3600.0 + t.tm_min * 60.0 + t.tm_sec
             + nanosegundos / 1e9;
    double d = s / 86400.0;
    return d < 1.0 ? d : nextafter(1.0, 0.0);
}

void we_giro_coloca(const WeGiro *g, double grados, double aspecto,
                    float m[16])
{
    /* La colocación que escribe `object_mvp` es D · R(ángulo) · E, con E la
     * semiextensión en píxeles y D = diag(2/w, 2/h) el paso a clip: el giro
     * va en píxeles del lienzo. Girar a `grados` es entonces
     * D · R(grados - base) · D⁻¹ por la que trae el plan, y así sale lo mismo
     * que horneando ese ángulo en `angles`. De D solo queda el cociente
     * w/h: la fila de x se mezcla con la de y por h/w y la de y con la de x
     * por w/h. Con el giro directo en clip, R(Δ) · m, una capa girada de un
     * lienzo no cuadrado salía estirada y cizallada; ver NOTAS. */
    const double d = (grados - g->base) * (3.14159265358979323846 / 180.0);
    const double c = cos(d), s = sin(d);
    const double k = aspecto > 0.0 ? aspecto : 1.0;
    const double m0 = m[0], m1 = m[1], m4 = m[4], m5 = m[5];
    m[0] = (float)(c * m0 - s * m4 / k);
    m[1] = (float)(c * m1 - s * m5 / k);
    m[4] = (float)(s * k * m0 + c * m4);
    m[5] = (float)(s * k * m1 + c * m5);
}
