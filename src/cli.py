"""Batch grading without opening the desktop UI."""
import argparse
import json
from pathlib import Path
import sys
import subprocess
from grader import Grader
from reports import save_report
from paths import natural_key


def main(argv=None):
    parser = argparse.ArgumentParser(description='SWLAB C/Python practice grader')
    parser.add_argument('submissions', type=Path, help='Student directory, or parent directory with --batch')
    definition = parser.add_mutually_exclusive_group(required=True)
    definition.add_argument('--cases', type=Path, help='Legacy unweighted test cases')
    definition.add_argument('--manifest', type=Path, help='Validated problem.yaml with case weights')
    parser.add_argument('--layout', type=Path, help='Submission mapping YAML (default: layout.local.yaml beside problem)')
    parser.add_argument('--records', type=Path, help='Directory for automatically saved grading runs')
    parser.add_argument('--batch', action='store_true')
    parser.add_argument('--roster', type=Path, help='CSV roster; include missing student folders (--manifest --batch)')
    parser.add_argument('--chapter')
    parser.add_argument('--problem')
    parser.add_argument('--source', dest='target_file')
    parser.add_argument('--mode', choices=['docker', 'windows', 'linux', 'wsl'], default='docker')
    parser.add_argument('--timeout', type=float)
    parser.add_argument('--image', default='grader-image')
    parser.add_argument('--output', type=Path, help='Optional export; manifest runs always save an archive')
    options = parser.parse_args(argv)
    try:
        if options.roster and not (options.manifest and options.batch):
            raise ValueError('--roster requires --manifest and --batch')
        if not options.submissions.is_dir():
            raise ValueError('Submission directory not found.')
        students = sorted((p for p in options.submissions.iterdir() if p.is_dir() and not p.name.startswith('.')), key=lambda p: natural_key(p.name)) if options.batch else [options.submissions]
        if not students and not options.roster:
            raise ValueError('No student directories found.')
        if options.manifest:
            if options.chapter or options.problem or options.target_file or options.timeout is not None:
                raise ValueError('With --manifest, define submission paths, source files and timeout in the manifest/layout.')
            if options.layout and not options.layout.is_file():
                raise ValueError('Layout file not found.')
            if options.output and options.output.suffix.lower() not in ('.json', '.csv'):
                raise ValueError('--output must be a .json or .csv file')
            from core.service import run_batch
            submissions = [{'student_id': p.name, 'path': str(p)} for p in students]
            if options.roster:
                from core.roster import roster_submissions
                submissions = roster_submissions(options.roster, options.submissions)
            archive, run = run_batch(options.manifest,
                submissions,
                records_dir=options.records, mode=options.mode, image=options.image, layout_path=options.layout)
            if options.output:
                from core.record import export_summary, atomic_text
                if options.output.suffix.lower() == '.csv':
                    export_summary(options.output, run)
                else:
                    atomic_text(options.output, json.dumps(run, ensure_ascii=False, indent=2))
            for row in run['results']:
                score = 'ungraded' if row['final_score'] is None else f"{row['final_score']}/{row['max_score']}"
                print(f"{row['student_id']}: {row['status']} {score}")
            print(f'Record: {archive}\nSummary: {archive.with_name("summary.csv")}')
            return 0 if all(r['status'] == 'graded' and r['passed_cases'] == r['case_count'] for r in run['results']) else 1
        grader = Grader()
        cases = grader.load_test_cases(options.cases)
        if not cases:
            raise ValueError('No enabled test cases found.')
        rows = []
        config = {**vars(options), 'timeout': options.timeout if options.timeout is not None else 10}
        for student in students:
            for row in grader.grade_student(student, cases, config):
                rows.append(dict(row, class_name=options.submissions.name if options.batch else student.parent.name, student=student.name, chapter=options.chapter, problem=options.problem))
        output = options.output or Path('reports/results.json')
        save_report(output, rows)
        print(f"{sum(r['passed'] for r in rows)}/{len(rows)} passed; report: {output}")
        return 0 if all(row['passed'] for row in rows) else 1
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
