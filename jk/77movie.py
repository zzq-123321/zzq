# -*- coding: utf-8 -*-
"""
66大片网 Python Spider (https://www.77dpw.vip/)
兼容 FongMi/TV (T3) 和 WebHomeTV/PeekPro (T4)

站点结构（实测 2026-08-20）：
- 苹果 CMS HTML 模板（mxpro，module-* 前缀），API 已关闭
- 分类页: /vodtype/{tid}.html  / /vodtype/{tid}-{pg}.html （可正常访问）
- 详情页: /voddetail/{id}.html    （可正常访问）
- 播放页: /vodplay/{id}-{sid}-{eid}.html （可正常访问，含 player_aaaa 变量）
- 搜索页: /index.php?m=vod-search-wd-{keyword} （vodsearch/ 路径 404）
- 分类: 1=电影 2=动漫 3=剧集 4=短剧 5=综艺

HTML 结构（module-* 模板，实测）：
- 视频卡片: <a href="/voddetail/xxx.html" title="标题" class="module-poster-item module-item">
    - 封面: <img data-original="URL">
    - 备注: <div class="module-item-note">备注</div>
    - 标题: <div class="module-poster-item-title">标题</div>
- 详情页标题: <h1> 在 module-info-heading 内
- 详情页封面: <img data-original="..."> 在 module-item-pic 内
- 详情页年份/地区: module-info-tag-link 内的 <a> 标签
- 详情页导演/主演: module-info-item-title + module-info-item-content 内的 <a> 标签
- 线路名: module-tab-item 内的 <span> + <small>（集数）
- 集数链接: module-play-list-link 的 href + title + <span>
"""
import sys
import json
import re
import base64
import time
from urllib.parse import quote, urljoin, unquote

# AES 解密依赖（用于官源解析）
try:
    from Crypto.Cipher import AES
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

sys.path.append('..')

try:
    from base.spider import Spider
except ImportError:
    import requests as rq
    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=30, **kw)
            r.encoding = 'utf-8'
            return r


class Spider(Spider):

    # ===== 站点配置 =====
    HOST = "https://www.77dpw.vip"

    # 父分类（首页导航栏）
    CLASSES = [
        {'type_name': '电影', 'type_id': '1'},
        {'type_name': '动漫', 'type_id': '2'},
        {'type_name': '剧集', 'type_id': '3'},
        {'type_name': '短剧', 'type_id': '4'},
        {'type_name': '综艺', 'type_id': '5'},
    ]

    # 子分类筛选器（始终返回，不依赖 filter 参数）
    FILTERS = {
        '1': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '科幻片', 'v': '科幻片'},
                {'n': '恐怖片', 'v': '恐怖片'},
                {'n': '动作片', 'v': '动作片'},
                {'n': '战争片', 'v': '战争片'},
                {'n': '爱情片', 'v': '爱情片'},
                {'n': '喜剧片', 'v': '喜剧片'},
                {'n': '剧情片', 'v': '剧情片'},
                {'n': '记录片', 'v': '记录片'},
            ]},
            {'key': 'year', 'name': '年份', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '2026', 'v': '2026'},
                {'n': '2025', 'v': '2025'},
                {'n': '2024', 'v': '2024'},
                {'n': '2023', 'v': '2023'},
            ]},
        ],
        '2': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '大陆番', 'v': '大陆番'},
                {'n': '日本番', 'v': '日本番'},
                {'n': '韩国番', 'v': '韩国番'},
                {'n': '港台番', 'v': '港台番'},
                {'n': '欧美番', 'v': '欧美番'},
            ]},
        ],
        '3': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '大陆剧', 'v': '大陆剧'},
                {'n': '日本剧', 'v': '日本剧'},
                {'n': '韩国剧', 'v': '韩国剧'},
                {'n': '香港剧', 'v': '香港剧'},
                {'n': '台湾剧', 'v': '台湾剧'},
                {'n': '欧美剧', 'v': '欧美剧'},
            ]},
        ],
        '4': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
            ]},
        ],
        '5': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '大陆综艺', 'v': '大陆综艺'},
                {'n': '港台综艺', 'v': '港台综艺'},
                {'n': '日韩综艺', 'v': '日韩综艺'},
                {'n': '欧美综艺', 'v': '欧美综艺'},
            ]},
        ],
    }

    # 需要跳过的搜索引擎线路关键词
    SKIP_KEYWORDS = ("搜索", "百度", "搜狗", "神马", "360", "baidu", "google", "sogou")

    # 官源解析失败后的嗅探兜底页（第三方解析器，按优先级排序）
    # 注意: bfq 返回"解析失败"页时说明资源被 VIP 锁死, 换解析器也可能无解, 仅提高命中率
    SNIFF_PAGES = [
        "https://jx.xmflv.com/?url=",      # 实测 200, 内嵌 JS 播放器
        "https://jx.playerjy.com/?url=",   # 实测 200, 备用
        "https://bfq.txnp.cn/player?url=", # 兜底
    ]

    def init(self, extend=""):
        """初始化"""
        if isinstance(extend, list):
            self.extend = ''
        else:
            self.extend = extend or ''
        self.host = self.HOST
        self.header = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36',
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self._home_cache = []
        self._home_cache_time = 0

    # ========== 工具方法 ==========

    def _txt(self, url, referer=None, timeout=30):
        """带异常兜底的 HTTP 请求，返回文本"""
        headers = dict(self.header)
        if referer:
            headers["Referer"] = referer
        try:
            rsp = self.fetch(url, headers=headers, timeout=timeout)
            try:
                rsp.encoding = "utf-8"
            except Exception:
                pass
            return rsp.text
        except Exception:
            return ""

    def _url(self, path):
        """URL 拼接"""
        if not path:
            return ""
        if path.startswith("http"):
            return path
        return self.host + path if path.startswith("/") else self.host + "/" + path

    def _match(self, pattern, text, default=""):
        """正则匹配第一个分组"""
        m = re.search(pattern, text, re.S)
        return m.group(1).strip() if m else default

    def _strip_tags(self, html):
        """去除 HTML 标签"""
        return re.sub(r'<[^>]+>', '', html).strip()

    def _is_direct_media(self, url):
        """判断是否为直链媒体"""
        url = (url or "").lower()
        return ".m3u8" in url or ".mp4" in url or ".flv" in url or ".mkv" in url

    def _is_official_source(self, url):
        """判断是否为官方播放页（非直链）"""
        url = (url or "").lower()
        keys = (
            "mgtv.com", "youku.com", "iqiyi.com", "qiyi.com",
            "v.qq.com", "qq.com", "bilibili.com", "le.com",
            "sohu.com", "pptv.com", "1905.com",
        )
        return any(k in url for k in keys) and not self._is_direct_media(url)

    def _extract_official_url_from_playpage(self, html):
        """从播放页 HTML 中提取官方播放 URL（藏在 player_aaaa 或 iframe 中）"""
        if not html:
            return ""

        # 1. 从 player_aaaa JSON 中提取
        m = re.search(r'var\s+player_[a-zA-Z0-9_]+\s*=\s*(\{.*?\})\s*</script>', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                url = data.get("url", "") or ""
                if url and self._is_official_source(url):
                    return url
                # encrypt 解码后再检查
                encrypt = data.get("encrypt", 0)
                if encrypt in [1, 2] and url:
                    try:
                        decoded = base64.b64decode(url).decode("utf-8")
                        if encrypt == 2 and "%" in decoded:
                            decoded = unquote(decoded)
                        if self._is_official_source(decoded):
                            return decoded
                    except Exception:
                        pass
            except Exception:
                pass

        # 2. 从 iframe src 中提取
        iframe = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.S)
        if iframe:
            iframe_url = self._url(iframe.group(1))
            iframe_html = self._txt(iframe_url, referer=self.host + "/", timeout=20)
            if iframe_html:
                # 递归提取
                nested_url = self._extract_official_url_from_playpage(iframe_html)
                if nested_url:
                    return nested_url
                # 直接从 iframe HTML 中找官方域名
                for key in ("mgtv.com", "youku.com", "iqiyi.com", "qiyi.com",
                           "v.qq.com", "qq.com", "bilibili.com", "le.com",
                           "sohu.com", "pptv.com", "1905.com"):
                    m2 = re.search(r'["\'](https?://[^"\']*' + key + r'[^"\']*)["\']', iframe_html, re.I)
                    if m2:
                        return m2.group(1)

        # 3. 全局搜索官方域名
        for key in ("mgtv.com", "youku.com", "iqiyi.com", "qiyi.com",
                   "v.qq.com", "qq.com", "bilibili.com", "le.com",
                   "sohu.com", "pptv.com", "1905.com"):
            m3 = re.search(r'["\'](https?://[^"\']*' + key + r'[^"\']*)["\']', html, re.I)
            if m3:
                return m3.group(1)

        return ""

    def _aes_cbc_decrypt_text(self, cipher_text):
        """AES-CBC 解密 bfq 解析器返回的加密数据

        密文结构：base64(明文) + key(16字节) + iv(16字节)
        key = 倒数第 32 到倒数第 16 位，iv = 最后 16 位
        """
        if not HAS_CRYPTO:
            return ""
        try:
            # 密文最后 32 位拆成 key 和 iv
            key = cipher_text[-32:-16].encode("utf-8")
            iv = cipher_text[-16:].encode("utf-8")
            data = base64.b64decode(cipher_text[:-32])
            raw = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
            pad = raw[-1] if raw else 0
            if 0 < pad <= 16:
                raw = raw[:-pad]
            return raw.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _decode_bfq_result(self, result):
        """解码 bfq 解析器的 result 字段"""
        text = self._aes_cbc_decrypt_text(result or "")
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            return {}

    def _resolve_official_to_media(self, src_url):
        """通过 bfq 解析器将官方播放页 URL 解析为真实 m3u8/mp4

        流程：
        1. 访问 https://bfq.txnp.cn/player?url={encoded_src_url}
        2. 提取页面中的 let result = "..."
        3. AES-CBC 解密得到 JSON
        4. 从 video_info.video.url 获取真实媒体地址

        如果 bfq 解析失败，返回空字符串，由调用方决定是否使用原始 URL
        """
        if not src_url or not self._is_official_source(src_url):
            return ""
        page_url = "https://bfq.txnp.cn/player?url=" + quote(src_url, safe="")
        referer = "https://bfq.txnp.cn/excessive?url=" + quote(src_url, safe="")
        # bfq 服务不稳定（实测超时频发），重试 2 次
        for attempt in range(2):
            try:
                html = self._txt(page_url, referer=referer, timeout=25)
                if not html:
                    continue
                # 解析失败页没有 result 字段，重试无意义直接返回
                result = self._match(r'let\s+result\s*=\s*"([^"]+)"', html)
                if not result:
                    return ""
                data = self._decode_bfq_result(result)
                video = ((data.get("video_info") or {}).get("video") or {})
                media = (video.get("url") or "").replace("\\/", "/")
                if media and self._is_direct_media(media):
                    if ".m3u8" in media:
                        media = self._resolve_m3u8_child(media, referer=page_url)
                    return media
                return ""
            except Exception:
                pass
        return ""

    # ========== 首页 ==========

    def homeContent(self, filter):
        """首页分类 + 筛选器（始终返回 filters）"""
        return {
            'class': self.CLASSES,
            'filters': self.FILTERS,
        }

    def homeVideoContent(self):
        """首页精选内容（从多个分类均衡抓取，带缓存）"""
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < 300:
            return {"list": self._home_cache[:100]}

        # 从所有 5 个分类均衡抓取，每个分类抓第1页，保证内容多样性
        tids = ["1", "2", "3", "4", "5"]
        category_videos = {tid: [] for tid in tids}
        seen = set()

        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            use_pool = True
        except Exception:
            use_pool = False

        def load_category(tid):
            """抓取单个分类的第1页"""
            url = f"{self.host}/vodtype/{tid}.html"
            html = self._txt(url, timeout=15)
            return self._parse_video_list(html)

        if use_pool:
            pool = ThreadPoolExecutor(max_workers=5)
            futures = {pool.submit(load_category, t): t for t in tids}
            try:
                for fu in as_completed(futures, timeout=20):
                    tid = futures[fu]
                    videos = fu.result() or []
                    category_videos[tid] = videos[:20]  # 每个分类最多取20条
            except Exception:
                pass
            finally:
                pool.shutdown(wait=False)
        else:
            for tid in tids:
                videos = load_category(tid) or []
                category_videos[tid] = videos[:20]

        # 按分类顺序交错合并，保证首页内容多样性
        videos = []
        max_per_cat = max(len(v) for v in category_videos.values()) if category_videos else 0
        for i in range(max_per_cat):
            for tid in tids:
                cat_videos = category_videos.get(tid, [])
                if i < len(cat_videos):
                    v = cat_videos[i]
                    vid = v.get("vod_id")
                    if vid and vid not in seen:
                        seen.add(vid)
                        videos.append(v)
                if len(videos) >= 100:
                    break
            if len(videos) >= 100:
                break

        self._home_cache = videos[:100]
        self._home_cache_time = now
        return {"list": self._home_cache}

    # ========== 分类列表 ==========

    def categoryContent(self, tid, pg, filter, extend):
        """分类页内容"""
        try:
            pg = int(pg or 1)
            url = f"{self.host}/vodtype/{tid}-{pg}.html"
            html = self._txt(url, timeout=20)

            if not html or "系统安全验证" in html:
                return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0}

            videos = self._parse_video_list(html)
            pagecount = self._parse_pagecount(html, pg)

            return {
                'list': videos,
                'page': pg,
                'pagecount': pagecount,
                'limit': 20,
                'total': pagecount * 20,
            }
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0}

    def _parse_pagecount(self, html, current_pg):
        """从分类页 HTML 解析总页数"""
        page_links = re.findall(r'/vodtype/\d+-(\d+)\.html', html)
        if page_links:
            max_page = max(int(p) for p in page_links)
            # 确保至少返回当前页，且不超过合理上限（50页）
            return min(max(max_page, current_pg), 50)
        # 兜底：如果解析不到页码，默认给10页让 TV 壳能继续翻页
        return max(current_pg, 10)

    # ========== 视频列表解析 ==========

    def _parse_video_list(self, html):
        """从分类页/首页/搜索页 HTML 解析视频卡片列表

        实测 HTML 结构:
        <a href="/voddetail/65055.html" title="标题" class="module-poster-item module-item">
            <div class="module-item-cover">
                <div class="module-item-note">备注</div>
                <div class="module-item-pic">
                    <img data-original="封面URL" ...>
                </div>
            </div>
            <div class="module-poster-item-info">
                <div class="module-poster-item-title">标题</div>
            </div>
        </a>
        """
        videos = []
        seen_ids = set()

        # 主匹配：module-poster-item 卡片
        card_pattern = re.compile(
            r'<a\s+href="(/voddetail/(\d+)\.html)"\s+title="([^"]*)"\s+'
            r'class="[^"]*module-poster-item[^"]*"[^>]*>([\s\S]*?)</a>',
            re.S
        )
        for m in card_pattern.finditer(html):
            vod_id = m.group(2)
            if vod_id in seen_ids:
                continue
            seen_ids.add(vod_id)

            title = m.group(3).strip()
            inner = m.group(4)

            # 封面：data-original
            pic = self._match(r'data-original="([^"]+)"', inner)
            if pic and not pic.startswith("http"):
                pic = self._url(pic)

            # 备注：module-item-note 或 module-item-new
            remarks = self._match(r'class="module-item-note[^"]*"[^>]*>([^<]+)<', inner)
            if not remarks:
                remarks = self._match(r'class="module-item-new[^"]*"[^>]*>([^<]+)<', inner)

            # 如果标题为空，从 module-poster-item-title 取
            if not title:
                title = self._match(r'class="module-poster-item-title[^"]*"[^>]*>([^<]+)<', inner)

            videos.append({
                'vod_id': vod_id,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remarks,
            })

        # 兜底：宽松匹配所有 voddetail 链接
        if not videos:
            links = re.findall(
                r'<a\s+href="(/voddetail/(\d+)\.html)"\s+title="([^"]*)"',
                html, re.S
            )
            for href, vod_id, title in links:
                if vod_id in seen_ids:
                    continue
                seen_ids.add(vod_id)
                videos.append({
                    'vod_id': vod_id,
                    'vod_name': title,
                    'vod_pic': '',
                    'vod_remarks': '',
                })

        return videos

    # ========== 详情页 ==========

    def detailContent(self, ids):
        """详情页"""
        if isinstance(ids, str):
            ids = [ids]
        vod_id = ids[0]

        url = f"{self.host}/voddetail/{vod_id}.html"
        html = self._txt(url, timeout=30)

        if not html or "系统安全验证" in html:
            return {'list': []}

        vod = self._parse_detail(html, vod_id)
        return {'list': [vod] if vod else []}

    def _parse_detail(self, html, vod_id):
        """解析详情页（module-* 模板）"""
        # 标题：<h1> 在 module-info-heading 内
        title = self._match(r'<div class="module-info-heading">\s*<h1>([^<]+)</h1>', html)
        if not title:
            title = self._match(r'<h1[^>]*>([^<]+)</h1>', html)
        if not title:
            title = self._match(r'<title>([^<|]+)', html)
            title = re.sub(r'\s*[-_|].*$', '', title).strip() if title else ""

        # 封面图：data-original 在 module-item-pic 的 <img> 内
        pic = self._match(
            r'class="module-item-pic[^"]*"[^>]*>[\s\S]*?<img[^>]*data-original="([^"]+)"',
            html
        )
        if not pic:
            pic = self._match(r'data-original="([^"]+)"', html)
        if pic and not pic.startswith("http"):
            pic = self._url(pic)

        # 年份：module-info-tag-link 里的 <a title="2026">
        year = self._match(r'<a\s+title="(\d{4})"[^>]*href="/vodshow/', html)

        # 地区：module-info-tag-link 里的 <a title="中国">
        # 先找带 title 属性的地区链接
        area = self._match(
            r'href="/vodshow/\d+-%[0-9A-F]+%[0-9A-F]+----------\.html"\s+title="([^"]+)"',
            html
        )
        if not area:
            # 尝试 URL 编码的地区链接
            area_match = re.search(
                r'href="/vodshow/\d+-([^"]*?)----------\.html"\s+title="([^"]+)"',
                html
            )
            if area_match:
                area = area_match.group(2)

        # 类型：vodshow URL 中带 class 参数的链接（--- 后面）
        type_matches = re.findall(r'href="/vodshow/\d+---([^"]+?)--------\.html"', html)
        type_name = ""
        if type_matches:
            type_name = unquote(type_matches[0])

        # 剧情简介：module-info-introduction-content 内的 <p>
        content = self._match(
            r'class="module-info-introduction-content[^"]*"[^>]*>[\s\S]*?<p>([\s\S]*?)</p>',
            html
        )
        if content:
            content = self._strip_tags(content)[:500]

        # 导演/主演/状态
        director = self._extract_info_item(html, "导演")
        actor = self._extract_info_item(html, "主演")
        remarks = self._extract_info_item(html, "状态")
        if not remarks:
            remarks = self._extract_info_item(html, "更新")

        # 播放列表
        play_from, play_url = self._parse_playlist(html, vod_id)

        vod = {
            'vod_id': vod_id,
            'vod_name': title,
            'vod_pic': pic,
            'type_name': type_name,
            'vod_year': year,
            'vod_area': area,
            'vod_remarks': remarks,
            'vod_actor': actor,
            'vod_director': director,
            'vod_content': content,
            'vod_play_from': "$$$".join(play_from),
            'vod_play_url': "$$$".join(play_url),
        }
        return vod

    def _extract_info_item(self, html, label):
        """提取 module-info-item 中的字段值（导演/主演/状态等）

        实测结构:
        <span class="module-info-item-title">导演：</span>
        <div class="module-info-item-content">
            <a href="...">柏杉</a><span class="slash">/</span>
        </div>
        """
        pattern = re.compile(
            r'module-info-item-title">\s*' + label + r'[：:]\s*</span>\s*'
            r'<div class="module-info-item-content">\s*(.*?)</div>',
            re.S
        )
        m = pattern.search(html)
        if m:
            inner = m.group(1)
            links = re.findall(r'<a[^>]*>([^<]+)</a>', inner)
            if links:
                return ",".join(l.strip() for l in links)
            text = self._strip_tags(inner)
            return text.strip()
        return ""

    def _parse_playlist(self, html, vod_id):
        """解析播放列表（module-* 模板：多线路 + 集数）

        实测结构:
        线路名:
        <div class="module-tab-item tab-item" data-dropdown-value="优酷">
            <span>优酷</span><small>30</small>
        </div>

        集数链接:
        <a class="module-play-list-link" href="/vodplay/177302-1-1.html" title="播放九门1">
            <span>1</span>
        </a>
        """
        play_from = []
        play_url = []

        # 1. 找线路名
        source_items = re.findall(
            r'<div class="module-tab-item[^"]*"[^>]*data-dropdown-value="([^"]*)"[^>]*>\s*<span>([^<]+)</span>',
            html, re.S
        )

        # 2. 按 module-play-list-content 拆分集数块
        play_blocks = re.split(r'class="module-play-list-content', html)
        play_blocks = play_blocks[1:] if len(play_blocks) > 1 else []

        # 3. 如果没有线路选择器，直接找所有播放链接
        if not source_items:
            play_links = re.findall(
                r'<a[^>]*class="[^"]*module-play-list-link[^"]*"[^>]*'
                r'href="(/vodplay/[^"]+\.html)"[^>]*title="([^"]*)"[^>]*>',
                html, re.S
            )
            if play_links:
                episodes = []
                seen_eps = set()
                for href, title in play_links:
                    if href in seen_eps:
                        continue
                    seen_eps.add(href)
                    # 从 title 中提取纯数字集数（如"播放九门1" → "1"）
                    raw_name = self._strip_tags(title or "").strip() if title else ""
                    num_match = re.search(r'(\d+)$', raw_name)
                    if num_match:
                        name = num_match.group(1)
                    elif raw_name:
                        name = re.sub(r'^播放\s*', '', raw_name)
                    else:
                        name = "播放"
                    episodes.append(f"{name}${self._url(href)}")
                if episodes:
                    play_from.append("默认线路")
                    play_url.append("#".join(episodes))
            return play_from, play_url

        # 4. 逐线路匹配集数
        for idx, (data_value, span_text) in enumerate(source_items):
            source_name = (data_value or span_text).strip()

            # 跳过搜索引擎线路
            if any(kw in source_name.lower() for kw in self.SKIP_KEYWORDS):
                continue

            episodes = []
            if idx < len(play_blocks):
                block = play_blocks[idx]
                links = re.findall(
                    r'<a[^>]*class="[^"]*module-play-list-link[^"]*"[^>]*'
                    r'href="(/vodplay/[^"]+\.html)"[^>]*title="([^"]*)"[^>]*>',
                    block, re.S
                )
                for href, title in links:
                    # 从 title 中提取纯数字集数（如"播放九门1" → "1"）
                    raw_name = self._strip_tags(title or "").strip() if title else ""
                    # 尝试提取末尾的数字
                    num_match = re.search(r'(\d+)$', raw_name)
                    if num_match:
                        name = num_match.group(1)
                    elif raw_name:
                        # 如果没有数字，保留原始名称但去掉"播放"前缀
                        name = re.sub(r'^播放\s*', '', raw_name)
                    else:
                        name = "播放"
                    episodes.append(f"{name}${self._url(href)}")

            if episodes:
                play_from.append(source_name)
                play_url.append("#".join(episodes))

        # 5. 兜底：如果按线路拆分没拿到，直接找所有播放链接
        if not play_from:
            play_links = re.findall(
                r'<a[^>]*class="[^"]*module-play-list-link[^"]*"[^>]*'
                r'href="(/vodplay/[^"]+\.html)"[^>]*title="([^"]*)"',
                html, re.S
            )
            if play_links:
                episodes = []
                seen_eps = set()
                for href, title in play_links:
                    if href in seen_eps:
                        continue
                    seen_eps.add(href)
                    # 从 title 中提取纯数字集数（如"播放九门1" → "1"）
                    raw_name = self._strip_tags(title or "").strip() if title else ""
                    num_match = re.search(r'(\d+)$', raw_name)
                    if num_match:
                        name = num_match.group(1)
                    elif raw_name:
                        name = re.sub(r'^播放\s*', '', raw_name)
                    else:
                        name = "播放"
                    episodes.append(f"{name}${self._url(href)}")
                if episodes:
                    play_from.append("默认线路")
                    play_url.append("#".join(episodes))

        return play_from, play_url

    # ========== 搜索 ==========

    def searchContent(self, key, quick, pg="1"):
        """搜索

        实测搜索 URL: /index.php?m=vod-search-wd-{keyword}
        vodsearch/ 路径返回 404，必须用 index.php?m= 格式
        """
        try:
            pg = int(pg or 1)
            url = f"{self.host}/index.php?m=vod-search-wd-{quote(key, safe='')}"
            if pg > 1:
                url += f"-pg-{pg}"
            html = self._txt(url, timeout=20)

            if not html or "系统安全验证" in html:
                return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0}

            videos = self._parse_video_list(html)
            return {'list': videos, 'page': pg}
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0}

    # ========== 播放解析 ==========

    def playerContent(self, flag, id, vipFlags):
        """播放解析"""
        if not id:
            return {'parse': 1, 'playUrl': '', 'url': ''}

        url = id if str(id).startswith("http") else self._url(id)

        # 1. 直链检测（最高优先级）
        if self._is_direct_media(url):
            return {
                'parse': 0,
                'playUrl': '',
                'url': url,
                'header': {
                    'User-Agent': self.header['User-Agent'],
                    'Referer': self.host + '/',
                },
                'format': 'application/x-mpegURL' if '.m3u8' in url.lower() else '',
                'contentType': 'application/x-mpegURL' if '.m3u8' in url.lower() else '',
            }

        # 2. 播放页解析（必须先拿到 HTML 才能判断是否有官源）
        html = self._txt(url, referer=self.host + "/", timeout=30)
        if not html:
            return {'parse': 1, 'playUrl': '', 'url': url}

        # 2.1 从播放页提取官方 URL（藏在 player_aaaa 或 iframe 中）
        official_url = self._extract_official_url_from_playpage(html)
        if official_url:
            resolved = self._resolve_official_to_media(official_url)
            if resolved:
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': resolved,
                    'header': {
                        'User-Agent': self.header['User-Agent'],
                        'Referer': 'https://bfq.txnp.cn/',
                    },
                    'format': 'application/x-mpegURL' if '.m3u8' in resolved.lower() else '',
                    'contentType': 'application/x-mpegURL' if '.m3u8' in resolved.lower() else '',
                }
            # bfq 解析失败时，不要把爱优腾官方页交给壳子嗅探（有反爬，100% 嗅探失败）
            # 改为返回第三方解析器播放页，壳子用 webview 嗅探解析器内嵌的播放器
            sniff_page = self.SNIFF_PAGES[0] + quote(official_url, safe='')
            return {
                'parse': 1,
                'playUrl': '',
                'url': sniff_page,
                'header': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                                  'Chrome/120.0 Safari/537.36',
                    'Referer': self.SNIFF_PAGES[0].split('?')[0].rstrip('/') + '/',
                },
            }

        # 2.2 常规解析：player_aaaa JSON（苹果 CMS 标准播放变量）
        real = ""
        m = re.search(r'var\s+player_[a-zA-Z0-9_]+\s*=\s*(\{.*?\})\s*</script>', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                real = data.get("url", "") or ""
                encrypt = data.get("encrypt", 0)
                if encrypt in [1, 2] and real:
                    try:
                        decoded = base64.b64decode(real).decode("utf-8")
                        # encrypt=2 时 base64 解码后是 URL 编码字符串，需要再 unquote
                        if encrypt == 2 and "%" in decoded:
                            real = unquote(decoded)
                        else:
                            real = decoded
                    except Exception:
                        pass
            except Exception:
                real = self._match(r'"url"\s*:\s*"([^"]+)"', m.group(1))

        # 2.3 iframe 嵌套
        if not real:
            iframe = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.S)
            if iframe:
                iframe_url = self._url(iframe.group(1))
                iframe_html = self._txt(iframe_url, referer=url, timeout=30)
                real = self._match(r'"url"\s*:\s*"([^"]+)"', iframe_html)
                if not real:
                    real = self._match(
                        r'var\s+player_[a-zA-Z0-9_]+\s*=\s*\{[^}]*"url"\s*:\s*"([^"]+)"',
                        iframe_html
                    )

        # 2.4 全局匹配 m3u8/mp4
        if not real:
            m2 = re.search(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', html, re.I)
            if m2:
                real = m2.group(1)

        if real:
            real = real.replace("\\/", "/")
            if ".m3u8" in real.lower():
                real = self._resolve_m3u8_child(real, referer=url)

            return {
                'parse': 0,
                'playUrl': '',
                'url': real,
                'header': {
                    'User-Agent': self.header['User-Agent'],
                    'Referer': url,
                },
                'format': 'application/x-mpegURL' if '.m3u8' in real.lower() else '',
                'contentType': 'application/x-mpegURL' if '.m3u8' in real.lower() else '',
            }

        # 3. 兜底交给壳子嗅探
        return {'parse': 1, 'playUrl': '', 'url': url}

    def _resolve_m3u8_child(self, m3u8_url, referer=""):
        """解析主 m3u8 中的子 m3u8（Exo 兼容）"""
        text = self._txt(m3u8_url, referer=referer or self.host + "/", timeout=20)
        if not text or "#EXTM3U" not in text:
            return m3u8_url
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF"):
                for nxt in lines[i + 1:]:
                    if nxt and not nxt.startswith("#"):
                        return urljoin(m3u8_url, nxt)
        return m3u8_url

    # ========== 本地代理（可选）==========

    def localProxy(self, param):
        """本地代理：解决 Referer 丢失、m3u8 相对路径"""
        raw_url = param.get("url") or param.get("u") or ""
        referer = param.get("referer") or self.host + "/"
        media_url = raw_url

        try:
            import requests
            headers = {
                "User-Agent": self.header['User-Agent'],
                "Referer": referer,
            }
            r = requests.get(media_url, headers=headers, timeout=30, verify=False)
            text = r.content.decode("utf-8", errors="ignore")

            if "#EXTM3U" in text:
                out = []
                for line in text.splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        out.append(line)
                    else:
                        abs_url = urljoin(media_url, s)
                        proxy_url = self._proxy_url(abs_url, referer)
                        out.append(proxy_url)
                return [200, "application/x-mpegURL", "\n".join(out).encode("utf-8")]

            return [200, r.headers.get("content-type") or "application/octet-stream", r.content]
        except Exception:
            return [200, "video/MP2T", b"", ""]

    def _proxy_url(self, media_url, referer=""):
        """构造代理 URL"""
        if not hasattr(self, "getProxyUrl"):
            return media_url
        try:
            base = self.getProxyUrl()
            return base + "&url=" + quote(media_url, safe="") + "&referer=" + quote(referer or self.host + "/", safe="")
        except Exception:
            return media_url

    # ========== 清理 ==========

    def destroy(self):
        pass

    def close(self):
        """T4 daemon 关闭时调用"""
        self.destroy()
