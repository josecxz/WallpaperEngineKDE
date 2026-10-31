// El fondo fuera de Plasma: lo que en KDE dan KWin y el modelo de tareas, en
// Hyprland se le pregunta a Hyprland por su socket de IPC.
//
// Hyprland publica dos sockets en `$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/`:
//
//   .socket.sock   peticiones: se conecta, se escribe `j/clients`, se lee un
//                  JSON y Hyprland cierra. Es lo mismo que hace `hyprctl -j`.
//   .socket2.sock  eventos: una linea `EVENTO>>DATOS` por cada cosa que pasa
//                  (`workspace>>2`, `openwindow>>...`, `fullscreen>>1`).
//
// Nada de esto se usa si `HYPRLAND_INSTANCE_SIGNATURE` no esta definida: en
// Plasma los objetos se quedan en `disponible = false` y no hacen nada.

#pragma once

#include <QDateTime>
#include <QFileSystemWatcher>
#include <QLocalSocket>
#include <QObject>
#include <QPointF>
#include <QRectF>
#include <QScreen>
#include <QSet>
#include <QTimer>
#include <qqmlintegration.h>

namespace hypr {
// Ruta de un socket de esta instancia de Hyprland; vacia si no hay Hyprland.
QString rutaSocket(const char *nombre);
}

// ¿Hay algo tapando el fondo en ESTE monitor?
//
// Es el `VentanasEncima.qml` de Plasma con otra fuente: mismo modo, misma
// rejilla de 32x18 y mismo umbral del 92 % contra el area util (la pantalla
// sin la zona reservada por las barras). En Hyprland es mas facil que en KWin:
// una ventana se ve si esta en el espacio de trabajo activo del monitor, o en
// su espacio especial abierto, o fijada (`pinned`), y no hay "Mostrar el
// escritorio" ni minimizar que el modelo no refleje.
class Hyprland : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(bool disponible READ disponible CONSTANT)
    // Nombre del monitor (`eDP-1`), el `Screen.name` del QML. Vacio: el que
    // tenga el foco.
    Q_PROPERTY(QString monitor READ monitor WRITE setMonitor NOTIFY monitorChanged)
    // El QScreen de ese monitor, para `Window.screen` y `LayerShell.Window.screen`.
    // Hace falta porque `Qt.application.screens` da `QQuickScreenInfo`, que
    // ninguna de las dos acepta: sin esto todas las capas iban al primer monitor.
    Q_PROPERTY(QScreen *pantalla READ pantalla NOTIFY monitorChanged)
    // 0 nunca, 1 cuando lo visible tapa la pantalla, 2 con cualquier ventana.
    Q_PROPERTY(int modo READ modo WRITE setModo NOTIFY modoChanged)
    Q_PROPERTY(bool tapado READ tapado NOTIFY estadoChanged)
    Q_PROPERTY(qreal cobertura READ cobertura NOTIFY estadoChanged)
    Q_PROPERTY(int ventanas READ ventanas NOTIFY estadoChanged)
    Q_PROPERTY(QString detalle READ detalle NOTIFY estadoChanged)

public:
    explicit Hyprland(QObject *parent = nullptr);
    ~Hyprland() override;

    bool disponible() const { return m_disponible; }
    QString monitor() const { return m_monitor; }
    void setMonitor(const QString &m);
    QScreen *pantalla() const;
    int modo() const { return m_modo; }
    void setModo(int m);
    bool tapado() const { return m_tapado; }
    qreal cobertura() const { return m_cobertura; }
    int ventanas() const { return m_ventanas; }
    QString detalle() const { return m_detalle; }

Q_SIGNALS:
    void monitorChanged();
    void modoChanged();
    void estadoChanged();

private:
    void conectarEventos();
    void alLeerEventos();
    void revisar();

    bool m_disponible = false;
    QString m_monitor;
    int m_modo = 1;
    bool m_tapado = false;
    qreal m_cobertura = 0;
    int m_ventanas = 0;
    QString m_detalle;

    QLocalSocket m_eventos;
    QByteArray m_resto;
    QTimer m_pendiente;   // agrupa una rafaga de eventos en una revision
    QTimer m_repaso;      // red de seguridad, como el Timer de VentanasEncima
    QTimer m_reconectar;
};

// Donde esta el cursor, preguntado a Hyprland.
//
// El mismo problema que `CursorKWin` (escritorio.h): una superficie de fondo
// solo recibe el raton cuando no hay nada encima. Hyprland no emite eventos de
// cursor por `.socket2.sock`, asi que se pregunta `j/cursorpos` cada 16 ms, de
// forma asincrona para no bloquear nunca el hilo de la GUI, y solo se avisa
// cuando cambia. Mientras todos los fondos esten tapados no se pregunta.
class CursorHyprland : public QObject
{
    Q_OBJECT

public:
    static CursorHyprland *instancia();
    // Un fondo dice si le hace falta el raton (no lo necesita tapado).
    void quiere(const QObject *quien, bool si);

Q_SIGNALS:
    // Coordenadas globales del layout de Hyprland, en pixeles logicos: las
    // mismas que `QScreen::geometry()` en Wayland.
    void movido(QPointF global);

private:
    explicit CursorHyprland(QObject *parent);
    void preguntar();

    QString m_ruta;
    QTimer m_reloj;
    QLocalSocket *m_peticion = nullptr;
    QByteArray m_respuesta;
    QPointF m_ultimo{-1e9, -1e9};
    QSet<const QObject *> m_quieren;
};

// Avisa cuando cambia un fichero, tambien si se sustituye por un rename del
// directorio que lo contiene ---que es como `wectl` cambia el plan: escribe
// `scene.nueva/` y la renombra a `scene/`---. `QFileSystemWatcher` pierde el
// fichero en cuanto su inodo desaparece, asi que se vigila el directorio padre
// del padre y se compara la fecha del fichero.
class VigiaArchivo : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString ruta READ ruta WRITE setRuta NOTIFY rutaChanged)
    // Sube en uno cada vez que el fichero cambia de verdad.
    Q_PROPERTY(int version READ version NOTIFY versionChanged)

public:
    explicit VigiaArchivo(QObject *parent = nullptr);

    QString ruta() const { return m_ruta; }
    void setRuta(const QString &r);
    int version() const { return m_version; }

Q_SIGNALS:
    void rutaChanged();
    void versionChanged();

private:
    void vigilar();
    void comprobar();

    QString m_ruta;
    int m_version = 0;
    QDateTime m_fecha;
    quint64 m_inodo = 0;
    QFileSystemWatcher m_vigia;
    QTimer m_calma;   // el rename llega en varias senales; se espera a que pare
};
