/* Decodificador de video compartido. Ver `wevideo.h` para el contrato y para
 * por que hay dos modos.
 *
 * Se apoya en libavformat/libavcodec/libswscale. La alternativa era una
 * tuberia de `ffmpeg`, y no sale: el corpus tiene cuatro videos a 3840x2160 y
 * cuatro a 60 fps, y eso en RGBA por una tuberia son 2 GB/s. Ademas un fondo
 * necesita bucle y pausa, y por tuberia eso solo se hace matando el proceso.
 */

#include "wevideo.h"

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>

#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Cuanto puede alejarse el fotograma que tenemos del instante pedido antes de
 * rebobinar en vez de seguir decodificando. Medio segundo son 15 fotogramas a
 * 30 fps: decodificarlos cuesta menos que un seek, que tira el GOP entero. */
#define SALTO_MAX 0.5

/* El anillo se dimensiona por MEMORIA, no por numero de fotogramas: a 4K un
 * RGBA son 33 MB y cuatro huecos serian 132 MB de RAM por capa de video. Con
 * este tope un 1080p tiene 4 huecos y un 2160p dos, que es justo lo que hace
 * falta para que el hilo no se quede sin trabajo. */
#define ANILLO_BYTES (64u * 1024u * 1024u)
#define ANILLO_MIN 2
#define ANILLO_MAX 4

typedef struct {
    uint8_t *px;
    double pts;      /* segundos dentro del fichero */
} Hueco;

struct WeVideo {
    AVFormatContext *fmt;
    AVCodecContext *dec;
    struct SwsContext *sws;
    AVFrame *frame;
    AVPacket *pkt;
    int flujo;                  /* indice del stream de video */
    int w, h;                   /* tamano de SALIDA, ya escalado */
    double dur;
    double base;                /* time_base del stream, en segundos */
    /* Instante del primer fotograma DENTRO del fichero. No siempre es cero:
     * "Mass Effect Andromeda [No Arrow].mp4" arranca en 0,0333 y hay mas asi.
     * Todos los pts que salen de aqui se dan ya restado, o sea en una linea de
     * tiempo que empieza en 0, y por dos razones: `t = 0` tiene que dar el
     * PRIMER fotograma, y el bucle tiene que cerrar exactamente sobre la
     * duracion. Sin restarlo, cada vuelta se desplazaba lo que valga el
     * arranque. */
    double inicio;

    Hueco *anillo;
    int n_huecos;
    /* Indices que NO se envuelven: `esc - lec` es cuantos hay pendientes, y
     * asi no hace falta un flag de lleno/vacio por hueco. */
    unsigned long esc, lec;
    int entregado;              /* -1 si aun no se entrego ninguno */
    double pts_entregado;       /* para saber si hay que volver a subirlo */

    int modo;
    pthread_t hilo;
    pthread_mutex_t mtx;
    pthread_cond_t hay_hueco, hay_dato;
    int hilo_vivo, parar, fin;
    /* Rebobinado en tres estados, no en un flag: SIN -> PEDIDO (lo pone el
     * consumidor) -> EN_CURSO (lo pone el productor al saltar) -> SIN (cuando
     * publica un fotograma que ya alcanza el objetivo). Con solo dos estados
     * el consumidor volvia a pedir mientras el productor aun saltaba. */
    enum { SEEK_SIN = 0, SEEK_PEDIDO, SEEK_EN_CURSO } estado_seek;
    double seek_a;
    double saltar_hasta;        /* solo lo toca el productor; < 0: nada */

    char err[256];
};

static char err_abrir[256];

const char *wevideo_error(const WeVideo *v)
{
    return v ? v->err : err_abrir;
}

int wevideo_ancho(const WeVideo *v) { return v ? v->w : 0; }
int wevideo_alto(const WeVideo *v) { return v ? v->h : 0; }
double wevideo_duracion(const WeVideo *v) { return v ? v->dur : 0.0; }

/* Distancia entre dos instantes de un video en BUCLE: el final y el principio
 * son vecinos. Sin esto, al dar la vuelta el consumidor cree que se ha ido a
 * la otra punta del fichero y pide un seek en cada vuelta. */
static double dist_bucle(double a, double b, double dur)
{
    double d = fabs(a - b);
    if (dur > 0.0 && d > dur * 0.5)
        d = dur - d;
    return d;
}

/* ── decodificacion ──────────────────────────────────────────────────────── */

static void rebobinar(WeVideo *v, double a)
{
    /* `a` viene en la linea de tiempo normalizada; el fichero cuenta desde
     * `inicio`, asi que hay que devolverselo antes de buscar. */
    int64_t ts = (int64_t)((a + v->inicio) / (v->base > 0.0 ? v->base : 1.0));
    /* BACKWARD deja el cursor en el fotograma clave ANTERIOR al pedido; de ahi
     * en adelante se decodifica hasta alcanzarlo. Sin clave previa no hay
     * imagen que reconstruir. */
    if (av_seek_frame(v->fmt, v->flujo, ts, AVSEEK_FLAG_BACKWARD) >= 0)
        avcodec_flush_buffers(v->dec);
    v->fin = 0;
}

/* Convierte el AVFrame recien decodificado al hueco `dst`, en RGBA y del
 * derecho para GL. */
static void convertir(WeVideo *v, Hueco *dst)
{
    /* Las texturas de WE se guardan con el origen ARRIBA y las UV de GL van de
     * abajo a arriba; `werender.py` ya voltea las que decodifica en Python
     * (`rgba[::-1]`). Un fotograma de video llega igual de arriba a abajo, asi
     * que hay que voltearlo o el fondo sale del reves. Se hace con paso
     * NEGATIVO desde la ultima fila, que a swscale le cuesta cero: copiar el
     * buffer entero para darle la vuelta serian otros 33 MB por fotograma a
     * 4K. */
    uint8_t *plano[4] = { dst->px + (size_t)(v->h - 1) * (size_t)v->w * 4, NULL, NULL, NULL };
    int paso[4] = { -v->w * 4, 0, 0, 0 };
    sws_scale(v->sws, (const uint8_t *const *)v->frame->data, v->frame->linesize,
              0, v->dec->height, plano, paso);

    int64_t ts = v->frame->best_effort_timestamp;
    if (ts == AV_NOPTS_VALUE)
        ts = v->frame->pts;
    dst->pts = (ts == AV_NOPTS_VALUE) ? 0.0
                                     : (double)ts * v->base - v->inicio;
    if (dst->pts < 0.0)
        dst->pts = 0.0;
}

/* Decodifica el siguiente fotograma del fichero al hueco `dst`.
 * Devuelve 1 si lo consiguio, 0 si el fichero se acabo (y ya ha rebobinado al
 * principio, que es como se hace el bucle) y -1 si el fichero esta roto. */
static int siguiente(WeVideo *v, Hueco *dst)
{
    for (;;) {
        int r = avcodec_receive_frame(v->dec, v->frame);
        if (r == 0) {
            convertir(v, dst);
            return 1;
        }
        if (r != AVERROR(EAGAIN) && r != AVERROR_EOF) {
            snprintf(v->err, sizeof v->err, "avcodec_receive_frame: %d", r);
            return -1;
        }
        if (r == AVERROR_EOF || v->fin) {
            /* Fin de fichero: el bucle es rebobinar y seguir. Quien llama
             * vuelve a entrar y sale ya con el primer fotograma. */
            rebobinar(v, 0.0);
            return 0;
        }

        r = av_read_frame(v->fmt, v->pkt);
        if (r < 0) {
            /* Sin mas paquetes: se vacia el decodificador antes de rebobinar,
             * porque puede tener fotogramas reordenados dentro. */
            avcodec_send_packet(v->dec, NULL);
            v->fin = 1;
            continue;
        }
        if (v->pkt->stream_index == v->flujo)
            avcodec_send_packet(v->dec, v->pkt);
        av_packet_unref(v->pkt);
    }
}

/* ── hilo productor (solo en WEVIDEO_HILO) ───────────────────────────────── */

static void *productor(void *arg)
{
    WeVideo *v = (WeVideo *)arg;
    for (;;) {
        pthread_mutex_lock(&v->mtx);
        /* Aqui es donde la pausa del escritorio para tambien el decodificador:
         * si el reloj no avanza, el consumidor no consume, el anillo se queda
         * lleno y este hilo duerme. */
        while (!v->parar && v->estado_seek != SEEK_PEDIDO &&
               v->esc - v->lec >= (unsigned long)v->n_huecos)
            pthread_cond_wait(&v->hay_hueco, &v->mtx);
        if (v->parar) {
            pthread_mutex_unlock(&v->mtx);
            return NULL;
        }
        if (v->estado_seek == SEEK_PEDIDO) {
            double a = v->seek_a;
            v->estado_seek = SEEK_EN_CURSO;
            /* Se tiran los pendientes pero se conserva el que el consumidor
             * tiene en la mano: su puntero sigue vivo hasta que vuelva a
             * pedir. */
            v->esc = (v->esc > v->lec) ? v->lec + 1 : v->lec;
            pthread_mutex_unlock(&v->mtx);
            rebobinar(v, a);
            /* Un seek cae en el fotograma CLAVE anterior al pedido, y con un
             * GOP largo eso puede quedar segundos atras. Publicar desde ahi
             * hacia que el consumidor lo viera demasiado lejos y volviera a
             * pedir seek --- y otra vez, y otra: el video se quedaba clavado
             * en un fotograma. Se decodifica en vacio hasta pisar el instante
             * pedido, y solo entonces se publica. */
            v->saltar_hasta = a;
            continue;
        }
        Hueco *dst = &v->anillo[v->esc % (unsigned long)v->n_huecos];
        pthread_mutex_unlock(&v->mtx);

        /* Fuera del cerrojo: el hueco `esc` no lo mira nadie hasta que se
         * anuncia, y decodificar un 2160p son decenas de ms. */
        int r = siguiente(v, dst);
        if (r < 0)
            return NULL;
        if (r == 0) {
            /* Se acabo el fichero y ya rebobino al principio: el objetivo del
             * salto queda detras, asi que dejar de saltar. */
            v->saltar_hasta = -1.0;
            continue;
        }
        if (v->saltar_hasta >= 0.0) {
            if (dst->pts < v->saltar_hasta - 1e-6)
                continue;       /* aun por detras del objetivo: no se publica */
            v->saltar_hasta = -1.0;
        }

        pthread_mutex_lock(&v->mtx);
        v->esc++;
        if (v->estado_seek == SEEK_EN_CURSO)
            v->estado_seek = SEEK_SIN;
        pthread_cond_signal(&v->hay_dato);
        pthread_mutex_unlock(&v->mtx);
    }
}

/* ── apertura ────────────────────────────────────────────────────────────── */

WeVideo *wevideo_open(const char *ruta, int ancho, int alto, int modo)
{
    err_abrir[0] = 0;
    /* libav escribe en stderr por su cuenta y el stderr de `glexec` se lee
     * como registro del render: sus avisos de MP4 pasarian por fallos del
     * motor. */
    av_log_set_level(AV_LOG_QUIET);

    WeVideo *v = calloc(1, sizeof *v);
    if (!v) {
        snprintf(err_abrir, sizeof err_abrir, "sin memoria");
        return NULL;
    }
    v->flujo = -1;
    v->entregado = -1;
    v->seek_a = -1.0;
    v->saltar_hasta = -1.0;
    v->modo = modo;

    if (avformat_open_input(&v->fmt, ruta, NULL, NULL) < 0) {
        snprintf(err_abrir, sizeof err_abrir, "no se puede abrir: %s", ruta);
        goto mal;
    }
    if (avformat_find_stream_info(v->fmt, NULL) < 0) {
        snprintf(err_abrir, sizeof err_abrir, "sin informacion de flujos: %s", ruta);
        goto mal;
    }

    const AVCodec *codec = NULL;
    v->flujo = av_find_best_stream(v->fmt, AVMEDIA_TYPE_VIDEO, -1, -1, &codec, 0);
    if (v->flujo < 0 || !codec) {
        snprintf(err_abrir, sizeof err_abrir, "sin flujo de video: %s", ruta);
        goto mal;
    }
    AVStream *st = v->fmt->streams[v->flujo];

    v->dec = avcodec_alloc_context3(codec);
    if (!v->dec || avcodec_parameters_to_context(v->dec, st->codecpar) < 0) {
        snprintf(err_abrir, sizeof err_abrir, "no se puede preparar el decodificador");
        goto mal;
    }
    /* Hilos DENTRO del decodificador. En modo exacto es lo unico que hay, y en
     * modo con hilo se suman al productor: un 2160p no lo saca un solo nucleo
     * a 60 fps. 0 = los que decida libav por la maquina. */
    v->dec->thread_count = 0;
    if (avcodec_open2(v->dec, codec, NULL) < 0) {
        snprintf(err_abrir, sizeof err_abrir, "no se puede abrir el decodificador");
        goto mal;
    }

    v->base = av_q2d(st->time_base);
    v->inicio = (st->start_time != AV_NOPTS_VALUE && st->start_time > 0)
                    ? (double)st->start_time * v->base : 0.0;
    if (st->duration > 0 && st->duration != AV_NOPTS_VALUE)
        v->dur = (double)st->duration * v->base;
    else if (v->fmt->duration > 0 && v->fmt->duration != AV_NOPTS_VALUE)
        v->dur = (double)v->fmt->duration / (double)AV_TIME_BASE;
    if (v->dur <= 0.0)
        v->dur = 1.0;

    v->w = ancho > 0 ? ancho : v->dec->width;
    v->h = alto > 0 ? alto : v->dec->height;
    if (v->w <= 0 || v->h <= 0) {
        snprintf(err_abrir, sizeof err_abrir, "tamano de video invalido");
        goto mal;
    }

    v->sws = sws_getContext(v->dec->width, v->dec->height, v->dec->pix_fmt,
                            v->w, v->h, AV_PIX_FMT_RGBA,
                            SWS_BILINEAR, NULL, NULL, NULL);
    if (!v->sws) {
        snprintf(err_abrir, sizeof err_abrir, "no se puede convertir a RGBA");
        goto mal;
    }
    {
        /* Sin esto swscale asume BT.601 para todo, y todo el corpus es HD o
         * mayor: un BT.709 leido como BT.601 vira los verdes y los tonos de
         * piel. El fichero lo dice; hacerle caso es gratis.
         *
         * El destino va SIEMPRE en rango completo (el ultimo 1): RGBA de 0 a
         * 255. El origen depende del fichero, y casi todo H.264 viene en rango
         * limitado (16-235); tomarlo por completo lava los negros. */
        int cs = SWS_CS_ITU709;
        if (v->dec->colorspace == AVCOL_SPC_BT470BG ||
            v->dec->colorspace == AVCOL_SPC_SMPTE170M)
            cs = SWS_CS_ITU601;
        else if (v->dec->colorspace == AVCOL_SPC_UNSPECIFIED)
            cs = v->dec->height >= 720 ? SWS_CS_ITU709 : SWS_CS_ITU601;
        const int rango_origen = (v->dec->color_range == AVCOL_RANGE_JPEG);
        sws_setColorspaceDetails(v->sws, sws_getCoefficients(cs), rango_origen,
                                 sws_getCoefficients(SWS_CS_DEFAULT), 1,
                                 0, 1 << 16, 1 << 16);
    }

    v->frame = av_frame_alloc();
    v->pkt = av_packet_alloc();
    if (!v->frame || !v->pkt) {
        snprintf(err_abrir, sizeof err_abrir, "sin memoria");
        goto mal;
    }

    size_t bytes = (size_t)v->w * (size_t)v->h * 4u;
    v->n_huecos = 1;
    if (modo == WEVIDEO_HILO) {
        v->n_huecos = (int)(ANILLO_BYTES / (bytes ? bytes : 1));
        if (v->n_huecos < ANILLO_MIN) v->n_huecos = ANILLO_MIN;
        if (v->n_huecos > ANILLO_MAX) v->n_huecos = ANILLO_MAX;
    }
    v->anillo = calloc((size_t)v->n_huecos, sizeof *v->anillo);
    if (!v->anillo)
        goto sin_memoria;
    for (int i = 0; i < v->n_huecos; i++) {
        /* av_malloc alinea para SIMD: swscale escribe la fila con anchura de
         * registro y un buffer sin alinear le cuesta el camino lento. */
        v->anillo[i].px = av_malloc(bytes);
        if (!v->anillo[i].px)
            goto sin_memoria;
        memset(v->anillo[i].px, 0, bytes);
        v->anillo[i].pts = -1.0;
    }

    if (modo == WEVIDEO_HILO) {
        pthread_mutex_init(&v->mtx, NULL);
        pthread_cond_init(&v->hay_hueco, NULL);
        pthread_cond_init(&v->hay_dato, NULL);
        if (pthread_create(&v->hilo, NULL, productor, v) == 0) {
            v->hilo_vivo = 1;
        } else {
            /* Sin hilo se sigue: en modo exacto el vivo daria tirones, pero un
             * fondo con tirones es mejor que un fondo negro. */
            pthread_cond_destroy(&v->hay_dato);
            pthread_cond_destroy(&v->hay_hueco);
            pthread_mutex_destroy(&v->mtx);
            v->modo = WEVIDEO_EXACTO;
        }
    }
    return v;

sin_memoria:
    snprintf(err_abrir, sizeof err_abrir, "sin memoria para el anillo");
mal:
    wevideo_close(v);
    return NULL;
}

void wevideo_close(WeVideo *v)
{
    if (!v)
        return;
    if (v->hilo_vivo) {
        pthread_mutex_lock(&v->mtx);
        v->parar = 1;
        pthread_cond_broadcast(&v->hay_hueco);
        pthread_mutex_unlock(&v->mtx);
        pthread_join(v->hilo, NULL);
        pthread_cond_destroy(&v->hay_dato);
        pthread_cond_destroy(&v->hay_hueco);
        pthread_mutex_destroy(&v->mtx);
    }
    if (v->anillo) {
        for (int i = 0; i < v->n_huecos; i++)
            av_free(v->anillo[i].px);
        free(v->anillo);
    }
    if (v->sws) sws_freeContext(v->sws);
    if (v->frame) av_frame_free(&v->frame);
    if (v->pkt) av_packet_free(&v->pkt);
    if (v->dec) avcodec_free_context(&v->dec);
    if (v->fmt) avformat_close_input(&v->fmt);
    free(v);
}

/* ── entrega ─────────────────────────────────────────────────────────────── */

static int frame_exacto(WeVideo *v, double objetivo, const uint8_t **rgba)
{
    Hueco *h = &v->anillo[0];
    /* Rebobinar solo si el objetivo quedo ATRAS o demasiado adelante: hacia
     * adelante y cerca sale mas barato decodificar que tirar el GOP. */
    if (h->pts < 0.0 || objetivo < h->pts - 1e-6 || objetivo > h->pts + SALTO_MAX) {
        rebobinar(v, objetivo);
        h->pts = -1.0;
    }
    /* Decodifica hasta pisar el objetivo. `vueltas` es una red contra un
     * fichero cuyos pts no avanzan: sin ella esto es un bucle infinito. */
    for (int vueltas = 0; vueltas < 100000; vueltas++) {
        if (h->pts >= objetivo - 1e-6)
            break;
        int r = siguiente(v, h);
        if (r < 0)
            break;
        if (r == 0) {            /* el fichero se acabo antes del objetivo */
            if (h->pts >= 0.0)
                break;
            continue;
        }
    }
    if (h->pts < 0.0)
        return -1;
    *rgba = h->px;
    /* `werender.py` repite el mismo instante N veces para que converjan los
     * efectos temporales: a partir de la segunda el fotograma es el mismo y no
     * hay que volver a subirlo. */
    int cambio = (v->entregado < 0) || fabs(h->pts - v->pts_entregado) > 1e-9;
    v->entregado = 0;
    v->pts_entregado = h->pts;
    return cambio;
}

static int frame_hilo(WeVideo *v, double objetivo, const uint8_t **rgba)
{
    pthread_mutex_lock(&v->mtx);

    /* Avanza mientras el SIGUIENTE este mas cerca del objetivo que el actual.
     * Con distancia en bucle esto tambien cruza bien el final del fichero. */
    while (v->esc > v->lec + 1) {
        double d0 = dist_bucle(v->anillo[v->lec % (unsigned long)v->n_huecos].pts,
                               objetivo, v->dur);
        double d1 = dist_bucle(v->anillo[(v->lec + 1) % (unsigned long)v->n_huecos].pts,
                               objetivo, v->dur);
        if (d1 >= d0)
            break;
        v->lec++;
    }

    if (v->esc <= v->lec) {
        /* Aun no hay nada: arranque, o el decodificador va por detras. Se
         * devuelve el ultimo entregado si lo hubo; el ejecutor entonces no
         * vuelve a subir nada. */
        pthread_cond_signal(&v->hay_hueco);
        int e = v->entregado;
        pthread_mutex_unlock(&v->mtx);
        if (e < 0)
            return -1;
        *rgba = v->anillo[e].px;
        return 0;
    }

    int i = (int)(v->lec % (unsigned long)v->n_huecos);
    /* Si ni con lo que hay se llega, se pide rebobinar: pasa cuando el reloj
     * salta --- el escritorio despausa tras minutos tapado --- y decodificar
     * el hueco entero costaria mas que un seek. Solo si no hay ya uno en
     * marcha: pedirlo otra vez mientras el productor salta lo reinicia y no
     * llega a publicar nunca. */
    if (v->estado_seek == SEEK_SIN &&
        dist_bucle(v->anillo[i].pts, objetivo, v->dur) > SALTO_MAX) {
        v->seek_a = objetivo;
        v->estado_seek = SEEK_PEDIDO;
    }

    int cambio = (i != v->entregado) || fabs(v->anillo[i].pts - v->pts_entregado) > 1e-9;
    v->entregado = i;
    v->pts_entregado = v->anillo[i].pts;
    pthread_cond_signal(&v->hay_hueco);
    pthread_mutex_unlock(&v->mtx);

    *rgba = v->anillo[i].px;
    return cambio;
}

int wevideo_frame(WeVideo *v, double t, const uint8_t **rgba)
{
    if (!v || !rgba)
        return -1;
    /* El bucle del video sale de aqui y de ningun sitio mas: el reloj del
     * motor no se reinicia nunca, asi que el resto del codigo puede tratar el
     * fichero como si no acabara. */
    double objetivo = fmod(t, v->dur);
    if (objetivo < 0.0)
        objetivo += v->dur;

    return v->hilo_vivo ? frame_hilo(v, objetivo, rgba)
                        : frame_exacto(v, objetivo, rgba);
}
