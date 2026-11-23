from fastapi import APIRouter, Request, Body
from app.engine import evaluate
from app.web import render
from app.errors import BusinessError
from app import store

router = APIRouter()


def _db_path():
    from app.main import DB_PATH
    return DB_PATH


@router.get('/locking')
def page(request: Request):
    return render(request, 'locking')


@router.post('/api/locking')
def calculate(payload: dict = Body(default={})):
    return evaluate(payload, until=7)


@router.post('/api/runs/{run_id}/lock')
def lock(run_id: str, payload: dict = Body(...)):
    """把锁库范围绑定到一个 current 成员版本（锁库范围冻结）。"""
    version_id = payload.get('version_id')
    if not isinstance(version_id, str) or not version_id:
        raise BusinessError('BAD_VERSION', '缺少成员版本号')
    path = _db_path()
    result = store.get(path, run_id)
    if result.get('balance', {}).get('status') != '可锁库':
        raise BusinessError('LOCK_BLOCKED', '仍有阻断项，不能冻结锁库范围', 409)
    membership = result.get('analysis_membership')
    if not membership:
        raise BusinessError('MEMBERSHIP_NOT_READY', '分析集尚未裁决，不能锁定')
    return store.lock_membership(path, run_id, version_id)
