# Единица плотности в профилях STE Slicer

Источник: resources/qml/Preferences/Materials/MaterialsView.qml, строки 214–224.

SHA-256 исходного файла: 7bdb7b3b9f391daa36a680bdd1f908a3998c30f46218c9f30d61ff51fb757aca

```qml
                ReadOnlySpinBox
                {
                    id: densitySpinBox
                    width: scrollView.columnWidth
                    value: properties.density
                    decimals: 2
                    suffix: " g/cm³"
                    stepSize: 0.01
                    readOnly: !base.editingEnabled

                    onEditingFinished: base.setMetaDataEntry("properties/density", properties.density, value)
```

UI связывает properties.density с g/cm³. Это подтверждает единицу настройки профиля, но не метод или условия измерения материала.
