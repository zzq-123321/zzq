# -*- coding: utf-8 -*-
"""
蓝光网 (languangwang.com) Python Spider —— 兼容 FongMi/TV (T3) 与 PyramidStore/WebHomeTV (T4)

============================================================================
实测结论 (2026-09-15 沙箱实拉 + 反爬定位)
============================================================================
1. 站点情况
   - 苹果CMS(maccms) 模板站, 路由: 详情 /hd/{id}/ , 分类 /dvd/{tid}/ , 分页 /dvd/{tid}-{pg}/
   - 播放源 NOT 在详情页内联, 而是详情页列出每个选集的「播放页」链接:
        /bd/{vid}-{sid}-{nid}/
     其中 vid=影片ID, sid=线路序号, nid=选集序号 (例: /bd/46601-1-1/ = 第1线路第1集)
   - 播放页 /bd/ 内部加载外部播放器链: /bd.js -> js.777yhdm.com/g.js
     -> hd.gkkqkq.com/d/ds-545.js -> v-545.js, 最终 m3u8 由客户端 JS(带生成的
     cookie/token) 解析。因此纯服务端无法拿到直链, 必须交给设备 WebView 解析。

2. 反爬机制 (两层)
   - Layer A (头部校验): 动态页(详情/分类)若缺少浏览器客户端提示头
     (sec-ch-ua / sec-ch-ua-platform / sec-fetch-* / upgrade-insecure-requests),
     服务端返回 *伪造* 的 Cloudflare "error code: 520" 文本页
     (body 16字节, content-type:text/plain, set-cookie: cf_use_ob=0)。
     => 绕过: 每次请求带上完整 Chrome 头即可 200。
   - Layer B (路径规则): /bd/ /vodsearch/ /index.php/api/ 被 WAF 路径规则
     *硬性* 拦截(即便带齐 Chrome 头仍 520), 且播放页取流需客户端 JS token,
     故播放页只能交给设备端 WebView(parse:1) 解析。

3. 绕过方案 (已封装)
   - 所有请求统一走 _chrome_headers() 完整 Chrome 头 -> 解决 Layer A。
   - detailContent 解析详情页的播放面板(<div class="panel-hd"><h3>线路</h3>
     + <ul class="skin-playlist playlist">) 提取真实 /bd/ 路径作为 vod_play_url。
   - playerContent 先尝试服务端取 m3u8, 失败则 parse:1 回传 /bd/ URL 让 WebView 解析。

注意: 分类/首页 始终 200; 搜索 /vodsearch/ 受 Layer B 拦截, 此处保留实现但可能空返回。
============================================================================
"""
import sys
import re
import json
import urllib.parse

sys.path.append('..')

# ===== 兼容导入 =====
try:
    from base.spider import Spider
except ImportError:
    import requests as rq
    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r


class Spider(Spider):

    SITE = "https://www.languangwang.com"
    # 分类 (实测从首页导航提取, 兜底硬编码)
    DEFAULT_CATS = [
        {"type_id": "1", "type_name": "电影"},
        {"type_id": "2", "type_name": "电视剧"},
        {"type_id": "3", "type_name": "综艺"},
        {"type_id": "4", "type_name": "动漫"},
    ]

    def getName(self):
        return "蓝光网"

    def init(self, extend=""):
        # 完整 Chrome 请求头 —— 绕过 Layer A 伪造 520 的核心
        self._hdr_cache = self._chrome_headers()
        # 缓存分类 (从首页导航取, 失败用兜底)
        self._cats = self.DEFAULT_CATS
        try:
            html = self._get(self.SITE + '/')
            cats = self._parse_categories(html)
            if cats:
                self._cats = cats
        except Exception:
            pass

    # ========== 工具 ==========
    def _chrome_headers(self, referer=None):
        """完整 Chrome 头, 绕过 Cloudflare/Layer-A 伪造 520。"""
        h = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,'
                      'image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'sec-ch-ua': '"Chromium";v="120", "Google Chrome";v="120", "Not?A_Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
        }
        if referer:
            h['Referer'] = referer
            h['sec-fetch-site'] = 'same-origin'
        return h

    def _get(self, url, referer=None, timeout=20, retries=3):
        """fetch 封装: 返回解码后的文本; 失败返回空串。统一带 Chrome 头绕过 Layer-A 伪造 520。
        含重试+退避: Cloudflare 对连续快速请求会限流(偶发 000/520), 重试可稳定命中。"""
        import time
        last = ""
        for attempt in range(retries):
            try:
                r = self.fetch(url, headers=self._chrome_headers(referer), timeout=timeout)
                if r and r.status_code == 200:
                    return r.text
                last = f"HTTP {getattr(r, 'status_code', '?')}" if r else "no-response"
            except Exception as e:
                last = f"exc:{e}"
            # 指数退避 + 抖动, 避免触发限流
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1) + (attempt * 0.3))
        return ""

    @staticmethod
    def _strip(s):
        return re.sub(r'\s+', ' ', (s or '')).strip()

    def _parse_categories(self, html):
        """从首页导航提取 /dvd/{tid}/ 分类"""
        out = []
        seen = set()
        for tid, name in re.findall(r'<a[^>]*href="/dvd/(\d+)/"[^>]*>([^<]+)</a>', html):
            name = self._strip(name)
            if tid not in seen and name:
                seen.add(tid)
                out.append({"type_id": tid, "type_name": name})
        return out

    def _parse_cards(self, html):
        """解析列表卡片 (首页/分类/搜索通用)"""
        out = []
        seen = set()
        for blk in re.finditer(r'<li class="col">(.*?)</li>', html, re.S):
            b = blk.group(1)
            a = re.search(r'<a class="cover-img" href="/hd/(\d+)/"[^>]*title="([^"]*)"', b)
            if not a:
                continue
            vid = a.group(1)
            name = self._strip(a.group(2))
            if not name or vid in seen:
                continue
            seen.add(vid)
            img = re.search(r'data-original="([^"]+)"', b)
            pic = img.group(1) if img else ""
            rm = re.search(r'class="pic-text[^"]*">([^<]+)<', b)
            remarks = self._strip(rm.group(1)) if rm else ""
            out.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remarks,
            })
        return out

    # ========== 首页 ==========
    def homeContent(self, filter):
        return {'class': self._cats}

    def homeVideoContent(self):
        html = self._get(self.SITE + '/')
        return {'list': self._parse_cards(html)}

    # ========== 分类列表 ==========
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        # 第1页用 /dvd/{tid}/, 其余 /dvd/{tid}-{pg}/
        url = self.SITE + (f"/dvd/{tid}/" if pg <= 1 else f"/dvd/{tid}-{pg}/")
        html = self._get(url)
        videos = self._parse_cards(html)

        # 尝试从页面提取总页数
        page_count = 1
        m = re.search(r'href="/dvd/%s-(\d+)/"[^>]*class="last"' % tid, html)
        if m:
            page_count = int(m.group(1))
        else:
            nums = [int(x) for x in re.findall(r'href="/dvd/%s-(\d+)/"' % tid, html)]
            if nums:
                page_count = max(nums)

        return {
            'list': videos,
            'page': pg,
            'pagecount': page_count,
            'limit': 72,
            'total': page_count * 72,
        }

    # ========== 详情 / 播放 ==========
    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = ids[0]

        vod = {
            'vod_id': vod_id,
            'vod_name': '',
            'vod_pic': '',
            'type_name': '',
            'vod_year': '',
            'vod_area': '',
            'vod_remarks': '',
            'vod_actor': '',
            'vod_director': '',
            'vod_content': '',
            'vod_play_from': '',
            'vod_play_url': '',
        }

        html = self._get(self.SITE + f"/hd/{vod_id}/")
        if not html:
            # Layer A 未绕过 / 网络失败: 返回空列表 (播放不可用)
            return {'list': [vod]}

        # --- 基础信息 ---
        t = re.search(r'<title>(.*?)</title>', html, re.S)
        if t:
            title = self._strip(t.group(1).split('-')[0])
            vod['vod_name'] = title
        m = re.search(r'<meta name="description" content="([^"]*)"', html)
        if m:
            vod['vod_content'] = self._strip(m.group(1))
        img = re.search(r'<img[^>]*data-original="([^"]+)"[^>]*class="[^"]*lazyload[^"]*"', html)
        if not img:
            img = re.search(r'<div class="detail-pic[^"]*">\s*<img[^>]*src="([^"]+)"', html)
        if img:
            vod['vod_pic'] = img.group(1)
        # 年份/地区/备注
        for label, key in (('年份', 'vod_year'), ('地区', 'vod_area'), ('类型', 'type_name')):
            mm = re.search(r'%s[:：]\s*<[^>]*>([^<]+)</' % label, html)
            if mm:
                vod[key] = self._strip(mm.group(1))

        # --- 解析真实播放源: 每个 <div class="panel"> 一个线路 ---
        # 结构: <div class="panel-hd"><h3>线路名</h3></div>
        #       <div class="panel-bd"><ul class="skin-playlist playlist">
        #         <li><a href="javascript:;" onclick="location.replace('/bd/{vid}-{sid}-{nid}/')" title="第01集">第01集</a></li>
        #       </ul></div>
        play_from_list = []
        play_url_list = []
        cur_from = '默认线路'
        for chunk in re.split(r'(<div class="panel-hd"><h3>.*?</h3></div>)', html):
            fm = re.search(r'<div class="panel-hd"><h3>(.*?)</h3></div>', chunk)
            if fm:
                cur_from = self._strip(fm.group(1)) or cur_from
                continue
            ul = re.search(r'<ul class="skin-playlist playlist">(.*?)</ul>', chunk, re.S)
            if not ul:
                continue
            eps = {}
            for a in re.finditer(
                r'<a[^>]*?(?:href="(/bd/[0-9-]+/)"|onclick="location\.replace\(.(/bd/[0-9-]+/).\))'
                r'[^>]*>(.*?)</a>', ul.group(1), re.S):
                url = a.group(1) or a.group(2)
                name = self._strip(a.group(3)) or '正片'
                if url:
                    eps[name] = self.SITE + url
            if eps:
                play_from_list.append(cur_from)
                play_url_list.append('$$$'.join(f"{k}${v}" for k, v in eps.items()))
        # 兜底: 若面板解析失败, 全页扫描 /bd/ 链接按出现顺序拼成单线路
        if not play_from_list:
            links = []
            seen = set()
            for u in re.findall(r'(?:href|onclick="location\.replace\()["\']?(/bd/[0-9-]+/)', html):
                if u not in seen:
                    seen.add(u)
                    links.append('正片$' + self.SITE + u)
            if links:
                play_from_list.append('默认线路')
                play_url_list.append('$$$'.join(links))

        if play_from_list:
            vod['vod_play_from'] = '$$$'.join(play_from_list)
            vod['vod_play_url'] = '$$$'.join(play_url_list)

        return {'list': [vod]}

    # ========== 搜索 ==========
    # 注意: /vodsearch/ 受 Layer B(WAF 路径规则) 拦截, 可能稳定 520。
    # 此处按 maccms 路由实现, 能通则通, 不通返回空。
    def searchContent(self, key, quick, pg="1"):
        pg = int(pg or 1)
        path = f"/vodsearch/{urllib.parse.quote(key)}-------------/" if pg <= 1 \
            else f"/vodsearch/{urllib.parse.quote(key)}-------------/{pg}/"
        html = self._get(self.SITE + path)
        videos = self._parse_cards(html) if html else []
        return {
            'list': videos,
            'page': pg,
            'pagecount': 1,
            'limit': 72,
            'total': len(videos),
        }

    # ========== 播放解析 ==========
    def playerContent(self, flag, id, vipFlags):
        # id 可能是直接 m3u8, 也可能是 /bd/ 播放页
        if id.startswith('http') and '.m3u8' in id:
            return {
                'parse': 0, 'playUrl': '', 'url': id,
                'header': self._chrome_headers(),
                'format': 'application/x-mpegURL',
                'contentType': 'application/x-mpegURL',
            }
        if id.startswith('http'):
            # 尝试服务端直接取 m3u8 (若 WAF 放行 /bd/ 的成功情形)
            ph = self._get(id, referer=self.SITE + '/')
            if ph:
                m3 = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', ph)
                if not m3:
                    jm = re.search(r'["\']url["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']', ph)
                    if jm:
                        m3 = jm
                if m3:
                    return {
                        'parse': 0, 'playUrl': '', 'url': m3.group(1),
                        'header': self._chrome_headers(),
                        'format': 'application/x-mpegURL',
                        'contentType': 'application/x-mpegURL',
                    }
        # 兜底: /bd/ 播放页需客户端 JS / WebView 解析 (标准 player-page 处理)
        return {
            'parse': 1,
            'playUrl': '',
            'url': id,
            'header': self._chrome_headers(referer=self.SITE + '/'),
            'format': 'text/html',
        }

    # ========== 清理 ==========
    def destroy(self):
        pass

    def close(self):
        self.destroy()


# ========== 独立自测 (沙箱/本地可直接 python3 languangwang.py 运行) ==========
if __name__ == '__main__':
    import traceback

    def banner(t):
        print("\n" + "=" * 60 + f"\n  {t}\n" + "=" * 60)

    sp = Spider()
    sp.init()
    ok = True

    # 1) 首页分类
    banner("1) homeContent (分类)")
    hc = sp.homeContent(False)
    print("class:", hc.get('class'))
    assert hc.get('class'), "分类为空"
    print("OK 分类数:", len(hc['class']))

    # 2) 分类列表
    banner("2) categoryContent (电影第1页)")
    cc = sp.categoryContent('1', 1, False, {})
    print("list 数:", len(cc['list']), " pagecount:", cc['pagecount'])
    assert cc['list'], "列表为空"
    print("首条:", cc['list'][0])
    print("OK 列表非空")

    # 3) 详情 + 真实播放源
    banner("3) detailContent (取列表首条详情)")
    vid = cc['list'][0]['vod_id']
    print("目标 vod_id:", vid)
    dc = sp.detailContent([vid])
    v = dc['list'][0]
    print("片名:", v.get('vod_name'))
    print("播放线路 vod_play_from:", v.get('vod_play_from'))
    print("播放串 vod_play_url (前200):", (v.get('vod_play_url') or '')[:200])
    assert v.get('vod_name'), "详情片名为空"
    assert v.get('vod_play_from'), "未解析出播放线路"
    assert v.get('vod_play_url'), "未解析出播放地址(真实 /bd/ 路径)"
    # 校验播放串确为 /bd/ 真实路径
    assert '/bd/' in v.get('vod_play_url', ''), "播放串未包含真实 /bd/ 路径"
    print("OK 已定位真实播放路径 /bd/{vid}-{sid}-{nid}/")

    # 4) playerContent (WebView 解析策略)
    banner("4) playerContent (播放解析)")
    first_url = v['vod_play_url'].split('$$$')[0].split('$')[-1]
    pc = sp.playerContent('', first_url, '')
    print("parse:", pc.get('parse'), "url:", pc.get('url'))
    assert pc.get('url'), "playerContent 未返回 url"
    print("OK playerContent 返回可解析地址")

    banner("自测全部通过 ✅")
    print("播放源定位: /bd/{vid}-{sid}-{nid}/  | 反爬绕过: 完整 Chrome 头化解 Layer-A 伪造520")
