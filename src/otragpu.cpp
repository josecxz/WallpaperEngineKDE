// Ver otragpu.h: por que el fondo puede ir en otra GPU sin salir del hilo de
// render de Qt, y por que el fotograma cruza por la CPU.

// Sin esto eglplatform.h trae Xlib, cuyas macros (`None`, `Bool`, `Status`)
// chocan con Qt.
#define EGL_NO_X11
#define GL_GLEXT_PROTOTYPES
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/gl.h>
#include <GL/glext.h>

#include "otragpu.h"

#include <QByteArray>
#include <QtGlobal>

#include <cstring>
#include <ctime>

namespace {

double ahoraMs()
{
    timespec t{};
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec / 1e6;
}

// Media movil: un fotograma suelto lento no dice nada.
void acumula(double &media, double muestra)
{
    media = media > 0.0 ? media * 0.95 + muestra * 0.05 : muestra;
}

QString renderer()
{
    const auto *s = reinterpret_cast<const char *>(glGetString(GL_RENDERER));
    return s ? QString::fromLatin1(s) : QString();
}

} // namespace

bool OtraGpu::abrir(QString *informe)
{
    auto di = [informe](const QString &s) { if (informe) *informe = s; return false; };

    EGLContext ctxQt = eglGetCurrentContext();
    if (ctxQt == EGL_NO_CONTEXT)
        return di(QStringLiteral("Qt no dibuja con EGL: se dibuja en su GPU"));
    m_ctxQt = ctxQt;
    const QString rendererQt = renderer();

    auto queryDevices = reinterpret_cast<PFNEGLQUERYDEVICESEXTPROC>(
        eglGetProcAddress("eglQueryDevicesEXT"));
    auto queryDeviceString = reinterpret_cast<PFNEGLQUERYDEVICESTRINGEXTPROC>(
        eglGetProcAddress("eglQueryDeviceStringEXT"));
    if (!queryDevices || !queryDeviceString)
        return di(QStringLiteral("EGL sin EGL_EXT_device_enumeration"));

    EGLDeviceEXT dispositivos[16];
    EGLint n = 0;
    if (!queryDevices(16, dispositivos, &n) || n <= 0)
        return di(QStringLiteral("EGL no enumera dispositivos"));

    // Lo que se va a tocar es el estado EGL del hilo de Qt: se guarda todo y
    // se devuelve tal cual, pase lo que pase con cada candidato.
    const EGLenum apiQt = eglQueryAPI();
    EGLDisplay dpyQt = eglGetCurrentDisplay();
    EGLSurface drawQt = eglGetCurrentSurface(EGL_DRAW);
    EGLSurface readQt = eglGetCurrentSurface(EGL_READ);

    QString descartes;
    for (EGLint i = 0; i < n && !m_ctx; ++i) {
        // Sin nodo de render no es una GPU sino un rasterizador por software
        // (llvmpipe se enumera asi).
        const char *nodo = queryDeviceString(dispositivos[i], EGL_DRM_RENDER_NODE_FILE_EXT);
        const char *exts = queryDeviceString(dispositivos[i], EGL_EXTENSIONS);
        if (!nodo || (exts && std::strstr(exts, "EGL_MESA_device_software")))
            continue;
        EGLDisplay dpy = eglGetPlatformDisplay(EGL_PLATFORM_DEVICE_EXT, dispositivos[i], nullptr);
        // Mesa enumera tambien el nodo de NVIDIA, y ahi no tiene driver: falla
        // aqui y se pasa al siguiente, que es el de NVIDIA de verdad.
        if (dpy == EGL_NO_DISPLAY || !eglInitialize(dpy, nullptr, nullptr))
            continue;
        eglBindAPI(EGL_OPENGL_API);
        // GL 3.3 core, el mismo contexto que `tools/glexec.c`.
        const EGLint atr[] = {EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 3,
                              EGL_CONTEXT_OPENGL_PROFILE_MASK,
                              EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE};
        EGLContext ctx = eglCreateContext(dpy, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, atr);
        if (ctx == EGL_NO_CONTEXT)
            continue;
        if (eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
            const QString r = renderer();
            eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
            if (!r.isEmpty() && r != rendererQt) {
                m_dpy = dpy;
                m_ctx = ctx;
                if (informe)
                    *informe = QStringLiteral("el fondo se dibuja en %1 (%2); Qt compone en %3")
                                   .arg(r, QString::fromLatin1(nodo), rendererQt);
                break;
            }
            descartes += QStringLiteral(" %1=Qt").arg(QString::fromLatin1(nodo));
        }
        eglDestroyContext(dpy, ctx);
        // Sin eglTerminate: el EGLDisplay de un dispositivo es unico en el
        // proceso, y lo puede estar usando el fondo de otra pantalla.
    }

    eglBindAPI(apiQt);
    eglMakeCurrent(dpyQt, drawQt, readQt, ctxQt);
    if (!m_ctx)
        return di(QStringLiteral("no hay otra GPU que la de Qt (%1;%2)").arg(rendererQt, descartes));
    return true;
}

bool OtraGpu::entrar()
{
    m_prevApi = eglQueryAPI();
    m_prevDpy = eglGetCurrentDisplay();
    m_prevDraw = eglGetCurrentSurface(EGL_DRAW);
    m_prevRead = eglGetCurrentSurface(EGL_READ);
    m_prevCtx = eglGetCurrentContext();
    eglBindAPI(EGL_OPENGL_API);
    if (eglMakeCurrent(m_dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, m_ctx))
        return true;
    eglBindAPI(m_prevApi);
    return false;
}

void OtraGpu::salir()
{
    eglBindAPI(m_prevApi);
    if (m_prevCtx != EGL_NO_CONTEXT)
        eglMakeCurrent(m_prevDpy, m_prevDraw, m_prevRead, m_prevCtx);
    else
        eglMakeCurrent(m_dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
}

unsigned OtraGpu::destino(int w, int h)
{
    if (m_fbo && w == m_w && h == m_h)
        return m_fbo;
    if (!m_tex) {
        glGenTextures(1, &m_tex);
        glGenFramebuffers(1, &m_fbo);
    }
    glBindTexture(GL_TEXTURE_2D, m_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glBindTexture(GL_TEXTURE_2D, 0);
    glBindFramebuffer(GL_FRAMEBUFFER, m_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, m_tex, 0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    m_w = w;
    m_h = h;
    m_pixeles.resize(qsizetype(w) * h * 4);
    return m_fbo;
}

void OtraGpu::leer()
{
    const double t0 = ahoraMs();
    glBindFramebuffer(GL_READ_FRAMEBUFFER, m_fbo);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
    glReadPixels(0, 0, m_w, m_h, GL_RGBA, GL_UNSIGNED_BYTE, m_pixeles.data());
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    acumula(m_msLeer, ahoraMs() - t0);
}

void OtraGpu::presentar(unsigned qtFbo)
{
    const double t0 = ahoraMs();
    if (!m_texQt) {
        glGenTextures(1, &m_texQt);
        glGenFramebuffers(1, &m_fboQt);
    }
    // El estado de desempaquetado es de Qt: se deja como estaba. El de
    // texturas y framebuffers lo da por perdido el propio `endExternal()`.
    GLint unpackBuf = 0, align = 4, fila = 0;
    glGetIntegerv(GL_PIXEL_UNPACK_BUFFER_BINDING, &unpackBuf);
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &align);
    glGetIntegerv(GL_UNPACK_ROW_LENGTH, &fila);
    glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);

    glBindTexture(GL_TEXTURE_2D, m_texQt);
    if (m_wQt != m_w || m_hQt != m_h) {
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, m_w, m_h, 0, GL_RGBA, GL_UNSIGNED_BYTE,
                     m_pixeles.constData());
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, m_fboQt);
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                               m_texQt, 0);
        m_wQt = m_w;
        m_hQt = m_h;
    } else {
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, m_w, m_h, GL_RGBA, GL_UNSIGNED_BYTE,
                        m_pixeles.constData());
    }
    glBindTexture(GL_TEXTURE_2D, 0);

    glBindBuffer(GL_PIXEL_UNPACK_BUFFER, GLuint(unpackBuf));
    glPixelStorei(GL_UNPACK_ALIGNMENT, align);
    glPixelStorei(GL_UNPACK_ROW_LENGTH, fila);

    // Pixel a pixel y sin mezcla: es el mismo fotograma que el plan habria
    // dejado en `qtFbo` dibujando directamente ahi, alfa incluido.
    glBindFramebuffer(GL_READ_FRAMEBUFFER, m_fboQt);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, qtFbo);
    glBlitFramebuffer(0, 0, m_w, m_h, 0, 0, m_w, m_h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
    // Como lo deja `GlExecutor::render`: el destino de Qt, que sigue dibujando
    // ahi al volver de endExternal().
    glBindFramebuffer(GL_FRAMEBUFFER, qtFbo);
    glViewport(0, 0, m_w, m_h);
    acumula(m_msPresentar, ahoraMs() - t0);
}

void OtraGpu::liberarDentro()
{
    if (m_tex) glDeleteTextures(1, &m_tex);
    if (m_fbo) glDeleteFramebuffers(1, &m_fbo);
    m_tex = m_fbo = 0;
    m_w = m_h = 0;
}

void OtraGpu::cerrar()
{
    // Lo de Qt solo con SU contexto puesto; si no, se queda para cuando Qt
    // destruya el suyo, como hace GlExecutor en su destructor.
    if (eglGetCurrentContext() == m_ctxQt && m_ctxQt) {
        if (m_texQt) glDeleteTextures(1, &m_texQt);
        if (m_fboQt) glDeleteFramebuffers(1, &m_fboQt);
    }
    m_texQt = m_fboQt = 0;
    m_wQt = m_hQt = 0;
    if (m_ctx) {
        eglDestroyContext(m_dpy, m_ctx);
        m_ctx = nullptr;
    }
}
