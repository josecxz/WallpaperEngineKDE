// La escena que se ve y la que se esta cargando debajo.
//
// Cambiar de wallpaper en Plasma era salir a `org.kde.image` y volver: tres
// fondos en pantalla en un cuarto de segundo, y de 140 a 230 ms sin escena en
// cada cambio de la rotacion. Ahora el fondo vigila el plan como en Hyprland y
// la escena nueva se carga en el hueco que no se ve; cuando dice `dibujado`
// pasa arriba y la vieja se suelta. Mientras, la vieja se queda en su ultimo
// fotograma: el `init` bloquea el hilo de render de la ventana, pero no se ve
// negro. Ver NOTAS, «La recarga del plan» y «La recarga en Plasma».
//
// Va en su propio fichero y sin nada de Plasma para poder probarlo en una
// `Window` suelta: no se itera sobre plasmashell en vivo.

import QtQuick
import org.jose.wallpaperengine.render

Item {
    id: escenas

    required property string plan   // ruta local del plan.txt
    required property real tiempo   // el reloj, que no para al cambiar de escena
    property int encaje: 0
    property real zoom: 1
    property real desplazamientoX: 0
    property real desplazamientoY: 0
    property bool gpuDedicada: true
    property real fpsMax: 60
    property color colorBarras: "#0b0b0d"
    property HoverHandler raton: null

    // La escena que se ve. Puede ser null un instante al arrancar.
    readonly property var actual: turno === 0 ? huecoA.item : huecoB.item
    readonly property bool dibujado: actual ? actual.dibujado : false
    // Hay una escena debajo sin dibujar. El reloj no puede pararse mientras:
    // sin `time` nuevo no hay fotograma, y sin fotograma no llega el relevo.
    readonly property bool cargando: otro.active

    property int turno: 0                     // el hueco que se ve
    readonly property var otro: turno === 0 ? huecoB : huecoA

    VigiaArchivo {
        id: vigia
        ruta: escenas.plan
    }

    // `int` para que solo salte al cambiar de verdad: `VigiaArchivo` tambien
    // avisa al ponerle la ruta, con la version aun a cero.
    readonly property int version: vigia.version
    onVersionChanged: {
        // Si han quitado el plan, lo que hay sigue siendo lo mejor que hay.
        if (!vigia.existe)
            return
        console.info("Escena: plan nuevo, se carga debajo de la que se ve")
        cargar(otro)
    }

    function cargar(hueco) {
        hueco.active = false
        hueco.origen = escenas.tiempo
        hueco.active = true
    }

    function relevo(hueco) {
        if (hueco !== otro || !hueco.item || !hueco.item.dibujado)
            return
        turno = 1 - turno
        otro.active = false
        console.info("Escena: relevo, se ve el hueco " + (turno === 0 ? "A" : "B")
                     + " y se suelta el otro")
    }

    Component.onCompleted: cargar(huecoA)

    Loader {
        id: huecoA
        anchors.fill: parent
        // Donde estaba el reloj al crearla: cada escena empieza en `g_Time`
        // 0, como cuando Plasma recreaba el fondo, y no con las horas que
        // lleve la sesion, que en un float le quitarian precision al shader.
        property real origen: 0
        active: false
        z: escenas.turno === 0 ? 1 : 0
        sourceComponent: escena
    }
    Loader {
        id: huecoB
        anchors.fill: parent
        property real origen: 0
        active: false
        z: escenas.turno === 1 ? 1 : 0
        sourceComponent: escena
    }
    Connections {
        target: huecoA.item
        ignoreUnknownSignals: true
        function onStatusChanged() { escenas.relevo(huecoA) }
    }
    Connections {
        target: huecoB.item
        ignoreUnknownSignals: true
        function onStatusChanged() { escenas.relevo(huecoB) }
    }

    Component {
        id: escena
        SceneView {
            id: vista
            // El plan se lee al crear la escena y la ruta no cambia nunca: lo
            // que cambia es lo que hay en ella.
            planSource: "file://" + escenas.plan
            // La animacion se deriva del tiempo, no de un contador de frames,
            // para que la velocidad no dependa del refresco de la pantalla.
            time: escenas.tiempo - parent.origen

            // La escena se dibuja al tamano del lienzo de su autor ---16:9 en
            // 99 de las 125 escenas--- y esto decide como llega a la pantalla.
            // El color de las barras se pasa al motor en vez de dejarlo al
            // Rectangle de debajo porque el item se compone sin mezcla alfa: lo
            // que el motor no pinte sale negro, no transparente.
            encaje: escenas.encaje
            zoom: escenas.zoom
            desplazamientoX: escenas.desplazamientoX
            desplazamientoY: escenas.desplazamientoY
            gpuDedicada: escenas.gpuDedicada
            fpsMax: escenas.fpsMax
            colorBarras: escenas.colorBarras

            puntero: {
                const r = escenas.raton
                if (!r)
                    return Qt.point(0, 0)
                const p = vista.mapFromItem(r.parent, r.point.position.x,
                                            r.point.position.y)
                return Qt.point(p.x / Math.max(1, vista.width),
                                p.y / Math.max(1, vista.height))
            }
            punteroPresente: escenas.raton ? escenas.raton.hovered : false
        }
    }
}
