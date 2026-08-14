/* newlocale/uselocale son POSIX 2008 y con -std=c11 glibc no las declara sin
 * esto. Hacen falta para leer los numeros del .psys: ver we_psys_load. */
#define _POSIX_C_SOURCE 200809L

#include "weparticles.h"

#include <locale.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_PIEZAS 24
#define MAX_CP 8
#define MAX_F 12          /* floats por pieza; ninguna del corpus pasa de 9 */
#define PASO (1.0f / 60.0f)
/* Tope de simulacion en una sola llamada. Protege dos casos reales: el primer
 * fotograma, que tiene que recuperar `starttime` mas el instante pedido, y un
 * salto de reloj (suspension, cambio de wallpaper). Sin el, un `t` grande
 * bloquea el hilo de render. */
#define MAX_SEG_POR_LLAMADA 60.0f

/* ── vocabulario ───────────────────────────────────────────────────────────
 *
 * Los codigos y el ORDEN DE LOS FLOATS de cada pieza son el contrato con
 * `tools/weparticles.py`. Cambiar uno hay que cambiarlo en los dos sitios; por
 * eso el numero de floats se declara aqui y el cargador rechaza la pieza si no
 * cuadra, en vez de leer basura. */

enum { EM_ESFERA, EM_CAJA };

enum {
    IN_VIDA, IN_TAM, IN_ALFA, IN_COLOR, IN_VEL, IN_ROT, IN_ANGVEL, IN_TURBVEL
};
enum {
    OP_MOV, OP_FADE, OP_TAM, OP_ALFA, OP_COLOR, OP_OSCALFA, OP_OSCTAM,
    OP_OSCPOS, OP_ANGMOV, OP_TURB, OP_ATRAE, OP_VORTICE
};

typedef struct { const char *nombre; int codigo; int nfloats; } Entrada;

/* min[3] max[3] salvo donde se indique. */
static const Entrada INICIALIZADORES[] = {
    {"lifetimerandom",          IN_VIDA,    2},   /* min max */
    {"sizerandom",              IN_TAM,     2},   /* min max */
    {"alpharandom",             IN_ALFA,    2},   /* min max */
    {"colorrandom",             IN_COLOR,   6},
    {"velocityrandom",          IN_VEL,     6},
    {"rotationrandom",          IN_ROT,     6},
    {"angularvelocityrandom",   IN_ANGVEL,  6},
    /* escala, escalatiempo, velmin, velmax, fasemax, desplazamiento[3] */
    {"turbulentvelocityrandom", IN_TURBVEL, 8},
    {NULL, 0, 0},
};

static const Entrada OPERADORES[] = {
    {"movement",            OP_MOV,     4},   /* gravedad[3], rozamiento */
    {"alphafade",           OP_FADE,    2},   /* entrada, salida */
    {"sizechange",          OP_TAM,     4},   /* t0 t1 v0 v1 */
    {"alphachange",         OP_ALFA,    4},   /* t0 t1 v0 v1 */
    {"colorchange",         OP_COLOR,   8},   /* t0 t1 v0[3] v1[3] */
    {"oscillatealpha",      OP_OSCALFA, 6},   /* fmin fmax emin emax pmin pmax */
    {"oscillatesize",       OP_OSCTAM,  6},
    {"oscillateposition",   OP_OSCPOS,  9},   /* ...los 6 de arriba + mascara[3] */
    {"angularmovement",     OP_ANGMOV,  4},   /* fuerza[3], rozamiento */
    /* escala, escalatiempo, velmin, velmax, fasemin, fasemax, mascara[3] */
    {"turbulence",          OP_TURB,    9},
    /* punto de control, escala, umbral, desplazamiento[3] */
    {"controlpointattract", OP_ATRAE,   6},
    /* dist_interior, dist_exterior, vel_interior, vel_exterior, eje[3] */
    {"vortex",              OP_VORTICE, 7},
};

typedef struct { int codigo; float f[MAX_F]; } Pieza;

typedef struct {
    float pos[3], vel[3];
    float rot[3], angvel[3];
    float tam_base, alfa_base, color_base[3];
    float vida, edad;
    unsigned int semilla;
    int viva;
    /* Solo para las cintas: cuantos puntos de historial tiene ya y cuanto
     * falta para el siguiente. Ver `guarda_punto`. */
    int n_hist;
    float t_hist;
} Particula;

/* Un punto del historial de una cinta: posicion, tamano, color y alfa TAL COMO
 * estaban al pasar por ahi. */
#define WE_HIST_FLOATS 8

struct WeParticleSystem {
    int maxcount;
    float starttime;

    int emisor;                     /* -1 si el sistema no emite */
    float rate, dmin[3], dmax[3], dir[3], org[3], signo[3];
    float instantaneo, duracion;

    int n_init, n_oper;
    Pieza init[MAX_PIEZAS], oper[MAX_PIEZAS];

    float cp[MAX_CP][3];

    /* Como recorre la hoja de sprites: 0 = una pasada por vida, 1 = un
     * fotograma fijo elegido al azar. `anim_mult` repite la secuencia. */
    int anim_modo;
    float anim_mult;

    /* Cinta: 0 sprite suelto, 1 `rope`, 2 `ropetrail`. Los dos ultimos comparten
     * geometria y solo cambian el reparto de UV, que decide un combo. */
    int cinta;
    int puntos;                     /* longitud del historial de cada cinta */
    float intervalo;                /* segundos entre puntos del historial */
    float *hist;

    Particula *p;
    float *verts;
    int n_verts;

    float t_prev;
    float credito;                  /* particulas pendientes de emitir */
    int cursor;                     /* por donde seguir buscando hueco */
    float vivido;                   /* segundos simulados, para `duracion` */
    unsigned int rng;
    int arrancado;
};

/* ── aleatoriedad ──────────────────────────────────────────────────────────
 * xorshift32: reproducible y suficiente. Que sea reproducible no es un lujo:
 * la regresion compara PNG entre ejecuciones. */
static unsigned int siguiente(unsigned int *e)
{
    unsigned int x = *e ? *e : 0x9e3779b9u;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *e = x;
    return x;
}

static float azar(unsigned int *e) { return (siguiente(e) & 0xffffff) / 16777216.0f; }

/* Aleatorio ESTABLE derivado de la particula y de un indice. Los osciladores
 * necesitan una frecuencia y una fase propias de cada particula que no cambien
 * entre fotogramas; guardarlas costaria un array por operador, y derivarlas de
 * la semilla sale gratis. */
static float azar_fijo(unsigned int semilla, int indice)
{
    unsigned int x = semilla ^ (0x9e3779b9u * (unsigned int)(indice + 1));
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return (x & 0xffffff) / 16777216.0f;
}

static float mezcla(float a, float b, float t) { return a + (b - a) * t; }
static float sujeta(float v, float a, float b) { return v < a ? a : (v > b ? b : v); }

/* ── ruido ─────────────────────────────────────────────────────────────────
 * Ruido de valor en 3D y su rotacional. La turbulencia de WE es un campo
 * solenoidal (las particulas giran, no divergen); el rotacional de un potencial
 * de ruido da eso mismo sin tener que reproducir su implementacion exacta. */
static float ruido_hash(int x, int y, int z, int c)
{
    unsigned int h = (unsigned int)(x * 374761393 + y * 668265263 + z * 2147483647
                                    + c * 1274126177);
    h = (h ^ (h >> 13)) * 1274126177u;
    return ((h ^ (h >> 16)) & 0xffffff) / 8388608.0f - 1.0f;   /* -1..1 */
}

static float suave(float t) { return t * t * (3.0f - 2.0f * t); }

static float ruido(float x, float y, float z, int c)
{
    int ix = (int)floorf(x), iy = (int)floorf(y), iz = (int)floorf(z);
    float fx = suave(x - ix), fy = suave(y - iy), fz = suave(z - iz);
    float a = 0.0f;
    for (int dz = 0; dz < 2; dz++)
        for (int dy = 0; dy < 2; dy++)
            for (int dx = 0; dx < 2; dx++) {
                float w = (dx ? fx : 1.0f - fx) * (dy ? fy : 1.0f - fy)
                        * (dz ? fz : 1.0f - fz);
                a += w * ruido_hash(ix + dx, iy + dy, iz + dz, c);
            }
    return a;
}

static void rotacional(float x, float y, float z, float out[3])
{
    const float h = 0.5f;
    float dp3dy = (ruido(x, y + h, z, 2) - ruido(x, y - h, z, 2)) / (2 * h);
    float dp2dz = (ruido(x, y, z + h, 1) - ruido(x, y, z - h, 1)) / (2 * h);
    float dp1dz = (ruido(x, y, z + h, 0) - ruido(x, y, z - h, 0)) / (2 * h);
    float dp3dx = (ruido(x + h, y, z, 2) - ruido(x - h, y, z, 2)) / (2 * h);
    float dp2dx = (ruido(x + h, y, z, 1) - ruido(x - h, y, z, 1)) / (2 * h);
    float dp1dy = (ruido(x, y + h, z, 0) - ruido(x, y - h, z, 0)) / (2 * h);
    out[0] = dp3dy - dp2dz;
    out[1] = dp1dz - dp3dx;
    out[2] = dp2dx - dp1dy;
}

/* ── carga ─────────────────────────────────────────────────────────────── */

static int lee_floats(const char *linea, float *dst, int n)
{
    int leidos = 0;
    const char *p = linea;
    char *fin;
    while (leidos < n) {
        float v = strtof(p, &fin);
        if (fin == p)
            break;
        dst[leidos++] = v;
        p = fin;
    }
    return leidos;
}

/* Salta la palabra en curso y los espacios que la siguen. */
static const char *tras_palabra(const char *p)
{
    while (*p && *p != ' ' && *p != '\t' && *p != '\n') p++;
    while (*p == ' ' || *p == '\t') p++;
    return p;
}

static int busca(const Entrada *tabla, int n, const char *nombre, int *nfloats)
{
    for (int i = 0; i < n; i++)
        if (strcmp(tabla[i].nombre, nombre) == 0) {
            *nfloats = tabla[i].nfloats;
            return tabla[i].codigo;
        }
    return -1;
}

/* Formato del `.psys`, tal y como lo escribe `tools/weparticles.py`:
 *
 *   maxcount  <n>
 *   starttime <segundos>
 *   seed      <entero>
 *   anim      <0 secuencia | 1 fotograma fijo> <repeticiones por vida>
 *   emit  <sphererandom|boxrandom> <rate> <dmin[3]> <dmax[3]> <dir[3]>
 *         <origen[3]> <signo[3]> <instantaneas> <duracion>
 *   cp    <indice> <x> <y> <z>
 *   init  <nombre> <floats...>
 *   oper  <nombre> <floats...>
 *
 * Las lineas que empiezan por `#` son comentarios. Cualquier nombre que no este
 * en las tablas de arriba se cuenta como desconocido y se ignora: mas vale un
 * sistema incompleto que uno leyendo campos que no le corresponden. */
WeParticleSystem *we_psys_load(const char *path, int *piezas_desconocidas)
{
    FILE *f = fopen(path, "r");
    if (!f)
        return NULL;

    WeParticleSystem *s = calloc(1, sizeof *s);
    if (!s) { fclose(f); return NULL; }
    s->maxcount = 32;
    s->emisor = -1;
    s->anim_mult = 1.0f;
    s->rng = 0x1234567u;
    s->t_prev = -1.0f;
    for (int i = 0; i < 3; i++) s->dir[i] = 1.0f;

    /* `strtof` mira LC_NUMERIC. Este fichero lo escribe siempre con punto
     * decimal, pero el motor vive dentro de plasmashell, y Qt hace
     * setlocale(LC_ALL, "") al arrancar: con LC_NUMERIC=es_ES el punto deja de
     * ser separador y "0.88235" se lee como 0. La pieza se queda corta de
     * floats y se descarta como si no estuviera soportada --- 17 de 42 en el
     * primer wallpaper que se probo en el escritorio, todas las que llevaban
     * decimales. Fuera de plasmashell no se ve: un binario en C que nunca llama
     * a setlocale se queda en la locale "C" y lee bien. La C de este hilo, y
     * solo la numerica, para no tocar el formato del resto de la interfaz. */
    locale_t loc_c = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
    locale_t loc_previa = loc_c ? uselocale(loc_c) : (locale_t)0;

    int desconocidas = 0;
    char linea[1024], nombre[64];
    while (fgets(linea, sizeof linea, f)) {
        char kw[32];
        if (sscanf(linea, "%31s", kw) != 1 || kw[0] == '#')
            continue;
        const char *resto = tras_palabra(linea);

        if (strcmp(kw, "maxcount") == 0) {
            s->maxcount = atoi(resto);
        } else if (strcmp(kw, "starttime") == 0) {
            s->starttime = strtof(resto, NULL);
        } else if (strcmp(kw, "anim") == 0) {
            float v[2] = {0.0f, 1.0f};
            lee_floats(resto, v, 2);
            s->anim_modo = (int)v[0];
            s->anim_mult = v[1];
        } else if (strcmp(kw, "cinta") == 0) {
            float v[3] = {0.0f, 8.0f, 0.05f};
            lee_floats(resto, v, 3);
            s->cinta = (int)v[0];
            s->puntos = (int)v[1];
            s->intervalo = v[2];
        } else if (strcmp(kw, "seed") == 0) {
            s->rng = (unsigned int)strtoul(resto, NULL, 10);
            if (!s->rng) s->rng = 0x1234567u;
        } else if (strcmp(kw, "emit") == 0) {
            if (sscanf(resto, "%63s", nombre) != 1)
                continue;
            s->emisor = strcmp(nombre, "boxrandom") == 0 ? EM_CAJA : EM_ESFERA;
            float v[18] = {0};
            lee_floats(tras_palabra(resto), v, 18);
            s->rate = v[0];
            for (int i = 0; i < 3; i++) {
                s->dmin[i] = v[1 + i];
                s->dmax[i] = v[4 + i];
                s->dir[i] = v[7 + i];
                s->org[i] = v[10 + i];
                s->signo[i] = v[13 + i];
            }
            s->instantaneo = v[16];
            s->duracion = v[17];
        } else if (strcmp(kw, "cp") == 0) {
            float v[4] = {0};
            if (lee_floats(resto, v, 4) == 4) {
                int i = (int)v[0];
                if (i >= 0 && i < MAX_CP) {
                    s->cp[i][0] = v[1]; s->cp[i][1] = v[2]; s->cp[i][2] = v[3];
                }
            }
        } else if (strcmp(kw, "init") == 0 || strcmp(kw, "oper") == 0) {
            int es_init = kw[0] == 'i';
            if (sscanf(resto, "%63s", nombre) != 1)
                continue;
            int nf = 0, codigo;
            if (es_init)
                codigo = busca(INICIALIZADORES,
                               (int)(sizeof INICIALIZADORES / sizeof *INICIALIZADORES) - 1,
                               nombre, &nf);
            else
                codigo = busca(OPERADORES,
                               (int)(sizeof OPERADORES / sizeof *OPERADORES),
                               nombre, &nf);
            if (codigo < 0) { desconocidas++; continue; }
            Pieza pz;
            memset(&pz, 0, sizeof pz);
            pz.codigo = codigo;
            if (lee_floats(tras_palabra(resto), pz.f, nf) != nf) {
                desconocidas++;
                continue;
            }
            if (es_init) {
                if (s->n_init < MAX_PIEZAS) s->init[s->n_init++] = pz;
            } else {
                if (s->n_oper < MAX_PIEZAS) s->oper[s->n_oper++] = pz;
            }
        }
    }
    fclose(f);

    if (loc_c) {
        uselocale(loc_previa ? loc_previa : LC_GLOBAL_LOCALE);
        freelocale(loc_c);
    }

    if (s->maxcount < 1) s->maxcount = 1;
    /* Tope duro. El corpus llega a declarar 50000 particulas, y a 6 vertices de
     * 17 floats cada una eso son 20 MB de VBO reescritos por fotograma. 8192
     * dan 3.3 MB y ya son mas particulas de las que se distinguen en pantalla.
     * Recorta la densidad de un par de sistemas; quedarse sin ancho de banda de
     * memoria en el escritorio seria peor. */
    if (s->maxcount > 8192) s->maxcount = 8192;

    size_t v_por_particula = WE_PSYS_VERTICES_POR_PARTICULA;
    size_t floats = WE_PSYS_FLOATS_POR_VERTICE;
    if (s->cinta) {
        if (s->puntos < 2) s->puntos = 2;
        if (s->puntos > 32) s->puntos = 32;
        if (s->intervalo < PASO) s->intervalo = PASO;
        /* Una cinta cuesta (puntos-1) quads por particula, no uno. Con el tope
         * de 8192 y 8 puntos serian 35 MB de VBO reescritos por fotograma; el
         * corpus no pasa de 512 particulas en un sistema de cinta. */
        if (s->maxcount > 1024) s->maxcount = 1024;
        v_por_particula *= (size_t)(s->puntos - 1);
        floats = WE_PSYS_FLOATS_CINTA;
        s->hist = calloc((size_t)s->maxcount * s->puntos * WE_HIST_FLOATS,
                         sizeof *s->hist);
        if (!s->hist) { we_psys_free(s); return NULL; }
    }
    s->p = calloc((size_t)s->maxcount, sizeof *s->p);
    s->verts = calloc((size_t)s->maxcount * v_por_particula * floats,
                      sizeof *s->verts);
    if (!s->p || !s->verts) { we_psys_free(s); return NULL; }

    if (piezas_desconocidas)
        *piezas_desconocidas = desconocidas;
    return s;
}

void we_psys_free(WeParticleSystem *s)
{
    if (!s) return;
    free(s->p);
    free(s->verts);
    free(s->hist);
    free(s);
}

/* ── nacimiento ────────────────────────────────────────────────────────── */

static void emite(WeParticleSystem *s, Particula *q)
{
    memset(q, 0, sizeof *q);
    q->viva = 1;
    q->semilla = siguiente(&s->rng);
    q->vida = 1.0f;
    q->tam_base = 32.0f;
    q->alfa_base = 1.0f;
    q->color_base[0] = q->color_base[1] = q->color_base[2] = 1.0f;

    /* Posicion. `directions` da la FORMA del volumen de emision: en la esfera
     * deforma la direccion unitaria a un elipsoide, en la caja escala cada
     * semieje. Es lo que aplana casi todos los sistemas del corpus contra el
     * plano z=0 (`1 0.2 0`, `1 0.03 0`...). */
    float d[3];
    if (s->emisor == EM_CAJA) {
        for (int i = 0; i < 3; i++)
            d[i] = (azar(&s->rng) * 2.0f - 1.0f) * s->dmax[i] * s->dir[i];
    } else {
        float u[3];
        for (int i = 0; i < 3; i++)
            u[i] = azar(&s->rng) * 2.0f - 1.0f;
        float n = sqrtf(u[0] * u[0] + u[1] * u[1] + u[2] * u[2]);
        if (n < 1e-6f) { u[0] = 1.0f; u[1] = u[2] = 0.0f; n = 1.0f; }
        float radio = mezcla(s->dmin[0], s->dmax[0], azar(&s->rng));
        for (int i = 0; i < 3; i++)
            d[i] = u[i] / n * radio * s->dir[i];
    }
    /* `sign` fuerza el semieje: 29 sistemas emiten solo hacia un lado. */
    for (int i = 0; i < 3; i++) {
        if (s->signo[i] > 0.0f && d[i] < 0.0f) d[i] = -d[i];
        else if (s->signo[i] < 0.0f && d[i] > 0.0f) d[i] = -d[i];
        q->pos[i] = s->org[i] + d[i];
    }

    for (int i = 0; i < s->n_init; i++) {
        const float *v = s->init[i].f;
        float t = azar(&s->rng);
        switch (s->init[i].codigo) {
        case IN_VIDA:  q->vida = mezcla(v[0], v[1], t); break;
        case IN_TAM:   q->tam_base = mezcla(v[0], v[1], t); break;
        case IN_ALFA:  q->alfa_base = mezcla(v[0], v[1], t); break;
        case IN_COLOR:
            /* UN solo aleatorio para las tres componentes: el color sale de la
             * recta que une los dos declarados.
             *
             * Sortear cada componente por separado parece dar mas variedad,
             * pero da la variedad equivocada. El preset de luciernagas declara
             * min (246, 207, 135) y max (0, 0, 0): por componente salen
             * particulas rojas puras y verdes puras --- se veian como luces de
             * navidad --- y con un unico factor salen todas del mismo ambar, a
             * distinto brillo, que es lo que el autor pidio al elegir esos dos
             * colores. */
            for (int k = 0; k < 3; k++)
                q->color_base[k] = mezcla(v[k], v[3 + k], t);
            break;
        case IN_VEL:
            for (int k = 0; k < 3; k++)
                q->vel[k] += mezcla(v[k], v[3 + k], azar(&s->rng));
            break;
        case IN_ROT:
            for (int k = 0; k < 3; k++)
                q->rot[k] = mezcla(v[k], v[3 + k], azar(&s->rng));
            break;
        case IN_ANGVEL:
            for (int k = 0; k < 3; k++)
                q->angvel[k] = mezcla(v[k], v[3 + k], azar(&s->rng));
            break;
        case IN_TURBVEL: {
            /* Velocidad inicial tomada de un campo de ruido: las particulas
             * nacidas cerca salen en la misma direccion, que es lo que da a la
             * niebla y al humo su aspecto de corriente. */
            float c[3];
            rotacional(q->pos[0] * v[0] + v[5], q->pos[1] * v[0] + v[6],
                       q->pos[2] * v[0] + v[7], c);
            float vel = mezcla(v[2], v[3], azar(&s->rng));
            for (int k = 0; k < 3; k++)
                q->vel[k] += c[k] * vel;
            break;
        }
        default: break;
        }
    }
    if (q->vida < 1e-3f) q->vida = 1e-3f;
}

/* ── un paso de simulacion ─────────────────────────────────────────────── */

/* Vive mas abajo, con los vertices, porque necesita la modulacion. */
static void guarda_punto(WeParticleSystem *s, int i, const Particula *q);

static void paso(WeParticleSystem *s, float dt)
{
    /* Emision. El credito acumulado evita que un `rate` menor que un fotograma
     * por segundo --- los hay de 0.2 --- no emita nunca por truncamiento. */
    int emitiendo = s->duracion <= 0.0f || s->vivido < s->duracion;
    if (s->emisor >= 0 && emitiendo) {
        s->credito += s->rate * dt;
        while (s->credito >= 1.0f) {
            s->credito -= 1.0f;
            /* El hueco se busca desde donde acabo la ultima vez, no desde el
             * principio: con `maxcount` de 8192 y un ritmo de 700 por segundo,
             * empezar siempre en cero convierte la emision en cuadratica. */
            int hueco = -1;
            for (int n = 0; n < s->maxcount; n++) {
                int i = s->cursor + n;
                if (i >= s->maxcount) i -= s->maxcount;
                if (!s->p[i].viva) { hueco = i; break; }
            }
            if (hueco < 0) break;
            s->cursor = hueco + 1 >= s->maxcount ? 0 : hueco + 1;
            emite(s, &s->p[hueco]);
        }
    }
    s->vivido += dt;

    for (int i = 0; i < s->maxcount; i++) {
        Particula *q = &s->p[i];
        if (!q->viva)
            continue;
        q->edad += dt;
        if (q->edad >= q->vida) { q->viva = 0; continue; }

        for (int j = 0; j < s->n_oper; j++) {
            const float *v = s->oper[j].f;
            switch (s->oper[j].codigo) {
            case OP_MOV: {
                for (int k = 0; k < 3; k++)
                    q->vel[k] += v[k] * dt;
                /* Rozamiento exponencial en vez de `vel -= vel*drag*dt`: con
                 * drag 2.5 y un paso de 1/60 la version lineal es estable, pero
                 * ante un salto de reloj se pasa de largo y la velocidad
                 * cambia de signo. */
                if (v[3] > 0.0f) {
                    float f = expf(-v[3] * dt);
                    for (int k = 0; k < 3; k++) q->vel[k] *= f;
                }
                break;
            }
            case OP_ANGMOV: {
                for (int k = 0; k < 3; k++)
                    q->angvel[k] += v[k] * dt;
                if (v[3] > 0.0f) {
                    float f = expf(-v[3] * dt);
                    for (int k = 0; k < 3; k++) q->angvel[k] *= f;
                }
                break;
            }
            case OP_TURB: {
                float fase = azar_fijo(q->semilla, j * 4) * (v[5] - v[4]) + v[4];
                float c[3];
                rotacional(q->pos[0] * v[0] + fase,
                           q->pos[1] * v[0] + fase,
                           q->pos[2] * v[0] + s->vivido * v[1], c);
                float vel = mezcla(v[2], v[3], azar_fijo(q->semilla, j * 4 + 1));
                for (int k = 0; k < 3; k++)
                    q->vel[k] += c[k] * vel * v[6 + k] * dt;
                break;
            }
            case OP_ATRAE: {
                int idx = (int)v[0];
                const float *cp = (idx >= 0 && idx < MAX_CP) ? s->cp[idx] : s->cp[0];
                float d[3], n2 = 0.0f;
                for (int k = 0; k < 3; k++) {
                    d[k] = q->pos[k] - (cp[k] + v[3 + k]);
                    n2 += d[k] * d[k];
                }
                float n = sqrtf(n2);
                /* Fuera del umbral no actua: es lo que deja a las luciernagas
                 * vagando y solo las recoge cuando se alejan demasiado. */
                if (n > v[2] && n > 1e-4f)
                    for (int k = 0; k < 3; k++)
                        q->vel[k] += d[k] / n * v[1] * dt;
                break;
            }
            case OP_VORTICE: {
                float d[3] = {q->pos[0], q->pos[1], q->pos[2]};
                float n = sqrtf(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
                if (n > 1e-4f) {
                    float t = sujeta((n - v[0]) / (v[1] - v[0] + 1e-6f), 0.0f, 1.0f);
                    float vel = mezcla(v[2], v[3], t);
                    /* Tangente = eje x radio, normalizada por el radio para que
                     * la velocidad pedida sea lineal y no angular. */
                    float e[3] = {v[4], v[5], v[6]};
                    float tg[3] = {e[1] * d[2] - e[2] * d[1],
                                   e[2] * d[0] - e[0] * d[2],
                                   e[0] * d[1] - e[1] * d[0]};
                    float tn = sqrtf(tg[0] * tg[0] + tg[1] * tg[1] + tg[2] * tg[2]);
                    /* ARRASTRA, no empuja: mueve la posicion y deja la
                     * velocidad como estaba. Sumandolo a la velocidad, la
                     * particula acumula tangencial sin nada que la retenga y
                     * la orbita se abre en espiral --- en `3219398263` las
                     * cintas acababan cruzando el cielo entero, y el preview
                     * las tiene cortas y pegadas al contorno de la esfera.
                     * Fijar la velocidad tampoco vale: con `speedouter: 0`
                     * ---los petalos de `2788036464`--- congelaria todo lo que
                     * cae fuera del radio. Como campo de arrastre los cuatro
                     * grupos del corpus se sostienen a la vez. */
                    if (tn > 1e-4f)
                        for (int k = 0; k < 3; k++)
                            q->pos[k] += tg[k] / tn * vel * dt;
                }
                break;
            }
            default: break;      /* los de modulacion se evaluan al construir */
            }
        }

        for (int k = 0; k < 3; k++) {
            q->pos[k] += q->vel[k] * dt;
            q->rot[k] += q->angvel[k] * dt;
        }

        if (s->cinta) {
            /* El primer punto se guarda al nacer, para que una particula
             * recien emitida tenga ya cinta --- corta, pero cinta. */
            q->t_hist -= dt;
            if (q->n_hist == 0 || q->t_hist <= 0.0f) {
                q->t_hist = s->intervalo;
                guarda_punto(s, (int)(q - s->p), q);
            }
        }
    }
}

/* ── modulacion y vertices ─────────────────────────────────────────────── */

/* Rampa de un operador `*change`: constante fuera de [t0, t1]. */
static float rampa(float vn, float t0, float t1, float v0, float v1)
{
    if (t1 <= t0) return vn >= t1 ? v1 : v0;
    return mezcla(v0, v1, sujeta((vn - t0) / (t1 - t0), 0.0f, 1.0f));
}

/* Estado visible de una particula en este instante: lo que los operadores de
 * modulacion hacen con su tamano, su color, su alfa y su posicion.
 *
 * Esta aparte porque lo necesitan dos sitios y con la misma cuenta: el
 * constructor de vertices, y el muestreo del historial de las estelas. Un
 * punto de la cola tiene que guardar el tamano y el color que tenia CUANDO
 * paso por ahi; calcularlo al dibujar daria una cinta de color uniforme que se
 * apaga de golpe. */
typedef struct { float tam, alfa, col[3], desp[3]; } Modulado;

static void modula(const WeParticleSystem *s, const Particula *q, Modulado *m)
{
    float vn = sujeta(q->edad / q->vida, 0.0f, 0.999999f);
    m->tam = q->tam_base;
    m->alfa = q->alfa_base;
    for (int k = 0; k < 3; k++) {
        m->col[k] = q->color_base[k];
        m->desp[k] = 0.0f;
    }

    for (int j = 0; j < s->n_oper; j++) {
        const float *v = s->oper[j].f;
        switch (s->oper[j].codigo) {
        case OP_FADE:
            /* fadeintime y fadeouttime son fracciones de la vida: sube
             * hasta la primera y baja a partir de la segunda. */
            if (v[0] > 0.0f && vn < v[0])
                m->alfa *= vn / v[0];
            if (v[1] > 0.0f && v[1] < 1.0f && vn > v[1])
                m->alfa *= 1.0f - (vn - v[1]) / (1.0f - v[1]);
            break;
        case OP_TAM:
            m->tam *= rampa(vn, v[0], v[1], v[2], v[3]);
            break;
        case OP_ALFA:
            m->alfa *= rampa(vn, v[0], v[1], v[2], v[3]);
            break;
        case OP_COLOR:
            /* FIJA el color, no lo modula. Se ve en una antorcha del
             * corpus: su preset nace en cian --- (0, 0.91, 1) --- y el
             * operador va de naranja (1, 0.75, 0) a rojo. Multiplicando,
             * las dos componentes que el operador pone a cero anulan las
             * del preset y la llama sale NEGRA; el sistema simulaba bien y
             * no se veia nada. Fijando, sale la llama que el autor pinto.
             *
             * El tinte del objeto no se pierde: `weparticles.py` lo aplica
             * tambien sobre estos valores, no solo sobre `colorrandom`. */
            for (int k = 0; k < 3; k++)
                m->col[k] = rampa(vn, v[0], v[1], v[2 + k], v[5 + k]);
            break;
        case OP_OSCALFA:
        case OP_OSCTAM:
        case OP_OSCPOS: {
            float fr = mezcla(v[0], v[1], azar_fijo(q->semilla, j * 4));
            float fa = mezcla(v[4], v[5], azar_fijo(q->semilla, j * 4 + 1));
            float o = sinf(q->edad * fr + fa);
            if (s->oper[j].codigo == OP_OSCPOS) {
                float amp = mezcla(v[2], v[3], azar_fijo(q->semilla, j * 4 + 2));
                for (int k = 0; k < 3; k++)
                    m->desp[k] += o * amp * v[6 + k];
            } else {
                float e = mezcla(v[2], v[3], 0.5f + 0.5f * o);
                if (s->oper[j].codigo == OP_OSCALFA) m->alfa *= e;
                else m->tam *= e;
            }
            break;
        }
        default: break;
        }
    }
    m->alfa = sujeta(m->alfa, 0.0f, 1.0f);
}

/* ── estelas de cinta ──────────────────────────────────────────────────────
 *
 * `rope` y `ropetrail` no dibujan un sprite por particula sino una CINTA por
 * particula, cosida por donde ha pasado. Cada segmento de la cinta es un
 * elemento con sus dos extremos y dos puntos de control --- asi lo pide
 * `genericropeparticle.vert`, que en la ruta sin geometry shader los une con un
 * quad recto (la curva Bezier solo la evalua el geometry shader, con
 * `subdivision`, y esa ruta no la usamos).
 *
 * De ahi que haga falta guardar el historial: un punto cada `intervalo`
 * segundos, hasta `puntos`. El indice 0 es el mas reciente. */
static float *punto(WeParticleSystem *s, int particula, int i)
{
    return s->hist + ((size_t)particula * s->puntos + i) * WE_HIST_FLOATS;
}

static void guarda_punto(WeParticleSystem *s, int i, const Particula *q)
{
    Modulado m;
    modula(s, q, &m);
    float *h = punto(s, i, 0);
    /* El mas reciente entra por delante; los demas corren un puesto. Con 8
     * puntos de 8 floats el desplazamiento es mas barato que llevar un anillo
     * con su indice, y el constructor de vertices queda legible. */
    if (s->p[i].n_hist > 0)
        memmove(h + WE_HIST_FLOATS, h,
                (size_t)(s->puntos - 1) * WE_HIST_FLOATS * sizeof *h);
    for (int k = 0; k < 3; k++)
        h[k] = q->pos[k] + m.desp[k];
    h[3] = m.tam;
    h[4] = m.col[0]; h[5] = m.col[1]; h[6] = m.col[2]; h[7] = m.alfa;
    if (s->p[i].n_hist < s->puntos)
        s->p[i].n_hist++;
}

static int construye_cinta(WeParticleSystem *s)
{
    float *w = s->verts;
    int n = 0;
    /* Las cuatro esquinas del quad del segmento. `u` cruza la cinta y `v` la
     * recorre; el shader las usa para las dos cosas a la vez --- posicion y
     * coordenada de textura --- asi que tienen que ir en [0, 1]. */
    static const float esq[6][2] = {
        {0, 0}, {1, 0}, {0, 1},
        {0, 1}, {1, 0}, {1, 1},
    };

    for (int i = 0; i < s->maxcount; i++) {
        Particula *q = &s->p[i];
        if (!q->viva || q->n_hist < 2)
            continue;

        for (int seg = 0; seg + 1 < q->n_hist; seg++) {
            const float *a = punto(s, i, seg);       /* mas nuevo */
            const float *b = punto(s, i, seg + 1);   /* mas viejo */
            /* Los puntos de control son los vecinos de fuera del segmento; en
             * los extremos de la cinta no hay vecino y se refleja el propio
             * segmento, que da la misma tangente que tendria una prolongacion
             * recta. El shader hace `CP = extremo - control`. */
            const float *ca = seg > 0 ? punto(s, i, seg - 1) : NULL;
            const float *cb = seg + 2 < q->n_hist ? punto(s, i, seg + 2) : NULL;
            float cp0[3], cp1[3];
            for (int k = 0; k < 3; k++) {
                cp0[k] = ca ? ca[k] : 2.0f * a[k] - b[k];
                cp1[k] = cb ? cb[k] : 2.0f * b[k] - a[k];
            }

            for (int k = 0; k < 6; k++) {
                w[0] = a[0]; w[1] = a[1]; w[2] = a[2];
                w[3] = a[3];                                  /* tamano inicio */
                w[4] = b[0]; w[5] = b[1]; w[6] = b[2];
                w[7] = (float)q->n_hist;                      /* trailLength */
                w[8] = a[4]; w[9] = a[5]; w[10] = a[6]; w[11] = a[7];
                w[12] = cp0[0]; w[13] = cp0[1]; w[14] = cp0[2];
                w[15] = (float)seg;                           /* trailPosition */
                w[16] = cp1[0]; w[17] = cp1[1]; w[18] = cp1[2];
                w[19] = b[3];                                 /* tamano fin */
                w[20] = b[4]; w[21] = b[5]; w[22] = b[6]; w[23] = b[7];
                w[24] = esq[k][0];
                w[25] = esq[k][1];
                w += WE_PSYS_FLOATS_CINTA;
                n++;
            }
        }
    }
    s->n_verts = n;
    return n;
}

static int construye(WeParticleSystem *s)
{
    if (s->cinta)
        return construye_cinta(s);

    float *w = s->verts;
    int n = 0;
    /* Las cuatro esquinas del sprite. La UV va directa al muestreo y ademas
     * define el quad en el vertice: `-up*(v-0.5)` pone v=0 arriba, que es la
     * fila 0 de la textura sin voltear --- por eso las texturas de particula se
     * suben sin el volteo comun. */
    static const float esq[6][2] = {
        {0, 0}, {1, 0}, {0, 1},
        {0, 1}, {1, 0}, {1, 1},
    };

    for (int i = 0; i < s->maxcount; i++) {
        Particula *q = &s->p[i];
        if (!q->viva)
            continue;
        float vn = sujeta(q->edad / q->vida, 0.0f, 0.999999f);

        Modulado m;
        modula(s, q, &m);
        const float tam = m.tam, alfa = m.alfa;
        const float *col = m.col, *desp = m.desp;
        if (tam <= 0.0f || alfa <= 0.001f)
            continue;

        for (int k = 0; k < 6; k++) {
            w[0] = q->pos[0] + desp[0];
            w[1] = q->pos[1] + desp[1];
            w[2] = q->pos[2] + desp[2];
            w[3] = esq[k][0];
            w[4] = esq[k][1];
            w[5] = q->rot[2];
            w[6] = tam;
            w[7] = q->rot[0];
            w[8] = q->rot[1];
            w[9] = col[0]; w[10] = col[1]; w[11] = col[2]; w[12] = alfa;
            w[13] = q->vel[0]; w[14] = q->vel[1]; w[15] = q->vel[2];
            /* El shader saca el fotograma de la hoja de este valor, con un
             * `frac` por delante. En modo `randomframe` cada particula se queda
             * en uno fijo --- lluvia, escombros, petalos: 89 sistemas cuyo
             * sprite no debe animarse, solo variar entre particulas. */
            w[16] = s->anim_modo == 1 ? azar_fijo(q->semilla, 99)
                                      : vn * s->anim_mult;
            w += WE_PSYS_FLOATS_POR_VERTICE;
            n++;
        }
    }
    s->n_verts = n;
    return n;
}

int we_psys_update(WeParticleSystem *s, float t)
{
    if (!s)
        return 0;

    float dt;
    if (!s->arrancado) {
        /* Primera llamada: hay que recuperar `starttime` --- los segundos que
         * WE da por ya transcurridos --- mas el instante pedido. Sin esto un
         * render a t=0 sale vacio y uno a t=25 mostraria un sistema recien
         * arrancado en vez de en regimen. */
        s->arrancado = 1;
        dt = s->starttime + (t > 0.0f ? t : 0.0f);
    } else {
        dt = t - s->t_prev;
        if (dt < 0.0f)                     /* el reloj retrocedio */
            dt = s->starttime;
    }
    s->t_prev = t;
    if (dt > MAX_SEG_POR_LLAMADA)
        dt = MAX_SEG_POR_LLAMADA;

    /* Las particulas instantaneas son un unico estallido al arrancar. */
    if (s->instantaneo > 0.0f && s->vivido == 0.0f) {
        int n = (int)s->instantaneo;
        if (n > s->maxcount) n = s->maxcount;
        for (int i = 0; i < n; i++)
            emite(s, &s->p[i]);
    }

    /* Paso fijo: el resultado no puede depender de a cuantos fotogramas por
     * segundo vaya el escritorio, ni diferir entre el ejecutor offline y el
     * de plasmashell. */
    while (dt > 0.0f) {
        float h = dt > PASO ? PASO : dt;
        paso(s, h);
        dt -= h;
    }
    return construye(s);
}

const float *we_psys_vertices(const WeParticleSystem *s)
{
    return s ? s->verts : NULL;
}

int we_psys_cinta(const WeParticleSystem *s)
{
    return s ? s->cinta : 0;
}

int we_psys_floats_por_vertice(const WeParticleSystem *s)
{
    return s && s->cinta ? WE_PSYS_FLOATS_CINTA : WE_PSYS_FLOATS_POR_VERTICE;
}
