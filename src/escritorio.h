// ¿Esta KWin mostrando el escritorio?
//
// Hace falta porque **no se puede deducir del modelo de tareas**. Medido sobre
// Plasma 6.7 / Wayland: al pulsar "Mostrar el escritorio", KWin aparta las
// ventanas pero el modelo las sigue dando con su geometria intacta, sin marcar
// `IsMinimized` ni `IsHidden`, y ademas conserva la ventana activa. La traza
// del momento exacto:
//
//     CachyOS Hello [560,303 800x594]; Dolphin [480,0 960x1168];
//     Google Chrome ACTIVA [0,0 1920x1168]; Konsole [0,0 1920x1168]; ...
//
// Ni una `MIN`, ni una `OCULTA`. Con esos datos la cobertura sale del 100% y el
// fondo se queda congelado justo cuando lo estas mirando. Minimizar de verdad
// si se marca ---`Google Chrome MIN OCULTA`--- asi que el agujero es solo este.
//
// Quien lo sabe es KWin, que lo publica por D-Bus. Se lee al arrancar y se
// escucha su senal de cambio; si KWin no responde ---otro compositor, D-Bus
// caido--- se queda en `false` y el motor se comporta como antes.

#pragma once

#include <QObject>
#include <QPointF>
#include <qqmlintegration.h>

class Escritorio : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    // Cierto mientras KWin tiene el escritorio a la vista.
    Q_PROPERTY(bool mostrandoEscritorio READ mostrandoEscritorio
               NOTIFY mostrandoEscritorioChanged)
    // Si la consulta inicial fallo. Lo mira el HUD: sin esto, "no esta
    // mostrando el escritorio" y "no hemos podido preguntar" se parecen.
    Q_PROPERTY(bool disponible READ disponible NOTIFY mostrandoEscritorioChanged)

public:
    explicit Escritorio(QObject *parent = nullptr);

    bool mostrandoEscritorio() const { return m_mostrando; }
    bool disponible() const { return m_disponible; }

Q_SIGNALS:
    void mostrandoEscritorioChanged();

private Q_SLOTS:
    void alCambiar(bool mostrando);

private:
    bool m_mostrando = false;
    bool m_disponible = false;
};

// Donde esta el cursor en la pantalla, preguntado a KWin.
//
// Un fondo en Wayland solo ve el raton cuando el compositor se lo da, y en este
// escritorio casi nunca se lo da: con cuatro ventanas maximizadas apiladas
// encima, incluso con "Mostrar el escritorio" la ventana del escritorio recibio
// de 1 a 5 posiciones por segundo, todas pegadas al panel, y `hovered` nunca a
// true ---medido con un `HoverHandler` en la escena y otro en la raiz de la
// ventana---. El parallax iba a saltos de segundos. Wallpaper Engine en Windows
// lee el cursor global; aqui quien lo tiene es KWin.
//
// Un script de KWin escucha `workspace.cursorPosChanged` y llama por D-Bus a
// `posicion(x, y)` de este objeto, como mucho una vez cada 8 ms y siempre con la
// ultima. Lo carga este objeto al crearse ---con el nombre unico de esta
// conexion, que es la direccion a la que llamar--- y lo descarga al destruirse;
// uno de un plasmashell anterior se descarga antes por el nombre del script.
// Si KWin no responde, nunca llega una posicion y `SceneView` se queda con el
// `HoverHandler` del QML.
class CursorKWin : public QObject
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.jose.wallpaperengine.Cursor")

public:
    // Una por proceso: los dos fondos de dos escritorios comparten cursor.
    static CursorKWin *instancia();
    ~CursorKWin() override;

public Q_SLOTS:
    // KWin manda enteros (`cursorPos` es un QPoint); con escala fraccional
    // podria mandar reales. D-Bus elige por la firma, asi que van las dos.
    Q_SCRIPTABLE void posicion(double x, double y);
    Q_SCRIPTABLE void posicion(int x, int y);

Q_SIGNALS:
    // Coordenadas globales de KWin, en pixeles logicos.
    void movido(QPointF global);

private:
    explicit CursorKWin(QObject *parent);
    bool m_cargado = false;
};
