# -*- coding: utf-8 -*-
import re, urllib.parse
import json
from bs4 import BeautifulSoup
import requests
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    def init(self, extend=""):
        self.host = "https://www.okfenduo.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def getName(self):
        return 'ok电影天堂'

    def homeContent(self, filter):
        return {"class": [
            {'type_id': "1", 'type_name': "电影"},
            {'type_id': "2", 'type_name': "电视剧"},
            {'type_id': "3", 'type_name': "动漫"},
            {'type_id': "4", 'type_name': "综艺"},
            {'type_id': "5", 'type_name': "短剧"},
        ], "filters": self._build_filters()}

    def _build_filters(self):
        area = [{"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
                {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"},
                {"n": "日本", "v": "日本"}, {"n": "泰国", "v": "泰国"}, {"n": "英国", "v": "英国"},
                {"n": "法国", "v": "法国"}, {"n": "德国", "v": "德国"}, {"n": "印度", "v": "印度"},
                {"n": "其它", "v": "其它"}]
        year = [{"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
                {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
                {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
                {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"},
                {"n": "2015", "v": "2015"}, {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"},
                {"n": "2012", "v": "2012"}, {"n": "2011", "v": "2011"}, {"n": "2010", "v": "2010"}]
        lang = [{"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"},
                {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"},
                {"n": "日语", "v": "日语"}, {"n": "法语", "v": "法语"}, {"n": "德语", "v": "德语"},
                {"n": "其它", "v": "其它"}]
        sort = [{"n": "时间", "v": "time"}, {"n": "人气", "v": "hits"}, {"n": "评分", "v": "score"}]
        letter = [{"n": "全部", "v": ""}, {"n": "A", "v": "A"}, {"n": "B", "v": "B"}, {"n": "C", "v": "C"},
                  {"n": "D", "v": "D"}, {"n": "E", "v": "E"}, {"n": "F", "v": "F"}, {"n": "G", "v": "G"},
                  {"n": "H", "v": "H"}, {"n": "I", "v": "I"}, {"n": "J", "v": "J"}, {"n": "K", "v": "K"},
                  {"n": "L", "v": "L"}, {"n": "M", "v": "M"}, {"n": "N", "v": "N"}, {"n": "O", "v": "O"},
                  {"n": "P", "v": "P"}, {"n": "Q", "v": "Q"}, {"n": "R", "v": "R"}, {"n": "S", "v": "S"},
                  {"n": "T", "v": "T"}, {"n": "U", "v": "U"}, {"n": "V", "v": "V"}, {"n": "W", "v": "W"},
                  {"n": "X", "v": "X"}, {"n": "Y", "v": "Y"}, {"n": "Z", "v": "Z"}, {"n": "0-9", "v": "0-9"}]
        return {
            "2": [
                {"key": "class", "name": "类型",
                 "value": [{"n": "全部", "v": ""}, {"n": "国产剧", "v": "国产剧"}, {"n": "港台剧", "v": "港台剧"},
                           {"n": "日韩剧", "v": "日韩剧"}, {"n": "欧美剧", "v": "欧美剧"}, {"n": "海外剧", "v": "海外剧"}]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "1": [
                {"key": "class", "name": "类型",
                 "value": [{"n": "全部", "v": ""}, {"n": "动作片", "v": "动作片"}, {"n": "喜剧片", "v": "喜剧片"},
                           {"n": "恐怖片", "v": "恐怖片"}, {"n": "科幻片", "v": "科幻片"}, {"n": "爱情片", "v": "爱情片"},
                           {"n": "剧情片", "v": "剧情片"}, {"n": "战争片", "v": "战争片"}, {"n": "纪录片", "v": "纪录片"},
                           {"n": "惊悚片", "v": "惊悚片"}, {"n": "犯罪片", "v": "犯罪片"}, {"n": "动画", "v": "动画"}]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "3": [
                {"key": "class", "name": "类型",
                 "value": [{"n": "全部", "v": ""}, {"n": "国产动漫", "v": "国产动漫"}, {"n": "日本动漫", "v": "日本动漫"},
                           {"n": "欧美动漫", "v": "欧美动漫"}, {"n": "海外动漫", "v": "海外动漫"}]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "4": [
                {"key": "class", "name": "类型",
                 "value": [{"n": "全部", "v": ""}, {"n": "大陆综艺", "v": "大陆综艺"}, {"n": "港台综艺", "v": "港台综艺"},
                           {"n": "日韩综艺", "v": "日韩综艺"}, {"n": "欧美综艺", "v": "欧美综艺"}]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "5": [
                {"key": "class", "name": "类型",
                 "value": [{"n": "全部", "v": ""}, {"n": "古装短剧", "v": "古装短剧"}, {"n": "现代短剧", "v": "现代短剧"}]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
        }

    def homeVideoContent(self):
        html = self._fetch('/')
        return {"list": self._parse_video_list(html)}

    def categoryContent(self, tid, pg, filter, extend):
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

        # MacCMS 筛选格式尝试
        segs = [route_tid]
        filters = [area, genre, year, lang, letter, sort]
        for f in filters:
            segs.append(f if f else '')
        segs.append(str(pg))

        url = f'/ok/{"-".join(segs)}.html'
        html = self._fetch(url)
        items = self._parse_video_list(html)

        # 回退：无筛选简单分页
        if not items and not any([area, genre, year, lang, letter]):
            url = f'/ok/{route_tid}-{pg}.html'
            html = self._fetch(url)
            items = self._parse_video_list(html)

        page = int(pg)
        pagecount = page
        soup = BeautifulSoup(html, 'html.parser')
        # MacCMS 分页链接
        for a in soup.select('a[href*=".html"]'):
            href = a.get('href', '')
            text = a.get_text(strip=True)
            if text in ['尾页', '\u00bb', '末页', 'Last']:
                m = re.search(r'-(\d+)\.html', href)
                if m:
                    pagecount = int(m.group(1))
                    break
        if not items:
            pagecount = page

        return {"list": items, "page": page, "pagecount": pagecount, "limit": 36, "total": 9999}

    def detailContent(self, ids):
        result = {"list": []}
        vid = ids[0].split(',')[0].strip()
        try:
            html = self._fetch(f'/oktv/{vid}.html')
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
            og_director = soup.select_one('meta[property="og:video:director"]')
            if og_director:
                vod_director = og_director.get('content', '')

            # 演员
            vod_actor = ''
            og_actor = soup.select_one('meta[property="og:video:actor"]')
            if og_actor:
                vod_actor = og_actor.get('content', '')

            # 简介
            vod_content = ''
            og_desc = soup.select_one('meta[property="og:description"]')
            if og_desc:
                vod_content = og_desc.get('content', '')
            if not vod_content:
                desc = soup.select_one('.desc') or soup.select_one('.summary') or soup.select_one('.content_detail')
                if desc:
                    vod_content = desc.get_text(' ', strip=True)

            # 播放源
            play_from, play_url = [], []
            play_links = soup.select('a[href^="/okplay/"]')
            servers = {}
            for a in play_links:
                href = a.get('href', '')
                text = a.get_text(strip=True)
                m = re.search(r'/okplay/(\d+)-(\d+)-(\d+)\.html', href)
                if m:
                    sid = m.group(2)
                    if sid not in servers:
                        servers[sid] = []
                    servers[sid].append(f'{text}${href}')

            for sid, eps in servers.items():
                play_from.append(f'线路{sid}')
                play_url.append('#'.join(eps))

            result["list"].append({
                "vod_id": vid, "vod_name": vod_name, "vod_pic": vod_pic,
                "vod_director": vod_director, "vod_actor": vod_actor,
                "vod_content": vod_content,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url),
            })
        except Exception as e:
            print(e)
        return result

    def searchContent(self, key, quick, pg="1"):
        try:
            decoded = urllib.parse.unquote(key)
        except:
            decoded = key
        # 正确搜索接口: /search.html?wd=关键词 (第1页) /search.html?wd=关键词&pg=N (第2页起)
        try:
            if pg == "1":
                html = self._fetch(f'/search.html?wd={urllib.parse.quote(decoded)}')
            else:
                html = self._fetch(f'/search.html?wd={urllib.parse.quote(decoded)}&pg={pg}')
        except:
            html = ''
        items = self._parse_search_list(html)
        # 网站搜索分页有bug，所有页返回相同内容，固定返回1页
        return {"list": items, "page": int(pg), "pagecount": 1, "limit": 36, "total": len(items)}

    def playerContent(self, flag, id, vipFlags):
        url = ''
        try:
            if id.startswith('/okplay/'):
                url = self.host + id
            elif id.startswith('http'):
                url = id
            else:
                url = f'{self.host}/okplay/{id}'

            if url.startswith('http') and ('.m3u8' in url or '.mp4' in url):
                return {"parse": 0, "url": url, "header": {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                    'Referer': self.host + '/',
                    'Accept': '*/*',
                }}

            html = self._fetch(url)
            if html:
                m = re.search(r'var player_aaaa=(\{.*?\});', html, re.S)
                if m:
                    try:
                        player = json.loads(m.group(1))
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
                        print(e)

                soup = BeautifulSoup(html, 'html.parser')
                iframe = soup.select_one('iframe')
                if iframe:
                    src = iframe.get('src', '')
                    if src:
                        if src.startswith('//'):
                            src = 'https:' + src
                        elif src.startswith('/'):
                            src = self.host + src
                        return {"parse": 1, "url": src}

        except Exception as e:
            print(e)
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
            rsp = self.fetch(url, headers=self.headers)
            return rsp.text if rsp else ''
        except:
            return ''

    def _fix_pic(self, u):
        if not u: return ''
        if u.startswith('//'):
            return 'https:' + u
        return u.replace('&amp;', '&')

    def _parse_video_list(self, html):
        """适配 MacCMS mb013 模板: li > a.tu > div.tu_box > img"""
        videos, seen = [], set()
        if not html:
            return videos
        soup = BeautifulSoup(html, 'html.parser')
        for li in soup.select('li'):
            thumb = li.select_one('a.tu')
            if not thumb:
                continue
            href = thumb.get('href', '')
            m = re.search(r'/oktv/(\d+)\.html', href)
            if not m:
                continue
            vod_id = m.group(1)
            if vod_id in seen:
                continue
            seen.add(vod_id)

            vod_name = ''
            img = thumb.select_one('div.tu_box img')
            if img:
                vod_name = img.get('alt', '')
            if not vod_name:
                p = li.select_one('p a')
                if p:
                    vod_name = p.get_text(strip=True)

            vod_pic = ''
            if img:
                vod_pic = self._fix_pic(img.get('src', ''))

            vod_remarks = ''
            tip = thumb.select_one('span.tip')
            if tip:
                vod_remarks = tip.get_text(strip=True)

            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name.strip(),
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks,
                "vod_year": "",
            })
        return videos

    def _parse_search_list(self, html):
        """解析搜索 results 页面: li > p#name > a + p#time + p#actor"""
        videos, seen = [], set()
        if not html:
            return videos
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html, 'html.parser')
        except:
            return videos
        for li in soup.select('li'):
            # 跳过头部行 li#t（表头行没有 p#name，此检查已足够）
            name_p = li.select_one('p#name')
            if not name_p:
                continue
            a = name_p.select_one('a')
            if not a:
                continue
            href = a.get('href', '')
            m = re.search(r'/oktv/(\d+)\.html', href)
            if not m:
                continue
            vod_id = m.group(1)
            if vod_id in seen:
                continue
            seen.add(vod_id)

            vod_name = a.get_text(strip=True)
            vod_pic = ''
            vod_remarks = ''
            # 类型
            time_p = li.select_one('p#time')
            if time_p:
                vod_remarks = time_p.get_text(strip=True)

            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name.strip(),
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks,
                "vod_year": "",
            })
        return videos

    def _parse_section(self, html, section_name):
        """从首页HTML中解析指定分类区块的视频列表"""
        videos, seen = [], set()
        if not html or not section_name:
            return videos
        soup = BeautifulSoup(html, 'html.parser')
        for ul in soup.select('ul') + soup.select('ol'):
            prev = ul.find_previous_sibling()
            if prev and section_name in prev.get_text(strip=True):
                for li in ul.select('li'):
                    thumb = li.select_one('a.tu')
                    if not thumb:
                        continue
                    href = thumb.get('href', '')
                    m = re.search(r'/oktv/(\d+)\.html', href)
                    if not m:
                        continue
                    vod_id = m.group(1)
                    if vod_id in seen:
                        continue
                    seen.add(vod_id)

                    vod_name = ''
                    img = thumb.select_one('div.tu_box img')
                    if img:
                        vod_name = img.get('alt', '')

                    vod_pic = ''
                    if img:
                        vod_pic = self._fix_pic(img.get('src', ''))

                    vod_remarks = ''
                    tip = thumb.select_one('span.tip')
                    if tip:
                        vod_remarks = tip.get_text(strip=True)

                    videos.append({
                        "vod_id": vod_id,
                        "vod_name": vod_name.strip(),
                        "vod_pic": vod_pic,
                        "vod_remarks": vod_remarks,
                        "vod_year": "",
                    })
                break
        return videos


if __name__ == '__main__':
    sp = Spider()
    sp.init()
    print(sp.homeContent(True))
    pass
