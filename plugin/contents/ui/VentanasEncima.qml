// ¿Hay algo tapando el escritorio?
//
// Dibujar un fondo que nadie ve es el gasto mas facil de quitar: la escena mas
// pesada del corpus se come el 92% del motor de render de la iGPU, en continuo,
// y con una ventana maximizada encima no se ve ni un pixel de ella.
//
// Quien lo sabe es el gestor de ventanas, y `org.kde.taskmanager` --- el mismo
// modelo que usa el gestor de tareas del panel --- lo expone ya filtrado por
// pantalla, escritorio virtual y actividad. Sin ese filtrado un maximizado en
// el monitor de al lado, o en otro escritorio virtual, pararia este fondo.
//
// Mirar `IsMaximized` de la ventana ACTIVA no basta, y se ve en cuanto lo usas:
// dos ventanas en mosaico que entre las dos tapan la pantalla y ninguna esta
// maximizada; una ventana pequena activa encima de una maximizada; una
// redimensionada a mano hasta cubrirlo todo. En los tres casos el fondo se
// pone a dibujar sin que se vea un pixel de el.
//
// La pregunta buena no es una bandera de una ventana sino CUANTA pantalla
// queda tapada, asi que se mide: se marca una rejilla gruesa con los
// rectangulos de las ventanas visibles y se cuenta. No hace falta la union
// exacta ---calcularla en QML seria lento y fragil--- y una celda entera
// absorbe margenes, paneles y escalado fraccional, que es lo que hacia temer
// comparar geometrias a mano.
//
// De paso arregla solo el caso que tumbo al primer intento: al llegar al
// escritorio con "Mostrar el escritorio" las ventanas siguen siendo
// `IsMaximized` para KWin, pero no aportan superficie porque estan ocultas.

import QtQuick
import org.kde.taskmanager as TaskManager
import org.jose.wallpaperengine.render

Item {
    id: raiz

    // Rectangulo de la pantalla de este fondo, para filtrar por monitor.
    property rect geometriaPantalla

    // Area util: la pantalla MENOS los paneles. Es contra lo que hay que medir
    // la cobertura, porque el fondo que queda debajo de un panel opaco no se
    // ve: con la pantalla entera, una ventana maximizada se queda en el 94% y
    // el umbral tendria que aflojarse hasta dejar pasar huecos de verdad.
    // Si llega vacia ---la expone el containment y puede no resolverse--- se
    // cae a la pantalla completa, que es peor referencia pero nunca es cero.
    property rect geometriaUtil

    // 0 nunca, 1 maximizada o pantalla completa, 2 cualquier ventana visible.
    property int modo: 1

    readonly property bool tapado: _tapado
    property bool _tapado: false
    // Recuento para el HUD. Sin el no hay forma de saber POR QUE esta en pausa:
    // si el modelo no ve ventanas es un problema de filtrado, y si las ve y
    // dice que estan maximizadas es que lo estan de verdad.
    readonly property int ventanas: _ventanas
    readonly property int maximizadas: _maximizadas
    readonly property int ocultas: _ocultas
    property int _ventanas: 0
    property int _maximizadas: 0
    property int _ocultas: 0
    // Quien dice tapar, y en que escritorio virtual se esta filtrando. Es el
    // dato que separa "esa ventana tapa de verdad" de "el filtro no descarta
    // las de otro escritorio".
    readonly property string detalle: _detalle
    property string _detalle: ""
    property string _activa: "-"
    property string _escritorio: ""
    property string _filtrado: ""

    // Lo unico que sabe si KWin esta mostrando el escritorio; el modelo de
    // tareas no lo refleja (ver escritorio.h).
    Escritorio {
        id: kwin
        onMostrandoEscritorioChanged: raiz.revisar()
    }

    TaskManager.ActivityInfo {
        id: actividad
        onCurrentActivityChanged: raiz.revisar()
    }

    TaskManager.VirtualDesktopInfo {
        id: escritorios
        onCurrentDesktopChanged: raiz.revisar()
    }

    TaskManager.TasksModel {
        id: tareas
        // Sin agrupar: una ventana, una fila. Agrupadas habria que bajar a los
        // hijos para saber si alguna esta maximizada.
        groupMode: TaskManager.TasksModel.GroupDisabled

        screenGeometry: raiz.geometriaPantalla
        filterByScreen: true

        virtualDesktop: escritorios.currentDesktop
        filterByVirtualDesktop: true

        activity: actividad.currentActivity
        filterByActivity: true

        onActiveTaskChanged: raiz.revisar()
        onCountChanged: raiz.revisar()
        onDataChanged: raiz.revisar()
        onModelReset: raiz.revisar()
        onRowsInserted: raiz.revisar()
        onRowsRemoved: raiz.revisar()
        onLayoutChanged: raiz.revisar()
    }

    function _valor(fila, papel) {
        return tareas.data(tareas.index(fila, 0),
                           TaskManager.AbstractTasksModel[papel])
    }

    // Red de seguridad. La deteccion va por senales del modelo; si alguna no
    // llega ---y desmaximizar tiene que llegar por `dataChanged`, que es la mas
    // facil de perder--- el fondo se quedaria congelado para siempre. Un
    // repaso por segundo cuesta nada y convierte ese fallo en un retraso.
    Timer {
        interval: 1000
        running: raiz.modo !== 0
        repeat: true
        onTriggered: raiz.revisar()
    }

    readonly property bool mostrandoEscritorio: kwin.mostrandoEscritorio

    // Fraccion de la pantalla tapada, 0 a 1. Se publica porque es el dato que
    // separa "no pausa porque de verdad se ve el fondo" de "no pausa porque el
    // filtro esta descartando ventanas", y sin el esto se depura a ciegas.
    readonly property real cobertura: _cobertura
    property real _cobertura: 0

    // Rejilla de muestreo. Se comprueba el CENTRO de cada celda contra cada
    // ventana: contar una celda entera por rozarla inflaria la cobertura y el
    // fondo se pararia con una ventana pegada al borde.
    readonly property int _cols: 32
    readonly property int _filas: 18

    // A partir de aqui se considera tapado. No es 1.0 a proposito: aunque se
    // mida contra el area util, quedan los bordes redondeados de las ventanas,
    // los margenes de las que se colocan en mosaico y el respaldo a pantalla
    // completa cuando el area util no llega. El 8% de holgura cubre esos casos
    // sin tragarse una franja de fondo que se vea.
    readonly property real _umbral: 0.92

    function _referencia() {
        const u = geometriaUtil
        return (u && u.width > 0 && u.height > 0) ? u : geometriaPantalla
    }

    function _medirCobertura() {
        const p = _referencia()
        if (!p || p.width <= 0 || p.height <= 0)
            return 0
        // Rectangulos visibles, ya recortados a la pantalla y en fraccion de
        // ella, que es lo que hace la cuenta independiente del escalado.
        let cajas = []
        for (let i = 0; i < tareas.count; i++) {
            if (!_valor(i, "IsWindow") || _valor(i, "SkipTaskbar"))
                continue
            if (_valor(i, "IsMinimized") || _valor(i, "IsHidden"))
                continue
            const g = _valor(i, "Geometry")
            if (!g || g.width <= 0 || g.height <= 0)
                continue
            cajas.push({
                x0: (g.x - p.x) / p.width,
                x1: (g.x + g.width - p.x) / p.width,
                y0: (g.y - p.y) / p.height,
                y1: (g.y + g.height - p.y) / p.height
            })
        }
        if (!cajas.length)
            return 0
        let tapadas = 0
        for (let f = 0; f < _filas; f++) {
            const cy = (f + 0.5) / _filas
            for (let c = 0; c < _cols; c++) {
                const cx = (c + 0.5) / _cols
                for (let k = 0; k < cajas.length; k++) {
                    const b = cajas[k]
                    if (cx >= b.x0 && cx < b.x1 && cy >= b.y0 && cy < b.y1) {
                        tapadas++
                        break
                    }
                }
            }
        }
        return tapadas / (_cols * _filas)
    }

    // ¿Cual es la ventana ACTIVA, y tapa?
    //
    // Preguntar "¿hay alguna maximizada?" no vale: al llegar al escritorio con
    // "Mostrar el escritorio", minimizando o cambiando de escritorio virtual,
    // las ventanas siguen siendo maximizadas para KWin y el fondo se quedaba en
    // pausa con el escritorio a la vista --- que es justo cuando hay que
    // dibujarlo. Lo que decide es que estas mirando: si la ventana activa tapa
    // la pantalla, el fondo no se ve; si no hay ninguna activa, estas en el
    // escritorio.
    // ¿Estas mirando una ventana, o el escritorio?
    //
    // Hace falta ADEMAS de la cobertura porque el modelo no siempre marca lo
    // minimizado: con las cinco ventanas minimizadas seguia diciendo "0
    // ocultas" y sus geometrias mantenian la cobertura en el 100%, o sea que
    // el fondo se quedaba en pausa con el escritorio a la vista ---el mismo
    // fallo que tumbo el primer intento, por otro camino---. La ventana activa
    // si se actualiza: al minimizar todo o pulsar "Mostrar el escritorio" no
    // queda ninguna, y eso es justo lo que significa estar viendo el fondo.
    function _hayActivaVisible() {
        const idx = tareas.activeTask
        if (!idx || !idx.valid)
            return false
        const dato = (papel) => tareas.data(idx, TaskManager.AbstractTasksModel[papel])
        if (!dato("IsWindow") || dato("SkipTaskbar") || dato("IsMinimized")
                || dato("IsHidden"))
            return false
        _activa = (dato("AppName") || "?")
        return true
    }

    function revisar() {
        if (modo === 0) {
            _tapado = false
            _ventanas = 0
            return
        }
        _activa = "-"
        let vistas = 0, maxi = 0, fuera = 0, tapa = false
        let nombres = []
        for (let i = 0; i < tareas.count; i++) {
            // `SkipTaskbar` deja fuera lo que no es una ventana de usuario:
            // OSD, notificaciones, ventanas de utilidad. Una de esas a pantalla
            // completa pararia el fondo sin que haya nada tapandolo.
            if (!_valor(i, "IsWindow") || _valor(i, "SkipTaskbar"))
                continue
            vistas++
            // `IsHidden` cubre lo que `IsMinimized` no --- entre otras, las
            // ventanas apartadas por "Mostrar el escritorio".
            if (_valor(i, "IsMinimized") || _valor(i, "IsHidden")) {
                fuera++
                continue
            }
            if (modo === 2 || _valor(i, "IsMaximized") || _valor(i, "IsFullScreen")) {
                maxi++
                tapa = true
                if (nombres.length < 3) {
                    const d = _valor(i, "VirtualDesktops")
                    nombres.push((_valor(i, "AppName") || "?")
                                 + (d && d.length ? "@" + String(d[0]).slice(0, 4) : ""))
                }
            }
        }
        _ventanas = vistas
        _maximizadas = maxi
        _ocultas = fuera
        _cobertura = _medirCobertura()
        // Modo 2 se para con que haya algo visible; modo 1, cuando lo visible
        // tapa la pantalla. La ventana activa ya no decide: lo que importa es
        // cuanta pantalla queda a la vista, no cual de ellas tiene el foco.
        const antes = _tapado
        // Dos condiciones, y cada una tapa el agujero de la otra: la activa
        // dice si estas mirando algo, y la cobertura si eso que miras deja ver
        // el fondo. Con la activa sola, dos ventanas en mosaico no paraban
        // nada; con la cobertura sola, el escritorio a la vista tampoco
        // arrancaba.
        const mirando = _hayActivaVisible() && !kwin.mostrandoEscritorio
        _tapado = mirando && (modo === 2 ? _cobertura > 0
                                         : _cobertura >= _umbral)
        // Solo al cambiar de estado: el numero vivo lo ensena el HUD, y esto
        // es para cuando alguien pregunta por que se paro o por que no.
        if (antes !== _tapado)
            console.warn("VentanasEncima: " + (_tapado ? "en pausa" : "dibujando")
                         + " con " + (_cobertura * 100).toFixed(0) + "% tapado, "
                         + "activa=" + (mirando ? _activa : "-")
                         + (kwin.mostrandoEscritorio ? " (mostrando escritorio)" : "")
                         + ", "
                         + vistas + " ventanas (" + fuera + " ocultas)")
        _escritorio = String(escritorios.currentDesktop || "?").slice(0, 4)
        _detalle = "activa:" + _activa + "  tapan:"
                 + (nombres.join(", ") || "-")
    }

    onModoChanged: revisar()
    onGeometriaPantallaChanged: revisar()
    Component.onCompleted: revisar()
}
