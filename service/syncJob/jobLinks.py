import time

from common.LNG import G
from mapper import jobLinkMapper


def create(req):
    source, targets = req.get('source'), req.get('targets')
    condition, minutes = req.get('condition'), req.get('minutes', 0)
    if type(source) is not int or not isinstance(targets, list) or not targets or any(
            type(t) is not int for t in targets):
        raise ValueError(G('link_select_jobs'))
    if condition not in ('finished', 'success'):
        raise ValueError(G('link_invalid_condition'))
    if type(minutes) is not int or not 0 <= minutes <= 2147483647:
        raise ValueError(G('link_invalid_delay'))
    return jobLinkMapper.create(source, set(targets), condition, minutes)


def history(linkId, page):
    result = jobLinkMapper.history(linkId, page)
    reasons = ('link_target_disabled', 'link_updating', 'link_start_failed', 'link_interrupted')
    # Older workers persisted Chinese text instead of the reason key.
    keys = {G(key, 'zh_CN'): key for key in reasons}
    for row in result['rows']:
        key = keys.get(row['detail'], row['detail'])
        if key in reasons:
            row['detail'] = G(key)
    return result


def dispatchDue():
    from service.syncJob import jobService

    for row in jobLinkMapper.due(int(time.time())):
        if not jobLinkMapper.claim(row['id'], int(time.time())):
            continue
        try:
            result = jobService.launchLinkedJob(row['target'])
        except Exception as exc:
            jobLinkMapper.setResult(row['id'], 'failed', str(exc))
        else:
            jobLinkMapper.setResult(row['id'], result)


def startScheduler():
    from service.syncJob.jobClient import getScheduler

    # Also picks up overdue deliveries after restart; the immediate path needn't wait for this tick.
    getScheduler().add_job(dispatchDue, 'interval', seconds=5, id='job-links', replace_existing=True,
                           coalesce=True, max_instances=1)
