/* Compila shaders con el driver GLES real, no con un validador de referencia.
 *
 * glslangValidator es util pero no es el compilador que usara el motor. Mesa
 * acepta y rechaza cosas distintas, asi que la unica prueba que vale es pasar
 * el shader por el mismo glCompileShader que correra en produccion.
 *
 * Usa el contexto surfaceless de EGL: ni ventana ni pbuffer, corre headless.
 *
 *   cc -O2 -o glslcheck glslcheck.c -lEGL -lGLESv2
 *   ./glslcheck fichero.vert fichero.frag ...
 *
 * Salida: una linea "OK <ruta>" o "FAIL <ruta>" por fichero; el log del
 * compilador va a stderr para no ensuciar el recuento.
 */

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Las entradas GL se resuelven por eglGetProcAddress en vez de enlazarse.
 * Asi el mismo binario compila contra GLES y contra GL de escritorio, que es
 * justo la comparacion que interesa: los dos dialectos no aceptan lo mismo. */
static GLuint (*p_glCreateShader)(GLenum);
static void (*p_glShaderSource)(GLuint, GLsizei, const GLchar *const *, const GLint *);
static void (*p_glCompileShader)(GLuint);
static void (*p_glGetShaderiv)(GLuint, GLenum, GLint *);
static void (*p_glGetShaderInfoLog)(GLuint, GLsizei, GLsizei *, GLchar *);
static void (*p_glDeleteShader)(GLuint);
static const GLubyte *(*p_glGetString)(GLenum);
/* Para --link: compilar no basta. Un vertice y un fragmento pueden compilar
 * cada uno por su lado y no poder enlazarse, porque lo que tiene que casar es
 * la INTERFAZ entre los dos --- que el varying que uno escribe y el otro lee
 * tengan el mismo tipo y la misma longitud. Ese error no lo ve nadie hasta que
 * el motor intenta crear el programa y se queda sin pase. */
static GLuint (*p_glCreateProgram)(void);
static void (*p_glAttachShader)(GLuint, GLuint);
static void (*p_glLinkProgram)(GLuint);
static void (*p_glGetProgramiv)(GLuint, GLenum, GLint *);
static void (*p_glGetProgramInfoLog)(GLuint, GLsizei, GLsizei *, GLchar *);
static void (*p_glDeleteProgram)(GLuint);
static void (*p_glBindAttribLocation)(GLuint, GLuint, const GLchar *);

static int load_gl(void)
{
    p_glCreateShader = (void *)eglGetProcAddress("glCreateShader");
    p_glShaderSource = (void *)eglGetProcAddress("glShaderSource");
    p_glCompileShader = (void *)eglGetProcAddress("glCompileShader");
    p_glGetShaderiv = (void *)eglGetProcAddress("glGetShaderiv");
    p_glGetShaderInfoLog = (void *)eglGetProcAddress("glGetShaderInfoLog");
    p_glDeleteShader = (void *)eglGetProcAddress("glDeleteShader");
    p_glGetString = (void *)eglGetProcAddress("glGetString");
    p_glCreateProgram = (void *)eglGetProcAddress("glCreateProgram");
    p_glAttachShader = (void *)eglGetProcAddress("glAttachShader");
    p_glLinkProgram = (void *)eglGetProcAddress("glLinkProgram");
    p_glGetProgramiv = (void *)eglGetProcAddress("glGetProgramiv");
    p_glGetProgramInfoLog = (void *)eglGetProcAddress("glGetProgramInfoLog");
    p_glDeleteProgram = (void *)eglGetProcAddress("glDeleteProgram");
    p_glBindAttribLocation = (void *)eglGetProcAddress("glBindAttribLocation");
    return p_glCreateShader && p_glShaderSource && p_glCompileShader &&
           p_glGetShaderiv && p_glGetShaderInfoLog && p_glDeleteShader && p_glGetString;
}

static char *read_file(const char *path, long *len)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    *len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(*len + 1);
    if (fread(buf, 1, *len, f) != (size_t)*len) {
        fclose(f);
        free(buf);
        return NULL;
    }
    buf[*len] = 0;
    fclose(f);
    return buf;
}

int main(int argc, char **argv)
{
    int desktop = 0, first = 1;
    if (argc > 1 && strcmp(argv[1], "--desktop") == 0) {
        desktop = 1;
        first = 2;
    }

    EGLDisplay dpy = eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA,
                                           EGL_DEFAULT_DISPLAY, NULL);
    if (dpy == EGL_NO_DISPLAY) {
        fprintf(stderr, "sin display surfaceless de EGL\n");
        return 2;
    }
    if (!eglInitialize(dpy, NULL, NULL)) {
        fprintf(stderr, "eglInitialize fallo\n");
        return 2;
    }
    eglBindAPI(desktop ? EGL_OPENGL_API : EGL_OPENGL_ES_API);

    EGLint cfg_attr[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
                         EGL_RENDERABLE_TYPE,
                         desktop ? EGL_OPENGL_BIT : EGL_OPENGL_ES3_BIT,
                         EGL_NONE};
    EGLConfig cfg;
    EGLint n;
    if (!eglChooseConfig(dpy, cfg_attr, &cfg, 1, &n) || n < 1) {
        fprintf(stderr, "sin config EGL para %s\n", desktop ? "GL" : "GLES3");
        return 2;
    }

    EGLint es_attr[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLint gl_attr[] = {EGL_CONTEXT_MAJOR_VERSION, 3,
                        EGL_CONTEXT_MINOR_VERSION, 3,
                        EGL_CONTEXT_OPENGL_PROFILE_MASK,
                        EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,
                        EGL_NONE};
    EGLContext ctx = eglCreateContext(dpy, cfg, EGL_NO_CONTEXT,
                                      desktop ? gl_attr : es_attr);
    if (ctx == EGL_NO_CONTEXT) {
        fprintf(stderr, "eglCreateContext fallo\n");
        return 2;
    }
    /* Requiere EGL_KHR_surfaceless_context, presente en Mesa desde hace anos. */
    if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
        fprintf(stderr, "eglMakeCurrent sin superficie fallo\n");
        return 2;
    }

    if (!load_gl()) {
        fprintf(stderr, "no se pudieron resolver las entradas GL\n");
        return 2;
    }

    if (argc > first && strcmp(argv[first], "--info") == 0) {
        printf("GL_VERSION  : %s\n", p_glGetString(GL_VERSION));
        printf("GL_RENDERER : %s\n", p_glGetString(GL_RENDERER));
        printf("GLSL        : %s\n", p_glGetString(GL_SHADING_LANGUAGE_VERSION));
        return 0;
    }

    /* --link <v1> <f1> <v2> <f2> ...: compila cada par y lo ENLAZA. */
    if (argc > first && strcmp(argv[first], "--link") == 0) {
        int failed = 0;
        for (int i = first + 1; i + 1 < argc; i += 2) {
            GLuint prog = p_glCreateProgram();
            int ok_compilar = 1;
            for (int k = 0; k < 2; k++) {
                long len;
                char *src = read_file(argv[i + k], &len);
                if (!src) { ok_compilar = 0; break; }
                GLuint sh = p_glCreateShader(k == 0 ? GL_VERTEX_SHADER
                                                   : GL_FRAGMENT_SHADER);
                const char *pp = src;
                p_glShaderSource(sh, 1, &pp, NULL);
                p_glCompileShader(sh);
                GLint ok = 0;
                p_glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
                if (ok)
                    p_glAttachShader(prog, sh);
                else
                    ok_compilar = 0;   /* ya lo reporta el modo normal */
                p_glDeleteShader(sh);
                free(src);
            }
            if (!ok_compilar) {
                p_glDeleteProgram(prog);
                continue;              /* no es fallo de enlace */
            }
            /* Los mismos atributos que ata el motor, o el enlazador puede
             * quejarse de algo que en produccion no pasa. */
            p_glBindAttribLocation(prog, 0, "a_Position");
            p_glBindAttribLocation(prog, 0, "a_PositionVec4");
            p_glBindAttribLocation(prog, 1, "a_TexCoord");
            p_glLinkProgram(prog);
            GLint ok = 0;
            p_glGetProgramiv(prog, GL_LINK_STATUS, &ok);
            if (ok) {
                printf("OK %s\n", argv[i]);
            } else {
                printf("FAIL %s\n", argv[i]);
                GLint loglen = 0;
                p_glGetProgramiv(prog, GL_INFO_LOG_LENGTH, &loglen);
                char *log = malloc(loglen + 1);
                p_glGetProgramInfoLog(prog, loglen, NULL, log);
                fprintf(stderr, "== enlace %s + %s ==\n%s\n",
                        argv[i], argv[i + 1], log);
                free(log);
                failed++;
            }
            p_glDeleteProgram(prog);
        }
        return failed ? 1 : 0;
    }

    int failed = 0;
    for (int i = first; i < argc; i++) {
        const char *path = argv[i];
        const char *dot = strrchr(path, '.');
        GLenum stage = (dot && strcmp(dot, ".vert") == 0) ? GL_VERTEX_SHADER
                                                          : GL_FRAGMENT_SHADER;
        long len;
        char *src = read_file(path, &len);
        if (!src) {
            printf("FAIL %s\n", path);
            fprintf(stderr, "== %s ==\nno se pudo leer\n", path);
            failed++;
            continue;
        }

        GLuint sh = p_glCreateShader(stage);
        const char *p = src;
        p_glShaderSource(sh, 1, &p, NULL);
        p_glCompileShader(sh);

        GLint ok = 0;
        p_glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
        if (ok) {
            printf("OK %s\n", path);
        } else {
            printf("FAIL %s\n", path);
            GLint loglen = 0;
            p_glGetShaderiv(sh, GL_INFO_LOG_LENGTH, &loglen);
            char *log = malloc(loglen + 1);
            p_glGetShaderInfoLog(sh, loglen, NULL, log);
            fprintf(stderr, "== %s ==\n%s\n", path, log);
            free(log);
            failed++;
        }
        p_glDeleteShader(sh);
        free(src);
    }
    return failed ? 1 : 0;
}
