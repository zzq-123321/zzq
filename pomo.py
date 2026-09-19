# -*- coding: utf-8 -*-
"""
Pomo影院 爬虫 (CatVod / 影视仓 py spider)

【反爬机制说明 / 绕过方案】
------------------------------------------------------------
站点 pomo.mom 已做前端混淆：
  1. 详情/播放页里 const route1Data = [] 被置空，原来直接写在页面里的
     m3u8 直链不再存在（旧脚本正则提取到这里就得到空列表）。
  2. 真实播放地址改由站内接口动态下发：
       GET /content/plugins/plyr_player/api.php?type=auto_search&wd=<关键词>
            -> 返回各源(天堂/西瓜/暴风/非凡...)的搜索结果与 play_url
       GET /content/plugins/plyr_player/api.php?type=auto_detail&site=<源>&id=<id>
            -> 单条结果的剧集(分集)列表
       GET /content/plugins/plyr_player/api.php?type=parse&url=<m3u8>
            -> 把外部 m3u8 解析成 pomo.mom 的代理直链
            /content/plugins/plyr_player/api.php?type=proxy&url=<encoded>
  3. 最终浏览器真正播放的是 type=proxy 这条 pomo.mom 自己的代理直链，
     由 pomo 服务端去抓取外部 m3u8 并转发（规避跨域 / 防盗链）。

绕过：不再依赖页面内 route1Data，改为直接调用上面的 api.php 接口链，
并在 playerContent 里用 parse 把 m3u8 转成 proxy 代理直链返回。
接口仅需 Referer=pomo.mom 与常规 UA，无签名/令牌校验。
"""
import re, urllib.parse, json, time, hashlib
from bs4 import BeautifulSoup
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    def init(self, extend=""):
        self.host = "https://pomo.mom"
        self.api = "/content/plugins/plyr_player/api.php"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        # PikPak 配置: extend 格式 "pikpak_user|pikpak_pass"
        self.pikpak_user = ""
        self.pikpak_pass = ""
        if extend and "|" in extend:
            parts = extend.split("|", 1)
            self.pikpak_user = parts[0].strip()
            self.pikpak_pass = parts[1].strip()

    def getName(self):
        return 'Pomo影院'

    def homeContent(self, filter):
        return {"class": [
            {"type_id": "huayurm", "type_name": "华语热门"},
            {"type_id": "jiating", "type_name": "家庭影院"},
            {"type_id": "donghuadadiany", "type_name": "动画大电影"},
            {"type_id": "lengmenjiapian", "type_name": "冷门佳片"},
            {"type_id": "top250", "type_name": "TOP250"},
            {"type_id": "languang", "type_name": "蓝光原盘"},
            {"type_id": "dianshiju", "type_name": "剧集"},
        ], "filters": {}}

    def homeVideoContent(self):
        html = self._fetch('/')
        return {"list": self._parse_video_list(html)}

    def categoryContent(self, tid, pg, filter, extend):
        url = f'/{tid}'
        if int(pg) > 1:
            url = f'/{tid}/page/{pg}'
        html = self._fetch(url)
        items = self._parse_video_list(html)
        page = int(pg)
        page_count = page if len(items) < 24 else page + 2
        return {"list": items, "page": page, "pagecount": page_count, "limit": 24, "total": page_count * 24}

    # ------------------------------------------------------------------
    # 详情：磁力 / 在线播放(新接口) / 夸克网盘
    # ------------------------------------------------------------------
    def detailContent(self, ids):
        result = {"list": []}
        vid = ids[0].split(',')[0].strip()
        try:
            html = self._fetch(f'/{vid}')
            if not html:
                return result
            soup = BeautifulSoup(html, 'html.parser')

            vod_name = self._extract_title(html, soup)
            vod_pic = ''
            img = soup.select_one('img.w-full')
            if img:
                vod_pic = self._fix_pic(img.get('src', ''))

            vod_content = ''
            desc = soup.select_one('p.text-gray')
            if desc:
                vod_content = desc.get_text(strip=True)

            play_from = []
            play_url = []

            # 1. 磁力链接
            ep_list = []
            for item in soup.select('div.download-item'):
                a = item.select_one('a.x-dbjs-download-link')
                if a:
                    magnet = a.get('data-url', '')
                    name = a.get_text(strip=True)
                    if magnet and magnet.startswith('magnet:'):
                        ep_list.append(f'{name}${magnet}')
            if ep_list:
                play_from.append('磁力链接')
                play_url.append('#'.join(ep_list))

            # 2. 在线播放 —— 新接口绕过（auto_search -> play_url -> parse(proxy)）
            online_eps = self._get_online_eps(vid)
            if online_eps:
                play_from.append('在线播放')
                play_url.append('#'.join(online_eps))

            # 3. 夸克网盘
            #    只从下载区 (.download-item > a.x-dbjs-download-link 的 data-url) 取，
            #    不再全页正则扫描——全页扫描会把页脚"软件推荐"里的
            #    qBittorrent / PotPlayer / MX Player 等安装包分享一并收进来，
            #    点开是软件而非影片，网盘解析找不到视频文件就播不了。
            SOFT_KW = (
                'bitcomet', 'qbittorrent', 'potplayer', 'mx player', 'mxplayer',
                'vlc', 'nplayer', 'infuse', 'kodi', '比特彗星', '播放器',
            )
            seen_quark = set()
            quark_eps = []

            # 本站的夸克网盘区块是 <script> 里 JS 动态注入的
            # （insertAdjacentHTML / appendChild，属性带 \" 转义），
            # 静态 DOM 中并不存在，所以先把转义还原再从原始文本里提取。
            flat = html.replace('\\"', '"').replace('\\/', '/')
            cands = []
            pat = (r'class="x-dbjs-download-link"\s+data-url="'
                   r'(https?://pan\.quark\.cn/s/[A-Za-z0-9]+)"[^>]*>(.*?)</a>')
            for m in re.finditer(pat, flat, re.S):
                tail = flat[m.end():m.end() + 300]
                sz = re.search(r'class="file-size"[^>]*>([^<]*)<', tail)
                cands.append((m.group(1), m.group(2), sz.group(1).strip() if sz else ''))
            # 兜底：若页面是静态输出的，用 DOM 再取一次
            for item in soup.select('div.download-item'):
                a = item.select_one('a.x-dbjs-download-link')
                if not a:
                    continue
                u = (a.get('data-url') or '').strip()
                if re.match(r'https?://pan\.quark\.cn/s/[A-Za-z0-9]+', u):
                    size_el = item.select_one('span.file-size')
                    cands.append((u, a.get_text(strip=True),
                                  size_el.get_text(strip=True) if size_el else ''))

            for qurl, raw_name, size_txt in cands:
                if qurl in seen_quark:
                    continue
                if any(k in raw_name.lower() for k in SOFT_KW):
                    continue
                seen_quark.add(qurl)
                # 分集名不能含 $ 与 #（TVBox 用 # 分隔分集、$ 分隔名称与地址）
                name = re.sub(r'<[^>]+>', '', raw_name)
                name = re.sub(r'[\U0001F000-\U0001FAFF✅☑️⭐★]', '', name)
                name = name.replace('$', ' ').replace('#', ' ').replace('&', ' ').strip()
                if size_txt:
                    name = (name + ' ' + size_txt).strip()
                if not name:
                    name = '夸克网盘'
                quark_eps.append(f'{name}${qurl}')
            if quark_eps:
                play_from.append('夸克网盘')
                play_url.append('#'.join(quark_eps))

            if play_from:
                result["list"].append({
                    "vod_id": vid,
                    "vod_name": vod_name,
                    "vod_pic": vod_pic,
                    "vod_content": vod_content,
                    "vod_play_from": "$$$".join(play_from),
                    "vod_play_url": "$$$".join(play_url),
                })
        except Exception as e:
            print(f'detailContent error: {e}')
        return result

    def searchContent(self, key, quick, pg="1"):
        try:
            decoded = urllib.parse.unquote(key)
        except:
            decoded = key
        url = f'/?keyword={urllib.parse.quote(decoded)}'
        if int(pg) > 1:
            url = f'/?keyword={urllib.parse.quote(decoded)}&page={pg}'
        html = self._fetch(url)
        items = self._parse_video_list(html)
        return {"list": items, "page": int(pg), "pagecount": 1, "limit": 24, "total": len(items)}

    # ------------------------------------------------------------------
    # playerContent：m3u8 / proxy 直链直接播放；网盘 WebView；磁力 PikPak/webtor
    # ------------------------------------------------------------------
    def playerContent(self, flag, id, vipFlags):
        # m3u8 / mp4 直链：优先用 parse 转成 pomo 代理直链（规避外部防盗链）
        if id.startswith('http') and any(ext in id.lower() for ext in ['.m3u8', '.mp4', '.ts', '.flv']):
            proxied = self._parse_to_proxy(id)
            final_url = proxied or id
            return {
                "parse": 0,
                "url": final_url,
                "header": {
                    "User-Agent": self.headers['User-Agent'],
                    "Referer": "https://pomo.mom/",
                    "Accept": "*/*",
                }
            }
        # 网盘链接：必须 parse=0，交给 TVBox 的「网盘解析」通道处理，
        # 这样才能用上你在 TVBox 里做的夸克授权（token）去换真实播放地址。
        # 旧代码 parse=1 会走网页嗅探，分享页是纯前端 + 需登录态，必然解析失败。
        if 'pan.quark.cn' in id or 'pan.baidu.com' in id or 'aliyundrive' in id:
            return {
                "parse": 0,
                "url": id,
                "header": {"User-Agent": self.headers['User-Agent']}
            }
        # 磁力链接 -> 优先 PikPak 离线解析，否则 webtor
        if id.startswith('magnet:'):
            if self.pikpak_user and self.pikpak_pass:
                try:
                    pikpak = PikPakClient(self.pikpak_user, self.pikpak_pass)
                    pikpak.login()
                    result = pikpak.offline_download(id)
                    task_id = None
                    file_id = None
                    if result:
                        task_id = result.get('task', {}).get('id')
                        file_id = result.get('file', {}).get('id')
                        if not file_id and isinstance(result.get('file'), str):
                            file_id = result.get('file')
                    if task_id and file_id:
                        for _ in range(30):
                            time.sleep(0.5)
                            status = pikpak.get_task_status(task_id, file_id)
                            if status == 'done':
                                break
                            if status == 'error':
                                raise Exception('PikPak offline download failed')
                        file_info = pikpak.get_download_url(file_id)
                        medias = file_info.get('medias', [])
                        if medias and len(medias) > 0:
                            media_url = medias[0].get('link', {}).get('url')
                            if media_url:
                                return {
                                    "parse": 0,
                                    "url": media_url,
                                    "header": {
                                        "User-Agent": pikpak.user_agent,
                                        "Referer": "https://mypikpak.com/",
                                        "Accept": "*/*",
                                    }
                                }
                        web_content = file_info.get('web_content_link')
                        if web_content:
                            return {
                                "parse": 0,
                                "url": web_content,
                                "header": {
                                    "User-Agent": pikpak.user_agent,
                                    "Referer": "https://mypikpak.com/",
                                    "Accept": "*/*",
                                }
                            }
                except Exception as e:
                    print(f'PikPak play error: {e}')
            webtor_url = f"https://webtor.io/#/show?magnet={urllib.parse.quote(id)}"
            return {
                "parse": 1,
                "url": webtor_url,
                "header": {
                    "User-Agent": self.headers['User-Agent'],
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }
            }
        return {"parse": 1, "url": id}

    def localProxy(self, param=''):
        return {}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    # ====================== 网络 / 解析辅助 ======================
    def _fetch(self, url):
        try:
            if not url.startswith('http'):
                url = self.host + url
            rsp = self.fetch(url, headers=self.headers)
            return rsp.text if rsp else ''
        except Exception as e:
            print(f'_fetch error: {e}')
            return ''

    def _api_fetch(self, path):
        """调用 api.php 接口，返回解析后的 JSON 或 None。"""
        try:
            url = path if path.startswith('http') else (self.host + path)
            headers = {
                "User-Agent": self.headers['User-Agent'],
                "Referer": "https://pomo.mom/",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
            rsp = self.fetch(url, headers=headers)
            if not rsp:
                return None
            text = rsp.text if hasattr(rsp, 'text') else str(rsp)
            return json.loads(text)
        except Exception as e:
            print(f'_api_fetch error: {e}')
            return None

    def _parse_to_proxy(self, m3u8_url):
        """调用 type=parse 把外部 m3u8 解析成 pomo 代理直链。失败返回 None。"""
        try:
            path = f"{self.api}?type=parse&url={urllib.parse.quote(m3u8_url, safe='')}"
            data = self._api_fetch(path)
            if data and data.get('code') == 200 and data.get('data'):
                return data['data']
        except Exception as e:
            print(f'_parse_to_proxy error: {e}')
        return None

    def _get_search_keyword(self, vid):
        """从播放器页拿到搜索关键词（精确匹配站点使用的 query）。"""
        html = self._fetch(f'/?plugin=plyr_player&gid={vid}')
        if html:
            m = re.search(r'const\s+searchKeyword\s*=\s*"((?:[^"\\]|\\.)*)"', html)
            if m:
                return self._decode_js(m.group(1))
        # 兜底：用详情页 <title> 第一段
        dh = self._fetch(f'/{vid}')
        if dh:
            mt = re.search(r'<title>(.*?)</title>', dh, re.S)
            if mt:
                title = re.sub(r'\s*[-–—]\s*.*$', '', mt.group(1)).strip()
                return title
        return ''

    def _get_online_eps(self, vid):
        """在线播放真实路径：auto_search -> play_url -> (可选 parse 代理)。"""
        eps = []
        keyword = self._get_search_keyword(vid)
        if not keyword:
            return eps
        data = self._api_fetch(f"{self.api}?type=auto_search&wd={urllib.parse.quote(keyword)}")
        if not data or data.get('code') != 200:
            return eps
        sources = data.get('data') or {}
        for _src, items in sources.items():
            if not isinstance(items, list):
                continue
            for it in items:
                pu = it.get('play_url', '')
                if not pu:
                    continue
                # play_url 内多线路用字面量 "$$$" 连接，跨集可能用 "#" 连接；
                # 注意 name 与 url 之间只是单个 "$"，不能把单 "$" 当分隔符。
                for seg in re.split(r'\$\$\$|#', pu):
                    if '$' not in seg:
                        continue
                    name, link = seg.split('$', 1)
                    link = link.strip().replace('\\/', '/')
                    if not link:
                        continue
                    # 仅保留可直接播放的视频链接（m3u8/mp4/ts/flv），
                    # 丢弃 /share/ 之类的落地页（浏览器里 parse 会处理，
                    # 但作为独立播放源交给播放器反而无法直放）。
                    if not any(ext in link.lower() for ext in ('.m3u8', '.mp4', '.ts', '.flv')):
                        continue
                    eps.append(f'{name}${link}')
        # 去重（同名同链）
        seen, uniq = set(), []
        for e in eps:
            if e not in seen:
                seen.add(e)
                uniq.append(e)
        return uniq

    def _extract_title(self, html, soup):
        h1 = soup.select_one('h1')
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)
        mt = re.search(r'<title>(.*?)</title>', html, re.S)
        if mt:
            return re.sub(r'\s*[-–—]\s*.*$', '', mt.group(1)).strip()
        return ''

    def _fix_pic(self, u):
        if not u:
            return ''
        if u.startswith('//'):
            return 'https:' + u
        return u.replace('&amp;', '&')

    def _parse_video_list(self, html):
        videos, seen = [], set()
        if not html:
            return videos
        soup = BeautifulSoup(html, 'html.parser')
        for card in soup.select('div.bg-cardbg'):
            a = card.select_one('a[href]')
            if not a:
                continue
            href = a.get('href', '')
            m = re.search(r'/(\d+)$', href)
            if not m:
                continue
            vod_id = m.group(1)
            if vod_id in seen:
                continue
            seen.add(vod_id)

            img = a.select_one('img')
            vod_name = img.get('alt', '') if img else ''
            vod_pic = self._fix_pic(img.get('src', '')) if img else ''

            remark_el = card.select_one('span.file-size')
            vod_remarks = remark_el.get_text(strip=True) if remark_el else ''

            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name.strip(),
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks,
            })
        return videos

    @staticmethod
    def _decode_js(s):
        """解码 JS 字符串里的 \\uXXXX 与 \\/ 转义。"""
        def _rep(m):
            return chr(int(m.group(1), 16))
        s = re.sub(r'\\u([0-9a-fA-F]{4})', _rep, s)
        s = s.replace('\\/', '/').replace('\\"', '"').replace('\\\\', '\\')
        return s


# ==================== PikPak 同步客户端 ====================

PIKPAK_CLIENT_ID = "YNxT9w7GMdWvEOKa"
PIKPAK_CLIENT_SECRET = "dbw2OtmVEeuUvIptb1Coyg"
PIKPAK_CLIENT_VERSION = "1.47.1"
PIKPAK_PACKAGE_NAME = "com.pikcloud.pikpak"
PIKPAK_SDK_VERSION = "2.0.4.204000"

PIKPAK_SALTS = [
    "Gez0T9ijiI9WCeTsKSg3SMlx", "zQdbalsolyb1R/", "ftOjr52zt51JD68C3s",
    "yeOBMH0JkbQdEFNNwQ0RI9T3wU/v", "BRJrQZiTQ65WtMvwO", "je8fqxKPdQVJiy1DM6Bc9Nb1",
    "niV", "9hFCW2R1", "sHKHpe2i96", "p7c5E6AcXQ/IJUuAEC9W6", "",
    "aRv9hjc9P+Pbn+u3krN6", "BzStcgE8qVdqjEH16l4", "SqgeZvL5j9zoHP95xWHt", "zVof5yaJkPe3VFpadPof",
]


class PikPakClient:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.device_id = hashlib.md5(f"{username}{password}".encode()).hexdigest()
        self.access_token = None
        self.refresh_token = None
        self.user_id = None
        self.captcha_token = None
        self.user_agent = self._build_user_agent()

    def _build_user_agent(self):
        signature_base = f"{self.device_id}{PIKPAK_PACKAGE_NAME}1appkey"
        sha1_hash = hashlib.sha1(signature_base.encode("utf-8")).hexdigest()
        md5_result = hashlib.md5(sha1_hash.encode("utf-8")).hexdigest()
        device_sign = f"div101.{self.device_id}{md5_result}"
        ts = int(time.time() * 1000)
        parts = [
            f"ANDROID-{PIKPAK_PACKAGE_NAME}/{PIKPAK_CLIENT_VERSION}",
            "protocolVersion/200", "accesstype/",
            f"clientid/{PIKPAK_CLIENT_ID}", f"clientversion/{PIKPAK_CLIENT_VERSION}",
            "action_type/", "networktype/WIFI", "sessionid/",
            f"deviceid/{self.device_id}", "providername/NONE",
            f"devicesign/{device_sign}", "refresh_token/",
            f"sdkversion/{PIKPAK_SDK_VERSION}", f"datetime/{ts}",
            f"usrno/{self.user_id or ''}", f"appname/{PIKPAK_PACKAGE_NAME}",
            "session_origin/", "grant_type/", "appid/", "clientip/",
            "devicename/Xiaomi_M2004j7ac", "osversion/13",
            "platformversion/10", "accessmode/",
            "devicemodel/M2004J7AC",
        ]
        return " ".join(parts)

    def _captcha_sign(self, timestamp):
        sign = PIKPAK_CLIENT_ID + PIKPAK_CLIENT_VERSION + PIKPAK_PACKAGE_NAME + self.device_id + timestamp
        for salt in PIKPAK_SALTS:
            sign = hashlib.md5((sign + salt).encode()).hexdigest()
        return f"1.{sign}"

    def _get_headers(self):
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/json; charset=utf-8",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.captcha_token:
            headers["X-Captcha-Token"] = self.captcha_token
        if self.device_id:
            headers["X-Device-Id"] = self.device_id
        return headers

    def _request(self, method, url, data=None, params=None, headers=None):
        import requests
        req_headers = headers or self._get_headers()
        try:
            if method == "get":
                resp = requests.get(url, params=params, headers=req_headers, timeout=15)
            elif method == "post":
                resp = requests.post(url, json=data, params=params, headers=req_headers, timeout=15)
            elif method == "patch":
                resp = requests.patch(url, json=data, headers=req_headers, timeout=15)
            elif method == "delete":
                resp = requests.delete(url, params=params, json=data, headers=req_headers, timeout=15)
            else:
                resp = requests.request(method, url, json=data, params=params, headers=req_headers, timeout=15)
            resp.raise_for_status()
            json_data = resp.json()
            if json_data and "error" in json_data:
                if json_data.get("error_code") == 16:
                    self._refresh_token()
                    return self._request(method, url, data, params, headers)
                raise Exception(json_data.get("error_description", "Unknown Error"))
            return json_data
        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {e}")

    def _captcha_init(self, action, meta=None):
        url = f"https://user.mypikpak.com/v1/shield/captcha/init"
        t = str(int(time.time() * 1000))
        if not meta:
            meta = {
                "captcha_sign": self._captcha_sign(t),
                "client_version": PIKPAK_CLIENT_VERSION,
                "package_name": PIKPAK_PACKAGE_NAME,
                "user_id": self.user_id,
                "timestamp": t,
            }
        data = {
            "client_id": PIKPAK_CLIENT_ID,
            "action": action,
            "device_id": self.device_id,
            "meta": meta,
        }
        return self._request("post", url, data=data)

    def login(self):
        login_url = f"https://user.mypikpak.com/v1/auth/signin"
        metas = {}
        if re.match(r"\w+([-+.]\w+)*@\w+([-.]\w+)*\.\w+([-.]\w+)*", self.username):
            metas["email"] = self.username
        elif re.match(r"\d{11,18}", self.username):
            metas["phone_number"] = self.username
        else:
            metas["username"] = self.username
        result = self._captcha_init(action=f"POST:{login_url}", meta=metas)
        self.captcha_token = result.get("captcha_token", "")
        if not self.captcha_token:
            raise Exception("captcha_token get failed")
        login_data = {
            "client_id": PIKPAK_CLIENT_ID,
            "client_secret": PIKPAK_CLIENT_SECRET,
            "password": self.password,
            "username": self.username,
            "captcha_token": self.captcha_token,
        }
        user_info = self._request("post", login_url, data=login_data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
        })
        self.access_token = user_info.get("access_token")
        self.refresh_token = user_info.get("refresh_token")
        self.user_id = user_info.get("sub")
        self.user_agent = self._build_user_agent()
        self.captcha_token = None
        return user_info

    def _refresh_token(self):
        refresh_url = f"https://user.mypikpak.com/v1/auth/token"
        refresh_data = {
            "client_id": PIKPAK_CLIENT_ID,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        user_info = self._request("post", refresh_url, data=refresh_data)
        self.access_token = user_info.get("access_token")
        self.refresh_token = user_info.get("refresh_token")
        self.user_id = user_info.get("sub")
        self.user_agent = self._build_user_agent()
        return user_info

    def offline_download(self, file_url, parent_id=None, name=None):
        url = f"https://api-drive.mypikpak.com/drive/v1/files"
        data = {
            "kind": "drive#file",
            "name": name,
            "upload_type": "UPLOAD_TYPE_URL",
            "url": {"url": file_url},
            "folder_type": "DOWNLOAD" if not parent_id else "",
            "parent_id": parent_id,
        }
        return self._request("post", url, data=data)

    def offline_list(self, size=100, next_page_token=None, phase=None):
        if phase is None:
            phase = ["PHASE_TYPE_RUNNING", "PHASE_TYPE_ERROR", "PHASE_TYPE_COMPLETE"]
        url = f"https://api-drive.mypikpak.com/drive/v1/tasks"
        params = {
            "type": "offline",
            "thumbnail_size": "SIZE_SMALL",
            "limit": size,
            "page_token": next_page_token,
            "filters": json.dumps({"phase": {"in": ",".join(phase)}}),
            "with": "reference_resource",
        }
        return self._request("get", url, params=params)

    def get_download_url(self, file_id):
        result = self._captcha_init(action=f"GET:/drive/v1/files/{file_id}")
        self.captcha_token = result.get("captcha_token")
        try:
            resp = self._request("get", f"https://api-drive.mypikpak.com/drive/v1/files/{file_id}?thumbnail_size=SIZE_LARGE")
            self.captcha_token = None
            return resp
        except Exception:
            self.captcha_token = None
            raise

    def get_task_status(self, task_id, file_id):
        try:
            infos = self.offline_list()
            if infos and infos.get("tasks", []):
                for task in infos.get("tasks", []):
                    if task_id == task.get("id"):
                        phase = task.get("phase", '')
                        if phase == "PHASE_TYPE_COMPLETE":
                            return "done"
                        elif phase == "PHASE_TYPE_ERROR":
                            return "error"
                        else:
                            return "downloading"
            if file_id:
                file_info = self.get_download_url(file_id)
                if file_info and file_info.get("id"):
                    return "done"
            return "not_found"
        except Exception:
            return "error"


if __name__ == '__main__':
    sp = Spider()
    sp.init()
    print(sp.homeVideoContent())
