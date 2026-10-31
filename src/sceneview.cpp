// GL_GLEXT_PROTOTYPES debe definirse antes de cualquier include: Qt
// arrastra GL/gl.h, y si llega primero no se declaran los prototipos de GL 2+.
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>

#include "sceneview.h"
#include "escritorio.h"
#include "hyprland.h"

#include <QQuickWindow>
#include <QScreen>

#include <chrono>
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
    // El cursor global manda sobre el HoverHandler del QML en cuanto llega la
    // primera posicion: de KWin en Plasma (CursorKWin), de Hyprland en
    // Hyprland (CursorHyprland). Fuera de su escritorio cada uno se queda mudo.
    connect(CursorKWin::instancia(), &CursorKWin::movido, this,
            &SceneView::alMoverCursorGlobal);
    connect(CursorHyprland::instancia(), &CursorHyprland::movido, this,
            &SceneView::alMoverCursorGlobal);
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
    // El tope. El 0,9 da holgura al latido: con 60 en un panel de 165 Hz
    // (6,06 ms) se dibuja uno de cada tres latidos ---55 por segundo, siempre
    // con el mismo paso---; exigir 16,67 ms exactos alternaria tres y cuatro
    // latidos, y eso se ve como tirones. Un tiempo que va hacia atras es otro
    // reloj (la escena se ha recreado) y pide fotograma siempre.
    if (m_fpsMax > 0 && m_tPedido >= 0 && t >= m_tPedido && t - m_tPedido < 0.9 / m_fpsMax)
        return;
    m_tPedido = t;
    update();     // pide un fotograma nuevo
}

void SceneView::setFpsMax(qreal v)
{
    v = qMax<qreal>(0, v);
    if (qFuzzyCompare(1 + v, 1 + m_fpsMax))
        return;
    m_fpsMax = v;
    Q_EMIT fpsMaxChanged();
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

// El raton no pide fotograma: pedirlo dejaria el motor dibujando a la
// velocidad del raton con el escritorio tapado y el reloj en pausa, que es
// justo lo que la pausa evita. Con el reloj andando ya hay un fotograma por
// refresco y el puntero viaja en el de al lado.
void SceneView::setPuntero(const QPointF &p)
{
    if (!m_cursorKWin)
        ponPuntero(p, m_punteroPresente);
}

void SceneView::setPunteroPresente(bool v)
{
    if (!m_cursorKWin)
        ponPuntero(m_puntero, v);
}

// Pide fotograma: con el escritorio tapado y el reloj en pausa, el cambio de
// GPU tiene que llegar igual, como el encaje.
void SceneView::setGpuDedicada(bool v)
{
    if (v == m_gpuDedicada)
        return;
    m_gpuDedicada = v;
    Q_EMIT gpuDedicadaChanged();
    update();
}

void SceneView::ponPuntero(const QPointF &p, bool presente)
{
    if (p == m_puntero && presente == m_punteroPresente)
        return;
    m_puntero = p;
    m_punteroPresente = presente;
    Q_EMIT punteroChanged();
}

// El cursor global de KWin, a la pantalla de ESTE fondo. La ventana del
// escritorio ocupa su pantalla entera desde la esquina, asi que restar la
// esquina de la pantalla da coordenadas de la ventana, y de ahi al item.
// Fuera de esta pantalla no hay raton para este fondo. Sobre una ventana SI:
// como en Wallpaper Engine, que sigue el cursor por debajo de ellas.
void SceneView::alMoverCursorGlobal(QPointF global)
{
    QQuickWindow *w = window();
    QScreen *pantalla = w ? w->screen() : nullptr;
    if (!pantalla)
        return;
    m_cursorKWin = true;
    const QRectF g = pantalla->geometry();
    if (!g.contains(global)) {
        ponPuntero(m_puntero, false);
        return;
    }
    const QPointF enItem = mapFromScene(global - g.topLeft());
    ponPuntero(QPointF(enItem.x() / qMax(1.0, width()), enItem.y() / qMax(1.0, height())),
               true);
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

void SceneRenderer::soltarPlan()
{
    if (m_otra.abierta()) {
        if (m_otra.entrar()) {
            m_exec.releaseResources();
            m_otra.liberarDentro();
            m_otra.salir();
        }
        m_otra.cerrar();
    } else {
        m_exec.releaseResources();
    }
    // Todo como en el primer fotograma: se decide la GPU, se carga el plan y
    // se vuelve a publicar el estado. Un fallo de antes no se arrastra: puede
    // ser de la GPU que se deja.
    m_gpuDecidida = false;
    m_planLoaded = false;
    m_failed = false;
    m_diagDone = false;
    m_frames = 0;
    m_reportedPhase = -1;
}

SceneRenderer::~SceneRenderer()
{
    if (!m_otra.abierta())
        return;
    // El plan vive en el contexto propio: se entra, se suelta todo y se
    // devuelve el que hubiera. Asi el destructor de GlExecutor ya no tiene
    // nada que liberar ---ni con que contexto equivocarse---.
    if (m_otra.entrar()) {
        m_exec.releaseResources();
        m_otra.liberarDentro();
        m_otra.salir();
    }
    m_otra.cerrar();
}

namespace {
double ahoraMs()
{
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}
}  // namespace

SceneRenderer::SceneRenderer()
{
    bool ok = false;
    const double s = qEnvironmentVariable("WE_MEDIDAS").toDouble(&ok);
    m_medidaSeg = ok && s > 0 ? s : 0;
}

void SceneRenderer::contarMedida(double msCpu)
{
    const double ahora = ahoraMs();
    if (m_medidaInicio < 0) {
        // El primer fotograma abre el intervalo y no cuenta: lleva la carga
        // del plan dentro.
        m_medidaInicio = ahora;
        double d1, d2, d3;
        int i1;
        m_exec.tomarMuestrasGpu(d1, i1, d2);
        m_otra.tomarMuestrasCopia(d1, d3, i1);
        return;
    }
    m_medidaFotos++;
    m_medidaCpu += msCpu;
    m_medidaCpuMax = std::max(m_medidaCpuMax, msCpu);
    const double dur = ahora - m_medidaInicio;
    if (dur < m_medidaSeg * 1000.0)
        return;
    double gpuSuma = 0, gpuMax = 0, leer = 0, subir = 0;
    int gpuN = 0, copias = 0;
    m_exec.tomarMuestrasGpu(gpuSuma, gpuN, gpuMax);
    m_otra.tomarMuestrasCopia(leer, subir, copias);
    const int n = qMax(1, m_medidaFotos);
    qInfo("SceneView: medida pantalla=%s seg=%.2f fotogramas=%d fps=%.2f "
          "cpu_ms=%.3f cpu_max=%.3f gpu_ms=%.3f gpu_max=%.3f gpu_muestras=%d "
          "leer_ms=%.3f subir_ms=%.3f copias=%d",
          qPrintable(m_pantalla.isEmpty() ? QStringLiteral("?") : m_pantalla),
          dur / 1000.0, m_medidaFotos, m_medidaFotos * 1000.0 / dur,
          m_medidaCpu / n, m_medidaCpuMax, gpuN ? gpuSuma / gpuN : -1.0, gpuMax, gpuN,
          copias ? leer / copias : 0.0, copias ? subir / copias : 0.0, copias);
    m_medidaInicio = ahora;
    m_medidaFotos = 0;
    m_medidaCpu = m_medidaCpuMax = 0;
}

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
    m_puntero[0] = float(view->m_puntero.x());
    m_puntero[1] = float(view->m_puntero.y());
    m_punteroPresente = view->m_punteroPresente;
    m_quiereOtra = view->m_gpuDedicada;
    // En cada sincronia y no solo en la primera: al crearse, la ventana aun
    // tiene la pantalla por defecto, y las dos de dos monitores salian con el
    // mismo nombre.
    if (m_medidaSeg > 0 && view->window() && view->window()->screen())
        m_pantalla = view->window()->screen()->name();

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
    const double t0Medida = m_medidaSeg > 0 ? ahoraMs() : 0;
    // Pedir la otra GPU tambien saca de un fallo: se vuelve a intentar alli.
    const bool cambioDeGpu = m_gpuDecidida && m_quiereOtra != m_gpuPedida;
    if ((m_failed && !cambioDeGpu) || m_planPath.isEmpty())
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

    // El destino de Qt se lee AQUI, con su contexto aun puesto.
    GLint qtFbo = 0;
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &qtFbo);

    if (cambioDeGpu)
        soltarPlan();
    if (!m_gpuDecidida) {
        m_gpuDecidida = true;
        m_gpuPedida = m_quiereOtra;
        QString informe = QStringLiteral("configurado para dibujar en la GPU de Qt");
        if (m_gpuPedida)
            m_otra.abrir(&informe);
        qInfo("SceneView: %s", qPrintable(informe));
    }
    // Desde aqui hasta `salir()` todo GL va a la otra GPU, plan incluido: se
    // carga, se compila y se dibuja ahi.
    const bool aparte = m_otra.abierta();
    if (aparte && !m_otra.entrar()) {
        m_failed = true;
        qWarning("SceneView: no se pudo poner el contexto de la otra GPU");
        cb->endExternal();
        cb->endPass();
        return;
    }

    if (!m_planLoaded) {
        QString err;
        if (!m_exec.loadPlan(m_planPath, &err) || !m_exec.initialize(&err)) {
            m_failed = true;
            qWarning("SceneView: %s", qPrintable(err.isEmpty() ? m_exec.log() : err));
            if (aparte)
                m_otra.salir();
            cb->endExternal();
            cb->endPass();
            return;
        }
        m_planLoaded = true;
        qInfo("SceneView: backend %s, plan con %d pases, lienzo %dx%d, "
              "init %d ms, uniforms %d activos (%d por fotograma) / %d descartados, "
              "mallas %d subidas / %d pases las piden / %d animadas, "
              "particulas %d sistemas / %d piezas sin soporte / %d siguen al raton",
              r->backendName(), m_exec.passCount(),
              m_exec.canvasWidth(), m_exec.canvasHeight(), m_exec.initMillis(),
              m_exec.liveUniformCount(), m_exec.uniformsPorFotograma(),
              m_exec.droppedUniformCount(),
              m_exec.meshCount(), m_exec.meshPassCount(), m_exec.meshAnimCount(),
              m_exec.psysCount(), m_exec.psysUnknownParts(),
              m_exec.psysCursorCount());
        if (!m_exec.log().isEmpty())
            qWarning("SceneView: %s", qPrintable(m_exec.log()));
    }

    const GLuint destino = aparte ? m_otra.destino(size.width(), size.height())
                                  : GLuint(qtFbo);
    m_exec.setFit(m_encaje, m_zoom, m_despX, m_despY);
    m_exec.setBarColor(m_bar[0], m_bar[1], m_bar[2]);
    m_exec.setPuntero(m_puntero[0], m_puntero[1], m_punteroPresente);
    m_exec.render(destino, size.width(), size.height(), m_time);

    // Segundo parte, ya en marcha: el primero sale en el fotograma 1, cuando el
    // cronometro de GPU aun no puede tener resultado por definicion. Con el
    // plan en otra GPU el cronometro mide ESA GPU, y la copia va aparte: leer
    // en la otra y subir en la de Qt, en ms de CPU.
    if (++m_frames == 200)
        qInfo("SceneView: cronometro de GPU -> %.2f ms/fotograma, "
              "saltos=%d fallos=%d consulta_ajena=%d; copia leer=%.2f subir=%.2f ms",
              m_exec.diagGpuMs(), m_exec.diagGpuSaltos(),
              m_exec.diagGpuFallos(), m_exec.diagGpuAjena(),
              m_otra.msLeer(), m_otra.msPresentar());

    if (!m_diagDone) {
        m_diagDone = true;
        const GLenum e = glGetError();
        qInfo("SceneView: destino=%u (%s) tam=%dx%d glError=0x%x compo_medio=%.1f "
              "targets=%d gpu=%.2f ms fallos_cronometro=%d",
              destino, aparte ? "otra GPU" : "Qt", size.width(), size.height(), e,
              m_exec.diagCompoMean(), m_exec.targetCount(),
              m_exec.diagGpuMs(), m_exec.diagGpuFallos());
        if (m_exec.diagBlitError())
            qWarning("SceneView: error de GL tras componer: 0x%x", m_exec.diagBlitError());
    }

    if (aparte) {
        // Asincrono solo si el reloj ha avanzado: en marcha, un fotograma de
        // retraso no se ve. Con el reloj parado ---un cambio de encaje o de
        // zoom en pausa, el primer fotograma--- se dibuja UNA vez, y en
        // asincrono se veria el anterior hasta el siguiente fotograma, que
        // en pausa no llega nunca.
        m_otra.leer(m_tLeido >= 0 && m_time != m_tLeido);
        m_tLeido = m_time;
        m_otra.salir();
        m_otra.presentar(GLuint(qtFbo));
    }
    if (m_medidaSeg > 0)
        contarMedida(ahoraMs() - t0Medida);

    cb->endExternal();
    cb->endPass();
}
