# -*- coding: utf-8 -*-
"""
青麦视频 (https://www.qingmaisp.com) Python Spider
站点类型: Vue/Nuxt SPA

API 列表:
- /api/auth/deviceIdLogin: 游客 token（form-urlencoded）
- /api/v1/pc/screen/screenType: 分类树（含子分类：地区/类型/年份）
- /api/v1/pc/screen/screenMovie: 分类内容分页（支持 typeId/region/classify/year/sort）
- /api/v1/pc/play/movieDetails: 影片详情 + 播放地址（含 VIP 集数）
- /api/v1/pc/search/tipSearch: 搜索提示（form-urlencoded）
- /api/v1/pc/index/navPage: 首页导航
- /api/v1/pc/play/guessLike: 猜你喜欢

关键发现:
1. screenMovie 支持分页，总数据量 4653+ 条
2. screenMovie 的 classify/region 参数接受中文名称（如 "剧情"、"美国"），不接受 ID
3. movieDetails 对 VIP 集数也返回真实 m3u8 地址，lock 仅为 UI 标记
4. 播放地址 qmsp.qmspapp.cn/ts/xxx 302 跳转到 eos 云存储 CDN，不需要 cookies
5. 现代接口已不再对 m3u8 做 AES-128 加密，切片为明文 TS，直接可播
6. 游客 token 可获取所有集数（含 VIP）的播放地址
7. 清晰度以 "4K*url~HD*url~LD*url" 形式返回；但绝大多数片源只有 HD~LD，
   只有少数片源带 4K。因此播放源必须按接口“实际返回”的清晰度动态生成，
   否则会出现“青麦4K”源其实播放的是 1080P 的假 4K 问题。

【4K 播放源修复要点】
- detailContent 不再写死 3 路固定源，而是解析 movieDetails 返回的 url，
  仅对“真实存在”的清晰度（4K/HD/LD）生成对应线路（有 4K 才显示青麦4K）。
- playerContent 在请求的质量缺失时，自动降级到最佳可用清晰度，
  保证任意线路都不会返回空地址 / 解析失败。
"""

import sys
import json
import base64
import time
import re

try:
    import requests as rq
except ImportError:
    rq = None

sys.path.append('..')

try:
    from base.spider import Spider as _Base
except Exception:
    class _Base(object):
        def isVideoFormat(self, url):
            return False
        def manualVideoCheck(self):
            return False


class Spider(_Base):

    HOST = "https://www.qingmaisp.com"
    API = HOST + "/api"

    UA = (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    )

    CLASSES = [
        {"type_name": "电影", "type_id": "M16"},
        {"type_name": "电视剧", "type_id": "M15"},
        {"type_name": "综艺", "type_id": "M18"},
        {"type_name": "动漫", "type_id": "M17"},
        {"type_name": "纪录片", "type_id": "M416"},
    ]

    SORT_OPTIONS = [
        {"n": "最新", "v": "NEWEST"},
        {"n": "最热", "v": "HOT"},
    ]

    # 清晰度优先级：4K > HD > LD
    QUALITY_ORDER = ["4K", "HD", "LD"]
    # 清晰度 -> 播放源线路名
    QUALITY_LABEL = {
        "4K": "青麦4K",
        "HD": "青麦1080P",
        "LD": "青麦720P",
    }

    def __init__(self):
        self._s = None
        self._token = None
        self._token_expire = 0
        self._device_id = ""
        self._detail_cache = {}
        self._filters = {}

    def getName(self):
        return "青麦视频"

    def init(self, extend=""):
        self._device_id = self._gen_device_id()
        self._s = rq.Session()
        self._s.headers.update({
            "User-Agent": self.UA,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": self.HOST,
            "Referer": self.HOST + "/",
            "client": "pc",
            "useclient": "pc",
            "devicetype": "web",
            "deviceId": self._device_id,
        })
        try:
            self._s.get(self.HOST + "/", timeout=10)
        except Exception:
            pass
        self._ensure_token()
        self._build_filters()
        return ""

    # ===================== Token =====================

    @staticmethod
    def _gen_device_id():
        ua = Spider.UA
        return base64.b64encode(ua.encode("utf-8")).decode("utf-8")[:16]

    def _ensure_token(self):
        now = time.time()
        if self._token and now < self._token_expire:
            return self._token
        try:
            r = self._s.post(
                self.API + "/auth/deviceIdLogin",
                data={"deviceId": self._device_id},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "devicetype": "web",
                },
                timeout=10,
            )
            j = r.json()
            if j.get("code") == 200 and j.get("data"):
                self._token = j["data"]
                self._token_expire = now + 3600
                self._s.headers.update({"token": self._token})
                return self._token
        except Exception:
            pass
        return None

    # ===================== API =====================

    def _post_json(self, path, body=None):
        self._ensure_token()
        try:
            r = self._s.post(
                self.API + path,
                data=json.dumps(body or {}),
                timeout=15,
            )
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {}

    def _post_form(self, path, data=None):
        self._ensure_token()
        try:
            r = self._s.post(
                self.API + path,
                data=data or {},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {}

    def _screen_movie(self, type_id, page=1, size=20, year="", sort="NEWEST", region="", classify=""):
        condition = {
            "classify": classify or None,
            "region": region or None,
            "source": "0",
            "sreecnTypeEnum": sort or "NEWEST",
            "typeId": type_id,
            "year": year or None,
        }
        body = {
            "condition": condition,
            "pageNum": page,
            "pageSize": size,
        }
        return self._post_json("/v1/pc/screen/screenMovie", body)

    # ===================== 子分类筛选器 =====================

    def _build_filters(self):
        data = self._post_json("/v1/pc/screen/screenType", {})
        filters = {}
        if data.get("code") == 200 and data.get("data"):
            for cat in data["data"]:
                cat_id = cat["id"]
                cat_filters = []
                for group in cat.get("children", []):
                    group_name = group.get("name", "")
                    children = group.get("children", [])
                    if not children:
                        continue
                    if group_name == "地区":
                        key = "region"
                    elif group_name == "类型":
                        key = "classify"
                    elif group_name == "年份":
                        key = "year"
                    else:
                        continue
                    values = [{"n": "全部", "v": ""}]
                    for sub in children:
                        name = sub.get("name", "")
                        if name:
                            if key == "year":
                                values.append({"n": name, "v": name})
                            else:
                                values.append({"n": name, "v": name})
                    cat_filters.append({"key": key, "name": group_name, "value": values})
                cat_filters.append({"key": "sort", "name": "排序", "value": self.SORT_OPTIONS})
                filters[cat_id] = cat_filters
        if not filters:
            filters = self._fallback_filters()
        self._filters = filters

    @staticmethod
    def _fallback_filters():
        regions = ["美国", "英国", "韩国", "日本", "泰国", "内地", "中国香港", "中国台湾", "其他"]
        types = ["剧情", "喜剧", "动作", "冒险", "爱情", "动画", "歌舞", "医疗", "科幻",
                 "奇幻", "悬疑", "惊悚", "犯罪", "传记", "历史", "战争", "灾难", "美食",
                 "真人秀", "脱口秀"]
        years = ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018",
                 "2017", "2016", "2015", "2014", "2013", "2012", "2011", "2010"]
        cat_ids = ["M16", "M15", "M17", "M18", "M416"]
        filters = {}
        for cid in cat_ids:
            filters[cid] = [
                {"key": "region", "name": "地区", "value": [{"n": "全部", "v": ""}] + [{"n": r, "v": r} for r in regions]},
                {"key": "classify", "name": "类型", "value": [{"n": "全部", "v": ""}] + [{"n": t, "v": t} for t in types]},
                {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] + [{"n": y, "v": y} for y in years]},
                {"key": "sort", "name": "排序", "value": Spider.SORT_OPTIONS},
            ]
        return filters

    # ===================== 首页 =====================

    def homeContent(self, filter):
        return {
            "class": self.CLASSES,
            "filters": self._filters,
        }

    def homeVideoContent(self):
        data = self._screen_movie("M", 1, 20, "", "NEWEST")
        videos = []
        if data.get("code") == 200 and data.get("data"):
            for item in data["data"].get("records", []):
                v = self._build_card(item)
                if v:
                    videos.append(v)
        return {"list": videos}

    # ===================== 分类 =====================

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if pg else 1
        except Exception:
            pg = 1

        ext = {}
        if extend:
            if isinstance(extend, dict):
                ext = extend
            elif isinstance(extend, str):
                try:
                    ext = json.loads(extend)
                except Exception:
                    ext = {}

        year = ext.get("year", "")
        sort = ext.get("sort", "NEWEST")
        region = ext.get("region", "")
        classify = ext.get("classify", "")

        data = self._screen_movie(tid, pg, 20, year, sort, region, classify)
        videos = []
        pagecount = 1
        total = 0

        if data.get("code") == 200 and data.get("data"):
            d = data["data"]
            for item in d.get("records", []):
                v = self._build_card(item)
                if v:
                    videos.append(v)
                    self._cache_detail(v["vod_id"], self._build_detail_from_card(item))
            total = d.get("total", 0)
            pagecount = d.get("pages", 1)

        return {
            "list": videos,
            "page": pg,
            "pagecount": pagecount,
            "limit": 20,
            "total": total,
        }

    # ===================== 详情 =====================

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = ids[0]

        body = {
            "id": str(vod_id),
            "playerId": 93,
            "userId": 0,
            "episodeId": None,
            "typeId": "M",
        }
        data = self._post_json("/v1/pc/play/movieDetails", body)

        vod = dict(self._detail_cache.get(vod_id, {}))
        vod["vod_id"] = str(vod_id)
        vod.setdefault("vod_name", "")
        vod.setdefault("vod_pic", "")
        vod.setdefault("type_name", "")
        vod.setdefault("vod_year", "")
        vod.setdefault("vod_area", "")
        vod.setdefault("vod_remarks", "")
        vod.setdefault("vod_actor", "")
        vod.setdefault("vod_director", "")
        vod.setdefault("vod_content", "")

        if data.get("code") == 200 and data.get("data"):
            d = data["data"]

            if not vod.get("vod_name"):
                vod["vod_name"] = d.get("name", "")
            vod["vod_remarks"] = d.get("remarks", "") or vod.get("vod_remarks", "")

            # 解析该影片“真实可用”的清晰度（4K/HD/LD），
            # 只有接口真的返回了 4K，才生成“青麦4K”线路。
            avail = self._qualities_from_url(d.get("url", ""))

            ep_list = d.get("episodeList", [])
            if ep_list:
                episodes = []
                for ep in ep_list:
                    ep_id = str(ep.get("id", ""))
                    ep_num = ep.get("episodeNum", "")
                    ep_name = ep.get("episode", "")
                    label = "第{}集".format(ep_num) if ep_num else ep_name
                    episodes.append("{}${}_{}".format(label, vod_id, ep_id))

                ep_str = "#".join(episodes)
                if avail:
                    # 有可用清晰度：按真实清晰度生成线路
                    labels = [self.QUALITY_LABEL[q] for q in self.QUALITY_ORDER if q in avail]
                    vod["vod_play_from"] = "$$$".join(labels)
                    # 三路共用同一份集数占位（playerContent 会按线路重新拉取对应质量）
                    vod["vod_play_url"] = "$$$".join([ep_str] * len(labels))
                else:
                    # 未知清晰度：兜底写死三路，交给 playerContent 自适应
                    vod["vod_play_from"] = "青麦4K$$$青麦1080P$$$青麦720P"
                    vod["vod_play_url"] = "{}$$${}$$${}".format(ep_str, ep_str, ep_str)
            else:
                url = d.get("url", "")
                if url:
                    if avail:
                        labels = [self.QUALITY_LABEL[q] for q in self.QUALITY_ORDER if q in avail]
                        groups = []
                        for q in labels:
                            qk = self._quality_key_of_label(q)
                            u = self._parse_quality_url(url, qk)
                            if u:
                                groups.append("正片${}".format(u))
                        if not groups:
                            groups = ["正片${}".format(self._parse_quality_url(url) or url)]
                        vod["vod_play_from"] = "$$$".join(labels)
                        vod["vod_play_url"] = "$$$".join(groups)
                    else:
                        # 无法识别质量：把原始地址分别塞给三路，由 playerContent 兜底
                        vod["vod_play_from"] = "青麦4K$$$青麦1080P$$$青麦720P"
                        vod["vod_play_url"] = "正片${}$$$正片${}$$$正片${}".format(
                            self._parse_quality_url(url, "4K") or self._parse_quality_url(url) or url,
                            self._parse_quality_url(url, "HD") or self._parse_quality_url(url) or url,
                            self._parse_quality_url(url, "LD") or self._parse_quality_url(url) or url,
                        )
                else:
                    vod["vod_play_from"] = "青麦4K$$$青麦1080P$$$青麦720P"
                    vod["vod_play_url"] = "正片${}_{}$$$正片${}_{}$$$正片${}_{}".format(
                        vod_id, vod_id, vod_id, vod_id, vod_id, vod_id)
        else:
            vod["vod_play_from"] = "青麦4K$$$青麦1080P$$$青麦720P"
            vod["vod_play_url"] = "正片${}$$$正片${}$$$正片${}".format(vod_id, vod_id, vod_id)

        return {"list": [vod]}

    @staticmethod
    def _quality_key_of_label(label):
        for k, v in Spider.QUALITY_LABEL.items():
            if v == label:
                return k
        return "HD"

    # ===================== 搜索 =====================

    def searchContent(self, key, quick, pg="1"):
        movies = []
        seen = set()

        result = self._post_form("/v1/pc/search/tipSearch", {"value": key})
        if result.get("code") == 200 and result.get("data"):
            for item in result["data"]:
                name = item.get("value", "")
                mid = item.get("movieId") or item.get("id", "")
                if mid:
                    mid = str(mid)
                    if mid not in seen:
                        seen.add(mid)
                        movies.append({
                            "vod_id": mid,
                            "vod_name": name,
                            "vod_pic": "",
                        })

        if len(movies) < 10:
            type_ids = ["M", "M16", "M15", "M17", "M18"]
            key_lower = key.lower()
            for tid in type_ids:
                if len(movies) >= 30:
                    break
                try:
                    data = self._screen_movie(tid, 1, 50, "", "NEWEST")
                    if data.get("code") == 200 and data.get("data"):
                        for item in data["data"].get("records", []):
                            name = item.get("name", "")
                            mid = str(item.get("id", ""))
                            if key_lower in name.lower() and mid not in seen:
                                seen.add(mid)
                                v = self._build_card(item)
                                if v:
                                    movies.append(v)
                                    self._cache_detail(mid, self._build_detail_from_card(item))
                except Exception:
                    pass

        return {
            "list": movies,
            "page": 1,
            "pagecount": 1,
            "limit": len(movies),
            "total": len(movies),
        }

    # ===================== 播放 =====================

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": self.UA,
            "Referer": self.HOST + "/",
        }

        if str(id).startswith("http"):
            return {
                "parse": 0,
                "playUrl": "",
                "url": id,
                "header": headers,
                "format": "application/x-mpegURL" if ".m3u8" in id else "",
                "contentType": "application/x-mpegURL" if ".m3u8" in id else "",
            }

        movie_id = ""
        episode_id = str(id)
        if "_" in episode_id:
            parts = episode_id.split("_", 1)
            movie_id = parts[0]
            episode_id = parts[1]

        if not movie_id:
            return {
                "parse": 1,
                "playUrl": "",
                "url": self.HOST + "/#/m/movie/" + episode_id,
                "header": headers,
            }

        body = {
            "id": str(movie_id),
            "playerId": 93,
            "userId": 0,
            "episodeId": str(episode_id),
            "typeId": "M",
        }
        data = self._post_json("/v1/pc/play/movieDetails", body)

        if data.get("code") == 200 and data.get("data"):
            d = data["data"]
            url = d.get("url", "")
            if url:
                preferred = self._flag_to_quality(flag)
                real_url = self._parse_quality_url(url, preferred)
                # 【修复】请求的质量在接口里不存在时，自动降级到最佳可用清晰度，
                # 避免“青麦4K”等线路拿到空地址导致解析失败。
                if not real_url:
                    for q in self.QUALITY_ORDER:
                        real_url = self._parse_quality_url(url, q)
                        if real_url:
                            break
                if real_url:
                    resolved = self._resolve_redirect(real_url)
                    if resolved:
                        real_url = resolved
                    return {
                        "parse": 0,
                        "playUrl": "",
                        "url": real_url,
                        "header": headers,
                        "format": "application/x-mpegURL",
                        "contentType": "application/x-mpegURL",
                    }

        return {
            "parse": 1,
            "playUrl": "",
            "url": self.HOST + "/#/m/movie/" + movie_id,
            "header": headers,
        }

    def _resolve_redirect(self, url):
        try:
            r = self._s.get(url, allow_redirects=False, timeout=10,
                           headers={"User-Agent": self.UA, "Referer": self.HOST + "/"})
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location", "")
                if loc:
                    return loc
        except Exception:
            pass
        return ""

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def close(self):
        self.destroy()

    # ===================== 辅助方法 =====================

    @staticmethod
    def _build_card(item):
        mid = item.get("id") or item.get("movieId") or item.get("relationId")
        if not mid:
            return None
        mid = str(mid)
        remarks = item.get("remarks", "")
        if not remarks:
            total = item.get("totalEpisode", 0)
            if total and total > 1:
                remarks = "{}集".format(total)
        return {
            "vod_id": mid,
            "vod_name": item.get("name", ""),
            "vod_pic": item.get("cover", ""),
            "vod_remarks": remarks,
        }

    @staticmethod
    def _build_detail_from_card(item):
        vod = {
            "vod_id": str(item.get("id") or item.get("movieId", "")),
            "vod_name": item.get("name", ""),
            "vod_pic": item.get("cover", ""),
            "type_name": item.get("classify", ""),
            "vod_year": str(item.get("year", "")) if item.get("year") else "",
            "vod_area": item.get("area", ""),
            "vod_actor": item.get("star", ""),
            "vod_director": item.get("director", ""),
            "vod_content": item.get("desc", item.get("introduce", "")),
        }
        total = item.get("totalEpisode", 0)
        if total and total > 1:
            vod["vod_remarks"] = item.get("remarks", "") or "{}集".format(total)
        else:
            vod["vod_remarks"] = item.get("remarks", "")
        return vod

    def _cache_detail(self, vod_id, vod_data):
        vod_id = str(vod_id)
        if vod_id in self._detail_cache:
            existing = self._detail_cache[vod_id]
            if existing.get("vod_content") and len(existing["vod_content"]) > 10:
                if not vod_data.get("vod_content"):
                    return
        self._detail_cache[vod_id] = vod_data

    @staticmethod
    def _flag_to_quality(flag):
        flag_lower = (flag or "").lower()
        if "4k" in flag_lower:
            return "4K"
        if "720" in flag_lower or "ld" in flag_lower:
            return "LD"
        return "HD"

    @staticmethod
    def _qualities_from_url(url_str):
        """从 "4K*url~HD*url~LD*url" 中解析出“真实存在”的清晰度列表（按 4K>HD>LD 顺序）。"""
        if not url_str:
            return []
        sep = "～" if "～" in url_str else "~"
        found = []
        for part in url_str.split(sep):
            if "*" in part:
                q = part.split("*", 1)[0]
                if q in Spider.QUALITY_ORDER and q not in found:
                    found.append(q)
        return found

    @staticmethod
    def _parse_quality_url(url_str, preferred=""):
        if not url_str:
            return ""
        if "～" not in url_str and "~" not in url_str:
            return url_str

        sep = "～" if "～" in url_str else "~"
        parts = url_str.split(sep)

        quality_map = {}
        for part in parts:
            if "*" in part:
                q, u = part.split("*", 1)
                quality_map[q] = u

        if preferred and preferred in quality_map:
            return quality_map[preferred]

        for quality in ["4K", "HD", "LD"]:
            if quality in quality_map:
                return quality_map[quality]

        if parts:
            first = parts[0]
            if "*" in first:
                return first.split("*", 1)[1]
            return first
        return url_str


if __name__ == "__main__":
    s = Spider()
    s.init()

    print("=== 青麦视频 Spider 测试 ===")
    print("站点:", s.HOST)
    print("Token:", s._token)

    home = s.homeContent("")
    print("\n分类数量:", len(home["class"]))
    for c in home["class"]:
        print("  [{}] {}".format(c["type_id"], c["type_name"]))
    print("筛选器分类:", list(home["filters"].keys()))
    if home["filters"]:
        first_key = list(home["filters"].keys())[0]
        print("  {} 的筛选器:".format(first_key))
        for f in home["filters"][first_key]:
            vals = [v["n"] for v in f["value"][:5]]
            print("    {} ({}): {} ...".format(f["key"], f["name"], vals))

    hv = s.homeVideoContent()
    print("\n首页推荐: {} 条".format(len(hv["list"])))
    if hv["list"]:
        print("  第一条: {} ({})".format(hv["list"][0].get("vod_name"), hv["list"][0].get("vod_id")))

    cat = s.categoryContent("M16", 1, "", {"region": "美国", "classify": "剧情", "year": "2025", "sort": "NEWEST"})
    print("\n电影(美国+剧情+2025): {} 条，第{}/{}页".format(cat["total"], cat["page"], cat["pagecount"]))
    for i, m in enumerate(cat["list"][:5]):
        print("  {}. {} ({}) {}".format(i+1, m.get("vod_name"), m.get("vod_id"), m.get("vod_remarks")))

    cat2 = s.categoryContent("M16", 1, "", "")
    print("\n电影(全部): {} 条，第{}/{}页".format(cat2["total"], cat2["page"], cat2["pagecount"]))

    cat3 = s.categoryContent("M16", 2, "", "")
    print("第2页: {} 条".format(len(cat3["list"])))

    if cat2["list"]:
        vid = cat2["list"][0]["vod_id"]
        detail = s.detailContent([vid])
        if detail["list"]:
            d = detail["list"][0]
            print("\n详情:", d.get("vod_name"))
            print("  年份:", d.get("vod_year"))
            print("  地区:", d.get("vod_area"))
            print("  播放源:", d.get("vod_play_from"))
            play_url = d.get("vod_play_url", "")
            print("  播放地址:", play_url[:120])

            sources = d.get("vod_play_from", "").split("$$$")
            url_groups = d.get("vod_play_url", "").split("$$$")
            for si, (src, grp) in enumerate(zip(sources, url_groups)):
                eps = grp.split("#")
                print("\n  播放源 [{}] - {} 集".format(src, len(eps)))
                if eps and "$" in eps[0]:
                    ep_val = eps[0].split("$")[1]
                    for qf in sources:
                        pc = s.playerContent(qf, ep_val, [])
                        print("    {} -> parse={} url={}...".format(qf, pc["parse"], pc.get("url", "")[:80]))

    search = s.searchContent("外滩", False)
    print("\n搜索'外滩': {} 条".format(len(search["list"])))
    for i, m in enumerate(search["list"][:5]):
        print("  {}. {} ({})".format(i+1, m.get("vod_name"), m.get("vod_id")))

    print("\n=== VIP影片测试 ===")
    detail = s.detailContent(['832224'])
    if detail['list']:
        d = detail['list'][0]
        print("片名:", d.get("vod_name"))
        print("播放源:", d.get("vod_play_from"))
        url_groups = d["vod_play_url"].split("$$$")
        sources = d["vod_play_from"].split("$$$")
        for src, grp in zip(sources, url_groups):
            eps = grp.split("#")
            print("\n  [{}] {} 集".format(src, len(eps)))
            for ep in eps[:3]:
                name, val = ep.split("$", 1)
                print("    {} -> {}".format(name, val))

        print("\n第1集 各清晰度:")
        ep1_val = url_groups[0].split("#")[0].split("$")[1]
        for qf in sources:
            pc = s.playerContent(qf, ep1_val, [])
            print("  {} -> parse={} url={}...".format(qf, pc["parse"], pc.get("url", "")[:80]))

    print("\n测试完成")
