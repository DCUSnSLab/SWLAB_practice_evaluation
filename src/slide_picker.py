"""Select lecture slides by title and problem, without entering page ranges."""
import re
from PyQt6.QtCore import Qt, QUrl, QItemSelectionModel, QSize
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QLabel, QSplitter,
    QAbstractItemView, QDialogButtonBox)
from paths import ROOT, safe_path


def problem_heading(text):
    heading = next((line.strip() for line in text.splitlines() if line.strip()), '')
    match = re.match(r'^(실습\s*문제|연습\s*문제|문제|실습|과제)\s*(\d+)\s*(?:번)?(.*)$', heading)
    if not match or (match[1] == '실습' and not match[3].strip()):
        return None
    kind = 'hw' if match[1].startswith(('연습', '과제')) else 'prob'
    return kind, int(match[2])


class SlidePicker(QDialog):
    def __init__(self, decks, chapter='', problem='', selection=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('문제 슬라이드 선택')
        self.resize(1150, 760)
        self.decks = decks
        self.selection = None
        self.initial_selection = selection or {}
        self.problem_hint = re.fullmatch(r'(prob|prod|hw)(\d+)', problem)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.chapter = QComboBox(); self.chapter.addItem('전체 장', None)
        for value in sorted({d['chapter'] for d in decks if d['chapter'] is not None}):
            self.chapter.addItem(f'{value}장', value)
        match = re.fullmatch(r'chap(\d+)', chapter)
        if match:
            self.chapter.setCurrentIndex(max(0, self.chapter.findData(int(match[1]))))
        self.deck = QComboBox()
        self.deck.setMinimumContentsLength(20)
        self.deck.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.chapter); row.addWidget(self.deck, 1)
        self.open_button = QPushButton('원본 PPT 열기'); self.open_button.clicked.connect(self.open_source)
        row.addWidget(self.open_button); layout.addLayout(row)
        self.search = QLineEdit(); self.search.setPlaceholderText('페이지 제목·본문 검색 (예: 복사, 실습 2)')
        layout.addWidget(self.search)
        layout.addWidget(QLabel('페이지를 클릭해 선택/해제하세요. 같은 문제의 설명·코드 페이지는 한 번에 선택할 수 있습니다.'))
        split = QSplitter()
        self.pages = QListWidget(); self.pages.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True)
        split.addWidget(self.pages); split.addWidget(self.preview); split.setSizes([480, 600]); layout.addWidget(split, 1)
        actions = QHBoxLayout()
        self.same_problem = QPushButton('같은 문제 페이지 모두 선택'); self.same_problem.clicked.connect(self.select_problem)
        self.clear_button = QPushButton('선택 해제'); self.clear_button.clicked.connect(self.pages.clearSelection)
        actions.addWidget(self.same_problem); actions.addWidget(self.clear_button); actions.addStretch(); layout.addLayout(actions)
        self.summary = QLabel(); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.use_button = buttons.button(QDialogButtonBox.StandardButton.Ok); self.use_button.setText('선택한 페이지 사용')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.accept_selection); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.chapter.currentIndexChanged.connect(self.populate_decks)
        self.deck.currentIndexChanged.connect(self.populate_pages)
        self.search.textChanged.connect(self.filter_pages)
        self.pages.itemSelectionChanged.connect(self.update_preview)
        self.populate_decks()

    def populate_decks(self):
        self.deck.blockSignals(True); self.deck.clear()
        for index, deck in enumerate(self.decks):
            if self.chapter.currentData() is None or deck['chapter'] == self.chapter.currentData():
                self.deck.addItem(deck['title'], index)
        previous = self.initial_selection.get('source')
        for index in range(self.deck.count()):
            if self.decks[self.deck.itemData(index)]['source'] == previous:
                self.deck.setCurrentIndex(index); break
        self.deck.blockSignals(False); self.populate_pages()

    def current_deck(self):
        index = self.deck.currentData()
        return self.decks[index] if index is not None else None

    def populate_pages(self):
        self.pages.blockSignals(True); self.pages.clear()
        deck = self.current_deck()
        for slide in deck['slides'] if deck else []:
            title = next((s for s in slide['text'].splitlines() if s.strip()), '(본문 텍스트 없음)')
            item = QListWidgetItem(f"{slide['page']}쪽 · {title}" + (' · 이미지 있음' if slide.get('has_images') else ''))
            item.setSizeHint(QSize(0, self.pages.fontMetrics().height() + 18))
            item.setData(Qt.ItemDataRole.UserRole, slide); item.setToolTip(slide['text'][:2000]); self.pages.addItem(item)
            previous = deck['source'] == self.initial_selection.get('source')
            key = problem_heading(slide['text'])
            hint = ('hw' if self.problem_hint[1] == 'hw' else 'prob', int(self.problem_hint[2])) if self.problem_hint else None
            if (previous and slide['page'] in self.initial_selection.get('pages', [])) or (not self.initial_selection and key and key == hint):
                item.setSelected(True)
        self.pages.blockSignals(False); self.filter_pages(); self.update_preview()
        if self.pages.selectedItems():
            first = self.pages.selectedItems()[0]
            self.pages.setCurrentItem(first, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.pages.scrollToItem(first)

    def filter_pages(self):
        query = self.search.text().strip().casefold()
        for index in range(self.pages.count()):
            item = self.pages.item(index)
            item.setHidden(query not in (item.text() + item.data(Qt.ItemDataRole.UserRole)['text']).casefold())

    def selected_slides(self):
        return [self.pages.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.pages.count()) if self.pages.item(i).isSelected()]

    def select_problem(self):
        item = self.pages.currentItem()
        key = problem_heading(item.data(Qt.ItemDataRole.UserRole)['text']) if item else None
        if not key:
            self.summary.setText('문제 번호가 있는 페이지를 먼저 클릭하세요. 번호가 없는 페이지는 직접 여러 쪽을 선택하세요.'); return
        self.search.clear(); self.pages.blockSignals(True); self.pages.clearSelection()
        for i in range(self.pages.count()):
            candidate = self.pages.item(i)
            candidate.setSelected(problem_heading(candidate.data(Qt.ItemDataRole.UserRole)['text']) == key)
        self.pages.blockSignals(False); self.update_preview()

    def update_preview(self):
        slides = self.selected_slides()
        keys = {key for slide in slides if (key := problem_heading(slide['text']))}
        images = sum(bool(s.get('has_images')) for s in slides)
        self.preview.setPlainText('\n\n'.join(f"── {s['page']}쪽 ──\n{s['text']}" for s in slides))
        text = f"선택 {len(slides)}쪽: " + ', '.join(str(s['page']) for s in slides)
        if len(keys) > 1: text += ' · 서로 다른 문제가 포함되어 있습니다. 한 문제씩 선택하세요.'
        if images: text += f' · 이미지가 있는 {images}쪽은 원본 PPT에서 확인하세요. 이미지 속 글자는 자동 추출되지 않습니다.'
        self.summary.setText(text)
        self.use_button.setEnabled(bool(slides) and len(keys) <= 1 and any(s['text'].strip() for s in slides))

    def accept_selection(self):
        if not self.use_button.isEnabled(): return
        slides = self.selected_slides(); deck = self.current_deck()
        keys = {key for s in slides if (key := problem_heading(s['text']))}
        self.selection = dict(source=deck['source'], title=deck['title'], chapter=deck['chapter'],
            pages=[s['page'] for s in slides], problem=list(next(iter(keys))) if keys else None,
            text='\n\n'.join(s['text'] for s in slides), has_images=any(s.get('has_images') for s in slides))
        self.accept()

    def open_source(self):
        deck = self.current_deck()
        if deck:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(safe_path(ROOT, deck['source']))))
