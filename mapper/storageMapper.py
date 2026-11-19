"""Persistence helpers for TaoSync virtual storage mounts."""

import json

from common import sqlBase


def getMountList(engineId):
    rows = sqlBase.fetchall_to_table(
        "select * from storage_mount where engineId=? and enabled=1 order by createTime asc, id asc",
        (engineId,),
    )
    for row in rows:
        try:
            row["config"] = json.loads(row["config"] or "{}")
        except (TypeError, ValueError):
            row["config"] = {}
    return rows


def getMountById(mountId):
    rows = sqlBase.fetchall_to_table("select * from storage_mount where id=?", (mountId,))
    if not rows:
        raise ValueError("storage mount not found")
    row = rows[0]
    try:
        row["config"] = json.loads(row["config"] or "{}")
    except (TypeError, ValueError):
        row["config"] = {}
    return row


def addMount(mount, target=None):
    query = (
        "insert into storage_mount (engineId, name, driverType, config, enabled, copyConcurrency) "
        "select :engineId, :name, :driverType, :config, :enabled, :copyConcurrency"
    )
    values = {**mount, "config": json.dumps(mount["config"], ensure_ascii=False),
              "enabled": mount.get("enabled", 1), "copyConcurrency": mount.get("copyConcurrency", 5)}
    if mount["driverType"] != "crypt":
        return sqlBase.execute_insert(query, values)
    # Check the exact backing row that was probed, atomically with the insert.
    if not target or target["id"] != mount["config"]["target_mount_id"]:
        raise ValueError("crypt mount requires a validated target")
    return _insertCrypt(query, values, target)


@sqlBase.connect_sql
def _insertCrypt(conn, query, values, target):
    cursor = conn.execute(query + " from storage_mount where id=:target and engineId=:engineId "
                          "and enabled=1 and driverType!='crypt' and configVersion=:version",
                          {**values, "target": target["id"], "version": target["configVersion"]})
    if cursor.rowcount != 1:
        raise ValueError("target mount changed; reload and retry")
    conn.commit()
    return cursor.lastrowid


def _isReferenced(conn, mountId):
    # Disabled crypt mounts still own their reference and may be enabled again.
    return conn.execute("select 1 from storage_mount where driverType='crypt' and "
                        "json_extract(config, '$.target_mount_id')=? limit 1", (mountId,)).fetchone() is not None


@sqlBase.connect_sql
def updateMount(conn, mount):
    conn.execute("begin immediate")
    if mount["changesBackingLocation"] and _isReferenced(conn, mount["id"]):
        raise ValueError("cannot disable or relocate a mount referenced by a crypt mount")
    cursor = conn.execute(
        "update storage_mount set name=:name, driverType=:driverType, config=:config, enabled=:enabled, "
        "configVersion=configVersion + 1, authVersion=:authVersion, copyConcurrency=:copyConcurrency "
        "where id=:id and configVersion=:expectedVersion and copyConcurrency=:expectedConcurrency",
        {
            **mount,
            "config": json.dumps(mount["config"], ensure_ascii=False),
            "enabled": mount.get("enabled", 1),
            "copyConcurrency": mount.get("copyConcurrency", 5),
        },
    )
    if cursor.rowcount != 1:
        raise ValueError("storage configuration changed; reload and retry")
    conn.commit()


@sqlBase.connect_sql
def updateMountTokens(conn, mountId, expectedAuthVersion, tokenValues, expectedTokens=None):
    """Merge rotated cloud tokens only if the originating config is current."""
    conn.execute("begin immediate")
    row = conn.execute("select config from storage_mount where id=? and driverType='aliyun' and authVersion=?",
                       (mountId, expectedAuthVersion)).fetchone()
    if row is None:
        return None
    config = json.loads(row[0])
    if expectedTokens and any(config.get(key) != value for key, value in expectedTokens.items()):
        return {"conflict": True, "config": config}
    driveId = config.get("drive_id")
    if driveId and tokenValues.get("drive_id", driveId) != driveId and _isReferenced(conn, mountId):
        return {"conflict": True, "config": config}
    config.update(tokenValues)
    conn.execute("update storage_mount set config=?, configVersion=configVersion + 1 where id=?",
                 (json.dumps(config, ensure_ascii=False), mountId))
    conn.commit()
    return True


def updateCopyConcurrency(mountId, value):
    sqlBase.execute_update("update storage_mount set copyConcurrency=? where id=?", (value, mountId))


@sqlBase.connect_sql
def removeMount(conn, mountId):
    conn.execute("begin immediate")
    if _isReferenced(conn, mountId):
        raise ValueError("remove the referencing crypt mount first")
    conn.execute("delete from storage_mount where id=?", (mountId,))
    conn.commit()
