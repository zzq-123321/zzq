# -*- coding: utf-8 -*-
"""
爱壹帆影视 (iyf.lv) Spider —— TVBox / CatVod 框架
===================================================
现场重建结论 (2026-09-06):
  * 站点: https://www.iyf.lv  (m3u8 CDN: m3u8.vhmzy.com)
  * 分类路由: /t/1 电影 /t/2 剧集 /t/3 综艺 /t/4 动漫
        |  4K(type_id=4k): 站点无独立 4K 路由, 取首页 "4K精选🎆" 栏目模块
  * 标签路由: /label/new/ 更新  /label/hot/ 热榜
  * 搜索路由: /s/{关键词}-------------.html  (关键词空格用 + 连接, 末尾 13 个 -)
  * 列表卡片两种布局:
        - 首页/分类: a.module-poster-item  (图 data-original|src, 标题 .module-poster-item-title, 备注 .module-item-note)
        - 热榜/搜索: div.module-card-item  (图 data-original, 标题 .module-card-item-title, 备注 .module-item-note)
  * 详情页选集: .module-tab-item 线路名 + .module-play-list 内 a.module-play-list-link -> /iyfplay/{id}-{线路}-{集}/
  * 播放页: 内嵌 var player_aaaa={"url":"https://m3u8.vhmzy.com/.../index.m3u8", "encrypt":0, ...}
            真实播放源为该 url (HLS, AES-128 加密, 播放器自动解密, 直接 parse:0 返回即可)
  * 反爬机制(实测): 站点接入 Cloudflare。单请求均无阻(bot UA / 无 Cookie / 无 Referer 均可返回);
        但高频连续请求偶发质询页(返回 200 却无 player_aaaa / 无卡片)——已用 _get 清空会话 Cookie 重试绕过。
        player_aaaa 中 encrypt=0, url 明文, 无需 JS 解密; 真实播放源为 HLS(AES-128 加密, 播放器自动解密)。
        仍需: 维持会话 Cookie + 标准 UA/Referer + 正确解析两套卡片布局 + 括号级精确提取 player_aaaa。
  * 分页: 站点分页为"假分页" —— /t/2/page/2/、/label/hot/page/2/、搜索 /page/2/ 均返回与第 1 页完全相同内容。
        故 pg>1 直接返回空列表, 避免 TVBox 无限翻页刷出重复数据。

鸿蒙手机导入方式 (影视仓 / 番茄影视仓 / 猫影视 等 CatVod 系 App, 鸿蒙 4.x 可直接装 Android 版):
  1) 依赖: 运行时需 requests + bs4 (绝大多数 CatVod App 已随 Python 引擎内置, 无需额外安装)。
  2) 落地: 将此文件以「爱壹帆影视.py」命名, 放入 App 的 spider 目录 (或 App 设置里"jar/spider 仓库"指向的本地路径),
           也可在 App 的「爬虫/配置」里粘贴本文件直链 (支持 .py 订阅) 后刷新加载。
  3) 生效: 在 App 站点/配置中启用名为「爱壹帆」的源即可。home=推荐, 分类=电影/剧集/综艺/动漫/更新/热榜, 可直接播放 m3u8。
  4) 若加载后报 No module named 'requests'/'bs4', 说明该 App 未内置 Python 依赖, 请换用内置依赖的 CatVod 系 App 或通过 App 的「依赖库」入口安装 requests+beautifulsoup4。
"""

import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

try:
    from base.spider import Spider
except ImportError:
    # 本地测试时提供一个最小基类, 便于脱离框架直接跑通逻辑
    class Spider:
        def init(self, extend=""):
            pass

        def getName(self):
            return "base"

        def fetch(self, url, **kwargs):
            return requests.get(url, timeout=kwargs.get("timeout", 15), headers=kwargs.get("headers"))


# 搜索关键词与后缀之间的分隔横线数量 (与站点生成的链接一致)
SEARCH_DASH = "-" * 13


class Spider(Spider):
    def init(self, extend=""):
        self.host = "https://www.iyf.lv"
        # 维持会话, 自动携带 server_session cookie (实测不强制, 但带上更稳)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 11; SAMSUNG SM-G973U) AppleWebKit/537.36 "
                "(KHTML, like Gecko) SamsungBrowser/14.2 Chrome/87.0.4280.141 Mobile Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        # 播放源(m3u8)请求头: 带 Referer 与 UA, 大部分 CDN 不校验, 但带上更保险
        self.play_headers = {
            "User-Agent": self.session.headers["User-Agent"],
            "Referer": self.host + "/",
            "Origin": self.host,
        }

    # ---------------- 基础请求封装 (绕过 Cloudflare 质询 + 重试) ----------------
    @staticmethod
    def _is_challenge(text):
        """检测 Cloudflare / 站点软限流质询页 (返回 200 但无真实内容)."""
        if not text:
            return True
        markers = ("just a moment", "cf-mitigated", "challenge-platform",
                   "_cf_chl_", "verify you are human", "enable javascript")
        low = text.lower()
        return any(m in low for m in markers)

    def _get(self, url, headers=None, timeout=20, retries=3):
        last = None
        for attempt in range(retries + 1):
            try:
                r = self.session.get(url, headers=headers, timeout=timeout)
                # 正常 200 且非质询页 -> 直接返回
                if r.status_code == 200 and not self._is_challenge(r.text):
                    return r
                last = r
                # 触发质询 / 限流: 清空会话 Cookie 重建身份后重试
                if r.status_code in (403, 429, 503) or self._is_challenge(r.text):
                    self.session.cookies.clear()
                    time.sleep(1.5)
                    continue
            except Exception as e:
                last = e
                time.sleep(1)
        if isinstance(last, Exception):
            raise last
        return last

    def _soup(self, url, headers=None):
        return BeautifulSoup(self._get(url, headers).text, "html.parser")

    # ---------------- 分类 (首页左栏) ----------------
    def homeContent(self, filter):
        classes = [
            {"type_name": "电影", "type_id": "1"},
            {"type_name": "剧集", "type_id": "2"},
            {"type_name": "综艺", "type_id": "3"},
            {"type_name": "动漫", "type_id": "4"},
            {"type_name": "4K", "type_id": "4k"},
            {"type_name": "更新", "type_id": "new"},
            {"type_name": "热榜", "type_id": "hot"},
        ]
        # 站点无筛选参数 UI, 返回空 filters
        return {"class": classes, "filters": {}}

    # ---------------- 首页推荐 ----------------
    def homeVideoContent(self):
        try:
            soup = self._soup(self.host + "/")
            # 取激活 tab 下的推荐卡片; 兜底取前 20 个海报卡
            items = soup.select(".tab-list.active a.module-poster-item")
            if not items:
                items = soup.select("a.module-poster-item")[:20]
            vods, seen = [], set()
            for el in items:
                v = self._parse_card(el)
                if v and v["vod_id"] not in seen:
                    seen.add(v["vod_id"])
                    vods.append(v)
            return {"list": vods}
        except Exception:
            return {"list": []}

    # ---------------- 分类 / 标签 列表 ----------------
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1

        # 站点为"假分页", 第 2 页起与第 1 页完全相同 -> 直接返回空, 防止 TVBox 死循环刷重复
        if pg > 1:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

        if tid == "new":
            url = f"{self.host}/label/new/"
        elif tid == "hot":
            url = f"{self.host}/label/hot/"
        elif tid == "4k":
            # 站点无独立 4K 路由(/label/4k/ 为无效空页), 但首页有 "4K精选🎆" 栏目模块。
            # 4K 分类页 = 解析首页 4K精选 模块内的影片卡片
            #   (实测示例: 楚汉传奇 / 凡人修仙传 / 扫毒风暴 / 逐玉 / 利剑·玫瑰 / 少帅 / 一笑随歌 / 水龙吟)。
            home_soup = self._soup(self.host + "/")
            vods = self._parse_home_module(home_soup, "4K精选")
            return {
                "list": vods,
                "page": pg,
                "pagecount": 1,
                "limit": len(vods) or 20,
                "total": len(vods),
            }
        else:
            url = f"{self.host}/t/{tid}/"

        try:
            soup = self._soup(url)
            vods = self._parse_list(soup)
            return {
                "list": vods,
                "page": pg,
                "pagecount": 1,           # 单页站点
                "limit": len(vods) or 20,
                "total": len(vods),
            }
        except Exception:
            return {"list": []}

    # ---------------- 详情 + 选集 ----------------
    def detailContent(self, ids):
        try:
            url = ids[0]
            if not url.startswith("http"):
                url = self.host + url
            soup = self._soup(url)

            vod = {"vod_id": ids[0]}

            h1 = soup.select_one("h1")
            vod["vod_name"] = h1.get_text(strip=True) if h1 else "未知"

            # 海报: 优先 data-original, 否则 src
            pic = ""
            img = soup.select_one(".module-info-poster img.lazyload") \
                or soup.select_one(".module-info-poster img") \
                or soup.select_one(".module-item-pic img") \
                or soup.select_one("img.lazyload")
            if img:
                pic = img.get("data-original") or img.get("src") or ""
                if pic in ("", "/loading.png"):
                    pic = ""
            if pic and not pic.startswith("http"):
                pic = self.host + pic
            vod["vod_pic"] = pic

            # 简介
            intro = soup.select_one(".module-info-introduction-content") \
                or soup.select_one(".module-info-introduction-text") \
                or soup.select_one(".module-info-introduction")
            vod["vod_content"] = intro.get_text(strip=True) if intro else ""

            # 演职员 / 年份等
            info = {}
            for item in soup.select(".module-info-item"):
                t = item.select_one(".module-info-item-title")
                c = item.select_one(".module-info-item-content")
                if t and c:
                    info[t.get_text(strip=True).replace("：", "").replace(":", "")] = c.get_text(strip=True)
            vod["vod_actor"] = info.get("主演", "")
            vod["vod_director"] = info.get("导演", "")
            vod["vod_area"] = info.get("地区", "")
            _yr = info.get("年份", "") or info.get("上映", "")
            vod["vod_year"] = (re.search(r"\d{4}", _yr).group(0) if re.search(r"\d{4}", _yr) else _yr)
            vod["vod_remarks"] = info.get("更新", "") or info.get("集数", "") or info.get("状态", "")

            # 选集: 线路名 + 各线路播放列表
            tabs = [t.get_text(strip=True) for t in soup.select(".module-tab-item")]
            play_lists = soup.select(".module-play-list")

            from_list, url_list = [], []
            for i, pl in enumerate(play_lists):
                from_name = tabs[i] if i < len(tabs) else f"线路{i + 1}"
                from_list.append(from_name)
                links = []
                for a in pl.select("a.module-play-list-link"):
                    href = a.get("href")
                    if not href:
                        continue
                    name = a.get_text(strip=True) or f"{i + 1}"
                    if not href.startswith("http"):
                        href = self.host + href
                    links.append(f"{name}${href}")
                if links:
                    url_list.append("#".join(links))

            if from_list and url_list:
                vod["vod_play_from"] = "$$$".join(from_list)
                vod["vod_play_url"] = "$$$".join(url_list)

            return {"list": [vod]}
        except Exception:
            return {"list": []}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1

        # 搜索同样为假分页
        if pg > 1:
            return {"list": [], "page": pg}

        q = key.replace(" ", "+")  # 站点搜索链接中空格用 + 表示
        url = f"{self.host}/s/{q}{SEARCH_DASH}.html"
        try:
            soup = self._soup(url)
            vods = self._parse_list(soup)
            return {"list": vods, "page": pg}
        except Exception:
            return {"list": []}

    # ---------------- 播放源解析 ----------------
    def playerContent(self, flag, id, vipFlags):
        url = id
        if not url.startswith("http"):
            url = self.host + url

        try:
            html = self._get(url).text

            # 1) 优先解析内嵌 player_aaaa 配置 (encrypt=0, url 明文)
            #    注意: 真实 HTML 为 var player_aaaa={...}; (无外层括号),
            #    且页面后续 <script> 中还存在其他 "};", 不能用正则贪婪/非贪婪匹配,
            #    改用 json.JSONDecoder.raw_decode 做"括号级"精确解析, 自动忽略尾部垃圾。
            idx = html.find("var player_aaaa=")
            if idx >= 0:
                start = idx + len("var player_aaaa=")
                if html[start:start + 1] == " ":
                    start += 1
                try:
                    obj, _ = json.JSONDecoder().raw_decode(html, start)
                    real = obj.get("url") if isinstance(obj, dict) else None
                    if isinstance(real, list):
                        real = real[0] if real else None
                    if real:
                        return {"parse": 0, "url": real, "header": self.play_headers}
                except Exception:
                    pass

            # 2) 兜底正则抓取 m3u8 / mp4
            m3u8 = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", html)
            if m3u8:
                return {"parse": 0, "url": m3u8.group(1), "header": self.play_headers}
            mp4 = re.search(r"(https?://[^\s\"'<>]+\.(?:mp4|m4a)[^\s\"'<>]*)", html)
            if mp4:
                return {"parse": 0, "url": mp4.group(1), "header": self.play_headers}

            # 3) 仍无果: 交给播放器嗅探
            return {"parse": 1, "url": url, "header": self.play_headers}
        except Exception:
            return {"parse": 1, "url": url, "header": self.play_headers}

    # ---------------- 首页栏目模块解析 (如 4K精选🎆) ----------------
    def _parse_home_module(self, soup, title_keyword):
        """从首页提取标题含 title_keyword 的 module 栏目内所有 a.module-poster-item 卡片。

        站点首页把 "4K精选🎆" 等栏目放在独立的 <div class="module"> 里,
        标题为 <h2 class="module-title">4K精选🎆</h2>, 卡片为 a.module-poster-item。
        该模块无独立路由, 故 4K 分类页需抓首页再在此摘取。
        """
        out, seen = [], set()
        for h2 in soup.find_all("h2", class_="module-title"):
            if title_keyword in (h2.get_text(strip=True) or ""):
                mod = h2.find_parent("div", class_="module") or h2.parent
                if not mod:
                    continue
                for el in mod.select("a.module-poster-item"):
                    v = self._parse_card(el)
                    if v and v.get("vod_id") and v["vod_id"] not in seen:
                        seen.add(v["vod_id"])
                        out.append(v)
                break
        return out

    # ---------------- 通用卡片解析 (兼容两套布局) ----------------
    def _parse_list(self, soup):
        out, seen = [], set()
        # 同时覆盖: 海报卡(a.module-poster-item) 与 卡片卡(div.module-card-item)
        for el in soup.select("a.module-poster-item, .module-card-item"):
            v = self._parse_card(el)
            if v and v.get("vod_id") and v["vod_id"] not in seen:
                seen.add(v["vod_id"])
                out.append(v)
        return out

    def _parse_card(self, el):
        try:
            # 1) 详情链接
            link = None
            if el.name == "a" and "/iyftv/" in (el.get("href") or ""):
                link = el
            if link is None:
                link = (el.select_one("a.module-card-item-poster")
                        or el.select_one("a.module-poster-item")
                        or el.select_one('a[href*="/iyftv/"]'))
            if not link:
                return None
            href = link.get("href") or ""
            if "/iyftv/" not in href:
                return None

            # 2) 图片 (data-original 优先, 忽略 loading 占位图)
            pic = ""
            img = el.select_one("img[data-original]")
            if img and img.get("data-original"):
                pic = img.get("data-original")
            if not pic:
                img = el.select_one("img")
                if img:
                    pic = img.get("src") or ""
                    if pic in ("", "/loading.png"):
                        pic = ""
            if pic and not pic.startswith("http"):
                pic = self.host + pic

            # 3) 标题
            title = ""
            for sel in (".module-poster-item-title", ".module-card-item-title", ".module-item-title"):
                e = el.select_one(sel)
                if e and e.get_text(strip=True):
                    title = e.get_text(strip=True)
                    break
            if not title:
                title = link.get("title") or ""
            if not title and img:
                title = img.get("alt") or ""

            # 4) 备注 (更新/集数)
            note = ""
            for sel in (".module-item-note", ".module-card-item-note", ".pic-text", ".module-item-text"):
                e = el.select_one(sel)
                if e and e.get_text(strip=True):
                    note = e.get_text(strip=True)
                    break

            return {
                "vod_id": href,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": note,
            }
        except Exception:
            return None

    # ---------------- 框架约定桩方法 ----------------
    def getName(self):
        return "爱壹帆"

    def isVideoFormat(self, url):
        return bool(url) and url.lower().endswith((".m3u8", ".mp4", ".m4a"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    def localProxy(self, param):
        return None
