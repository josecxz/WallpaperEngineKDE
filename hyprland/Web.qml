// Un wallpaper de tipo web en el fondo de Hyprland: la pagina en un
// `WebEngineView` (QtWebEngine, o sea Chromium) en vez del `SceneView`.
//
// Va en su propio fichero y se carga con `Loader.source` solo cuando el plan
// es web: asi, sin `qt6-webengine` instalado, lo unico que falla es esto y
// las escenas y los videos siguen como estaban.
//
// Lo que WE le da a la pagina lo imitan dos scripts que `werender.plan_de_web`
// deja junto al plan: `web-antes.js` (antes de que corra la pagina: define
// vacias las funciones de audio y medios, que aqui no hay) y
// `web-despues.js` (al acabar de cargar: aplica las propiedades de
// `project.json` con sus valores por defecto, como WE).
//
// La interfaz hacia `main.qml` es la del `SceneView` que usan el relevo y el
// HUD: `dibujado`, `status`, `sceneTitle`, `msGpu`, `puntero`.

import QtQuick
import QtWebEngine

Item {
    id: raiz

    // La pone `main.qml`: `web <url>` del plan, el directorio del plan (para
    // los dos scripts) y si el monitor esta tapado.
    property url direccion
    property string dirPlan: ""
    property bool pausado: false
    property color colorFondo: "#0b0b0d"
    // `--fps` del anfitrion; 0, sin tope.
    property real fpsMax: 60

    property bool dibujado: false
    property string status: "cargando"
    property string sceneTitle: vista.title
    readonly property real msGpu: -1
    readonly property point puntero: Qt.point(0, 0)
    readonly property bool punteroPresente: false

    WebEngineView {
        id: vista
        anchors.fill: parent
        backgroundColor: raiz.colorFondo

        // Tapado del todo: se oculta y se congela (sin JS ni pintado), y la
        // pagina se entera por su `setPaused`, como en WE.
        visible: !raiz.pausado
        lifecycleState: raiz.pausado ? WebEngineView.LifecycleState.Frozen
                                     : WebEngineView.LifecycleState.Active

        settings.localContentCanAccessFileUrls: true
        // Fuentes y librerias de CDN: varias paginas las piden.
        settings.localContentCanAccessRemoteUrls: true
        settings.playbackRequiresUserGesture: false
        settings.showScrollBars: false
        settings.javascriptCanOpenWindows: false

        onLoadingChanged: function (carga) {
            if (carga.status === WebEngineView.LoadSucceededStatus) {
                console.info("Web: cargada " + carga.url)
                raiz.dibujado = true
                raiz.status = "web"
            } else if (carga.status === WebEngineView.LoadFailedStatus) {
                console.warn("Web: no cargo " + carga.url + ": " + carga.errorString)
                // Tambien cuenta como dibujado: si no, el relevo esperaria
                // para siempre con la escena anterior encima.
                raiz.dibujado = true
                raiz.status = "error web: " + carga.errorString
            }
        }
        onJavaScriptConsoleMessage: function (nivel, mensaje, linea, origen) {
            if (nivel === WebEngineView.ErrorMessageLevel)
                console.warn("Web: " + mensaje + " (" + origen + ":" + linea + ")")
        }
        // Un fondo no abre menus.
        onContextMenuRequested: function (peticion) { peticion.accepted = true }
        // Si el proceso de la pagina se cae, el fondo se quedaria congelado
        // en su ultimo fotograma: se recarga.
        onRenderProcessTerminated: function (estado, codigo) {
            console.warn("Web: el proceso de la pagina termino (" + estado + ", "
                         + codigo + "); se recarga")
            raiz.reintentar()
        }
    }

    // A veces Chromium no acaba de cargar la pagina y no avisa de nada: ni
    // `LoadSucceeded` ni `LoadFailed`, y la CPU a cero. Medido en dos de los
    // 15 web de la biblioteca, una de cada tres o cuatro cargas, y
    // recargando sale. Se espera 15 s y se reintenta, hasta tres veces.
    property int intentos: 0
    function reintentar() {
        if (raiz.intentos >= 3) {
            console.warn("Web: no cargo tras " + raiz.intentos + " reintentos")
            raiz.dibujado = true      // que el relevo no espere para siempre
            raiz.status = "error web: no carga"
            return
        }
        raiz.intentos++
        vista.reload()
        espera.restart()
    }
    Timer {
        id: espera
        interval: 15000
        onTriggered: if (!raiz.dibujado) {
            console.warn("Web: sin cargar a los 15 s; se recarga")
            raiz.reintentar()
        }
    }

    onPausadoChanged: {
        if (raiz.dibujado)
            vista.runJavaScript("window.__wePausa && window.__wePausa(" + raiz.pausado + ")")
    }

    function guion(nombre, momento) {
        const s = WebEngine.script()
        s.name = nombre
        s.sourceUrl = "file://" + raiz.dirPlan + "/" + nombre
        s.injectionPoint = momento
        s.worldId = WebEngineScript.MainWorld
        s.runsOnSubFrames = false
        return s
    }

    // `main.qml` pone `dirPlan` y luego `direccion`: con la direccion ya se
    // sabe todo y se carga una sola vez.
    onDireccionChanged: {
        if (vista.url.toString() !== "")
            return
        const tope = WebEngine.script()
        tope.name = "fps"
        tope.sourceCode = "window.__weFps = " + raiz.fpsMax + ";"
        tope.injectionPoint = WebEngineScript.DocumentCreation
        tope.worldId = WebEngineScript.MainWorld
        vista.userScripts.insert(tope)
        vista.userScripts.insert(guion("web-antes.js", WebEngineScript.DocumentCreation))
        // `Deferred`: tras el `load` de la pagina, cuando ya ha registrado su
        // `wallpaperPropertyListener` (muchas lo hacen en `onload`).
        vista.userScripts.insert(guion("web-despues.js", WebEngineScript.Deferred))
        vista.url = raiz.direccion
        espera.start()
    }
}
