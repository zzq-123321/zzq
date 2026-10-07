# -*- coding: utf-8 -*-
"""
4kvms.com — WebHomeTV / PeekPro Python Spider (Chaquopy)  —— 增强/修复版
==============================================================================
站点特征（与 MacCMS 不同，需定制解析，但沿用 WebHomeTV 契约）:
  - 自建 Tailwind 框架；路由: /movie /tv /anime 分类, /play/{hash} 单集播放页
  - 每集独立 hash；选集列在播放页的 <a class="episode-link"> 上:
        href="/play/{hash}"   dataid="{播放令牌输入}"   data-line / data-episode
    ⚠ 注意: 该 <a> 是多行标签(属性跨行)，必须用 BeautifulSoup 解析，不能靠
      单行正则 <a[^>]*class="episode-link" 去抓(会被换行截断，抓不到)。
  - 播放地址由 WASM (nbmovie_wasm) 现场签名:
        JS 侧:  i = wasm.build_play_url(dataid, pageHash, quality, playKey||'0')
                fetch(i)   // i 形如 /video/play?p=&v=&q=&s=&t=&k=
    => /video/play 这个字符串本身【不在 JS 里】，是 WASM(Rust)内部拼出来的；
       s(签名)/t(时间戳)/k(令牌) 三个参数在 WASM 内用内置密钥算出。
  - 签名已逆向复现(纯 Python 即可):
        k  = base64( userlink XOR "nbmovie2024secretkey" )   # userlink 来自播放页 x-data
        s  = HMAC-SHA256( key=v, msg="p:t:v" )[:32]          # v = 播放页 URL hash
        t  = Date.now() (毫秒)
      => playerContent 在 Python 内自算 k/s/t，直接请求 /video/play 拿到 CDN 直链，
         以 parse:0 交给 App 原生播放器(支持 m3u8/mp4)，无需 webview、不依赖浏览器内核。

本次修复/增强（对应需求）:
  ① 精确取令牌  —— _extract_token(): 从选集 <a dataid>、页面 var vodid、
     inline episodeManager(...) 精确抽取“播放令牌输入”(dataid)。明确: /video/play
     最终签名令牌由 WASM 运行时生成，静态页只能拿到其输入 dataid（即 p 参数）。
  ② 打印全部选集链接属性 —— _dump_episode_attrs(): 遍历所有选集 <a>，打印每个元素的
     全部属性 key=value（含 href/dataid/data-line/data-episode/@click/x-show 等），
     便于核对 Alpine 绑定与排错。
  ③ 定位调用 /video/play 的 JS 签名逻辑 —— _locate_sign_logic(): 下载打包 JS，抽取
     build_play_url + fetch(i) 调用片段与 loadPlayUrl/autoLoadCurrentEpisode 逻辑，
     输出并说明“签名在 WASM 内完成，JS 仅发起 fetch”。
  ★ ④ 纯 Python 直签播放(修复“打不开”) —— playerContent() 复现 k/s/t 三参，
     直连 /video/play 取 CDN 直链，parse:0 交由原生播放器，彻底摆脱 webview。

WebHomeTV 契约（勿改）:
  ✓ class Spider(base.spider.Spider), 实例方法
  ✓ 解析只用 BeautifulSoup(html.parser) + requests
  ✓ 接口返回 dict（框架序列化）
  ✓ playerContent.header 为 dict
"""
import re
import sys
import json
import time
import hmac
import base64
import hashlib
import requests
from bs4 import BeautifulSoup
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            return requests.get(url, headers=headers or {}, timeout=15, **kw)


class Spider(BaseSpider):

    # ===================== 站点配置 =====================
    SITE_HOST = "https://4kvms.com"
    SITE_NAME = "4K影视"

    # 调试开关: True 时 detailContent 会顺带打印选集属性与令牌（生产环境保持 False）
    DEBUG = False

    # 首页分类（导航里仅这三个影视分类；playlists 是片单非影片）
    CATEGORIES = [
        {'type_id': "movie", 'type_name': "电影"},
        {'type_id': "tv",    'type_name': "电视剧"},
        {'type_id': "anime", 'type_name': "动漫"},
    ]

    # URL 路由
    URL_CATEGORY = "/%s"                 # /movie /tv /anime
    URL_DETAIL   = "/play/%s"           # /play/{hash} 单集播放页(含完整选集)
    URL_SEARCH   = "/search?q=%s"       # /search?q=关键词

    # 打包主 JS（含 build_play_url / loadPlayUrl / autoLoadCurrentEpisode 逻辑）
    JS_BUNDLE_RE = re.compile(
        r'src="(/static/js/dist/app\.ultra\.min\.[^"]+\.js)"')

    # 内联 vodid（播放页 <script> 里: var vodid = 'ch4xxxx'）
    VODID_RE = re.compile(r"""var\s+vodid\s*=\s*['"]([^'"]+)['"]""", re.I)
    # 播放页导航 x-data 内携带的 userlink（k 令牌源；每次会话不同）
    USERLINK_RE = re.compile(r"""userlink\s*:\s*['"]([^'"]+)['"]""")
    # 选集组件: episodeManager(currentLine, currentEpisode, [{lineName, episodeCount}, ...])
    EPISODE_MGR_RE = re.compile(
        r'episodeManager\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\[.*?\])\s*\)', re.S)

    # —— 签名常量（逆向复现 WASM nbmovie_wasm）——
    # k = base64( userlink XOR SIGN_KEY )；s = HMAC-SHA256( key=v, msg="p:t:v" )[:32]
    SIGN_KEY = b'nbmovie2024secretkey'
    API_PATH = "/video/play"

    # ===================== 初始化 =====================
    def init(self, extend=""):
        self.host = self.SITE_HOST
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.host + '/',
        }
        if extend and isinstance(extend, str) and extend.startswith('http'):
            m = re.match(r'(https?://[^/]+)', extend)
            if m:
                self.host = m.group(1).rstrip('/')
                self.headers['Referer'] = self.host + '/'

    def getName(self):
        return self.SITE_NAME

    # ===================== 接口 =====================
    def homeContent(self, filter):
        return {"class": [dict(t) for t in self.CATEGORIES], "filters": {}}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if pg else 1
        except Exception:
            pg = 1
        html = self._fetch(self.URL_CATEGORY % tid)
        items = self._parse_cards(html) if html else []
        # 分类分页服务端无效(首屏固定), 单页返回
        return {"list": items, "page": pg, "pagecount": 1,
                "limit": len(items), "total": len(items)}

    def detailContent(self, ids):
        try:
            vid = ids[0].split(',')[0].strip() if isinstance(ids, list) else str(ids)
            html = self._fetch(self.URL_DETAIL % vid)
            if not html:
                return {"list": []}
            soup = BeautifulSoup(html, 'html.parser')

            # —— 需求②: 打印全部选集链接属性（调试）——
            if self.DEBUG:
                self._dump_episode_attrs(soup)
            # —— 需求①: 精确取令牌（调试/诊断，同时供扩展使用）——
            token = self._extract_token(html, soup)
            if self.DEBUG:
                print("[TOKEN] 精确令牌输入: %s" % json.dumps(
                    token, ensure_ascii=False))

            vod = self._parse_detail(soup, vid, token)
            if not vod:
                return {"list": []}
            if self.DEBUG and token.get('dataids'):
                # 把每集 dataid 作为诊断字段并入结果(框架会忽略未知 key)
                vod['vod_play_dataid'] = token['dataids']
            return {"list": [vod]}
        except Exception as e:
            if self.DEBUG:
                print("[detailContent] 异常: %s" % e)
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg) if pg else 1
        except Exception:
            pg = 1
        from urllib.parse import quote
        html = self._fetch(self.URL_SEARCH % quote(str(key)))
        items = self._parse_cards(html) if html else []
        return {"list": items, "page": pg, "pagecount": 1 if items else 0}

    def playerContent(self, flag, id, vipFlags):
        """
        纯 Python 复现 WASM 签名，直连 /video/play 取 CDN 直链，parse:0 交由原生播放器。

        id 形如: "$" 后的播放路径 "/play/{hash}"（vod_play_url 由 detailContent 构造,
        兼容旧格式 "/play/{hash}#dataid={p}"）
        逆向结论（已用真实播放页 + 服务端 200 复验）:
          - v = 播放页 URL hash（/play/{hash}），同时作为 HMAC 密钥与消息一部分
          - p = 选集 dataid（#dataid= 后的值，即 WASM 第 1 参）
          - k = base64( userlink XOR "nbmovie2024secretkey" )，userlink 来自播放页
          - s = HMAC-SHA256( key=v, msg="p:t:v" )[:32]，t = 毫秒时间戳
        => 不再依赖 webview / WASM，App 原生播放器可直接播 m3u8 / mp4 直链，解决“打不开”。
        """
        try:
            raw = str(id)
            # 1) 切出当前选集: 取第一个 '$' 之后的部分
            ep = raw if '$' not in raw else raw.split('$', 1)[1]

            # 2) 提取 v（URL hash）与 p（dataid）
            v = ''
            m = re.search(r'/play/([^/?#]+)', ep)
            if m:
                v = m.group(1).strip()
            p = ''
            m = re.search(r'#dataid=([^&]+)', ep)
            if m:
                p = m.group(1).strip()
            if not v:
                v = ep.strip('/').split('/')[-1].split('#')[0].strip()

            if not v:
                return {"parse": 0, "url": "", "header": self._api_headers()}

            # 3) 抓播放页取 userlink（k 源，每次会话不同）—— 顺便兜底取 dataid
            html = self._fetch(self.URL_DETAIL % v)
            userlink = self._extract_userlink(html) if html else ''
            if not p and html:
                p = self._dataid_for(html, v)
            if not p:
                p = v  # 极端兜底

            # 4) 自算 k / s / t 并请求直链
            k = self._make_k(userlink) if userlink else '0'
            t = str(int(time.time() * 1000))
            s = self._sign(p, v, t)
            api = ("%s%s?p=%s&v=%s&q=1080&s=%s&t=%s&k=%s"
                   % (self.host, self.API_PATH, p, v, s, t, k))

            data = ''
            try:
                rsp = self.fetch(api, headers=self._api_headers())
                data = rsp.text if rsp else ''
            except Exception:
                data = ''

            stream_url, _mtype = self._select_stream(data)
            if not stream_url:
                # 兜底: 若签名接口异常，回退到 4K 试一次（q=1）
                t2 = str(int(time.time() * 1000))
                s2 = self._sign(p, v, t2)
                api2 = ("%s%s?p=%s&v=%s&q=1&s=%s&t=%s&k=%s"
                        % (self.host, self.API_PATH, p, v, s2, t2, k))
                try:
                    rsp2 = self.fetch(api2, headers=self._api_headers())
                    data2 = rsp2.text if rsp2 else ''
                    stream_url, _mtype = self._select_stream(data2)
                except Exception:
                    pass

            if stream_url:
                return {"parse": 0, "url": stream_url, "header": self._api_headers()}
            # 实在取不到直链: 返回空（交由框架提示），不再交给 webview
            return {"parse": 0, "url": "", "header": self._api_headers()}
        except Exception as e:
            if self.DEBUG:
                print("[playerContent] 异常: %s" % e)
            return {"parse": 0, "url": "", "header": self._api_headers()}

    # ===================== 直签辅助（复现 WASM nbmovie_wasm） =====================
    def _api_headers(self):
        return {
            'User-Agent': self.headers['User-Agent'],
            'Referer': self.host + '/',
            'Accept': 'application/json, text/plain, */*',
        }

    def _extract_userlink(self, html):
        """从播放页取 userlink（x-data 内 userlink:'...'），作为 k 的源。"""
        if not html:
            return ''
        m = self.USERLINK_RE.search(html)
        return m.group(1).strip() if m else ''

    def _dataid_for(self, html, v):
        """从播放页取与 /play/{v} 这一集对应的 dataid。

        真实 <a> 的 href 与 dataid 之间夹着 @click.prevent / x-show 等其他属性,
        不能假设二者紧邻。主路径用 BeautifulSoup 按 href 精确匹配;
        正则只作兜底(属性间允许夹其他属性, [^>]* 宽松跳过)。
        """
        if not html:
            return ''
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for a in soup.select('a[dataid][href]'):
                href = (a.get('href') or '').strip()
                if href.rstrip('/').endswith('/' + v):
                    did = (a.get('dataid') or '').strip()
                    if did:
                        return did
        except Exception:
            pass
        pats = [
            r'dataid="(\d+)"[^>]*?href="[^"]*/play/%s\b' % re.escape(v),
            r'href="[^"]*/play/%s\b[^"]*"[^>]*?dataid="(\d+)"' % re.escape(v),
        ]
        for pat in pats:
            m = re.search(pat, html)
            if m:
                return m.group(1)
        return ''

    @classmethod
    def _make_k(cls, userlink):
        """k = base64( userlink XOR SIGN_KEY )，密钥流周期 20，确定性可复现。"""
        if not userlink or userlink == '0':
            return '0'
        xored = bytes(ord(c) ^ cls.SIGN_KEY[i % len(cls.SIGN_KEY)]
                      for i, c in enumerate(userlink))
        return base64.b64encode(xored).decode('ascii')

    @classmethod
    def _sign(cls, p, v, t):
        """
        s = HMAC-SHA256( key=v, msg="p:t:v" )[:32]
        逆向确认: 内存中明文为 p + ':' + t + ':' + v，密钥为 v（页 hash）。
        """
        msg = "%s:%s:%s" % (p, t, v)
        return hmac.new(v.encode('utf-8'), msg.encode('utf-8'),
                        hashlib.sha256).hexdigest()[:32]

    @staticmethod
    def _select_stream(json_text):
        """从 /video/play 响应里挑出可用 CDN 直链；过滤占位 '1' 与非 http(s)。"""
        try:
            j = json.loads(json_text)
        except Exception:
            return '', ''
        if not isinstance(j, dict) or j.get('code') != 200:
            return '', ''
        urls = j.get('data', {}).get('quality_urls', []) or []
        valid = [u for u in urls
                 if isinstance(u, dict) and str(u.get('url', '')).startswith('http')
                 and str(u.get('url', '')) != '1']
        if not valid:
            return '', ''
        # 优先 m3u8，再 mp4，其余；同类型按码率从高到低
        order = {'m3u8': 0, 'mp4': 1}
        valid.sort(key=lambda u: (order.get((u.get('mtype') or '').lower(), 2),
                                 -(int(u.get('bitrate') or 0))))
        best = valid[0]
        return best.get('url', ''), best.get('mtype', '')

    # ===================== 基础方法 =====================
    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def localProxy(self, param=''):
        return {}

    # ===================== 网络 =====================
    def _fetch(self, url):
        try:
            if not url.startswith('http'):
                url = self.host + url
            rsp = self.fetch(url, headers=self.headers)
            return rsp.text if rsp else ''
        except Exception:
            try:
                r = requests.get(url, headers=self.headers, timeout=15)
                return r.text if r.status_code == 200 else ''
            except Exception:
                return ''

    # ===================== 需求①: 精确取令牌 =====================
    def _extract_token(self, html, soup):
        """
        精确抽取“播放令牌输入”。

        说明: /video/play?p=&v=&q=&s=&t=&k= 的最终签名令牌(s/t/k)由 WASM 在运行时生成，
        静态 HTML 里【没有】现成令牌。这里取到的是签名的【输入】，即:
          - 页面级 vodid        (var vodid = '...')
          - 每集 dataid         (<a dataid="...">，即 /video/play 的 v 参数，WASM 第一参)
          - 选集组件参数        episodeManager(currentLine, currentEpisode, lines)
          - 任何 data-token / meta token（站点若后续新增可自动捕获）
        返回 dict，全部为“精确字符串”，无截断。
        """
        token = {
            'vodid': '',
            'dataids': [],          # 每集 dataid（顺序与选集一致）
            'current_line': '',
            'current_episode': '',
            'lines': [],            # episodeManager 的线路定义
            'secret_key': 'play',   # JS 里硬编码: let s='play'
            'extra': {},            # 其它偶发的 token 类属性
        }

        # 1) 页面级 vodid（内联 <script>）
        m = self.VODID_RE.search(html or '')
        if m:
            token['vodid'] = m.group(1).strip()

        # 2) 每集 dataid —— 来自选集 <a>（优先 a.episode-link，兜底 a[dataid][href^="/play/"]）
        seen = set()
        for a in soup.select('a.episode-link'):
            did = (a.get('dataid') or '').strip()
            if did and did not in seen:
                seen.add(did)
                token['dataids'].append(did)
        if not token['dataids']:
            for a in soup.select('a[dataid][href^="/play/"]'):
                did = (a.get('dataid') or '').strip()
                if did and did not in seen:
                    seen.add(did)
                    token['dataids'].append(did)

        # 3) 选集组件 inline 参数 episodeManager(...)
        m = self.EPISODE_MGR_RE.search(html or '')
        if m:
            token['current_line'] = m.group(1)
            token['current_episode'] = m.group(2)
            token['lines'] = self._parse_js_line_array(m.group(3))

        # 4) 兜底: 任何 token/sign/key 类属性（data-token / data-sign / meta 等）
        for tag in soup.find_all(attrs={'data-token': True}):
            token['extra']['data-token'] = tag.get('data-token')
        for tag in soup.find_all('meta'):
            name = (tag.get('name') or tag.get('property') or '').lower()
            if 'token' in name or 'sign' in name or name in ('key', 'secret'):
                token['extra'][name] = tag.get('content', '')

        return token

    @staticmethod
    def _parse_js_line_array(js_arr):
        """
        解析 episodeManager 的线路数组。它是 JS 对象字面量(单引号/无引号 key)，
        不能直接 json.loads。优先尝试容错转换，失败则正则抽取 lineName/episodeCount。
        """
        if not js_arr:
            return []
        try:
            # 容错: 单引号->双引号, 去尾逗号, key 加引号
            s = js_arr.strip()
            s = re.sub(r"'", '"', s)
            s = re.sub(r'([{,]\s*)([A-Za-z_$][\w$]*)\s*:', r'\1"\2":', s)
            s = re.sub(r',\s*([}\]])', r'\1', s)
            return json.loads(s)
        except Exception:
            lines = []
            for mm in re.finditer(
                    r"lineName\s*:\s*'([^']*)'[^}]*?episodeCount\s*:\s*(\d+)",
                    js_arr or '', re.S):
                lines.append({'lineName': mm.group(1),
                              'episodeCount': int(mm.group(2))})
            return lines

    # ===================== 需求②: 打印全部选集链接属性 =====================
    def _dump_episode_attrs(self, soup):
        """
        调试用: 遍历所有选集 <a>，打印每个元素的【全部属性】 key=value。
        选集元素来源(按优先级并集去重):
          - a.episode-link                              （主选集，含 dataid）
          - a[dataid][href^="/play/"]                   （兜底，含 dataid）
          - a[href^="/play/"][data-line][data-episode]  （当前集占位/线路集）
        """
        print("=" * 70)
        print("[选集链接属性] 开始打印全部选集 <a> 的属性")
        print("=" * 70)
        dumped, idx = set(), 0
        selectors = [
            'a.episode-link',
            'a[dataid][href^="/play/"]',
            'a[href^="/play/"][data-line][data-episode]',
        ]
        for sel in selectors:
            for a in soup.select(sel):
                # 用 (href, dataid) 去重，避免重复打印同一集
                key = (a.get('href', ''), a.get('dataid', ''))
                if key in dumped:
                    continue
                dumped.add(key)
                idx += 1
                name = (a.get_text(strip=True) or '(无文本)')
                print("\n--- 选集#%d  显示名=%r ---" % (idx, name))
                for k, v in a.attrs.items():
                    print("    %-14s = %s" % (k, v))
        if idx == 0:
            print("（未找到任何选集 <a>；本 spider 依赖静态 <a dataid> 直签，若选集纯客户端渲染则无法取到 dataid）")
        print("=" * 70)
        print("[选集链接属性] 共打印 %d 个选集元素" % idx)
        print("=" * 70)

    # ===================== 需求③: 定位调用 /video/play 的 JS 签名逻辑 =====================
    def _locate_sign_logic(self, html=None, play_id=None):
        """
        定位并抽取“调用 /video/play 的 JS 签名逻辑”。

        结论(已扒打包 JS 验证):
          - /video/play 这个 URL 字符串【不在 JS 文本中】，由 WASM(Rust→nbmovie_wasm)
            在 build_play_url() 内部拼出，返回完整 URL 字符串。
          - JS 侧签名调用链:
                loadPlayUrl(dataid, secretKey='play', quality, playKey='0')
                  -> i = wasm.build_play_url(dataid, 'play', quality, playKey||'0')
                  -> fetch(i)                      // i = /video/play?p=&v=&q=&s=&t=&k=
          - autoLoadCurrentEpisode() 从 a[data-line][data-episode] 读 href(播放hash) 与
            dataid(令牌输入)，喂给 loadPlayUrl。
          - s(签名)/t(令牌)/k(密钥) 三个参数在 WASM 内用内置密钥计算，纯 Python 不可复现。
        => 本函数下载打包 JS，抽取上述片段并打印，供核对/审计。
        """
        if not html and play_id:
            html = self._fetch(self.URL_DETAIL % play_id)
        if not html:
            # 没给 html 也无法抓，尝试直接拉首页取其引用的打包 JS 也行，但这里要求 play 页
            print("[签名逻辑] 无可用 HTML，无法定位（请提供 play 页 HTML 或 play_id）")
            return None

        m = self.JS_BUNDLE_RE.search(html)
        if not m:
            print("[签名逻辑] 播放页未找到打包主 JS 引用")
            return None
        js_url = self.host + m.group(1)
        js = self._fetch(js_url)
        if not js:
            print("[签名逻辑] 下载打包 JS 失败: %s" % js_url)
            return None

        print("=" * 70)
        print("[签名逻辑] 打包 JS: %s  (size=%d)" % (js_url, len(js)))
        print("=" * 70)

        # 片段1: build_play_url + fetch(i) —— 真·签名调用点
        print("\n--- 片段A: WASM build_play_url -> fetch(i)（/video/play 来源）---")
        i = js.find('build_play_url')
        if i >= 0:
            start = max(0, i - 160)
            end = min(len(js), i + 320)
            print("    ...%s..." % js[start:end])
        else:
            print("    (未在主 JS 找到 build_play_url，可能已拆到独立 wasm 胶水 JS)")

        # 片段2: loadPlayUrl 定义 —— dataid 如何流入签名
        print("\n--- 片段B: loadPlayUrl(dataid, secretKey, quality, playKey) ---")
        i = js.find('loadPlayUrl')
        if i >= 0:
            start = max(0, i - 60)
            end = min(len(js), i + 360)
            print("    ...%s..." % js[start:end])

        # 片段3: autoLoadCurrentEpisode —— 从选集 <a> 读 dataid/href
        print("\n--- 片段C: autoLoadCurrentEpisode（选集 <a> -> dataid/href）---")
        i = js.find('autoLoadCurrentEpisode')
        if i >= 0:
            start = max(0, i - 40)
            end = min(len(js), i + 360)
            print("    ...%s..." % js[start:end])

        print("\n" + "-" * 70)
        print("结论: /video/play 由 WASM.build_play_url 在【运行时】签名生成，")
        print("      JS 仅负责 fetch(i)。但签名算法已逆向复现（纯 Python 即可）:")
        print("        k = base64( userlink XOR 'nbmovie2024secretkey' )")
        print("        s = HMAC-SHA256( key=页hash, msg='p:t:v' )[:32]")
        print("      => playerContent 已用纯 Python 自算 k/s/t，直连 /video/play 取直链，")
        print("         parse:0 交由原生播放器，无需 webview / 浏览器内核。")
        print("-" * 70)
        return js

    # ===================== 卡片解析 =====================
    def _fix_pic(self, u):
        if not u:
            return ''
        # 百度 gimg 中转图: 真实图藏在 .../gimg/...&src=真实图URL（无 '?'，参数在 path 里）
        if 'gimg' in u and 'src=' in u:
            real = u.split('src=', 1)[1].split('&')[0]
            if real:
                if real.startswith('//'):
                    return 'https:' + real
                if real.startswith('/'):
                    return self.host + real
                if real.startswith('http'):
                    return real
                return 'https://' + real
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('/'):
            return self.host + u
        return u.replace('&amp;', '&')

    def _card_remarks(self, a):
        """提取卡片角标: 画质(4k/1080P等) + 状态(更新至X集/全X集), 作为 vod_remarks"""
        tags = []
        for sp in a.find_all('span'):
            t = sp.get_text(strip=True)
            if not t or len(t) > 12:
                continue
            tl = t.lower()
            if re.match(r'^(4k|1080p?|720p?|蓝光|超清|高清|hd)$', tl):
                tags.append(t)
            elif re.match(r'^(更新至\d+集|全\d+集|共\d+集|完结|全集)$', t):
                tags.append(t)
        # 去重并保持出现顺序
        seen = set(); uniq = []
        for t in tags:
            if t not in seen:
                seen.add(t); uniq.append(t)
        return ' '.join(uniq)

    def _parse_cards(self, html):
        items, seen = [], set()
        if not html:
            return items
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.select('a[href^="/play/"]'):
            href = a.get('href', '').strip()
            if not href or href.count('/') != 2:
                continue
            vid = href.rstrip('/').split('/')[-1]
            if not vid or vid in seen:
                continue
            img = a.select_one('img')
            cover = self._fix_pic(
                (img.get('data-src') or img.get('src') or '') if img else '')
            h3 = a.select_one('h3')
            title = (h3.get_text(strip=True) if h3
                     else (img.get('alt', '').strip() if img else '')
                     or a.get_text(strip=True))
            if not title:
                continue
            # 过滤榜单角标行: 分类页/首页的排行区每行也是 <a href="/play/..">，
            # 但只有数字角标图(/static/images/numbers/N.svg)或占位图，无真实封面
            if not cover or '/static/images/numbers/' in cover or '/static/images/placeholder' in cover:
                continue
            seen.add(vid)
            items.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": cover,
                "vod_remarks": self._card_remarks(a),
            })
        return items

    # ===================== 详情解析 =====================
    def _parse_detail(self, soup, vid, token=None):
        if soup is None:
            return None

        # 片名: <title> 形如 "凡人修仙传 - 第1集 -4k影视" -> 取首个 ' - ' 之前
        name = ''
        if soup.title:
            name = soup.title.get_text().split(' - ')[0].strip()

        # 封面: og:image
        pic = ''
        og = soup.find('meta', attrs={'property': 'og:image'})
        if og:
            pic = self._fix_pic(og.get('content', ''))

        # 选集: a.episode-link（真实静态标签，属性含 href/dataid/data-line/data-episode）
        # 兜底: a[dataid][href^="/play/"] 与当前集占位 a[data-line][data-episode]
        eps = []
        seen = set()
        selectors = [
            'a.episode-link',
            'a[dataid][href^="/play/"]',
            'a[href^="/play/"][data-line][data-episode]',
        ]
        for sel in selectors:
            for a in soup.select(sel):
                href = (a.get('href') or '').strip()
                if '/play/' not in href:
                    continue
                key = href.rstrip('/').split('/')[-1]
                if key in seen:
                    continue
                seen.add(key)
                ep_name = a.get_text(strip=True) or str(len(eps) + 1)
                full = href if href.startswith('/') else '/' + href
                # 注意: 这里【不能】把 dataid 拼成 "/play/{hash}#dataid={p}"!
                # WebHomeTV 按 '#' 拆集、'$' 拆名/链, '#dataid=..' 会被当成
                # 第二集(无名, 框架自动编号显示成"02")。
                # dataid 由 playerContent 抓播放页时用 _dataid_for(html, v) 兜底查得,
                # 与取 userlink 同一次请求, 零额外成本。
                eps.append((ep_name, full))

        if not eps:
            # 兜底: 没有选集链接就不构造成片
            return None

        # 4kvms 无独立画质直链(wasm 签名 + WAF): 所有画质共用同一播放页 /play/{hash}。
        # 4K 由 App 端 WebHome 扩展(匹配本站点 key)在播放页加载前把
        # localStorage['artplayer_settings'].quality 钉成 '1' 实现(见扩展配置说明)。
        one_line = "#".join("%s$%s" % (n, h) for n, h in eps)
        vod_play_from = "4kvms"
        vod_play_url = one_line

        # 元信息(尽力): keywords / description meta
        meta_kw = soup.find('meta', attrs={'name': 'keywords'})
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        content = (meta_desc.get('content', '') if meta_desc else '')
        area = ''
        if meta_kw:
            kw = meta_kw.get('content', '')
            for part in re.split(r'[,，]', kw):
                if '中国' in part or '美国' in part or '韩国' in part or '日本' in part \
                   or '大陆' in part or '港' in part or '台' in part:
                    area = part.strip()
                    break

        # 精确令牌输入(需求①): 优先用已抽取的 token，回写 vodid 便于校验
        vodid = (token or {}).get('vodid', '') if token else ''

        return {
            "vod_id": str(vid),
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": "",
            "type_name": "",
            "vod_year": "",
            "vod_area": area,
            "vod_director": "",
            "vod_actor": "",
            "vod_content": content,
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url,
            # 诊断字段(框架忽略未知 key): 页面级 vodid 与每集 dataid
            "vod_vodid": vodid,
        }


# ===================== 诊断入口（本地运行） =====================
def _diagnose(sp, play_id):
    """
    本地诊断: 给定播放页 hash（或带 /play/ 的 URL），依次执行三项增强并输出。
    用法:  python 4kvms.py <play_hash_or_url>   （不带参则仅做自检）
    """
    if play_id.startswith('http'):
        m = re.search(r'/play/([^/?#]+)', play_id)
        play_id = m.group(1) if m else play_id
    html = sp._fetch(sp.URL_DETAIL % play_id)
    if not html:
        print("抓取播放页失败: %s" % play_id)
        return
    soup = BeautifulSoup(html, 'html.parser')
    print("\n########## ① 精确取令牌 ##########")
    tok = sp._extract_token(html, soup)
    print(json.dumps(tok, ensure_ascii=False, indent=2))
    print("\n########## ② 打印全部选集链接属性 ##########")
    sp._dump_episode_attrs(soup)
    print("\n########## ③ 定位 /video/play 的 JS 签名逻辑 ##########")
    sp._locate_sign_logic(html=html)


if __name__ == '__main__':
    sp = Spider()
    sp.init()
    print("Spider:", sp.getName())
    print("home:", [c['type_name'] for c in sp.homeContent(True)['class']])
    if len(sys.argv) > 1:
        _diagnose(sp, sys.argv[1])
    else:
        print("4kvms spider 自检 OK（带播放页 hash 运行可做三项诊断: "
              "python 4kvms.py <play_hash>）")
