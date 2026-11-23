import io
import json
import zipfile
from app.errors import BusinessError


def serialize(result):
    if not result.get('manifest') or not result.get('views'):
        raise BusinessError('INCOMPLETE_RUN', '批次尚未完成')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            'manifest.json',
            json.dumps({**result['manifest'], 'revision': result.get('revision', 1),
                        'status': result.get('status', '待复核'),
                        'locked_membership': result.get('locked_membership')},
                       ensure_ascii=False, indent=2))
        archive.writestr(
            'evidence.json',
            json.dumps({'counts': result['counts'], 'views': result['views'],
                        'quarantine': result['quarantine']},
                       ensure_ascii=False, indent=2))
        membership = result.get('analysis_membership')
        if membership:
            # 成员版本与方案/访视/偏离/复检凭证共用同一份成员材料
            archive.writestr(
                'analysis_membership.json',
                json.dumps({'digest': membership['digest'], 'sets': membership['sets'],
                            'locked_membership': result.get('locked_membership'),
                            'rows': membership['rows']}, ensure_ascii=False, indent=2))
    return buffer.getvalue()
