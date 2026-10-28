"""Read-only presentation of saved qualitative reviews in the execution results table."""
LABELS = {'ai_proposed': 'AI 제안', 'confirmed': '교수자 확정', 'error': '평가 실패', 'not_reviewed': '미평가'}
HEADERS = ['정성 상태', '정성 품질 /100', '정성 제안 점수', '정성 확정 점수']


def cells(reviews, all_problems=False):
    """Keep different problems separate; there is no implicit averaging or approval."""
    texts = [[] for _ in HEADERS]
    sorts = [None] * len(HEADERS)
    for review in reviews:
        prefix = (('전체' if review.get('problem') == '__all__' else str(review.get('problem') or '문제 없음')) + ': ') if all_problems else ''
        proposed = review.get('suggested_score')
        final = review.get('final_score') if review.get('status') == 'confirmed' else None
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
