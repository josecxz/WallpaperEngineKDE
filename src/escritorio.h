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
