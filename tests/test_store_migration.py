import sqlite3


def test_old_schema_db_migrates_and_keeps_data(tmp_path):
    db = str(tmp_path / 'old.sqlite')
    con = sqlite3.connect(db)
    # 旧版表结构：无 locked_membership 列、无 membership_versions 表
    con.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, "
                "result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, "
                "status TEXT NOT NULL DEFAULT '待复核')")
    con.execute("INSERT INTO runs VALUES('r1','d','{}',1,'待复核')")
    con.commit()
    con.close()

    from app import store
    result = store.get(db, 'r1')  # 触发幂等迁移
    assert result['locked_membership'] is None
    store.get(db, 'r1')  # 再次连接不报错（迁移幂等）
    assert store.list_membership(db, 'r1') == []


def test_fresh_db_has_membership_table(tmp_path):
    from app import store
    from app.engine import evaluate
    db = str(tmp_path / 'new.sqlite')
    saved = store.save(db, evaluate({'dataset': 'clean'}))
    rid = saved['manifest']['run_id']
    ver = store.publish_membership(db, rid, saved['analysis_membership'])
    assert ver['status'] == 'current'
