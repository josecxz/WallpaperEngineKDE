// SceneView: el puente entre QML y nuestro renderizador GL.
//
// QQuickRhiItem nos da una textura propia sobre la que pintar; Qt la compone
// como un nodo mas del scene graph, asi que el z-order (iconos del escritorio
// encima), la opacidad y el redimensionado siguen funcionando solos.
//
// El render corre en OTRO HILO. `synchronize()` es el unico punto en que los
// dos estan parados: ahi se copia el estado del item al renderizador. Tocar el
// item desde `render()` seria una condicion de carrera.

#pragma once

#include <QColor>
#include <QQuickRhiItem>
#include <QString>
#include <QUrl>

#include "glexecutor.h"

class SceneRenderer : public QQuickRhiItemRenderer
{
public:
    SceneRenderer() = default;
    // Contiene un GlExecutor, que posee handles de GL y no es copiable.
    SceneRenderer(const SceneRenderer &) = delete;
    SceneRenderer &operator=(const SceneRenderer &) = delete;

    void initialize(QRhiCommandBuffer *cb) override;
    void synchronize(QQuickRhiItem *item) override;
    void render(QRhiCommandBuffer *cb) override;

private:
    GlExecutor m_exec;
    QString m_planPath;      // copiado en synchronize()
    float m_time = 0.0f;
    bool m_planLoaded = false;
    bool m_failed = false;
    bool m_diagDone = false;
    int m_reportedPhase = -1;   // evita rehacer el estado en cada fotograma
    // Copiados en synchronize() como todo lo demas: el encaje se puede cambiar
    // desde la UI de configuracion mientras el hilo de render esta dibujando.
    int m_encaje = 0;
    float m_zoom = 1.0f, m_despX = 0.0f, m_despY = 0.0f;
    float m_bar[3] = {0.0f, 0.0f, 0.0f};
};

class SceneView : public QQuickRhiItem
{
    Q_OBJECT
    // QML entrega Qt.resolvedUrl(), que es una url. Declararla QString
    // obligaba a recortar "file://" a mano; con QUrl lo hace Qt.
    Q_PROPERTY(QUrl planSource READ planSource WRITE setPlanSource NOTIFY planSourceChanged)
    Q_PROPERTY(qreal time READ time WRITE setTime NOTIFY timeChanged)
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    // Si el plan ya esta cargado y se ha dibujado al menos un fotograma. Lo
    // necesita QML para no pausar el reloj ANTES del primer fotograma: sin
    // reloj no hay `time` que cambie, sin cambio de `time` no hay `update()`,
    // y el plan no llega a cargarse nunca --- el fondo se queda negro en vez
    // de congelado.
    Q_PROPERTY(bool dibujado READ dibujado NOTIFY statusChanged)
    Q_PROPERTY(QString sceneTitle READ sceneTitle NOTIFY sceneTitleChanged)
    // Encaje del lienzo en la pantalla: 0 cubrir, 1 encajar entero, 2 estirar.
    // Ver GlExecutor::Encaje, que es quien define los valores.
    Q_PROPERTY(int encaje READ encaje WRITE setEncaje NOTIFY encajeChanged)
    Q_PROPERTY(qreal zoom READ zoom WRITE setZoom NOTIFY encajeChanged)
    Q_PROPERTY(qreal desplazamientoX READ desplazamientoX WRITE setDesplazamientoX
               NOTIFY encajeChanged)
    Q_PROPERTY(qreal desplazamientoY READ desplazamientoY WRITE setDesplazamientoY
               NOTIFY encajeChanged)
    // Color de las barras cuando la escena no llena la pantalla.
    Q_PROPERTY(QColor colorBarras READ colorBarras WRITE setColorBarras
               NOTIFY encajeChanged)

public:
    explicit SceneView(QQuickItem *parent = nullptr);

    QUrl planSource() const { return m_planSource; }
    void setPlanSource(const QUrl &source);

    qreal time() const { return m_time; }
    void setTime(qreal t);

    QString status() const { return m_status; }
    bool dibujado() const { return m_dibujado; }
    QString sceneTitle() const { return m_sceneTitle; }

    int encaje() const { return m_encaje; }
    qreal zoom() const { return m_zoom; }
    qreal desplazamientoX() const { return m_despX; }
    qreal desplazamientoY() const { return m_despY; }
    QColor colorBarras() const { return m_colorBarras; }
    void setEncaje(int v);
    void setZoom(qreal v);
    void setDesplazamientoX(qreal v);
    void setDesplazamientoY(qreal v);
    void setColorBarras(const QColor &c);

Q_SIGNALS:
    void planSourceChanged();
    void timeChanged();
    void statusChanged();
    void sceneTitleChanged();
    // Una sola senal para los cinco: van juntos a la misma cuenta y quien los
    // mira ---el HUD--- los enseña en la misma linea.
    void encajeChanged();

protected:
    QQuickRhiItemRenderer *createRenderer() override;

private Q_SLOTS:
    // Solo para que el hilo de render publique estado por QMetaObject. Siguen
    // siendo invocables por nombre siendo privados, y asi no aparecen en la
    // API que ve QML.
    void setStatusFromRenderer(const QString &s);
    void setSceneTitleFromRenderer(const QString &t);

private:
    // El renderizador lee estos campos solo desde synchronize(), que es el
    // unico punto en que los dos hilos estan parados.
    friend class SceneRenderer;
    QUrl m_planSource;
    QString m_planPath;
    qreal m_time = 0.0;
    QString m_status = QStringLiteral("sin inicializar");
    bool m_dibujado = false;
    QString m_sceneTitle;
    int m_encaje = 0;                        // GlExecutor::Cubrir
    qreal m_zoom = 1.0;
    qreal m_despX = 0.0, m_despY = 0.0;
    QColor m_colorBarras = QColor(0, 0, 0);
};
