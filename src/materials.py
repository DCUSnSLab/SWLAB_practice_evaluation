"""Browse the supplied lecture decks without requiring PowerPoint."""
import json
from pathlib import Path
import re
import zipfile
import posixpath
from xml.etree import ElementTree as ET
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QTextBrowser, QPushButton, QLabel
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from paths import ROOT, natural_key, safe_path

NAMESPACE = '{http://schemas.openxmlformats.org/drawingml/2006/main}'


def read_deck(path):
    slides = []
    with zipfile.ZipFile(path) as archive:
        presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
        relationships = ET.fromstring(archive.read('ppt/_rels/presentation.xml.rels'))
        targets = {item.attrib['Id']: item.attrib['Target'] for item in relationships
                   if item.attrib.get('TargetMode') != 'External'}
        names = []
        for item in presentation.findall('.//{http://schemas.openxmlformats.org/presentationml/2006/main}sldId'):
            target = targets[item.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            names.append(posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'ppt/' + target))
        for page, name in enumerate(names, 1):
            root = ET.fromstring(archive.read(name))
            paragraphs = [''.join(t.text or '' for t in paragraph.iter(NAMESPACE + 't'))
                          for paragraph in root.iter(NAMESPACE + 'p')]
            slides.append({'page': page, 'text': '\n'.join(p for p in paragraphs if p.strip()),
                           'has_images': bool(root.findall('.//{http://schemas.openxmlformats.org/presentationml/2006/main}pic'))})
    return slides


def build_catalog():
    decks = []
    for path in sorted((ROOT / '강의자료').rglob('*.pptx'), key=lambda p: natural_key(p.name)):
        decks.append({'source': path.relative_to(ROOT).as_posix(), 'title': path.stem,
                      'chapter': int(re.match(r'\d+', path.name)[0]) if re.match(r'\d+', path.name) else None,
                      'slides': read_deck(path)})
    return decks


class MaterialsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('시스템 프로그래밍 실습 자료')
        self.resize(1000, 750)
        self.decks = build_catalog()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('원본 판본별 실습 내용입니다. 실행 결과 이미지와 코드는 원본 PPT에서 확인하세요.'))
        self.selector = QComboBox()
        self.selector.addItems([deck['title'] for deck in self.decks])
        layout.addWidget(self.selector)
        self.content = QTextBrowser()
        layout.addWidget(self.content)
        button = QPushButton('선택한 원본 PPT 열기')
        button.clicked.connect(self.open_source)
        layout.addWidget(button)
        self.selector.currentIndexChanged.connect(self.show_deck)
        self.show_deck()

    def show_deck(self):
        index = self.selector.currentIndex()
        if index < 0:
            self.content.setPlainText('강의자료 폴더에 PPTX 파일을 추가하세요.')
            return
        self.content.setPlainText('\n\n'.join(f"── 슬라이드 {s['page']} ──\n{s['text']}" for s in self.decks[index]['slides']))

    def open_source(self):
        if self.selector.currentIndex() >= 0:
            source = safe_path(ROOT, self.decks[self.selector.currentIndex()]['source'])
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(source)))


if __name__ == '__main__':
    output = ROOT / 'docs' / 'practice_catalog.json'
    output.parent.mkdir(exist_ok=True)
    decks = build_catalog()
    output.write_text(json.dumps(decks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(decks)} decks, {sum(len(d["slides"]) for d in decks)} slides -> {output}')
