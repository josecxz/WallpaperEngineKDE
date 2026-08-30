/* Ver `wereloj.h`. Compartido por los dos ejecutores. */

/* `uselocale`, `newlocale` y `localtime_r` son POSIX, no C11: con -std=c11 a
 * secas el compilador no ve sus declaraciones. */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include "wereloj.h"

#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_PLANTILLA 512
#define MAX_TABLAS      3
#define MAX_FILAS      24
#define MAX_PALABRA    64
#define MAX_GLIFOS    192
#define MAX_TEXTO     512

typedef struct {
    int cp;                 /* punto de código Unicode */
    float avance;           /* lo que empuja el cursor, en px del atlas */
    float ink[4];           /* x0 y0 x1 y1, respecto al cursor */
    float uv[4];
} Glifo;

typedef struct {
    char codigo[4];         /* "%A", "%B" o "%N" */
    int filas;
    char palabra[MAX_FILAS][MAX_PALABRA];
} Tabla;

struct WeReloj {
    char plantilla[MAX_PLANTILLA];
    Tabla tabla[MAX_TABLAS];
    int n_tablas;
    Glifo glifo[MAX_GLIFOS];
    int n_glifos;

    float periodo;
    float caja[2], pad[2];
    int halign, valign;     /* 0 izquierda/arriba, 1 centro, 2 derecha/abajo */
    float u;                /* unidades de lienzo por píxel del atlas */
    float alto_linea;
    int max_glifos;
    int configurado;
};

WeReloj *we_reloj_nuevo(void)
{
    WeReloj *r = calloc(1, sizeof *r);
    if (r) {
        r->periodo = 60.0f;
        r->u = 1.0f;
    }
    return r;
}

void we_reloj_free(WeReloj *r)
{
    free(r);
}

/* ── lectura del plan ───────────────────────────────────────────────────── */

/* Las cadenas del plan viajan con los espacios escapados: una línea del plan
 * se parte por espacios y hay nombres de mes que llevan uno dentro
 * ---`Thứ Sáu`, de la fecha en vietnamita de `3299228616`---. */
static void desescapa(const char *src, char *dst, int tope)
{
    int j = 0;
    /* La linea llega de `fgets`, con su salto al final: sin quitarlo la
     * plantilla acaba en `\n` y el reloj escribe una linea de mas. */
    int largo = 0;
    while (src[largo]) largo++;
    while (largo > 0 && (src[largo - 1] == '\n' || src[largo - 1] == '\r'
                         || src[largo - 1] == ' ' || src[largo - 1] == '\t'))
        largo--;
    for (int i = 0; i < largo && j < tope - 1; i++) {
        if (src[i] == '\\' && src[i + 1] == 's') {
            dst[j++] = ' ';
            i++;
        } else if (src[i] == '\\' && src[i + 1] == '\\') {
            dst[j++] = '\\';
            i++;
        } else {
            dst[j++] = src[i];
        }
    }
    dst[j] = 0;
}

static const char *tras_palabra(const char *s)
{
    while (*s && *s != ' ' && *s != '\t') s++;
    while (*s == ' ' || *s == '\t') s++;
    return s;
}

int we_reloj_linea(WeReloj *r, const char *kw, const char *resto)
{
    if (!r || !kw || !resto)
        return 0;

    /* `strtof` mira LC_NUMERIC, y Qt adopta la locale del entorno al arrancar:
     * dentro de plasmashell con es_ES el punto deja de separar decimales y
     * todas las métricas se leen como cero. Es el mismo agujero por el que se
     * cayeron las partículas; la cura también es la misma, y solo para este
     * hilo y solo la parte numérica. */
    locale_t loc_c = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
    locale_t previa = loc_c ? uselocale(loc_c) : (locale_t)0;
    int ok = 0;

    if (strcmp(kw, "reloj") == 0) {
        float v[10] = {0};
        int n = 0;
        const char *p = resto;
        while (n < 10 && *p) {
            char *fin;
            float x = strtof(p, &fin);
            if (fin == p) break;
            v[n++] = x;
            p = fin;
        }
        if (n >= 10) {
            r->periodo = v[0] > 0.0f ? v[0] : 60.0f;
            r->caja[0] = v[1]; r->caja[1] = v[2];
            r->pad[0] = v[3];  r->pad[1] = v[4];
            r->halign = (int)v[5];
            r->valign = (int)v[6];
            r->u = v[7] != 0.0f ? v[7] : 1.0f;
            r->alto_linea = v[8];
            r->max_glifos = (int)v[9];
            if (r->max_glifos > MAX_GLIFOS) r->max_glifos = MAX_GLIFOS;
            r->configurado = 1;
            ok = 1;
        }
    } else if (strcmp(kw, "relojfmt") == 0) {
        desescapa(resto, r->plantilla, MAX_PLANTILLA);
        ok = 1;
    } else if (strcmp(kw, "relojtab") == 0) {
        char codigo[4] = {0};
        int filas = 0;
        if (sscanf(resto, "%3s %d", codigo, &filas) == 2 && r->n_tablas < MAX_TABLAS
                && filas > 0 && filas <= MAX_FILAS) {
            Tabla *t = &r->tabla[r->n_tablas];
            snprintf(t->codigo, sizeof t->codigo, "%s", codigo);
            t->filas = filas;
            const char *p = tras_palabra(tras_palabra(resto));
            for (int i = 0; i < filas && *p; i++) {
                char cruda[MAX_PALABRA * 2] = {0};
                if (sscanf(p, "%127s", cruda) != 1) break;
                desescapa(cruda, t->palabra[i], MAX_PALABRA);
                p = tras_palabra(p);
            }
            r->n_tablas++;
            ok = 1;
        }
    } else if (strcmp(kw, "relojglifo") == 0) {
        if (r->n_glifos < MAX_GLIFOS) {
            Glifo *g = &r->glifo[r->n_glifos];
            float v[10] = {0};
            int n = 0;
            const char *p = resto;
            while (n < 10 && *p) {
                char *fin;
                float x = strtof(p, &fin);
                if (fin == p) break;
                v[n++] = x;
                p = fin;
            }
            if (n >= 10) {
                g->cp = (int)v[0];
                g->avance = v[1];
                for (int i = 0; i < 4; i++) g->ink[i] = v[2 + i];
                for (int i = 0; i < 4; i++) g->uv[i] = v[6 + i];
                r->n_glifos++;
                ok = 1;
            }
        }
    }

    if (loc_c) {
        uselocale(previa);
        freelocale(loc_c);
    }
    return ok;
}

int we_reloj_nvertices(const WeReloj *r)
{
    return r && r->configurado ? r->max_glifos * 4 : 0;
}

int we_reloj_nindices(const WeReloj *r)
{
    return r && r->configurado ? r->max_glifos * 6 : 0;
}

float we_reloj_periodo(const WeReloj *r)
{
    return r ? r->periodo : 60.0f;
}

/* ── rellenar la plantilla ──────────────────────────────────────────────── */

static const char *palabra_de(const WeReloj *r, const char *codigo, int fila)
{
    for (int i = 0; i < r->n_tablas; i++)
        if (strncmp(r->tabla[i].codigo, codigo, 2) == 0) {
            if (fila < 0 || fila >= r->tabla[i].filas)
                return "";
            return r->tabla[i].palabra[fila];
        }
    return "";
}

static int anade(char *salida, int j, int tope, const char *texto)
{
    while (*texto && j < tope - 1)
        salida[j++] = *texto++;
    return j;
}

int we_reloj_texto(const WeReloj *r, time_t cuando, char *salida, int tope)
{
    if (!r || !salida || tope < 2)
        return 0;
    struct tm tm;
    localtime_r(&cuando, &tm);

    int j = 0;
    char num[32];
    for (int i = 0; r->plantilla[i] && j < tope - 1; i++) {
        if (r->plantilla[i] != '%' || !r->plantilla[i + 1]) {
            salida[j++] = r->plantilla[i];
            continue;
        }
        char c = r->plantilla[++i];
        int h12 = tm.tm_hour % 12;
        if (h12 == 0) h12 = 12;
        switch (c) {
        case '%': salida[j++] = '%'; break;
        case 'H': snprintf(num, sizeof num, "%02d", tm.tm_hour); j = anade(salida, j, tope, num); break;
        case 'k': snprintf(num, sizeof num, "%d", tm.tm_hour);   j = anade(salida, j, tope, num); break;
        case 'I': snprintf(num, sizeof num, "%02d", h12);        j = anade(salida, j, tope, num); break;
        case 'l': snprintf(num, sizeof num, "%d", h12);          j = anade(salida, j, tope, num); break;
        case 'M': snprintf(num, sizeof num, "%02d", tm.tm_min);  j = anade(salida, j, tope, num); break;
        case 'S': snprintf(num, sizeof num, "%02d", tm.tm_sec);  j = anade(salida, j, tope, num); break;
        case 'd': snprintf(num, sizeof num, "%02d", tm.tm_mday); j = anade(salida, j, tope, num); break;
        case 'e': snprintf(num, sizeof num, "%d", tm.tm_mday);   j = anade(salida, j, tope, num); break;
        case 'm': snprintf(num, sizeof num, "%02d", tm.tm_mon + 1); j = anade(salida, j, tope, num); break;
        case 'f': snprintf(num, sizeof num, "%d", tm.tm_mon + 1);   j = anade(salida, j, tope, num); break;
        case 'Y': snprintf(num, sizeof num, "%04d", tm.tm_year + 1900); j = anade(salida, j, tope, num); break;
        case 'y': snprintf(num, sizeof num, "%02d", (tm.tm_year + 1900) % 100); j = anade(salida, j, tope, num); break;
        case 'p': j = anade(salida, j, tope, tm.tm_hour < 12 ? "AM" : "PM"); break;
        case 'P': j = anade(salida, j, tope, tm.tm_hour < 12 ? "am" : "pm"); break;
        case 'A': j = anade(salida, j, tope, palabra_de(r, "%A", tm.tm_wday)); break;
        case 'B': j = anade(salida, j, tope, palabra_de(r, "%B", tm.tm_mon)); break;
        case 'N': j = anade(salida, j, tope, palabra_de(r, "%N", tm.tm_hour)); break;
        default:
            salida[j++] = '%';
            if (j < tope - 1) salida[j++] = c;
            break;
        }
    }
    salida[j] = 0;
    return j;
}

/* ── disposición ────────────────────────────────────────────────────────── */

/* UTF-8 -> punto de código. Devuelve cuántos bytes ha consumido. Una secuencia
 * mal formada se toma como un byte suelto: peor un glifo raro que un bucle. */
static int siguiente_cp(const char *s, int *cp)
{
    unsigned char c = (unsigned char)s[0];
    if (c < 0x80) { *cp = c; return 1; }
    if ((c & 0xE0) == 0xC0 && (s[1] & 0xC0) == 0x80) {
        *cp = ((c & 0x1F) << 6) | (s[1] & 0x3F);
        return 2;
    }
    if ((c & 0xF0) == 0xE0 && (s[1] & 0xC0) == 0x80 && (s[2] & 0xC0) == 0x80) {
        *cp = ((c & 0x0F) << 12) | ((s[1] & 0x3F) << 6) | (s[2] & 0x3F);
        return 3;
    }
    if ((c & 0xF8) == 0xF0 && (s[1] & 0xC0) == 0x80 && (s[2] & 0xC0) == 0x80
            && (s[3] & 0xC0) == 0x80) {
        *cp = ((c & 0x07) << 18) | ((s[1] & 0x3F) << 12)
            | ((s[2] & 0x3F) << 6) | (s[3] & 0x3F);
        return 4;
    }
    *cp = c;
    return 1;
}

static const Glifo *busca_glifo(const WeReloj *r, int cp)
{
    for (int i = 0; i < r->n_glifos; i++)
        if (r->glifo[i].cp == cp)
            return &r->glifo[i];
    return NULL;
}

int we_reloj_vertices(const WeReloj *r, time_t cuando, float *verts)
{
    if (!r || !r->configurado || !verts || r->n_glifos <= 0)
        return 0;

    char texto[MAX_TEXTO];
    we_reloj_texto(r, cuando, texto, MAX_TEXTO);

    /* Primera pasada: cuánto avanza la línea entera. Hace falta antes de
     * colocar nada, porque la alineación se mide desde el otro extremo. */
    float avance = 0.0f;
    for (int i = 0; texto[i];) {
        int cp;
        i += siguiente_cp(texto + i, &cp);
        const Glifo *g = busca_glifo(r, cp);
        if (g) avance += g->avance;
    }

    float util_w = r->caja[0] - 2.0f * r->pad[0];
    float util_h = r->caja[1] - 2.0f * r->pad[1];
    if (util_w < 0.0f) util_w = 0.0f;
    if (util_h < 0.0f) util_h = 0.0f;

    float x_linea = (r->halign == 0) ? 0.0f
                  : (r->halign == 2) ? util_w / r->u - avance
                  : (util_w / r->u - avance) / 2.0f;
    float y_linea = (r->valign == 0) ? 0.0f
                  : (r->valign == 2) ? util_h / r->u - r->alto_linea
                  : (util_h / r->u - r->alto_linea) / 2.0f;

    memset(verts, 0, (size_t)r->max_glifos * 4 * 5 * sizeof *verts);
    float pluma = 0.0f;
    int n = 0;
    for (int i = 0; texto[i] && n < r->max_glifos;) {
        int cp;
        i += siguiente_cp(texto + i, &cp);
        const Glifo *g = busca_glifo(r, cp);
        if (!g)
            continue;
        if (g->ink[2] > g->ink[0]) {
            float x_a = (x_linea + pluma + g->ink[0]) * r->u;
            float x_b = (x_linea + pluma + g->ink[2]) * r->u;
            float y_a = (y_linea + g->ink[1]) * r->u;
            float y_b = (y_linea + g->ink[3]) * r->u;
            float X0 = -r->caja[0] / 2.0f + r->pad[0] + x_a;
            float X1 = -r->caja[0] / 2.0f + r->pad[0] + x_b;
            float Y0 =  r->caja[1] / 2.0f - r->pad[1] - y_a;
            float Y1 =  r->caja[1] / 2.0f - r->pad[1] - y_b;
            float esq[4][4] = {
                {X0, Y0, g->uv[0], 1.0f - g->uv[1]},
                {X1, Y0, g->uv[2], 1.0f - g->uv[1]},
                {X1, Y1, g->uv[2], 1.0f - g->uv[3]},
                {X0, Y1, g->uv[0], 1.0f - g->uv[3]},
            };
            for (int j = 0; j < 4; j++) {
                float *v = verts + (n * 4 + j) * 5;
                v[0] = esq[j][0];
                v[1] = esq[j][1];
                v[2] = 0.0f;
                v[3] = esq[j][2];
                v[4] = esq[j][3];
            }
            n++;
        }
        pluma += g->avance;
    }
    return r->max_glifos * 4;
}
