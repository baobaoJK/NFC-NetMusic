# -*- coding: utf-8 -*-
"""从网易云分享链接 / 短链 / 纯数字里提取歌曲 ID（纯 Python，无第三方依赖）"""
import re
import urllib.request

# 支持 orpheus 协议链接、查询串 id=、163.com 各种路径形态的 /song/{id}
_ORPHEUS = re.compile(r'orpheus://song/(\d+)')
_ID_IN_QUERY = re.compile(r'[?&]id=(\d+)')
_SONG_IN_PATH = re.compile(r'163\.com/(?:[a-z0-9]+/)*song/(\d+)')
_PURE_ID = re.compile(r'^\d{3,15}$')
# 分享页 HTML 里可能内嵌 "songId": 123456
_JSON_ID = re.compile(r'"songId"\s*[:=]\s*"?(\d+)')


def _fetch_and_extract(url):
    """打开链接（跟随短链跳转），在最终地址和页面内容里找歌曲 ID。"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36',
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=8) as resp:
        final_url = resp.geturl()
        body = resp.read(256 * 1024).decode('utf-8', 'ignore')
    content = final_url + '\n' + body
    for regex in (_ID_IN_QUERY, _SONG_IN_PATH, _JSON_ID, re.compile(r'/song/(\d+)')):
        m = regex.search(content)
        if m:
            return m.group(1), None
    return None, '能打开链接，但没在里面找到歌曲ID，请换用完整链接'


def extract_song_id(text, allow_network=True):
    """返回 (song_id, 错误信息)；成功时错误信息为 None。

    allow_network=False 用于边输入边预览：不联网，短链会解析不到。
    """
    text = (text or '').strip()
    if not text:
        return None, '请先粘贴网易云分享链接或歌曲ID'

    m = _ORPHEUS.search(text) or _ID_IN_QUERY.search(text) or _SONG_IN_PATH.search(text)
    if m:
        return m.group(1), None
    if _PURE_ID.match(text):
        return text, None

    url_match = re.search(r'https?://\S+', text)
    if url_match and allow_network:
        return _fetch_and_extract(url_match.group(0))
    if url_match:
        return None, '没识别到歌曲ID'
    return None, '没有识别到歌曲ID，请粘贴网易云分享链接或歌曲ID'
