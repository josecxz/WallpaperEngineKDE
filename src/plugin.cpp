// Plugin de extension QML: registra SceneView para que main.qml pueda usarlo.

#include <QQmlExtensionPlugin>
#include <qqml.h>

#include "escritorio.h"
#include "sceneview.h"

class WallpaperEnginePlugin : public QQmlExtensionPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QQmlExtensionInterface_iid)

public:
    void registerTypes(const char *uri) override
    {
        qmlRegisterType<SceneView>(uri, 1, 0, "SceneView");
        qmlRegisterType<Escritorio>(uri, 1, 0, "Escritorio");
    }
};

#include "plugin.moc"
