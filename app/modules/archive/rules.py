import hashlib
import json


def freeze(state):
    basis = {
        'selected': state['selected_results'],
        'windows': state['windows'],
        'deviations': state['deviations'],
        'membership_digest': (state.get('analysis_membership') or {}).get('digest'),
        'locked_membership': state.get('locked_membership'),
    }
    seal = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
    lock_ready = state.get('balance', {}).get('status') == '可锁库' and bool(state.get('locked_membership'))
    return {
        'status': '可冻结' if lock_ready else '待处理',
        'seal': seal,
        'subjects': len(state['context']['subjects']),
        'results': len(state['selected_results']),
        'locked_membership': state.get('locked_membership') or '',
        'membership_digest': basis['membership_digest'] or '',
    }


def apply(state):
    state['archive'] = freeze(state)
    state['views']['archive'] = {
        'title': '冻结清单', 'rows': state['selected_results'],
        'metrics': {'受试者': state['archive']['subjects'], '结果': state['archive']['results'],
                    '状态': state['archive']['status']},
    }
