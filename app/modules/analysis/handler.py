from fastapi import APIRouter, Request, Body
from app.engine import evaluate
from app.web import render
from app.errors import BusinessError
from app import store

router = APIRouter()


def _db_path():
    # 与 app.web 保持一致：运行时读取，便于测试通过 monkeypatch 切换 DB_PATH
    from app.main import DB_PATH
    return DB_PATH


@router.get('/analysis')
def page(request: Request):
    return render(request, 'analysis')


@router.post('/api/analysis')
def calculate(payload: dict = Body(default={})):
    # 仅重算到分析集（第 6 个模块），不触发锁库与冻结归档
    return evaluate(payload, until=6)


@router.post('/api/runs/{run_id}/membership/publish')
def publish(run_id: str, payload: dict = Body(...)):
    """整版发布成员版本。

    - 内容寻址：同一成员材料（digest 相同）重试返回同一版本，不新增版本。
    - 事务替换：发布在单个 SQLite 事务内完成，失败保留旧版。
    - 上游处置更新后 digest 变化，旧版本标记 superseded（旧成员结论失效），另立新版。
    """
    expected_digest = payload.get('digest')
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise BusinessError('BAD_DIGEST', '成员材料指纹缺失或格式错误')
    path = _db_path()
    result = store.get(path, run_id)
    current = result.get('analysis_membership')
    if not current:
        raise BusinessError('MEMBERSHIP_NOT_READY', '该批次尚未完成分析集裁决')
    if current['digest'] != expected_digest:
        raise BusinessError('STALE_MATERIAL', '上游处置已更新，成员材料已变化，请刷新后重算', 409)
    return store.publish_membership(path, run_id, current)


@router.get('/api/runs/{run_id}/membership')
def membership_versions(run_id: str):
    path = _db_path()
    store.get(path, run_id)
    return store.list_membership(path, run_id)


@router.get('/api/runs/{run_id}/membership/{version_id}')
def membership_detail(run_id: str, version_id: str):
    path = _db_path()
    store.get(path, run_id)
    return store.get_membership(path, run_id, version_id)
