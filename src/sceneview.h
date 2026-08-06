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
};

class SceneView : public QQuickRhiItem
{
    Q_OBJECT
    // QML entrega Qt.resolvedUrl(), que es una url. Declararla QString
    // obligaba a recortar "file://" a mano; con QUrl lo hace Qt.
    Q_PROPERTY(QUrl planSource READ planSource WRITE setPlanSource NOTIFY planSourceChanged)
    Q_PROPERTY(qreal time READ time WRITE setTime NOTIFY timeChanged)
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    Q_PROPERTY(QString sceneTitle READ sceneTitle NOTIFY sceneTitleChanged)

public:
    explicit SceneView(QQuickItem *parent = nullptr);

    QUrl planSource() const { return m_planSource; }
    void setPlanSource(const QUrl &source);

    qreal time() const { return m_time; }
    void setTime(qreal t);

    QString status() const { return m_status; }
    QString sceneTitle() const { return m_sceneTitle; }

Q_SIGNALS:
    void planSourceChanged();
    void timeChanged();
    void statusChanged();
    void sceneTitleChanged();

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
    QString m_sceneTitle;
};
