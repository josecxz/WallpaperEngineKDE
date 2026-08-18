// UI de configuracion del wallpaper. Plasma la incrusta en Ajustes del
// Sistema y en "Configurar escritorio". El contrato es: por cada entrada
// <entry name="X"> de config/main.xml, exponer una propiedad cfg_X.

import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kquickcontrols as KQuickControls
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: root
    twinFormLayouts: parentLayout

    property alias cfg_Color: colorButton.color
    property alias cfg_ShowDiagnostics: diagnosticsCheck.checked
    // El combo guarda el indice, que es justo el valor que espera `PauseMode`.
    property alias cfg_PauseMode: pausaCombo.currentIndex
    // Igual que arriba: el indice del combo ES el valor de `FitMode`.
    property alias cfg_FitMode: encajeCombo.currentIndex
    property alias cfg_Zoom: zoomSlider.value
    property alias cfg_OffsetX: despXSlider.value
    property alias cfg_OffsetY: despYSlider.value
    property alias formLayout: root

    KQuickControls.ColorButton {
        id: colorButton
        Kirigami.FormData.label: "Color de fondo:"
        dialogTitle: "Seleccionar color de fondo"
    }

    QQC2.ComboBox {
        id: encajeCombo
        Kirigami.FormData.label: "Encaje:"
        model: ["Cubrir la pantalla, recortando lo que sobre",
                "Ver la escena entera, con barras",
                "Estirar hasta llenar, deformando"]
    }

    QQC2.Label {
        text: "Casi todas las escenas estan hechas en 16:9. Si tu pantalla no lo es,\n" +
              "cubrir recorta por los lados y encajar deja barras del color de fondo."
        opacity: 0.7
        wrapMode: Text.WordWrap
    }

    QQC2.Slider {
        id: zoomSlider
        Kirigami.FormData.label: "Acercamiento:"
        from: 0.5
        to: 3.0
        stepSize: 0.05
        implicitWidth: Kirigami.Units.gridUnit * 14
        QQC2.ToolTip.visible: pressed
        QQC2.ToolTip.text: Math.round(value * 100) + "%"
    }

    // Los dos de abajo solo hacen algo cuando sobra escena que elegir. Con la
    // escena entera y sin acercamiento no hay recorte que mover, y apagarlos lo
    // dice mejor que dejar al usuario moviendo algo que no cambia nada.
    QQC2.Slider {
        id: despXSlider
        Kirigami.FormData.label: "Recorte horizontal:"
        from: -1.0
        to: 1.0
        stepSize: 0.05
        implicitWidth: Kirigami.Units.gridUnit * 14
        enabled: encajeCombo.currentIndex === 0 || zoomSlider.value > 1.0
        QQC2.ToolTip.visible: pressed
        QQC2.ToolTip.text: value < 0 ? "hacia la izquierda"
                                     : (value > 0 ? "hacia la derecha" : "centrado")
    }

    QQC2.Slider {
        id: despYSlider
        Kirigami.FormData.label: "Recorte vertical:"
        from: -1.0
        to: 1.0
        stepSize: 0.05
        implicitWidth: Kirigami.Units.gridUnit * 14
        enabled: despXSlider.enabled
        QQC2.ToolTip.visible: pressed
        QQC2.ToolTip.text: value < 0 ? "hacia abajo"
                                     : (value > 0 ? "hacia arriba" : "centrado")
    }

    QQC2.ComboBox {
        id: pausaCombo
        Kirigami.FormData.label: "Dejar de dibujar:"
        model: ["Nunca",
                "Con una ventana maximizada o a pantalla completa",
                "Con cualquier ventana visible"]
    }

    QQC2.Label {
        text: "Un fondo que no se ve puede costar la mitad de la GPU. Al volver,\n" +
              "la escena continua donde estaba en vez de dar un salto."
        opacity: 0.7
        wrapMode: Text.WordWrap
    }

    QQC2.CheckBox {
        id: diagnosticsCheck
        Kirigami.FormData.label: "Diagnostico:"
        text: "Mostrar FPS y geometria"
    }
}
