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
//          [--solo eDP-1,HDMI-A-3]
//
// `wectl` toma `--gpu` de `wectl gpu` y el resto de `opciones` en
// ~/.config/wallpaperengine/hyprland.json.
//
// Las opciones son las del panel de ajustes del plugin de Plasma
// (plugin/contents/config/main.xml), con los mismos valores por defecto.
//
// Cambiar de wallpaper es escribir un plan nuevo en la misma ruta (`make plan`
// o `wectl set`/`shuffle`): el
// `VigiaArchivo` lo ve y se crea una escena nueva, igual que `Escenas.qml` en
// Plasma: el SceneView no sabe cambiar de plan en caliente, uno nuevo si. La
// nueva se carga DEBAJO de la
// que se ve y la vieja no se suelta hasta que la nueva ha dibujado: ver
// NOTAS, «La recarga del plan».

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
    // `--solo eDP-1,HDMI-A-3`: fondo solo en esos monitores. Para medir lo
    // que cuesta cada pantalla sin desenchufar ninguna.
    readonly property var solo: opcion("solo", "") ? opcion("solo", "").split(",") : []

    property VigiaArchivo vigia: VigiaArchivo { ruta: app.plan }

    // La `url` de un plan web (`web <url>`, de `werender.plan_de_web`), o ""
    // si es una escena o un video. Se lee el plan con un XHR sincrono:
    // `wectl` arranca el fondo con `QML_XHR_ALLOW_FILE_READ=1`.
    // `Web.qml` se compila solo cuando hace falta: sin `qt6-webengine`, su
    // `import QtWebEngine` falla, y asi solo fallan los web.
    // Un objeto y no una propiedad: guardarlo en una propiedad que lee el
    // binding de `sourceComponent` era un bucle de bindings.
    readonly property var _cache: ({})
    function componenteWeb() {
        if (!_cache.web) {
            _cache.web = Qt.createComponent(Qt.resolvedUrl("Web.qml"))
            if (_cache.web.status === Component.Error)
                console.warn("hyprland/main.qml: " + _cache.web.errorString())
        }
        return _cache.web
    }

    function urlWeb(ruta) {
        if (!ruta)
            return ""
        const xhr = new XMLHttpRequest()
        try {
            xhr.open("GET", "file://" + ruta, false)
            xhr.send()
        } catch (e) {
            return ""
        }
        for (const linea of (xhr.responseText || "").split("\n"))
            if (linea.startsWith("web "))
                return linea.substring(4).trim()
        return ""
    }

    Component.onCompleted: {
        app.sincronizarMonitores()
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
    //
    // El modelo son los NOMBRES de los monitores, y al enchufar o
    // desenchufar uno solo se añade o se quita ese. Con
    // `Qt.application.screens` de modelo, un array de JS, el `Instantiator`
    // rehacia todos los fondos y recargaba todas las escenas. Ver NOTAS,
    // «Enchufar un monitor recargaba los de todos».
    property ListModel monitores: ListModel {}
    function sincronizarMonitores() {
        // Sin nombre todavia no se sabe que monitor es; ya llegara otro aviso.
        const nombres = Qt.application.screens.map(pantalla => pantalla.name)
            .filter(nombre => nombre && (!app.solo.length || app.solo.indexOf(nombre) >= 0))
        for (let i = monitores.count - 1; i >= 0; i--)
            if (nombres.indexOf(monitores.get(i).nombre) < 0)
                monitores.remove(i)
        const hay = []
        for (let i = 0; i < monitores.count; i++)
            hay.push(monitores.get(i).nombre)
        for (const nombre of nombres)
            if (hay.indexOf(nombre) < 0)
                monitores.append({ nombre: nombre })
    }
    property Connections pantallas: Connections {
        target: Qt.application
        function onScreensChanged() { app.sincronizarMonitores() }
    }

    property Instantiator fondos: Instantiator {
        model: app.monitores

        delegate: Window {
            id: ventana
            required property string nombre
            // La pantalla de QML (`QQuickScreenInfo`): el `QScreen` de
            // `hypr.pantalla` aqui no se puede asignar.
            screen: Qt.application.screens.find(pantalla => pantalla.name === ventana.nombre) ?? null
            visible: false
            color: app.color
            title: "WallpaperEngine " + ventana.nombre

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
            Component.onCompleted: {
                show()
                // El `onClaveChanged` de la creacion puede haberla cargado
                // ya; cargarla otra vez era subir las texturas dos veces.
                if (!huecoA.active && !huecoB.active) {
                    ventana.fijar(huecoA)
                    huecoA.active = ventana.plan !== ""
                }
            }

            Hyprland {
                id: hypr
                monitor: ventana.nombre
                modo: app.pausa
            }

            FrameAnimation {
                id: reloj
                running: true
                // `paused` y nunca antes del primer fotograma: ver el porque en
                // plugin/contents/ui/main.qml, que tiene el mismo reloj.
                paused: hypr.tapado && (ventana.escena.item ? ventana.escena.item.dibujado : false)
            }

            // El plan propio de este monitor, si `wectl` le ha dado uno.
            VigiaArchivo {
                id: propio
                ruta: app.planes ? app.planes + "/" + ventana.nombre + "/plan.txt" : ""
            }
            readonly property bool planPropio: app.planes !== "" && propio.existe
            readonly property string plan: planPropio ? propio.ruta : app.plan

            // Se crea una escena nueva cuando cambia el plan que ESTE monitor
            // usa: un cambio del compartido no toca a los que tienen el suyo.
            //
            // Dos huecos y no uno. Con un solo Loader la escena vieja se
            // destruia al instante y la ventana enseñaba su color de fondo
            // hasta el primer fotograma de la nueva: de 27 a 501 ms de
            // pantallazo, casi todo el `init` de la nueva (subir texturas).
            // Ahora la nueva se carga en el otro hueco, DEBAJO, y cuando dice
            // `dibujado` pasa arriba y la vieja se suelta. Mientras, la vieja
            // se queda en su ultimo fotograma: el `init` bloquea el hilo de
            // render de la ventana, pero no se ve negro.
            property string clave: ventana.plan + "#"
                                   + (ventana.planPropio ? propio.version : app.vigia.version)
            property int turno: 0                     // el hueco que se ve
            readonly property var escena: turno === 0 ? huecoA : huecoB
            readonly property var otro: turno === 0 ? huecoB : huecoA
            onClaveChanged: {
                if (!escena.active && !otro.active) {
                    // La primera: no hay nada que tapar, va al hueco que se ve.
                    ventana.fijar(escena)
                    escena.active = ventana.plan !== ""
                    return
                }
                console.info("Escena: plan nuevo en " + ventana.nombre
                             + ", se carga debajo de la que se ve")
                otro.active = false
                ventana.fijar(otro)
                otro.active = ventana.plan !== ""
                if (!otro.active)
                    escena.active = false
            }
            // El plan de un hueco, y si es web, leidos en el momento de cargarlo.
            function fijar(h) {
                h.planFijo = ventana.plan
                h.webUrl = app.urlWeb(ventana.plan)
            }
            function relevo(h) {
                if (h !== otro || !h.item || !h.item.dibujado)
                    return
                turno = 1 - turno
                otro.active = false
                console.info("Escena: relevo en " + ventana.nombre + ", se ve el hueco "
                             + (turno === 0 ? "A" : "B") + " y se suelta el otro")
            }

            Loader {
                id: huecoA
                anchors.fill: parent
                property string planFijo: ""
                // Se fija con el plan, en `fijar`, y no como binding sobre
                // `planFijo`: la ruta es la misma de un plan al siguiente
                // (`plan.txt`), el binding no se reevaluaba y al pasar de un
                // web a una escena el hueco volvia a cargar el web anterior.
                property string webUrl: ""
                active: false
                z: ventana.turno === 0 ? 1 : 0
                sourceComponent: webUrl ? app.componenteWeb() : escenaComponente
                onLoaded: if (webUrl) ventana.prepararWeb(item, planFijo, webUrl)
            }
            Loader {
                id: huecoB
                anchors.fill: parent
                property string planFijo: ""
                // Se fija con el plan, en `fijar`, y no como binding sobre
                // `planFijo`: la ruta es la misma de un plan al siguiente
                // (`plan.txt`), el binding no se reevaluaba y al pasar de un
                // web a una escena el hueco volvia a cargar el web anterior.
                property string webUrl: ""
                active: false
                z: ventana.turno === 1 ? 1 : 0
                sourceComponent: webUrl ? app.componenteWeb() : escenaComponente
                onLoaded: if (webUrl) ventana.prepararWeb(item, planFijo, webUrl)
            }
            Connections {
                target: huecoA.item
                ignoreUnknownSignals: true
                function onStatusChanged() { ventana.relevo(huecoA) }
            }
            Connections {
                target: huecoB.item
                ignoreUnknownSignals: true
                function onStatusChanged() { ventana.relevo(huecoB) }
            }

            function prepararWeb(item, plan, url) {
                item.colorFondo = app.color
                item.fpsMax = app.fpsMax
                item.dirPlan = plan.substring(0, plan.lastIndexOf("/"))
                item.pausado = Qt.binding(() => hypr.tapado && item.dibujado)
                item.direccion = url
            }

            Component {
                id: escenaComponente
                SceneView {
                    // El plan de ESTE hueco, fijado al crearlo: la escena vieja
                    // sigue en pantalla mientras carga la nueva y no tiene que
                    // ver cambiar el suyo.
                    planSource: "file://" + parent.planFijo
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
                    readonly property var e: ventana.escena.item
                    text: [
                        "── WallpaperEngine · Hyprland ──",
                        "escena    : " + (e ? e.sceneTitle || "…" : "-"),
                        "motor     : " + (e ? e.status : "-"),
                        "monitor   : " + ventana.nombre + " " + ventana.width
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
