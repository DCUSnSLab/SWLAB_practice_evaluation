import sys
from PyQt6.QtWidgets import QApplication
from src.evaluator import Evaluator
from src.gui import Gui

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = Gui()
    sys.exit(app.exec())