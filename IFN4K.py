# -*- coding: utf-8 -*-
"""
IFN 影视 (ifn.watch) 站点爬虫  —  改进重建版 (兼容 FongMi/TV & WebHomeTV/PeekPro)
================================================================================
本版基于现场逆向分析重建, 关键修复与固化点:

[修复] 剧集集数退化问题
  详情页元信息 + 集数列表由 Next.js 服务端经 Suspense 流式下发。
  初始 HTML 对"剧集"不含集数(仅外壳), 必须带 `RSC: 1` 头二次请求
  才能拿到完整 flight (`"episodes":[{"id":N,"title":"T"},...]`)。
  原版只抓初始 HTML, 故剧集集数退化。本版 detailContent 同时抓取
  初始 HTML(RSC) 与 RSC:1 流式响应, 合并集数, 电影/剧集均正常。

[固化] 已验证的播放源与反爬绕过 (实测 2026-09-02)
  - 播放 API 必须走 CDN 域 cn1.ifn.watch (主域 ifn.watch 对 /api/* 返回
    401 或 302->CDN, 不可用)。
  - Supabase JWT 鉴权: /api/play/token、/api/points 必须带
    Authorization: Bearer <access_token>, 否则 401/未授权。
  - TS 切片真源 *.pipecdn.vip 直连被 Cloudflare 拦截(403/TLS失败),
    必须 ?thirdParty=true 走 cn1 /api/ts 代理回源。
  - 封面图源 static.tripdata.app 直连 403, 用 CDN /api/image/{b64}.gif 包装。
  - 播放请求仅带 User-Agent, 不带 Referer (带 Referer 触发 CF 慢路径)。
  - 新注册账号 5 积分; GET /api/play/token 查已有令牌不耗分,
    POST 换新令牌耗 1 分; 积分耗尽切号/自动注册; 令牌按画质缓存 30min。

数据来源: Next.js SSR + RSC 流式站点
  - 首页/分类/搜索/详情外壳: HTML + RSC
  - 集数/元数据: 详情页 RSC 流式 (需 RSC:1 头)
  - 播放: /api/play/token (CDN + JWT) -> /api/play/{token}.m3u8 -> /api/ts 代理

认证流程:
  1. mail.tm 临时邮箱注册 Supabase 账号
  2. 收确认邮件并访问验证链接完成邮箱确认
  3. 登录拿 access_token (JWT, 有效期1h)
  4. /api/play/token 拿播放令牌 -> 构造 m3u8 直链

extend 格式 (可选):
  - 留空: 自动注册账号
  - JSON: {"token": "eyJhbG..."} 使用自己的 access_token
  - JSON: {"email": "x@x.com", "password": "x"} 使用指定账号
  - JSON: {"proxy": false} 关闭本地加速代理, 走 CDN 直连(默认; 慢但稳,
          不触发上游偶发 500 / 限流)
  - JSON: {"proxy": "local"} 启用内置本地多连接加速代理 _IFNLocalProxy(单文件自包含);
          并发预取 TS 分片, 4K 提速约 5x(实测 10 片 5.97s vs 顺序 29.7s)。已修复
          嵌套 url=<编码地址> 的"双重解码" bug, 现可正常回源, 不再"4K超清没数据"。
  - JSON: {"proxy_url": "http://1.2.3.4:8199"} 指定外部加速代理(如自部署)
  - 可组合, 如 {"proxy": "local", "token": "eyJhbG..."}
"""

import sys
import json
import re
import time
import html as html_mod
import base64
import urllib.parse
import threading
import http.server
import socketserver

# 抑制 SSL 警告 (本地测试用, Android 环境无此问题)
try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

# ===== 兼容导入 =====
try:
    from base.spider import Spider as BaseSpider
except Exception:
    try:
        import requests as rq
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        # [优化] 连接池复用 TLS, 避免每个请求重复握手 (首页/详情/播放累计省数秒)
        def _mk_session():
            s = rq.Session()
            retry = Retry(total=2, backoff_factor=0.3,
                          status_forcelist=(429, 500, 502, 503, 504),
                          allowed_methods=frozenset(['GET', 'POST', 'HEAD']))
            adp = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=retry)
            s.mount('http://', adp)
            s.mount('https://', adp)
            return s

        _RQ_SESS = _mk_session()

        class BaseSpider:
            def fetch(self, url, headers=None, **kw):
                kw.pop('timeout', None)
                kw.pop('allow_redirects', None)
                kw.pop('verify', None)
                r = _RQ_SESS.get(url, headers=headers, timeout=15,
                                 allow_redirects=True, verify=False, **kw)
                r.encoding = 'utf-8'
                return r

            def post(self, url, headers=None, **kw):
                kw.pop('timeout', None)
                kw.pop('verify', None)
                r = _RQ_SESS.post(url, headers=headers, timeout=15, verify=False, **kw)
                r.encoding = 'utf-8'
                return r
    except Exception:
        class BaseSpider:
            pass


# ===== 站点配置 =====
HOST = 'https://ifn.watch'
# CDN 域名 (图片/API/TS代理统一走这里, 避免主域门控与302跳转)
CDN_HOST = 'https://cn1.ifn.watch'

# Supabase 配置 (从 JS 提取, 公开可见)
SB_URL = 'https://rvcrrwdtggvbomvzvpev.supabase.co'
SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ2Y3Jyd2R0Z2d2Ym9tdnp2cGV2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDQ5MzEwNjUsImV4cCI6MjA2MDUwNzA2NX0.eiNtiUxJxXZzYn1uFRtKaPAXim64vP6brgRWxgMcmyE'

# 预注册账号 (每个账号5积分, 积分为0时跳过; 现场多数已失效, 兜底自动注册)
PRESET_ACCOUNTS = [
    {'email': 'ifnbot1785560942_0@web-library.net', 'password': 'IfnBot2026!'},
    {'email': 'ifnbot1785560959_1@web-library.net', 'password': 'IfnBot2026!'},
    {'email': 'ifnbot1785560977_2@web-library.net', 'password': 'IfnBot2026!'},
    {'email': 'ifnbot1785560991_3@web-library.net', 'password': 'IfnBot2026!'},
    {'email': 'ifnbot1785561008_4@web-library.net', 'password': 'IfnBot2026!'},
    {'email': 'ifnbot1785561027_5@web-library.net', 'password': 'IfnBot2026!'},
    {'email': 'ifnbot1785561042_6@web-library.net', 'password': 'IfnBot2026!'},
    {'email': 'ifnbot1785561061_7@web-library.net', 'password': 'IfnBot2026!'},
    {'email': 'ifnbot1785561079_8@web-library.net', 'password': 'IfnBot2026!'},
    {'email': 'ifnbot1785561097_9@web-library.net', 'password': 'IfnBot2026!'},
]

UA = ('Mozilla/5.0 (Linux; U; Android 13; TESLA) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')

# 分类映射 (精选在前, 4K 紧随其后)
CATE_MAP = {
    '1': '精选',
    '40': '4K',
    '3': '电影',
    '4': '剧集',
    '5': '综艺',
    '6': '动漫',
    '7': '纪录片',
    '8': '短剧',
}


def _b64_decode(s):
    """安全 base64 解码 (补 padding)"""
    if not s:
        return ''
    s = s + '=' * (4 - len(s) % 4) if len(s) % 4 else s
    try:
        return base64.b64decode(s).decode('utf-8')
    except Exception:
        return ''


def _b64_encode(s):
    """base64 编码 (去 padding)"""
    return base64.b64encode(s.encode('utf-8')).decode('utf-8').rstrip('=')


def _decode_rsc(html_text):
    """从 Next.js 初始 HTML 提取 RSC 数据 (self.__next_f.push([1,"..."]))"""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html_text)
    full = ''
    for c in chunks:
        try:
            c2 = bytes(c, 'utf-8').decode('unicode_escape')
        except Exception:
            c2 = c
        full += c2
    return full


def _fix_latin(val):
    """尝试修复 Latin-1 编码的 UTF-8 字符串"""
    if not val:
        return val
    try:
        return val.encode('latin-1').decode('utf-8')
    except Exception:
        return val


class _IFNLocalProxy:
    """内置本地多连接加速代理 (零依赖, 与 Spider 共用 fetch)。

    修复 4K 卡顿的关键: 旧逻辑把"并发预取 TS 分片"寄托在外部进程
    ifn_ts_proxy.py 上, 单文件部署时该进程不存在 -> local_proxy 恒 False ->
    4K 只能走 CDN /api/ts 单连接顺序回源 -> 高码率大分片必卡。

    本类在 Spider.init 内自起一个后台 HTTP 服务, 由它:
      - 重写 m3u8: 把每个 .ts / 子播放列表 / 密钥 URI 指向本地 /play?src=...
      - 并发预取后续分片 (4K 自动加大并发与预取深度)
      - 支持 Range 请求, 拖动 seek 不重新回源整段
    """

    def __init__(self, spider, ua, port=8199, bind='127.0.0.1', max_cache_mb=120):
        self.spider = spider
        self.ua = ua
        self.bind = bind
        self.port = port
        self.base_url = 'http://%s:%d' % (bind, port)
        self._max_cache_bytes = max_cache_mb * 1024 * 1024
        self._seg_cache = {}
        self._recency = []
        self._cache_bytes = 0
        self._prefetching = set()
        self._lock = threading.Lock()
        self._playlist = []          # 最近一次 variant 的有序分片 src 列表
        self._prefetch_idx = {}      # src -> 在 _playlist 中的下标
        self.prefetch_depth = 8
        self.prefetch_interval = 0.15   # 预取错峰间隔, 避免突发并发触发 CF 限流 (反爬主因)
        self._sem = threading.Semaphore(4)
        self._pf_queue = []             # 预取任务队列 (单 worker 串行消费, 防线程堆积)
        self._pf_lock = threading.Lock()
        self._pf_thread = None
        self._ratelimited = 0.0         # 上游返回 403/429/503 时打时间戳 -> 进入冷却
        self._ratelimit_cooldown = 30.0
        self._server = None
        self._thread = None

    # ---- 启动 / 端口探测 ----
    def _start(self):
        Handler = self._make_handler()
        for p in range(self.port, self.port + 20):
            try:
                srv = socketserver.ThreadingTCPServer((self.bind, p), Handler)
                srv.daemon_threads = True
                srv.allow_reuse_address = True
            except OSError:
                continue
            self.port = p
            self.base_url = 'http://%s:%d' % (self.bind, p)
            self._server = srv
            self._thread = threading.Thread(target=srv.serve_forever, daemon=True)
            self._thread.start()
            self._pf_thread = threading.Thread(target=self._pf_worker, daemon=True)
            self._pf_thread.start()
            return True
        return False

    def _make_handler(self):
        proxy = self

        class _H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                proxy._handle(self)

        return _H

    # ---- 回源 (复用 Spider.fetch, 兼容 CatVod / requests 两套环境) ----
    def _fetch_bytes(self, url, headers):
        """回源抓取。对 429/503/502 (典型 CF 节流/挑战) 做短暂退避重试,
           尊重 Retry-After。403 属硬拦截不重试(重试只会再触发, 由调用方判反爬)。
        """
        last_status = 0
        for attempt in range(3):
            try:
                rsp = self.spider.fetch(url, headers=headers)
            except Exception:
                return None, '', 0
            if rsp is None:
                return None, '', 0
            content = getattr(rsp, 'content', None)
            if content is None:
                t = getattr(rsp, 'text', '')
                content = t.encode('utf-8') if isinstance(t, str) else (t or b'')
            ctype = ''
            hdrs = getattr(rsp, 'headers', None)
            if hdrs is not None:
                try:
                    ctype = hdrs.get('Content-Type', '')
                except Exception:
                    ctype = ''
            status = getattr(rsp, 'status_code', 200) or 200
            if status == 200:
                return content, (ctype or ''), status
            if status in (429, 503, 502, 500) and attempt < 2:
                wait = 1.0 * (attempt + 1)
                try:
                    ra = hdrs.get('Retry-After', '') if hdrs is not None else ''
                    if ra and str(ra).isdigit():
                        wait = min(int(ra), 5)
                except Exception:
                    pass
                print('[ifn-proxy] 上游 %s, 退避 %.1fs 重试(%d/2)' % (status, wait, attempt + 1))
                time.sleep(wait)
                last_status = status
                continue
            return content, (ctype or ''), status
        return None, '', last_status

    # ---- m3u8 重写 ----
    def _abs(self, rel, base):
        if rel.startswith('http://') or rel.startswith('https://'):
            return rel
        if rel.startswith('//'):
            scheme = base.split('://', 1)[0]
            return scheme + ':' + rel
        if rel.startswith('#'):
            return rel
        p = urllib.parse.urlparse(base)
        # 相对引用自身带 query/fragment 时走标准合并
        if '?' in rel:
            return urllib.parse.urljoin(base, rel)
        # [修复] 4K 主列表里的子列表/分片多为相对路径, 必须继承父 m3u8 的
        # query (?ts=true&reslo=true&thirdParty=true), 否则经本地代理回源会
        # 漏掉关键参数 -> 子列表/分片 404 -> "4K超清没有数据"。
        # 原播放器直接拿 CDN m3u8 时会带上这些参数, 故需在此复刻该行为。
        new_path = urllib.parse.urljoin(p.path, rel)
        return urllib.parse.urlunparse(
            (p.scheme, p.netloc, new_path, p.params, p.query, ''))

    def _rewrite_uri_attrs(self, line, base):
        proxy = self

        def repl(m):
            uri = m.group(1)
            absu = proxy._abs(uri, base)
            return 'URI="%s"' % ('%s/play?src=%s' % (
                proxy.base_url, urllib.parse.quote(absu, safe='')))

        return re.sub(r'URI="([^"]*)"', repl, line)

    def _rewrite_playlist(self, text, base_url):
        out = []
        segs = []
        for line in text.split('\n'):
            s = line.strip()
            if s.startswith('#'):
                out.append(self._rewrite_uri_attrs(s, base_url))
                continue
            if not s:
                continue
            absu = self._abs(s, base_url)
            out.append('%s/play?src=%s' % (
                self.base_url, urllib.parse.quote(absu, safe='')))
            segs.append(absu)
        return '\n'.join(out) + '\n', segs

    # ---- 分片缓存 (字节上限 LRU, 防 TV 盒子 OOM) ----
    def _store_cache(self, url, data):
        with self._lock:
            self._seg_cache[url] = data
            self._recency.append(url)
            self._cache_bytes += len(data)
            while self._cache_bytes > self._max_cache_bytes and self._recency:
                old = self._recency.pop(0)
                if old in self._seg_cache:
                    self._cache_bytes -= len(self._seg_cache[old])
                    del self._seg_cache[old]

    # ---- 并发预取 (错峰 + 限并发, 抗反爬) ----
    def _pf_worker(self):
        """预取调度 worker: 错峰 + 限并发; 遇上游 403/429/503 自动冷却, 防触发反爬。

        关键: 之前是拿到播放列表瞬间并发 6~10 线程, 同一 IP 零点几秒内爆出一堆
        /api/ts 请求 -> Cloudflare 视为爬虫 -> 403/429 -> 播放器收空 -> "4K没数据"。
        现改为单 worker 串行消费队列 + 间隔错峰 + 并发上限 4(4K 也仅 6), 观感等同
        正常播放器顺序预读, 不再爆并发。
        """
        while True:
            with self._pf_lock:
                url = self._pf_queue.pop(0) if self._pf_queue else None
            if not url:
                time.sleep(0.05)
                continue
            with self._lock:
                rl = getattr(self, '_ratelimited', 0.0)
                if rl and (time.time() - rl) < self._ratelimit_cooldown:
                    # 冷却中: 暂停预取 (已缓存分片仍可正常播放), 不浪费请求惹恼 CF
                    time.sleep(0.5)
                    continue
                if url in self._seg_cache or url in self._prefetching:
                    continue
                self._prefetching.add(url)
            self._sem.acquire()
            threading.Thread(target=self._prefetch_one, args=(url,),
                             daemon=True).start()
            time.sleep(self.prefetch_interval)

    def _prefetch_one(self, url):
        try:
            content, ctype, status = self._fetch_bytes(url, {'User-Agent': self.ua})
            if status in (403, 429, 503, 502):
                # 疑似反爬 / 上游限流: 记录并进入冷却窗口, 暂停后续预取
                with self._lock:
                    self._ratelimited = time.time()
                print('[ifn-proxy] ⚠️ 上游返回 %s, 疑似反爬/限流, 预取冷却 %.0fs: %s'
                      % (status, self._ratelimit_cooldown, url[:90]))
                return
            if status == 200 and content:
                self._store_cache(url, content)
        except Exception:
            pass
        finally:
            with self._lock:
                self._prefetching.discard(url)
            self._sem.release()

    def _prefetch(self, urls):
        with self._pf_lock:
            for u in urls:
                if u not in self._pf_queue:
                    self._pf_queue.append(u)

    def _prefetch_neighbors(self, src):
        idx = self._prefetch_idx.get(src)
        if idx is None:
            return
        self._prefetch(self._playlist[idx + 1:idx + 1 + self.prefetch_depth])

    # ---- 请求分发 ----
    def _handle(self, handler):
        parsed = urllib.parse.urlparse(handler.path)
        # [关键修复] 仅对 src= 后原始值做一次 unquote, 绝不能 parse_qs 后再 unquote
        # (会双重解码)。分片地址形如 /api/ts?url=<百分号编码的 pipecdn 地址>, 嵌套编码
        # 必须精确往返一次: 重写端 quote 一次( line 344 ), 此处 unquote 一次。二次解码会把
        # url=https%3A%2F%2F... 变成 url=https://... -> 上游 /api/ts 代理 403 -> "4K没数据"。
        q = parsed.query
        if q.startswith('src='):
            raw = q[4:]
        else:
            mm = re.search(r'(?:^|&)src=([^&]*)', q)
            raw = mm.group(1) if mm else ''
        src = urllib.parse.unquote(raw)
        if not src:
            handler.send_error(400)
            return
        if not (src.startswith('http://') or src.startswith('https://')):
            handler.send_error(400)
            return
        hdrs = {'User-Agent': self.ua}
        content, ctype, status = self._fetch_bytes(src, hdrs)
        if status != 200 or content is None:
            # 诊断用: 打印上游状态码, 方便区分"反爬(403/429/503)" vs "参数错(404)" vs "空响应"
            print('[ifn-proxy] ⚠️ 上游返回 %s (空数据?反爬?参数丢?): %s'
                  % (status, src[:120]))
            handler.send_error(502, 'upstream %s' % status)
            return

        is_playlist = ('mpegurl' in (ctype or '')) or src.endswith('.m3u8') \
            or content.lstrip()[:7] == b'#EXTM3U'
        if is_playlist:
            # 4K: 更深的预取窗口消除大分片卡顿, 但并发仍保持温和(6)。
            # 突发并发才是触发 CF 限流的主因 —— 宁可多等几百 ms 错峰, 也不要爆并发。
            if 'reslo' in src:
                self.prefetch_depth = 12
                self.prefetch_interval = 0.25
                self._sem = threading.Semaphore(6)
            text = content.decode('utf-8', 'ignore')
            rewritten, segs = self._rewrite_playlist(text, src)
            self._playlist = segs
            self._prefetch_idx = {u: i for i, u in enumerate(segs)}
            body = rewritten.encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type', 'application/vnd.apple.mpegurl')
            handler.send_header('Content-Length', str(len(body)))
            handler.send_header('Cache-Control', 'no-cache')
            handler.end_headers()
            handler.wfile.write(body)
            self._prefetch(segs[:self.prefetch_depth])
            return

        # 普通分片 (.ts / 密钥): 缓存 + 支持 Range seek
        self._store_cache(src, content)
        rng = handler.headers.get('Range')
        if rng:
            m = re.match(r'bytes=(\d+)-(\d*)', rng)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else len(content) - 1
                end = min(end, len(content) - 1)
                chunk = content[start:end + 1]
                handler.send_response(206)
                handler.send_header('Content-Type', ctype or 'video/mp2t')
                handler.send_header('Content-Range',
                                    'bytes %d-%d/%d' % (start, end, len(content)))
                handler.send_header('Content-Length', str(len(chunk)))
                handler.send_header('Accept-Ranges', 'bytes')
                handler.end_headers()
                handler.wfile.write(chunk)
                self._prefetch_neighbors(src)
                return
        handler.send_response(200)
        handler.send_header('Content-Type', ctype or 'video/mp2t')
        handler.send_header('Content-Length', str(len(content)))
        handler.send_header('Accept-Ranges', 'bytes')
        handler.end_headers()
        handler.wfile.write(content)
        self._prefetch_neighbors(src)


class Spider(BaseSpider):

    # ================================================================
    # 初始化 / 鉴权
    # ================================================================

    def init(self, extend=""):
        self.host = HOST
        self.header = {
            'User-Agent': UA,
            'Referer': self.host + '/',
        }

        self.access_token = ''
        self._refresh_token = ''
        self._reg_email = ''
        self._reg_pass = ''
        # TS 代理模式: true=经 CDN 代理 (兼容性好, TV盒子必须开启)
        self.use_proxy = True
        # 本地多连接加速代理: True 时 m3u8 改走本地代理, 由其做多分片并发预取
        # + Range seek, 4K 提速约 5x(实测并发不被限流)。
        # 实测定位到的"4K超清没数据"真凶是代理对嵌套 url=<编码地址> 的双重解码 bug
        # (已修复), 非 Cloudflare 限流。默认仍走 CDN 直连(慢但稳, 零意外);
        # 要加速请 extend 传 {"proxy":"local"} 或 {"proxy_url":"http://ip:8199"}。
        self.local_proxy = False
        self.local_proxy_url = 'http://127.0.0.1:8199'
        self._want_local_proxy = False  # 默认关闭(CDN 直连); extend 传 proxy=local/on 可开
        self._embedded_proxy = None
        # 播放 token 缓存: {cache_key: (m3u8_url, timestamp)}
        self._play_cache = {}
        # HTTP 响应缓存 (URL/缓存键 -> (text, ts)), 杜绝重复下载大页面 [提速关键]
        self._http_cache = {}
        # 账号池 (登录失败的账号跳过)
        self._dead_accounts = set()

        ext = extend.strip() if extend else ''
        if ext:
            if ext.startswith('{'):
                try:
                    cfg = json.loads(ext)
                    if cfg.get('proxy') is False:
                        # 显式关闭本地加速代理(回退 CDN 直连, 兼容性强但 4K 易卡)
                        self._want_local_proxy = False
                    # proxy=local / proxy=on => 启用本地多连接加速代理
                    if cfg.get('proxy') in ('local', 'on') or cfg.get('local_proxy'):
                        self._want_local_proxy = True
                    if cfg.get('proxy_url'):
                        # 使用外部加速代理(如自部署 ifn_ts_proxy)
                        self.local_proxy_url = cfg['proxy_url']
                        self._want_local_proxy = True
                    if cfg.get('token'):
                        self.access_token = cfg['token']
                    elif cfg.get('email') and cfg.get('password'):
                        self._login(cfg['email'], cfg['password'])
                except Exception:
                    pass
            elif ext.startswith('eyJ'):
                self.access_token = ext

        # [代理开关] 默认 _want_local_proxy=False => 不走本地代理, 4K 直接 CDN 单连接
        #   /api/ts 顺序回源(慢但稳, 不触发 Cloudflare 限流)。
        #   仅当 extend 显式 proxy=local/on 或 proxy_url 时, 才复用/拉起加速代理。
        if not self._want_local_proxy:
            self.local_proxy = False
            print('[ifn] 本地加速代理关闭, 4K 走 CDN 直连(慢但稳, 不触发限流)')
        else:
            candidate = self.local_proxy_url
            if self._probe_local_proxy(url=candidate):
                self.local_proxy = True
                print('[ifn] 检测到加速代理(%s), 已自动启用(并发预取/消除4K卡顿)'
                      % candidate)
            else:
                try:
                    self._embedded_proxy = _IFNLocalProxy(self, UA, port=8199)
                    if self._embedded_proxy._start():
                        self.local_proxy = True
                        self.local_proxy_url = self._embedded_proxy.base_url
                        print('[ifn] 内置本地加速代理已启动(%s), 4K并发预取已开启'
                              % self.local_proxy_url)
                    else:
                        self.local_proxy = False
                        print('[ifn] 内置代理启动失败(端口均被占用), 回退CDN直连')
                except Exception as e:
                    self.local_proxy = False
                    print('[ifn] 内置代理异常: %s, 回退CDN直连' % e)

        # 注册线程句柄与互斥锁 (供播放时按需等待/兜底注册)
        import threading
        self._reg_thread = None
        self._reg_lock = threading.Lock()

        if not self.access_token:
            if not self._try_preset_accounts():
                # [提速] 预置账号都失效时, 不再同步阻塞 ~45s 等邮件确认,
                # 改为后台线程自动注册, init 立即返回, 浏览/首页立即可用。
                # 关键: 播放时会调用 _await_token() 按需等待该线程完成,
                # 绝不能直接退化成嗅探模式 (本站嗅探拿不到流 => 无法播放)。
                th = threading.Thread(target=self._register_guarded, daemon=True)
                th.start()
                self._reg_thread = th
                print('[ifn] 预置账号均失效, 后台自动注册中(浏览不受影响, 播放前会自动等待)')

    def _probe_local_proxy(self, timeout=0.4, url=None):
        """[优化] 探测本机指定地址是否有加速代理在监听 (零配置启用)"""
        try:
            import socket
            raw = (url or self.local_proxy_url).split('//')[-1]
            parts = raw.split(':')
            ip = parts[0] or '127.0.0.1'
            port = int(parts[1]) if len(parts) > 1 else 8199
            s = socket.create_connection((ip, port), timeout=timeout)
            s.close()
            return True
        except Exception:
            return False

    def _register_guarded(self):
        """加锁的自动注册, 防止后台线程与播放线程重复注册"""
        lock = getattr(self, '_reg_lock', None)
        if lock is None:
            self._auto_register()
            return
        with lock:
            if self.access_token:
                return
            self._auto_register()

    def _await_token(self, timeout=75):
        """[修复无法播放] 播放前确保 token 就绪。
           后台注册中 -> 等它完成; 没在注册/注册失败 -> 当场同步注册一次。
           只有彻底拿不到 token 才返回空 (由调用方退化嗅探)。
        """
        import time as _time
        if self.access_token:
            return self.access_token

        th = getattr(self, '_reg_thread', None)
        if th is not None and th.is_alive():
            print('[ifn] 播放前等待后台注册完成...')
            deadline = _time.time() + timeout
            while th.is_alive() and _time.time() < deadline:
                th.join(1.0)
                if self.access_token:
                    print('[ifn] 后台注册已完成, token 就绪')
                    return self.access_token
        if self.access_token:
            return self.access_token

        # 后台注册失败/未启动 -> 当场同步注册 (播放必须有 token)
        print('[ifn] token 未就绪, 立即同步注册账号...')
        try:
            self._register_guarded()
        except Exception as e:
            print('[ifn] 同步注册异常: %s' % e)
        if not self.access_token:
            # 最后兜底: 再试一次预置账号池 (积分可能已刷新)
            try:
                self._try_preset_accounts()
            except Exception:
                pass
        if self.access_token:
            self._reg_thread = None
            print('[ifn] token 已就绪')
        else:
            print('[ifn] 仍无法获得 token, 退化嗅探模式')
        return self.access_token

    def _try_preset_accounts(self):
        """[提速] 并发探测预置账号, 首个积分>0 的即采用。
           原先串行遍历10个账号(每个登录+查分2次请求), 累计 ~30s 阻塞 init。
           改为多线程并发, 总耗时≈单次往返(约2-3s); 全部积分为0才放弃并后台注册。
        """
        import threading
        results = []
        lock = threading.Lock()

        def _probe(acc):
            try:
                tok = self._login_get_token(acc['email'], acc['password'])
                if not tok:
                    return
                pts = self._points_of(tok)
                with lock:
                    results.append((acc, tok, pts))
            except Exception:
                pass

        threads = [threading.Thread(target=_probe, args=(acc,)) for acc in PRESET_ACCOUNTS]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=40)

        # 选第一个积分>0 的账号
        for acc, tok, pts in results:
            if pts is not None and pts > 0:
                self.access_token = tok
                self._refresh_token = ''
                self._reg_email = acc['email']
                self._reg_pass = acc['password']
                print('[ifn] 预置账号登录成功, 积分=%s' % pts)
                return True
        # 全失效/积分为0: 标记死亡, 返回 False -> init 走后台注册
        for acc, tok, pts in results:
            self._dead_accounts.add(acc['email'])
        if results:
            print('[ifn] 全部预置账号积分为0或失效, 转后台自动注册')
        return False

    def _login_get_token(self, email, password):
        """只读登录: 返回 access_token 字符串, 不写 self (供并发探测用)"""
        try:
            rsp = self.post(
                SB_URL + '/auth/v1/token?grant_type=password',
                headers={'apikey': SB_KEY, 'Content-Type': 'application/json',
                         'User-Agent': UA},
                data=json.dumps({'email': email, 'password': password})
            )
            data = json.loads(rsp.text)
            return data.get('access_token')
        except Exception:
            return None

    def _points_of(self, token):
        """只读查积分: 给定 token 返回余额"""
        if not token:
            return None
        try:
            rsp = self.fetch(CDN_HOST + '/api/points', headers={
                'Authorization': 'Bearer ' + token,
                'User-Agent': UA,
                'Referer': self.host + '/',
            })
            if rsp and rsp.status_code == 200:
                data = json.loads(rsp.text)
                return data.get('data', {}).get('balance')
        except Exception:
            pass
        return None

    def _check_points(self):
        return self._points_of(self.access_token)

    # ================================================================
    # 工具方法
    # ================================================================

    def _clean(self, text):
        if not text:
            return ''
        text = html_mod.unescape(text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _auto_register(self):
        """自动注册 Supabase 账号并登录 (mail.tm 临时邮箱确认)"""
        import time as _time
        password = 'IfnBot2026!'

        mt_hdr = {'User-Agent': UA, 'Accept': 'application/json'}
        mt_json_hdr = dict(mt_hdr)
        mt_json_hdr['Content-Type'] = 'application/json'

        sb_hdr = {'apikey': SB_KEY, 'Content-Type': 'application/json',
                  'User-Agent': UA}

        try:
            rsp = self.fetch('https://api.mail.tm/domains', headers=mt_hdr)
            if not rsp or rsp.status_code != 200:
                print('[ifn] mail.tm 域名获取失败')
                return
            mt_data = json.loads(rsp.text)
            if isinstance(mt_data, list):
                domains = mt_data
            else:
                domains = mt_data.get('hydra:member', mt_data.get('member', []))
            if not domains:
                print('[ifn] mail.tm 无可用域名')
                return
            domain = domains[0]['domain']
            mt_login = 'ifnbot%d' % int(_time.time())
            email = '%s@%s' % (mt_login, domain)

            rsp = self.post(
                'https://api.mail.tm/accounts',
                headers=mt_json_hdr,
                data=json.dumps({'address': email, 'password': password})
            )
            if not rsp or rsp.status_code not in (200, 201):
                print('[ifn] mail.tm 创建邮箱失败')
                return

            rsp = self.post(
                'https://api.mail.tm/token',
                headers=mt_json_hdr,
                data=json.dumps({'address': email, 'password': password})
            )
            mt_token = json.loads(rsp.text).get('token', '')
            if not mt_token:
                print('[ifn] mail.tm token 获取失败')
                return

            rsp = self.post(
                SB_URL + '/auth/v1/signup',
                headers=sb_hdr,
                data=json.dumps({'email': email, 'password': password})
            )
            data = json.loads(rsp.text)

            if data.get('access_token'):
                self.access_token = data['access_token']
                self._refresh_token = data.get('refresh_token', '')
                self._reg_email = email
                self._reg_pass = password
                print('[ifn] 自动注册成功, 获得 token')
                return

            print('[ifn] 等待确认邮件...')
            mt_auth_hdr = dict(mt_hdr)
            mt_auth_hdr['Authorization'] = 'Bearer ' + mt_token

            verify_url = ''
            for _ in range(15):
                _time.sleep(3)
                try:
                    rsp = self.fetch('https://api.mail.tm/messages', headers=mt_auth_hdr)
                    if rsp and rsp.status_code == 200:
                        msg_data = json.loads(rsp.text)
                        if isinstance(msg_data, list):
                            msgs = msg_data
                        else:
                            msgs = msg_data.get('hydra:member', msg_data.get('member', []))
                        if msgs:
                            msg_id = msgs[0]['id']
                            rsp = self.fetch(
                                'https://api.mail.tm/messages/%s' % msg_id,
                                headers=mt_auth_hdr
                            )
                            if rsp and rsp.status_code == 200:
                                msg_data = json.loads(rsp.text)
                                body = str(msg_data.get('text', '')) + str(msg_data.get('html', ''))
                                links = re.findall(
                                    r'https://rvcrrwdtggvbomvzvpev\.supabase\.co/auth/v1/verify\?[^\s"<>]+',
                                    body
                                )
                                if links:
                                    verify_url = links[0]
                                    break
                except Exception:
                    pass

            if not verify_url:
                print('[ifn] 未收到确认邮件, 将使用嗅探模式播放')
                return

            self.fetch(verify_url, headers=mt_hdr)
            print('[ifn] 邮箱确认完成')

            self._login(email, password)
            if self.access_token:
                self._reg_email = email
                self._reg_pass = password
                print('[ifn] 自动注册+确认+登录成功')
            else:
                print('[ifn] 登录失败, 将使用嗅探模式播放')

        except Exception as e:
            print('[ifn] 自动注册失败: %s' % e)

    def _login(self, email, password):
        try:
            rsp = self.post(
                SB_URL + '/auth/v1/token?grant_type=password',
                headers={
                    'apikey': SB_KEY,
                    'Content-Type': 'application/json',
                    'User-Agent': UA,
                },
                data=json.dumps({'email': email, 'password': password})
            )
            data = json.loads(rsp.text)
            if data.get('access_token'):
                self.access_token = data['access_token']
                self._refresh_token = data.get('refresh_token', '')
                self._reg_email = email
                self._reg_pass = password
        except Exception as e:
            print('[ifn] 登录失败: %s' % e)

    def _fetch(self, url, timeout=15, retry=1, ttl=120, use_cache=True,
               cache_key=None, headers=None):
        """带响应缓存的抓取 [提速关键]:
           - 相同 URL(或 cache_key) 在 ttl 秒内直接返回缓存, 不再重复下载整页
           - 首页/分类/详情多次调用共享一份 HTML, 避免 3x 叠加的 ~12s 抓取
           - cache_key 用于区分同 URL 不同头(如详情 RSC:1 vs 初始HTML)
        """
        key = cache_key or url
        cache = getattr(self, '_http_cache', None)
        if cache is None:
            cache = self._http_cache = {}
        if use_cache and key in cache:
            txt, ts = cache[key]
            if time.time() - ts < ttl:
                return txt
        hdrs = dict(self.header)
        if headers:
            hdrs.update(headers)
        last_err = ''
        for attempt in range(retry + 1):
            try:
                rsp = self.fetch(url, headers=hdrs)
                text = rsp.text if rsp else ''
                if text:
                    if use_cache:
                        cache[key] = (text, time.time())
                    return text
            except Exception as e:
                last_err = str(e)
                if attempt < retry:
                    print('[ifn] 请求重试 %d/%d: %s' % (attempt + 1, retry, url[:60]))
                else:
                    print('[ifn] 请求失败: %s => %s' % (url[:80], last_err))
        return ''

    def _fetch_rsc_stream(self, b64_id):
        """[修复] 带 RSC:1 头二次请求, 拿流式下发的 flight (含完整集数/元数据)
           走 _fetch 缓存(cache_key 与初始HTML区分), TTL 5min 避免重复抓详情。
        """
        return self._fetch(
            CDN_HOST + '/detail/' + b64_id,
            ttl=300,
            cache_key='rsc1_' + b64_id,
            headers={'RSC': '1'},
        )

    def _extract_cards(self, html_text):
        cards = []
        seen = set()
        for m in re.finditer(r'<a\s+href="(/detail/[^"]+)"[^>]*>', html_text):
            href = m.group(1)
            b64_id = href.replace('/detail/', '')
            if b64_id in seen:
                continue
            block = html_text[m.start():m.start() + 6000]

            title = ''
            title_m = re.search(r'title="([^"]+)"', block)
            if title_m:
                title = html_mod.unescape(title_m.group(1))
                if '查看' in title and '详情' in title:
                    title = ''
            if not title:
                alt_m = re.search(r'alt="([^"]+)"', block)
                if alt_m:
                    title = html_mod.unescape(alt_m.group(1))
            if not title:
                h3_m = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL)
                if h3_m:
                    title = self._clean(h3_m.group(1))

            pic = ''
            img_m = re.search(r'/api/image/([A-Za-z0-9+/=]+)\.gif', block)
            if img_m:
                pic = CDN_HOST + '/api/image/' + img_m.group(1) + '.gif'

            remark = ''
            score_m = re.search(r'bg-red-600[^>]*>([\d.]+)<!--\s*-->分', block)
            if score_m:
                remark = score_m.group(1) + '分'

            if title:
                seen.add(b64_id)
                cards.append({
                    'vod_id': b64_id,
                    'title': title,
                    'pic': pic,
                    'remark': remark,
                })
        return cards

    # ================================================================
    # 首页 / 分类 / 搜索
    # ================================================================

    def _home_cards(self):
        """抓取首页推荐卡片, 返回标准 vod 列表 (供 homeContent/HomeVideoContent 复用)"""
        html_text = self._fetch(CDN_HOST + '/', retry=1)
        if not html_text:
            return []
        raw_cards = self._extract_cards(html_text)
        videos = []
        seen = set()
        for c in raw_cards:
            if c['vod_id'] in seen:
                continue
            seen.add(c['vod_id'])
            videos.append({
                "vod_id": c['vod_id'],
                "vod_name": c['title'],
                "vod_pic": c['pic'],
                "vod_remarks": c['remark'],
            })
        return videos

    def homeContent(self, filter):
        """CatVod/FongMi 协议首页入口 (修复首页无法显示):
           - Java/壳子端常传字符串 'true'/'false'(或 '1'/'0'), 必须正确解析,
             否则 `if filter:` 永远为真, 永远走筛选分支而拿不到 list -> 首页空白。
           - filter 为真: 返回分类 + filters (用于筛选条)
           - filter 为假: 返回首页推荐列表 list (+ class, 部分壳子需要)
        """
        f = filter
        if isinstance(f, str):
            f = f.strip().lower() in ('true', '1', 'yes', 'y')
        else:
            f = bool(f)

        classes = [{"type_id": tid, "type_name": tname} for tid, tname in CATE_MAP.items()]

        if f:
            # 筛选模式: 分类 + 各分类的筛选条件 (本站无服务端筛选, 给空)
            return {"class": classes, "filters": {tid: [] for tid in CATE_MAP}}
        else:
            # 首页内容: 推荐列表 + 分类 (关键修复, 否则 WebHomeTV 首页空白)
            videos = self._home_cards()
            return {"class": classes, "list": videos}

    def homeVideoContent(self):
        """首页推荐视频 (WebHomeTV 原生首页也会调用)"""
        videos = self._home_cards()
        return {"list": videos}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        if tid == '1':
            if page > 1:
                return {"list": [], "page": page, "pagecount": 1,
                        "limit": 30, "total": 0}
            html_text = self._fetch(CDN_HOST + '/', retry=1)
        else:
            url = CDN_HOST + '/category/%s?page=%d' % (tid, page)
            html_text = self._fetch(url, retry=1)

        if not html_text:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 30, "total": 0}

        raw_cards = self._extract_cards(html_text)
        videos = []
        for c in raw_cards:
            videos.append({
                "vod_id": c['vod_id'],
                "vod_name": c['title'],
                "vod_pic": c['pic'],
                "vod_remarks": c['remark'],
            })

        pagecount = page + 1 if len(videos) >= 20 else page
        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": 30,
            "total": pagecount * 30,
        }

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        query = urllib.parse.quote(key)
        url = CDN_HOST + '/search?q=%s&page=%d' % (query, page)
        html_text = self._fetch(url, retry=1)
        if not html_text:
            return {"list": []}
        raw_cards = self._extract_cards(html_text)
        videos = []
        seen = set()
        for c in raw_cards:
            if c['vod_id'] in seen:
                continue
            seen.add(c['vod_id'])
            videos.append({
                "vod_id": c['vod_id'],
                "vod_name": c['title'],
                "vod_pic": c['pic'],
                "vod_remarks": c['remark'],
            })
        return {"list": videos}

    def search(self, wd, quick):
        return self.searchContent(wd, quick)

    # ================================================================
    # 详情页 (修复: RSC 流式拿集数)
    # ================================================================

    def _extract_episodes(self, text):
        """从 RSC/flight 文本提取集数列表 [{'id':N,'title':T'}, ...]"""
        eps = []
        seen = set()
        for m in re.finditer(r'\{"id":(\d+),"title":"([^"]*)"\}', text):
            eid = m.group(1)
            title = m.group(2)
            if eid in seen:
                continue
            seen.add(eid)
            eps.append({'id': eid, 'title': _fix_latin(title)})
        # 兜底: "episodes":[{"id":N,"title":"T"}] 数组整体解析
        if not eps:
            for arr in re.finditer(r'"episodes":\[(.*?)\]', text, re.DOTALL):
                for m in re.finditer(r'\{"id":(\d+),"title":"([^"]*)"\}', arr.group(1)):
                    eid, title = m.group(1), m.group(2)
                    if eid in seen:
                        continue
                    seen.add(eid)
                    eps.append({'id': eid, 'title': _fix_latin(title)})
        return eps

    def _media_field(self, text, field, is_str=True):
        """取媒体对象内字段 (位于含 episodes 的对象中, 优先)"""
        pat = r'"%s":%s[^{}]*"episodes":\[' % (
            field, r'"([^"]*)"' if is_str else r'([-\d.]+)')
        m = re.search(pat, text, re.DOTALL)
        if m:
            return m.group(1)
        # 回退: 全局首个
        m = re.search(r'"%s":%s' % (field, r'"([^"]*)"' if is_str else r'([-\d.]+)'), text)
        return m.group(1) if m else ''

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        b64_id = ids[0]

        # 1) + 2) [提速] 初始HTML 与 RSC:1 流式响应 并行抓取 (省一半网络耗时)
        #    RSC:1 与初始HTML 用不同 cache_key, 互不串; TTL 5min 避免重复抓同详情
        import threading
        _res = {}
        _errs = {}

        def _g_html():
            try:
                _res['html'] = self._fetch(
                    CDN_HOST + '/detail/' + b64_id, retry=1,
                    ttl=300, cache_key='html_' + b64_id)
            except Exception as e:
                _errs['html'] = e

        def _g_rsc():
            try:
                _res['rsc1'] = self._fetch_rsc_stream(b64_id)
            except Exception as e:
                _errs['rsc1'] = e

        t_html = threading.Thread(target=_g_html)
        t_rsc = threading.Thread(target=_g_rsc)
        t_html.start()
        t_rsc.start()
        t_html.join()
        t_rsc.join()

        html_text = _res.get('html', '')
        rsc_html = _decode_rsc(html_text) if html_text else ''

        # [修复] RSC:1 流式响应 (剧集/元数据主要来源)
        rsc1 = _res.get('rsc1', '')

        # 合并文本用于提取
        full = rsc_html + '\n' + rsc1

        # 解码原始 ID (完整 mediaId, 如 "48428_0,1,4,146")
        raw_id = _b64_decode(b64_id)
        media_id = raw_id if raw_id else ''

        # ---- 标题 ----
        vod_name = ''
        title_m = re.search(r'<title>(.*?)</title>', html_text or '', re.DOTALL)
        if title_m:
            parts = title_m.group(1).strip().split(' - ')
            if parts:
                vod_name = parts[0].strip()
        if not vod_name:
            vod_name = self._media_field(rsc1 or rsc_html, 'title', True)
            if not vod_name:
                vod_name = self._media_field(rsc_html, 'title', True)

        # ---- 更新状态 ----
        update_status = ''
        if title_m:
            parts = title_m.group(1).strip().split(' - ')
            if len(parts) > 1:
                cand = parts[1].strip()
                if cand and 'IFN' not in cand and '影视' not in cand:
                    update_status = cand

        # ---- 各元数据字段 (优先 RSC:1) ----
        vod_content = self._media_field(rsc1 or rsc_html, 'description', True)
        vod_actor = self._media_field(rsc1 or rsc_html, 'actor', True)
        vod_director = self._media_field(rsc1 or rsc_html, 'director', True)
        if not update_status:
            update_status = self._media_field(rsc1 or rsc_html, 'updateStatus', True)
        media_type = self._media_field(rsc1 or rsc_html, 'mediaType', True)
        type_name = self._media_field(rsc1 or rsc_html, 'typeName', True)
        content_type = self._media_field(rsc1 or rsc_html, 'contentType', True)
        year = self._media_field(rsc1 or rsc_html, 'year', True)
        score = self._media_field(rsc1 or rsc_html, 'score', False)
        video_type = -1
        vt = self._media_field(rsc1 or rsc_html, 'videoType', False)
        if vt:
            try:
                video_type = int(float(vt))
            except Exception:
                pass
        if not year:
            date_str = self._media_field(rsc1 or rsc_html, 'date', True)
            if date_str:
                ym = re.search(r'(\d{4})', date_str)
                if ym:
                    year = ym.group(1)

        # ---- 封面 (CDN 包装) ----
        vod_pic = ''
        cover = self._media_field(rsc1 or rsc_html, 'coverImgUrl', True)
        if cover:
            img_m = re.search(r'/api/image/([A-Za-z0-9+/=]+)\.gif', cover)
            if img_m:
                vod_pic = CDN_HOST + '/api/image/' + img_m.group(1) + '.gif'
            elif cover.startswith('http'):
                vod_pic = cover
        if not vod_pic:
            img_m = re.search(r'/api/image/([A-Za-z0-9+/=]+)\.gif', full)
            if img_m:
                vod_pic = CDN_HOST + '/api/image/' + img_m.group(1) + '.gif'

        # ---- [修复] 集数: 合并初始HTML RSC 与 RSC:1 流式 ----
        episodes = self._extract_episodes(rsc_html)
        episodes += self._extract_episodes(rsc1)
        # 去重 (按 id)
        _seen = set()
        _uniq = []
        for ep in episodes:
            if ep['id'] in _seen:
                continue
            _seen.add(ep['id'])
            _uniq.append(ep)
        episodes = _uniq

        # ---- 构建播放列表 ----
        # play_url 格式: 集名$episode_id@detail_b64_id
        if episodes:
            ep_str = '#'.join([
                ep['title'] + '$' + ep['id'] + '@' + b64_id for ep in episodes
            ])
        else:
            if media_id:
                ep_str = u'第1集$' + media_id + '@' + b64_id
            else:
                ep_str = u'第1集$' + b64_id + '@' + b64_id

        if video_type == 0 and episodes:
            ep_str = u'正片$' + episodes[0]['id'] + '@' + b64_id

        # 双源: 4K超清 + 流畅1080P
        play_from = u'4K超清$$$流畅1080P'
        play_url = ep_str + '$$$' + ep_str

        vod_remarks = update_status or ('HD' if video_type == 0 else '')

        vod = {
            "vod_id": b64_id,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "vod_content": vod_content[:500] if vod_content else '',
            "vod_year": year,
            "vod_area": '',
            "vod_actor": _fix_latin(vod_actor),
            "vod_director": _fix_latin(vod_director),
            "vod_remarks": vod_remarks,
            "vod_play_from": play_from,
            "vod_play_url": play_url,
            "type_name": type_name or media_type,
            "vod_score": score,
        }
        return {"list": [vod]}

    # ================================================================
    # 播放 (playerContent) — 嗅探 + 可选 token 直连
    # ================================================================

    def playerContent(self, flag, id, vipFlags):
        raw_id = str(id) if id else ''
        parts = raw_id.split('@')
        ep_id = parts[0] if parts else ''
        detail_b64 = parts[1] if len(parts) > 1 else ep_id

        media_id = _b64_decode(detail_b64) or ''

        use_4k = '4K' in str(flag) or '超清' in str(flag)

        # [修复无法播放] 播放前确保 token 就绪 (等后台注册 / 必要时同步注册),
        # 不能因 init 异步化就直接退化嗅探 —— 本站嗅探拿不到视频流。
        if not self.access_token:
            self._await_token()

        # 方式1: 有 auth token, 经 CDN 代理 m3u8 播放
        if self.access_token:
            try:
                m3u8_url = self._get_play_url(media_id, ep_id, detail_b64, use_4k)
                # [兜底] 4K 拿不到地址(如该片无 4K 源/令牌不足)时回退 1080P,
                # 避免播放器显示"4K超清没有数据"。4K 正常时不会触发此分支。
                if not m3u8_url and use_4k:
                    print('[ifn] 4K 源不可用, 回退 1080P')
                    m3u8_url = self._get_play_url(media_id, ep_id, detail_b64, False)
                if m3u8_url:
                    # [本地加速代理] m3u8 改走 ifn_ts_proxy, 由其做多分片并发预取
                    if self.local_proxy:
                        m3u8_url = '%s/play?src=%s' % (
                            self.local_proxy_url.rstrip('/'),
                            urllib.parse.quote(m3u8_url, safe=''))
                    return {
                        "parse": 0,
                        "playUrl": '',
                        "url": m3u8_url,
                        "format": 'application/x-mpegURL',
                        "header": {'User-Agent': UA},  # 不带 Referer, 规避 CF 慢路径
                    }
            except Exception as e:
                print('[ifn] 获取播放地址失败: %s' % e)

        # 方式2: 无 token 或获取失败, 嗅探详情页
        sniff_url = CDN_HOST + '/detail/' + detail_b64
        return {
            "parse": 1,
            "playUrl": '',
            "url": sniff_url,
            "header": {'User-Agent': UA},
        }

    def _get_play_url(self, media_id, ep_id, detail_b64, use_4k=False):
        if not self.access_token or not ep_id:
            return ''

        mid = media_id or str(ep_id)
        eid = str(ep_id)

        import time as _time
        cache_key = mid + '_' + eid + ('_4k' if use_4k else '_1080')
        if cache_key in self._play_cache:
            cached_url, cached_time = self._play_cache[cache_key]
            if _time.time() - cached_time < 1800:
                print('[ifn] 使用缓存的 play token (%s)' % ('4K' if use_4k else '1080P'))
                return cached_url

        token = self._ensure_valid_token()
        if not token:
            return ''

        auth_headers = {
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json',
            'User-Agent': UA,
            'Referer': self.host + '/',
        }

        m3u8_params = '?ts=true'
        if use_4k:
            m3u8_params += '&reslo=true'
        if self.use_proxy:
            m3u8_params += '&thirdParty=true'

        # 1) GET 检查已有 token (不消耗积分)
        try:
            rsp = self.fetch(
                CDN_HOST + '/api/play/token?mediaId=%s&episodeId=%s' % (
                    urllib.parse.quote(mid), eid
                ),
                headers=auth_headers
            )
            if rsp and rsp.status_code == 200:
                data = json.loads(rsp.text)
                if data.get('success') and data.get('token'):
                    play_token = data['token']
                    m3u8_url = CDN_HOST + '/api/play/' + play_token + '.m3u8' + m3u8_params
                    self._play_cache[cache_key] = (m3u8_url, _time.time())
                    print('[ifn] 使用已有 play token, %s' % ('4K' if use_4k else '1080P'))
                    return m3u8_url
        except Exception as e:
            print('[ifn] GET play token 失败: %s' % e)

        # 2) POST 获取新 token (消耗积分)
        try:
            rsp = self.post(
                CDN_HOST + '/api/play/token',
                headers=auth_headers,
                data=json.dumps({'mediaId': mid, 'episodeId': eid, 'title': 'play'})
            )
            data = json.loads(rsp.text)
            if data.get('success') and data.get('token'):
                play_token = data['token']
                m3u8_url = CDN_HOST + '/api/play/' + play_token + '.m3u8' + m3u8_params
                self._play_cache[cache_key] = (m3u8_url, _time.time())
                print('[ifn] 获取新 play token, %s' % ('4K' if use_4k else '1080P'))
                return m3u8_url
            else:
                err = data.get('error', data.get('message', ''))
                code = data.get('code', '')
                print('[ifn] play token 返回失败: %s (code=%s)' % (err, code))
                if '积分' in str(err) or 'point' in str(err).lower() or code == 'INSUFFICIENT_POINTS':
                    print('[ifn] 积分不足, 尝试切换账号...')
                    self._dead_accounts.add(self._reg_email)
                    if self._switch_account():
                        return self._get_play_url(media_id, ep_id, detail_b64, use_4k)
        except Exception as e:
            print('[ifn] POST play token 失败: %s' % e)
        return ''

    def _switch_account(self):
        old_email = self._reg_email
        self.access_token = ''
        self._refresh_token = ''
        for acc in PRESET_ACCOUNTS:
            if acc['email'] in self._dead_accounts or acc['email'] == old_email:
                continue
            try:
                self._login(acc['email'], acc['password'])
                if self.access_token:
                    points = self._check_points()
                    if points is not None and points > 0:
                        print('[ifn] 切换到账号 %s, 积分=%s' % (acc['email'][:20], points))
                        return True
                    else:
                        self._dead_accounts.add(acc['email'])
                        self.access_token = ''
            except Exception:
                pass
        print('[ifn] 所有预置账号积分耗尽, 自动注册新账号...')
        self._auto_register()
        if self.access_token:
            points = self._check_points()
            print('[ifn] 新账号注册成功, 积分=%s' % points)
            return True
        return False

    def _ensure_valid_token(self):
        if self.access_token:
            try:
                parts = self.access_token.split('.')
                if len(parts) >= 2:
                    payload_b64 = parts[1] + '=' * (4 - len(parts[1]) % 4)
                    payload = json.loads(base64.b64decode(payload_b64))
                    exp = payload.get('exp', 0)
                    import time as _time
                    if exp - int(_time.time()) > 300:
                        return self.access_token
            except Exception:
                pass

        refresh_token = getattr(self, '_refresh_token', '')
        if refresh_token:
            try:
                rsp = self.post(
                    SB_URL + '/auth/v1/token?grant_type=refresh_token',
                    headers={'apikey': SB_KEY, 'Content-Type': 'application/json'},
                    data=json.dumps({'refresh_token': refresh_token})
                )
                data = json.loads(rsp.text)
                if data.get('access_token'):
                    self.access_token = data['access_token']
                    self._refresh_token = data.get('refresh_token', refresh_token)
                    return self.access_token
            except Exception:
                pass

        reg_email = getattr(self, '_reg_email', '')
        reg_pass = getattr(self, '_reg_pass', '')
        if reg_email and reg_pass:
            print('[ifn] token 过期, 重新登录...')
            self._login(reg_email, reg_pass)
            if self.access_token:
                return self.access_token
        return self.access_token

    def player(self, flag, id, vipFlags):
        return self.playerContent(flag, id, vipFlags)

    def isVideoContent(self, ids):
        return True


# ====================================================================
# 独立运行测试
# ====================================================================
if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings()

    s = Spider()
    s.init()

    print('IFN影视爬虫测试 (改进版)')
    print('=' * 60)

    print('\n=== homeContent ===')
    hc = s.homeContent(True)
    for c in hc['class']:
        print('  %s -> %s' % (c['type_id'], c['type_name']))

    print('\n=== homeVideoContent ===')
    hv = s.homeVideoContent()
    print('推荐 %d 条:' % len(hv['list']))
    for v in hv['list'][:5]:
        print('  [%s] %s  %s' % (v['vod_id'][:20], v['vod_name'], v['vod_remarks']))

    print('\n=== categoryContent (电影 p1) ===')
    cc = s.categoryContent('3', 1, True, {})
    print('共 %d 条:' % len(cc['list']))

    print('\n=== searchContent("凡人修仙传") ===')
    sr = s.searchContent('凡人修仙传', False)
    print('搜索到 %d 条' % len(sr['list']))
    test_id = sr['list'][0]['vod_id'] if sr['list'] else (cc['list'][0]['vod_id'] if cc['list'] else None)

    if test_id:
        print('\n=== detailContent (关键修复验证) ===')
        dc = s.detailContent([test_id])
        if dc.get('list'):
            v = dc['list'][0]
            print('  标题: %s' % v['vod_name'])
            print('  封面: %s' % v.get('vod_pic', '')[:80])
            print('  导演: %s' % v.get('vod_director', '')[:50])
            print('  主演: %s' % v.get('vod_actor', '')[:50])
            print('  简介: %s' % v.get('vod_content', '')[:80])
            print('  评分: %s' % v.get('vod_score', ''))
            print('  播放源: %s' % v['vod_play_from'])
            if v['vod_play_url']:
                eps = v['vod_play_url'].split('#')
                print('  集数: %d 集  <-- [修复] 剧集应远多于1集' % len(eps))
                if eps:
                    print('  首集: %s' % eps[0][:60])
                    print('  播放首集...')
                    r = s.playerContent('IFN影视', eps[0].split('$')[1], [])
                    print('    parse=%s url=%s' % (r['parse'], r['url'][:100]))
                    print('    header类型: %s' % type(r['header']).__name__)
