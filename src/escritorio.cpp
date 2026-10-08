#include "escritorio.h"

#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusInterface>
#include <QDBusReply>
#include <QDir>
#include <QFile>
#include <QStandardPaths>
#include <QVariant>
#include <QtGlobal>

namespace {
constexpr auto SERVICIO = "org.kde.KWin";
constexpr auto RUTA = "/KWin";
constexpr auto INTERFAZ = "org.kde.KWin";
}

Escritorio::Escritorio(QObject *parent)
    : QObject(parent)
{
    auto bus = QDBusConnection::sessionBus();
    if (!bus.isConnected())
        return;

    // La senal primero: si llega una entre la conexion y la lectura, el valor
    // bueno gana igual porque `alCambiar` compara antes de emitir.
    m_disponible = bus.connect(SERVICIO, RUTA, INTERFAZ, "showingDesktopChanged",
                               this, SLOT(alCambiar(bool)));

    QDBusInterface kwin(SERVICIO, RUTA, INTERFAZ, bus);
    if (kwin.isValid()) {
        const QVariant v = kwin.property("showingDesktop");
        if (v.isValid()) {
            m_mostrando = v.toBool();
            m_disponible = true;
        }
    }
    qInfo("Escritorio: KWin %s, mostrando=%d",
          m_disponible ? "responde" : "NO responde", int(m_mostrando));
    if (m_disponible)
        Q_EMIT mostrandoEscritorioChanged();
}

void Escritorio::alCambiar(bool mostrando)
{
    if (mostrando == m_mostrando)
        return;
    m_mostrando = mostrando;
    m_disponible = true;
    qInfo("Escritorio: KWin dice mostrando=%d", int(mostrando));
    Q_EMIT mostrandoEscritorioChanged();
}

// ── el cursor, desde KWin ───────────────────────────────────────────────────

namespace {
constexpr auto RUTA_CURSOR = "/WallpaperEngine/Cursor";
constexpr auto NOMBRE_SCRIPT = "wallpaperengine-cursor";

// %1 es el nombre unico de la conexion de plasmashell en el bus.
constexpr auto SCRIPT = R"js(
var SERVICIO = "%1";
var ultimo = 0;
var espera = new QTimer();
espera.singleShot = true;
espera.interval = 8;
function manda() {
    var p = workspace.cursorPos;
    ultimo = Date.now();
    callDBus(SERVICIO, "/WallpaperEngine/Cursor", "org.jose.wallpaperengine.Cursor",
             "posicion", p.x, p.y);
}
espera.timeout.connect(manda);
workspace.cursorPosChanged.connect(function () {
    if (Date.now() - ultimo >= 8)
        manda();
    else if (!espera.active)
        espera.start();
});
manda();
)js";
}

CursorKWin *CursorKWin::instancia()
{
    static CursorKWin *unica = new CursorKWin(QCoreApplication::instance());
    return unica;
}

CursorKWin::CursorKWin(QObject *parent)
    : QObject(parent)
{
    auto bus = QDBusConnection::sessionBus();
    if (!bus.isConnected())
        return;
    if (!bus.registerObject(QString::fromLatin1(RUTA_CURSOR), this,
                            QDBusConnection::ExportScriptableSlots)) {
        qWarning("CursorKWin: no se pudo registrar %s", RUTA_CURSOR);
        return;
    }
    const QString dir = QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
    const QString ruta = QDir(dir.isEmpty() ? QDir::tempPath() : dir)
                             .filePath(QStringLiteral("wallpaperengine-cursor.js"));
    QFile f(ruta);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        qWarning("CursorKWin: no se puede escribir %s", qPrintable(ruta));
        return;
    }
    f.write(QString::fromLatin1(SCRIPT).arg(bus.baseService()).toUtf8());
    f.close();

    QDBusInterface scripting(QString::fromLatin1(SERVICIO), QStringLiteral("/Scripting"),
                             QStringLiteral("org.kde.kwin.Scripting"), bus);
    if (!scripting.isValid()) {
        qInfo("CursorKWin: KWin no responde; el raton sale del HoverHandler");
        return;
    }
    scripting.call(QStringLiteral("unloadScript"), QString::fromLatin1(NOMBRE_SCRIPT));
    const QDBusReply<int> id = scripting.call(QStringLiteral("loadScript"), ruta,
                                              QString::fromLatin1(NOMBRE_SCRIPT));
    if (!id.isValid() || id.value() < 0) {
        qWarning("CursorKWin: KWin no carga el script: %s", qPrintable(id.error().message()));
        return;
    }
    QDBusInterface script(QString::fromLatin1(SERVICIO),
                          QStringLiteral("/Scripting/Script%1").arg(id.value()),
                          QStringLiteral("org.kde.kwin.Script"), bus);
    script.call(QStringLiteral("run"));
    m_cargado = true;
    qInfo("CursorKWin: el cursor llega de KWin (script %d, servicio %s)", id.value(),
          qPrintable(bus.baseService()));
}

CursorKWin::~CursorKWin()
{
    if (!m_cargado)
        return;
    QDBusInterface scripting(QString::fromLatin1(SERVICIO), QStringLiteral("/Scripting"),
                             QStringLiteral("org.kde.kwin.Scripting"),
                             QDBusConnection::sessionBus());
    if (scripting.isValid())
        scripting.call(QStringLiteral("unloadScript"), QString::fromLatin1(NOMBRE_SCRIPT));
}

void CursorKWin::posicion(double x, double y)
{
    Q_EMIT movido(QPointF(x, y));
}

void CursorKWin::posicion(int x, int y)
{
    Q_EMIT movido(QPointF(x, y));
}
