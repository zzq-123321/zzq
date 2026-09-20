# -*- coding: utf-8 -*-
"""
荐片影视 绕过爬虫 (jianpian_bypass)
=====================================
在原始 jianpian.py 基础上, 系统性补齐反爬绕过能力:

  1. 过门域名刷新   refresh_domains() + _parse_redirect()
     - 站点常换域名, 入口是一个"过门页", 里面用 `var url='https://真实域名'` 或
       <meta http-equiv=refresh url=...> 指向当前可用域名。
     - 启动/失败时自动解析出真实 host, 避免硬编码域名过期导致整站空白。
  2. 抗结构漂移     _parse_cards() 双轨
     - 先按精确结构(item-cover/pic/lay-src/tag/item-title)匹配;
     - 失败再用宽松正则扫 /movie/{id}.html, 封面兼容 lay-src/data-src/src。
  3. 反爬挑战识别   _is_cf_challenge()
     - 识别 Cloudflare / 风控挑战页, 不当正常内容返回。
  4. 播放解码       playerContent() 全量支持 encrypt 0/1/2
     - 2: base64decode -> unquote -> 直链
     - 1: unquote -> 直链
     - 0: 直链
     - 解码后若为 /video/play?... 或 /xxx 相对路径, 自动补全 host。

反爬机制现场认知(见 README.md):
  - 数据中心 IP 在 TLS 层被 RST(只有家宽/ residential IP 能直连 Web 站)。
  - 播放地址经 player_aaaa 的 base64 混淆, 且最终 m3u8 常带时效 token。
  - 域名轮换 + 过门页(var url)。
  - UA / Referer / sec-ch-* 浏览器头校验。

依赖: TVBox 运行时 `from base.spider import Spider`; 本地自测时无 base 会自动降级为桩类。
"""
import sys
sys.path.append("..")

import re
import json
import time
import base64

try:
    from urllib.parse import unquote as _unquote
except Exception:
    _unquote = lambda x: x

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    # 本地自测用的桩: 真实环境由 TVBox 注入 fetch
    class _BaseSpider:
        def fetch(self, url, headers=None, **kw):
            raise NotImplementedError("需在 TVBox 环境或自测中覆盖 fetch")
        def post(self, url, data=None, headers=None, **kw):
            raise NotImplementedError


# UA 轮换池
_UA_POOL = [
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
]

_HOME_CACHE_TTL = 300
_PLAY_CACHE_TTL = 3600
_REQUEST_TIMEOUT = 10

# 过门域名候选(站点换域名时, 入口常是这些"短链/网关"之一)
# 实际部署请把你已知可用的过门地址填到 ini.extend 或覆盖本类变量。
_GATE_DOMAINS = [
    "https://m.jpyy.site",
    "https://jpyy.site",
    "https://www.jpyy.site",
]


class Spider(_BaseSpider):
    # 默认入口(会被 refresh_domains / init(extend) 覆盖)
    host = "https://m.jpyy.site"
    gate_domains = list(_GATE_DOMAINS)

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
        if not hasattr(self, 'gate_domains'):
            self.gate_domains = list(_GATE_DOMAINS)

    # ============================================================
    #  基础方法
    # ============================================================

    def getName(self):
        return '荐片影视·绕过'

    def init(self, extend=""):
        self._init_state()
        if isinstance(extend, list):
            extend = ''
        extend = extend or ''

        # extend 支持:
        #   "https://真实域名"           -> 直接覆盖 host
        #   "gate=https://过门地址"      -> 设定过门地址并刷新
        gate = ''
        if 'gate=' in extend:
            gate = extend.split('gate=', 1)[1].split('|')[0].strip()
            if gate:
                self.gate_domains = [gate] + self.gate_domains
        if extend.startswith('http'):
            m = re.match(r'(https?://[^/]+)', extend)
            if m:
                self.host = m.group(1).rstrip('/')
                self.header['Referer'] = self.host + '/'
        else:
            # 非 http 的 extend(如分类约定) -> 尝试过门刷新
            self.refresh_domains()

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

    # ---- 过门: 域名刷新 + 解析 var url ----
    @staticmethod
    def _parse_redirect(text):
        """从过门页提取真实域名。
        支持:  var url='https://...'   以及   <meta http-equiv=refresh content='0;url=https://...'>
        """
        if not text:
            return ''
        # 1) var url = '...'
        m = re.search(r"var\s+url\s*=\s*['\"]([^'\"]+)['\"]", text)
        if m and m.group(1).startswith('http'):
            return m.group(1).rstrip('/')
        # 2) meta refresh
        m = re.search(r"<meta[^>]+http-equiv\s*=\s*[\"']?refresh[\"']?[^>]*url\s*=\s*[\"']?([^\"'\s>]+)", text, re.I)
        if m and m.group(1).startswith('http'):
            return m.group(1).rstrip('/')
        # 3) window.location = '...'
        m = re.search(r"location(?:\.href)?\s*=\s*['\"](https?://[^'\"]+)['\"]", text)
        if m:
            return m.group(1).rstrip('/')
        return ''

    def refresh_domains(self):
        """依次尝试过门地址, 解出真实 host 并应用。返回最终 host。"""
        for g in self.gate_domains:
            try:
                r = self.fetch(g, headers={'User-Agent': _UA_POOL[0],
                                           'Referer': g + '/'}, timeout=8)
                t = r.text if hasattr(r, 'text') else ''
                u = self._parse_redirect(t)
                if u:
                    self.host = u
                    self.header['Referer'] = u + '/'
                    return u
            except Exception:
                continue
        return self.host

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
    #  内部请求
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
        if not text:
            return True
        # 播放页常较短且含 player_aaaa, 是真页面, 不误杀
        if 'player_aaaa' in text:
            return False
        # 含真实卡片特征 -> 不算挑战(防止短有效页被误杀成空白)
        for sig in ('/movie/', 'item-cover', 'lay-src', 'item-title', 'jisuimage'):
            if sig in text:
                return False
        if len(text) < 200:
            return True
        markers = ['Just a moment', 'cf-challenge', 'challenge-platform',
                   'cf-browser-verification', 'cf-mitigated',
                   'Attention Required', 'enable JavaScript']
        low = text[:2000].lower()
        for m in markers:
            if m.lower() in low:
                return True
        return False

    @staticmethod
    def _looks_like_site(html):
        """判断响应是否来自荐片真实站点(而非域名过期页/过门页/挑战页)。

        站点过期时, 对方常返回 200 的「网站出售/维护/跳转」页, 既不含 CF
        挑战标记, 也不含本站特征 —— 这正是「卡片空白」最常见的静默根因。
        此方法用于把这类无效页识别出来, 触发过门刷新重试, 而不是静默返回空。
        """
        if not html:
            return False
        for sig in ('/movie/', 'item-cover', 'item-title', 'lay-src',
                    'player_aaaa', 'jisuimage', 'class="tag"', '荐片', '搜索'):
            if sig in html:
                return True
        return False

    @staticmethod
    def log(tag, msg):
        """诊断日志。TVBox 爬虫日志可见, 用于定位卡片空白属哪一类失败。"""
        try:
            print('[%s] jianpian_bypass: %s' % (tag, msg))
        except Exception:
            pass

    def _try_one(self, url, headers):
        """取一页: 先 TVBox fetch, 失败再用 requests.Session 兜底(verify 降级)。返回 text 或 ''。"""
        try:
            r = self.fetch(url, headers=headers, timeout=_REQUEST_TIMEOUT)
            t = r.text if hasattr(r, 'text') else ''
            if t:
                return t
        except Exception:
            pass
        session = self._get_session()
        if session:
            for verify in (True, False):
                try:
                    r = session.get(url, headers=headers, timeout=_REQUEST_TIMEOUT,
                                    allow_redirects=True, verify=verify)
                    if r.status_code == 200 and r.text:
                        return r.text
                except Exception:
                    continue
        return ''

    def _fetch_html(self, path, use_cache=False, _recursion=False):
        url = path if path.startswith('http') else self.host + path

        if use_cache and not _recursion:
            now = time.time()
            if self._home_html and (now - self._home_html_time) < _HOME_CACHE_TTL:
                return self._home_html

        got = ''  # 最后拿到的「非空但非本站」页(过期域名页/过门页), 用于诊断与刷新决策
        for ua in _UA_POOL:
            headers = dict(self.header)
            headers['User-Agent'] = ua
            headers['Referer'] = self.host + '/'

            text = self._try_one(url, headers)
            if not text:
                continue  # 连接失败/超时 -> 换 UA
            if self._is_cf_challenge(text):
                continue  # 风控挑战页 -> 换 UA
            if self._looks_like_site(text):
                # 真实站点页 -> 命中; 仅缓存有效页(绝不缓存无效页, 避免污染自愈)
                if use_cache:
                    self._home_html = text
                    self._home_html_time = time.time()
                return text
            got = text  # 非空但不像本站(过期域名页/过门页) -> 暂存, 继续试其他 UA

        # 所有 UA 都没拿到有效页 -> 很可能是域名过期/被墙, 过门刷新后重试一次
        if not _recursion and not path.startswith('http'):
            old = self.host
            self.refresh_domains()
            if self.host != old:
                return self._fetch_html(path, use_cache=use_cache, _recursion=True)
        return got  # 返回最后拿到的内容(可能为空), 由上层解析/诊断

    def _fix_url(self, url):
        if not url:
            return ''
        url = url.strip()
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.host + url
        return url

    # ============================================================
    #  卡片解析(双轨: 精确 + 宽松抗漂移)
    # ============================================================

    @staticmethod
    def _parse_cards(html):
        if not html:
            return []
        vod_list = []
        seen = set()

        # 1) 精确结构
        cards = re.findall(
            r'<div class="item-cover">\s*'
            r'<div class="pic">\s*'
            r'<a href="/movie/(\d+)\.html"></a>\s*'
            r'<img[^>]*lay-src="([^"]*)"[^>]*>\s*'
            r'</div>\s*'
            r'<div class="tag">([^<]*)</div>\s*'
            r'</div>\s*'
            r'<div class="item-title">\s*'
            r'<a href="/movie/\d+\.html">([^<]+)</a>',
            html, re.DOTALL
        )
        for vid, pic, remark, title in cards:
            if vid in seen:
                continue
            seen.add(vid)
            vod_list.append({
                'vod_id': vid,
                'vod_name': title.strip(),
                'vod_pic': pic.strip(),
                'vod_remarks': remark.strip(),
            })

        # 2) 宽松兜底: 任何 /movie/{id}.html 链接, 兼容 lay-src/data-src/src
        #    用"本卡附近(向前优先, 再向后)"的窄窗口, 避免抓到邻居卡的图/标题
        for mid in re.findall(r'href="/movie/(\d+)\.html"', html):
            if mid in seen:
                continue
            seen.add(mid)
            pos = html.find('/movie/%s.html' % mid)
            if pos < 0:
                continue
            after = html[pos: pos + 500]
            before = html[max(0, pos - 300): pos]
            pic_m = (re.search(r'data-src="([^"]+)"', after)
                     or re.search(r'lay-src="([^"]+)"', after)
                     or re.search(r'data-src="([^"]+)"', before)
                     or re.search(r'lay-src="([^"]+)"', before)
                     or re.search(r'src="([^"]+)"', after))
            title_m = (re.search(r'alt="([^"]+)"', after)
                       or re.search(r'alt="([^"]+)"', before)
                       or re.search(r'>([^<]{2,40})</a>', after)
                       or re.search(r'>([^<]{2,40})</a>', before))
            vod_list.append({
                'vod_id': mid,
                'vod_name': title_m.group(1).strip() if title_m else '',
                'vod_pic': pic_m.group(1).strip() if pic_m else '',
                'vod_remarks': '',
            })

        return vod_list

    # ============================================================
    #  首页 / 分类
    # ============================================================

    def homeContent(self, filter):
        result = {
            'class': [{'type_id': slug, 'type_name': name} for slug, name in self.categories],
            'filters': {},
        }
        try:
            html = self._fetch_html('/', use_cache=True)
        except Exception:
            html = ''
        cards = self._parse_cards(html)
        if not cards:
            # 自愈: 解析为空 -> 刷新过门域名再试一次(覆盖「拿到无效页但 host 解析失败」的残局)
            self.log('WARN', 'homeContent 卡片为空, 触发 refresh_domains 自愈; host=%s' % self.host)
            self.refresh_domains()
            html = self._fetch_html('/')
            cards = self._parse_cards(html)
            if not cards:
                if not html:
                    self.log('WARN', '卡片空白根因=网络层失败(过门/域名过期/被风控); 请查 gate_domains 与入口域名')
                else:
                    self.log('WARN', '卡片空白根因=解析层失败(站点DOM漂移/改版); _parse_cards 未命中, 检查 HTML 结构')
        result['list'] = cards
        return result

    def homeVideoContent(self):
        try:
            html = self._fetch_html('/', use_cache=True)
            return {'list': self._parse_cards(html)}
        except Exception:
            return {'list': []}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            pg = int(pg) if pg else 1
            path = '/list/%s.html' % tid if pg <= 1 else '/list/%s-%d.html' % (tid, pg)
            html = self._fetch_html(path)
            videos = self._parse_cards(html)
            if not videos:
                self.log('WARN', 'categoryContent[%s] 卡片为空, 触发 refresh_domains 自愈; host=%s' % (tid, self.host))
                self.refresh_domains()
                html = self._fetch_html(path)
                videos = self._parse_cards(html)
            pagecount = 1
            if html:
                nums = re.findall(r'/list/%s-(\d+)\.html' % re.escape(tid), html)
                if nums:
                    pagecount = max(int(p) for p in nums)
                if not pagecount and videos:
                    pagecount = pg
            return {'page': pg, 'pagecount': pagecount, 'limit': len(videos),
                    'total': pagecount * 20, 'list': videos}
        except Exception:
            return {'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0, 'list': []}

    # ============================================================
    #  详情
    # ============================================================

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, list) else str(ids)
            html = self._fetch_html('/movie/%s.html' % vid)
            if not html:
                return {'list': []}

            # 标题
            title = ''
            m = re.search(r'<title>([^<]+)</title>', html)
            if m:
                raw = m.group(1)
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

            # 封面
            pic = ''
            lazy = re.findall(r'(?:lay-src|data-src|src)="([^"]*)"', html)
            for i in lazy:
                if 'cover' in i or 'jisuimage' in i:
                    pic = i
                    break
            if not pic and lazy:
                pic = lazy[0]
            pic = self._fix_url(pic)

            # 简介
            desc = ''
            m = re.search(r'class="info-desc">([^<]*(?:<[^>]*>[^<]*)*)</div>', html, re.DOTALL)
            if m:
                desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                desc = re.sub(r'^[简介：:]+', '', desc).strip()
            if not desc:
                m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
                if m:
                    desc = re.sub(r'^.*?剧情简介[：:]', '', m.group(1)).strip()

            # 年份/地区/类型/演员/导演
            year = area = type_ = actor = director = ''
            for label, value in re.findall(
                r'class="info-label">([^<]+)</span>\s*<span\s+class="info-text">([^<]*)</span>', html
            ):
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
            if not year:
                ym = re.search(r'(\d{4})', desc or html[:5000])
                if ym:
                    year = ym.group(1)

            # 选集链接: /play/{vid}-{src}-{ep}.html
            plays = re.findall(
                r'href="/play/%s-(\d+)-(\d+)\.html"[^>]*>([^<]+)<' % re.escape(vid), html
            )
            if not plays:
                plays = [('1', '1', '点击播放')]

            sources = {}
            for src_id, ep_id, ep_name in plays:
                sources.setdefault(src_id, []).append((ep_id, ep_name))

            sorted_srcs = sorted(sources.keys(), key=lambda x: int(x) if x.isdigit() else 0)
            src_names = {}
            h2s = re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL)
            for i, h in enumerate(h2s):
                name = re.sub(r'<[^>]+>', '', h).strip()
                if name and i < len(sorted_srcs):
                    src_names[sorted_srcs[i]] = name
            if not src_names and sorted_srcs:
                src_names[sorted_srcs[0]] = '荐片专线'

            play_from_parts = []
            play_url_parts = []
            for idx, src_id in enumerate(sorted_srcs):
                sname = src_names.get(src_id, '线路%d' % (idx + 1))
                play_from_parts.append(sname)
                ep_list = []
                for ep_id, ep_name in sources[src_id]:
                    ep_name = ep_name.strip() if ep_name.strip() else '第%s集' % ep_id
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
    #  搜索
    # ============================================================

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg) if pg else 1
            from urllib.parse import quote as _q
            path = '/search.html?wd=%s' % _q(key)
            if pg > 1:
                path += '&page=%d' % pg
            html = self._fetch_html(path)
            videos = self._parse_cards(html)
            if not videos:
                self.log('WARN', 'searchContent[%s] 卡片为空, 触发 refresh_domains 自愈; host=%s' % (key, self.host))
                self.refresh_domains()
                html = self._fetch_html(path)
                videos = self._parse_cards(html)
            return {'page': pg, 'list': videos}
        except Exception:
            return {'page': 1, 'list': []}

    def searchContentPage(self, key, quick, pg=1):
        return self.searchContent(key, quick, pg)

    # ============================================================
    #  播放解码(player_aaaa + encrypt 0/1/2)
    # ============================================================

    @staticmethod
    def _decode_player(obj, host):
        enc = obj.get('encrypt', 0)
        url = obj.get('url', '')
        try:
            if enc == 2:
                url = _unquote(base64.b64decode(url).decode('utf-8'))
            elif enc == 1:
                url = _unquote(url)
        except Exception:
            pass
        if url.startswith('/'):
            url = host.rstrip('/') + url
        return url

    def playerContent(self, flag, id, vipFlags):
        try:
            url = id if id.startswith('http') else (self.host + id if id.startswith('/') else self.host + '/' + id)

            cache_key = url
            now = time.time()
            cached = self._play_cache.get(cache_key)
            if cached and (now - cached['time']) < _PLAY_CACHE_TTL:
                return self._ok(cached['url'], flag)

            html = self._fetch_html(url)
            play_url = ''

            # player_aaaa JSON
            if html:
                idx = html.find('player_aaaa')
                if idx >= 0:
                    brace = html.find('{', idx)
                    if brace >= 0:
                        try:
                            from json.decoder import JSONDecoder
                            obj, _ = JSONDecoder().raw_decode(html[brace:])
                            play_url = self._decode_player(obj, self.host)
                        except Exception:
                            pass

            # 兜底: 直接搜 m3u8 / mp4
            if not play_url:
                m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
                if m:
                    play_url = m.group(0)
            if not play_url:
                m = re.search(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', html)
                if m:
                    play_url = m.group(0)

            if play_url:
                self._play_cache[cache_key] = {'url': play_url, 'time': now}
                return self._ok(play_url, flag)

            return {'parse': 1, 'playUrl': '', 'url': url,
                    'header': json.dumps({'User-Agent': self.header['User-Agent'], 'Referer': self.host}),
                    'from': flag}
        except Exception:
            return {'parse': 1, 'playUrl': '', 'url': '',
                    'header': json.dumps({'User-Agent': self.header['User-Agent']}), 'from': flag}

    def _ok(self, url, flag):
        return {
            'parse': 0,
            'playUrl': '',
            'url': url,
            'header': json.dumps({'User-Agent': self.header['User-Agent'], 'Referer': self.host}),
            'from': flag,
        }


if __name__ == '__main__':
    s = Spider()
    s.init('')
    print('host =', s.host)
    print('home =', len(s.homeContent(False).get('list', [])), 'cards')
