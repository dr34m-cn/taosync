from common import sqlBase
from common.LNG import G


def initSchema(cursor):
    cursor.execute('create table if not exists job_link (id integer primary key autoincrement, '
                   'source integer not null, condition text not null, minutes integer not null)')
    cursor.execute('create index if not exists idx_link_source on job_link(source)')
    cursor.execute('create table if not exists job_link_target (linkId integer not null, target integer not null, '
                   'primary key(linkId,target))')
    cursor.execute('create table if not exists job_dispatch (id integer primary key autoincrement, '
                   'linkId integer not null, target integer not null, due integer not null, '
                   'runTime integer, result text, detail text)')
    cursor.execute('create index if not exists idx_dispatch_due on job_dispatch(due) where result is null')
    cursor.execute('create index if not exists idx_dispatch_history on job_dispatch(linkId,runTime desc,id desc)')
    cursor.execute('create trigger if not exists clean_job_link after delete on job_link begin '
                   'delete from job_dispatch where linkId=old.id; delete from job_link_target where linkId=old.id; end')
    if cursor.execute("select 1 from sqlite_master where type='table' and name='job'").fetchone():
        cursor.execute('create trigger if not exists clean_job_links after delete on job begin '
                       'delete from job_dispatch where target=old.id and result is null; '
                       'delete from job_link_target where target=old.id; '
                       'delete from job_link where source=old.id or not exists '
                       '(select 1 from job_link_target where linkId=job_link.id); end')


def overview():
    with sqlBase.DB_LOCK:
        jobs = sqlBase.fetchall_to_table('select id, remark from job order by id')
        rules = {}
        for row in sqlBase.fetchall_to_table('select l.*, t.target from job_link l join job_link_target t '
                                             'on l.id=t.linkId order by l.id desc,t.target'):
            target = row.pop('target')
            rules.setdefault(row['id'], dict(row, targets=[]))['targets'].append(target)
        return {'jobs': jobs, 'rules': list(rules.values())}


@sqlBase.connect_sql
def create(conn, source, targets, condition, minutes):
    with conn:
        conn.execute('begin immediate')
        jobs = {row[0] for row in conn.execute('select id from job')}
        if not {source, *targets} <= jobs:
            raise ValueError(G('link_job_missing'))
        # Following existing edges from any proposed target must never reach the source.
        edges = {}
        for a, b in conn.execute('select source,target from job_link join job_link_target on id=linkId'):
            edges.setdefault(a, []).append(b)
        seen, todo = set(), list(targets)
        while todo:
            node = todo.pop()
            if node == source:
                raise ValueError(G('link_cycle'))
            if node not in seen:
                seen.add(node)
                todo.extend(edges.get(node, ()))
        link = conn.execute('insert into job_link(source,condition,minutes) values (?,?,?)',
                            (source, condition, minutes)).lastrowid
        conn.executemany('insert into job_link_target values (?,?)', [(link, target) for target in targets])
        return link


@sqlBase.connect_sql
def finishAndEnqueue(conn, taskId, status, errMsg, finished):
    # Persist the terminal transition and its deliveries together, exactly once.
    with conn:
        changed = conn.execute('update job_task set status=?,errMsg=? where id=? and status in (0,1)',
                               (status, errMsg, taskId)).rowcount
        if not changed:
            return False
        return bool(conn.execute(
            'insert into job_dispatch(linkId,target,due) select l.id,t.target,?+l.minutes*60 '
            'from job_task j join job_link l on l.source=j.jobId join job_link_target t on t.linkId=l.id '
            "where j.id=? and (?=2 or (?=3 and l.condition='finished'))",
            (finished, taskId, status, status)).rowcount)


def due(now):
    return sqlBase.fetchall_to_table('select id,target from job_dispatch where result is null and due<=? '
                                     'order by due,id limit 256', (now,))


@sqlBase.connect_sql
def claim(conn, dispatchId, now):
    with conn:
        # Never replay a possibly-started target after an interrupted handoff.
        return conn.execute("update job_dispatch set result='launching',"
                            'runTime=? where id=? and result is null', (now, dispatchId)).rowcount == 1


def setResult(dispatchId, result, detail=None):
    sqlBase.execute_update('update job_dispatch set result=?,detail=? where id=?', (result, detail, dispatchId))


def recoverInterrupted():
    sqlBase.execute_update("update job_dispatch set result='failed',detail='link_interrupted' "
                           "where result='launching'")


def history(linkId, page):
    where = " from job_dispatch where linkId=? and result in ('executed','skipped','failed')"
    with sqlBase.DB_LOCK:
        return {'count': sqlBase.fetch_first_val('select count(*)' + where, (linkId,)),
                'rows': sqlBase.fetchall_to_table('select id,target,runTime,result,detail' + where +
                                                  ' order by runTime desc,id desc limit 20 offset ?',
                                                  (linkId, (page - 1) * 20))}


def clear(linkId=None):
    sqlBase.execute_update("delete from job_dispatch where result in ('executed','skipped','failed')" +
                           (' and linkId=?' if linkId is not None else ''), (linkId,) if linkId is not None else ())


def remove(linkId):
    sqlBase.execute_update('delete from job_link where id=?', (linkId,))
