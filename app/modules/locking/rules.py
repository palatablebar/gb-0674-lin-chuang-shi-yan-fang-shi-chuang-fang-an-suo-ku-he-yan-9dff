def decide(state):
    c = state['counts']
    explained = len(state['records']) + len(state['quarantine']) + c['blank'] + c['duplicate'] + c['repeated_header']
    blocked = len(state['deviations']) + len(state['retest_issues']) + len(state['quarantine'])
    return {
        'input': c['input'], 'accepted': len(state['records']), 'quarantined': len(state['quarantine']),
        'row_balanced': c['input'] == explained,
        'completed': len(state['completed']),
        'expected': len(state['context']['subjects']) * len(state['context']['required_visits']),
        'deviations': len(state['deviations']), 'retest_issues': len(state['retest_issues']),
        'blocked': blocked,
        'status': '可锁库' if not blocked and c['input'] == explained else '待处理',
    }


def lock_scope(state):
    """锁库范围：以分析集成员版本为口径，逐集给出成员数与名单。

    锁库检查本身不要求数据零问题（dirty 批可查看范围），但冻结归档要求先消除阻断并锁定
    一个 current 成员版本。未给药者只出现在 FAS，不给药不进 SS/PPS。
    """
    membership = state.get('analysis_membership')
    if not membership:
        return {'ready': False, 'sets': [], 'note': '分析集尚未裁决'}
    sets = []
    for spec in membership['sets']:
        code = spec['set']
        members = [r['subject'] for r in membership['rows']
                   if any(m['set'] == code and m['included'] for m in r['memberships'])]
        sets.append({'set': code, 'set_name': spec['set_name'], 'size': len(members), 'members': members})
    return {
        'ready': True,
        'digest': membership['digest'],
        'sets': sets,
        'blocker_counts': membership['blocker_counts'],
        'note': '同一成员版本供方案、访视、偏离、复检与冻结凭证共用',
    }


def apply(state):
    state['balance'] = decide(state)
    state['lock_scope'] = lock_scope(state)
    state['views']['locking'] = {
        'title': '锁库闸门', 'rows': [state['balance']],
        'metrics': {'应访视': state['balance']['expected'], '已完成': state['balance']['completed'],
                    '阻断项': state['balance']['blocked']},
    }
