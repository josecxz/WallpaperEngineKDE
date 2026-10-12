/* Ver `wereloj.h`. Compartido por los dos ejecutores. */

/* `uselocale`, `newlocale` y `localtime_r` son POSIX, no C11: con -std=c11 a
 * secas el compilador no ve sus declaraciones. */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include "wereloj.h"

#include <limits.h>
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

/* El kerning de un par: lo que se suma a la pluma entre `a` y `b`. */
typedef struct {
    int a, b;
    float dx;               /* px del atlas */
} Par;

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
    /* Los pares van aparte y crecen según llegan: un alfabeto de 47 puede
     * traer más de dos mil, y la mayoría de los relojes ninguno. */
    Par *par;
    int n_pares, cap_pares;

    float periodo;
    float caja[2], pad[2];
    int halign, valign;     /* 0 izquierda/arriba, 1 centro, 2 derecha/abajo */
    float u;                /* unidades de lienzo por píxel del atlas */
    float alto_linea;
    float espaciado;        /* entre renglón y renglón, en px del atlas */
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
    if (r)
        free(r->par);
    free(r);
}

/* ── lectura del plan ───────────────────────────────────────────────────── */

/* Las cadenas del plan viajan con los espacios escapados: una línea del plan
 * se parte por espacios y hay nombres de mes que llevan uno dentro
 * ---`Thứ Sáu`, de la fecha en vietnamita de `3299228616`---. El salto de
 * línea también, como `\n`: partiría la línea del plan en dos, y hay tablas
 * que lo llevan ---el `SATURDAY` de `2946362143` empieza por uno---. */
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
        } else if (src[i] == '\\' && src[i + 1] == 'n') {
            dst[j++] = '\n';
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
        /* Diez obligatorios y el espaciado entre renglones, que llegó después
         * y va el último: un plan anterior no lo trae y vale cero. */
        float v[11] = {0};
        int n = 0;
        const char *p = resto;
        while (n < 11 && *p) {
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
            r->espaciado = v[10];
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
    } else if (strcmp(kw, "relojkern") == 0) {
        /* `<cp_a> <cp_b> <dx>`. Llegó después que las demás y va en su propia
         * línea: un ejecutor anterior no la entiende y dibuja sin kerning. */
        char *fin;
        const char *p = resto;
        long a = strtol(p, &fin, 10);
        int ok_a = fin != p;
        p = fin;
        long b = strtol(p, &fin, 10);
        int ok_b = fin != p;
        p = fin;
        float dx = strtof(p, &fin);
        if (ok_a && ok_b && fin != p) {
            if (r->n_pares == r->cap_pares) {
                int cap = r->cap_pares ? 2 * r->cap_pares : 64;
                Par *nuevo = realloc(r->par, (size_t)cap * sizeof *nuevo);
                if (nuevo) {
                    r->par = nuevo;
                    r->cap_pares = cap;
                }
            }
            if (r->n_pares < r->cap_pares) {
                r->par[r->n_pares].a = (int)a;
                r->par[r->n_pares].b = (int)b;
                r->par[r->n_pares].dx = dx;
                r->n_pares++;
                ok = 1;
            }
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

static float kern_de(const WeReloj *r, int a, int b)
{
    for (int i = 0; i < r->n_pares; i++)
        if (r->par[i].a == a && r->par[i].b == b)
            return r->par[i].dx;
    return 0.0f;
}

int we_reloj_vertices(const WeReloj *r, time_t cuando, float *verts)
{
    if (!r || !r->configurado || !verts || r->n_glifos <= 0)
        return 0;

    char texto[MAX_TEXTO];
    we_reloj_texto(r, cuando, texto, MAX_TEXTO);

    float util_w = r->caja[0] - 2.0f * r->pad[0];
    float util_h = r->caja[1] - 2.0f * r->pad[1];
    if (util_w < 0.0f) util_w = 0.0f;
    if (util_h < 0.0f) util_h = 0.0f;

    /* Los renglones se apilan como en `wetext.disponer`: el bloque se alinea
     * en vertical contando también los renglones VACÍOS ---el `SATURDAY` de
     * `2946362143` empieza por `\n`---, y cada renglón por su lado en
     * horizontal. Cuántos hay cambia con la hora, así que se cuenta aquí. */
    int renglones = 1;
    for (int i = 0; texto[i]; i++)
        if (texto[i] == '\n') renglones++;
    float bloque_h = renglones * r->alto_linea + (renglones - 1) * r->espaciado;
    float y_bloque = (r->valign == 0) ? 0.0f
                   : (r->valign == 2) ? util_h / r->u - bloque_h
                   : (util_h / r->u - bloque_h) / 2.0f;

    memset(verts, 0, (size_t)r->max_glifos * 4 * 5 * sizeof *verts);
    int n = 0;
    int inicio = 0;
    for (int k = 0; k < renglones; k++) {
        int fin = inicio;
        while (texto[fin] && texto[fin] != '\n') fin++;

        /* Primera pasada: cuánto avanza el renglón entero, con el kerning de
         * cada par. Hace falta antes de colocar nada, porque la alineación se
         * mide desde el otro extremo. El par se forma con el glifo anterior
         * que existe, igual que `_plumas` en `tools/wetext.py`. */
        float avance = 0.0f;
        int previo = -1;
        for (int i = inicio; i < fin;) {
            int cp;
            i += siguiente_cp(texto + i, &cp);
            const Glifo *g = busca_glifo(r, cp);
            if (!g)
                continue;
            if (previo >= 0)
                avance += kern_de(r, previo, cp);
            avance += g->avance;
            previo = cp;
        }
        float x_linea = (r->halign == 0) ? 0.0f
                      : (r->halign == 2) ? util_w / r->u - avance
                      : (util_w / r->u - avance) / 2.0f;
        float y_linea = y_bloque + k * (r->alto_linea + r->espaciado);

        float pluma = 0.0f;
        previo = -1;
        for (int i = inicio; i < fin && n < r->max_glifos;) {
            int cp;
            i += siguiente_cp(texto + i, &cp);
            const Glifo *g = busca_glifo(r, cp);
            if (!g)
                continue;
            if (previo >= 0)
                pluma += kern_de(r, previo, cp);
            previo = cp;
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
        inicio = texto[fin] ? fin + 1 : fin;
    }
    return r->max_glifos * 4;
}

/* ── hoja de sprites por hora ───────────────────────────────────────────── */

#define MAX_FOTOGRAMAS 256

struct WeHoja {
    int volteada;
    int n;                              /* fotogramas leídos */
    float fotograma[MAX_FOTOGRAMAS][6]; /* rotación (4) y traslación (2) */
    int hora[24];
    int completa;                       /* `hojahora` con sus 24 horas */
    float duracion[MAX_FOTOGRAMAS];     /* `frame_time`, en segundos */
    double total;                       /* la suma de las duraciones */
    int por_tiempo;                     /* `hojatiempo` leída entera */
    int textura[MAX_FOTOGRAMAS];        /* la del plan, de `hojaimagenes` */
    int con_texturas;                   /* `hojaimagenes` leída entera */
};

WeHoja *we_hoja_nueva(void)
{
    return calloc(1, sizeof(WeHoja));
}

void we_hoja_free(WeHoja *h)
{
    free(h);
}

int we_hoja_linea(WeHoja *h, const char *resto)
{
    if (!h || !resto)
        return 0;

    /* La misma guarda que `we_reloj_linea`: con la locale del escritorio,
     * es_ES, `strtof` leería `0.5` como `0`. */
    locale_t loc_c = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
    locale_t previa = loc_c ? uselocale(loc_c) : (locale_t)0;
    int ok = 0;

    /* Un ejecutor puede releer la misma hoja con una línea de otro tipo. */
    h->completa = h->por_tiempo = h->con_texturas = 0;

    const char *p = resto;
    char *fin;
    long volteada = strtol(p, &fin, 10);
    if (fin != p) {
        p = fin;
        long n = strtol(p, &fin, 10);
        if (fin != p && n > 0 && n <= MAX_FOTOGRAMAS) {
            p = fin;
            int leidos = 0;
            for (int i = 0; i < n * 6; i++) {
                float x = strtof(p, &fin);
                if (fin == p) break;
                h->fotograma[i / 6][i % 6] = x;
                p = fin;
                leidos++;
            }
            int horas = 0;
            for (int i = 0; leidos == n * 6 && i < 24; i++) {
                long f = strtol(p, &fin, 10);
                if (fin == p || f < 0 || f >= n) break;
                h->hora[i] = (int)f;
                p = fin;
                horas++;
            }
            if (horas == 24) {
                h->volteada = volteada != 0;
                h->n = (int)n;
                h->completa = 1;
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

/* En la textura volteada la v de las UV y la del quad van al revés que en
 * WE: v' = 1 - v en las dos. Sustituyendo en `T + u*R.xy + v*R.zw` sale otra
 * transformación del mismo tipo, y es la que se sube: cambian de signo las dos
 * componentes que mezclan la v con la u, y el origen pasa a la esquina de
 * abajo del fotograma. */
static void voltea(float rotacion[4], float traslacion[2])
{
    const float r[4] = {rotacion[0], rotacion[1], rotacion[2], rotacion[3]};
    const float t[2] = {traslacion[0], traslacion[1]};
    rotacion[1] = -r[1];
    rotacion[2] = -r[2];
    traslacion[0] = t[0] + r[2];
    traslacion[1] = 1.0f - t[1] - r[3];
}

int we_hoja_uniforms_we(const WeHoja *h, time_t cuando,
                        float rotacion[4], float traslacion[2])
{
    if (!h || !h->completa)
        return 0;
    struct tm tm;
    localtime_r(&cuando, &tm);
    const float *f = h->fotograma[h->hora[tm.tm_hour % 24]];
    for (int i = 0; i < 4; i++) rotacion[i] = f[i];
    traslacion[0] = f[4];
    traslacion[1] = f[5];
    return 1;
}

int we_hoja_uniforms(const WeHoja *h, time_t cuando,
                     float rotacion[4], float traslacion[2])
{
    if (!we_hoja_uniforms_we(h, cuando, rotacion, traslacion))
        return 0;
    if (h->volteada)
        voltea(rotacion, traslacion);
    return 1;
}

/* ── hoja de sprites por `frame_time` ───────────────────────────────────── */

/* `hojatiempo` lleva siete números por fotograma; `hojaimagenes`, ocho: los
 * mismos y, detrás, la textura del plan del fotograma. */
static int lee_por_tiempo(WeHoja *h, const char *resto, int con_textura)
{
    if (!h || !resto)
        return 0;
    h->completa = h->por_tiempo = h->con_texturas = 0;

    /* La misma guarda que `we_hoja_linea`. */
    locale_t loc_c = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
    locale_t previa = loc_c ? uselocale(loc_c) : (locale_t)0;
    int ok = 0;
    const int k = con_textura ? 8 : 7;

    const char *p = resto;
    char *fin;
    long volteada = strtol(p, &fin, 10);
    if (fin != p) {
        p = fin;
        long n = strtol(p, &fin, 10);
        if (fin != p && n > 0 && n <= MAX_FOTOGRAMAS) {
            p = fin;
            int leidos = 0;
            double total = 0.0;
            for (int i = 0; i < n * k; i++) {
                if (i % k == 7) {
                    long t = strtol(p, &fin, 10);
                    if (fin == p || t < 0 || t > INT_MAX) break;
                    h->textura[i / k] = (int)t;
                } else {
                    float x = strtof(p, &fin);
                    if (fin == p) break;
                    if (i % k < 6) {
                        h->fotograma[i / k][i % k] = x;
                    } else {
                        /* Una duración nula o negativa no cabe en el bucle
                         * de abajo; `werender.py` no las manda. */
                        if (!(x > 0.0f)) break;
                        h->duracion[i / k] = x;
                        total += x;
                    }
                }
                p = fin;
                leidos++;
            }
            if (leidos == n * k) {
                h->volteada = volteada != 0;
                h->n = (int)n;
                h->total = total;
                h->por_tiempo = 1;
                h->con_texturas = con_textura;
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

int we_hoja_tiempo_linea(WeHoja *h, const char *resto)
{
    return lee_por_tiempo(h, resto, 0);
}

int we_hoja_imagenes_linea(WeHoja *h, const char *resto)
{
    return lee_por_tiempo(h, resto, 1);
}

int we_hoja_fotograma_en(const WeHoja *h, double segundos)
{
    if (!h || !h->por_tiempo || !(h->total > 0.0))
        return -1;
    /* WE suma el paso de cada fotograma al tiempo del fotograma actual y,
     * cuando llega a su duración, pasa al siguiente; del último, al 0. Empieza
     * en el 0 con el tiempo a cero, así que a los `segundos` de escena está en
     * el que cubre `segundos` módulo la suma de las duraciones. El resto se
     * hace a mano para no tirar de libm: `tools/test_hoja.py` compila este
     * módulo sin `-lm`. */
    double t = segundos - (double)(long long)(segundos / h->total) * h->total;
    if (t < 0.0)
        t += h->total;
    double acumulado = 0.0;
    for (int i = 0; i < h->n; i++) {
        acumulado += h->duracion[i];
        if (t < acumulado)
            return i;
    }
    return h->n - 1;
}

int we_hoja_tiempo_uniforms(const WeHoja *h, double segundos,
                            float rotacion[4], float traslacion[2])
{
    int i = we_hoja_fotograma_en(h, segundos);
    if (i < 0)
        return 0;
    const float *f = h->fotograma[i];
    for (int k = 0; k < 4; k++) rotacion[k] = f[k];
    traslacion[0] = f[4];
    traslacion[1] = f[5];
    if (h->volteada)
        voltea(rotacion, traslacion);
    return 1;
}

int we_hoja_tiempo_textura(const WeHoja *h, double segundos)
{
    if (!h || !h->con_texturas)
        return -1;
    int i = we_hoja_fotograma_en(h, segundos);
    return i < 0 ? -1 : h->textura[i];
}
