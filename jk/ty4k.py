# -*- coding: utf-8 -*-

import base64
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import requests
except Exception:                       # 裁剪包可能不带 requests，走 urllib 兜底
    requests = None

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass

KEY = 'yingtan4k'
HOST = 'http://cms.lyyytv.cn'
CMS_KEY = 'wP5bvxoc3yv7FoBQENFZuAF0EUYr4LTy'

# 解析接口：2026-10-31 实测 parsesId=5 可用（腾讯/爱奇艺出 m3u8，B站出 mpd），
# 2/4 已废（服务端 Parses::getApi 抛异常 → 500），6/7 在库但对该片返回"解析失败"。
# 顺序即优先级：先 5，失败再退到 2/4 碰运气（它们偶尔恢复）。
PARSE_BASE = 'http://fys.lyyytv.cn/api/index?appid=10001&parsesId=%d&videoUrl=%s'
PARSE_IDS = (5, 2, 4)
PARSE_TIMEOUT = 12
PID_DOWN_TTL = 600          # 单个解析通道故障后的冷却（秒）
PID_NET_TTL = 90            # 传输层异常（断网/超时）的短冷却
PARSE_DOWN_TTL = 300        # 全部通道故障后的全局冷却（秒）

UA_OKHTTP = 'okhttp/4.12.0'
UA_WEB = ('Mozilla/5.0 (Linux; Android 13; SM-G981B) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36')

HEADERS = {'User-Agent': UA_OKHTTP}
# 播放请求头：只带 UA。实测腾讯 / 69mini 的 ts 分片不校验 Referer，
# 带上 lyyytv 的 Referer 反而会让部分 CDN 403。
PLAY_HEADERS = {'User-Agent': UA_OKHTTP}
# 解析失败降级给播放器嗅探时用浏览器 UA + 站点 Referer
WEB_HEADERS = {'User-Agent': UA_WEB, 'Referer': 'http://cms.lyyytv.cn/'}

# baidu.con 前缀加密常量（对齐 yt4k.js）
DEC_PREFIX = 'https://baidu.con/'

PAGE_LIMIT = 20
HOME_LIMIT = 30
FILTER_NAMES = {
    'class': '类型', 'area': '地区', 'lang': '语言', 'year': '年份',
    'letter': '字母', 'by': '排序', 'sort': '顺序',
}
HOME_CACHE_TTL = 6 * 3600
# 解析结果缓存：落地 CDN 的 auth_key 是「过期时间 + 路径 + IP」签名，有效期只有几分钟。
# 原来给 600s 太长，等于拿过期票去检票（播放器一打开就 403）。收到 90s。
PLAY_CACHE_TTL = 90
PROBE_CACHE_TTL = 240       # 直链可用性探测缓存
PROBE_TIMEOUT = 2.5
DETAIL_CACHE_TTL = 600      # 详情缓存，反复进出详情页不再重复打接口

# ---- 出口行为：把「像人」这件事做在细节里 ----
MIN_GAP = 0.25              # 同一 host 两次请求的最小间隔（秒）
MIN_GAP_DEFAULT = 0.25
MAX_WAIT = 1.5              # 排队等待上限，别把 UI 线程卡死
BAN_BASE = 30               # 403/429 首次冷却（秒），之后翻倍
BAN_MAX = 600

_BASE64_RE = re.compile(r'(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?')
_LDMAX_RE = re.compile(r'^https?://ldmax\.cooom/', re.I)
_MEDIA_RE = re.compile(r'\.(?:mp4|m3u8?|flv|avi|mkv|ts|mov|wmv|webm|m4v|mpd)$', re.I)
_EP_NUM_RE = re.compile(r'^\s*第?\s*0*(\d+)\s*(?:集|话|期|回|-|_)')

_home_cache = {}
_play_cache = {}
_probe_cache = {}
_detail_cache = {}   # vod_id -> (过期时间, vod dict)
_lines = {}      # vod_id -> [{'flag': 线路名, 'eps': [(key, url), ...]}, ...]
_id_index = {}   # 播放地址 -> (vod_id, 集 key, 线路名)
_pref = {}       # vod_id -> 上次成功的线路名
_warming = set()  # 正在后台预解析的地址

_pid_dead = {}      # 解析通道 parsesId -> 解禁时间
_parse_down = [0.0]  # 解析服务整体解禁时间
_ban_until = {}     # host -> 解禁时间
_ban_streak = {}    # host -> 连续被拒次数
_last_hit = {}      # host -> 上次请求时间
_gate_lock = threading.Lock()
_session = [None]
_proxy = [None]


class _Blocked(Exception):
    """该 host 处于熔断冷却期，本次不发请求。"""
    pass


def _host_of(url):
    try:
        return urllib.parse.urlparse(text(url)).netloc or ''
    except Exception:
        return ''


def session_obj():
    """全局唯一的 requests.Session：复用连接 + 保持 CDN 下的 server_session cookie。
    每次 requests.get 都是新连接新 cookie，在 CDN 眼里就是「又来了一个新客户端」，
    这正是频繁触发风控的原因之一。"""
    if requests is None:
        return None
    if _session[0] is None:
        with _gate_lock:
            if _session[0] is None:
                s = requests.Session()
                try:
                    from requests.adapters import HTTPAdapter
                    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0)
                    s.mount('http://', adapter)
                    s.mount('https://', adapter)
                except Exception:
                    pass
                s.headers.update(HEADERS)
                _session[0] = s
    return _session[0]


def _reset_session():
    s = _session[0]
    _session[0] = None
    if s is not None:
        try:
            s.close()
        except Exception:
            pass


def _throttle(url):
    """同 host 串行 + 最小间隔 + 熔断检查。熔断期内抛 _Blocked，调用方据此降级。"""
    host = _host_of(url)
    if not host:
        return
    now = time.time()
    if _ban_until.get(host, 0) > now:
        raise _Blocked(host)
    with _gate_lock:
        wait = (_last_hit.get(host) or 0) + MIN_GAP - time.time()
        if wait > 0:
            time.sleep(min(wait, MAX_WAIT))
        _last_hit[host] = time.time()


def _breach(url, code):
    """记录响应码，403/429/451/503 走指数退避，正常响应清零。"""
    host = _host_of(url)
    if not host:
        return
    try:
        code = int(code or 0)
    except (TypeError, ValueError):
        code = 0
    if code in (403, 429, 451, 503):
        n = _ban_streak.get(host, 0) + 1
        _ban_streak[host] = n
        _ban_until[host] = time.time() + min(BAN_BASE * (2 ** (n - 1)), BAN_MAX)
    elif 200 <= code < 400:
        _ban_streak[host] = 0
        _ban_until[host] = 0


def cookie_header(url):
    """取该 host 在全局 Session 里的 cookie，回填给播放器。
    CDN 下发的 server_session_* 缺失时，分片请求会被当成陌生会话拒掉。"""
    s = _session[0]
    if s is None:
        return ''
    try:
        pairs = ['%s=%s' % (c.name, c.value) for c in s.cookies
                 if c.domain and c.domain.lstrip('.') in _host_of(url)]
        return '; '.join(pairs)
    except Exception:
        return ''


def _apply_extend(raw):
    """extend 支持 JSON：{"ua": "...", "proxy": "http://ip:port", "gap": 0.4}"""
    global MIN_GAP
    txt = text(raw)
    if not txt.startswith('{'):
        MIN_GAP = MIN_GAP_DEFAULT
        return
    try:
        cfg = json.loads(txt)
    except Exception:
        MIN_GAP = MIN_GAP_DEFAULT
        return
    if not isinstance(cfg, dict):
        MIN_GAP = MIN_GAP_DEFAULT
        return
    ua = text(cfg.get('ua'))
    if ua:
        HEADERS['User-Agent'] = ua
        PLAY_HEADERS['User-Agent'] = ua
        s = _session[0]
        if s is not None:
            s.headers['User-Agent'] = ua
    proxy = text(cfg.get('proxy'))
    if proxy:
        _proxy[0] = proxy
        s = session_obj()
        if s is not None:
            s.proxies = {'http': proxy, 'https': proxy}
            s.headers.update(HEADERS)
    try:
        gap = float(cfg.get('gap'))
        if 0 < gap <= 5:
            MIN_GAP = gap
    except (TypeError, ValueError):
        pass


def _fetch_urllib(url, headers, timeout, peek):
    """无 requests 时的兜底出口，语义与 _fetch 一致。"""
    req = urllib.request.Request(url, headers=headers)
    try:
        rsp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as err:
        rsp = err
    except Exception:
        raise
    try:
        code = int(getattr(rsp, 'getcode', lambda: 0)() or 0)
    except Exception:
        code = 0
    final = getattr(rsp, 'geturl', lambda: url)() or url
    try:
        ctype = (rsp.headers.get('Content-Type') or '').lower()
    except Exception:
        ctype = ''
    data = b''
    if peek and 200 <= code < 300:
        try:
            data = rsp.read(peek) or b''
        except Exception:
            data = b''
    try:
        rsp.close()
    except Exception:
        pass
    _breach(url, code)
    return {'code': code, 'final': final, 'ctype': ctype, 'peek': data, 'cookie': ''}


def _fetch(url, headers=None, timeout=10, rng=None, peek=0):
    """全模块唯一出口。熔断期内抛 _Blocked；其余异常原样抛出。
    返回 {code, final, ctype, peek, cookie}，不下载正文（peek 只读前几字节）。"""
    headers = dict(PLAY_HEADERS if headers is None else headers)
    if rng:
        headers['Range'] = 'bytes=0-%d' % max(0, int(rng) - 1)
    _throttle(url)
    s = session_obj()
    if s is None:
        return _fetch_urllib(url, headers, timeout, peek)
    try:
        rsp = s.get(url, headers=headers, timeout=timeout, stream=True,
                    allow_redirects=True)
    except Exception:
        raise
    out = {
        'code': rsp.status_code,
        'final': rsp.url or url,
        'ctype': (rsp.headers.get('Content-Type') or '').lower(),
        'peek': b'',
        'cookie': '',
    }
    if peek:
        try:
            out['peek'] = rsp.raw.read(peek) or b''
        except Exception:
            out['peek'] = b''
    try:
        rsp.close()
    except Exception:
        pass
    _breach(url, out['code'])
    out['cookie'] = cookie_header(url)
    return out


# ---------------------------------------------------------------- 基础工具
def text(value):
    return '' if value is None else str(value).strip()


def page_of(value):
    m = re.match(r'\s*[+-]?\d+', '' if value is None else str(value))
    n = int(m.group(0)) if m else 0
    return max(1, n) if n else 1


def list_of(value):
    return value if isinstance(value, list) else []


def object_of(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _trim(cache, keep=240):
    if len(cache) > keep:
        for k in list(cache.keys())[:len(cache) - keep]:
            cache.pop(k, None)


def get_json(url, headers=None, timeout=15):
    headers = HEADERS if headers is None else headers
    # CMS 接口同样要排队：详情页连带 6 条线路的探测，短时间打太多
    # 会被站点当成采集器（这一步才是「被检测」最常见的真实原因）。
    try:
        _throttle(url)
    except _Blocked:
        raise Exception('影探4K：该站点暂时限流，稍后再试')
    net = _NET[0]
    if net is not None:
        try:
            resp = net.req(url, {"headers": headers, "timeout": _ms(timeout)})
        except Exception as error:
            raise Exception('影探4K：接口请求异常 %s' % error)
        _breach(url, resp.get('code') or 0)
        if not _net_ok(resp):
            raise Exception('影探4K：接口返回 %s' % (resp.get("code"),
                                                  resp.get("error") or ""))
        try:
            data = object_of(_json.loads(_resp_text(resp)))
        except Exception:
            data = {}
        if not data:
            raise Exception('影探4K：接口未返回有效 JSON')
        return data

    s = session_obj()
    if s is None:
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=timeout).read()
        except Exception as error:
            raise Exception('影探4K：接口请求异常 %s' % error)
        data = object_of(raw.decode('utf-8', 'replace'))
        if not data:
            raise Exception('影探4K：接口未返回有效 JSON')
        return data

    rsp = s.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    _breach(url, rsp.status_code)
    try:
        data = object_of(rsp.json())
    except Exception:
        data = {}
    if not data:
        raise Exception('影探4K：接口未返回有效 JSON')
    return data


def cms(path, params=None):
    params = params or {}
    query = urllib.parse.urlencode(params)
    data = get_json('%s/api.php/app/%s?%s' % (HOST, path, query))
    code = data.get('code')
    if code is not None:
        try:
            ok = int(code) in (1, 200)
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise Exception('影探4K：CMS 请求失败')
    return data


def abs_url(value, base=HOST):
    url = text(value)
    if not url:
        return ''
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        return base + url
    return url


# ---------------------------------------------------------------- 解密
def decode_base64(value):
    clean = re.sub(r'\s+', '', text(value))
    if not clean or not _BASE64_RE.fullmatch(clean):
        return None
    try:
        return base64.b64decode(clean)
    except Exception:
        return None


def decrypt_lvdou(value):
    """对齐 JS decUrlOne：lvdou+ → 前16 key/后16 iv AES/CBC/PKCS7"""
    original = text(value)
    if not original.startswith('lvdou+'):
        return original
    if not CMS_KEY:
        return original
    try:
        encrypted = decode_base64(original[6:])
        if not encrypted:
            return original
        key = CMS_KEY[:16].encode('utf-8')
        iv = CMS_KEY[16:32].encode('utf-8') if len(CMS_KEY) >= 32 else key
        cipher = AES.new(key, AES.MODE_CBC, iv)
        plain = unpad(cipher.decrypt(encrypted), AES.block_size)
        result = plain.decode('utf-8', errors='replace').strip()
        if result.startswith('http'):
            return result
    except Exception:
        pass
    return original


def is_http_url(value):
    try:
        parsed = urllib.parse.urlparse(text(value))
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except Exception:
        return False


def is_ldmax_url(value):
    return bool(_LDMAX_RE.match(text(value)))


def decrypt_ldmax(value, depth=0):
    """兼容老加密：ldmax.cooom 前缀"""
    if depth > 5:
        return ''
    url = text(value)
    decoded = decode_base64(url)
    if decoded:
        url = re.sub(r'\s+', '', decoded.decode('utf-8', errors='replace'))
    if not is_ldmax_url(url):
        return url
    path = _LDMAX_RE.sub('', url)
    if len(path) <= 16:
        return ''
    try:
        key = path[:16][::-1].encode('utf-8')
        encrypted = decode_base64(path[16:])
        if not encrypted or len(encrypted) % 16:
            return ''
        cipher = AES.new(key, AES.MODE_CBC, key)
        plain = bytearray(cipher.decrypt(encrypted))
        pad = plain[-1]
        if 0 < pad <= 16:
            del plain[-pad:]
        result = bytes(plain).decode('utf-8', errors='replace').strip()
        return decrypt_ldmax(result, depth + 1) if is_ldmax_url(result) else result
    except Exception:
        return ''


# ---------------------------------------------------------------- 解析
def find_url(value):
    """对齐 JS findUrl：从解析响应 JSON 中挑出 url/playUrl/link/data.url"""
    if not isinstance(value, dict):
        return ''
    for key in ('url', 'playUrl', 'link'):
        v = value.get(key)
        if v:
            return text(v)
    return find_url(value.get('data'))


def resolve_parse(body):
    """
    对齐 JS resolveParse：
      1) JSON 包裹 → 取出 url
      2) https://baidu.con/ 前缀 → 前16位 key=iv，余下 base64 密文 AES/CBC/PKCS7
      3) 明文 URL
    """
    body = text(body)
    if not body:
        return ''

    candidate = body
    if body.startswith('{'):
        try:
            parsed = json.loads(body)
            found = find_url(parsed)
            if found:
                candidate = found
        except Exception:
            pass

    if not candidate.startswith(DEC_PREFIX):
        return candidate if candidate.startswith('http') else ''

    rest = candidate[len(DEC_PREFIX):]
    if len(rest) <= 16:
        return ''
    key = rest[:16].encode('utf-8')
    cipher_b64 = rest[16:]

    # 优先按 base64 密文解密
    try:
        encrypted = base64.b64decode(cipher_b64, validate=False)
        cipher = AES.new(key, AES.MODE_CBC, key)
        plain = unpad(cipher.decrypt(encrypted), AES.block_size)
        result = plain.decode('utf-8', errors='replace').strip()
        if result.startswith('http'):
            return result
    except Exception:
        pass
    # 兜底：密文本身是 raw bytes
    try:
        raw = cipher_b64.encode('latin-1', errors='ignore')
        if raw and len(raw) % 16 == 0:
            cipher = AES.new(key, AES.MODE_CBC, key)
            plain = unpad(cipher.decrypt(raw), AES.block_size)
            result = plain.decode('utf-8', errors='replace').strip()
            if result.startswith('http'):
                return result
    except Exception:
        pass
    return ''


def finalize(url, timeout=8):
    """
    解析接口吐出的是「一次性中转地址」，6 秒后即失效（页面原文：链接超过6秒会失效）。
    这里立刻跟一次 302，把长期有效的落地地址换出来，否则播放器打开时早就过期。

    只取响应头（Range: bytes=0-0），不下载正文 —— 这一跳本来就是买票，
    没必要顺手把整段片子拖下来，拖得越久票越容易在检票口过期。

    返回空字符串表示文件确实不存在；403 不再判死（可能只是 auth_key 的
    时间戳/来源校验没过，播放器换一套头还有机会），原样交给调用方。
    """
    if not is_http_url(url):
        return ''
    try:
        got = _fetch(url, PLAY_HEADERS, timeout=timeout, rng=1)
    except _Blocked:
        return url                      # 熔断中：不消耗这条一次性地址，原样返回
    except Exception:
        return url                      # 网络抖动，保守返回原地址
    code = got['code']
    final = got['final'] or url
    if code in (200, 206):
        if 'html' in got['ctype']:
            return ''
        return final
    if code in (404, 410):
        return ''
    return final or url


def parse_url(raw):
    """把页面地址拼到解析基址后请求，解出可长期播放的地址。

    改造要点（都是为了「少留下痕迹」）：
      · 单个通道只试一次，不搞两轮重试；
      · 5xx / 错误页 = 通道本身挂了 → 该通道冷却 PID_DOWN_TTL；
      · code:0 解析失败 = 这条视频没资源 → 换下一个通道，不算故障；
      · 全部通道都挂 → 全局冷却 PARSE_DOWN_TTL，期间直接降级给播放器嗅探。
    改造前：一条播不了的剧会打 19 次请求（其中 18 次是 500），很容易被风控盯上。
    """
    if not raw:
        return ''
    if _parse_down[0] > time.time():
        return ''
    target_q = urllib.parse.quote(text(raw), safe="!'()*")
    now = time.time()
    tried = 0
    saw_5xx = False
    s = session_obj()
    for pid in PARSE_IDS:
        if _pid_dead.get(pid, 0) > now:
            continue
        tried += 1
        api = PARSE_BASE % (pid, target_q)
        try:
            _throttle(api)
            if s is not None:
                rsp = s.get(api, headers=HEADERS, timeout=PARSE_TIMEOUT,
                            allow_redirects=True)
                body = rsp.text or ''
                code = rsp.status_code
                _breach(api, code)
            else:
                rsp = urllib.request.urlopen(
                    urllib.request.Request(api, headers=HEADERS), timeout=PARSE_TIMEOUT)
                body = rsp.read().decode('utf-8', 'replace')
                code = int(rsp.getcode() or 0)
        except _Blocked:
            return ''
        except Exception:
            # 传输层异常（断网/超时）：只短冷却，别当成通道死了，
            # 否则一次电梯里断网就等于五分钟不能解析。
            _pid_dead[pid] = time.time() + PID_NET_TTL
            continue
        if code >= 500 or body.lstrip().lower().startswith(('<!doctype', '<html')):
            # 服务端自己报错（Parses::getApi 空对象之类），重试只会继续报错
            saw_5xx = True
            _pid_dead[pid] = time.time() + PID_DOWN_TTL
            continue
        resolved = resolve_parse(body)
        if not resolved or not resolved.startswith('http'):
            continue                    # 这条视频在该通道上没有资源，换下一个
        landed = finalize(resolved)
        if landed:
            return landed
    if tried and saw_5xx and all(_pid_dead.get(p, 0) > time.time() for p in PARSE_IDS):
        # 所有通道都吐 5xx：不是这条视频的问题，是解析服务本身病了
        _parse_down[0] = time.time() + PARSE_DOWN_TTL
    return ''


def is_media_url(url):
    if not is_http_url(url):
        return False
    try:
        path = urllib.parse.unquote(urllib.parse.urlparse(text(url)).path)
    except Exception:
        path = text(url)
    return bool(_MEDIA_RE.search(path))


def probe(url):
    """探测直链是否真的能取到媒体数据。True=可播 False=明确失效 None=未知

    只发一次请求。原来「失败再换 Referer 重试」等于对同一个地址打两遍，
    站点看到的是翻倍的请求量，而换头能救回来的概率极低。
    403 归为「未知」而不是「失效」：那多半是 auth_key 的时间/来源校验，
    判死会误杀整条线路，交给播放器自己再试一次更划算。
    """
    now = time.time()
    hit = _probe_cache.get(url)
    if hit and hit[0] > now:
        return hit[1]

    ok = None
    try:
        got = _fetch(url, PLAY_HEADERS, timeout=PROBE_TIMEOUT, rng=64, peek=32)
        code = got['code']
        if code in (200, 206):
            head = (got['peek'] or b'').lstrip()[:16].lower()
            if 'html' in got['ctype'] or head.startswith(b'<!doctype') or head.startswith(b'<html'):
                # 站点对已删除的文件会返回「200 + HTML 404 页面」，
                # 这种必须判死，否则播放器拿到一段网页直接报错。
                ok = False
            else:
                ok = True
        elif code in (404, 410, 451):
            ok = False
    except _Blocked:
        ok = None
    except Exception:
        ok = None

    _trim(_probe_cache)
    _probe_cache[url] = (now + PROBE_CACHE_TTL, ok)
    return ok



# ---------------------------------------------------------------- 数据接口
def home():
    cached = _home_cache.get('home')
    if cached and cached[0] > time.time():
        return cached[1]
    data = cms('nav', {'token': ''})
    classes = []
    filters = {}
    for item in list_of(data.get('list')):
        if not isinstance(item, dict):
            continue
        if item.get('type_id') is None or not text(item.get('type_name')):
            continue
        tid = text(item['type_id'])
        classes.append({'type_id': tid, 'type_name': text(item['type_name'])})
        ext = object_of(item.get('type_extend'))
        groups = []
        for key, name in FILTER_NAMES.items():
            values = [v for v in (text(x) for x in text(ext.get(key)).split(',')) if v]
            values = list(dict.fromkeys(values))
            if values:
                groups.append({
                    'key': key,
                    'name': name,
                    'init': '',
                    'value': [{'n': '全部', 'v': ''}] + [{'n': v, 'v': v} for v in values],
                })
        if groups:
            filters[tid] = groups
    result = {'class': classes, 'filters': filters}
    if classes:
        _home_cache['home'] = (time.time() + HOME_CACHE_TTL, result)
    return result


def home_vod():
    data = cms('index_video', {'token': ''})
    vlist = []
    seen = set()
    for item in list_of(data.get('list')):
        if not isinstance(item, dict):
            continue
        for vod in list_of(item.get('vlist')):
            if not isinstance(vod, dict):
                continue
            vid = text(vod.get('vod_id'))
            if not vid or vid in seen:
                continue
            seen.add(vid)
            vod['vod_pic'] = abs_url(vod.get('vod_pic'))
            vlist.append(vod)
            if len(vlist) >= HOME_LIMIT:
                return {'list': vlist}
    return {'list': vlist}


def paginated(data, requested_page):
    lst = list_of(data.get('list'))
    for item in lst:
        if isinstance(item, dict):
            item['vod_pic'] = abs_url(item.get('vod_pic'))
    raw_page = data.get('page')
    page = page_of(raw_page if raw_page is not None else requested_page)
    try:
        limit = int(data.get('limit') or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        limit = PAGE_LIMIT
    try:
        raw_pagecount = int(data.get('pagecount') or 0)
    except (TypeError, ValueError):
        raw_pagecount = 0
    has_pagecount = raw_pagecount > 0
    pagecount = raw_pagecount if has_pagecount else page + (1 if len(lst) >= limit else 0)
    try:
        raw_total = data.get('total')
        has_total = raw_total is not None and int(raw_total) >= 0
    except (TypeError, ValueError):
        has_total = False
    if has_pagecount and has_total:
        total = int(data.get('total'))
    else:
        total = (page - 1) * limit + len(lst) + (1 if pagecount > page else 0)
    data['page'] = page
    data['pagecount'] = pagecount
    data['limit'] = limit
    data['total'] = total
    data['list'] = lst
    return data


def category(tid, pg, extend):
    page = page_of(pg)
    tid = text(tid)
    if not tid:
        return paginated({'list': []}, page)
    extend = extend if isinstance(extend, dict) else {}
    params = {'tid': tid, 'pg': str(page), 'limit': str(PAGE_LIMIT)}
    for key in FILTER_NAMES:
        value = text(extend.get(key))
        if value and value.lower() != 'all':
            params[key] = value
    return paginated(cms('video', params), page)


def playlist(value):
    parts = []
    for entry in text(value).split('#'):
        sep = entry.find('$')
        if sep <= 0 or not text(entry[sep + 1:]):
            continue
        parts.append('%s$%s' % (text(entry[:sep]), decrypt_lvdou(entry[sep + 1:])))
    return '#'.join(parts)


def parse_eps(url_str):
    """'第1集$http://...#第2集$http://...' -> [(key, url), ...]"""
    eps = []
    for entry in text(url_str).split('#'):
        sep = entry.find('$')
        if sep <= 0:
            continue
        label = text(entry[:sep])
        url = text(entry[sep + 1:])
        if not url:
            continue
        eps.append((ep_key(label), url))
    return eps


def ep_key(label):
    s = text(label)
    m = _EP_NUM_RE.match(s)
    if m:
        try:
            return ('n', int(m.group(1)))
        except ValueError:
            pass
    m = re.match(r'^\s*0*(\d+)\s*m?$', s)
    if m:
        try:
            return ('n', int(m.group(1)))
        except ValueError:
            pass
    return ('s', re.sub(r'\s+', '', s))


def line_weight(eps):
    """0=直链实测可播  1=页面需解析/未知  2=直链明确失效

    只看第一集。原来探两集，等于把探测请求量翻倍，而第二集的结论
    和第一集基本一致 —— 同一部剧的文件在同一批 CDN 上，没必要重复问。
    """
    for _, url in eps[:1]:
        if is_media_url(url):
            state = probe(url)
            if state is True:
                return 0
            if state is False:
                return 2
            return 1
    return 1


def weights_of(entries):
    """并发探测各线路，返回与 entries 等长的权重列表。

    并发上限 2：原来 6 条线路一起打，在站点看来就是一次典型的采集行为。
    排队 2 路 + _fetch 内建的间隔，总耗时仍在 5 秒预算内。
    """
    results = {}
    slots = threading.Semaphore(2)

    def work(idx, eps):
        try:
            with slots:
                results[idx] = line_weight(eps)
        except Exception:
            results[idx] = 1

    threads = []
    for idx, entry in enumerate(entries):
        th = threading.Thread(target=work, args=(idx, entry['eps']))
        th.daemon = True
        th.start()
        threads.append(th)
    deadline = time.time() + 5
    for th in threads:
        th.join(max(0.0, deadline - time.time()))
    return [results.get(i, 1) for i in range(len(entries))]


def warm(url):
    """后台预解析，用户点播放时命中缓存。解析服务熔断时不做无用功。"""
    try:
        if url and not is_media_url(url) and _parse_down[0] <= time.time():
            play(url)
    except Exception:
        pass
    finally:
        _warming.discard(url)


def detail(ids):
    if not isinstance(ids, (list, tuple)):
        ids = [ids]
    lst = []
    for vid in ids:
        vid = text(vid)
        if not vid:
            continue
        hit = _detail_cache.get(vid)
        if hit and hit[0] > time.time():
            # 反复进出详情页（TVBox 的返回/刷新很频繁）不再重复打接口，
            # 既省一次请求，也少留一次访问记录。
            for line in hit[2]:
                for key, url in line['eps']:
                    _id_index[url] = (vid, key, line['flag'])
            _lines[vid] = hit[2]
            lst.append(dict(hit[1]))
            continue
        data = cms('video_detail', {'id': vid}).get('data')
        if not isinstance(data, dict):
            continue
        players = data.get('vod_url_with_player')
        vod = {k: v for k, v in data.items() if k != 'vod_url_with_player'}
        names = text(vod.get('vod_play_from')).split('$$$')
        if isinstance(players, list) and players:
            sources = players
        else:
            sources = [
                {'name': names[i] if i < len(names) else '', 'url': u}
                for i, u in enumerate(text(vod.get('vod_play_url')).split('$$$'))
            ]

        entries = []
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            url = playlist(source.get('url'))
            if not url:
                continue
            name = text(source.get('name')) or text(source.get('code')) or '线路%d' % (index + 1)
            name = re.sub(r'[$#]', ' ', name).strip() or '线路%d' % (index + 1)
            eps = parse_eps(url)
            if not eps:
                continue
            entries.append({
                'flag': name,
                'url': url,
                'eps': eps,
                'weight': 1,
                'order': index,
            })

        # 实测各线路可播性：能播的排前面（直链活 > 页面需解析 > 直链失效）
        if entries:
            for entry, weight in zip(entries, weights_of(entries)):
                entry['weight'] = weight

        # 能播的线路排前面：权重升序，同权重保持原顺序
        entries.sort(key=lambda e: (e['weight'], e['order']))

        pref = _pref.get(vid)
        if pref:
            for i, e in enumerate(entries):
                if e['flag'] == pref:
                    entries.insert(0, entries.pop(i))
                    break

        line_cache = []
        for e in entries:
            line_cache.append({'flag': e['flag'], 'eps': e['eps']})
            for key, url in e['eps']:
                _id_index[url] = (vid, key, e['flag'])
        _trim(_id_index, 4000)
        _lines[vid] = line_cache
        _trim(_lines, 200)

        vod['vod_id'] = vid
        vod['vod_pic'] = abs_url(vod.get('vod_pic'))
        vod['vod_play_from'] = '$$$'.join(e['flag'] for e in entries)
        vod['vod_play_url'] = '$$$'.join(e['url'] for e in entries)
        vod['vod_remarks'] = text(vod.get('vod_remarks')) or 'HD'
        lst.append(vod)
        _trim(_detail_cache, 200)
        _detail_cache[vid] = (time.time() + DETAIL_CACHE_TTL, dict(vod), line_cache)

        # 后台预热第一条线路的首集：用户点播放时基本已命中缓存
        if entries and len(_warming) < 3:
            head = entries[0]['eps'][0][1]
            if head and not is_media_url(head) and head not in _warming:
                _warming.add(head)
                th = threading.Thread(target=warm, args=(head,))
                th.daemon = True
                th.start()
    return {'list': lst}


def search(key, pg):
    wd = text(key)
    page = page_of(pg)
    if not wd:
        return paginated({'list': []}, page)
    data = cms('search', {'text': wd, 'pg': str(page)})
    lst = []
    for item in list_of(data.get('list')):
        if isinstance(item, dict):
            lst.append({k: v for k, v in item.items() if k != 'type'})
    data['list'] = lst
    return paginated(data, page)


# ---------------------------------------------------------------- 播放
def play_header(url, base=None):
    """给播放器的请求头。带上我们在探测阶段拿到的 CDN 会话 cookie：
    影像 CDN 会先发一个 server_session_* 再校验，播放器裸请求等于换了个人，
    分片直接 404/403 —— 这是「检测」里最容易被忽略的一环。"""
    h = dict(base if base is not None else PLAY_HEADERS)
    ck = cookie_header(url)
    if ck:
        h['Cookie'] = ck
    return h


def play(play_id):
    """原始地址 -> 真实可播地址。直链直出，页面走解析，最后降级嗅探。"""
    original = text(decrypt_lvdou(play_id))
    if not original:
        return {'parse': 0, 'url': '', 'header': dict(PLAY_HEADERS)}

    if is_ldmax_url(original):
        decrypted = decrypt_ldmax(original)
        if decrypted:
            original = decrypted

    now = time.time()
    cached = _play_cache.get(original)
    if cached and cached[0] > now:
        return {'parse': 0, 'url': cached[1], 'header': play_header(cached[1])}

    # 1) 本身就是媒体直链：探测后直接给播放器，不浪费解析接口
    if is_media_url(original):
        state = probe(original)
        if state is not False:
            _trim(_play_cache)
            _play_cache[original] = (now + PLAY_CACHE_TTL, original)
            return {'parse': 0, 'url': original, 'header': play_header(original)}
        # 可能是 6 秒过期的中转地址：跟一次 302 换长期地址
        landed = finalize(original)
        if landed and landed != original and probe(landed) is not False:
            _trim(_play_cache)
            _play_cache[original] = (now + PLAY_CACHE_TTL, landed)
            return {'parse': 0, 'url': landed, 'header': play_header(landed)}
        # 文件确实没了：快速失败，交给上层切线路
        return {'parse': 0, 'url': '', 'header': dict(PLAY_HEADERS)}

    # 2) 页面地址（腾讯/爱奇艺/优酷/B站）：走解析接口
    resolved = parse_url(original)
    if resolved:
        _trim(_play_cache)
        _play_cache[original] = (now + PLAY_CACHE_TTL, resolved)
        return {'parse': 0, 'url': resolved, 'header': play_header(resolved)}

    # 3) 解析失败：降级让播放器自己嗅探，比返回空 url 强
    return {'parse': 1, 'url': original, 'header': dict(WEB_HEADERS)}


def play_with_fallback(play_id):
    """当前地址播不了时，自动切同剧其它线路的同集。

    解析服务整体熔断时不再逐条线路重试：那只会把同样的请求再打 N 遍，
    对站点来说是「这个人疯了一样在刷」，对我们来说纯粹浪费 10 秒。
    直接降级给播放器嗅探。
    """
    result = play(play_id)
    good = bool(result.get('url')) and result.get('parse') == 0
    if good:
        ref = _id_index.get(text(play_id))
        if ref:
            _pref[ref[0]] = ref[2]
        return result

    if _parse_down[0] > time.time() and not is_media_url(text(play_id)):
        return result

    ref = _id_index.get(text(play_id))
    if not ref:
        return result
    vid, key, cur_flag = ref

    # 先试上次成功的线路
    order = []
    pref = _pref.get(vid)
    for line in _lines.get(vid, []):
        if line['flag'] == pref and line['flag'] != cur_flag:
            order.append(line)
    for line in _lines.get(vid, []):
        if line['flag'] != cur_flag and line['flag'] != pref:
            order.append(line)

    for line in order:
        target = ''
        for k, alt in line['eps']:
            if k == key and alt and alt != play_id:
                target = alt
                break
        if not target and len(line['eps']) == 1:
            # 电影只有一集，集名不同也能对上
            target = line['eps'][0][1]
        if not target:
            continue
        retry = play(target)
        if retry.get('url') and retry.get('parse') == 0:
            _pref[vid] = line['flag']
            return retry

    return result


# ---------------------------------------------------------------- 入口
# ══════════════════════════════════════════════════════════════
# 宿主网络层桥接（新内核 runtime/net.py 契约）
# ══════════════════════════════════════════════════════════════
# self.net 在 init 前由 App 注入：req(url, options) -> {error, code, content, headers}
# options.timeout 单位毫秒，buffer=3 取 bytes。
# 没有 self.net 时回落 requests / urllib，同一份代码在新旧内核都能跑。
# 注意：需要「跟随 302 后的最终 URL」或「大文件流式读取」的分支仍用原实现，
# 因为 net.req 不返回最终 URL —— 那不是可以机械替换的地方。
import json as _json

_NET = [None]


def _bind_net(spider):
    _NET[0] = getattr(spider, "net", None)
    return _NET[0]


def _ms(timeout):
    if isinstance(timeout, (list, tuple)):
        timeout = max([float(x) for x in timeout if x is not None] or [10.0])
    return max(1000, int(float(timeout or 10) * 1000))


def _resp_bytes(resp):
    content = resp.get("content")
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    if isinstance(content, str):
        return content.encode("utf-8")
    return b""


def _resp_text(resp):
    return _resp_bytes(resp).decode("utf-8", "replace")


def _net_ok(resp):
    if not resp or resp.get("error"):
        return False
    code = int(resp.get("code") or 0)
    return not code or 200 <= code < 300


class Spider(BaseSpider):

    def getDependence(self):
        # 运行时已内置 requests / pycryptodome，声明依赖会被当成本地模块下载
        return []

    def init(self, extend=''):
        _bind_net(self)          # 宿主在 init 前注入 self.net
        self.extend = extend or ''
        _apply_extend(self.extend)   # 支持 {"ua":..,"proxy":..,"gap":..}
        return self

    def isVideoFormat(self, url):
        return is_media_url(url)

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter=False):
        return home()

    def homeVideoContent(self):
        return home_vod()

    def categoryContent(self, tid, pg="1", filter=False, extend=None):
        return category(tid, pg, extend)

    def detailContent(self, ids):
        return detail(ids)

    def searchContent(self, key, quick=True, pg="1"):
        return search(key, pg)

    def playerContent(self, flag, id, vipFlags=None):
        return play_with_fallback(id)

    def destroy(self):
        _play_cache.clear()
        _probe_cache.clear()
        _detail_cache.clear()
        _lines.clear()
        _id_index.clear()
        _pref.clear()
        _pid_dead.clear()
        _parse_down[0] = 0.0
        _ban_until.clear()
        _ban_streak.clear()
        _last_hit.clear()
        _reset_session()     # 换站/换网时重开会话，别把旧 IP 的风控状态带过去
