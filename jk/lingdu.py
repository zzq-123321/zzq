# -*- coding: utf-8 -*-
import sys
import json
import re
import time

from urllib.parse import unquote

try:
    import requests
except Exception:
    requests = None

try:
    from base.spider import Spider as _Base
except Exception:
    class _Base(object):
        def isVideoFormat(self, url):
            return False
        def manualVideoCheck(self):
            return False


class Spider(_Base):
    OSS_CFG        = "https://minojson.oss-cn-beijing.aliyuncs.com/mino.json"
    HOST_FALLBACK  = "http://43.248.128.122:8080"
    UA             = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Mobile Safari/537.36 MINO/1.8.18")
    PAGE_SIZE       = 20

    # ===================== 解析接口配置 =====================
    # 网页解析接口（parse:1 嗅探用，按优先级排列）
    JX_PARSERS = [
        "https://jx.xmflv.com?url=",
        "https://jx.playerjy.com?url=",
        "https://bfq.txnp.cn/player?url=",
    ]

    QMSP_DIRECT_PLAY = True
    PLATFORM_SOURCES = ["qq", "qiyi", "mgtv", "youku", "bilibili"]
    ZYDJ_PARSER = "http://110.42.49.74:2222/parse/api.php?token=H9SzG8oX&url="

    # ===================== 认证解析配置 =====================
    # 登录凭据（游客账号，用于获取 parse API token）
    AUTH_PHONE = "13800138000"
    AUTH_CODE  = "1234"

    # 需要通过认证 parse API 解析的源
    AUTH_PARSE_SOURCES = ["rose", "duanju", "co", "zijianm3u8"]

    # 源名到 parse API from 参数的映射
    # co 和 zijianm3u8 不在 players 列表中，需要映射到同类的 parse API
    PARSE_FROM_MAP = {
        "rose":       "rose",
        "duanju":     "duanju",
        "co":         "1080P",
        "zijianm3u8": "duanju",
    }

    # 解析结果缓存时间（秒）- 避免重复解析同一集导致触发频率限制
    PARSE_CACHE_TTL = 3600  # 1小时

    # 解析失败重试次数和间隔
    PARSE_RETRY_COUNT = 2
    PARSE_RETRY_DELAY = 3  # 秒

    # ===================== 生命周期 =====================
    def getName(self):
        return "MINO零度影视"

    def init(self, extend=""):
        self._host = None
        self._cats = None
        self._players = None
        self._token = None
        self._token_expire = 0
        self._parse_cache = {}  # {ep_id: (url, expire_time)}
        self._s = requests.Session() if requests else None
        if self._s:
            self._s.headers.update({
                "User-Agent": self.UA,
                "Accept": "application/json, text/plain, */*",
            })
        _ = self.host
        _ = self.players
        return ""

    @property
    def host(self):
        if self._host:
            return self._host
        host = self.HOST_FALLBACK
        try:
            r = self._s.get(self.OSS_CFG, timeout=10)
            j = r.json()
            eps = j.get("endpoints") or (j.get("data") or {}).get("endpoints") or []
            for e in eps:
                if isinstance(e, str) and e.startswith("http"):
                    host = e.rstrip("/")
                    break
        except Exception:
            pass
        self._host = host
        return host

    @property
    def players(self):
        if self._players is not None:
            return self._players
        mp = {}
        try:
            j = self._api("/players")
            for k, v in (j.get("data") or {}).items():
                mp[v.get("player_from") or k] = v
        except Exception:
            pass
        self._players = mp
        return mp

    @property
    def cats(self):
        if self._cats is not None:
            return self._cats
        try:
            self._cats = self._api("/categories").get("data") or []
        except Exception:
            self._cats = []
        return self._cats

    def _api(self, path, params=None):
        url = self.host + "/api" + path
        r = self._s.get(url, params=params, timeout=20)
        return r.json()

    @staticmethod
    def _vod(item):
        return {
            "vod_id": str(item.get("vod_id") or ""),
            "vod_name": item.get("vod_name") or "",
            "vod_pic": item.get("vod_pic") or "",
            "vod_remarks": item.get("vod_remarks") or item.get("vod_sub") or "",
        }

    @staticmethod
    def _is_media(url):
        return bool(re.search(r"\.(m3u8|mp4|flv|ts)(\?|#|$)", str(url), re.I))

    @staticmethod
    def _fmt(url):
        u = str(url).lower()
        if ".m3u8" in u:
            return "application/x-mpegURL"
        if ".mp4" in u:
            return "video/mp4"
        return ""

    # ===================== 认证 & 解析 =====================
    def _get_token(self):
        """登录获取 JWT token，缓存到过期前 5 分钟"""
        if self._token and time.time() < self._token_expire - 300:
            return self._token
        try:
            r = self._s.post(
                self.host + "/api/auth/login",
                json={"phone": self.AUTH_PHONE, "code": self.AUTH_CODE},
                timeout=15,
            )
            j = r.json()
            if j.get("code") == 0:
                tk = (j.get("data") or {}).get("token") or {}
                self._token = tk.get("access_token", "")
                expires_in = tk.get("expires_in", 7200)
                self._token_expire = time.time() + expires_in
                return self._token
        except Exception:
            pass
        return None

    def _auth_parse(self, pfrom, ep_id):
        """调用认证 parse API 获取真实播放地址（带缓存和重试）"""
        # 缓存 key 用 pfrom + ep_id
        cache_key = pfrom + "|" + str(ep_id)
        now = time.time()

        # 检查缓存
        cached = self._parse_cache.get(cache_key)
        if cached:
            url, expire_at = cached
            if now < expire_at:
                return url
            else:
                # 过期了，删除缓存
                del self._parse_cache[cache_key]

        token = self._get_token()
        if not token:
            return None

        parse_from = self.PARSE_FROM_MAP.get(pfrom, pfrom)
        ep_id_decoded = unquote(str(ep_id))

        url = self._do_parse(parse_from, ep_id_decoded, token)
        if url:
            # 清理URL格式（去掉多余的 &.m3u8 后缀）
            url = self._cleanup_url(url)
            # 写入缓存
            self._parse_cache[cache_key] = (url, now + self.PARSE_CACHE_TTL)
            return url

        # 失败重试（可能触发了频率限制，等待后重试）
        for attempt in range(self.PARSE_RETRY_COUNT):
            time.sleep(self.PARSE_RETRY_DELAY)
            # 重新获取 token（可能 token 失效了）
            token = self._get_token()
            if not token:
                continue
            url = self._do_parse(parse_from, ep_id_decoded, token)
            if url:
                url = self._cleanup_url(url)
                self._parse_cache[cache_key] = (url, now + self.PARSE_CACHE_TTL)
                return url

        return None

    def _do_parse(self, parse_from, ep_id, token):
        """单次 parse API 调用"""
        try:
            r = self._s.post(
                self.host + "/api/parse",
                json={"from": parse_from, "url": ep_id},
                headers={"Authorization": "Bearer " + token},
                timeout=15,
            )
            j = r.json()
            if j.get("code") == 0:
                data = j.get("data")
                if isinstance(data, dict):
                    url = data.get("url") or ""
                    if url and url.startswith("http"):
                        return url
                elif isinstance(data, str) and data.startswith("http"):
                    return data
            # token 过期
            elif j.get("code") == 40110:
                self._token = None
                self._token_expire = 0
        except Exception:
            pass
        return None

    @staticmethod
    def _cleanup_url(url):
        """清理URL格式（当前保留原样，确保格式检测正常）"""
        # 注：服务端返回的URL末尾可能带有 &.m3u8 这样的冗余参数
        # 虽然不规范，但它有助于播放器识别m3u8格式，因此保留
        return url

    # ===================== 首页 =====================
    def homeContent(self, filter):
        result = {"class": [], "filters": {}}
        for c in self.cats:
            tid = str(c.get("type_id"))
            result["class"].append({
                "type_id": tid,
                "type_name": c.get("type_name") or tid,
            })
            vals = []
            try:
                ext = json.loads(c.get("type_extend") or "{}")
                for cn in (ext.get("class") or []):
                    vals.append({"n": cn, "v": cn})
            except Exception:
                pass
            if vals:
                result["filters"][tid] = [{"key": "class", "name": "类型", "value": vals}]
        return result

    def homeVideoContent(self):
        vods = []
        try:
            secs = self._api("/home/sections").get("data") or []
            for sec in secs:
                for it in (sec.get("items") or []):
                    vods.append(self._vod(it))
        except Exception:
            pass
        return {"list": vods}

    # ===================== 分类 =====================
    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        params = {"t": tid, "page": page}
        if extend and isinstance(extend, dict) and extend.get("class"):
            params["class"] = extend.get("class")
        elif extend and isinstance(extend, str):
            try:
                ext = json.loads(extend)
                if ext.get("class"):
                    params["class"] = ext.get("class")
            except Exception:
                pass
        try:
            data = self._api("/videos", params).get("data") or {}
            lst = [self._vod(x) for x in (data.get("list") or [])]
            total = int(data.get("total") or 0)
        except Exception:
            lst, total = [], 0
        pagecount = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE if total else page
        return {
            "list": lst,
            "page": page,
            "pagecount": pagecount,
            "limit": self.PAGE_SIZE,
            "total": total,
        }

    # ===================== 详情 =====================
    def detailContent(self, ids):
        vid = ids[0]
        d = self._api("/videos/" + str(vid)).get("data") or {}
        pf = (d.get("vod_play_from") or "").split("$$$")
        pu = (d.get("vod_play_url") or "").split("$$$")
        pl = self.players

        froms, urls = [], []
        source_types = []

        for i, f in enumerate(pf):
            if not f:
                continue
            eps = [e for e in (pu[i] if i < len(pu) else "").split("#") if "$" in e]
            if not eps:
                continue
            disp = (pl.get(f, {}) or {}).get("name") or f
            froms.append(disp)
            urls.append("#".join(eps))

            first = eps[0].split("$", 1)[1] if len(eps[0].split("$", 1)) > 1 else ""
            pfrom = None
            for k, v in pl.items():
                if (v.get("name") or k) == disp:
                    pfrom = k
                    break

            if "qmsp" in first:
                source_types.append(0)       # 臻彩4K 直链
            elif pfrom in self.PLATFORM_SOURCES and first.startswith("http"):
                source_types.append(1)       # 平台源
            elif pfrom == "zydj" and first.startswith("http"):
                source_types.append(2)       # 短剧
            elif pfrom in self.AUTH_PARSE_SOURCES or f in self.AUTH_PARSE_SOURCES:
                source_types.append(3)       # 认证解析源（rose/duanju/co/zijian）
            elif first.startswith("http"):
                source_types.append(4)       # 其他直链
            else:
                source_types.append(5)       # 未知

        idx = sorted(range(len(froms)), key=lambda k: (source_types[k], k))
        froms = [froms[k] for k in idx]
        urls = [urls[k] for k in idx]
        source_types = [source_types[k] for k in idx]

        content = (d.get("vod_content") or d.get("vod_blurb") or "")
        content = re.sub(r"<[^>]+>", "", content).strip()

        vod = {
            "vod_id": str(d.get("vod_id") or vid),
            "vod_name": d.get("vod_name") or "",
            "vod_pic": d.get("vod_pic") or "",
            "vod_year": d.get("vod_year") or "",
            "vod_area": d.get("vod_area") or "",
            "vod_class": d.get("vod_class") or "",
            "vod_actor": d.get("vod_actor") or "",
            "vod_director": d.get("vod_director") or "",
            "vod_content": content,
            "vod_play_from": "$$$".join(froms),
            "vod_play_url": "$$$".join(urls),
        }
        return {"list": [vod]}

    # ===================== 搜索 =====================
    def searchContent(self, key, quick, pg=1):
        # 过滤空关键词
        if not key or not key.strip():
            return {"list": [], "page": 1, "pagecount": 1, "limit": self.PAGE_SIZE, "total": 0}
        try:
            page = int(pg) if pg else 1
            data = self._api("/search", {"wd": key, "page": page}).get("data") or {}
            lst = [self._vod(x) for x in (data.get("list") or [])]
            total = int(data.get("total") or 0)
            # 使用 API 返回的实际 page_size 计算总页数
            ps = data.get("page_size") or self.PAGE_SIZE
            cur_page = int(data.get("page") or page)
            pagecount = (total + ps - 1) // ps if total else cur_page
        except Exception:
            lst, total = [], 0
            cur_page = 1
            ps = self.PAGE_SIZE
            pagecount = 1
        return {
            "list": lst,
            "page": cur_page,
            "pagecount": pagecount,
            "limit": ps,
            "total": total,
        }

    # ===================== 播放（修复核心） =====================
    def playerContent(self, flag, id, vipFlags):
        id = str(id)

        # 反查 player_from
        pfrom = flag
        for k, v in self.players.items():
            if (v.get("name") or k) == flag:
                pfrom = k
                break

        # 同时检查原始 from 名（vod_play_from 中的值）
        raw_from = flag
        for f in self.AUTH_PARSE_SOURCES:
            pl = self.players.get(f, {})
            if (pl.get("name") or f) == flag:
                raw_from = f
                break

        base_header = {"User-Agent": self.UA}

        # 1) qmsp 臻彩4K -> 获取302真实地址
        if "qmsp" in id and self.QMSP_DIRECT_PLAY:
            try:
                r = self._s.get(id, timeout=20, allow_redirects=False)
                if r.status_code in [301, 302, 307, 308]:
                    location = r.headers.get("Location", "")
                    if location:
                        if location.startswith("//"):
                            location = "https:" + location
                        return self._result(location, base_header)
            except Exception:
                pass
            return self._result(id, base_header)

        # 2) 平台源（TX/奇艺/优酷/芒果/B站）-> 走网页解析接口嗅探
        if id.startswith("http"):
            if self._is_media(id):
                return self._result(id, base_header)
            if pfrom in self.PLATFORM_SOURCES:
                jx_url = self.JX_PARSERS[0] + id
                return {
                    "parse": 1,
                    "playUrl": "",
                    "url": jx_url,
                    "header": base_header,
                }
            return {
                "parse": 1,
                "playUrl": "",
                "url": id,
                "header": base_header,
            }

        # 3) zydj 短剧 -> 外部聚合解析
        if pfrom == "zydj" or raw_from == "zydj":
            try:
                r = self._s.get(self.ZYDJ_PARSER + unquote(id), timeout=25)
                j = r.json()
                url = (j.get("url") or (j.get("data") or {}).get("url")
                       if isinstance(j.get("data"), dict) else j.get("data"))
                if url and isinstance(url, str):
                    return self._result(url, base_header)
            except Exception:
                pass

        # 4) 认证解析源（rose/duanju/co/zijianm3u8）
        #    通过登录获取 token，调用 /api/parse 获取真实播放地址
        if pfrom in self.AUTH_PARSE_SOURCES or raw_from in self.AUTH_PARSE_SOURCES:
            actual_from = pfrom if pfrom in self.AUTH_PARSE_SOURCES else raw_from
            url = self._auth_parse(actual_from, id)
            if url:
                return self._result(url, base_header)
            # 认证解析失败，继续尝试其他方法

        # 5) 兜底
        return {
            "parse": 1,
            "playUrl": "",
            "url": id,
            "header": base_header,
        }

    def _result(self, url, header):
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": header,
            "format": self._fmt(url),
            "contentType": self._fmt(url),
        }

    def isVideoFormat(self, url):
        return self._is_media(url)

    def manualVideoCheck(self):
        return False


if __name__ == "__main__":
    s = Spider()
    s.init()
    print("HOST =", s.host)
    print("加载完成")
