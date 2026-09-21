# -*- coding: utf-8 -*-
"""
TVBox Python Spider - 荐片影视 (jpyy.site)
适配 FongMi TV / OK影视 / webhome 框架
MacCMS 站, API 关闭, 走 HTML 解析

借鉴国色天香 + 果香园模板优化:
- requests.Session 连接复用: 减少 TCP/TLS 握手开销
- UA 轮换重试 + SSL 降级: 3 个 UA 自动切换, SSL 失败时 verify=False 兜底
- 完整浏览器请求头: sec-ch-ua / sec-fetch-* / Referer
- 播放 URL 缓存: 重复播放同一视频秒出(1 小时 TTL)
- 首页 HTML 缓存: homeContent + homeVideoContent 共享(5 分钟 TTL)
- 域名配置化: host 为类变量, init 支持 extend 覆盖
- CF 挑战页检测: 避免把挑战页当正常内容返回
- 取数重试(6 轮 + 退避): 站点限流/断连严重, 单次必挂, 必须重试才有稳定出卡率
- 软失败校验: 拿到响应却无 /movie/ 内容视为被限流, 触发重试而非返回空白
- 超时 10s: 减少用户等待转圈时间

站点结构:
- 分类页: /list/{slug}.html, 翻页 /list/{slug}-{page}.html
- 详情页: /movie/{id}.html (标题/封面/年份/地区/类型/简介/播放源/剧集)
- 播放页: /play/{vid}-{src}-{ep}.html (player_aaaa + encrypt:2)
  解码链路: base64decode(url) -> unquote() -> m3u8 直链
- 搜索页: /search.html?wd={keyword} (服务端渲染, 可用)
"""
import sys
sys.path.append("..")

import re
import json
import time
import base64

try:
    from urllib.parse import quote as _quote, unquote as _unquote
except:
    try:
        from urllib import quote as _quote, unquote as _unquote
    except:
        _quote = lambda x: x
        _unquote = lambda x: x

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            import requests
            kw.pop('timeout', None)
            r = requests.get(url, headers=headers or {}, timeout=15, **kw)
            return r

        def post(self, url, data=None, headers=None, **kw):
            import requests
            r = requests.post(url, data=data, headers=headers or {}, timeout=15, **kw)
            return r


# UA 轮换池(请求失败时自动切换)
_UA_POOL = [
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
]

# 缓存 TTL(秒)
_HOME_CACHE_TTL = 300    # 首页缓存 5 分钟
_PLAY_CACHE_TTL = 3600  # 播放 URL 缓存 1 小时
_REQUEST_TIMEOUT = 10   # 请求超时(秒)

# 取数重试: 站点近期限流/断连严重(约半数请求被 TLS/连接重置),
# 单次快速轮询必挂, 必须带退避重试才有稳定出卡率
_FETCH_MAX_RETRIES = 6
# 每次重试之间的退避(秒), 末尾用最后一项, 总退避约 11s
_FETCH_BACKOFF = [0, 0.6, 1.2, 2.0, 3.0, 4.0]


class Spider(Spider):
    host = "https://m.jpyy.site"

    header = {
        'User-Agent': _UA_POOL[0],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': 'https://m.jpyy.site/',
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'Upgrade-Insecure-Requests': '1',
    }

    # 分类: (slug, 分类名) — slug 用于 URL 路径
    categories = [
        ("dianying", "电影"),
        ("dianshiju", "电视剧"),
        ("zongyi", "综艺"),
        ("dongman", "动漫"),
        ("duanju", "短剧"),
    ]

    def __init__(self):
        self._init_state()

    def _init_state(self):
        """统一初始化, __init__ 和 init 都调用, 防止框架不调 __init__"""
        if not hasattr(self, '_session') or self._session is None:
            self._session = None
        if not hasattr(self, '_home_html'):
            self._home_html = ''
        if not hasattr(self, '_home_html_time'):
            self._home_html_time = 0
        if not hasattr(self, '_play_cache'):
            self._play_cache = {}
        if not hasattr(self, '_header_inited'):
            self.header = dict(Spider.header)
            self._header_inited = True

    # ============================================================
    #  基础方法 (TVBox 框架必需)
    # ============================================================

    def getName(self):
        return '荐片影视'

    def init(self, extend=""):
        self._init_state()
        if isinstance(extend, list):
            self.extend = ''
        else:
            self.extend = extend or ''
        if self.extend and self.extend.startswith('http'):
            m = re.match(r'(https?://[^/]+)', self.extend)
            if m:
                self.host = m.group(1).rstrip('/')
                Spider.host = self.host
                self.header['Referer'] = self.host + '/'
        if _HAS_REQUESTS and not self._session:
            self._session = _requests.Session()
            self._session.headers.update({
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Upgrade-Insecure-Requests': '1',
            })
        return ''

    def isVideoFormat(self, url):
        if not url or not isinstance(url, str):
            return False
        return any(x in url for x in ['.m3u8', '.mp4', '.flv', '.ts', '.mkv'])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
        self._play_cache.clear()

    # ============================================================
    #  内部请求 (UA 轮换 + Session 连接复用 + SSL 降级)
    # ============================================================

    def _get_session(self):
        if not self._session and _HAS_REQUESTS:
            self._session = _requests.Session()
            self._session.headers.update({
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Upgrade-Insecure-Requests': '1',
            })
        return self._session

    @staticmethod
    def _is_cf_challenge(text):
        if not text or len(text) < 200:
            return True
        markers = ['Just a moment', 'cf-challenge', 'challenge-platform',
                   'cf-browser-verification', 'cf-mitigated',
                   'Attention Required', 'enable JavaScript']
        low = text[:2000].lower()
        for m in markers:
            if m.lower() in low:
                return True
        return False

    def _do_fetch(self, url, headers):
        """
        单次取数: 优先框架 fetch(兼容 TVBox), 失败退化为 requests.Session
        (连接复用 + SSL 降级 verify=False)。返回非空文本或 ''。
        """
        # 1) 框架 fetch(真实 TVBox 环境)
        try:
            r = self.fetch(url, headers=headers, timeout=_REQUEST_TIMEOUT)
            t = r.text if hasattr(r, 'text') else ''
            if t:
                return t
        except Exception:
            pass

        # 2) requests.Session: 先正常 SSL, 失败再 verify=False 兜底
        session = self._get_session()
        if session:
            try:
                r = session.get(url, headers=headers, timeout=_REQUEST_TIMEOUT,
                                allow_redirects=True)
                if r.status_code == 200 and r.text:
                    return r.text
            except Exception:
                pass
            try:
                r = session.get(url, headers=headers, timeout=_REQUEST_TIMEOUT,
                                allow_redirects=True, verify=False)
                if r.status_code == 200 and r.text:
                    return r.text
            except Exception:
                pass
        return ''

    def _fetch_html(self, path, use_cache=False, lookfor=None):
        """
        统一 HTML 获取方法(带退避重试 + 软失败校验):
        1. 优先使用框架 fetch(兼容 TVBox 环境)
        2. 失败/被限流时用 requests.Session 重试(连接复用 + UA 轮换 + SSL 降级)
        3. 站点限流严重: 单轮快速轮询必挂, 改为多轮退避重试, 提升出卡率
        4. lookfor: 期望在有效内容中出现的关键串(如 '/movie/');
           若拿到响应却不含该串(被限流返回空壳/挑战页), 视为软失败并重试
        5. 支持首页缓存(homeContent + homeVideoContent 共享)
        """
        url = path if path.startswith('http') else self.host + path

        if use_cache:
            now = time.time()
            if self._home_html and (now - self._home_html_time) < _HOME_CACHE_TTL:
                return self._home_html

        last_err = None
        for attempt in range(_FETCH_MAX_RETRIES):
            ua = _UA_POOL[attempt % len(_UA_POOL)]
            headers = dict(self.header)
            headers['User-Agent'] = ua
            headers['Referer'] = self.host + '/'

            try:
                text = self._do_fetch(url, headers)
            except Exception as e:
                last_err = e
                text = ''

            if text and not self._is_cf_challenge(text):
                # 软失败校验: 响应回来了但没有预期内容(多半是被限流/空壳)
                if lookfor is None or lookfor in text:
                    if use_cache:
                        self._home_html = text
                        self._home_html_time = time.time()
                    return text

            # 软失败或被断连: 退避后重试, 避免狂打触发更狠的限流
            if attempt < _FETCH_MAX_RETRIES - 1:
                time.sleep(_FETCH_BACKOFF[min(attempt, len(_FETCH_BACKOFF) - 1)])

        return ''

    @staticmethod
    def _fix_url(url, host=None):
        if not url:
            return ''
        url = url.strip()
        base = (host or Spider.host).rstrip('/')
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return base + url
        return url

    # ============================================================
    #  卡片解析 (layui-col + item-cover + item-title 结构)
    # ============================================================

    # 占位图/加载图: 命中则视为无效封面, 继续找真实图
    _PLACEHOLDER_RE = re.compile(
        r'(load|loading|blank|placeholder|default|/static/|/images/|/img/loading|lazy)',
        re.I
    )

    # 备注(评分/状态)提取优先级
    _REMARK_PATTERNS = [
        r'(\d+(?:\.\d+)?\s*第\d+[集话]?\s*已完结)',
        r'(\d+(?:\.\d+)?\s*第\d+[集话]?)',
        r'(\d+(?:\.\d+)?\s*(?:正片|抢先版|预告|完结|HD|TC|TS|更新至第\d+[集话]?|更新中|连载|更新))',
        r'(\d+(?:\.\d+)?\s*(?:待更|全集))',
    ]

    @classmethod
    def _extract_img_url(cls, inner, after):
        """
        从链接内部(inner)或链接之后(after)提取封面 URL。
        优先链接内部(新版 <a><img src=...>), 其次链接之后(旧版 <a></a><img lay-src>)。
        命中占位图则跳过, 取第一张真实图。
        """
        for scope in (inner, after):
            if not scope:
                continue
            candidates = []
            for attr in ('lay-src', 'data-src', 'data-original', 'data-lazy-src', 'src'):
                for m in re.finditer(
                    r'<img\b[^>]*\b%s=["\']([^"\']+)["\']' % attr, scope, re.I
                ):
                    u = m.group(1).strip()
                    if u:
                        candidates.append(u)
            real = [u for u in candidates if not cls._PLACEHOLDER_RE.search(u)]
            if real:
                return real[0]
            if candidates:
                return candidates[0]
        return ''

    @classmethod
    def _extract_title(cls, inner, after):
        """提取标题: 优先本链接 img 的 alt, 其次 <b>/<strong> 文本, 再次链接文本。只在链接范围内取, 避免串到相邻卡片。"""
        # 1) 链接内部 img 的 alt(新版)
        am = re.search(r'<img\b[^>]*\balt=["\']([^"\']*)["\']', inner or '', re.I)
        if am and am.group(1).strip():
            return am.group(1).strip()
        # 2) 链接之后 img 的 alt(旧版 img 在 <a> 之后)
        am2 = re.search(r'<img\b[^>]*\balt=["\']([^"\']*)["\']', after or '', re.I)
        if am2 and am2.group(1).strip():
            return am2.group(1).strip()
        # 3) 链接内部 <b>/<strong> 文本(推荐位常见结构)
        bm = re.search(r'<(?:b|strong|h\d)[^>]*>([^<]{1,60})</', inner or '', re.I)
        if bm and bm.group(1).strip():
            return bm.group(1).strip()
        # 4) 链接自身文本(去标签/噪点)
        txt = re.sub(r'<[^>]+>', ' ', inner or '')
        txt = re.sub(r'\s+', ' ', txt).strip()
        for noise in ('立即观看', '立即播放', '在线观看', '播放', '详情', '查看更多', '更多'):
            txt = txt.replace(noise, ' ')
        txt = re.sub(r'\s+', ' ', txt).strip()
        if txt:
            # 取首段(到 / 或换行前), 避免把简介整段当标题
            first = re.split(r'[/]', txt)[0].strip()
            return first if first else txt[:40]
        return ''

    @classmethod
    def _extract_remark(cls, inner, after):
        """提取评分/状态(如 4.0正片 / 3.0第12集 / 7.0抢先版 / 5.0第32集已完结)。"""
        for scope in (inner, after):
            for p in cls._REMARK_PATTERNS:
                m = re.search(p, scope or '')
                if m:
                    return m.group(1).strip()
        # 新版 card-grid: 评分(card-badge) 与 集数/状态(card-score) 分属两个 span,
        # 不再相邻, 需分别抓取后拼接(如 3.0 + 第12集 -> 3.0第12集)
        badge = score = ''
        for scope in (inner, after):
            bm = re.search(r'class="card-badge"[^>]*>([^<]+)<', scope or '', re.I)
            if bm:
                badge = bm.group(1).strip()
            sm = re.search(r'class="card-score"[^>]*>([^<]+)<', scope or '', re.I)
            if sm:
                score = sm.group(1).strip()
        if badge and score:
            return '%s%s' % (badge, score)
        if score:
            return score
        if badge:
            return badge
        return ''

    @staticmethod
    def _parse_cards(html):
        """
        结构无关的卡片解析 —— 站点已多次改版, 不再依赖固定的 class 名/懒加载属性。

        兼容两种历史结构:
          旧版: <a href="/movie/{id}.html"></a> 与 <img lay-src="..."> 为兄弟节点,
                标题另在 <div class="item-title"><a href="/movie/{id}.html">标题</a></div>
          新版: <a href="/movie/{id}.html"><img src="https://img.jisuimage.com/cover/...">标题</a>

        做法: 扫描所有 /movie/{id}.html 链接, 同一 vid 的多个 <a> 合并为一个卡片
              (旧版空 <a> 与标题 <a> 归并), 再在链接内部 + 链接之后小窗内提取封面/标题/备注。
        """
        if not html:
            return []
        link_re = re.compile(
            r'<a\b[^>]*href=["\'](?:https?://[^"\'/]*?)?/movie/(\d+)\.html["\'][^>]*>'
            r'(.*?)</a>',
            re.I | re.S
        )

        # 按 vid 分组(同一个 vid 可能对应多个 <a>: 旧版空链接 + 标题链接)
        grouped = {}
        order = []
        for m in link_re.finditer(html):
            vid = m.group(1)
            inner = m.group(2)
            if vid not in grouped:
                grouped[vid] = {
                    'inner': inner,
                    'start': m.start(),
                    'title_inner': inner.strip(),   # 优先用含文本的链接作标题来源
                }
                order.append(vid)
            else:
                # 第二个 <a>(如旧版 item-title 里的标题链接)
                if inner.strip() and not grouped[vid]['title_inner'].strip():
                    grouped[vid]['title_inner'] = inner
                grouped[vid]['inner'] += inner   # 合并, 扩大图片/alt 搜索范围

        vod_list = []
        seen = set()
        for vid in order:
            if vid in seen:
                continue
            seen.add(vid)
            c = grouped[vid]
            inner = c['inner']
            title_inner = c['title_inner'] or inner
            # 链接之后取一小段(after): 覆盖旧版兄弟 img / tag, 不向前取以避免串到上一张卡
            after = html[c['start']:c['start'] + 400]

            pic = Spider._extract_img_url(inner, after)
            pic = Spider._fix_url(pic) if pic else ''
            title = Spider._extract_title(title_inner, after)
            remark = Spider._extract_remark(inner, after)

            vod_list.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remark,
            })

        # 极端兜底: 上述正则未命中(例如 a 标签被严重拆分), 退化为纯链接扫描
        if not vod_list:
            for mid in re.findall(r'href=["\'](?:https?://[^"\'/]*?)?/movie/(\d+)\.html["\']', html, re.I):
                if mid in seen:
                    continue
                seen.add(mid)
                pos = html.find('/movie/%s.html' % mid)
                if pos < 0:
                    continue
                after = html[pos:pos + 400]
                pic = Spider._fix_url(Spider._extract_img_url('', after))
                vod_list.append({
                    'vod_id': mid,
                    'vod_name': Spider._extract_title('', after),
                    'vod_pic': pic,
                    'vod_remarks': Spider._extract_remark('', after),
                })

        return vod_list

    # ============================================================
    #  首页 (HTML 缓存, 消除重复请求)
    # ============================================================

    def homeContent(self, filter):
        try:
            result = {
                'class': [{'type_id': slug, 'type_name': name}
                          for slug, name in self.categories],
                'filters': {},
            }
            html = self._fetch_html('/', use_cache=True, lookfor='/movie/')
            result['list'] = self._parse_cards(html)
            return result
        except Exception:
            return {
                'class': [{'type_id': slug, 'type_name': name}
                          for slug, name in self.categories],
                'filters': {},
                'list': [],
            }

    def homeVideoContent(self):
        try:
            html = self._fetch_html('/', use_cache=True, lookfor='/movie/')
            return {'list': self._parse_cards(html)}
        except Exception:
            return {'list': []}

    # ============================================================
    #  分类 (服务端渲染, 翻页可用)
    # ============================================================

    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            pg = int(pg) if pg else 1
            # 第一页: /list/{slug}.html
            # 第N页: /list/{slug}-{N}.html
            if pg <= 1:
                path = '/list/%s.html' % tid
            else:
                path = '/list/%s-%d.html' % (tid, pg)

            html = self._fetch_html(path, lookfor='/movie/')
            videos = self._parse_cards(html)

            # 估算总页数: 从页面中找最大页码
            pagecount = 1
            if html:
                page_nums = re.findall(r'/list/%s-(\d+)\.html' % re.escape(tid), html)
                if page_nums:
                    pagecount = max(int(p) for p in page_nums)
                # 如果当前页有数据但没找到翻页信息, 至少保留当前页
                if not pagecount and videos:
                    pagecount = pg

            return {
                'page': pg,
                'pagecount': pagecount,
                'limit': len(videos),
                'total': pagecount * 20,
                'list': videos,
            }
        except Exception:
            return {'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0, 'list': []}

    # ============================================================
    #  详情页 (标题/封面/年份/地区/类型/简介/播放源/剧集)
    # ============================================================

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, list) else str(ids)
            html = self._fetch_html('/movie/%s.html' % vid, lookfor='/movie/')
            if not html:
                return {'list': []}

            # 标题: <title>《{title}》... - 荐片影视</title>
            title = ''
            m = re.search(r'<title>([^<]+)</title>', html)
            if m:
                raw = m.group(1)
                # 去掉 《》和后续后缀
                tm = re.search(r'[《]([^》]+)[》]', raw)
                if tm:
                    title = tm.group(1)
                else:
                    for sep in ['全集在线观看', '- 荐片', '在线观看', '- ']:
                        idx = raw.find(sep)
                        if idx > 0:
                            raw = raw[:idx]
                            break
                    title = raw.strip()
            if not title:
                m = re.search(r'<meta\s+name="keywords"\s+content="([^,"]+)', html)
                if m:
                    title = m.group(1).strip()

            # 封面: 旧版 lay-src, 新版 src(直接 jisuimage.com/cover 绝对地址)
            pic = ''
            # 1) 优先 lay-src / data-src 中含 cover/jisuimage 的
            for attr in ('lay-src', 'data-src', 'data-original'):
                for i in re.findall(r'%s="([^"]*)"' % attr, html):
                    if 'cover' in i or 'jisuimage' in i:
                        pic = i
                        break
                if pic:
                    break
            # 2) 退而求其次: 任意含 cover/jisuimage 的 src
            if not pic:
                for i in re.findall(r'src="([^"]*)"', html):
                    if 'cover' in i or 'jisuimage' in i:
                        pic = i
                        break
            # 3) 兜底: 第一个非占位绝对/相对图
            if not pic:
                for i in re.findall(r'src="([^"]*)"', html):
                    if i and not self._PLACEHOLDER_RE.search(i):
                        pic = i
                        break
            pic = self._fix_url(pic, self.host)

            # 简介: info-desc div
            desc = ''
            m = re.search(r'class="info-desc">([^<]*(?:<[^>]*>[^<]*)*)</div>', html, re.DOTALL)
            if m:
                desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                # 去掉 "简介：" 前缀
                desc = re.sub(r'^[简介：:]+', '', desc).strip()
            # 兜底: 剧情简介 区块(新站常见结构)
            if not desc:
                m = re.search(r'剧情简介</h\d>\s*<p[^>]*>([^<]*(?:<[^>]*>[^<]*)*?)</p>', html, re.DOTALL)
                if m:
                    desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if not desc:
                m = re.search(r'class="[^"]*desc[^"]*">([^<]*(?:<[^>]*>[^<]*)*?)</(?:div|p)>', html, re.DOTALL)
                if m:
                    desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if not desc:
                m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
                if m:
                    desc = m.group(1)
                    # 去掉 "荐片影视为你提供XXX剧情简介:" 前缀
                    desc = re.sub(r'^.*?剧情简介[：:]', '', desc).strip()

            # 年份/地区/类型: 从 info-row 中提取
            year = ''
            area = ''
            type_ = ''
            actor = ''
            director = ''
            # info-label + info-text 配对
            pairs = re.findall(
                r'class="info-label">([^<]+)</span>\s*<span\s+class="info-text">([^<]*)</span>',
                html
            )
            for label, value in pairs:
                label = label.strip().rstrip('：:')
                value = value.strip()
                if not value or value == '内详':
                    continue
                if '年份' in label:
                    year = value
                elif '地区' in label:
                    area = value
                elif '类型' in label:
                    type_ = value
                elif '主演' in label:
                    actor = value
                elif '导演' in label:
                    director = value
            # 兜底: 中文标签(分类/地区/年份/类型/语言/导演/主演/更新) — 新站结构
            if not any([year, area, type_, actor, director]):
                for label, value in re.findall(
                    r'(分类|类型|地区|年份|语言|导演|主演|更新)[：:]\s*'
                    r'(?:<[^>]+>)?\s*([^<\n<>]+(?:<[^>]+>[^<\n<>]+)*)',
                    html
                ):
                    label_clean = re.sub(r'<[^>]+>', '', label)
                    value_clean = re.sub(r'<[^>]+>', '', value).strip('[] \t')
                    value_clean = re.sub(r'\s+', ' ', value_clean).strip()
                    if not value_clean or value_clean == '内详':
                        continue
                    if '年份' in label_clean and not year:
                        year = value_clean
                    elif '地区' in label_clean and not area:
                        area = value_clean
                    elif ('类型' in label_clean or '分类' in label_clean) and not type_:
                        type_ = value_clean
                    elif '主演' in label_clean and not actor:
                        actor = value_clean
                    elif '导演' in label_clean and not director:
                        director = value_clean
            # 兜底: 从 meta description 或 info 文本中提取年份
            if not year:
                ym = re.search(r'(\d{4})', desc or html[:5000])
                if ym:
                    year = ym.group(1)

            # 播放源和剧集: /play/{vid}-{src}-{ep}.html (同时记录位置用于源名定位)
            play_iter = list(re.finditer(
                r'href="/play/%s-(\d+)-(\d+)\.html"[^>]*>([^<]*)<' % re.escape(vid), html))
            plays = [(m.group(1), m.group(2), m.group(3)) for m in play_iter]

            # 兜底: 站点改版后内部文案可能变化, 退化为从 URL 解析 src/ep
            if not plays:
                for href in re.finditer(r'href=["\'](/play/%s-(\d+)-(\d+)\.html)["\']' % re.escape(vid), html):
                    plays.append((href.group(2), href.group(3), '第%s集' % href.group(3)))

            if not plays:
                plays = [('1', '1', '点击播放')]

            # 按来源(src)分组, 并记录每个源播放链接的位置(避开 <head> 里的 meta og:video)
            sources = {}
            src_pos = {}
            for m in play_iter:
                sid = m.group(1)
                sources.setdefault(sid, []).append((m.group(2), m.group(3)))
                src_pos.setdefault(sid, []).append(m.start())
            if not src_pos:  # 兜底分支: 重新扫描位置
                for sid, ep, _ in plays:
                    src_pos.setdefault(sid, []).append(html.find('href="/play/%s-%s-' % (vid, sid)))

            # 源名称: 取离该源播放区(播放链接中点)最近的、非推荐类标题(h2/h3)
            sorted_srcs = sorted(sources.keys(), key=lambda x: int(x) if x.isdigit() else 0)
            src_names = {}
            heads = [(m.start(), re.sub(r'<[^>]+>', '', m.group(1)).strip())
                     for m in re.finditer(r'<h[23][^>]*>(.*?)</h[23]>', html, re.DOTALL)]
            _NOISE = re.compile(r'(猜你|相关|推荐|热门|最新|排行|猜你喜欢|剧情简介)')
            for sid in sorted_srcs:
                pos_list = src_pos.get(sid) or [html.find('href="/play/%s-%s-' % (vid, sid))]
                center = (min(pos_list) + max(pos_list)) / 2.0
                best, best_d = '', 1 << 30
                for hp, ht in heads:
                    if not ht or _NOISE.search(ht):
                        continue
                    d = abs(hp - center)
                    if d < best_d:
                        best_d, best = d, ht
                src_names[sid] = best or '荐片专线'

            # 构建播放列表
            play_from_parts = []
            play_url_parts = []
            for idx, src_id in enumerate(sorted_srcs):
                sname = src_names.get(src_id, '线路%d' % (idx + 1))
                play_from_parts.append(sname)
                eps = sources[src_id]
                ep_list = []
                for ep_id, ep_name in eps:
                    ep_name = (ep_name or '').strip()
                    # 播放按钮文案(立即播放/播放)无集数含义, 规整为 第N集
                    if not ep_name or re.match(r'^(立即播放|播放|点击播放|观看|在线看)$', ep_name):
                        ep_name = '第%s集' % ep_id
                    play_url = '/play/%s-%s-%s.html' % (vid, src_id, ep_id)
                    ep_list.append('%s$%s' % (ep_name, play_url))
                play_url_parts.append('#'.join(ep_list))

            vod = {
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_year': year,
                'vod_area': area,
                'vod_type': type_,
                'vod_actor': actor,
                'vod_director': director,
                'vod_content': desc,
                'vod_play_from': '$$$'.join(play_from_parts),
                'vod_play_url': '$$$'.join(play_url_parts),
            }
            return {'list': [vod]}
        except Exception:
            return {'list': []}

    # ============================================================
    #  搜索 (服务端渲染, 可用)
    # ============================================================

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg) if pg else 1
            kw = _quote(key)
            path = '/search.html?wd=%s' % kw
            if pg > 1:
                path += '&page=%d' % pg
            html = self._fetch_html(path, lookfor='/movie/')
            results = self._parse_cards(html)
            return {'page': pg, 'list': results}
        except Exception:
            return {'page': 1, 'list': []}

    def searchContentPage(self, key, quick, pg=1):
        return self.searchContent(key, quick, pg)

    # ============================================================
    #  播放 (player_aaaa + encrypt:2 解码)
    # ============================================================

    def playerContent(self, flag, id, vipFlags):
        """
        播放页解码链路:
        1. 提取 player_aaaa JSON 对象
        2. encrypt=2: base64decode(url) -> unquote() -> m3u8 直链
        3. encrypt=1: unquote(url) -> m3u8 直链
        4. encrypt=0: url 即直链
        5. 兜底: 直接搜索 m3u8/mp4 直链
        """
        try:
            if not id.startswith('http'):
                url = self.host + id if id.startswith('/') else self.host + '/' + id
            else:
                url = id

            # 播放 URL 缓存
            cache_key = url
            now = time.time()
            cached = self._play_cache.get(cache_key)
            if cached and (now - cached['time']) < _PLAY_CACHE_TTL:
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': cached['url'],
                    'header': json.dumps({
                        'User-Agent': self.header['User-Agent'],
                        'Referer': self.host,
                    }),
                    'from': flag,
                }

            html = self._fetch_html(url)
            play_url = ''

            # 提取 player_aaaa JSON(用 JSONDecoder 处理嵌套花括号)
            if html:
                idx = html.find('player_aaaa')
                if idx >= 0:
                    brace_idx = html.find('{', idx)
                    if brace_idx >= 0:
                        try:
                            from json.decoder import JSONDecoder
                            decoder = JSONDecoder()
                            obj, _ = decoder.raw_decode(html[brace_idx:])
                            encrypt = obj.get('encrypt', 0)
                            enc_url = obj.get('url', '')

                            if encrypt == 2:
                                # base64 -> url_decode
                                decoded = base64.b64decode(enc_url).decode('utf-8')
                                play_url = _unquote(decoded)
                            elif encrypt == 1:
                                play_url = _unquote(enc_url)
                            else:
                                play_url = enc_url
                        except Exception:
                            pass

            # 兜底: 直接搜索 m3u8 直链
            if not play_url:
                m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
                if m:
                    play_url = m.group(0)

            # 兜底: 搜索 mp4 直链
            if not play_url:
                m = re.search(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', html)
                if m:
                    play_url = m.group(0)

            if play_url:
                self._play_cache[cache_key] = {'url': play_url, 'time': now}
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': play_url,
                    'header': json.dumps({
                        'User-Agent': self.header['User-Agent'],
                        'Referer': self.host,
                    }),
                    'from': flag,
                }

            # 兜底: 交给框架解析
            return {
                'parse': 1,
                'playUrl': '',
                'url': url,
                'header': json.dumps({
                    'User-Agent': self.header['User-Agent'],
                    'Referer': self.host,
                }),
                'from': flag,
            }
        except Exception:
            return {
                'parse': 1,
                'playUrl': '',
                'url': '',
                'header': json.dumps({'User-Agent': self.header['User-Agent']}),
                'from': flag,
            }
