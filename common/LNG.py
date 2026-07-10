"""
Compatibility wrapper for the old flat-key language API.
"""
import threading

from common.commonUtils import readOrSet
from common.locales import getOrSetDefaultLang, t

sysLanguage = None
_local = threading.local()


def set_context_lang(lang=None):
    _local.lang = getOrSetDefaultLang(lang)
    return _local.lang


def get_context_lang():
    return getattr(_local, 'lang', None)


def language(lang=None):
    """
    获取或修改默认语言。兼容旧值 zh_cn/eng，同时支持 zh-CN/en。
    :param lang: 语言，不填为读取，否则是修改
    :return: 读取时为值，否则为空
    """
    global sysLanguage
    fileName = 'data/language.txt'
    if lang is None:
        if sysLanguage is None:
            sysLanguage = getOrSetDefaultLang(readOrSet(fileName, 'zh_CN'))
            readOrSet(fileName, sysLanguage, True)
        return sysLanguage
    sysLanguage = getOrSetDefaultLang(lang)
    readOrSet(fileName, sysLanguage, True)


def G(params, lang=None):
    """
    根据语言获取文字。
    :param params: 文字关键字
    :param lang: 可选语言；不传时使用当前请求语言或默认语言
    :return:
    """
    return t(params, lang or get_context_lang() or language())
