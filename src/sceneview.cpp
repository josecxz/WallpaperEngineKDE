// GL_GLEXT_PROTOTYPES debe definirse antes de cualquier include: Qt
// arrastra GL/gl.h, y si llega primero no se declaran los prototipos de GL 2+.
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>

#include "sceneview.h"

#include <cmath>

#include <QDebug>
#include <QMetaObject>
#include <QUrl>
#include <QColor>

#include <rhi/qrhi.h>


// ── SceneView ───────────────────────────────────────────────────────────────

SceneView::SceneView(QQuickItem *parent)
    : QQuickRhiItem(parent)
{
    // El plan ya trae el color con alfa correcto; sin esto Qt lo compondria
    // otra vez y volveria a oscurecer los bordes.
    setAlphaBlending(false);
}

void SceneView::setPlanSource(const QUrl &source)
{
    if (source == m_planSource)
        return;
    m_planSource = source;
    m_planPath = source.isLocalFile() ? source.toLocalFile() : source.toString();
    Q_EMIT planSourceChanged();
    update();
}

void SceneView::setTime(qreal t)
{
    // qFuzzyCompare no sirve cerca de cero, y elapsedTime empieza justo ahi.
    // Se compara contra un umbral absoluto: por debajo de medio milisegundo no
    // hay fotograma que ganar ni a 1000 Hz.
    if (qAbs(t - m_time) < 0.0005)
        return;
    m_time = t;
    Q_EMIT timeChanged();
    update();     // pide un fotograma nuevo
}

// Los cinco piden un fotograma al cambiar, y ese `update()` no es opcional:
// `SceneView` solo dibuja cuando algo cambia, asi que con el reloj en pausa
// ---escritorio tapado--- mover el encaje desde la configuracion no se veria
// hasta que volviera a haber ventana. La misma razon por la que el color de
// las barras vive aqui y no en el QML de debajo.
void SceneView::setEncaje(int v)
{
    if (v == m_encaje)
        return;
    m_encaje = v;
    Q_EMIT encajeChanged();
    update();
}

void SceneView::setZoom(qreal v)
{
    if (qFuzzyCompare(v, m_zoom))
        return;
    m_zoom = v;
    Q_EMIT encajeChanged();
    update();
}

void SceneView::setDesplazamientoX(qreal v)
{
    if (qFuzzyCompare(1.0 + v, 1.0 + m_despX))    // qFuzzyCompare no vale en 0
        return;
    m_despX = v;
    Q_EMIT encajeChanged();
    update();
}

void SceneView::setDesplazamientoY(qreal v)
{
    if (qFuzzyCompare(1.0 + v, 1.0 + m_despY))
        return;
    m_despY = v;
    Q_EMIT encajeChanged();
    update();
}

void SceneView::setColorBarras(const QColor &c)
{
    if (c == m_colorBarras)
        return;
    m_colorBarras = c;
    Q_EMIT encajeChanged();
    update();
}

void SceneView::setStatusFromRenderer(const QString &s)
{
    // `dibujado` solo puede ir a mas: una vez que la escena ha salido a
    // pantalla, un error posterior no la devuelve a "cargando".
    if (!m_dibujado && !s.isEmpty() && s != QStringLiteral("cargando")
            && s != QStringLiteral("sin inicializar"))
        m_dibujado = true;
    if (s == m_status)
        return;
    m_status = s;
    Q_EMIT statusChanged();
}

void SceneView::setMsGpuFromRenderer(qreal ms)
{
    if (qFuzzyCompare(ms, m_msGpu))
        return;
    m_msGpu = ms;
    Q_EMIT msGpuChanged();
}

void SceneView::setSceneTitleFromRenderer(const QString &t)
{
    if (t == m_sceneTitle)
        return;
    m_sceneTitle = t;
    Q_EMIT sceneTitleChanged();
}

QQuickRhiItemRenderer *SceneView::createRenderer()
{
    return new SceneRenderer;
}

// ── SceneRenderer ───────────────────────────────────────────────────────────

void SceneRenderer::initialize(QRhiCommandBuffer *)
{
    // Nada que hacer aqui: los recursos GL se crean en el primer render, ya
    // dentro de beginExternal(), que es donde el contexto GL es nuestro.
}

void SceneRenderer::synchronize(QQuickRhiItem *item)
{
    // Unico punto seguro para leer del item: los dos hilos estan parados.
    auto *view = static_cast<SceneView *>(item);
    m_planPath = view->m_planPath;
    m_time = float(view->m_time);
    // Antes del corte por fase de abajo: el encaje cambia sin que cambie la
    // fase, y si se copiara despues no llegaria nunca al hilo de render.
    m_encaje = view->m_encaje;
    m_zoom = float(view->m_zoom);
    m_despX = float(view->m_despX);
    m_despY = float(view->m_despY);
    m_bar[0] = float(view->m_colorBarras.redF());
    m_bar[1] = float(view->m_colorBarras.greenF());
    m_bar[2] = float(view->m_colorBarras.blueF());

    // El estado solo cambia en las transiciones cargando -> listo -> error.
    // Construir la cadena y cruzar hilos en cada fotograma seria trabajo
    // constante para un resultado que no cambia: 166 QString y 166
    // invokeMethod por segundo tirados.
    const int fase = m_failed ? 2 : (m_planLoaded ? 1 : 0);
    // El cronometro de GPU va ANTES del corte por fase, y ese detalle es todo:
    // debajo hay un `return` que solo deja pasar el fotograma en que cambia el
    // estado, asi que publicarlo despues lo mandaba una vez y nunca mas ---el
    // HUD decia "sin medida" mientras el motor tenia el numero. Solo se manda
    // cuando se mueve de verdad: son 165 sincronias por segundo y no hay nada
    // que ganar despertando al hilo de la interfaz por una centesima.
    const double gpu = m_exec.diagGpuMs();
    if (gpu >= 0 && std::abs(gpu - m_gpuPublicado) > 0.05) {
        m_gpuPublicado = gpu;
        QMetaObject::invokeMethod(view, "setMsGpuFromRenderer", Qt::QueuedConnection,
                                  Q_ARG(qreal, qreal(gpu)));
    }

    if (fase == m_reportedPhase)
        return;
    m_reportedPhase = fase;

    QString estado;
    switch (fase) {
    case 2:
        estado = QStringLiteral("error: ") + m_exec.log().section(QLatin1Char('\n'), 0, 0);
        break;
    case 1:
        estado = QStringLiteral("%1 pases · %2x%3 · %4 uniforms activos")
                     .arg(m_exec.passCount())
                     .arg(m_exec.canvasWidth())
                     .arg(m_exec.canvasHeight())
                     .arg(m_exec.liveUniformCount());
        break;
    default:
        estado = QStringLiteral("cargando");
        break;
    }

    // No se puede emitir la senal desde el hilo de render.
    QMetaObject::invokeMethod(view, "setStatusFromRenderer", Qt::QueuedConnection,
                              Q_ARG(QString, estado));

    if (fase == 1) {
        // Q_ARG guarda std::addressof() del valor, NO una copia. Pasarle el
        // temporal que devuelve title() deja al evento en cola apuntando a
        // memoria muerta: la cadena llega con puntero nulo y longitud no nula
        // y Qt aborta con ASSERT "str || !len".
        const QString titulo = m_exec.title();
        QMetaObject::invokeMethod(view, "setSceneTitleFromRenderer", Qt::QueuedConnection,
                                  Q_ARG(QString, titulo));
    }
}

void SceneRenderer::render(QRhiCommandBuffer *cb)
{
    if (m_failed || m_planPath.isEmpty())
        return;

    QRhi *r = rhi();
    if (!r)
        return;
    if (r->backend() != QRhi::OpenGLES2) {
        // QRhi::OpenGLES2 es el nombre del backend de OpenGL en Qt, tanto
        // para GL de escritorio como para GLES. Cualquier otro (Vulkan) hace
        // que las llamadas GL crudas no signifiquen nada.
        m_failed = true;
        qWarning("SceneView: backend RHI %s; se necesita OpenGL. "
                 "Arranca con QSG_RHI_BACKEND=opengl.", r->backendName());
        return;
    }

    QRhiTexture *color = colorTexture();
    if (!color)
        return;
    const QSize size = color->pixelSize();
    if (size.isEmpty())
        return;

    // Abrir el pase de Qt y escribir en SU framebuffer, en vez de fabricar uno
    // propio envolviendo la textura. Asi no hay que suponer nada sobre como
    // Qt tiene montado el render target (MSAA, formato, capas), y el resultado
    // queda donde Qt lo espera.
    cb->beginPass(renderTarget(), QColor(0, 0, 0, 0), {1.0f, 0});
    cb->beginExternal();

    if (!m_planLoaded) {
        QString err;
        if (!m_exec.loadPlan(m_planPath, &err) || !m_exec.initialize(&err)) {
            m_failed = true;
            qWarning("SceneView: %s", qPrintable(err.isEmpty() ? m_exec.log() : err));
            cb->endExternal();
            cb->endPass();
            return;
        }
        m_planLoaded = true;
        qInfo("SceneView: backend %s, plan con %d pases, lienzo %dx%d, "
              "init %d ms, uniforms %d activos / %d descartados, "
              "mallas %d subidas / %d pases las piden / %d animadas, "
              "particulas %d sistemas / %d piezas sin soporte",
              r->backendName(), m_exec.passCount(),
              m_exec.canvasWidth(), m_exec.canvasHeight(), m_exec.initMillis(),
              m_exec.liveUniformCount(), m_exec.droppedUniformCount(),
              m_exec.meshCount(), m_exec.meshPassCount(), m_exec.meshAnimCount(),
              m_exec.psysCount(), m_exec.psysUnknownParts());
        if (!m_exec.log().isEmpty())
            qWarning("SceneView: %s", qPrintable(m_exec.log()));
    }

    GLint qtFbo = 0;
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &qtFbo);
    m_exec.setFit(m_encaje, m_zoom, m_despX, m_despY);
    m_exec.setBarColor(m_bar[0], m_bar[1], m_bar[2]);
    m_exec.render(GLuint(qtFbo), size.width(), size.height(), m_time);

    // Segundo parte, ya en marcha: el primero sale en el fotograma 1, cuando el
    // cronometro de GPU aun no puede tener resultado por definicion.
    if (++m_frames == 200)
        qInfo("SceneView: cronometro de GPU -> %.2f ms/fotograma, "
              "saltos=%d fallos=%d consulta_ajena=%d",
              m_exec.diagGpuMs(), m_exec.diagGpuSaltos(),
              m_exec.diagGpuFallos(), m_exec.diagGpuAjena());

    if (!m_diagDone) {
        m_diagDone = true;
        const GLenum e = glGetError();
        qInfo("SceneView: destino=%d tam=%dx%d glError=0x%x compo_medio=%.1f targets=%d "
              "gpu=%.2f ms fallos_cronometro=%d",
              qtFbo, size.width(), size.height(), e,
              m_exec.diagCompoMean(), m_exec.targetCount(),
              m_exec.diagGpuMs(), m_exec.diagGpuFallos());
        if (m_exec.diagBlitError())
            qWarning("SceneView: error de GL tras componer: 0x%x", m_exec.diagBlitError());
    }

    cb->endExternal();
    cb->endPass();
}
