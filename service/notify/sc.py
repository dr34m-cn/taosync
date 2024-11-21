import re

import requests


def send(sendKey, title, content=''):
    params = {
        'title': title,
        'desp': content
    }
    # 判断 sendKey 是否以 'sctp' 开头，并提取数字构造 URL
    if sendKey.startswith('sctp'):
        match = re.match(r'sctp(\d+)t', sendKey)
        if match:
            num = match.group(1)
            url = f'https://{num}.push.ft07.com/send/{sendKey}.send'
            params['tags'] = 'TaoSync'
        else:
            raise ValueError('Invalid sendkey format for sctp')
    else:
        url = f'https://sctapi.ftqq.com/{sendKey}.send'

    headers = {
        'Content-Type': 'application/json;charset=utf-8'
    }
    return requests.post(url, json=params, headers=headers, timeout=(5, 30))
