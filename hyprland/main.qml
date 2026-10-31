// El motor como fondo de Hyprland.
//
// En Plasma el fondo es un plugin de wallpaper (plugin/contents/ui/main.qml)
// que vive dentro de plasmashell. Fuera de Plasma no hay plasmashell, asi que
// este QML es el proceso entero: una ventana por monitor, cada una pedida al
// compositor como superficie `wlr-layer-shell` en la capa `background`
// (`org.kde.layershell`, paquete layer-shell-qt), con el mismo `SceneView`.
//
// Lo que en Plasma dan KWin y el modelo de tareas aqui lo da `Hyprland`
// (src/hyprland.cpp): que tapa cada monitor, para la pausa, y donde esta el
// cursor, para el parallax y las particulas que lo siguen.
//
// Lo lanza `wectl start` (o `wectl set`, `wectl shuffle`) como unidad de
// systemd de usuario `wallpaperengine-hyprland`. A mano, para depurar:
//
//   QML_IMPORT_PATH=~/.local/lib/qt6/qml /usr/lib/qt6/bin/qml hyprland/main.qml \
//       -- --plan <plan.txt> [--pausa 0|1|2] [--encaje 0|1|2] [--zoom 1.0]
//          [--color '#0b0b0d'] [--gpu dedicada|integrada] [--fps 60] [--hud]
//
// `wectl` toma `--gpu` de `wectl gpu` y el resto de `opciones` en
// ~/.config/wallpaperengine/hyprland.json.
//
// Las opciones son las del panel de ajustes del plugin de Plasma
// (plugin/contents/config/main.xml), con los mismos valores por defecto.
//
// Cambiar de wallpaper es escribir un plan nuevo en la misma ruta (`make plan`
// o `wectl set`/`shuffle`): el
// `VigiaArchivo` lo ve y se vuelve a crear la escena. Es lo mismo que hace
// `wectl` en Plasma al salir a otro plugin y volver: el SceneView no sabe
// cambiar de plan en caliente, uno nuevo si.

import QtQuick
import QtQuick.Window
import QtQml
import org.kde.layershell 1.0 as LayerShell
import org.jose.wallpaperengine.render

QtObject {
    id: app

    // ── opciones ────────────────────────────────────────────────────────────
    function opcion(nombre, porDefecto) {
        const a = Qt.application.arguments
        const i = a.indexOf("--" + nombre)
        if (i < 0)
            return porDefecto
        if (typeof porDefecto === "boolean")
            return true
        return i + 1 < a.length ? a[i + 1] : porDefecto
    }

    readonly property string plan: {
        const p = opcion("plan", "")
        return p.startsWith("/") ? p : (p ? Qt.resolvedUrl(p).toString().replace("file://", "") : "")
    }
    // Con `--planes <dir>` cada monitor busca su plan propio en
    // `<dir>/<monitor>/plan.txt` y, mientras no lo haya, usa el compartido de
    // `--plan`. Es el modo `independiente` de `wectl pantallas`.
    readonly property string planes: opcion("planes", "")
    readonly property int pausa: parseInt(opcion("pausa", "1"))
    readonly property int encaje: parseInt(opcion("encaje", "0"))
    readonly property real zoom: parseFloat(opcion("zoom", "1"))
    readonly property real despX: parseFloat(opcion("despx", "0"))
    readonly property real despY: parseFloat(opcion("despy", "0"))
    readonly property string color: opcion("color", "#0b0b0d")
    readonly property bool gpuDedicada: opcion("gpu", "dedicada") !== "integrada"
    // Tope de fotogramas por segundo; 0, sin tope (el ritmo del monitor). 60
    // por defecto, como el plugin de Plasma (config/main.xml, `FpsMax`).
    readonly property real fpsMax: parseFloat(opcion("fps", "60"))
    readonly property bool hud: opcion("hud", false)

    property VigiaArchivo vigia: VigiaArchivo { ruta: app.plan }

    Component.onCompleted: {
        if (!app.plan)
            console.warn("hyprland/main.qml: falta --plan <ruta a plan.txt>")
        else
            console.info("WallpaperEngine en Hyprland: plan " + app.plan
                         + (app.planes ? " (y uno por monitor en " + app.planes + ")" : "")
                         + ", pausa "
                         + app.pausa + ", encaje " + app.encaje + ", "
                         + Qt.application.screens.length + " monitor(es)")
    }

    // ── un fondo por monitor ────────────────────────────────────────────────
    property Instantiator fondos: Instantiator {
        model: Qt.application.screens

        delegate: Window {
            id: ventana
            required property var modelData
            screen: modelData
            visible: false
            color: app.color
            title: "WallpaperEngine " + modelData.name

            LayerShell.Window.scope: "wallpaperengine"
            LayerShell.Window.layer: LayerShell.Window.LayerBackground
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom
                                       | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
            // -1: no la empuja ninguna barra; el fondo va de borde a borde.
            LayerShell.Window.exclusionZone: -1
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            // El monitor lo decide layer-shell-qt con SU propiedad, no con
            // `Window.screen`: con solo esa, las dos capas de dos monitores
            // acababan en el primero y el segundo se quedaba sin fondo.
            LayerShell.Window.screen: hypr.pantalla
            LayerShell.Window.wantsToBeOnActiveScreen: false

            // Las propiedades de layer-shell se leen al crear la superficie,
            // asi que se muestra cuando ya estan puestas.
            Component.onCompleted: show()

            Hyprland {
                id: hypr
                monitor: ventana.modelData.name
                modo: app.pausa
            }

            FrameAnimation {
                id: reloj
                running: true
                // `paused` y nunca antes del primer fotograma: ver el porque en
                // plugin/contents/ui/main.qml, que tiene el mismo reloj.
                paused: hypr.tapado && (escena.item ? escena.item.dibujado : false)
            }

            // El plan propio de este monitor, si `wectl` le ha dado uno.
            VigiaArchivo {
                id: propio
                ruta: app.planes ? app.planes + "/" + ventana.modelData.name + "/plan.txt" : ""
            }
            readonly property bool planPropio: app.planes !== "" && propio.existe
            readonly property string plan: planPropio ? propio.ruta : app.plan

            // Se recrea la escena cuando cambia el plan que ESTE monitor usa:
            // un cambio del compartido no toca a los que tienen el suyo.
            Loader {
                id: escena
                anchors.fill: parent
                property string clave: ventana.plan + "#"
                                       + (ventana.planPropio ? propio.version : app.vigia.version)
                onClaveChanged: { active = false; active = true }
                active: ventana.plan !== ""

                sourceComponent: SceneView {
                    planSource: "file://" + ventana.plan
                    time: reloj.elapsedTime
                    encaje: app.encaje
                    zoom: app.zoom
                    desplazamientoX: app.despX
                    desplazamientoY: app.despY
                    gpuDedicada: app.gpuDedicada
                    fpsMax: app.fpsMax
                    colorBarras: app.color

                    // Respaldo: con Hyprland manda CursorHyprland y esto se
                    // ignora. Solo mira, no se queda clics.
                    HoverHandler { id: raton }
                    puntero: Qt.point(raton.point.position.x / Math.max(1, width),
                                      raton.point.position.y / Math.max(1, height))
                    punteroPresente: raton.hovered
                }
            }

            Rectangle {
                visible: app.hud
                anchors { top: parent.top; left: parent.left; margins: 24; topMargin: 48 }
                width: texto.implicitWidth + 32
                height: texto.implicitHeight + 24
                radius: 6
                color: Qt.rgba(0, 0, 0, 0.72)
                Text {
                    id: texto
                    anchors.centerIn: parent
                    font.family: "monospace"
                    font.pixelSize: 14
                    color: "#ffffff"
                    textFormat: Text.PlainText
                    readonly property var e: escena.item
                    text: [
                        "── WallpaperEngine · Hyprland ──",
                        "escena    : " + (e ? e.sceneTitle || "…" : "-"),
                        "motor     : " + (e ? e.status : "-"),
                        "monitor   : " + ventana.modelData.name + " " + ventana.width
                                        + "x" + ventana.height,
                        "gpu       : " + (e && e.msGpu >= 0 ? e.msGpu.toFixed(1) + " ms/fotograma"
                                                            : "sin medida"),
                        "g_Time    : " + reloj.elapsedTime.toFixed(1) + " s"
                                        + (reloj.paused ? " (en pausa)" : ""),
                        "puntero   : " + (e && e.punteroPresente
                                          ? e.puntero.x.toFixed(3) + ", " + e.puntero.y.toFixed(3)
                                          : "fuera"),
                        "tapado    : " + Math.round(hypr.cobertura * 100) + "% · "
                                        + hypr.ventanas + " ventanas · "
                                        + (hypr.disponible ? "" : "SIN IPC de Hyprland"),
                        "            " + hypr.detalle,
                        "plan      : " + (ventana.planPropio ? "propio" : "compartido")
                                        + " · version " + (ventana.planPropio ? propio.version
                                                                              : app.vigia.version)
                    ].join("\n")
                }
            }
        }
    }
}
