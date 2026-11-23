from app.engine import evaluate
from app.modules.analysis.rules import adjudicate_subject, membership_digest, REASON_TEXT
from copy import deepcopy


def _row(state, subject):
    return next(r for r in state['analysis_membership']['rows'] if r['subject'] == subject)


def _in_set(row, code):
    return next(m for m in row['memberships'] if m['set'] == code)


def test_never_dosed_kept_in_fas_only(sample):
    # 00019 随机后从未给药：FAS 保留，SS/PPS 排除，随机凭据仍在
    row = _row(sample, '00019')
    assert row['randomized'] is True
    assert row['dose_count'] == 0
    assert row['randomized_at']  # 随机凭据可追踪
    assert _in_set(row, 'FAS')['included'] is True
    assert _in_set(row, 'SS')['included'] is False
    assert _in_set(row, 'PPS')['included'] is False
    assert 'NEVER_DOSED' in row['blockers']


def test_first_dose_withdrawal_stays_in_safety_set(sample):
    # 00020 首剂后退出：给药即纳入 SS，偏离不剔除安全性成员
    row = _row(sample, '00020')
    assert row['dose_count'] == 1
    assert _in_set(row, 'FAS')['included'] is True
    assert _in_set(row, 'SS')['included'] is True
    assert 'DISCONTINUED_AFTER_FIRST_DOSE' in row['blockers']
    # V2 缺首次访视 -> PPS 排除，但 SS 不受影响
    assert _in_set(row, 'PPS')['included'] is False


def test_dosed_subject_with_deviation_not_removed_from_safety(sample):
    # 00001 窗外访视（重大偏离）：仍在 SS，仅 PPS 排除
    row = _row(sample, '00001')
    assert _in_set(row, 'SS')['included'] is True
    assert _in_set(row, 'PPS')['included'] is False
    assert 'MAJOR_DEVIATION' in row['blockers']


def test_retest_gap_does_not_exclude_pp(clean):
    # 00006 仅缺一次复检但完成主要终点：三集全入，不产生阻断
    row = _row(clean, '00006')
    assert row['dose_count'] == 1
    assert row['primary_endpoint_ok'] is True
    assert all(m['included'] for m in row['memberships'])
    assert row['blockers'] == []


def test_clean_set_sizes(clean):
    sizes = clean['analysis_membership']['set_sizes']
    # 干净批：20 随机，19 给药（00019 未给药），给药者主要终点均可评估且无重大偏离
    assert sizes['FAS'] == 20
    assert sizes['SS'] == 19
    assert sizes['PPS'] == 19


def test_membership_digest_deterministic(clean):
    a = evaluate({'dataset': 'clean'})
    b = evaluate({'dataset': 'clean'})
    assert a['analysis_membership']['digest'] == b['analysis_membership']['digest']


def test_digest_changes_when_upstream_disposition_updates(clean):
    before = clean['analysis_membership']['digest']
    changed = deepcopy(clean)
    # 上游处置更新：让 00006 退组，成员结论应变化 -> 指纹变化（旧版本据此失效）
    changed['context']['dosing_registry']['00006']['disposition'] = '首剂后退出'
    changed['context']['dosing_registry']['00006']['disposition_at'] = '2026-10-20T00:00:00+08:00'
    from app.modules.analysis.rules import apply as apply_analysis
    apply_analysis(changed)
    assert changed['analysis_membership']['digest'] != before
    row = _row(changed, '00006')
    assert 'DISCONTINUED_AFTER_FIRST_DOSE' in row['blockers']
    # 退出但已给药且终点可评估：SS 仍在
    assert _in_set(row, 'SS')['included'] is True


def test_evidence_refs_present_for_dosed(clean):
    row = _row(clean, '00002')
    assert row['evidence_refs'] == ['DOSE-00002-01']


def test_reason_text_complete(sample):
    for row in sample['analysis_membership']['rows']:
        assert row['blocker_text']
        for code in row['blockers']:
            assert code in REASON_TEXT
