import QtQuick 2.2
import QtQuick.Controls 1.1
import QtQuick.Layouts 1.1
import QtQuick.Dialogs 1.1

import UM 1.2 as UM

UM.Dialog
{
    id: dialog
    title: "AI помощник печати"
    width: 760 * screenScaleFactor
    height: 640 * screenScaleFactor
    minimumWidth: 520 * screenScaleFactor
    minimumHeight: 420 * screenScaleFactor

    ColumnLayout
    {
        anchors.fill: parent
        spacing: 6

        Connections
        {
            target: manager
            onReplyReceived: { log.append("<b>AI:</b> " + answer + "<br>"); status.text = "" }
            onErrorReceived: { log.append("<font color='red'>" + message + "</font><br>"); status.text = "" }
            onStatusReceived: status.text = text
            onChangesUpdated: changes.text = html
        }

        RowLayout
        {
            TextField { id: url; Layout.fillWidth: true; placeholderText: "Base URL"; text: manager.getBaseUrl() }
            TextField { id: key; Layout.preferredWidth: 150; placeholderText: manager.hasKey() ? "ключ сохранён" : "API key"; echoMode: TextInput.Password }
            TextField { id: model; Layout.preferredWidth: 150; placeholderText: "Model"; text: manager.getModel() }
            Button { text: "Save"; onClicked: { manager.saveSettings(url.text, key.text, model.text); key.text = "" } }
        }

        RowLayout
        {
            Label { text: "Сценарий:" }
            ComboBox
            {
                id: scenario
                Layout.fillWidth: true
                model: manager.scenarioTitles()
                onActivated: input.text = manager.selectScenario(index)
            }
            Button { text: "Новый чат"; onClicked: { manager.resetChat(); log.text = "" } }
        }

        RowLayout
        {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 6

            TextArea { id: log; Layout.fillWidth: true; Layout.fillHeight: true; readOnly: true; textFormat: TextEdit.RichText }

            ColumnLayout
            {
                Layout.preferredWidth: 220 * screenScaleFactor
                Layout.fillHeight: true
                Label { text: "Что изменено" ; font.bold: true }
                TextArea { id: changes; Layout.fillWidth: true; Layout.fillHeight: true; readOnly: true; textFormat: TextEdit.RichText }
            }
        }

        Label { id: status; Layout.fillWidth: true; text: "" }

        FileDialog
        {
            id: fileDialog
            title: "Выбери модель"
            nameFilters: ["3D models (*.stl *.3mf *.obj)", "All files (*)"]
            onAccepted: manager.attachFile(fileUrl.toString())
        }

        RowLayout
        {
            Button { text: "Файл"; onClicked: fileDialog.open() }
            TextField
            {
                id: input
                Layout.fillWidth: true
                placeholderText: "Опиши задачу или выбери сценарий"
                onAccepted: send.clicked()
            }
            Button
            {
                id: send
                text: "Send"
                onClicked:
                {
                    if (input.text == "") return
                    log.append("<b>You:</b> " + input.text + "<br>")
                    status.text = "Думаю..."
                    manager.send(input.text)
                    input.text = ""
                }
            }
        }
    }
}
