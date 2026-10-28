import json
import os
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PyQt6.QtWidgets import QApplication,QTableWidgetSelectionRange
from PyQt6.QtCore import Qt,QItemSelectionModel,QPoint
from PyQt6.QtTest import QTest,QSignalSpy
from qualitative import DEFAULT_RUBRIC,validate_review,confirm_review,load_reviews,save_reviews
from qualitative_gui import QualitativeWindow


class QualitativeSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        config=patch.dict(os.environ,{'SWLAB_LLM_URL':'https://example.invalid/v1','SWLAB_LLM_MODEL':'test-model'})
        config.start();self.addCleanup(config.stop)
        root=patch('qualitative_gui.ROOT',self.root);root.start();self.addCleanup(root.stop)
        self.submissions=[]
        for student in ('101','102','103'):
            path=self.root/student;path.mkdir();(path/'main.c').write_text(f'int student_{student}=0;')
            self.submissions.append(dict(class_name='system_3_2026',student=student,chapter='chap1',problem='prob1',path=str(path)))
        self.raw=dict(summary='평가 결과',strengths=[],improvements=[],uncertainties=[],criteria=[
            dict(id=r['id'],score=5,assessment='코드 확인',suggestion='요구사항 확인',evidence=[]) for r in DEFAULT_RUBRIC])
        self.payload={'choices':[{'message':{'content':json.dumps(self.raw)},'finish_reason':'stop'}]}
        self.window=QualitativeWindow(self.submissions)
        self.addCleanup(self.window.close)
        self.window.problem_text.setPlainText('정수를 화면에 출력한다.')

    def select(self,*indices):
        self.window.table.clearSelection()
        for i in indices:self.window.table.setRangeSelected(QTableWidgetSelectionRange(i,0,i,self.window.table.columnCount()-1),True)

    def finish(self):
        deadline=time.monotonic()+5
        while self.window.worker.isRunning() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(self.window.worker.isRunning())

    def proposed_row(self,index,score=5):
        raw=deepcopy(self.raw)
        for criterion in raw['criteria']:criterion['score']=score
        row=validate_review(raw,DEFAULT_RUBRIC,{'main.c':'line'})
        row.update({k:v for k,v in self.submissions[index].items() if k!='path'})
        row.update(status='ai_proposed',final_score=None,reviewer_note='')
        return row

    def test_header_sorting_keeps_student_selection_details_and_search_aligned(self):
        w=self.window
        w.rows=[self.proposed_row(i,score) for i,score in enumerate((10,2,9))]
        for row,name in zip(w.rows,('다학생','가학생','나학생')):
            row.update(student_name=name,summary=row['student']+' 평가')
        w.refresh_rows();w.select_rows([0,2])
        self.assertEqual([w.table.horizontalHeaderItem(i).text() for i in range(2)],['학번','이름'])
        w.table.sortItems(4,Qt.SortOrder.AscendingOrder)
        self.assertEqual([w.table.item(i,0).text() for i in range(3)],['102','103','101'])
        self.assertEqual(w.selected_indices(),[0,2]);self.assertEqual(w.current_index(),0)
        self.assertIn('101 평가',w.detail.toPlainText())
        w.table.sortItems(4,Qt.SortOrder.DescendingOrder)
        self.assertEqual([w.table.item(i,0).text() for i in range(3)],['101','103','102'])
        w.show();self.app.processEvents()
        header=w.table.horizontalHeader()
        point=QPoint(header.sectionViewportPosition(1)+header.sectionSize(1)//2,header.height()//2)
        orders=[]
        for _ in range(2):
            QTest.mouseClick(header.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point)
            order=header.sortIndicatorOrder();orders.append(order)
            expected=['102','103','101'] if order==Qt.SortOrder.AscendingOrder else ['101','103','102']
            self.assertEqual([w.table.item(i,0).text() for i in range(3)],expected)
            self.assertEqual(w.selected_indices(),[0,2])
        self.assertNotEqual(*orders)
        w.student_search.setText('102')
        self.assertEqual(w.current_index(),1)
        self.assertIn('102 평가',w.detail.toPlainText())
        self.assertEqual(w.selected_indices(),[0,2])
        order=header.sortIndicatorOrder();w.refresh_rows()
        self.assertEqual(header.sortIndicatorOrder(),order)
        self.assertEqual(w.current_index(),1);self.assertEqual(w.selected_indices(),[0,2])

    def test_sorted_review_and_approval_target_only_selected_student(self):
        w=self.window
        w.select_submissions([{**s,'student_name':n} for s,n in zip(self.submissions,('나학생','가학생','다학생'))])
        for i in range(3):w.rows[i]={**self.proposed_row(i),'student_name':w.rows[i]['student_name']}
        w.refresh_rows();w.select_rows([1])
        w.table.sortItems(1,Qt.SortOrder.DescendingOrder)
        self.assertEqual(w.table.item(2,0).text(),'102')
        self.assertEqual(w.current_index(),1)
        with patch('llm_cases.LLMClient._request',return_value=self.payload) as request:
            w.start_button.click();self.finish()
        self.assertEqual(request.call_count,1)
        sent=json.loads(request.call_args.args[1]['messages'][1]['content'])
        self.assertIn('student_102',sent['source_files']['main.c'])
        self.assertEqual(w.selected_indices(),[1]);self.assertEqual(w.current_index(),1)
        w.batch_confirm_button.click()
        self.assertEqual([row['final_score'] for row in w.rows],[None,50,None])
        self.assertEqual(load_reviews(w.archive)['results'],w.rows)
        w.table.sortItems(5,Qt.SortOrder.AscendingOrder)
        self.assertEqual(w.table.item(0,0).text(),'102')
        self.assertEqual(w.current_index(),1)
        self.assertEqual(w.final_score.value(),50)

    def test_student_search_jumps_cycles_and_shows_details_without_changing_selection(self):
        w=self.window
        w.rows=[self.proposed_row(i) for i in range(3)]
        for row in w.rows:row['summary']=f"{row['student']} 학생 평가"
        w.refresh_rows();self.select(0,2)
        w.student_search.setText(' 102 ')
        self.assertEqual(w.table.currentRow(),1)
        self.assertIn('102 학생 평가',w.detail.toPlainText())
        self.assertEqual(w.search_result.text(),'1/1명')
        self.assertEqual(w.selected_indices(),[0,2])
        w.student_search.setText('10')
        self.assertEqual(w.table.currentRow(),0)
        self.assertEqual(w.search_result.text(),'1/3명')
        QTest.keyClick(w.student_search,Qt.Key.Key_Return)
        self.assertEqual(w.table.currentRow(),1)
        self.assertIn('102 학생 평가',w.detail.toPlainText())
        w.find_next_button.click();self.assertEqual(w.table.currentRow(),2)
        self.assertIn('103 학생 평가',w.detail.toPlainText())
        w.find_next_button.click();self.assertEqual(w.table.currentRow(),0)
        self.assertEqual(w.selected_indices(),[0,2])
        w.student_search.setText('999')
        self.assertEqual(w.search_result.text(),'검색 결과 없음')
        self.assertFalse(w.find_next_button.isEnabled())
        self.assertEqual(w.table.currentRow(),0)
        w.student_search.clear()
        self.assertEqual(w.search_result.text(),'')
        self.assertEqual(w.selected_indices(),[0,2])

    def test_names_survive_review_csv_and_report_reload_without_entering_model_request(self):
        w=self.window
        w.select_submissions([{**self.submissions[1],'student_name':'이름표시학생'}])
        self.assertEqual(w.table.item(1,0).text(),'102')
        self.assertEqual(w.table.item(1,1).text(),'이름표시학생')
        with patch('llm_cases.LLMClient._request',return_value=self.payload) as request:
            w.start_button.click();self.finish()
        self.assertNotIn('이름표시학생',json.dumps(request.call_args.args[1],ensure_ascii=False))
        self.assertEqual(w.rows[1]['student_name'],'이름표시학생')
        self.assertEqual(load_reviews(w.archive)['results'][1]['student_name'],'이름표시학생')
        import csv
        path=self.root/'names.csv';save_reviews(path,w.rows,w.context)
        with path.open(encoding='utf-8-sig',newline='') as stream:records=list(csv.DictReader(stream))
        self.assertEqual(records[1]['student'],'102')
        self.assertEqual(records[1]['student_name'],'이름표시학생')
        reopened=QualitativeWindow([]);self.addCleanup(reopened.close)
        with patch('qualitative_gui.QFileDialog.getOpenFileName',return_value=(str(w.archive),'')):
            reopened.open_report()
        self.assertEqual(reopened.table.item(1,0).text(),'102')
        self.assertEqual(reopened.table.item(1,1).text(),'이름표시학생')

    def test_search_prefers_exact_id_and_tracks_updated_roster(self):
        w=self.window
        w.rows[0]['student']='001020';w.rows[1]['student']='00102';w.rows[2]['student']='001021'
        w.refresh_rows();w.student_search.setText('00102')
        self.assertEqual(w.table.item(w.table.currentRow(),0).text(),'00102')
        self.assertEqual(w.search_result.text(),'1/3명')
        w.rows=[w.rows[2]];w.refresh_rows()
        self.assertEqual(w.search_result.text(),'1/1명')
        w.find_next_button.click();self.assertEqual(w.table.item(w.table.currentRow(),0).text(),'001021')
        w.rows=[];w.refresh_rows()
        self.assertEqual(w.search_result.text(),'검색 결과 없음')
        self.assertFalse(w.find_next_button.isEnabled())

    def test_select_missing_proposals_includes_errors_but_preserves_zero_and_confirmed_scores(self):
        w=self.window
        w.rows[1]={**w.rows[1],'status':'error','message':'응답 실패'}
        zero=self.proposed_row(2,0);w.rows[2]=zero;w.refresh_rows()
        w.select_unreviewed_button.click()
        self.assertEqual(w.selected_indices(),[0,1])
        self.assertEqual(w.start_button.text(),'선택 2명 일괄 정성평가')
        confirm_review(zero,0,'0점 제안 검토 완료')
        before=deepcopy(zero)
        w.refresh_rows();w.select_unreviewed_button.click()
        self.assertEqual(w.selected_indices(),[0,1])
        with patch('llm_cases.LLMClient._request',return_value=self.payload) as request:
            w.start_button.click();self.finish()
        self.assertEqual(request.call_count,2)
        self.assertEqual(w.rows[2],before)
        self.assertEqual(load_reviews(w.archive)['results'],w.rows)
        w.select_unreviewed_button.click()
        self.assertEqual(w.selected_indices(),[])
        self.assertFalse(w.start_button.isEnabled())
        self.assertIn('0명 선택',w.status.text())

    def test_arrow_keys_update_current_details_without_changing_bulk_selection(self):
        w=self.window
        first=self.proposed_row(0);first.update(summary='첫 학생 평가',reviewer_note='첫 검토')
        second=self.proposed_row(1);second['summary']='둘째 학생 평가';confirm_review(second,75,'둘째 검토')
        w.rows=[first,second,{**w.rows[2],'status':'error','message':'셋째 학생 응답 실패'}]
        w.refresh_rows();self.select(0)
        w.table.setCurrentCell(0,0,QItemSelectionModel.SelectionFlag.NoUpdate)
        w.show();w.table.setFocus();self.app.processEvents()
        selection_changes=QSignalSpy(w.table.itemSelectionChanged)
        QTest.keyClick(w.table,Qt.Key.Key_Down)
        self.assertEqual(w.table.currentRow(),1)
        self.assertIn('둘째 학생 평가',w.detail.toPlainText())
        self.assertEqual(w.final_score.value(),75)
        self.assertEqual(w.note.toPlainText(),'둘째 검토')
        QTest.keyClick(w.table,Qt.Key.Key_Down)
        self.assertEqual(w.detail.toPlainText(),'셋째 학생 응답 실패')
        self.assertEqual(w.final_score.value(),0);self.assertEqual(w.note.toPlainText(),'')
        w.rows[2]=w.unreviewed_row(self.submissions[2]);w.refresh_rows()
        self.assertIn('아직 정성평가하지 않은',w.detail.toPlainText())
        QTest.keyClick(w.table,Qt.Key.Key_Up)
        self.assertIn('둘째 학생 평가',w.detail.toPlainText())
        QTest.keyClick(w.table,Qt.Key.Key_Up)
        self.assertIn('첫 학생 평가',w.detail.toPlainText())
        self.assertEqual(w.note.toPlainText(),'첫 검토')
        self.assertEqual(w.selected_indices(),[0])
        self.assertEqual(len(selection_changes),0)

    def test_only_current_selection_is_requested_and_other_reviews_are_preserved(self):
        w=self.window
        self.assertEqual(w.selected_indices(),[0,1,2])
        self.assertEqual(w.table.rowCount(),3)
        self.assertEqual([r['status'] for r in w.rows],['not_reviewed']*3)
        existing=validate_review(self.raw,DEFAULT_RUBRIC,{'main.c':'line'})
        existing.update({k:v for k,v in self.submissions[0].items() if k!='path'})
        existing.update(status='ai_proposed',final_score=None,reviewer_note='')
        confirm_review(existing,75,'이미 확정한 점수')
        w.rows[0]=existing;w.refresh_rows();before=deepcopy(w.rows)
        self.select(1)
        self.assertEqual(w.start_button.text(),'선택 1명 일괄 정성평가')
        with patch('llm_cases.LLMClient._request',return_value=self.payload) as request:
            w.start_button.click();self.finish()
        self.assertEqual(request.call_count,1)
        sent=json.loads(request.call_args.args[1]['messages'][1]['content'])
        self.assertIn('student_102',sent['source_files']['main.c'])
        self.assertEqual(w.rows[0],before[0])
        self.assertEqual(w.rows[2],before[2])
        self.assertEqual(len(w.rows),3)
        self.assertEqual(w.rows[1]['status'],'ai_proposed')
        self.assertEqual(w.selected_indices(),[1])
        self.assertEqual(w.progress.maximum(),1);self.assertEqual(w.progress.value(),1)
        self.assertEqual([s['student'] for s in w.context['submissions']],['102'])
        self.assertEqual(load_reviews(w.archive)['results'],w.rows)

    def test_empty_or_unresolvable_selection_never_falls_back_to_all(self):
        w=self.window;self.select()
        before=deepcopy(w.rows)
        with patch('llm_cases.LLMClient._request') as request:
            self.assertFalse(w.start_button.isEnabled())
            w.start();request.assert_not_called()
            self.assertIn('선택하세요',w.status.text())
            self.select(1);w.submissions=[]
            w.start();request.assert_not_called()
            self.assertIn('로컬 제출 경로',w.status.text())
        self.assertIsNone(w.archive);self.assertEqual(w.rows,before)

    def test_cancellation_and_midrun_selection_changes_keep_run_targets_fixed(self):
        w=self.window;self.select(0,2)
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        def request(*args):
            entered.set()
            if not release.wait(3):raise ValueError('test request timed out')
            return self.payload
        with patch('llm_cases.LLMClient._request',side_effect=request) as network:
            w.start()
            self.assertTrue(entered.wait(2))
            self.assertEqual([s['student'] for s in w.worker.arguments[3]],['101','103'])
            self.assertFalse(w.select_unreviewed_button.isEnabled())
            w.select_unreviewed_button.click()
            self.assertEqual(w.selected_indices(),[0,2])
            w.table.selectAll()
            self.assertFalse(w.start_button.isEnabled())
            w.cancel_button.click();release.set();self.finish()
        self.assertEqual(network.call_count,1)
        self.assertEqual(w.context['run_state'],'cancelled')
        self.assertEqual([r['status'] for r in w.rows],['ai_proposed','not_reviewed','not_reviewed'])
        self.assertEqual(w.progress.maximum(),2);self.assertEqual(w.progress.value(),1)
        self.assertEqual([s['student'] for s in w.context['submissions']],['101','103'])
        self.assertEqual(load_reviews(w.archive)['results'],w.rows)

    def test_unreviewed_report_rejects_scores(self):
        path=self.root/'report.json'
        row=deepcopy(self.window.rows[0]);row['final_score']=100
        save_reviews(path,[row],{})
        with self.assertRaises(ValueError):load_reviews(path)


if __name__=='__main__':unittest.main()
