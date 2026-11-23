from fastapi.testclient import TestClient
from app import main, store
from app.engine import evaluate
from copy import deepcopy


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', str(tmp_path / 'test.sqlite'))
    return TestClient(main.app)


def _clean_run(c):
    return c.post('/api/runs', json={'dataset': 'clean'}).json()


def test_publish_idempotent_same_material_no_new_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = _clean_run(c)
    rid, digest = run['manifest']['run_id'], run['analysis_membership']['digest']
    url = f'/api/runs/{rid}/membership/publish'
    first = c.post(url, json={'digest': digest})
    second = c.post(url, json={'digest': digest})
    third = c.post(url, json={'digest': digest})
    assert first.status_code == second.status_code == third.status_code == 200
    assert first.json()['version_id'] == second.json()['version_id'] == third.json()['version_id']
    versions = c.get(f'/api/runs/{rid}/membership').json()
    assert len(versions) == 1  # 同一材料重试不新增成员版本
    assert versions[0]['status'] == 'current'


def test_stale_material_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = _clean_run(c)
    rid = run['manifest']['run_id']
    resp = c.post(f'/api/runs/{rid}/membership/publish', json={'digest': 'a' * 64})
    assert resp.status_code == 409
    assert resp.json()['code'] == 'STALE_MATERIAL'


def test_bad_digest_shape(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = _clean_run(c)
    rid = run['manifest']['run_id']
    assert c.post(f'/api/runs/{rid}/membership/publish', json={'digest': 'short'}).status_code == 422


def test_upstream_update_supersedes_old_and_creates_new(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = _clean_run(c)
    rid, old_digest = run['manifest']['run_id'], run['analysis_membership']['digest']
    c.post(f'/api/runs/{rid}/membership/publish', json={'digest': old_digest})
    # 模拟上游处置更新后重新计算：直接在持久化结果上重放分析模块并改 digest
    db = str(tmp_path / 'test.sqlite')
    result = store.get(db, rid)
    result['context']['dosing_registry']['00006']['disposition'] = '首剂后退出'
    result['context']['dosing_registry']['00006']['disposition_at'] = '2026-10-20T00:00:00+08:00'
    from app.modules.analysis.rules import apply as apply_analysis
    apply_analysis(result)
    new_digest = result['analysis_membership']['digest']
    assert new_digest != old_digest
    # 同 run_id 下上游重算落库（处置更新改变成员材料，但输入快照批号不变）
    import sqlite3, json
    with sqlite3.connect(db) as con:
        con.execute('UPDATE runs SET result=? WHERE id=?', (json.dumps(result, ensure_ascii=False), rid))
    resp = c.post(f'/api/runs/{rid}/membership/publish', json={'digest': new_digest})
    assert resp.status_code == 200
    versions = c.get(f'/api/runs/{rid}/membership').json()
    statuses = {v['version_id']: v['status'] for v in versions}
    assert len(versions) == 2
    assert set(statuses.values()) == {'current', 'superseded'}  # 旧成员结论失效，另立新版


def test_lock_binds_current_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = _clean_run(c)
    rid, digest = run['manifest']['run_id'], run['analysis_membership']['digest']
    pv = c.post(f'/api/runs/{rid}/membership/publish', json={'digest': digest}).json()
    locked = c.post(f'/api/runs/{rid}/lock', json={'version_id': pv['version_id']})
    assert locked.status_code == 200
    assert locked.json()['locked_membership'] == pv['version_id']
    assert locked.json()['archive']['status'] == '可冻结'


def test_lock_blocked_when_balance_not_clean(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={}).json()  # dirty 批存在阻断
    rid, digest = run['manifest']['run_id'], run['analysis_membership']['digest']
    pv = c.post(f'/api/runs/{rid}/membership/publish', json={'digest': digest}).json()
    resp = c.post(f'/api/runs/{rid}/lock', json={'version_id': pv['version_id']})
    assert resp.status_code == 409
    assert resp.json()['code'] == 'LOCK_BLOCKED'


def test_cannot_lock_superseded_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = _clean_run(c)
    rid, digest = run['manifest']['run_id'], run['analysis_membership']['digest']
    pv = c.post(f'/api/runs/{rid}/membership/publish', json={'digest': digest}).json()
    db = str(tmp_path / 'test.sqlite')
    import sqlite3
    with sqlite3.connect(db) as con:
        con.execute("UPDATE membership_versions SET status='superseded' WHERE run_id=? AND version_id=?",
                    (rid, pv['version_id']))
    resp = c.post(f'/api/runs/{rid}/lock', json={'version_id': pv['version_id']})
    assert resp.status_code == 409
    assert resp.json()['code'] == 'VERSION_SUPERSEDED'


def test_failed_publish_keeps_old_version(tmp_path, monkeypatch):
    # 事务级验证：发布在单个事务内先标记旧版失效再插入新版；
    # 若插入因主键冲突失败，整个事务回滚，旧 current 版本保持不变。
    c = _client(tmp_path, monkeypatch)
    run = _clean_run(c)
    rid = run['manifest']['run_id']
    db = str(tmp_path / 'test.sqlite')
    v1 = store.publish_membership(db, rid, run['analysis_membership'])
    assert len(store.list_membership(db, rid)) == 1

    broken = deepcopy(run['analysis_membership'])
    broken['digest'] = 'd' * 64
    new_vid = 'mv-' + broken['digest'][:12]
    import sqlite3
    with sqlite3.connect(db) as con:
        # 预置同 version_id、不同 digest 的行：digest 幂等查不到，插入必冲突
        con.execute(
            "INSERT INTO membership_versions(run_id,version_id,digest,payload,status,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (rid, new_vid, 'e' * 64, '{}', 'current', '2026-01-01T00:00:00+00:00'))
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        store.publish_membership(db, rid, broken)

    versions = store.list_membership(db, rid)
    old = next(v for v in versions if v['version_id'] == v1['version_id'])
    assert old['status'] == 'current'  # 失效标记随事务回滚
    assert len(versions) == 2  # 仅旧版与预置冲突行，无半成品新版


def test_export_contains_membership_evidence(tmp_path, monkeypatch):
    import io, zipfile, json
    c = _client(tmp_path, monkeypatch)
    run = _clean_run(c)
    rid, digest = run['manifest']['run_id'], run['analysis_membership']['digest']
    pv = c.post(f'/api/runs/{rid}/membership/publish', json={'digest': digest}).json()
    c.post(f'/api/runs/{rid}/lock', json={'version_id': pv['version_id']})
    raw = c.get(f'/api/export/{rid}').content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert 'analysis_membership.json' in z.namelist()
        payload = json.loads(z.read('analysis_membership.json'))
        assert payload['locked_membership'] == pv['version_id']
        assert payload['digest'] == digest


def test_analysis_page_and_api(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = _clean_run(c)
    rid = run['manifest']['run_id']
    assert c.post('/api/analysis', json={'dataset': 'clean'}).status_code == 200
    html = c.get(f'/analysis?run_id={rid}')
    assert html.status_code == 200
    assert '分析集成员裁决' in html.text
    assert '00019' in html.text
