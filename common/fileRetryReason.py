"""Only typed, application-owned file retry failures are translatable."""
import json

from common.LNG import G


class FileRetryError(ValueError):
    def __str__(self):
        key, *params = self.args
        return G(key).format(*params)


def storedReason(error):
    if isinstance(error, FileRetryError):
        return None, json.dumps(error.args, ensure_ascii=False)
    return error, None


def renderReason(row):
    reason = row.pop('retryReason', None)
    if reason is not None:
        row['errMsg'] = str(FileRetryError(*json.loads(reason)))
    return row
