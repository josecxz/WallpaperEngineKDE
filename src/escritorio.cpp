#include "escritorio.h"

#include <QDBusConnection>
#include <QDBusInterface>
#include <QDBusReply>
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
