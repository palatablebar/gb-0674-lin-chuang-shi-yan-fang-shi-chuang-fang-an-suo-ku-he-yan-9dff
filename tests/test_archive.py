from app.modules.archive.rules import freeze
from app.archive import serialize
from copy import deepcopy
import zipfile
import io
import json


def _locked(state):
    s = deepcopy(state)
    s['locked_membership'] = 'mv-' + s['analysis_membership']['digest'][:12]
    return s


def test_clean_frozen_only_after_lock(clean):
    # 未锁定成员版本前不可冻结
    assert clean['archive']['status'] == '待处理'
    assert freeze(_locked(clean))['status'] == '可冻结'


def test_dirty_not_frozen(sample):
    assert sample['archive']['status'] == '待处理'
    # 即使绑定成员版本，阻断未消除仍不可冻结
    s = _locked(sample)
    s['balance']['status'] = '待处理'
    assert freeze(s)['status'] == '待处理'


def test_subject_count(clean):
    assert clean['archive']['subjects'] == 20
    assert clean['archive']['results'] == 40


def test_locked_state_propagates(clean):
    s = _locked(clean)
    s['balance']['status'] = '待处理'
    assert freeze(s)['status'] == '待处理'


def test_seal_covers_results(clean):
    s = _locked(clean)
    s['selected_results'][0]['value_mg_dl'] = '999'
    assert freeze(s)['seal'] != freeze(_locked(clean))['seal']


def test_seal_covers_membership_binding(clean):
    base = freeze(_locked(clean))
    other = _locked(clean)
    other['locked_membership'] = 'mv-000000000000'
    assert freeze(other)['seal'] != base['seal']


def test_bundle_has_evidence(sample):
    z = zipfile.ZipFile(io.BytesIO(serialize(sample)))
    d = json.loads(z.read('evidence.json'))
    assert len(d['quarantine']) == 3
    # 冻结包含成员版本证据
    members = json.loads(z.read('analysis_membership.json'))
    assert members['digest'] == sample['analysis_membership']['digest']
    assert len(members['rows']) == 20


def test_manifest_digest(clean):
    z = zipfile.ZipFile(io.BytesIO(serialize(clean)))
    assert json.loads(z.read('manifest.json'))['sha256'] == clean['manifest']['sha256']
