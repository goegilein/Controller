import tkinter as tk
from tkinter import ttk

from PyQt6 import QtWidgets, uic, QtCore

class BaseClass:
    def __init__(self):
        self.widget_dict = {}

    def connect_widget(self, widget, method):
        if isinstance(widget, QtWidgets.QCheckBox):
            widget.stateChanged.connect(method)
        elif isinstance(widget, QtWidgets.QComboBox):
            widget.currentIndexChanged.connect(method)
        elif isinstance(widget, QtWidgets.QPushButton):
            widget.pressed.connect(lambda: method(action='pressed'))
            widget.released.connect(lambda: method(action='released'))
        elif isinstance(widget, QtWidgets.QRadioButton):
            widget.clicked.connect(method)
        elif isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            widget_id=widget.objectName()
            self.widget_dict[widget_id] = widget.value()
            widget.editingFinished.connect(lambda: self.spinbox_callback(widget_id, widget.value(), method))
        elif isinstance(widget, QtWidgets.QSlider):
            widget.valueChanged.connect(method)
        elif isinstance(widget, QtWidgets.QTextEdit):
            widget.textChanged.connect(method)
        elif isinstance(widget, QtWidgets.QListWidget):
            widget.itemSelectionChanged.connect(method)
        else:
            print("Widget not supported")

    def spinbox_callback(self, widget_id, value, method):
        if value != self.widget_dict[widget_id]: 
            self.widget_dict[widget_id] = value
            method()
    
    def lock_toggle_buttons(self, *buttons):
        for button in buttons:
            button.clicked.connect(lambda _, b=button: self.unclick_buttons(buttons, b))

    def unclick_buttons(self, buttons, button_sender):
        for button in buttons:
            if button==button_sender:
                pass
            else:
                button.setChecked(False)
        
        button_sender.setChecked(True)