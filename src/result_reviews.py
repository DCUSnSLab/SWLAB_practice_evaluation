"""Read-only presentation of saved qualitative reviews in the execution results table."""
LABELS = {'ai_proposed': 'AI 제안', 'confirmed': '교수자 확정', 'error': '평가 실패', 'not_reviewed': '미평가',
          'submission_zero': '제출 상태 0점'}
HEADERS = ['정성 상태', '정성 품질 /100', '정성 제안 점수', '정성 확정 점수']


def one_line(text, limit=100):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def table_columns(reviews, all_problems=False):
    from midterm_scoring import PROBLEM_LABELS
    present = {row.get('problem') for row in reviews}
    problems = [p for p in [*PROBLEM_LABELS, '__all__'] if p in present]
    problems += sorted(present - set(problems), key=lambda p: str(p or ''))
    headers = [('정성 ' + ('전체' if p == '__all__' else PROBLEM_LABELS.get(p, str(p or '문제'))))
               if all_problems else '정성 점수' for p in problems]
    return problems, headers + ['정성 사유'] if problems else []


def short_reason(review):
    issue = review.get('submission_issue')
    if issue:
        return {'missing_folder': '폴더 없음', 'missing_file': '파일 없음',
                'no_sources': '소스 없음', 'empty_file': '빈 파일'}.get(issue, '제출 없음')
    if review['status'] == 'error':
        message = review.get('message', '')
        if '줄 번호' in message:
            return '평가 실패 · 근거 줄 번호 오류'
        if any(word in message for word in ('JSON', 'Unterminated', 'Expecting', 'Invalid control')):
            return '평가 실패 · 응답 형식 오류'
        if any(word in message for word in ('Cannot reach', 'timed out', 'HTTP', '연결')):
            return '평가 실패 · 서버 응답 오류'
        return '평가 실패' + (': ' + one_line(message, 45) if message else '')
    return ''


def table_cells(reviews, problems, all_problems=False):
    from midterm_scoring import PROBLEM_LABELS
    by_problem = {r.get('problem'): r for r in reviews}
    values = []
    reasons = []
    for problem in problems:
        review = by_problem.get(problem)
        score = None
        if review:
            if review['status'] in ('confirmed', 'submission_zero'):
                score = review.get('final_score')
            elif review['status'] == 'ai_proposed':
                score = review.get('suggested_score')
            reason = short_reason(review)
            if reason:
                label = '전체' if problem == '__all__' else PROBLEM_LABELS.get(problem, str(problem or '문제'))
                reasons.append(f'{label}: {reason}' if all_problems else reason)
        values.append(('—' if score is None else f'{score:g}', score))
    if reasons and any(r['status'] == 'ai_proposed' for r in reviews):
        reasons.insert(0, 'AI 제안 포함')
    reason = one_line(' · '.join(reasons))
    if not reason and reviews:
        reason = ('AI 제안' if any(r['status'] == 'ai_proposed' for r in reviews) else
                  '확정' if any(r['status'] == 'confirmed' for r in reviews) else '미평가')
    return [*values, (reason or '—', reason or None)]


def execution_reason(score, rows):
    """Collapse repeated missing/empty-case counts; preserve other grading explanations."""
    from midterm_scoring import PROBLEM_LABELS
    grouped = {}
    for target, problem in score['problems'].items():
        if problem['overrides']:
            return one_line(score['reason_short'])
        if problem['auto_score'] == problem['max_score']:
            continue
        own = [r for r in rows if r.get('target_file') == target]
        if own and all(r['status'] == 'missing_source' for r in own):
            reason = '폴더 없음' if all('Submission directory missing:' in r.get('message', '') for r in own) else '파일 없음'
        elif own and all(r['status'] == 'empty_source' for r in own):
            reason = '빈 파일'
        else:
            return one_line(score['reason_short'])
        grouped.setdefault(reason, []).append(PROBLEM_LABELS[target])
    if not grouped:
        return one_line(score['reason_short'])
    if len(grouped) == 1 and sum(map(len, grouped.values())) == len(score['problems']):
        return next(iter(grouped))
    return one_line(' · '.join('·'.join(labels) + ' ' + reason for reason, labels in grouped.items()))


def cells(reviews, all_problems=False):
    """Keep different problems separate; there is no implicit averaging or approval."""
    texts = [[] for _ in HEADERS]
    sorts = [None] * len(HEADERS)
    for review in reviews:
        prefix = (('전체' if review.get('problem') == '__all__' else str(review.get('problem') or '문제 없음')) + ': ') if all_problems else ''
        proposed = review.get('suggested_score')
        final = review.get('final_score') if review.get('status') in ('confirmed', 'submission_zero') else None
        quality = review.get('overall')
        maximum = review.get('max_score')
        values = [LABELS.get(review['status'], review['status']),
                  '—' if quality is None else f'{quality:g}',
                  '—' if proposed is None else f'{proposed:g} / {maximum:g}',
                  '—' if final is None else f'{final:g} / {maximum:g}']
        for index, value in enumerate(values):
            texts[index].append(prefix + value)
        if len(reviews) == 1:
            sorts = [values[0], quality, proposed, final]
    return [(' / '.join(text) if text else '—', sort) for text, sort in zip(texts, sorts)]


def details(review):
    parts = [f"정성평가 · {review.get('problem') or '문제 없음'} · {LABELS.get(review['status'], review['status'])}",
             f"DB 기록: {review['run_id']} · 평가/확정 시각: {review.get('saved_at') or '기록 없음'}"]
    values = cells([review])
    parts.append(' · '.join(f'{name}: {value[0]}' for name, value in zip(HEADERS[1:], values[1:])))
    for key in ('summary', 'message'):
        if review.get(key):
            parts.append(review[key])
    for criterion in review.get('criteria', []):
        score = '계산 제외' if criterion.get('applicable') is False else f"{criterion.get('score')} / {criterion.get('max_score')}"
        parts.append(f"{criterion['name']}: {score}\n{criterion.get('reason', '')}")
        for ref in criterion.get('evidence', []):
            parts.append(f"  {ref['file']}:{ref['line']}  {ref['code']}")
    if review.get('reviewer_note'):
        parts.append('교수자 검토 의견: ' + review['reviewer_note'])
    return '\n'.join(parts)
