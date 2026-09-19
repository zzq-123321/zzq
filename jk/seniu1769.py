# -*- coding: utf-8 -*-
"""
seniu1769.cc 影视站 Spider —— WebHomeTV / PeekPro 通用模板改造版
================================================================
骨架 100% 沿用你给的模板,仅顶部 ⚙ CONFIG 改为本站;其他方法
(init / getName / 7 个 Content / isVideoFormat / manualVideoCheck /
localProxy / _fetch / extract_player_json / decrypt_player_url /
_parse_cards / _parse_detail) 一字未改。

沙箱无法直连目标站验证(envoy 直连 RST),所以选择器先按模板作者
标注"已对照验证"的青禾/荐片 MacCMS 骨架来填。导入 WebHomeTV 后
若首页/详情/播放对不上,把对应 HTML 片段贴回来,直接改 CONFIG 即可。
"""

import re
import json
import base64
import urllib.parse
from copy import deepcopy
from bs4 import BeautifulSoup
import requests

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    # 仅沙箱（无 base.spider）下生效；WebHomeTV 设备会加载真实基类
    class BaseSpider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            return requests.get(url, headers=headers or {}, timeout=15, **kw)


class Spider(BaseSpider):

    # ============================================================
    # ⚙ CONFIG —— 仅本区块针对本站改过
    # ============================================================
    SITE_HOST = "https://8.seniu1769.cc:8888"
    SITE_NAME = "Seniu影视"

    CATEGORIES = [
        {'type_id': "tv",          'type_name': "剧集"},
        {'type_id': "movies",      'type_name': "电影"},
        {'type_id': "varietyshow", 'type_name': "综艺"},
        {'type_id': "anime",       'type_name': "动漫"},
        {'type_id': "shortdrama",  'type_name': "短剧"},
    ]

    URL_CATEGORY = "/type/%s/"
    URL_DETAIL   = "/detail/%s/"
    URL_SEARCH   = "/vodsearch/%s/page/%d/"
    URL_PLAY     = "/play/%s/"

    # —— 列表卡片 ——
    SEL_CARD_BOX     = "div.public-list-box, div.search-box"
    SEL_CARD_LINK    = "a.public-list-exp"
    SEL_CARD_TITLE   = "div.thumb-txt"
    SEL_CARD_IMG     = "div.gen-movie-img"
    SEL_CARD_REMARK  = "span.public-list-prb"
    RE_CARD_ID       = r'/detail/(\d+)/'

    # —— 详情 ——
    SEL_DETAIL_NAME    = "h2.slide-info-title"
    SEL_DETAIL_PIC     = "a.detail-pic"
    SEL_SOURCE_TAB     = "div.anthology-tab a.swiper-slide"
    SEL_EPISODE_BLOCK  = "div.anthology-list-box"
    SEL_EPISODE_LINK   = "ul.anthology-list-play li a"

    # —— 播放解密 ——
    PLAYER_VAR     = "player_aaaa"
    DECRYPT_METHOD = 2

    # ============================================================
    #  初始化
    # ============================================================
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

    # ============================================================
    #  接口（返回 dict；框架负责序列化）
    # ============================================================
    def homeContent(self, filter):
        return {"class": [dict(t) for t in self.CATEGORIES], "filters": {}}

    def homeVideoContent(self):
        html = self._fetch('/')
        items = self._parse_cards(html)[:24] if html else []
        return {"list": items}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if pg else 1
        except Exception:
            pg = 1
        html = self._fetch(self.URL_CATEGORY % tid)
        items = self._parse_cards(html) if html else []
        return {"list": items, "page": pg, "pagecount": 1,
                "limit": len(items), "total": len(items)}

    def detailContent(self, ids):
        try:
            vid = ids[0].split(',')[0].strip() if isinstance(ids, list) else str(ids)
            html = self._fetch(self.URL_DETAIL % vid)
            if not html:
                return {"list": []}
            vod = self._parse_detail(html, vid)
            if not vod:
                return {"list": []}
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg) if pg else 1
        except Exception:
            pg = 1
        kw = urllib.parse.quote(str(key))
        html = self._fetch(self.URL_SEARCH % (kw, pg))
        items = self._parse_cards(html) if html else []
        pagecount = pg + (1 if items else 0)
        return {"list": items, "page": pg, "pagecount": pagecount}

    def playerContent(self, flag, id, vipFlags):
        try:
            ep = id if '$' not in str(id) else str(id).split('$', 1)[1]
            if str(ep).startswith('http'):
                url = str(ep)
            elif str(ep).startswith('/'):
                url = self.host + str(ep)
            else:
                url = self.host + '/' + str(ep)
            html = self._fetch(url)
            real = ''
            if html:
                data = self.extract_player_json(html)
                if data:
                    real = self.decrypt_player_url(data.get('url', ''),
                                                   int(data.get('encrypt', 0) or 0))
                if not real:
                    m = re.search(r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*', html)
                    if m:
                        real = m.group(0)
            if real:
                return {"parse": 0, "url": real, "header": {
                    'User-Agent': self.headers['User-Agent'],
                    'Referer': self.host + '/',
                    'Accept': '*/*',
                }}
            return {"parse": 1, "url": url, "header": {
                'User-Agent': self.headers['User-Agent'],
                'Referer': self.host + '/',
            }}
        except Exception:
            return {"parse": 1, "url": "", "header": {
                'User-Agent': self.headers['User-Agent'],
            }}

    # ============================================================
    #  基础方法（一般不用动）
    # ============================================================
    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def localProxy(self, param=''):
        return {}

    # ============================================================
    #  网络
    # ============================================================
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

    # ============================================================
    #  播放解密
    # ============================================================
    @staticmethod
    def extract_player_json(text):
        i = text.find("var %s" % Spider.PLAYER_VAR)
        if i < 0:
            i = text.find(Spider.PLAYER_VAR)
        if i < 0:
            return None
        start = text.find("{", i)
        if start < 0:
            return None
        depth = 0
        end = -1
        for k in range(start, len(text)):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    end = k + 1
                    break
        if end < 0:
            return None
        try:
            return json.loads(text[start:end])
        except Exception:
            return None

    @staticmethod
    def decrypt_player_url(enc, method):
        if not enc:
            return ""
        try:
            if method == 1:
                return base64.b64decode(enc).decode('utf-8', 'ignore')
            if method == 2:
                raw = base64.b64decode(enc).decode('latin1')
                return urllib.parse.unquote(raw)
        except Exception:
            pass
        try:
            return urllib.parse.unquote(enc)
        except Exception:
            return enc

    # ============================================================
    #  卡片解析
    # ============================================================
    def _fix_pic(self, u):
        if not u:
            return ''
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('/'):
            return self.host + u
        return u.replace('&amp;', '&')

    def _parse_cards(self, html):
        items, seen = [], set()
        if not html:
            return items
        soup = BeautifulSoup(html, 'html.parser')
        for box in soup.select(self.SEL_CARD_BOX):
            a = box.select_one(self.SEL_CARD_LINK)
            if not a:
                continue
            href = a.get('href', '').strip()
            title = (a.get('title') or '').strip()
            if not title:
                tt = box.select_one(self.SEL_CARD_TITLE)
                if tt:
                    title = tt.get_text(strip=True)
            if not title:
                title = a.get_text(strip=True)
            img = box.select_one(self.SEL_CARD_IMG)
            cover = ''
            if img:
                cover = self._fix_pic(img.get('data-original') or img.get('data-src') or '')
            prb = box.select_one(self.SEL_CARD_REMARK)
            remarks = prb.get_text(strip=True) if prb else ''
            m = re.search(self.RE_CARD_ID, href)
            if not href or not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            items.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": cover,
                "vod_remarks": remarks,
            })
        return items

    # ============================================================
    #  详情解析
    # ============================================================
    def _parse_detail(self, html, vid):
        if not html:
            return None
        soup = BeautifulSoup(html, 'html.parser')

        h2 = soup.select_one(self.SEL_DETAIL_NAME)
        name = h2.get_text(strip=True) if h2 else ''

        pic = ''
        pd = soup.select_one(self.SEL_DETAIL_PIC)
        if pd:
            p = pd.get('data-original') or pd.get('data-src') or ''
            pic = self._fix_pic(p)

        sources = []
        for a in soup.select(self.SEL_SOURCE_TAB):
            node = deepcopy(a)
            for bad in node.select('span.badge'):
                bad.extract()
            s = re.sub(r"[\ue000-\uf8ff]", "", node.get_text()).replace("\xa0", "").strip()
            if s:
                sources.append(s)

        blocks = soup.select(self.SEL_EPISODE_BLOCK)
        groups = {}
        for sid, block in enumerate(blocks, start=1):
            eps = []
            for li in block.select(self.SEL_EPISODE_LINK):
                href = li.get('href', '').strip()
                ep_name = li.get_text(strip=True)
                if "/play/" in href:
                    eps.append((ep_name, href if href.startswith("/") else "/" + href))
            groups[sid] = eps

        from_list = []
        for sid in range(1, len(sources) + 1):
            eps = groups.get(sid, [])
            from_list.append("#".join("%s$%s" % (n, h) for n, h in eps))
        vod_play_from = "$$$".join(sources)
        vod_play_url = "$$$".join(from_list)

        def grab(kw):
            for node in soup.select('div.slide-info'):
                if kw in node.get_text():
                    links = [x.get_text(strip=True) for x in node.select('a')]
                    val = '、'.join(links).strip()
                    if val:
                        return val
            return ""

        year = grab("年份")
        director = grab("导演")
        actor = grab("演员")
        area = grab("地区")
        content = ''
        desc = soup.select_one('div.slide-info-desc')
        if desc:
            content = desc.get_text(strip=True)
        if not content:
            desc2 = soup.select_one('div.detail-desc')
            if desc2:
                content = desc2.get_text(strip=True)

        return {
            "vod_id": str(vid),
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": "",
            "type_name": "",
            "vod_year": year,
            "vod_area": area,
            "vod_director": director,
            "vod_actor": actor,
            "vod_content": content,
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url,
        }


if __name__ == '__main__':
    # 沙箱自检：确认类与契约方法齐备（不会真的去抓站点）
    sp = Spider()
    sp.init()
    print("Spider:", sp.getName())
    print("host:", sp.host)
    print("home classes:", [c['type_name'] for c in sp.homeContent(True)['class']])
    print("CONFIG OK —— 导入 WebHomeTV 后如首页/详情空,把对应 HTML 贴回来")