#include "hyprland.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

#include <sys/stat.h>

namespace hypr {

QString rutaSocket(const char *nombre)
{
    const QByteArray firma = qgetenv("HYPRLAND_INSTANCE_SIGNATURE");
    if (firma.isEmpty())
        return {};
    // Desde 0.40 viven en el runtime dir; antes, en /tmp/hypr.
    const QByteArray xdg = qgetenv("XDG_RUNTIME_DIR");
    const QString sub = QStringLiteral("hypr/%1/%2")
                            .arg(QString::fromLocal8Bit(firma), QString::fromLatin1(nombre));
    if (!xdg.isEmpty()) {
        const QString r = QDir(QString::fromLocal8Bit(xdg)).filePath(sub);
        if (QFileInfo::exists(r))
            return r;
    }
    const QString viejo = QStringLiteral("/tmp/") + sub;
    return QFileInfo::exists(viejo) ? viejo : QString();
}

// Peticion sincrona: solo para la revision, que va agrupada y es rara. El
// cursor, que va cada 16 ms, pregunta de forma asincrona.
static QByteArray pedir(const QString &ruta, const QByteArray &orden)
{
    QLocalSocket s;
    s.connectToServer(ruta);
    if (!s.waitForConnected(200))
        return {};
    s.write(orden);
    if (!s.waitForBytesWritten(200))
        return {};
    QByteArray r;
    // Hyprland cierra al terminar de responder.
    while (s.state() == QLocalSocket::ConnectedState && s.waitForReadyRead(300))
        r += s.readAll();
    r += s.readAll();
    return r;
}

}  // namespace hypr

// ── tapado ──────────────────────────────────────────────────────────────────

namespace {
// Los mismos numeros que VentanasEncima.qml, por la misma razon.
constexpr int COLS = 32;
constexpr int FILAS = 18;
constexpr qreal UMBRAL = 0.92;

// Eventos que no cambian que se ve: el titulo de una terminal cambia a cada
// orden y no merece una revision.
bool irrelevante(const QByteArray &evento)
{
    return evento.startsWith("windowtitle") || evento.startsWith("activelayout")
        || evento.startsWith("submap") || evento.startsWith("screencast")
        || evento.startsWith("bell");
}
}  // namespace

Hyprland::Hyprland(QObject *parent)
    : QObject(parent)
{
    m_disponible = !hypr::rutaSocket(".socket.sock").isEmpty();
    if (!m_disponible)
        return;

    m_pendiente.setSingleShot(true);
    m_pendiente.setInterval(40);
    connect(&m_pendiente, &QTimer::timeout, this, &Hyprland::revisar);

    m_repaso.setInterval(2000);
    connect(&m_repaso, &QTimer::timeout, this, &Hyprland::revisar);
    m_repaso.start();

    m_reconectar.setSingleShot(true);
    m_reconectar.setInterval(1000);
    connect(&m_reconectar, &QTimer::timeout, this, &Hyprland::conectarEventos);

    connect(&m_eventos, &QLocalSocket::readyRead, this, &Hyprland::alLeerEventos);
    connect(&m_eventos, &QLocalSocket::disconnected, &m_reconectar,
            qOverload<>(&QTimer::start));
    connect(&m_eventos, &QLocalSocket::errorOccurred, &m_reconectar,
            [this](QLocalSocket::LocalSocketError) { m_reconectar.start(); });
    conectarEventos();
    m_pendiente.start();
}

Hyprland::~Hyprland()
{
    CursorHyprland::instancia()->quiere(this, false);
}

void Hyprland::conectarEventos()
{
    const QString ruta = hypr::rutaSocket(".socket2.sock");
    if (ruta.isEmpty())
        return;
    m_eventos.abort();
    m_resto.clear();
    m_eventos.connectToServer(ruta, QIODevice::ReadOnly);
}

void Hyprland::alLeerEventos()
{
    m_resto += m_eventos.readAll();
    bool algo = false;
    qsizetype fin;
    while ((fin = m_resto.indexOf('\n')) >= 0) {
        const QByteArray linea = m_resto.left(fin);
        m_resto.remove(0, fin + 1);
        if (!irrelevante(linea))
            algo = true;
    }
    if (algo && !m_pendiente.isActive())
        m_pendiente.start();
}

void Hyprland::setMonitor(const QString &m)
{
    if (m == m_monitor)
        return;
    m_monitor = m;
    Q_EMIT monitorChanged();
    if (m_disponible)
        m_pendiente.start();
}

void Hyprland::setModo(int m)
{
    if (m == m_modo)
        return;
    m_modo = m;
    Q_EMIT modoChanged();
    if (m_disponible)
        m_pendiente.start();
    else
        CursorHyprland::instancia()->quiere(this, false);
}

void Hyprland::revisar()
{
    const QString ruta = hypr::rutaSocket(".socket.sock");
    if (ruta.isEmpty())
        return;
    const QJsonArray monitores =
        QJsonDocument::fromJson(hypr::pedir(ruta, "j/monitors")).array();
    const QJsonArray clientes = QJsonDocument::fromJson(hypr::pedir(ruta, "j/clients")).array();

    // El monitor de este fondo.
    QJsonObject mon;
    for (const auto &v : monitores) {
        const QJsonObject o = v.toObject();
        if (m_monitor.isEmpty() ? o.value("focused").toBool()
                                : o.value("name").toString() == m_monitor) {
            mon = o;
            break;
        }
    }
    if (mon.isEmpty())
        return;

    // Pixeles fisicos -> logicos. `x`/`y` y las ventanas ya vienen en logicos;
    // el ancho y el alto no, y con rotacion de 90/270 van cambiados.
    const qreal escala = qMax(0.1, mon.value("scale").toDouble(1.0));
    qreal ancho = mon.value("width").toDouble() / escala;
    qreal alto = mon.value("height").toDouble() / escala;
    if (mon.value("transform").toInt() % 2 == 1)
        std::swap(ancho, alto);
    const QJsonArray res = mon.value("reserved").toArray();
    // Area util: la pantalla menos lo que reservan las barras (izq, arr, der, abj).
    const QRectF util(mon.value("x").toDouble() + res.at(0).toDouble(),
                      mon.value("y").toDouble() + res.at(1).toDouble(),
                      ancho - res.at(0).toDouble() - res.at(2).toDouble(),
                      alto - res.at(1).toDouble() - res.at(3).toDouble());
    const int idMon = mon.value("id").toInt(-1);
    const QJsonValue activo = mon.value("activeWorkspace").toObject().value("id");
    const QString especial = mon.value("specialWorkspace").toObject().value("name").toString();

    QList<QRectF> cajas;
    QStringList nombres;
    for (const auto &v : clientes) {
        const QJsonObject c = v.toObject();
        if (!c.value("mapped").toBool(true) || c.value("hidden").toBool(false))
            continue;
        if (c.value("monitor").toInt(-2) != idMon)
            continue;
        const QJsonObject ws = c.value("workspace").toObject();
        const bool enActivo = ws.value("id") == activo;
        const bool enEspecial = !especial.isEmpty() && ws.value("name").toString() == especial;
        if (!enActivo && !enEspecial && !c.value("pinned").toBool(false))
            continue;
        const QJsonArray at = c.value("at").toArray();
        const QJsonArray tam = c.value("size").toArray();
        const QRectF g(at.at(0).toDouble(), at.at(1).toDouble(), tam.at(0).toDouble(),
                       tam.at(1).toDouble());
        if (g.isEmpty())
            continue;
        cajas.append(g);
        if (nombres.size() < 3)
            nombres.append(c.value("class").toString());
    }

    qreal cobertura = 0;
    if (!cajas.isEmpty() && !util.isEmpty()) {
        int tapadas = 0;
        for (int f = 0; f < FILAS; f++) {
            const qreal cy = util.y() + (f + 0.5) / FILAS * util.height();
            for (int c = 0; c < COLS; c++) {
                const qreal cx = util.x() + (c + 0.5) / COLS * util.width();
                for (const QRectF &b : std::as_const(cajas)) {
                    if (cx >= b.left() && cx < b.right() && cy >= b.top() && cy < b.bottom()) {
                        tapadas++;
                        break;
                    }
                }
            }
        }
        cobertura = qreal(tapadas) / (COLS * FILAS);
    }

    const bool tapado = m_modo == 2   ? !cajas.isEmpty()
                        : m_modo == 1 ? cobertura >= UMBRAL
                                      : false;
    const QString detalle = mon.value("name").toString() + " ws "
                            + QString::number(activo.toInt())
                            + (especial.isEmpty() ? QString() : QStringLiteral(" +") + especial)
                            + "  tapan: " + (nombres.isEmpty() ? QStringLiteral("-")
                                                               : nombres.join(", "));
    const bool cambio = tapado != m_tapado;
    if (cambio)
        qInfo("Hyprland: %s con %d%% tapado en %s, %d ventanas visibles",
              tapado ? "en pausa" : "dibujando", int(cobertura * 100 + 0.5),
              qPrintable(mon.value("name").toString()), int(cajas.size()));
    if (cambio || !qFuzzyCompare(1 + cobertura, 1 + m_cobertura)
        || cajas.size() != m_ventanas || detalle != m_detalle) {
        m_tapado = tapado;
        m_cobertura = cobertura;
        m_ventanas = int(cajas.size());
        m_detalle = detalle;
        Q_EMIT estadoChanged();
    }
    CursorHyprland::instancia()->quiere(this, !m_tapado);
}

// ── cursor ──────────────────────────────────────────────────────────────────

CursorHyprland *CursorHyprland::instancia()
{
    static CursorHyprland *unica = new CursorHyprland(QCoreApplication::instance());
    return unica;
}

CursorHyprland::CursorHyprland(QObject *parent)
    : QObject(parent)
    , m_ruta(hypr::rutaSocket(".socket.sock"))
{
    if (m_ruta.isEmpty())
        return;
    m_reloj.setInterval(16);
    connect(&m_reloj, &QTimer::timeout, this, &CursorHyprland::preguntar);
    qInfo("CursorHyprland: el cursor llega de Hyprland (%s)", qPrintable(m_ruta));
}

void CursorHyprland::quiere(const QObject *quien, bool si)
{
    if (si)
        m_quieren.insert(quien);
    else
        m_quieren.remove(quien);
    if (m_ruta.isEmpty())
        return;
    if (m_quieren.isEmpty())
        m_reloj.stop();
    else if (!m_reloj.isActive())
        m_reloj.start();
}

void CursorHyprland::preguntar()
{
    // Una a la vez: si Hyprland tarda, se salta el tick en vez de apilar.
    if (m_peticion)
        return;
    m_peticion = new QLocalSocket(this);
    m_respuesta.clear();
    connect(m_peticion, &QLocalSocket::connected, m_peticion,
            [s = m_peticion] { s->write("j/cursorpos"); });
    connect(m_peticion, &QLocalSocket::readyRead, m_peticion,
            [this] { m_respuesta += m_peticion->readAll(); });
    auto terminar = [this] {
        if (!m_peticion)
            return;
        m_respuesta += m_peticion->readAll();
        m_peticion->deleteLater();
        m_peticion = nullptr;
        const QJsonObject o = QJsonDocument::fromJson(m_respuesta).object();
        if (!o.contains("x"))
            return;
        const QPointF p(o.value("x").toDouble(), o.value("y").toDouble());
        if (p == m_ultimo)
            return;
        m_ultimo = p;
        Q_EMIT movido(p);
    };
    connect(m_peticion, &QLocalSocket::disconnected, this, terminar);
    connect(m_peticion, &QLocalSocket::errorOccurred, this,
            [terminar](QLocalSocket::LocalSocketError) { terminar(); });
    m_peticion->connectToServer(m_ruta);
}

// ── vigia del plan ──────────────────────────────────────────────────────────

VigiaArchivo::VigiaArchivo(QObject *parent)
    : QObject(parent)
{
    m_calma.setSingleShot(true);
    m_calma.setInterval(300);
    connect(&m_calma, &QTimer::timeout, this, &VigiaArchivo::comprobar);
    auto otra = [this] { m_calma.start(); };
    connect(&m_vigia, &QFileSystemWatcher::directoryChanged, this, otra);
    connect(&m_vigia, &QFileSystemWatcher::fileChanged, this, otra);
}

void VigiaArchivo::setRuta(const QString &r)
{
    if (r == m_ruta)
        return;
    m_ruta = r;
    Q_EMIT rutaChanged();
    struct stat st{};
    if (::stat(QFile::encodeName(m_ruta).constData(), &st) == 0)
        m_inodo = st.st_ino;
    m_fecha = QFileInfo(m_ruta).lastModified();
    vigilar();
}

void VigiaArchivo::vigilar()
{
    if (!m_vigia.files().isEmpty())
        m_vigia.removePaths(m_vigia.files());
    if (!m_vigia.directories().isEmpty())
        m_vigia.removePaths(m_vigia.directories());
    if (m_ruta.isEmpty())
        return;
    const QFileInfo f(m_ruta);
    const QString dir = f.absolutePath();
    QStringList rutas{QFileInfo(dir).absolutePath(), dir};
    if (f.exists())
        rutas.append(f.absoluteFilePath());
    for (const QString &r : std::as_const(rutas))
        if (QFileInfo::exists(r))
            m_vigia.addPath(r);
}

void VigiaArchivo::comprobar()
{
    // Tras un rename las rutas vigiladas apuntan a inodos que ya no estan.
    vigilar();
    struct stat st{};
    if (::stat(QFile::encodeName(m_ruta).constData(), &st) != 0)
        return;   // a medio cambiar: el siguiente aviso lo vera entero
    const QDateTime fecha = QFileInfo(m_ruta).lastModified();
    if (quint64(st.st_ino) == m_inodo && fecha == m_fecha)
        return;
    m_inodo = st.st_ino;
    m_fecha = fecha;
    m_version++;
    qInfo("VigiaArchivo: %s ha cambiado (version %d)", qPrintable(m_ruta), m_version);
    Q_EMIT versionChanged();
}
