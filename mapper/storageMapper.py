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
        raise Exception("storage mount not found")
    row = rows[0]
    try:
        row["config"] = json.loads(row["config"] or "{}")
    except (TypeError, ValueError):
        row["config"] = {}
    return row


def addMount(mount):
    return sqlBase.execute_insert(
        "insert into storage_mount (engineId, name, driverType, config, enabled) "
        "values (:engineId, :name, :driverType, :config, :enabled)",
        {
            **mount,
            "config": json.dumps(mount["config"], ensure_ascii=False),
            "enabled": mount.get("enabled", 1),
        },
    )


def updateMount(mount):
    sqlBase.execute_update(
        "update storage_mount set name=:name, driverType=:driverType, config=:config, enabled=:enabled, "
        "configVersion=configVersion + 1, authVersion=:authVersion "
        "where id=:id",
        {
            **mount,
            "config": json.dumps(mount["config"], ensure_ascii=False),
            "enabled": mount.get("enabled", 1),
        },
    )


@sqlBase.connect_sql
def updateMountTokens(conn, mountId, expectedAuthVersion, tokenValues, expectedTokens=None):
    """Merge rotated cloud tokens only if the originating config is current."""
    cursor = conn.cursor()
    try:
        for _ in range(3):
            cursor.execute(
                "select config, configVersion, authVersion from storage_mount where id=?",
                (mountId,),
            )
            row = cursor.fetchone()
            if row is None or int(row[2]) != int(expectedAuthVersion):
                return None
            try:
                config = json.loads(row[0] or "{}")
            except (TypeError, ValueError):
                config = {}
            if expectedTokens and any(
                config.get(key) != value for key, value in expectedTokens.items()
            ):
                # Another driver already rotated this token set. Return the
                # current config so the caller can adopt it instead of
                # overwriting a still-valid refresh token.
                return {"conflict": True, "config": config}
            config.update(tokenValues)
            cursor.execute(
                "update storage_mount set config=?, configVersion=configVersion + 1 "
                "where id=? and configVersion=? and authVersion=?",
                (
                    json.dumps(config, ensure_ascii=False),
                    mountId,
                    row[1],
                    expectedAuthVersion,
                ),
            )
            if cursor.rowcount == 1:
                conn.commit()
                return True
        return None
    finally:
        cursor.close()


def removeMount(mountId):
    sqlBase.execute_update("delete from storage_mount where id=?", (mountId,))
