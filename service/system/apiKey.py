import hashlib
import hmac
import re
import secrets

from common import sqlBase
from common.LNG import G


def _digest(key):
    return hashlib.sha256(key.encode('ascii')).hexdigest()


def _table(scope):
    if scope == 'general':
        return 'api_key'
    if scope == 'execute':
        return 'execution_api_key'
    raise ValueError(G('api_key_unknown_action'))


def status(scope='general'):
    return {'enabled': bool(sqlBase.fetchall(f'select 1 from {_table(scope)} where slot=1'))}


@sqlBase.connect_sql
def change(conn, action, userId, scope='general'):
    table = _table(scope)
    if action == 'disable':
        conn.execute(f'delete from {table} where slot=1')
        conn.commit()
        return {'enabled': False}
    if action not in ('enable', 'reset'):
        raise ValueError(G('api_key_unknown_action'))
    key = ('tx-' if scope == 'execute' else 't-') + secrets.token_hex(32)
    if action == 'enable':
        updated = conn.execute(f'insert or ignore into {table}(slot, userId, digest) values (1, ?, ?)',
                               (userId, _digest(key)))
    else:
        updated = conn.execute(f'update {table} set digest=?, userId=? where slot=1', (_digest(key), userId))
        if not updated.rowcount:
            raise ValueError(G('api_key_enable_first'))
    conn.commit()
    return {'enabled': True, **({'key': key} if updated.rowcount else {})}


def resolveUser(key, scope='general'):
    # Existing unprefixed keys remain valid until rotated.
    prefix = 'tx-' if scope == 'execute' else '(?:t-)?'
    if not re.fullmatch(prefix + r'[0-9a-f]{64}', key):
        return None
    rows = sqlBase.fetchall_to_table('select u.id, u.userName, u.createTime, k.digest '
                                     f'from {_table(scope)} k join user_list u on k.userId=u.id where k.slot=1')
    if rows and hmac.compare_digest(rows[0].pop('digest'), _digest(key)):
        return rows[0]
