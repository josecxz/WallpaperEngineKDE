// El motor corriendo en vivo dentro del plugin de Plasma.
//
// Ya no es un video pre-renderizado: SceneView es un QQuickRhiItem que ejecuta
// el plan de render (24 pases, 63 assets) con OpenGL crudo, fotograma a
// fotograma, sobre una textura que Qt compone en su scene graph. Por eso los
// iconos del escritorio siguen dibujandose encima sin hacer nada especial.
//
// El reloj es el mismo FrameAnimation del hito 0: late una vez por frame
// compuesto y su elapsedTime alimenta g_Time. Parar ese reloj es lo unico que
// hace falta para parar el motor: `SceneView` solo pide un fotograma nuevo
// cuando `time` cambia, asi que sin reloj no hay pases que ejecutar --- Qt
// sigue componiendo la ultima textura, que no cuesta nada.
//
// Antes aqui ponia que con el escritorio tapado Qt deja de componer y el motor
// se para solo. Nunca se comprobo. Lo que si esta medido es el coste cuando
// dibuja: la escena mas pesada del corpus se come el 92% del motor de render de
// la iGPU, en continuo, y con una ventana maximizada encima no se ve ni un
// pixel de ella. Asi que la pausa se pide explicitamente en vez de confiar en
// que alguien la haga por nosotros.

import QtQuick
import QtQuick.Window
import org.kde.plasma.plasmoid
import org.jose.wallpaperengine.render

WallpaperItem {
    id: root

    // Quien vigila si hay algo encima. `Screen` da la pantalla de ESTE fondo,
    // que es lo que hace falta para no pararlo por un maximizado en otro
    // monitor; `WallpaperItem` no expone la geometria de su pantalla.
    VentanasEncima {
        id: ventanas
        modo: root.configuration.PauseMode
        geometriaPantalla: Qt.rect(Screen.virtualX, Screen.virtualY,
                                   Screen.width, Screen.height)
    }

    FrameAnimation {
        id: clock
        running: true
        // `paused`, no `running`. Parar la animacion y volver a arrancarla la
        // reinicia --- `elapsedTime` vuelve a cero --- y ademas deja el reloj
        // en un estado del que no siempre vuelve: el fondo se quedaba
        // congelado al destapar el escritorio. En pausa el tiempo se queda
        // quieto y al reanudar sigue donde estaba, que es lo que se queria.
        //
        // Que se quede quieto tambien protege al simulador: un salto de varios
        // minutos en `g_Time` le pediria simular hasta el tope de 60 s de una
        // sentada --- 3600 pasos por sistema --- dentro del hilo de render.
        // NUNCA antes del primer fotograma. Pausar de entrada deja el fondo
        // NEGRO, no congelado: sin reloj no cambia `time`, sin cambio de
        // `time` no hay `update()`, y el plan no llega a cargarse. Pasa de
        // verdad --- basta arrancar la sesion con una ventana ya maximizada.
        paused: ventanas.tapado && escena.dibujado
    }

    readonly property real fps: clock.smoothFrameTime > 0 ? 1.0 / clock.smoothFrameTime : 0

    function num(v, dec) {
        return (typeof v === "number" && !isNaN(v)) ? v.toFixed(dec) : "n/d"
    }

    // Se ve mientras el primer fotograma no ha llegado.
    Rectangle {
        anchors.fill: parent
        color: root.configuration.Color || "#0b0b0d"
    }

    SceneView {
        id: escena
        anchors.fill: parent
        planSource: Qt.resolvedUrl("../scene/plan.txt")
        // La animacion se deriva del tiempo, no de un contador de frames, para
        // que la velocidad no dependa del refresco de la pantalla.
        time: clock.elapsedTime
    }

    Rectangle {
        visible: root.configuration.ShowDiagnostics
        anchors {
            top: parent.top
            left: parent.left
            margins: 24
        }
        width: hud.implicitWidth + 32
        height: hud.implicitHeight + 24
        radius: 6
        color: Qt.rgba(0, 0, 0, 0.72)

        Text {
            id: hud
            anchors.centerIn: parent
            font.family: "monospace"
            font.pixelSize: 14
            color: "#ffffff"
            textFormat: Text.PlainText
            text: [
                "── WallpaperEngine · en vivo ──",
                "escena       : " + (escena.sceneTitle || "…"),
                "renderizador : " + escena.status,
                "",
                "superficie   : " + root.width + "x" + root.height,
                "fps          : " + root.num(root.fps, 1),
                "g_Time       : " + root.num(clock.elapsedTime, 1) + " s",
                "estado       : " + (ventanas.tapado ? "en pausa (tapado)" : "dibujando"),
                "reloj        : " + (clock.paused ? "en pausa" : "corriendo")
                                  + " · dibujado " + escena.dibujado,
                "ventanas     : " + ventanas.ventanas + " · tapan "
                                  + ventanas.maximizadas + " · fuera "
                                  + ventanas.ocultas,
                "tapan        : " + ventanas.detalle
            ].join("\n")
        }
    }
}
