"""Display formatted cells while sorting by their actual values."""
from PyQt6.QtWidgets import QTableWidgetItem


class SortableItem(QTableWidgetItem):
    def __init__(self, text, value):
        super().__init__(str(text))
        self.sort_key = (value is None, value if value is not None else 0)

    def __lt__(self, other):
        return self.sort_key < other.sort_key


def student_sort_value(sid):
    sid = str(sid)
    return (0, int(sid), sid) if sid.isascii() and sid.isdigit() else (1, sid.casefold())
