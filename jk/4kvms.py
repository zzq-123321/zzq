# -*- coding: utf-8 -*-
"""
4kvms.com — WebHomeTV / PeekPro Python Spider (Chaquopy)
================================================================
站点特征（与 MacCMS 不同，需定制解析，但沿用 WebHomeTV 契约）:
  - 自建 Tailwind 框架；路由: /movie /tv /anime 分类, /play/{hash} 单集播放页
  - 每集独立 hash；选集列在播放页的 a.episode-link（text=集数, href=/play/{hash2}）
  - 播放地址由 WASM (nbmovie_wasm) 签名生成 /video/play?p=&v=&q=&s=&t=&k= 再 fetch
  - 站点有 WAF/TLS 指纹防护: 非真实浏览器(纯 curl/node/python) 一律 401 拿不到 m3u8
  => playerContent 用 parse:1 返回播放页 URL, 由 App 内置 webview(真实浏览器内核)
     过 WAF 并跑 wasm 播放, 与官网网页一致。

  画质(4K)方案(已扒打包 JS 验证):
  - 初始画质 = localStorage['artplayer_settings'].quality, 默认 '1080'; 4K 对应 '1'
  - 打包 JS 无任何 location.search / URLSearchParams 读取 => 不支持 URL 参数强制画质
  - build_play_url(dataid, secretKey, quality, playKey) 由 WASM 现场签名, quality 透传
  - 因此 4kvms 无独立画质直链, 所有画质共用同一播放页 /play/{hash}
  - 4K 由 App 端 WebHome 扩展(匹配本站点 key, runAt=document-start)在播放页加载前
    把 localStorage['artplayer_settings'].quality 钉成 '1' 实现; spider 侧无需 inject
  - 扩展配置见 4kvms_force4k_extension.json(在 App "增强功能→站点注入→WebHome 扩展"添加)

WebHomeTV 契约（已对齐可用样本，勿改）:
  ✓ class Spider(base.spider.Spider), 实例方法
  ✓ 解析只用 BeautifulSoup(html.parser) + requests
  ✓ 接口返回 dict（框架序列化）
  ✓ playerContent.header 为 dict
"""
import re
import json
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

    # 4K 画质由 App 端 WebHome 扩展负责(见 4kvms_force4k_extension.json),
    # 此处 spider 不再注入; 播放页统一 parse:1 交给 webview。

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
        from urllib.parse import quote
        html = self._fetch(self.URL_SEARCH % quote(str(key)))
        items = self._parse_cards(html) if html else []
        return {"list": items, "page": pg, "pagecount": 1 if items else 0}

    def playerContent(self, flag, id, vipFlags):
        # id 形如 "/play/{hash2}" 或 "第N集$/play/{hash2}"
        try:
            ep = id if '$' not in str(id) else str(id).split('$', 1)[1]
            if str(ep).startswith('http'):
                url = str(ep)
            elif str(ep).startswith('/'):
                url = self.host + str(ep)
            else:
                url = self.host + '/' + str(ep)
        except Exception:
            url = ''
        # 站点 WAF + wasm 签名: 只能交给 App 内置 webview 加载播放页来播。
        # 4K 画质由 App 端 WebHome 扩展(匹配本站点 key)在播放页加载前把
        # localStorage['artplayer_settings'].quality 钉成 '1' 实现, 不依赖 spider 注入字段。
        return {"parse": 1, "url": url, "header": {
            'User-Agent': self.headers['User-Agent'],
            'Referer': self.host + '/',
        }}

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
    def _parse_detail(self, html, vid):
        if not html:
            return None
        soup = BeautifulSoup(html, 'html.parser')

        # 片名: <title> 形如 "凡人修仙传 - 第1集 -4k影视" -> 取首个 ' - ' 之前
        name = ''
        if soup.title:
            name = soup.title.get_text().split(' - ')[0].strip()

        # 封面: og:image
        pic = ''
        og = soup.find('meta', attrs={'property': 'og:image'})
        if og:
            pic = self._fix_pic(og.get('content', ''))

        # 选集: a.episode-link (text=集数, href=/play/{hash2})
        eps = []
        for a in soup.select('a.episode-link'):
            href = a.get('href', '').strip()
            if '/play/' not in href:
                continue
            ep_name = a.get_text(strip=True) or str(len(eps) + 1)
            eps.append((ep_name, href if href.startswith('/') else '/' + href))

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
        }


if __name__ == '__main__':
    sp = Spider()
    sp.init()
    print("Spider:", sp.getName())
    print("home:", [c['type_name'] for c in sp.homeContent(True)['class']])
    print("4kvms spider 自检 OK")
