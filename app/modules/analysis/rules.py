"""分析集裁决（M7）。

成员归属完全由上游证据派生，不在此处接受人工改判：
- FAS 全分析集：已随机化即入集；随机后从未给药者仍保留，其随机与随访凭据可追踪。
- SS 安全性集：随机化后至少实际给药一次即入集；方案偏离不剔除成员，只作为依据登记。
- PPS 符合方案集：已给药、主要终点可评估、且无重大方案偏离。仅缺一次复检但主要终点
  完成者不剔除（复检只替代测量值，不构成完成度或重大偏离判定）。

阻断原因与每条入/出集结论同时输出，页面与冻结凭证共用同一份成员版本。
"""
import hashlib
import json

SETS = (
    ('FAS', '全分析集'),
    ('SS', '安全性集'),
    ('PPS', '符合方案集'),
)

# 阻断原因码 -> 中文说明与受影响分析集
REASON_TEXT = {
    'NOT_RANDOMIZED': '未随机化，不进入任何分析集',
    'NEVER_DOSED': '随机后从未给药：排除出 SS/PPS，保留 FAS，随机与随访凭据留存',
    'DISCONTINUED_AFTER_FIRST_DOSE': '首剂后退出：仍属 SS（给药即纳入安全性监测），主要终点不可评估则排除 PPS',
    'MAJOR_DEVIATION': '重大方案偏离（缺首次访视/重复首次/窗外访视/采信隔离）：排除 PPS',
    'PRIMARY_ENDPOINT_NOT_EVALUABLE': '主要终点访视 V2 不可评估：排除 PPS',
    'RETEST_GAP_ONLY': '仅缺一次复检，主要终点已完成：不剔除 PPS',
}

# 偏离/隔离原因码是否构成“重大方案偏离”
MAJOR_DEVIATION_CODES = {
    'MISSING_PRIMARY', 'DUPLICATE_PRIMARY', 'WINDOW_EARLY', 'WINDOW_LATE',
    'PROTOCOL_MISMATCH', 'ENROLLMENT_CONFLICT', 'BAD_KIND', 'UNKNOWN_VISIT',
}


def _subject_deviation_index(state):
    """受试者 -> 该受试者的重大偏离原因码集合（含偏离复核与采信隔离证据）。"""
    major = {}
    for issue in state.get('deviations', []):
        code = issue.get('code', '')
        if code in MAJOR_DEVIATION_CODES:
            major.setdefault(issue['subject'], set()).add(code)
    for row in state.get('quarantine', []):
        sid = (row.get('raw') or {}).get('subject', '')
        code = row.get('code', '')
        if sid and code in MAJOR_DEVIATION_CODES:
            major.setdefault(sid, set()).add(code)
    return major


def _evaluable_visits(state, subject):
    """该受试者可评估的访视（偏离复核判定完成的首次记录）。"""
    return {row['visit'] for row in state.get('completed', []) if row['subject'] == subject}


def _registry(context, subject):
    reg = context.get('dosing_registry', {}).get(subject)
    if reg is None:
        # 兼容未登记处置的旧上下文：按已入组但无给药凭据处理，阻断原因显式可见。
        return {'randomized_at': None, 'doses': [], 'disposition': '处置未登记', 'disposition_at': None}
    return reg


def adjudicate_subject(subject, state):
    context = state['context']
    reg = _registry(context, subject)
    randomized = bool(reg.get('randomized_at'))
    dosed = bool(reg.get('doses'))
    disposition = reg.get('disposition') or ''
    evaluable = _evaluable_visits(state, subject)
    endpoint_visits = list(context['required_visits'])
    primary_endpoint = endpoint_visits[-1]
    endpoint_ok = primary_endpoint in evaluable
    major = sorted(_subject_deviation_index(state).get(subject, set()))

    memberships = []
    blockers = []

    if not randomized:
        blockers.append('NOT_RANDOMIZED')
    if randomized and not dosed:
        blockers.append('NEVER_DOSED')
    if dosed and '退出' in disposition:
        blockers.append('DISCONTINUED_AFTER_FIRST_DOSE')
    if major:
        blockers.append('MAJOR_DEVIATION')
    if dosed and not endpoint_ok:
        blockers.append('PRIMARY_ENDPOINT_NOT_EVALUABLE')

    # FAS：随机化即入集（含从未给药者）
    fas_in = randomized
    memberships.append({
        'set': 'FAS', 'set_name': SETS[0][1], 'included': fas_in,
        'basis': '已随机化' if fas_in else REASON_TEXT['NOT_RANDOMIZED'],
    })

    # SS：实际给药一次即入集；方案偏离不剔除
    ss_in = randomized and dosed
    ss_basis = '随机化后至少实际给药一次，方案偏离不剔除' if ss_in else (
        REASON_TEXT['NEVER_DOSED'] if randomized else REASON_TEXT['NOT_RANDOMIZED'])
    memberships.append({'set': 'SS', 'set_name': SETS[1][1], 'included': ss_in, 'basis': ss_basis})

    # PPS：给药 + 无重大偏离 + 主要终点可评估；仅缺复检不剔除
    pps_block = []
    if not ss_in:
        pps_block.append('NEVER_DOSED' if randomized else 'NOT_RANDOMIZED')
    if major:
        pps_block.append('MAJOR_DEVIATION')
    if not endpoint_ok:
        pps_block.append('PRIMARY_ENDPOINT_NOT_EVALUABLE')
    pps_in = ss_in and not major and endpoint_ok
    if pps_in:
        pps_basis = '已给药、无重大偏离、主要终点 %s 可评估' % primary_endpoint
    else:
        pps_basis = '；'.join(REASON_TEXT[c] for c in dict.fromkeys(pps_block))
    memberships.append({'set': 'PPS', 'set_name': SETS[2][1], 'included': pps_in, 'basis': pps_basis})

    return {
        'subject': subject,
        'randomized': randomized,
        'randomized_at': reg.get('randomized_at') or '',
        'dose_count': len(reg.get('doses', [])),
        'first_dose_at': (reg['doses'][0]['at'] if reg.get('doses') else ''),
        'disposition': disposition,
        'disposition_at': reg.get('disposition_at') or '',
        'evaluable_visits': sorted(evaluable),
        'primary_endpoint': primary_endpoint,
        'primary_endpoint_ok': endpoint_ok,
        'major_deviations': major,
        'memberships': memberships,
        'blockers': blockers,
        'blocker_text': '；'.join(REASON_TEXT[c] for c in dict.fromkeys(blockers)) or '无阻断',
        'evidence_refs': [d.get('evidence', '') for d in reg.get('doses', []) if d.get('evidence')],
    }


def membership_digest(rows):
    """成员版本内容指纹：同一成员材料重算得到同一指纹，不产生新版本。"""
    payload = [{
        'subject': r['subject'],
        'memberships': [(m['set'], m['included'], m['basis']) for m in r['memberships']],
        'blockers': r['blockers'],
        'dose_count': r['dose_count'],
    } for r in rows]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def apply(state):
    rows = [adjudicate_subject(sid, state) for sid in sorted(state['context']['subjects'])]
    digest = membership_digest(rows)
    counts = {code: sum(code in r['blockers'] for r in rows) for code in REASON_TEXT}
    set_sizes = {code: sum(any(m['set'] == code and m['included'] for m in r['memberships']) for r in rows)
                 for code, _ in SETS}
    state['analysis_membership'] = {
        'rows': rows,
        'digest': digest,
        'set_sizes': set_sizes,
        'blocker_counts': {k: v for k, v in counts.items() if v},
        'sets': [{'set': c, 'set_name': n, 'size': set_sizes[c]} for c, n in SETS],
    }
    state['views']['analysis'] = {
        'title': '分析集成员裁决',
        'rows': rows,
        'metrics': {
            'FAS 全分析集': set_sizes['FAS'],
            'SS 安全性集': set_sizes['SS'],
            'PPS 符合方案集': set_sizes['PPS'],
            '阻断受试者': sum(1 for r in rows if r['blockers']),
        },
    }
