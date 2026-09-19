# -*- coding: utf-8 -*-
import re, urllib.parse
import json
from bs4 import BeautifulSoup
import requests
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    def init(self, extend=""):
        self.host = "https://www.pys1.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def getName(self):
        return '皮克网'

    def homeContent(self, filter):
        return {"class": [
            {'type_id': "1", 'type_name': "电影"},
            {'type_id': "2", 'type_name': "剧集"},
            {'type_id': "3", 'type_name': "综艺"},
            {'type_id': "4", 'type_name': "动漫"},
            {'type_id': "30", 'type_name': "短剧"},
        ], "filters": self._build_filters()}

    def _build_filters(self):
        area = [
            {"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"},
            {"n": "日本", "v": "日本"}, {"n": "泰国", "v": "泰国"}, {"n": "英国", "v": "英国"},
            {"n": "法国", "v": "法国"}, {"n": "德国", "v": "德国"}, {"n": "印度", "v": "印度"},
            {"n": "其它", "v": "其它"},
        ]
        year = [
            {"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"},
            {"n": "2015", "v": "2015"}, {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"},
            {"n": "2012", "v": "2012"}, {"n": "2011", "v": "2011"}, {"n": "2010", "v": "2010"},
        ]
        lang = [
            {"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"}, {"n": "法语", "v": "法语"}, {"n": "德语", "v": "德语"},
            {"n": "其它", "v": "其它"},
        ]
        sort = [
            {"n": "时间", "v": "time"}, {"n": "人气", "v": "hits"}, {"n": "评分", "v": "score"},
        ]
        letter = [
            {"n": "全部", "v": ""}, {"n": "A", "v": "A"}, {"n": "B", "v": "B"}, {"n": "C", "v": "C"},
            {"n": "D", "v": "D"}, {"n": "E", "v": "E"}, {"n": "F", "v": "F"}, {"n": "G", "v": "G"},
            {"n": "H", "v": "H"}, {"n": "I", "v": "I"}, {"n": "J", "v": "J"}, {"n": "K", "v": "K"},
            {"n": "L", "v": "L"}, {"n": "M", "v": "M"}, {"n": "N", "v": "N"}, {"n": "O", "v": "O"},
            {"n": "P", "v": "P"}, {"n": "Q", "v": "Q"}, {"n": "R", "v": "R"}, {"n": "S", "v": "S"},
            {"n": "T", "v": "T"}, {"n": "U", "v": "U"}, {"n": "V", "v": "V"}, {"n": "W", "v": "W"},
            {"n": "X", "v": "X"}, {"n": "Y", "v": "Y"}, {"n": "Z", "v": "Z"}, {"n": "0-9", "v": "0-9"},
        ]
        return {
            "2": [
                {"key": "class", "name": "类型",
                 "value": [
                     {"n": "全部", "v": ""}, {"n": "国产剧", "v": "国产剧"},
                     {"n": "港台剧", "v": "港台剧"}, {"n": "日韩剧", "v": "日韩剧"},
                     {"n": "欧美剧", "v": "欧美剧"}, {"n": "海外剧", "v": "海外剧"},
                 ]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "1": [
                {"key": "class", "name": "类型",
                 "value": [
                     {"n": "全部", "v": ""}, {"n": "动作片", "v": "动作片"},
                     {"n": "喜剧片", "v": "喜剧片"}, {"n": "恐怖片", "v": "恐怖片"},
                     {"n": "科幻片", "v": "科幻片"}, {"n": "爱情片", "v": "爱情片"},
                     {"n": "剧情片", "v": "剧情片"}, {"n": "战争片", "v": "战争片"},
                     {"n": "纪录片", "v": "纪录片"}, {"n": "惊悚片", "v": "惊悚片"},
                     {"n": "犯罪片", "v": "犯罪片"}, {"n": "动画", "v": "动画"},
                 ]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "3": [
                {"key": "class", "name": "类型",
                 "value": [
                     {"n": "全部", "v": ""}, {"n": "大陆综艺", "v": "大陆综艺"},
                     {"n": "港台综艺", "v": "港台综艺"}, {"n": "日韩综艺", "v": "日韩综艺"},
                     {"n": "欧美综艺", "v": "欧美综艺"},
                 ]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "4": [
                {"key": "class", "name": "类型",
                 "value": [
                     {"n": "全部", "v": ""}, {"n": "国产动漫", "v": "国产动漫"},
                     {"n": "日本动漫", "v": "日本动漫"},
                     {"n": "欧美动漫", "v": "欧美动漫"}, {"n": "海外动漫", "v": "海外动漫"},
                 ]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "30": [
                {"key": "class", "name": "类型",
                 "value": [
                     {"n": "全部", "v": ""}, {"n": "古装短剧", "v": "古装短剧"},
                     {"n": "现代短剧", "v": "现代短剧"},
                 ]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
        }

    def homeVideoContent(self):
        """首页推荐视频 - 解析首页各分类区块"""
        html = self._fetch('/')
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, 'html.parser')
        videos, seen = [], set()

        # 首页结构: 每个分类区块有 ul.row > li.col-xs-4.col-md-3.col-lg-2
        # 区块标题在上一兄弟元素的文本中
        all_rows = soup.select('ul.row')
        for row in all_rows:
            # 查找上一兄弟元素获取区块标题
            prev = row.find_previous_sibling()
            section_name = ''
            if prev:
                section_name = prev.get_text(strip=True)
            # 跳过导航等非视频区块
            if section_name in ['首页', '电影', '剧集', '综艺', '动漫', '短剧', '网址', '留言', '导航', '热播', '']:
                continue

            for li in row.select('li'):
                a = li.select_one('a')
                if not a or '/mv/' not in a.get('href', ''):
                    continue
                href = a.get('href', '')
                m = re.search(r'/mv/(\d+)\.html', href)
                if not m:
                    continue
                vod_id = m.group(1)
                if vod_id in seen:
                    continue
                seen.add(vod_id)

                vod_name = a.get('title', '')
                vod_pic = ''
                img = li.select_one('div.img-wrapper.lazyload')
                if img:
                    vod_pic = self._fix_pic(img.get('data-background', ''))
                if not vod_pic:
                    img2 = li.select_one('div.img-wrapper-pic')
                    if img2:
                        vod_pic = self._fix_pic(img2.get('data-original', ''))

                vod_remarks = ''
                s1 = li.select_one('span.s1')
                if s1:
                    vod_remarks = s1.get_text(strip=True)

                vod_year = ''
                videos.append({
                    "vod_id": vod_id,
                    "vod_name": vod_name.strip(),
                    "vod_pic": vod_pic,
                    "vod_remarks": vod_remarks,
                    "vod_year": vod_year,
                })

        return {"list": videos}

    def categoryContent(self, tid, pg, filter, extend):
        """分类列表页 - 支持筛选+分页"""
        args = {}
        if extend and isinstance(extend, dict):
            for k, v in extend.items():
                if v:
                    args[k] = str(v)
        if isinstance(filter, dict):
            for k, v in filter.items():
                if v and k not in args:
                    args[k] = str(v)

        route_tid = args.get('class', str(tid))
        area = args.get('area', '')
        genre = args.get('genre', '') or args.get('class', '')
        year = args.get('year', '')
        lang = args.get('lang', '')
        letter = args.get('letter', '')
        sort = args.get('sort', 'time')

        # pys1.com 筛选格式: /ms/{typeId}-{class}-{area}-{year}-{lang}-{letter}-{sort}-{pg}.html
        segs = [route_tid, genre, area, year, lang, letter, sort, str(pg)]
        url = f'/ms/{"-".join(segs)}.html'
        html = self._fetch(url)
        items = self._parse_video_list(html)

        # 回退: 无筛选简单分页 /vt/{typeId}-{pg}.html
        if not items:
            url = f'/vt/{route_tid}-{pg}.html'
            html = self._fetch(url)
            items = self._parse_video_list(html)

        page = int(pg)
        pagecount = page
        soup = BeautifulSoup(html, 'html.parser')
        # 分页链接: ul.ewave-page > li > a
        for a in soup.select('ul.ewave-page a[href]'):
            href = a.get('href', '')
            text = a.get_text(strip=True)
            if text in ['尾页', '末页', '下一页', '后页']:
                m = re.search(r'-(\d+)\.html', href)
                if m:
                    pagecount = int(m.group(1))
                    break
        if not items:
            pagecount = page

        return {"list": items, "page": page, "pagecount": pagecount, "limit": 36, "total": 9999}

    def detailContent(self, ids):
        """视频详情页"""
        result = {"list": []}
        vid = ids[0].split(',')[0].strip()
        try:
            html = self._fetch(f'/mv/{vid}.html')
            if not html:
                return result

            soup = BeautifulSoup(html, 'html.parser')

            # 标题
            vod_name = ''
            title_h1 = soup.select_one('h1')
            if title_h1:
                vod_name = title_h1.get_text(strip=True)
            if not vod_name:
                og_title = soup.select_one('meta[property="og:title"]')
                if og_title:
                    content = og_title.get('content', '')
                    vod_name = content.split('》')[0].replace('《', '') if '《' in content else content

            # 图片
            vod_pic = ''
            og_img = soup.select_one('meta[property="og:image"]')
            if og_img:
                vod_pic = self._fix_pic(og_img.get('content', ''))

            # 导演
            vod_director = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if text.startswith('导演：'):
                    vod_director = text.replace('导演：', '').strip()
                    break

            # 编剧
            vod_writer = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if text.startswith('编剧：'):
                    vod_writer = text.replace('编剧：', '').strip()
                    break

            # 演员
            vod_actor = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if text.startswith('主演：'):
                    vod_actor = text.replace('主演：', '').strip()
                    break

            # 类型
            vod_class = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if text.startswith('类型：'):
                    vod_class = text.replace('类型：', '').strip()
                    break

            # 地区
            vod_area = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if text.startswith('地区：'):
                    vod_area = text.replace('地区：', '').strip()
                    break

            # 语言
            vod_lang = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if text.startswith('语言：'):
                    vod_lang = text.replace('语言：', '').strip()
                    break

            # 上映日期
            vod_releasedate = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if text.startswith('上映：'):
                    vod_releasedate = text.replace('上映：', '').strip()
                    break

            # 片长
            vod_duration = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if text.startswith('片长：'):
                    vod_duration = text.replace('片长：', '').strip()
                    break

            # 又名
            vod_altname = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if text.startswith('又名：'):
                    vod_altname = text.replace('又名：', '').strip()
                    break

            # 评分
            vod_score = ''
            for span in soup.select('span'):
                text = span.get_text(strip=True)
                if '豆瓣' in text and re.search(r'\d+\.\d+', text):
                    m = re.search(r'(\d+\.\d+)', text)
                    if m:
                        vod_score = m.group(1)
                    break

            # 简介
            vod_content = ''
            desc_div = soup.select_one('div.zksq-content')
            if desc_div:
                vod_content = desc_div.get_text(strip=True)
            if not vod_content:
                og_desc = soup.select_one('meta[property="og:description"]')
                if og_desc:
                    vod_content = og_desc.get('content', '')

            # 播放源 - 解析播放列表
            # 结构: div.playlist-box (父容器)
            #   > div.playlist-tab-box (线路名)
            #   > ul#ewave-playlist-{N} (集数链接列表)
            play_from, play_url = [], []
            playlist_boxes = soup.select('div.playlist-box')

            for pbox in playlist_boxes:
                # 查找线路名
                tab_box = pbox.select_one('div.playlist-tab-box')
                tab_name = ''
                if tab_box:
                    tab_nav = tab_box.select_one('div.playlist-tab.ewave-swiper.ewave-swiper-nav')
                    if tab_nav:
                        tab_name = tab_nav.get_text(strip=True)
                    if not tab_name:
                        h2 = tab_box.select_one('h2')
                        if h2:
                            tab_name = h2.get_text(strip=True)
                if not tab_name:
                    continue

                # 查找集数链接 - 在 ul[id^="ewave-playlist-"] 中
                eps = []
                for ul in pbox.select('ul[id^="ewave-playlist-"]'):
                    for a in ul.select('a[href^="/py/"]'):
                        ep_href = a.get('href', '')
                        ep_text = a.get_text(strip=True)
                        if ep_text and ep_href:
                            m = re.search(r'/py/(\d+)-(\d+)-(\d+)\.html', ep_href)
                            if m:
                                # 存储完整 href 供 playerContent 使用
                                eps.append(f'{ep_text}${ep_href}')

                if eps:
                    play_from.append(tab_name)
                    play_url.append('#'.join(eps))

            result["list"].append({
                "vod_id": vid,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_director": vod_director,
                "vod_actor": vod_actor,
                "vod_content": vod_content,
                "vod_class": vod_class,
                "vod_area": vod_area,
                "vod_lang": vod_lang,
                "vod_releasedate": vod_releasedate,
                "vod_duration": vod_duration,
                "vod_altname": vod_altname,
                "vod_score": vod_score,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url),
            })
        except Exception as e:
            print(e)
        return result

    def searchContent(self, key, quick, pg="1"):
        """搜索 - JSON API + HTML回退双方案"""
        encoded_key = urllib.parse.quote(key)
        # 方法1: JSON API 搜索（主接口）
        try:
            search_url = f'{self.host}/index.php/ajax/suggest?mid=1&wd={encoded_key}&limit=30'
            html = self._fetch(search_url)
            if html:
                data = json.loads(html)
                items = data.get('list', [])
                videos = []
                for item in items:
                    vid = str(item.get('id', ''))
                    name = item.get('name', '')
                    pic = self._fix_pic(item.get('pic', ''))
                    videos.append({
                        "vod_id": vid,
                        "vod_name": name.strip(),
                        "vod_pic": pic,
                        "vod_remarks": "",
                        "vod_year": "",
                    })
                if videos:
                    return {"list": videos, "page": int(pg), "pagecount": 1, "limit": 30, "total": len(videos)}
        except Exception as e:
            print(f"JSON搜索失败: {e}")

        # 方法2: HTML回退搜索
        try:
            html = self._fetch(f'/vs/-------------.html?wd={encoded_key}')
            if html:
                items = self._parse_video_list(html)
                if items:
                    return {"list": items, "page": int(pg), "pagecount": 1, "limit": 30, "total": len(items)}
        except Exception as e:
            print(f"HTML搜索回退失败: {e}")

        return {"list": [], "page": int(pg), "pagecount": 1, "limit": 36, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        """视频播放解析"""
        url = ''
        try:
            # id 格式: "/py/514455-1-1.html" (完整 href，来自 detailContent)
            # 兼容旧格式: "第1集$/py/514455-1-1.html" (含显示文本)
            ep_href = id
            if '$' in id:
                ep_href = id.split('$', 1)[1]

            if ep_href.startswith('http'):
                url = ep_href
            elif ep_href.startswith('/'):
                url = self.host + ep_href
            else:
                url = f'{self.host}/py/{ep_href}'

            html = self._fetch(url)
            if html:
                # 尝试解析 player_aaaa 变量 (需处理嵌套对象)
                m = re.search(r'var\s+player_aaaa\s*=\s*(\{.*)', html)
                if m:
                    json_str = m.group(1)
                    # 匹配完整的 JSON 对象（处理嵌套括号）
                    depth = 0
                    end_pos = 0
                    for i, ch in enumerate(json_str):
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                end_pos = i + 1
                                break
                    if end_pos > 0:
                        json_str = json_str[:end_pos]
                        try:
                            player = json.loads(json_str)
                            play_url = player.get('url', '')
                            if play_url:
                                if play_url.startswith('//'):
                                    play_url = 'https:' + play_url
                                return {"parse": 0, "url": play_url, "header": {
                                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                                    'Referer': self.host + '/',
                                    'Accept': '*/*',
                                }}
                        except Exception as e:
                            print(f"player_aaaa 解析失败: {e}")

                # 回退: 提取 iframe src
                soup = BeautifulSoup(html, 'html.parser')
                iframe = soup.select_one('iframe')
                if iframe:
                    src = iframe.get('src', '')
                    if src:
                        if src.startswith('//'):
                            src = 'https:' + src
                        elif src.startswith('/'):
                            src = self.host + src
                        if '.m3u8' in src or '.mp4' in src:
                            return {"parse": 0, "url": src, "header": {
                                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                                'Referer': self.host + '/',
                                'Accept': '*/*',
                            }}
                        return {"parse": 1, "url": src, "header": {
                            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                            'Referer': self.host + '/',
                            'Accept': '*/*',
                        }}
        except Exception as e:
            print(f"playerContent 异常: {e}")
        return {"parse": 1, "url": url}
    def localProxy(self, param=''):
        return {}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def _fetch(self, url):
        try:
            if not url.startswith('http'):
                url = self.host + url
            print(f"[FETCH] {url}")
            rsp = self.fetch(url, headers=self.headers)
            result = rsp.text if rsp else ''
            print(f"[FETCH] 响应长度: {len(result)}")
            return result
        except Exception as e:
            print(f"[FETCH] 异常: {e}")
            return ''
    def _fix_pic(self, u):
        if not u:
            return ''
        if u.startswith('//'):
            return 'https:' + u
        return u.replace('&amp;', '&')

    def _parse_video_list(self, html):
        """解析视频列表 - 适配 pys1.com (MacCMS mds/ewave 模板)"""
        videos, seen = [], set()
        if not html:
            return videos
        soup = BeautifulSoup(html, 'html.parser')

        # 选择器: ul.row > li.col-xs-4.col-md-3.col-lg-2
        for li in soup.select('li'):
            a = li.select_one('a')
            if not a:
                continue
            href = a.get('href', '')
            if '/mv/' not in href:
                continue
            m = re.search(r'/mv/(\d+)\.html', href)
            if not m:
                continue
            vod_id = m.group(1)
            if vod_id in seen:
                continue
            seen.add(vod_id)

            vod_name = a.get('title', '')

            vod_pic = ''
            img = li.select_one('div.img-wrapper.lazyload')
            if img:
                vod_pic = self._fix_pic(img.get('data-background', ''))
            if not vod_pic:
                img2 = li.select_one('div.img-wrapper-pic')
                if img2:
                    vod_pic = self._fix_pic(img2.get('data-original', ''))

            vod_remarks = ''
            s1 = li.select_one('span.s1')
            if s1:
                vod_remarks = s1.get_text(strip=True)

            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name.strip(),
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks,
                "vod_year": "",
            })
        return videos


if __name__ == '__main__':
    sp = Spider()
    sp.init()
    print(sp.homeContent(True))