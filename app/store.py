import sqlite3, json
from datetime import datetime, timezone
from pathlib import Path
from app.errors import BusinessError
from app.modules.archive.rules import freeze


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT '待复核', locked_membership TEXT)")
    # 旧库迁移：补齐锁定指针列（SQLite 不支持 IF NOT EXISTS 加列，先查后加，幂等）
    cols = {r['name'] for r in con.execute('PRAGMA table_info(runs)')}
    if 'locked_membership' not in cols:
        con.execute('ALTER TABLE runs ADD COLUMN locked_membership TEXT')
    con.execute("""CREATE TABLE IF NOT EXISTS membership_versions (
        run_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        digest TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'current',
        created_at TEXT NOT NULL,
        superseded_at TEXT,
        PRIMARY KEY (run_id, version_id))""")
    return con


def save(path, result):
    run_id = result['manifest']['run_id']
    with connect(path) as con:
        con.execute('INSERT OR IGNORE INTO runs(id,digest,result) VALUES(?,?,?)',
                    (run_id, result['manifest']['sha256'], json.dumps(result, ensure_ascii=False)))
    return get(path, run_id)


def get(path, run_id):
    with connect(path) as con:
        row = con.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise BusinessError('NOT_FOUND', '批次不存在', 404)
    result = json.loads(row['result'])
    result.update(revision=row['revision'], status=row['status'],
                  locked_membership=row['locked_membership'])
    return result


def history(path):
    with connect(path) as con:
        return [dict(r) for r in con.execute('SELECT id,revision,status FROM runs ORDER BY rowid DESC LIMIT 100')]


def review(path, run_id, revision):
    with connect(path) as con:
        cur = con.execute('UPDATE runs SET revision=revision+1,status=? WHERE id=? AND revision=?',
                          ('已复核', run_id, revision))
        if cur.rowcount != 1:
            if not con.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
                raise BusinessError('NOT_FOUND', '批次不存在', 404)
            raise BusinessError('STALE_VERSION', '复核版本已更新，请刷新', 409)
    return get(path, run_id)


def _now():
    return datetime.now(timezone.utc).isoformat()


def list_membership(path, run_id):
    with connect(path) as con:
        rows = con.execute(
            'SELECT run_id,version_id,digest,status,created_at,superseded_at FROM membership_versions '
            'WHERE run_id=? ORDER BY rowid', (run_id,)).fetchall()
    return [dict(r) for r in rows]


def get_membership(path, run_id, version_id):
    with connect(path) as con:
        row = con.execute('SELECT * FROM membership_versions WHERE run_id=? AND version_id=?',
                          (run_id, version_id)).fetchone()
    if not row:
        raise BusinessError('NOT_FOUND', '成员版本不存在', 404)
    data = dict(row)
    data['payload'] = json.loads(data['payload'])
    return data


def publish_membership(path, run_id, membership):
    """整版事务替换：同 digest 幂等返回；新 digest 令旧版失效并创建新版。

    任何一步失败都会随 with 块回滚，旧版本与旧锁定指针保持不变。
    """
    digest = membership['digest']
    version_id = f'mv-{digest[:12]}'
    now = _now()
    payload = json.dumps(membership, ensure_ascii=False, sort_keys=True)
    with connect(path) as con:
        existing = con.execute(
            'SELECT version_id,status FROM membership_versions WHERE run_id=? AND digest=?',
            (run_id, digest)).fetchone()
        if existing:
            # 同一材料重试：不新增成员版本，直接返回既有版本
            return get_membership(path, run_id, existing['version_id'])
        con.execute("UPDATE membership_versions SET status='superseded', superseded_at=? "
                    "WHERE run_id=? AND status='current'", (now, run_id))
        con.execute('INSERT INTO membership_versions(run_id,version_id,digest,payload,status,created_at) '
                    'VALUES(?,?,?,?,?,?)', (run_id, version_id, digest, payload, 'current', now))
    return get_membership(path, run_id, version_id)


def lock_membership(path, run_id, version_id):
    """把锁库范围绑定到一个 current 成员版本；绑定动作随事务原子完成。

    绑定后同步重算冻结清单，使封存印章包含锁定的成员版本指针。
    """
    with connect(path) as con:
        row = con.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise BusinessError('NOT_FOUND', '批次不存在', 404)
        ver = con.execute('SELECT status FROM membership_versions WHERE run_id=? AND version_id=?',
                          (run_id, version_id)).fetchone()
        if not ver:
            raise BusinessError('NOT_FOUND', '成员版本不存在，无法锁定', 404)
        if ver['status'] != 'current':
            raise BusinessError('VERSION_SUPERSEDED', '该成员版本已失效，请基于最新成员版本锁定', 409)
        result = json.loads(row['result'])
        result['locked_membership'] = version_id
        result['archive'] = freeze(result)
        con.execute('UPDATE runs SET locked_membership=?, result=? WHERE id=?',
                    (version_id, json.dumps(result, ensure_ascii=False), run_id))
    return get(path, run_id)
