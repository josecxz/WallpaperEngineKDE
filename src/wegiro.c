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
#include <string.h>

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
    /* La hora puede llegar como el marcador `@HORA@` sin sustituir: se salta
     * esa palabra para llegar al lienzo, que va detrás. */
    if (leidos == 4) {
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p == '@')
            while (*p && *p != ' ' && *p != '\t' && *p != '\n')
                p++;
    }
    long ancho = 0, alto = 0;
    if (leidos >= 4) {
        ancho = strtol(p, &fin, 10);
        if (fin != p) {
            p = fin;
            alto = strtol(p, &fin, 10);
            if (fin == p)
                ancho = 0;
        }
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
    g->ancho = ancho > 0 && alto > 0 ? (int)ancho : 0;
    g->alto = ancho > 0 && alto > 0 ? (int)alto : 0;
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

void we_giro_coloca(const WeGiro *g, double grados, float m[16])
{
    /* La colocación que escribe `object_mvp` es D · R(ángulo) · E, con E la
     * semiextensión en píxeles y D = diag(2/w, 2/h) el paso a clip: el giro
     * va en píxeles del lienzo. Girar a `grados` es entonces
     * D · R(grados - base) · D⁻¹ por la que trae el plan, y así sale lo mismo
     * que horneando ese ángulo en `angles`. De D solo queda el cociente
     * w/h: la fila de x se mezcla con la de y por h/w y la de y con la de x
     * por w/h. El w/h es el del lienzo de la escena que trae la línea, no el
     * de `canvas`, que en vivo es la resolución de dibujo redondeada y se
     * separa de él en la cuarta cifra. Con el giro directo en clip, R(Δ) · m,
     * una capa girada de un lienzo no cuadrado salía estirada y cizallada;
     * ver NOTAS. Sin lienzo en la línea, k = 1: un plan viejo, horneado así. */
    const double d = (grados - g->base) * (3.14159265358979323846 / 180.0);
    const double c = cos(d), s = sin(d);
    const double k = g->ancho > 0 && g->alto > 0
                   ? (double)g->ancho / g->alto : 1.0;
    const double m0 = m[0], m1 = m[1], m4 = m[4], m5 = m[5];
    m[0] = (float)(c * m0 - s * m4 / k);
    m[1] = (float)(c * m1 - s * m5 / k);
    m[4] = (float)(s * k * m0 + c * m4);
    m[5] = (float)(s * k * m1 + c * m5);
}

int we_vaiven_linea(WeVaiven *v, const char *resto)
{
    if (!v || !resto)
        return 0;
    const char *p = resto;
    while (*p == ' ' || *p == '\t')
        p++;
    int angulo;
    if (strncmp(p, "angles", 6) == 0)
        angulo = 1;
    else if (strncmp(p, "origin", 6) == 0)
        angulo = 0;
    else
        return 0;
    p += 6;

    /* La misma guarda que `we_giro_linea`. */
    locale_t loc_c = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
    locale_t previa = loc_c ? uselocale(loc_c) : (locale_t)0;

    double n[5];
    int leidos = 0;
    char *fin;
    while (leidos < 5) {
        double x = strtod(p, &fin);
        if (fin == p)
            break;
        n[leidos++] = x;
        p = fin;
    }
    /* El tiempo, o el marcador `@TIME@` sin sustituir, que se salta. */
    double t = 0.0;
    int con_tiempo = 0;
    if (leidos == 5) {
        t = strtod(p, &fin);
        if (fin != p) {
            con_tiempo = 1;
            p = fin;
        } else {
            while (*p == ' ' || *p == '\t')
                p++;
            if (*p == '@')
                while (*p && *p != ' ' && *p != '\t' && *p != '\n')
                    p++;
        }
    }
    double q[2];
    int detras = 0;
    while (leidos == 5 && detras < 2) {
        double x = strtod(p, &fin);
        if (fin == p)
            break;
        q[detras++] = x;
        p = fin;
    }

    if (loc_c) {
        uselocale(previa);
        freelocale(loc_c);
    }
    if (leidos < 5 || detras < 2)
        return 0;
    v->angulo = angulo;
    v->k = n[0];
    v->a = n[1];
    v->w = n[2];
    v->fase = n[3];
    v->base = n[4];
    v->t = t;
    v->con_tiempo = con_tiempo;
    v->p[0] = q[0];
    v->p[1] = q[1];
    return 1;
}

double we_vaiven_valor(const WeVaiven *v, double t)
{
    return v->k + v->a * sin(v->w * t + v->fase);
}

void we_vaiven_coloca(const WeVaiven *v, double t, float m[16])
{
    const double valor = we_vaiven_valor(v, t);
    if (v->angulo) {
        /* El giro de `giro`, con su `base` y su lienzo: la misma conversión
         * de grados y la misma cuenta en píxeles. */
        WeGiro g = {0};
        g.base = v->base;
        g.ancho = (int)v->p[0];
        g.alto = (int)v->p[1];
        we_giro_coloca(&g, valor, m);
        return;
    }
    /* En t = 0 el seno da 0 y, si el script parte del `value`, `valor` es
     * exactamente `base`: no se suma nada y la colocación queda la del plan. */
    const double d = valor - v->base;
    m[3] = (float)(m[3] + v->p[0] * d);
    m[7] = (float)(m[7] + v->p[1] * d);
}
