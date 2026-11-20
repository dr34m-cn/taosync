import hashlib
import hmac
import re
import secrets

from common import sqlBase


def _digest(key):
    return hashlib.sha256(key.encode('ascii')).hexdigest()


def status():
    return {'enabled': bool(sqlBase.fetchall('select 1 from api_key where slot=1'))}


@sqlBase.connect_sql
def change(conn, action, userId):
    if action == 'disable':
        conn.execute('delete from api_key where slot=1')
        conn.commit()
        return {'enabled': False}
    if action not in ('enable', 'reset'):
        raise ValueError('未知的 API 密钥操作')
    key = secrets.token_hex(32)
    if action == 'enable':
        updated = conn.execute('insert or ignore into api_key(slot, userId, digest) values (1, ?, ?)',
                               (userId, _digest(key)))
    else:
        updated = conn.execute('update api_key set digest=?, userId=? where slot=1', (_digest(key), userId))
        if not updated.rowcount:
            raise ValueError('请先开启 API 密钥')
    conn.commit()
    return {'enabled': True, **({'key': key} if updated.rowcount else {})}


def resolveUser(key):
    if not re.fullmatch(r'[0-9a-f]{64}', key):
        return None
    rows = sqlBase.fetchall_to_table('select u.id, u.userName, u.createTime, k.digest '
                                     'from api_key k join user_list u on k.userId=u.id where k.slot=1')
    if rows and hmac.compare_digest(rows[0].pop('digest'), _digest(key)):
        return rows[0]
