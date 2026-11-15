import json
import re
from urllib.parse import quote, urlencode, urlsplit

import requests


TOKENS = re.compile(r'\$(title|content)\b')
METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD')
CONTENT_TYPES = ('application/json', 'application/x-www-form-urlencoded', 'text/plain')


def httpUrl(value):
    if not isinstance(value, str):
        raise ValueError('An HTTP(S) URL is required')
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('An HTTP(S) URL is required')
    return value


def fields(value, parseValues=True):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError('Expected an object or key: value lines')
    if value.lstrip().startswith('{'):
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError('Expected a JSON object')
        return result
    result = {}
    for line in value.splitlines():
        if not line.strip():
            continue
        key, separator, val = line.partition(':')
        if not separator or not key.strip():
            raise ValueError('Expected key: value lines')
        val = val.strip()
        if parseValues:
            try:
                val = json.loads(val)
            except ValueError:
                pass
        result[key.strip()] = val
    return result


def render(value, title, content):
    if isinstance(value, str):
        return TOKENS.sub(lambda match: title if match[1] == 'title' else content, value)
    if isinstance(value, dict):
        return {key: render(item, title, content) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, title, content) for item in value]
    return value


def validate(params):
    httpUrl(params.get('url'))
    if params.get('method') not in METHODS:
        raise ValueError('Unsupported HTTP method')
    if params.get('contentType') not in CONTENT_TYPES:
        raise ValueError('Unsupported content type')
    headers = fields(params.get('headers', ''), parseValues=False)
    for key, value in headers.items():
        if not isinstance(value, str) or any(char in key + value for char in '\r\n'):
            raise ValueError('Invalid request headers')
    body = params.get('body', '')
    if not isinstance(body, str):
        raise ValueError('Request body must be text')
    if params['contentType'] != 'text/plain':
        fields(body)


def send(params, title, content, timeout):
    validate(params)
    url = TOKENS.sub(lambda match: quote(title if match[1] == 'title' else content, safe=''), params['url'])
    headers = {key.lower(): value for key, value in fields(params.get('headers', ''), parseValues=False).items()}
    headers['content-type'] = params['contentType'] + '; charset=utf-8'
    body = params.get('body', '')
    if not body:
        data = ''
    elif params['contentType'] == 'text/plain':
        data = render(body, title, content)
    else:
        body = render(fields(body), title, content)
        data = (json.dumps(body, ensure_ascii=False) if params['contentType'] == 'application/json'
                else urlencode(body, doseq=True))
    response = requests.request(params['method'], url, headers=headers, data=data.encode('utf-8'), timeout=timeout)
    if not 200 <= response.status_code < 300:
        raise ValueError(f'HTTP {response.status_code}: {response.text}')


def barkUrl(params):
    push = params.get('push', '').strip()
    if not push:
        raise ValueError('Bark device key or URL is required')
    return httpUrl(push if push.startswith(('http://', 'https://')) else 'https://api.day.app/' + quote(push, safe=''))


def sendBark(params, title, content, timeout):
    data = {'title': title, 'body': content}
    for key in ('group', 'sound', 'icon', 'level', 'url', 'isArchive'):
        if params.get(key) not in (None, ''):
            data[key] = params[key]
    response = requests.post(barkUrl(params), json=data, timeout=timeout)
    if not 200 <= response.status_code < 300:
        raise ValueError(f'HTTP {response.status_code}: {response.text}')
    result = response.json()
    if result.get('code') != 200:
        raise ValueError(result.get('message') or 'Bark delivery failed')
