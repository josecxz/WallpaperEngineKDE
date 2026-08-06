// El motor corriendo en vivo dentro del plugin de Plasma.
//
// Ya no es un video pre-renderizado: SceneView es un QQuickRhiItem que ejecuta
// el plan de render (24 pases, 63 assets) con OpenGL crudo, fotograma a
// fotograma, sobre una textura que Qt compone en su scene graph. Por eso los
// iconos del escritorio siguen dibujandose encima sin hacer nada especial.
//
// El reloj es el mismo FrameAnimation del hito 0: late una vez por frame
// compuesto y su elapsedTime alimenta g_Time. Cuando el escritorio queda
// oculto Qt deja de componer, el reloj se para y el motor deja de renderizar
// solo, sin logica de pausa.

import QtQuick
import org.kde.plasma.plasmoid
import org.jose.wallpaperengine.render

WallpaperItem {
    id: root

    FrameAnimation {
        id: clock
        running: true
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
                "g_Time       : " + root.num(clock.elapsedTime, 1) + " s"
            ].join("\n")
        }
    }
}
