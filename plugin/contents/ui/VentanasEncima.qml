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
// No mira geometrias: `IsMaximized` e `IsFullScreen` los mantiene KWin, que es
// quien sabe de verdad si una ventana cubre su pantalla. Comparar rectangulos a
// mano volveria a fallar con paneles, margenes y escalado.

import QtQuick
import org.kde.taskmanager as TaskManager

Item {
    id: raiz

    // Rectangulo de la pantalla de este fondo, para filtrar por monitor.
    property rect geometriaPantalla

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

    // ¿Cual es la ventana ACTIVA, y tapa?
    //
    // Preguntar "¿hay alguna maximizada?" no vale: al llegar al escritorio con
    // "Mostrar el escritorio", minimizando o cambiando de escritorio virtual,
    // las ventanas siguen siendo maximizadas para KWin y el fondo se quedaba en
    // pausa con el escritorio a la vista --- que es justo cuando hay que
    // dibujarlo. Lo que decide es que estas mirando: si la ventana activa tapa
    // la pantalla, el fondo no se ve; si no hay ninguna activa, estas en el
    // escritorio.
    function _activaTapa() {
        const idx = tareas.activeTask
        if (!idx || !idx.valid)
            return false
        const dato = (papel) => tareas.data(idx, TaskManager.AbstractTasksModel[papel])
        if (!dato("IsWindow") || dato("SkipTaskbar") || dato("IsMinimized")
                || dato("IsHidden"))
            return false
        _activa = (dato("AppName") || "?")
        return modo === 2 || dato("IsMaximized") || dato("IsFullScreen")
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
        _tapado = _activaTapa()
        _escritorio = String(escritorios.currentDesktop || "?").slice(0, 4)
        _detalle = "activa:" + _activa + "  maximizadas:"
                 + (nombres.join(", ") || "-")
    }

    onModoChanged: revisar()
    onGeometriaPantallaChanged: revisar()
    Component.onCompleted: revisar()
}
