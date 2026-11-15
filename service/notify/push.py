import requests

from service.notify.custom import httpUrl


PUSHPLUS_URL = 'https://www.pushplus.plus/send'
PUSHDEER_URL = 'https://api2.pushdeer.com/message/push'
PUSHPLUS_TEMPLATES = ('html', 'txt', 'json', 'markdown', 'cloudMonitor', 'jenkins', 'route', 'pay')
PUSHPLUS_CHANNELS = ('wechat', 'webhook', 'cp', 'mail', 'sms')


def requiredText(params, key, label):
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} is required')
    return value.strip()


def pushPlusData(params, title='', content=''):
    data = {
        'token': requiredText(params, 'token', 'pushPlus Token'),
        'title': title,
        'content': content,
        'template': params.get('template') or 'html',
        'channel': params.get('channel') or 'wechat',
    }
    if data['template'] not in PUSHPLUS_TEMPLATES:
        raise ValueError('Unsupported pushPlus template')
    if data['channel'] not in PUSHPLUS_CHANNELS:
        raise ValueError('Unsupported pushPlus channel')
    for key in ('topic', 'webhook', 'callbackUrl', 'to'):
        value = params.get(key)
        if value not in (None, ''):
            if not isinstance(value, str):
                raise ValueError(f'pushPlus {key} must be text')
            if value.strip():
                data[key] = value.strip()
    if data.get('callbackUrl'):
        httpUrl(data['callbackUrl'])
    return data


def pushDeerUrl(params):
    requiredText(params, 'pushkey', 'PushDeer PushKey')
    url = params.get('url') or PUSHDEER_URL
    if not isinstance(url, str):
        raise ValueError('An HTTP(S) URL is required')
    return httpUrl(url.strip() or PUSHDEER_URL)


def responseResult(response):
    if not 200 <= response.status_code < 300:
        raise ValueError(f'HTTP {response.status_code}: {response.text}')
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError('Invalid push service response')
    return result


def sendPushPlus(params, title, content, timeout):
    data = pushPlusData(params, title, content)
    result = responseResult(requests.post(PUSHPLUS_URL, json=data, timeout=timeout))
    if result.get('code') != 200:
        raise ValueError(result.get('msg') or 'pushPlus delivery failed')


def sendPushDeer(params, title, content, timeout):
    url = pushDeerUrl(params)
    data = {'pushkey': requiredText(params, 'pushkey', 'PushDeer PushKey'),
            'text': title, 'desp': content, 'type': 'markdown'}
    result = responseResult(requests.post(url, data=data, timeout=timeout))
    details = result.get('content')
    targets = details.get('result') if isinstance(details, dict) else None
    if result.get('code') != 0 or not isinstance(targets, list) or not targets:
        raise ValueError(result.get('error') or result.get('msg') or 'PushDeer delivery failed')
