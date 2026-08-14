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
    property alias formLayout: root

    KQuickControls.ColorButton {
        id: colorButton
        Kirigami.FormData.label: "Color de fondo:"
        dialogTitle: "Seleccionar color de fondo"
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
