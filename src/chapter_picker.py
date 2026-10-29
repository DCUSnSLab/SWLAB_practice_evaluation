"""Choose which recorded chapters go into one latest-gradebook CSV."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QDialogButtonBox)
from midterm import is_midterm
from paths import natural_key


class ChapterPicker(QDialog):
    def __init__(self, class_name, recorded, current='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('장 골라 CSV 내보내기')
        self.resize(420, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('CSV에 넣을 장을 고르세요. 저장된 채점·정성평가 기록이 있는 장만 보입니다.\n'
                                '고른 장은 학생별 최신 점수가 장·문제마다 한 행씩 한 파일에 들어갑니다.'))
        self.chapters = QListWidget()
        for chapter in sorted(recorded, key=natural_key):
            problems = [p for p in recorded[chapter] if p and p != '__all__']
            detail = '중간고사 전체 문제' if is_midterm(class_name, chapter) else f'문제 {len(problems) or 1}개'
            item = QListWidgetItem(f'{chapter} · {detail}')
            item.setData(Qt.ItemDataRole.UserRole, chapter)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if chapter == current else Qt.CheckState.Unchecked)
            self.chapters.addItem(item)
        self.chapters.itemChanged.connect(self.update_buttons)
        layout.addWidget(self.chapters, 1)
        row = QHBoxLayout()
        for text, state in [('전체 선택', Qt.CheckState.Checked), ('선택 해제', Qt.CheckState.Unchecked)]:
            button = QPushButton(text); button.clicked.connect(lambda _, s=state: self.check_all(s)); row.addWidget(button)
        row.addStretch(); layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok); self.ok_button.setText('CSV로 저장')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.update_buttons()

    def selected(self):
        return [self.chapters.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.chapters.count())
                if self.chapters.item(i).checkState() == Qt.CheckState.Checked]

    def check_all(self, state):
        for index in range(self.chapters.count()):
            self.chapters.item(index).setCheckState(state)

    def update_buttons(self):
        self.ok_button.setEnabled(bool(self.selected()))
