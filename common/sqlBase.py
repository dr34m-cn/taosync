import logging
import sqlite3
import time

from common.config import CONFIG

RUN_FLAG = False


def connect_sql(func):
    def wrapper(*args, **kwargs):
        global RUN_FLAG
        while RUN_FLAG:
            time.sleep(0.073)
        RUN_FLAG = True
        conn = None
        try:
            conn = sqlite3.connect(CONFIG['db']['dbname'])
            result = func(conn, *args, **kwargs)
        except Exception as e:
            raise Exception(e)
        finally:
            RUN_FLAG = False
            if conn:
                conn.close()
        return result

    return wrapper


@connect_sql
def fetchall(conn, query, params=()):
    cursor = conn.cursor()
    cursor.execute(query, params)
    rst = cursor.fetchall()
    cursor.close()
    return rst


@connect_sql
def fetch_first_val(conn, query, params=()):
    cursor = conn.cursor()
    cursor.execute(query, params)
    rst = cursor.fetchone()
    cursor.close()
    return rst[0]


@connect_sql
def fetchall_to_table(conn, query, params=()):
    cursor = conn.cursor()
    cursor.execute(query, params)
    rst = cursor.fetchall()
    columns = [column[0] for column in cursor.description]
    cursor.close()
    results = []
    for row in rst:
        results.append(dict(zip(columns, row)))
    return results


def fetchall_to_page(sql, params=None):
    if params is None:
        params = {}
    sql_end = ''
    pageSize = params['pageSize'] if 'pageSize' in params else None
    pageNum = params['pageNum'] if 'pageNum' in params else None
    if pageNum is None or pageSize is None:
        return fetchall_to_table(sql, params)
    else:
        sql_end += ' limit :pageSize offset :offset'
        params['offset'] = (int(pageNum) - 1) * int(pageSize)
    dataList = fetchall_to_table(sql + sql_end, params)
    count = fetch_first_val(sql.replace('*', 'count(id)'), params)
    return {
        'dataList': dataList,
        'count': count
    }


@connect_sql
def execute_insert(conn, query, params=()):
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        lastId = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError as e:
        logger = logging.getLogger()
        logger.exception(e)
        raise Exception("已存在相同数据，请检查！_/_The same data already exists, please check!")
    except Exception as e:
        raise Exception(e)
    finally:
        cursor.close()
    return lastId


@connect_sql
def execute_manny(conn, query, params=()):
    cursor = conn.cursor()
    cursor.executemany(query, params)
    conn.commit()
    cursor.close()


@connect_sql
def execute_update(conn, query, params=()):
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    cursor.close()


def check_and_add_sql(sql, params, data):
    """
    检查字段并自动生成sql
    :param sql: 初始sql
    :param params: 参数列表，例如['sort','remark']
    :param data: 入参对象
    :return 生成的sql
    """
    flag = 0
    for item in params:
        if item in data:
            sql += " {}=:{},".format(item, item)
            flag += 1
    if flag == 0 or 'id' not in data:
        raise Exception("入参不全_/_Incomplete participation")
    sql = sql[:-1]
    sql += " where id=:id"
    return sql
