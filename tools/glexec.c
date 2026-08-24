/* Ejecutor de planes de render: corre una escena de WE headless y vuelca RGBA.
 *
 * Toda la inteligencia (parsear scene.json, traducir shaders, decodificar
 * texturas) vive en Python. Esto solo ejecuta un plan ya resuelto, en un
 * contexto EGL surfaceless con OpenGL 3.3 core -- el mismo dialecto al que
 * apunta el traductor.
 *
 *   make glexec        (o: cc -O2 -Isrc -o glexec tools/glexec.c
 *                            src/weparticles.c -lEGL -lGL -lm)
 *   ./glexec plan.txt
 *
 * Formato del plan (una directiva por linea, sin anidamiento):
 *
 *   canvas <w> <h>
 *   tex <id> <ruta.rgba> <w> <h>       textura RGBA8 cruda ya decodificada
 *   mesh <id> <ruta.bin> <nvert> <nidx> [<nhuesos> <nclaves> <duracion>]
 *   psys <id> <ruta.psys>              sistema de particulas a simular
 *   object <copiafondo> <16 floats> <composicion> <solo_buffer>
 *   pass                               abre un pase
 *     prog <vert> <frag>
 *     target <nombre|SCREEN>           SCREEN = buffer acumulado del objeto
 *     mesh <id>                        dibuja una malla en vez del quad
 *     psys <id>                        dibuja un sistema de particulas
 *     sampler <uniform> tex:<id>|rt:<nombre>|prev
 *     u1f/u2f/u3f/u4f <uniform> <floats>
 *     umat3 <uniform> <9 floats>   umat4 <uniform> <16 floats>
 *     blend <normal|translucent|additive|none|premul_additive|premul_alpha>
 *   endpass
 *   copy <origen> <destino>
 *   frame                              cierra el fotograma y limpia la escena
 *   output <ruta.rgba>
 *
 * Los render targets se crean bajo demanda; la resolucion sale del nombre,
 * que es como WE los organiza (Half -> /2, Quarter -> /4).
 */

#define GL_GLEXT_PROTOTYPES
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/gl.h>
#include <GL/glext.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

#include "weparticles.h"

#define MAX_TEX 64
#define MAX_RT 64
#define MAX_SAMPLERS 8
#define MAX_UNIFORMS 64

static int canvas_w = 1920, canvas_h = 1080;

typedef struct {
    char name[128];
    GLuint tex, fbo;
    int w, h;
} Target;

static Target rts[MAX_RT];
static int n_rts;
static GLuint textures[MAX_TEX];

/* Buffer acumulado del objeto, con ping-pong: no se puede leer y escribir
 * la misma textura en un pase. */
static Target compo[2];
static int compo_cur;

/* Buffer donde se acumulan todos los objetos. Sin el, cada objeto pisaba al
 * anterior en el par ping-pong y solo sobrevivia la ultima capa. */
static Target scene_rt;
static GLuint composite_prog;
static int object_open;
/* Colocacion del objeto en curso: los pases corren en el espacio de la capa
 * (su buffer representa el rectangulo de la capa) y esta matriz lo lleva al
 * lienzo una unica vez, al componer. Identidad para planes sin ella. */
static float obj_mvp[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
/* Como se compone el objeto sobre la escena:
 *   0  normal        el buffer trae alfa recta y se multiplica al componer
 *   1  aditivo       colorBlendMode 31: suma en vez de tapar
 *   2  premul sobre  el buffer ya viene premultiplicado (particulas)
 *   3  premul suma   idem, y ademas se suma
 * Los dos ultimos existen porque un buffer de particulas ya lleva el color
 * multiplicado por su alfa: volver a multiplicarlo lo apagaria. */
static int obj_aditivo;
/* colorBlendMode aparte: la capa no se compone, solo deja su buffer. */
static int obj_solo_buffer;

static GLuint quad_vao, quad_vbo;

/* Mallas puppet. El fichero trae los vertices intercalados (vec3 posicion +
 * vec2 UV, el mismo layout que el quad) y detras los indices u16. */
#define MAX_MESHES 64
static struct {
    GLuint vao, vbo, ibo;
    int index_count;
    /* Animacion por huesos; nbones == 0 si la malla va en pose de reposo. */
    int nvert, nbones, nkeys;
    float duration;
    float *bind;              /* (nvert, 5) reposo + UV */
    unsigned short *bone_idx; /* (nvert, 4) */
    float *weights;           /* (nvert, 4) */
    float *mats;              /* (nkeys, nbones, 12) ya compuestas */
    float *skinned;           /* destino, se reusa */
} meshes[MAX_MESHES];
static int n_meshes;
/* Instante al que deformar las mallas. Lo fija la directiva `meshtime`; sin
 * ella las mallas se quedan en reposo, que es el comportamiento anterior. */
static float mesh_time = -1.0f;
static int meshes_skinned;

/* Deforma una malla en el instante `t` y reescribe su VBO.
 *
 * Las matrices llegan del plan ya resueltas -- inversa de reposo, compuesta
 * con la del padre y evaluada en cada clave -- asi que aqui solo queda la
 * suma ponderada: v' = suma_j w_j * (v * M_j). Son 12 floats por hueso, por
 * filas; la columna que falta es siempre (0,0,0,1).
 *
 * Se toma la clave mas cercana, sin interpolar. */
static void skin_mesh(int id, float t)
{
    if (id < 0 || id >= MAX_MESHES) return;
    if (meshes[id].nbones <= 0 || meshes[id].nkeys <= 1) return;

    /* La ultima clave repite la primera para cerrar el bucle: el periodo son
     * nkeys-1 intervalos, no nkeys. Entre clave y clave se interpola: a 13
     * claves por segundo, saltar a la mas cercana se ve escalonado. */
    int span = meshes[id].nkeys - 1;
    float dur = meshes[id].duration > 1e-6f ? meshes[id].duration : 1e-6f;
    double fase = fmod((double)t / dur, 1.0);
    if (fase < 0.0) fase += 1.0;
    double fk = fase * span;
    int k0 = (int)fk;
    if (k0 >= span) k0 = span - 1;
    float fr = (float)(fk - k0);

    int nb = meshes[id].nbones;
    const float *m0 = meshes[id].mats + (size_t)k0 * nb * 12;
    const float *m1 = m0 + (size_t)nb * 12;        /* k0+1 <= nkeys-1 */
    float *mats = malloc((size_t)nb * 12 * sizeof(float));
    if (!mats) return;
    for (size_t i = 0; i < (size_t)nb * 12; i++)
        mats[i] = m0[i] + (m1[i] - m0[i]) * fr;
    for (int v = 0; v < meshes[id].nvert; v++) {
        const float *p = meshes[id].bind + (size_t)v * 5;
        float acc[3] = {0.0f, 0.0f, 0.0f};
        for (int s = 0; s < 4; s++) {
            float w = meshes[id].weights[(size_t)v * 4 + s];
            if (w == 0.0f) continue;
            int j = meshes[id].bone_idx[(size_t)v * 4 + s];
            if (j < 0 || j >= nb) continue;
            const float *o = mats + (size_t)j * 12;
            for (int c = 0; c < 3; c++)
                acc[c] += w * (p[0] * o[0 * 3 + c] + p[1] * o[1 * 3 + c]
                               + p[2] * o[2 * 3 + c] + o[3 * 3 + c]);
        }
        float *d = meshes[id].skinned + (size_t)v * 5;
        d[0] = acc[0]; d[1] = acc[1]; d[2] = acc[2];
    }
    free(mats);

    glBindBuffer(GL_ARRAY_BUFFER, meshes[id].vbo);
    glBufferSubData(GL_ARRAY_BUFFER, 0,
                    (GLsizeiptr)meshes[id].nvert * 5 * sizeof(float),
                    meshes[id].skinned);
}

static void skin_all(void)
{
    if (meshes_skinned || mesh_time < 0.0f) return;
    meshes_skinned = 1;
    for (int i = 0; i < n_meshes; i++)
        skin_mesh(i, mesh_time);
}

static void load_mesh(int id, const char *path, int nvert, int nidx,
                      int nbones, int nkeys, float duration)
{
    if (id < 0 || id >= MAX_MESHES) return;
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "malla no abre: %s\n", path); return; }
    size_t vbytes = (size_t)nvert * 5 * sizeof(float);
    size_t ibytes = (size_t)nidx * sizeof(unsigned short);
    size_t abytes = 0;
    if (nbones > 0 && nkeys > 1)
        abytes = (size_t)nvert * 4 * sizeof(unsigned short)
               + (size_t)nvert * 4 * sizeof(float)
               + (size_t)nkeys * nbones * 12 * sizeof(float);
    char *buf = malloc(vbytes + ibytes + abytes);
    if (!buf) { fclose(f); return; }
    if (fread(buf, 1, vbytes + ibytes + abytes, f) != vbytes + ibytes + abytes) {
        fprintf(stderr, "malla corta: %s\n", path);
        free(buf); fclose(f); return;
    }
    fclose(f);

    glGenVertexArrays(1, &meshes[id].vao);
    glBindVertexArray(meshes[id].vao);
    glGenBuffers(1, &meshes[id].vbo);
    glBindBuffer(GL_ARRAY_BUFFER, meshes[id].vbo);
    glBufferData(GL_ARRAY_BUFFER, vbytes, buf,
                 abytes ? GL_DYNAMIC_DRAW : GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 5 * sizeof(float), (void *)0);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 5 * sizeof(float),
                          (void *)(3 * sizeof(float)));
    glEnableVertexAttribArray(1);
    glGenBuffers(1, &meshes[id].ibo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, meshes[id].ibo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, ibytes, (char *)buf + vbytes, GL_STATIC_DRAW);
    meshes[id].index_count = nidx;
    meshes[id].nvert = nvert;

    if (abytes) {
        const char *src = buf + vbytes + ibytes;
        size_t ib = (size_t)nvert * 4 * sizeof(unsigned short);
        size_t wb = (size_t)nvert * 4 * sizeof(float);
        size_t kb = (size_t)nkeys * nbones * 12 * sizeof(float);
        meshes[id].bind     = malloc(vbytes);
        meshes[id].skinned  = malloc(vbytes);
        meshes[id].bone_idx = malloc(ib);
        meshes[id].weights  = malloc(wb);
        meshes[id].mats     = malloc(kb);
        if (meshes[id].bind && meshes[id].skinned && meshes[id].bone_idx
            && meshes[id].weights && meshes[id].mats) {
            memcpy(meshes[id].bind, buf, vbytes);
            memcpy(meshes[id].skinned, buf, vbytes);   /* copia las UV */
            memcpy(meshes[id].bone_idx, src, ib);      src += ib;
            memcpy(meshes[id].weights, src, wb);       src += wb;
            memcpy(meshes[id].mats, src, kb);
            meshes[id].nbones = nbones;
            meshes[id].nkeys = nkeys;
            meshes[id].duration = duration;
        } else {
            fprintf(stderr, "sin memoria para la animacion de %s\n", path);
        }
    }

    free(buf);
    glBindVertexArray(quad_vao);
    if (id >= n_meshes) n_meshes = id + 1;
}

/* Sistemas de particulas. La simulacion vive en src/weparticles.c, compartida
 * con el motor en vivo; aqui solo esta lo que toca GL: un VBO dinamico por
 * sistema que se reescribe cada fotograma con los vertices que devuelve. */
/* Una escena del corpus declara 96 sistemas de particulas y otra 46. Con el
 * limite en 32 los que sobraban se cargaban a medias --- sin aviso, porque
 * `load_psys` simplemente volvia --- y sus pases dibujaban el vacio. */
#define MAX_PSYS 128
static struct {
    WeParticleSystem *sys;
    GLuint vao, vbo;
    int capacidad;              /* vertices que caben en el VBO */
} psys[MAX_PSYS];

static void load_psys(int id, const char *path)
{
    if (id < 0 || id >= MAX_PSYS)
        return;
    int desconocidas = 0;
    psys[id].sys = we_psys_load(path, &desconocidas);
    if (!psys[id].sys) {
        fprintf(stderr, "sistema de particulas no abre: %s\n", path);
        return;
    }
    if (desconocidas)
        fprintf(stderr, "%s: %d piezas sin soporte\n", path, desconocidas);

    glGenVertexArrays(1, &psys[id].vao);
    glBindVertexArray(psys[id].vao);
    glGenBuffers(1, &psys[id].vbo);
    glBindBuffer(GL_ARRAY_BUFFER, psys[id].vbo);
    /* Dos layouts, uno por shader; ver weparticles.h. El sistema dice cual. */
    const GLsizei paso = we_psys_floats_por_vertice(psys[id].sys) * sizeof(float);
    typedef struct { int loc, n, off; } Attr;
    static const Attr sprite[] = {
        {0, 3, 0}, {2, 4, 3}, {3, 2, 7}, {4, 4, 9}, {5, 4, 13},
    };
    static const Attr cinta[] = {
        {0, 4, 0}, {2, 4, 4}, {4, 4, 8}, {5, 4, 12}, {6, 4, 16}, {7, 4, 20},
        {8, 2, 24},
    };
    const Attr *attr = we_psys_cinta(psys[id].sys) ? cinta : sprite;
    unsigned n_attr = we_psys_cinta(psys[id].sys)
                    ? sizeof cinta / sizeof *cinta
                    : sizeof sprite / sizeof *sprite;
    for (unsigned i = 0; i < n_attr; i++) {
        glVertexAttribPointer(attr[i].loc, attr[i].n, GL_FLOAT, GL_FALSE, paso,
                              (void *)(size_t)(attr[i].off * sizeof(float)));
        glEnableVertexAttribArray(attr[i].loc);
    }
    glBindVertexArray(quad_vao);
}

/* Simula hasta `t`, sube los vertices y dibuja. Devuelve 0 si no hay nada. */
static int draw_psys(int id, float t)
{
    if (id < 0 || id >= MAX_PSYS || !psys[id].sys)
        return 0;
    int nv = we_psys_update(psys[id].sys, t);
    if (nv <= 0)
        return 0;
    glBindVertexArray(psys[id].vao);
    glBindBuffer(GL_ARRAY_BUFFER, psys[id].vbo);
    size_t bytes = (size_t)nv * we_psys_floats_por_vertice(psys[id].sys)
                 * sizeof(float);
    /* El numero de particulas vivas sube y baja; se reserva por el maximo visto
     * y despues solo se reescribe, sin volver a pedir memoria a GL. */
    if (nv > psys[id].capacidad) {
        glBufferData(GL_ARRAY_BUFFER, bytes, we_psys_vertices(psys[id].sys),
                     GL_DYNAMIC_DRAW);
        psys[id].capacidad = nv;
    } else {
        glBufferSubData(GL_ARRAY_BUFFER, 0, bytes, we_psys_vertices(psys[id].sys));
    }
    glDrawArrays(GL_TRIANGLES, 0, nv);
    glBindVertexArray(quad_vao);
    return 1;
}

/* Cache de programas: renderizar una secuencia repite el mismo plan una vez
 * por fotograma, y recompilar 24 programas por fotograma domina el tiempo
 * total. La clave es el par de rutas, que ya identifica la variante. */
#define MAX_PROGS 256
static struct { char key[1024]; GLuint prog; } prog_cache[MAX_PROGS];
static int n_progs;

static GLuint cached_program(const char *vp, const char *fp);

static char *slurp(const char *path, long *len)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    *len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *b = malloc(*len + 1);
    if (fread(b, 1, *len, f) != (size_t)*len) {
        fclose(f);
        free(b);
        return NULL;
    }
    b[*len] = 0;
    fclose(f);
    return b;
}

static Target make_target(const char *name, int w, int h)
{
    Target t;
    snprintf(t.name, sizeof t.name, "%s", name);
    t.w = w;
    t.h = h;
    glGenTextures(1, &t.tex);
    glBindTexture(GL_TEXTURE_2D, t.tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, &t.fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, t.fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t.tex, 0);
    glClearColor(0, 0, 0, 0);
    glClear(GL_COLOR_BUFFER_BIT);
    return t;
}

/* WE codifica la resolucion del buffer en su nombre. */
static Target *find_rt(const char *name)
{
    /* Targets incorporados: no son buffers propios sino nombres con los que
     * un efecto pide leer lo que ya hay dibujado detras. Crearlos como buffer
     * vacio los dejaba en negro. */
    if (strcmp(name, "_rt_FullFrameBuffer") == 0
        || strcmp(name, "_rt_MipMappedFrameBuffer") == 0)
        return &scene_rt;

    for (int i = 0; i < n_rts; i++)
        if (strcmp(rts[i].name, name) == 0)
            return &rts[i];
    int div = 1;
    if (strstr(name, "Half"))
        div = 2;
    else if (strstr(name, "Quarter"))
        div = 4;
    else if (strstr(name, "Eighth"))
        div = 8;
    rts[n_rts] = make_target(name, canvas_w / div, canvas_h / div);
    return &rts[n_rts++];
}

static GLuint compile(const char *path, GLenum stage)
{
    long len;
    char *src = slurp(path, &len);
    if (!src) {
        fprintf(stderr, "no se pudo leer %s\n", path);
        return 0;
    }
    GLuint sh = glCreateShader(stage);
    const char *p = src;
    glShaderSource(sh, 1, &p, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[4096];
        glGetShaderInfoLog(sh, sizeof log, NULL, log);
        fprintf(stderr, "== %s ==\n%s\n", path, log);
        free(src);
        return 0;
    }
    free(src);
    return sh;
}

static GLuint link_program(const char *vp, const char *fp)
{
    GLuint v = compile(vp, GL_VERTEX_SHADER);
    GLuint f = compile(fp, GL_FRAGMENT_SHADER);
    if (!v || !f)
        return 0;
    GLuint prog = glCreateProgram();
    glAttachShader(prog, v);
    glAttachShader(prog, f);
    /* Localizaciones fijas: el ejecutor siempre manda el mismo quad. Las de
     * particula conviven porque genericparticle.vert no declara `a_TexCoord`
     * y ningun otro shader declara las de particula; enlazar un nombre que el
     * shader no tiene no cuesta nada. */
    glBindAttribLocation(prog, 0, "a_Position");
    glBindAttribLocation(prog, 1, "a_TexCoord");
    glBindAttribLocation(prog, 2, "a_TexCoordVec4");
    glBindAttribLocation(prog, 3, "a_TexCoordC2");
    glBindAttribLocation(prog, 4, "a_Color");
    glBindAttribLocation(prog, 5, "a_TexCoordVec4C1");
    /* Los de la cinta (genericropeparticle.vert). Conviven con los de arriba
     * porque cada shader declara solo los suyos: a_PositionVec4 y a_Position
     * nunca estan los dos en el mismo programa. */
    glBindAttribLocation(prog, 0, "a_PositionVec4");
    glBindAttribLocation(prog, 6, "a_TexCoordVec4C2");
    glBindAttribLocation(prog, 7, "a_TexCoordVec4C3");
    glBindAttribLocation(prog, 8, "a_TexCoordC4");
    glLinkProgram(prog);
    GLint ok = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[4096];
        glGetProgramInfoLog(prog, sizeof log, NULL, log);
        fprintf(stderr, "link %s + %s:\n%s\n", vp, fp, log);
        return 0;
    }
    glDeleteShader(v);
    glDeleteShader(f);
    return prog;
}

/* Programa interno para volcar el buffer de un objeto sobre la escena. Es el
 * unico shader que no viene del wallpaper. */
static void init_composite(void)
{
    static const char *vs =
        "#version 330 core\n"
        "layout(location=0) in vec3 p; layout(location=1) in vec2 t;\n"
        "uniform mat4 mvp;\n"
        "out vec2 uv; void main(){ uv=t; gl_Position=vec4(p,1.0)*mvp; }\n";
    static const char *fs =
        "#version 330 core\n"
        "in vec2 uv; out vec4 o; uniform sampler2D src;\n"
        "void main(){ o = texture(src, uv); }\n";
    GLuint v = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(v, 1, &vs, NULL); glCompileShader(v);
    GLuint f = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(f, 1, &fs, NULL); glCompileShader(f);
    composite_prog = glCreateProgram();
    glAttachShader(composite_prog, v); glAttachShader(composite_prog, f);
    glLinkProgram(composite_prog);
    GLint ok = 0;
    glGetProgramiv(composite_prog, GL_LINK_STATUS, &ok);
    if (!ok) fprintf(stderr, "no enlaza el programa de composicion\n");
    glDeleteShader(v); glDeleteShader(f);
}

/* Vuelca el objeto en curso sobre la escena. El alfa se mezcla por separado
 * (ONE, ONE_MINUS_SRC_ALPHA): con la mezcla normal se elevaba al cuadrado y
 * las capas se iban a transparente al encadenar pases. */
static void flush_object(void)
{
    if (!object_open || !composite_prog)
        return;
    object_open = 0;
    if (obj_solo_buffer)
        return;          /* su resultado ya se copio a su buffer con nombre */
    glBindFramebuffer(GL_FRAMEBUFFER, scene_rt.fbo);
    glViewport(0, 0, scene_rt.w, scene_rt.h);
    glUseProgram(composite_prog);
    glEnable(GL_BLEND);
    if (obj_aditivo == 3)
        glBlendFunc(GL_ONE, GL_ONE);
    else if (obj_aditivo == 2)
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    else if (obj_aditivo)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    else
        glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                            GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, compo[compo_cur].tex);
    glUniform1i(glGetUniformLocation(composite_prog, "src"), 0);
    glUniformMatrix4fv(glGetUniformLocation(composite_prog, "mvp"),
                       1, GL_FALSE, obj_mvp);
    glBindVertexArray(quad_vao);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

/* Cada objeto arranca transparente y aporta solo lo suyo; la mezcla con lo de
 * detras ocurre una vez, al componerlo. Los efectos que necesitan el fondo lo
 * leen del buffer de escena por su nombre (_rt_FullFrameBuffer). */
/* Espejo de WE_TRACE_FRAMES del motor en vivo: media RGBA de cada buffer al
 * cerrar el fotograma. Solo asi se pueden comparar los dos ejecutores termino
 * a termino en vez de por la media final, que es una sola cifra y esconde en
 * cual de los buffers empieza a torcerse. */
static int n_frames = 0;

static void media_buffer(const char *nombre, Target *t)
{
    unsigned char *px = malloc((size_t)t->w * t->h * 4);
    if (!px)
        return;
    glBindFramebuffer(GL_READ_FRAMEBUFFER, t->fbo);
    glReadPixels(0, 0, t->w, t->h, GL_RGBA, GL_UNSIGNED_BYTE, px);
    double rgb = 0, a = 0;
    long n = (long)t->w * t->h;
    for (long i = 0; i < n; i++) {
        rgb += px[4 * i] + px[4 * i + 1] + px[4 * i + 2];
        a += px[4 * i + 3];
    }
    fprintf(stderr, "  %s=rgb=%.2f a=%.1f", nombre, rgb / (3.0 * n), a / n);
    free(px);
}

static void traza_buffers(int frame)
{
    if (!getenv("WE_TRACE"))
        return;
    fprintf(stderr, "f=%d", frame);
    media_buffer("compo", &compo[compo_cur]);
    media_buffer("escena", &scene_rt);
    for (int i = 0; i < n_rts; i++)
        media_buffer(rts[i].name, &rts[i]);
    fprintf(stderr, "\n");
}

static int n_objetos = 0;

static void begin_object(void)
{
    flush_object();
    if (getenv("WE_TRACE")) {
        fprintf(stderr, "   obj %d:", n_objetos++);
        media_buffer("escena", &scene_rt);
        fprintf(stderr, "\n");
    }
    object_open = 1;
    glClearColor(0, 0, 0, 0);
    for (int i = 0; i < 2; i++) {
        glBindFramebuffer(GL_FRAMEBUFFER, compo[i].fbo);
        glClear(GL_COLOR_BUFFER_BIT);
    }
}

static GLuint cached_program(const char *vp, const char *fp)
{
    char key[1024];
    snprintf(key, sizeof key, "%s|%s", vp, fp);
    for (int i = 0; i < n_progs; i++)
        if (strcmp(prog_cache[i].key, key) == 0)
            return prog_cache[i].prog;
    GLuint prog = link_program(vp, fp);
    if (n_progs < MAX_PROGS) {
        snprintf(prog_cache[n_progs].key, sizeof prog_cache[n_progs].key, "%s", key);
        prog_cache[n_progs].prog = prog;
        n_progs++;
    }
    return prog;
}

static void init_quad(void)
{
    /* Dos triangulos en NDC con UV 0..1. El pase base y los de efecto son
     * todos fullscreen, asi que basta un unico quad para todo. */
    const float verts[] = {
        -1, -1, 0, 0, 0,
         1, -1, 0, 1, 0,
        -1,  1, 0, 0, 1,
         1,  1, 0, 1, 1,
    };
    glGenVertexArrays(1, &quad_vao);
    glBindVertexArray(quad_vao);
    glGenBuffers(1, &quad_vbo);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof verts, verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 5 * sizeof(float), (void *)0);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 5 * sizeof(float),
                          (void *)(3 * sizeof(float)));
    glEnableVertexAttribArray(1);
}

static GLuint load_texture(const char *path, int w, int h)
{
    long len;
    char *data = slurp(path, &len);
    if (!data || len < (long)w * h * 4) {
        fprintf(stderr, "textura corta: %s (%ld < %d)\n", path, len, w * h * 4);
        free(data);
        return 0;
    }
    GLuint t;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
    glGenerateMipmap(GL_TEXTURE_2D);
    free(data);
    return t;
}

static void set_blend(const char *mode)
{
    if (strcmp(mode, "none") == 0 || strcmp(mode, "opaque") == 0) {
        glDisable(GL_BLEND);
        return;
    }
    glEnable(GL_BLEND);
    /* Los dos modos `premul_*` son los de particula. Se diferencian de los
     * normales SOLO en el canal alfa: acumulan `srcA` en vez de `srcA*srcA`,
     * que es lo que deja el buffer del objeto en premultiplicado de verdad.
     *
     * Con la mezcla corriente el alfa se eleva al cuadrado, y al componer el
     * objeto sobre la escena se vuelve a multiplicar por el: tres veces en
     * total. Un sprite de halo, cuyo borde vale alfa 7/255, salia a
     * 0.027^3 = 2e-5 y desaparecia. Solo sobrevivia el nucleo opaco, asi que
     * las luciernagas de 80 px se dibujaban como puntos de 2 px --- geometria
     * correcta, brillo aniquilado.
     *
     * No se cambian `additive` ni `translucent` porque los usa todo el resto
     * del motor; que las particulas estrenen sus propios modos deja el corpus
     * intacto salvo donde hay particulas. */
    if (strcmp(mode, "additive") == 0)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    else if (strcmp(mode, "premul_additive") == 0)
        glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE, GL_ONE, GL_ONE);
    else if (strcmp(mode, "premul_alpha") == 0)
        glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                            GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    else
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "uso: glexec plan.txt\n");
        return 2;
    }

    EGLDisplay dpy = eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA,
                                           EGL_DEFAULT_DISPLAY, NULL);
    if (!eglInitialize(dpy, NULL, NULL)) {
        fprintf(stderr, "eglInitialize fallo\n");
        return 2;
    }
    eglBindAPI(EGL_OPENGL_API);
    EGLint cfg_attr[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
                         EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT, EGL_NONE};
    EGLConfig cfg;
    EGLint n;
    eglChooseConfig(dpy, cfg_attr, &cfg, 1, &n);
    EGLint ctx_attr[] = {EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 3,
                         EGL_CONTEXT_OPENGL_PROFILE_MASK,
                         EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE};
    EGLContext ctx = eglCreateContext(dpy, cfg, EGL_NO_CONTEXT, ctx_attr);
    if (ctx == EGL_NO_CONTEXT || !eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
        fprintf(stderr, "no se pudo crear contexto GL 3.3 core\n");
        return 2;
    }

    FILE *plan = fopen(argv[1], "r");
    if (!plan) {
        fprintf(stderr, "no se pudo abrir el plan\n");
        return 2;
    }

    char line[4096];
    int in_pass = 0, drawn = 0, skipped = 0, mesh_id = -1, psys_id = -1;
    GLuint prog = 0;
    char target[128] = "SCREEN";
    char frag_actual[512] = "";   // solo para WE_TRACE_PASES
    char blend[32] = "normal";
    struct { char uni[64]; char src[128]; } samplers[MAX_SAMPLERS];
    int n_samplers = 0;
    struct { char uni[64]; int n; float v[16]; } unis[MAX_UNIFORMS];
    int n_unis = 0;
    char outpath[512] = "";

    /* El quad y los buffers necesitan el contexto ya activo. */
    init_quad();

    while (fgets(line, sizeof line, plan)) {
        char kw[32];
        if (sscanf(line, "%31s", kw) != 1)
            continue;

        if (strcmp(kw, "canvas") == 0) {
            sscanf(line, "%*s %d %d", &canvas_w, &canvas_h);
            compo[0] = make_target("_compo_a", canvas_w, canvas_h);
            compo[1] = make_target("_compo_b", canvas_w, canvas_h);
            scene_rt = make_target("_scene", canvas_w, canvas_h);
            init_composite();
            glBindFramebuffer(GL_FRAMEBUFFER, scene_rt.fbo);
            glClearColor(0, 0, 0, 0);
            glClear(GL_COLOR_BUFFER_BIT);
        } else if (strcmp(kw, "object") == 0 && !in_pass) {
            /* El flush del objeto anterior usa SU matriz: primero componer,
             * despues adoptar la del que empieza. */
            float m[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
            int copybg = 0, adit = 0, solo = 0;
            int n = sscanf(line,
                "%*s %d %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f %d %d",
                &copybg, m+0,m+1,m+2,m+3, m+4,m+5,m+6,m+7,
                m+8,m+9,m+10,m+11, m+12,m+13,m+14,m+15, &adit, &solo);
            begin_object();
            if (n >= 17)
                memcpy(obj_mvp, m, sizeof m);
            obj_aditivo = (n >= 18) ? adit : 0;
            /* Capa que solo llena su buffer de composicion: se dibuja pero no
             * se compone sobre la escena, que la muestreara otra por nombre. */
            obj_solo_buffer = (n >= 19) ? solo : 0;
        } else if (strcmp(kw, "tex") == 0) {
            int id, w, h;
            char path[512];
            sscanf(line, "%*s %d %511s %d %d", &id, path, &w, &h);
            if (id >= 0 && id < MAX_TEX) {
                textures[id] = load_texture(path, w, h);
            }
        } else if (strcmp(kw, "frame") == 0) {
            /* Abre un fotograma: cierra el objeto que quedara pendiente del
             * anterior y limpia la escena, exactamente lo que hace render()
             * en el motor en vivo.
             *
             * Sin esto, repetir el cuerpo del plan NO reproduce la ejecucion
             * real: los render targets persisten -- que es lo que hace falta
             * para que converjan los efectos temporales -- pero la escena
             * acumulaba una composicion por repeticion y salia cada vez mas
             * brillante. Eso tapaba justo lo que se queria observar: en
             * 3146507587 el motion blur se desvanece a negro en vivo y con 30
             * repeticiones aqui salia mas claro que con una. */
            flush_object();
            traza_buffers(n_frames++);
            glBindFramebuffer(GL_FRAMEBUFFER, scene_rt.fbo);
            glViewport(0, 0, scene_rt.w, scene_rt.h);
            glClearColor(0, 0, 0, 0);
            glClear(GL_COLOR_BUFFER_BIT);
        } else if (strcmp(kw, "meshtime") == 0) {
            sscanf(line, "%*s %f", &mesh_time);
        } else if (strcmp(kw, "psys") == 0 && !in_pass) {
            int id;
            char path[512];
            if (sscanf(line, "%*s %d %511s", &id, path) == 2)
                load_psys(id, path);
        } else if (strcmp(kw, "mesh") == 0 && !in_pass) {
            int id, nvert, nidx, nbones = 0, nkeys = 0;
            float dur = 0.0f;
            char path[512];
            int n = sscanf(line, "%*s %d %511s %d %d %d %d %f",
                           &id, path, &nvert, &nidx, &nbones, &nkeys, &dur);
            if (n == 4 || n == 7)
                load_mesh(id, path, nvert, nidx,
                          n == 7 ? nbones : 0, n == 7 ? nkeys : 0, dur);
        } else if (strcmp(kw, "dump") == 0) {
            /* Instrumentacion: vuelca el compuesto actual para poder ver en
             * que pase exacto se pierde la imagen. */
            char path[512];
            if (sscanf(line, "%*s %511s", path) == 1) {
                unsigned char *px = malloc((size_t)canvas_w * canvas_h * 4);
                glBindFramebuffer(GL_FRAMEBUFFER, compo[compo_cur].fbo);
                glReadPixels(0, 0, canvas_w, canvas_h, GL_RGBA, GL_UNSIGNED_BYTE, px);
                FILE *o = fopen(path, "wb");
                if (o) { fwrite(px, 1, (size_t)canvas_w * canvas_h * 4, o); fclose(o); }
                free(px);
            }
        } else if (strcmp(kw, "copy") == 0) {
            /* Blit entre render targets. El motion blur lo usa para reciclar
             * su buffer de acumulacion; saltarselo corta la cadena entera. */
            char src[128], dst[128];
            if (sscanf(line, "%*s %127s %127s", src, dst) == 2) {
                Target *s = strcmp(src, "prev") == 0 ? &compo[compo_cur] : find_rt(src);
                Target *d = strcmp(dst, "prev") == 0 ? &compo[compo_cur] : find_rt(dst);
                glBindFramebuffer(GL_READ_FRAMEBUFFER, s->fbo);
                glBindFramebuffer(GL_DRAW_FRAMEBUFFER, d->fbo);
                glBlitFramebuffer(0, 0, s->w, s->h, 0, 0, d->w, d->h,
                                  GL_COLOR_BUFFER_BIT, GL_LINEAR);
                glBindFramebuffer(GL_FRAMEBUFFER, 0);
            }
        } else if (strcmp(kw, "output") == 0) {
            /* Va fuera de cualquier pase: hay que atenderla antes de la
             * guarda de !in_pass o se pierde silenciosamente. */
            sscanf(line, "%*s %511s", outpath);
        } else if (strcmp(kw, "pass") == 0) {
            /* Ultimo momento antes de dibujar: ya se leyo toda la cabecera,
             * asi que `meshtime` y las mallas estan cargadas en cualquier orden. */
            skin_all();
            in_pass = 1;
            prog = 0;
            n_samplers = n_unis = 0;
            mesh_id = -1;
            psys_id = -1;
            snprintf(target, sizeof target, "SCREEN");
            snprintf(blend, sizeof blend, "normal");
        } else if (!in_pass) {
            continue;
        } else if (strcmp(kw, "mesh") == 0) {
            /* Dentro de un pase `mesh` lleva solo el id. */
            sscanf(line, "%*s %d", &mesh_id);
        } else if (strcmp(kw, "psys") == 0) {
            sscanf(line, "%*s %d", &psys_id);
        } else if (strcmp(kw, "prog") == 0) {
            char vp[512], fp[512];
            sscanf(line, "%*s %511s %511s", vp, fp);
            prog = cached_program(vp, fp);
            snprintf(frag_actual, sizeof frag_actual, "%s", strrchr(fp, '/') ? strrchr(fp, '/') + 1 : fp);
        } else if (strcmp(kw, "target") == 0) {
            sscanf(line, "%*s %127s", target);
        } else if (strcmp(kw, "blend") == 0) {
            sscanf(line, "%*s %31s", blend);
        } else if (strcmp(kw, "sampler") == 0 && n_samplers < MAX_SAMPLERS) {
            sscanf(line, "%*s %63s %127s", samplers[n_samplers].uni,
                   samplers[n_samplers].src);
            n_samplers++;
        } else if (strncmp(kw, "u", 1) == 0 && n_unis < MAX_UNIFORMS) {
            int cnt = 0;
            if (strcmp(kw, "u1f") == 0) cnt = 1;
            else if (strcmp(kw, "u2f") == 0) cnt = 2;
            else if (strcmp(kw, "u3f") == 0) cnt = 3;
            else if (strcmp(kw, "u4f") == 0) cnt = 4;
            else if (strcmp(kw, "umat3") == 0) cnt = 9;
            else if (strcmp(kw, "umat4") == 0) cnt = 16;
            if (cnt) {
                char *p = line + strlen(kw);
                sscanf(p, "%63s", unis[n_unis].uni);
                p = strstr(p, unis[n_unis].uni) + strlen(unis[n_unis].uni);
                for (int i = 0; i < cnt; i++)
                    unis[n_unis].v[i] = strtof(p, &p);
                unis[n_unis].n = cnt;
                n_unis++;
            }
        } else if (strcmp(kw, "endpass") == 0) {
            in_pass = 0;
            if (!prog) {
                skipped++;
                continue;
            }

            /* Resolver TODO antes de bindear el destino. find_rt puede crear
             * el render target, y crearlo implica bindear su FBO para
             * limpiarlo: si eso pasa despues, el draw se va al buffer
             * equivocado y el destino se queda vacio. */
            GLuint bound[MAX_SAMPLERS];
            for (int i = 0; i < n_samplers; i++) {
                const char *s = samplers[i].src;
                bound[i] = 0;
                if (strncmp(s, "tex:", 4) == 0)
                    bound[i] = textures[atoi(s + 4)];
                else if (strncmp(s, "rt:", 3) == 0)
                    bound[i] = find_rt(s + 3)->tex;
                else if (strcmp(s, "prev") == 0)
                    bound[i] = compo[compo_cur].tex;
            }

            int to_screen = strcmp(target, "SCREEN") == 0;
            Target *dst = to_screen ? &compo[compo_cur ^ 1] : find_rt(target);

            glBindFramebuffer(GL_FRAMEBUFFER, dst->fbo);
            glViewport(0, 0, dst->w, dst->h);
            glClearColor(0, 0, 0, 0);
            glClear(GL_COLOR_BUFFER_BIT);
            glUseProgram(prog);
            set_blend(blend);

            for (int i = 0; i < n_samplers; i++) {
                glActiveTexture(GL_TEXTURE0 + i);
                glBindTexture(GL_TEXTURE_2D, bound[i]);
                GLint loc = glGetUniformLocation(prog, samplers[i].uni);
                if (loc >= 0)
                    glUniform1i(loc, i);
            }

            for (int i = 0; i < n_unis; i++) {
                GLint loc = glGetUniformLocation(prog, unis[i].uni);
                if (loc < 0)
                    continue;
                switch (unis[i].n) {
                case 1: glUniform1fv(loc, 1, unis[i].v); break;
                case 2: glUniform2fv(loc, 1, unis[i].v); break;
                case 3: glUniform3fv(loc, 1, unis[i].v); break;
                case 4: glUniform4fv(loc, 1, unis[i].v); break;
                case 9: glUniformMatrix3fv(loc, 1, GL_FALSE, unis[i].v); break;
                case 16: glUniformMatrix4fv(loc, 1, GL_FALSE, unis[i].v); break;
                }
            }

            if (psys_id >= 0) {
                /* El instante sale del propio pase: `g_Time` ya viene resuelto
                 * en el plan y asi la simulacion no necesita un reloj aparte
                 * que pudiera desincronizarse del que ven los shaders. */
                float t = 0.0f;
                for (int i = 0; i < n_unis; i++)
                    if (strcmp(unis[i].uni, "g_Time") == 0)
                        t = unis[i].v[0];
                draw_psys(psys_id, t);
            } else if (mesh_id >= 0 && mesh_id < MAX_MESHES && meshes[mesh_id].index_count > 0) {
                glBindVertexArray(meshes[mesh_id].vao);
                glDrawElements(GL_TRIANGLES, meshes[mesh_id].index_count,
                               GL_UNSIGNED_SHORT, (void *)0);
                glBindVertexArray(quad_vao);
            } else {
                glBindVertexArray(quad_vao);
                glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
            }
            drawn++;

            /* Traza por pase: que escribe cada uno y con que resultado. La
             * traza por fotograma dice que un buffer acaba mal, no cual de los
             * pases que lo tocan lo dejo asi. */
            if (getenv("WE_TRACE_PASES")) {
                fprintf(stderr, "    pase %-14s -> %-22s", frag_actual, target);
                media_buffer("", dst);
                fprintf(stderr, "\n");
            }

            if (to_screen)
                compo_cur ^= 1;
        }
    }
    fclose(plan);

    /* El ultimo objeto sigue abierto: sin esto se pierde la capa de arriba. */
    flush_object();

    if (outpath[0]) {
        unsigned char *px = malloc((size_t)canvas_w * canvas_h * 4);
        /* Se lee la escena acumulada, no el buffer del ultimo objeto. */
        glBindFramebuffer(GL_FRAMEBUFFER,
                          scene_rt.fbo ? scene_rt.fbo : compo[compo_cur].fbo);
        glReadPixels(0, 0, canvas_w, canvas_h, GL_RGBA, GL_UNSIGNED_BYTE, px);
        FILE *o = fopen(outpath, "wb");
        fwrite(px, 1, (size_t)canvas_w * canvas_h * 4, o);
        fclose(o);
        free(px);
    }

    printf("pases dibujados: %d   omitidos (sin programa): %d\n", drawn, skipped);
    return 0;
}
