// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
//
// Setup dialog for Bambu LAN Print. Plain QtQuick so it works on any Cura 5.x.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15

Window {
    id: win
    title: "Bambu LAN — printer setup"
    width: 480
    height: 700
    minimumWidth: 420
    minimumHeight: 560
    flags: Qt.Dialog
    modality: Qt.ApplicationModal
    color: pal.window

    SystemPalette { id: pal; colorGroup: SystemPalette.Active }

    property var cfg: JSON.parse(manager.loadConfig())
    property bool testing: false
    property bool searching: false
    property var found: []
    property bool accepted: manager.isAccepted()

    function collect() {
        return {
            ip: ipField.text.trim(),
            access_code: codeField.text.trim(),
            serial: serialField.text.trim(),
            insecure: insecureBox.checked,
            start: startBox.checked,
            filament: filamentBox.currentIndex - 1,   // 0 = external (-1), 1.. = AMS slot 0..
            bed_levelling: levelBox.checked,
            flow_cali: flowBox.checked,
            timelapse: timelapseBox.checked,
            bed_type: bedBox.currentValue
        }
    }

    Connections {
        target: manager
        function onStatusChanged(text, ok) {
            win.testing = false
            statusText.text = text
            statusText.color = ok ? "#2e7d32" : "#c62828"
        }
        function onPrintersFound(listJson) {
            win.searching = false
            win.found = JSON.parse(listJson)
            if (win.found.length === 0)
                statusText.text = "No printers heard. They announce every few seconds; make sure this computer is on the same network, or type the IP from the printer's screen."
            else
                statusText.text = "Found " + win.found.length + " printer(s). Pick one below."
            statusText.color = pal.text
        }
        function onSerialFound(serial) { serialField.text = serial }
    }

    ScrollView {
        anchors.fill: parent
        anchors.margins: 16
        contentWidth: availableWidth

        ColumnLayout {
            width: parent.width
            spacing: 8

            Label {
                text: "Cura printer: <b>" + (win.cfg.machine || "?") + "</b>"
                color: pal.text
                textFormat: Text.StyledText
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: pal.text
                font.pointSize: 9
                text: "Get the IP and access code from the printer's network screen, and insert an SD card. <b>Newer firmware</b> (A1 01.05+, P1 01.08.02+, X1 01.08.03+) also needs <b>LAN-only mode</b> then <b>Developer Mode</b>; older firmware doesn't. <b>Test connection</b> tells you which you have."
                textFormat: Text.StyledText
            }

            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: win.searching ? "Searching…" : "Find printers on network"
                    enabled: !win.searching
                    onClicked: { win.searching = true; statusText.text = "Listening for printers…"; statusText.color = pal.text; manager.discover() }
                }
            }
            Repeater {
                model: win.found
                delegate: Button {
                    Layout.fillWidth: true
                    text: modelData.name + "  —  " + modelData.ip + (modelData.model ? "  (" + modelData.model + ")" : "")
                    onClicked: { ipField.text = modelData.ip; serialField.text = modelData.serial }
                }
            }

            Label { text: "IP address"; color: pal.text }
            TextField { id: ipField; objectName: "ipField"; Layout.fillWidth: true; text: win.cfg.ip; placeholderText: "192.168.1.50" }

            Label { text: "Access code"; color: pal.text }
            TextField { id: codeField; objectName: "codeField"; Layout.fillWidth: true; text: win.cfg.access_code; placeholderText: "8 characters from the printer's network screen"; echoMode: showCode.checked ? TextInput.Normal : TextInput.Password }
            CheckBox { id: showCode; text: "Show access code" }

            Label { text: "Serial number (optional — read automatically)"; color: pal.text }
            TextField { id: serialField; objectName: "serialField"; Layout.fillWidth: true; text: win.cfg.serial; placeholderText: "leave empty to auto-detect" }

            CheckBox { id: insecureBox; objectName: "insecureBox"; text: "Skip certificate check (only if the check fails)"; checked: win.cfg.insecure }

            Rectangle { Layout.fillWidth: true; height: 1; color: pal.mid }

            CheckBox { id: startBox; objectName: "startBox"; text: "Start printing after upload"; checked: win.cfg.start }

            Label { text: "Filament source"; color: pal.text }
            ComboBox {
                id: filamentBox
                objectName: "filamentBox"
                Layout.fillWidth: true
                model: ["External spool", "AMS slot 1", "AMS slot 2", "AMS slot 3", "AMS slot 4",
                        "AMS 2 slot 1", "AMS 2 slot 2", "AMS 2 slot 3", "AMS 2 slot 4"]
                currentIndex: Math.max(0, Math.min(8, (win.cfg.filament === undefined ? -1 : win.cfg.filament) + 1))
            }

            Label { text: "Build plate"; color: pal.text }
            ComboBox {
                id: bedBox
                objectName: "bedBox"
                Layout.fillWidth: true
                textRole: "text"
                valueRole: "value"
                model: [
                    { text: "Auto (printer decides)", value: "auto" },
                    { text: "Textured PEI", value: "textured_plate" },
                    { text: "Cool plate", value: "cool_plate" },
                    { text: "Engineering plate", value: "eng_plate" },
                    { text: "High-temp plate", value: "hot_plate" }
                ]
                Component.onCompleted: currentIndex = Math.max(0, indexOfValue(win.cfg.bed_type))
            }

            CheckBox { id: levelBox; text: "Bed levelling before print"; checked: win.cfg.bed_levelling }
            CheckBox { id: flowBox; text: "Flow / vibration calibration"; checked: win.cfg.flow_cali }
            CheckBox { id: timelapseBox; text: "Timelapse"; checked: win.cfg.timelapse }

            Rectangle {
                id: notice
                objectName: "notice"
                visible: !win.accepted
                Layout.fillWidth: true
                implicitHeight: noticeCol.implicitHeight + 20
                color: "transparent"
                border.color: "#c62828"
                border.width: 1
                radius: 4
                ColumnLayout {
                    id: noticeCol
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: pal.text
                        textFormat: Text.StyledText
                        text: "<b>Before you use this</b><br>This plugin starts real print jobs on a real machine. A wrong printer profile or bad G-code can crash the nozzle, damage the bed or waste filament. Watch the first print. It is provided <b>as is, with no warranty and no liability</b>, and is not affiliated with Bambu Lab.<br>" + manager.aboutLine()
                    }
                    CheckBox { id: agreeBox; objectName: "agreeBox"; text: "I understand and agree" }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: pal.mid }

            Label {
                id: statusText
                objectName: "statusText"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                color: pal.text
                text: ""
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Button {
                    text: win.testing ? "Testing…" : "Test connection"
                    enabled: !win.testing && ipField.text.length > 0 && codeField.text.length > 0
                    onClicked: {
                        win.testing = true
                        statusText.text = "Connecting…"
                        statusText.color = pal.text
                        manager.testConnection(JSON.stringify(win.collect()))
                    }
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Remove"
                    onClicked: { manager.removeConfig(); win.close() }
                }
                Button {
                    objectName: "saveButton"
                    text: "Save"
                    highlighted: true
                    enabled: ipField.text.length > 0 && codeField.text.length > 0 && (win.accepted || agreeBox.checked)
                    onClicked: {
                        if (!win.accepted) manager.accept()
                        manager.saveConfig(JSON.stringify(win.collect()))
                        win.close()
                    }
                }
            }
        }
    }
}
