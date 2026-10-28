import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from student_names import CACHE_NAME,read_student_names,save_student_names,fill_student_names,student_label


class StudentNamesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for target,value in [('paths.ROOT',self.root),('paths.ORIGIN',self.root/'origin')]:
            mock=patch(target,value);mock.start();self.addCleanup(mock.stop)

    def roster(self,year,filename,name):
        path=self.root/'testdata'/str(year)/filename;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(f'학번,이름,github\n101,{name},https://github.com/example/repo\n',encoding='utf-8-sig')
        return path

    def test_roster_names_are_scoped_by_year_course_and_numeric_division(self):
        self.roster(2025,'system_02.csv','이전 학생')
        self.roster(2026,'system_02.csv','현재 학생')
        self.roster(2026,'python_02.csv','다른 수업')
        self.assertEqual(read_student_names('system_2_2026'),{'101':'현재 학생'})
        self.assertEqual(read_student_names('system_2_2025'),{'101':'이전 학생'})
        self.assertEqual(read_student_names('system_3_2026'),{})

    def test_imported_names_survive_restart_without_original_csv_or_repository_url(self):
        self.roster(2026,'system_2.csv','이전 명단')
        save_student_names('system_2_2026',[dict(student_id='101',name='가져온 학생',url='https://private.example/repo')])
        cache=self.root/'origin/system_2_2026'/CACHE_NAME
        self.assertNotIn('https://',cache.read_text(encoding='utf-8'))
        self.assertEqual(read_student_names('system_2_2026')['101'],'가져온 학생')
        (self.root/'testdata/2026/system_2.csv').unlink()
        self.assertEqual(read_student_names('system_2_2026'),{'101':'가져온 학생'})

    def test_old_test_rosters_missing_and_invalid_cache(self):
        path=self.roster(2026,'python_test_3.csv','이름 확인')
        self.assertEqual(read_student_names('python_3_2026'),{'101':'이름 확인'})
        save_student_names('python_3_2026',[dict(student_id='101',name='로컬 이름')])
        cache=self.root/'origin/python_3_2026'/CACHE_NAME
        cache.write_text('invalid',encoding='utf-8')
        self.assertEqual(read_student_names('python_3_2026'),{'101':'이름 확인'})
        path.unlink();self.assertEqual(read_student_names('python_3_2026'),{})

    def test_enrich_legacy_rows_without_changing_identity_or_existing_names(self):
        self.roster(2026,'system_2.csv','명단 이름')
        rows=[dict(student='101',class_name='system_2_2026'),
              dict(student='101',class_name='system_2_2026',student_name='기존 이름'),dict(student='999')]
        fill_student_names(rows)
        self.assertEqual(rows[0]['student'],'101')
        self.assertEqual(student_label(rows[0]),'101 · 명단 이름')
        self.assertEqual(student_label(rows[1]),'101 · 기존 이름')
        self.assertEqual(student_label(rows[2]),'999')


    def test_grading_reports_keep_names_beside_ids(self):
        import csv
        from reports import CaseReport,summarize_cases
        from midterm_scoring import export_scores
        names={'101':'첫 학생'}
        report=CaseReport({'students':['101','102'],'student_names':names,'case_count':1},root=self.root/'reports')
        rows=[dict(student='101',student_name='첫 학생',case='one',passed=True,status='passed'),
              dict(student='102',student_name='',case='one',passed=False,status='wrong_answer')]
        report.save(rows,'completed')
        self.assertEqual([s['student_name'] for s in summarize_cases(rows,['101','102'],1,'completed',names)],['첫 학생',''])
        self.assertEqual(summarize_cases(rows)[0]['student_name'],'첫 학생')
        self.assertEqual(summarize_cases([dict(student='7',case='c',passed=True,status='passed')])[0]['student_name'],'')
        with (report.directory/'summary.csv').open(encoding='utf-8-sig',newline='') as stream:records=list(csv.DictReader(stream))
        self.assertEqual([(r['student'],r['student_name']) for r in records],[('101','첫 학생'),('102','')])
        with (report.directory/'cases.csv').open(encoding='utf-8-sig',newline='') as stream:cases=list(csv.DictReader(stream))
        self.assertEqual(cases[0]['student_name'],'첫 학생')
        path=self.root/'scores.csv'
        export_scores(path,[dict(student='101',student_name='첫 학생',status='graded',auto_score=1,final_score=1,max_score=10,reason='',problems={})])
        with path.open(encoding='utf-8-sig',newline='') as stream:score=next(csv.DictReader(stream))
        self.assertEqual((score['student'],score['student_name']),('101','첫 학생'))


if __name__=='__main__':unittest.main()
