from PyQt6 import QtWidgets

class CustomGraphicsView(QtWidgets.QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setGeometry(1, 1, self.parent().width() - 2, self.parent().height() - 2)

class CustomGroupBox(QtWidgets.QGroupBox):
    def __init__(self, parent=None):
        super().__init__(parent)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setGeometry(self.parent().width() - self.width() - 2, 1, self.width(), self.height())
