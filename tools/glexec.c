/* Ejecutor de planes de render: corre una escena de WE headless y vuelca RGBA.
 *
 * Toda la inteligencia (parsear scene.json, traducir shaders, decodificar
 * texturas) vive en Python. Esto solo ejecuta un plan ya resuelto, en un
 * contexto EGL surfaceless con OpenGL 3.3 core -- el mismo dialecto al que
 * apunta el traductor.
 *
 *   cc -O2 -o glexec glexec.c -lEGL -lGL
 *   ./glexec plan.txt
 *
 * Formato del plan (una directiva por linea, sin anidamiento):
 *
 *   canvas <w> <h>
 *   tex <id> <ruta.rgba> <w> <h>       textura RGBA8 cruda ya decodificada
 *   pass                               abre un pase
 *     prog <vert> <frag>
 *     target <nombre|SCREEN>           SCREEN = buffer acumulado del objeto
 *     sampler <uniform> tex:<id>|rt:<nombre>|prev
 *     u1f/u2f/u3f/u4f <uniform> <floats>
 *     umat4 <uniform> <16 floats>
 *     blend <normal|translucent|additive|none>
 *   endpass
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
#include <string.h>

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

static GLuint quad_vao, quad_vbo;

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
    /* Localizaciones fijas: el ejecutor siempre manda el mismo quad. */
    glBindAttribLocation(prog, 0, "a_Position");
    glBindAttribLocation(prog, 1, "a_TexCoord");
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
    if (strcmp(mode, "additive") == 0)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE);
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
    int in_pass = 0, drawn = 0, skipped = 0;
    GLuint prog = 0;
    char target[128] = "SCREEN";
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
        } else if (strcmp(kw, "tex") == 0) {
            int id, w, h;
            char path[512];
            sscanf(line, "%*s %d %511s %d %d", &id, path, &w, &h);
            if (id >= 0 && id < MAX_TEX) {
                textures[id] = load_texture(path, w, h);
            }
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
            in_pass = 1;
            prog = 0;
            n_samplers = n_unis = 0;
            snprintf(target, sizeof target, "SCREEN");
            snprintf(blend, sizeof blend, "normal");
        } else if (!in_pass) {
            continue;
        } else if (strcmp(kw, "prog") == 0) {
            char vp[512], fp[512];
            sscanf(line, "%*s %511s %511s", vp, fp);
            prog = cached_program(vp, fp);
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
                case 16: glUniformMatrix4fv(loc, 1, GL_FALSE, unis[i].v); break;
                }
            }

            glBindVertexArray(quad_vao);
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
            drawn++;

            if (to_screen)
                compo_cur ^= 1;
        }
    }
    fclose(plan);

    if (outpath[0]) {
        unsigned char *px = malloc((size_t)canvas_w * canvas_h * 4);
        glBindFramebuffer(GL_FRAMEBUFFER, compo[compo_cur].fbo);
        glReadPixels(0, 0, canvas_w, canvas_h, GL_RGBA, GL_UNSIGNED_BYTE, px);
        FILE *o = fopen(outpath, "wb");
        fwrite(px, 1, (size_t)canvas_w * canvas_h * 4, o);
        fclose(o);
        free(px);
    }

    printf("pases dibujados: %d   omitidos (sin programa): %d\n", drawn, skipped);
    return 0;
}
