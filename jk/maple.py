# -*- coding: utf-8 -*-
import re, urllib.parse, time
import json
from bs4 import BeautifulSoup
import requests
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    # ★蓝光2k/至臻4k修复：线路 from 标识与解析站映射（与站方 playerconfig.js 保持一致）
    #   蓝光2k: co / BBA / vwnet / YYNB -> zzrs.mfdyvip.com；JD2K -> fgsrg.hzqingshan.com
    #   至臻4k: JD4K -> fgsrg.hzqingshan.com
    BL_FROMS = {'co', 'BBA', 'vwnet', 'YYNB', 'JD2K'}      # 蓝光2k
    ZC_FROMS = {'JD4K'}                                     # 至臻4k
    PLAYER_BASE = {
        'co': 'https://zzrs.mfdyvip.com/player',
        'BBA': 'https://zzrs.mfdyvip.com/player',
        'vwnet': 'https://zzrs.mfdyvip.com/player',
        'YYNB': 'https://zzrs.mfdyvip.com/player',
        'JD2K': 'https://fgsrg.hzqingshan.com/player',
        'JD4K': 'https://fgsrg.hzqingshan.com/player',
    }

    def init(self, extend=""):
        self.host = "https://maihaolian.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def getName(self):
        return '枫叶影院'

    def homeContent(self, filter):
        return {"class": [
            {'type_id': "/label/qq", 'type_name': "腾讯VIP精选"},
            {'type_id': "/label/bli", 'type_name': "B站VIP精选"},
            {'type_id': "/label/youku", 'type_name': "优酷VIP精选"},
            {"type_id": "/label/duanju", "type_name": "红果短剧"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "3", "type_name": "综艺"},
        ], "filters": self._build_filters()}

    def _build_filters(self):
        area = [{"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
                {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"},
                {"n": "日本", "v": "日本"}, {"n": "泰国", "v": "泰国"}, {"n": "新加坡", "v": "新加坡"},
                {"n": "马来西亚", "v": "马来西亚"}, {"n": "印度", "v": "印度"}, {"n": "英国", "v": "英国"},
                {"n": "法国", "v": "法国"}, {"n": "加拿大", "v": "加拿大"}, {"n": "西班牙", "v": "西班牙"},
                {"n": "俄罗斯", "v": "俄罗斯"}, {"n": "其它", "v": "其它"}]
        year = [{"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
                {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
                {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
                {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"},
                {"n": "2015", "v": "2015"}, {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"},
                {"n": "2012", "v": "2012"}, {"n": "2011", "v": "2011"}, {"n": "2010", "v": "2010"},
                {"n": "2009", "v": "2009"}, {"n": "2008", "v": "2008"}, {"n": "2007", "v": "2007"},
                {"n": "2006", "v": "2006"}, {"n": "2005", "v": "2005"}, {"n": "2004", "v": "2004"}]
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
                 "value": [{"n": "全部", "v": "2"}, {"n": "国产剧", "v": "13"}, {"n": "日韩剧", "v": "15"},
                           {"n": "海外剧", "v": "16"}]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "genre", "name": "剧情", "value": [{"n": v[0], "v": v[1]} for v in
                                                           [("全部", ""), ("古装", "古装"), ("战争", "战争"),
                                                            ("青春偶像", "青春偶像"), ("喜剧", "喜剧"),
                                                            ("家庭", "家庭"), ("犯罪", "犯罪"), ("动作", "动作"),
                                                            ("奇幻", "奇幻"), ("剧情", "剧情"), ("历史", "历史"),
                                                            ("经典", "经典"), ("乡村", "乡村"), ("情景", "情景"),
                                                            ("商战", "商战"), ("网剧", "网剧"), ("其他", "其他")]]},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "1": [
                {"key": "class", "name": "类型",
                 "value": [{"n": "全部", "v": "1"}, {"n": "动作片", "v": "6"}, {"n": "喜剧片", "v": "7"},
                           {"n": "恐怖片", "v": "8"}, {"n": "科幻片", "v": "9"}, {"n": "爱情片", "v": "10"},
                           {"n": "剧情片", "v": "11"}, {"n": "战争片", "v": "12"}, {"n": "纪录片", "v": "20"}]},
                {"key": "area", "name": "地区", "value": area},
                {"key": "genre", "name": "剧情", "value": [{"n": v[0], "v": v[1]} for v in
                                                           [("全部", ""), ("喜剧", "喜剧"), ("爱情", "爱情"),
                                                            ("恐怖", "恐怖"), ("动作", "动作"), ("科幻", "科幻"),
                                                            ("剧情", "剧情"), ("战争", "战争"), ("警匪", "警匪"),
                                                            ("犯罪", "犯罪"), ("动画", "动画"), ("奇幻", "奇幻"),
                                                            ("武侠", "武侠"), ("冒险", "冒险"), ("枪战", "枪战"),
                                                            ("悬疑", "悬疑"), ("惊悚", "惊悚"), ("经典", "经典"),
                                                            ("青春", "青春"), ("文艺", "文艺"), ("微电影", "微电影"),
                                                            ("古装", "古装"), ("历史", "历史"), ("运动", "运动"),
                                                            ("农村", "农村"), ("儿童", "儿童"),
                                                            ("网络电影", "网络电影")]]},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "4": [
                {"key": "class", "name": "类型",
                 "value": [{"n": "全部", "v": "4"}, {"n": "国产动漫", "v": "25"}, {"n": "日韩动漫", "v": "26"}]},
                {"key": "genre", "name": "剧情", "value": [{"n": v[0], "v": v[1]} for v in
                                                           [("全部", ""), ("情感", "情感"), ("科幻", "科幻"),
                                                            ("热血", "热血"), ("推理", "推理"), ("搞笑", "搞笑"),
                                                            ("冒险", "冒险"), ("奇幻", "奇幻"), ("战斗", "战斗"),
                                                            ("校园", "校园"), ("萝莉", "萝莉"), ("治愈", "治愈"),
                                                            ("原创", "原创"), ("亲子", "亲子"), ("益智", "益智"),
                                                            ("励志", "励志"), ("其他", "其他")]]},
                {"key": "area", "name": "地区",
                 "value": [{"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
                           {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"},
                           {"n": "日本", "v": "日本"}, {"n": "法国", "v": "法国"}, {"n": "英国", "v": "英国"},
                           {"n": "其它", "v": "其它"}]},
                {"key": "year", "name": "年份", "value": year},
                {"key": "lang", "name": "语言", "value": lang},
                {"key": "letter", "name": "字母", "value": letter},
                {"key": "sort", "name": "排序", "value": sort},
            ],
            "3": [
                {"key": "class", "name": "类型",
                 "value": [{"n": "全部", "v": "3"}, {"n": "大陆综艺", "v": "21"}, {"n": "日韩综艺", "v": "22"}]},
                {"key": "genre", "name": "剧情", "value": [{"n": v[0], "v": v[1]} for v in
                                                           [("全部", ""), ("选秀", "选秀"), ("情感", "情感"),
                                                            ("访谈", "访谈"), ("播报", "播报"), ("音乐", "音乐"),
                                                            ("美食", "美食"), ("旅游", "旅游"), ("搞笑", "搞笑"),
                                                            ("游戏", "游戏"), ("亲子", "亲子"), ("其它", "其它")]]},
                {"key": "area", "name": "地区",
                 "value": [{"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
                           {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"},
                           {"n": "日本", "v": "日本"}, {"n": "英国", "v": "英国"}, {"n": "其它", "v": "其它"}]},
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
        # 构建筛选参数：参照歪比巴卜，直接取extend里的值，fallback到filter
        if tid.startswith('/label'):
            url = f'{tid}/page/{pg}.html'
            html = self._fetch(url)
            items = self._parse_video_list(html)
            page = int(pg)
            page_count = page if len(items) < 24 else page + 2
            return {"list": items, "page": page, "pagecount": page_count, "limit": 24, "total": page_count * 24}

        args = {}
        if extend and isinstance(extend, dict):
            for k, v in extend.items():
                if v:
                    args[k] = str(v)
        if isinstance(filter, dict):
            for k, v in filter.items():
                if v and k not in args:
                    args[k] = str(v)
        route_tid = args.get('class', args.get('tid', str(tid)))
        area = args.get('area', '')
        genre = args.get('genre', '')
        year = args.get('year', '')
        lang = args.get('lang', '')
        letter = args.get('letter', '')
        sort = args.get('sort', '')
        # 无筛选走正常分页
        if not area and not genre and not year and not lang and not letter and not sort:
            url = f'/cupfox-list/{route_tid}--------{pg}---.html'
            html = self._fetch(url)
            items = self._parse_video_list(html)
            # cupfox-list 被拦截时，从首页对应区块回退解析
            section_map = {"1": "电影", "2": "电视剧", "3": "综艺", "4": "动漫"}
            if route_tid in section_map and not items:
                home_html = self._fetch('/')
                items = self._parse_section(home_html, section_map[route_tid])
            page = int(pg)
            soup = BeautifulSoup(html, 'html.parser')
            pagecount = page
            for a in soup.select('a.page-link'):
                if a.text == '尾页':
                    m = re.search(r'---(\d+)---', a.get('href', ''))
                    if m:
                        pagecount = int(m.group(1))
                    break
            if not items:
                pagecount = 0
            return {"list": items, "page": page, "pagecount": pagecount, "limit": 36, "total": 9999}
        # 有筛选：{tid}-{area}-{sort}-{genre}-{lang}-{letter}------{year}.html
        segs = [route_tid, area, sort, genre, lang, letter, '', '', year]
        url = '/cupfox-list/' + '-'.join(segs) + '.html'
        html = self._fetch(url)
        items = self._parse_video_list(html)
        return {"list": items, "page": 1, "pagecount": 1, "limit": 36, "total": 9999}

    def detailContent(self, ids):
        result = {"list": []}
        vid = ids[0].split(',')[0].strip()
        try:
            html = self._fetch(f'/detail/{vid}.html')
            if not html: return result
            soup = BeautifulSoup(html, 'html.parser')
            vod_name = soup.select_one('h3.slide-info-title')
            vod_name = vod_name.text.strip() if vod_name else ''
            vod_pic = soup.select_one('img.lazy')
            vod_pic = self._fix_pic(vod_pic.get('data-src', '')) if vod_pic else ''
            vod_director = ''
            vod_actor = ''
            for el in soup.select('.slide-info'):
                text = el.get_text(' ').strip()
                if text.startswith('导演：'):
                    vod_director = text.replace('导演：', '').strip()
                elif text.startswith('演员：'):
                    vod_actor = text.replace('演员：', '').strip()
            vod_content = soup.select_one('#height_limit')
            vod_content = vod_content.get_text(' ', strip=True) if vod_content else ''
            play_from, play_url = [], []
            for tab in soup.select('.anthology-tab a.swiper-slide'):
                src_name = re.sub(r'<[^>]+>', '', str(tab)).strip() or tab.get_text(' ', strip=True).strip()
                if src_name:
                    play_from.append(src_name)
            tab_blocks = soup.select('.anthology-list-box')
            for i, block in enumerate(tab_blocks):
                ep_list = []
                for a in block.select('li a'):
                    href = a.get('href', '')
                    m = re.search(r'/play/(.*?)\.html', href)
                    if m:
                        ep_list.append(f'{a.text.strip()}${vid}-{m.group(1)}')
                ep_list.reverse()
                if ep_list and i < len(play_from):
                    play_url.append('#'.join(ep_list))
            valid_from = [pf for i, pf in enumerate(play_from) if i < len(play_url)]
            result["list"].append({
                "vod_id": vid, "vod_name": vod_name, "vod_pic": vod_pic,
                "vod_director": vod_director, "vod_actor": vod_actor,
                "vod_content": vod_content,
                "vod_play_from": "$$$".join(valid_from),
                "vod_play_url": "$$$".join(play_url),
            })
        except:
            pass
        return result

    def searchContent(self, key, quick, pg="1"):
        try:
            decoded = urllib.parse.unquote(key)
        except:
            decoded = key
        try:
            search_url = f'{self.host}/index.php/ajax/suggest?mid=1&wd={urllib.parse.quote(decoded)}&limit=30'
            json_str = self._fetch(search_url)
            if json_str:
                data = json.loads(json_str)
                items = []
                for item in data.get('list', []):
                    items.append({
                        "vod_id": str(item['id']),
                        "vod_name": item['name'],
                        "vod_pic": self._fix_pic(item.get('pic', '')),
                        "vod_remarks": '',
                    })
                return {"list": items, "page": int(pg), "pagecount": data.get('pagecount', 1), "limit": 30, "total": data.get('total', len(items))}
        except Exception as e:
            print(f"Search error: {e}")
        return {"list": [], "page": int(pg), "pagecount": 1, "limit": 30, "total": 0}

    def _resolve_blplayer(self, base, q_url):
        """★蓝光2k/至臻4k修复：mplayer.php 直取真实 m3u8（纯 requests，不依赖 self.post）

        实测链路（2026-09 抓包验证）：
        1. GET  {base}/?url={q_url}     带 Referer: https://maihaolian.com/
           -> 解析页 <div id="player-data"> 的 data-te 即一次性 token
              (token 与 data-te 完全相同，由页面混淆 JS md5.js 直接透传，无需本地复现算法)
        2. POST {base}/mplayer.php       body: url={q_url}&token={data-te}
           X-Requested-With: XMLHttpRequest
           -> {"code":200,"url":"...m3u8"}
              蓝光2k: cibn-edge-5g.1ljx.com 中转链(302->优酷CDN, 无需Referer即可拉流)
              至臻4k: 天翼云 media-bjcy-fy-person01.bjoss.ctyunxs.cn 直链
        3. token 具时效且一次性：必须现取现用、不可复用缓存
        4. 两站均有短时频率限制(连续高频请求回404后自动恢复)，故重试需带间隔
        """
        s = requests.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
            'Referer': f'{self.host}/',
        })
        for attempt in range(3):
            try:
                r = s.get(f'{base}/?url={q_url}', timeout=10)
                m = re.search(r'data-te="([^"]+)"', r.text)
                if not m:
                    time.sleep(1.5)
                    continue
                r2 = s.post(f'{base}/mplayer.php',
                            data={'url': q_url, 'token': m.group(1)},
                            headers={'X-Requested-With': 'XMLHttpRequest'}, timeout=10)
                result = r2.json()
                if result.get('code') == 200 and result.get('url'):
                    return result['url']
                time.sleep(1.5)
            except Exception as e:
                print(f"_resolve_blplayer attempt{attempt + 1} failed: {e}")
                time.sleep(1.5)
        return None

    def playerContent(self, flag, id, vipFlags):
        # 通用播放头，解决CDN防盗链（Referer 必须带，否则切片 403）
        play_header = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
            'Referer': 'https://maihaolian.com/',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Origin': 'https://maihaolian.com',
        }
        # 解析接口专用请求头（模拟浏览器，绕过部分防盗链）
        api_headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            'Accept': "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            'Accept-Language': "zh-CN,zh;q=0.9",
            'Cache-Control': "no-cache",
            'Pragma': "no-cache",
            'Referer': 'https://maihaolian.com/',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        # from -> 解析接口映射（与播放页 player_aaaa.from 保持一致）
        api_map = {
            'YYNB': 'https://zzrs.mfdyvip.com/player/mplayer.php',
            'JD4K': 'https://fgsrg.hzqingshan.com/player/mplayer.php',
            'QIEBO': 'https://jx.xn--s9pr.work/player/mplayer.php',
            'ZLB': 'https://jx.zhanlangbu.com/m3u8.php',
            'FUQI': 'https://play.fuqizhishi.com/jq/player/prod.php',
            'BLAZ': 'https://blzb.tv/api/?url=',
            # ★修复蓝光/臻彩不能播放：补全站方 playerconfig.js 里的实际线路 from。
            #   蓝光2k 线路的 from 是 co/BBA/vwnet(JD2K)，之前未映射，
            #   蓝光参数会被丢给错误接口解析，导致蓝光/臻彩线路全部无法播放
            'co': 'https://zzrs.mfdyvip.com/player/mplayer.php',       # 蓝光2k
            'BBA': 'https://zzrs.mfdyvip.com/player/mplayer.php',      # 蓝光2k
            'vwnet': 'https://zzrs.mfdyvip.com/player/mplayer.php',    # 蓝光2k
            'JD2K': 'https://fgsrg.hzqingshan.com/player/mplayer.php',  # 蓝光2k
        }

        def _is_direct(u):
            """判断是否为可直接播放的 m3u8/mp4 直链"""
            if not isinstance(u, str) or not u.strip():
                return False
            u = u.strip()
            if not u.startswith('http'):
                return False
            return ('.m3u8' in u) or u.endswith('.mp4') or u.endswith('.m3u8')

        def _resolve_token_post(api_url, q_url):
            """通用 token + POST 二次解析（JD4K/YYNB 等 mplayer 类接口）

            ★修复至臻4k/蓝光偶发不能播放：
            1. token 必须从播放器页 .../player/?url= 提取（页面 data-te）。
               之前拼成 {api_url}/?url= 即 .../mplayer.php/?url= 只会返回 403 JSON，
               永远拿不到 token，POST 缺 token 必然 403，导致整条线路解析失败。
            2. 接口偶发抖动（瞬时 403/网络错误）会导致本次解析失败后立刻降级到无关接口，
               最终 parse:1 播放失败。这里对同一接口做多次重试（每次重新取 token），
               稳住了至臻4k/蓝光的解析成功率。
            """
            for attempt in range(3):
                try:
                    if 'mplayer.php' in api_url:
                        token_page = api_url.split('mplayer.php')[0] + '?url=' + urllib.parse.quote(q_url)
                    else:
                        token_page = f"{api_url}/?url={urllib.parse.quote(q_url)}"
                    token_resp = requests.get(token_page, headers=api_headers, timeout=10)
                    token = None
                    for pat in [r'data-te="(.*?)"', r'data-url="(.*?)"', r'data-href="(.*?)"',
                                r'data-src="(.*?)"', r"""url[="]+(.*?m3u8[^\s"'<>]*)"""]:
                        mm = re.search(pat, token_resp.text)
                        if mm:
                            token = mm.group(1)
                            break
                    payload = {'url': q_url}
                    if token:
                        payload['token'] = token
                    # 部分运行时 self.post 不可用/行为不一致，失败时用 requests 重发
                    try:
                        post_resp = self.post(api_url, data=payload, headers=api_headers)
                        post_resp.raise_for_status()
                        result = post_resp.json()
                    except Exception:
                        post_resp = requests.post(api_url, data=payload, headers=api_headers, timeout=10)
                        post_resp.raise_for_status()
                        result = post_resp.json()
                    if result.get('code') == 200 and result.get('url'):
                        return result['url']
                    # 部分接口成功但 code 非 200，仍可能带 url
                    if result.get('url'):
                        return result['url']
                except Exception as e:
                    print(f"_resolve_token_post attempt{attempt + 1} failed: {e}")
            return None

        def _resolve_blaz(param):
            """BLAZ(blzb.tv) 独立解析：GET 调用，兼容 JSON / 纯直链 / 302跳转 多种返回

            返回 (stream_url, header) 或 (None, None)。
            网页能播放说明播放参数有效，故解析策略尽量宽松：
            - 优先取 JSON 中的 url 字段（兼容 {code,url} / {data:{url}} / {url:...}）
            - 其次把整个返回体当直链
            - 最后跟随 302 拿到 Location
            """
            blaz_api = api_map.get('BLAZ')
            if not blaz_api:
                return None, None
            try:
                resp = requests.get(f"{blaz_api}{urllib.parse.quote(param)}",
                                    headers=api_headers, timeout=15, allow_redirects=True)
                text = (resp.text or '').strip()
                # 情况A：JSON 返回
                try:
                    j = json.loads(text)
                    # 兼容 url 在第一层 / data 对象 / data 字符串 三种结构
                    got = j.get('url') if isinstance(j.get('url'), str) else None
                    if not got and isinstance(j.get('data'), dict):
                        got = j['data'].get('url')
                    if not got and isinstance(j.get('data'), str):
                        got = j['data']
                    if got and _is_direct(got):
                        h = dict(play_header)
                        h['Referer'] = 'https://blzb.tv/'
                        return got.strip(), h
                except (json.JSONDecodeError, ValueError):
                    pass
                # 情况B：纯直链文本（可能带引号包裹）
                candidate = text.strip().strip('"\'').strip()
                if _is_direct(candidate):
                    h = dict(play_header)
                    h['Referer'] = 'https://blzb.tv/'
                    return candidate, h
                # 情况C：返回是播放页HTML —— 从中抠 m3u8/mp4 直链
                for pat in [r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>"\']*)',
                            r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>"\']*)']:
                    fm = re.search(pat, text)
                    if fm and _is_direct(fm.group(1)):
                        return fm.group(1).strip(), play_header
            except Exception as e:
                print(f"BLAZ resolve failed: {e}")
            return None, None

        url = ''
        try:
            url = id if id.startswith('http') else f'{self.host}/play/{id}.html'
            html = self._fetch(url)
            if html:
                m = re.search(r'player_aaaa=(.*?)</script>', html, re.S)
                if m:
                    try:
                        pd = json.loads(m.group(1))
                    except Exception as e:
                        print(f"player_aaaa JSON parse error: {e}")
                        pd = {}
                    play_url = pd.get('url') or ''
                    play_id = (pd.get('from') or '').strip()  # 主线路 from

                    # ★主 url 若是直链，直接返回（网页能播说明直链有效）
                    if play_url and _is_direct(play_url):
                        print(f"主url直链命中: {play_url[:80]}")
                        return {"parse": 0, "url": play_url.strip(), "header": play_header}

                    # ★★★ 蓝光2k / 至臻4k 专用直解（本次修复核心）★★★
                    # 站方 playerconfig.js 中这两条线路的解析站固定为：
                    #   蓝光2k(co/BBA/vwnet/YYNB) -> zzrs.mfdyvip.com
                    #   蓝光2k(JD2K)/至臻4k(JD4K) -> fgsrg.hzqingshan.com
                    # 取流协议：GET 解析页拿 data-te(一次性token) -> 立即 POST mplayer.php 换真实 m3u8。
                    # 之前这两条线路被丢进通用/BLAZ 流程，且部分运行时 self.post 返回 403
                    # 不抛异常导致 requests 兜底永不触发，最终必然解析失败。
                    _flag = flag or ''
                    _is_bl_line = (play_id in self.BL_FROMS or play_id in self.ZC_FROMS
                                   or '蓝光' in _flag or '至臻' in _flag)
                    if _is_bl_line and play_url:
                        base = self.PLAYER_BASE.get(play_id) or (
                            'https://fgsrg.hzqingshan.com/player'
                            if str(play_url).startswith('JD')
                            else 'https://zzrs.mfdyvip.com/player')
                        resolved = self._resolve_blplayer(base, play_url)
                        if resolved:
                            print(f"蓝光2k/至臻4k直解成功({play_id}): {resolved[:80]}")
                            return {"parse": 0, "url": resolved, "header": play_header}
                        # 直解失败：透传完整解析页走 App 内置嗅探兜底
                        # （解析页自带 JS 会自行计算 token 并加载 m3u8，App 嗅探即可播放；
                        #   之前透传裸参数 co_xxx/JD-xxx 播放器直接 404）
                        print(f"蓝光2k/至臻4k直解失败({play_id})，嗅探兜底 parse:1")
                        return {"parse": 1, "url": f'{base}/?url={play_url}'}

                    # ★★★ 画质字段 + 对应解析接口 的完整映射 ★★★
                    # 每个画质字段可带独立 from（如 url_2k 走 BLAZ，url 走 JD4K）
                    # 结构：(字段名, 该字段专属 from, 是否蓝光类)
                    quality_map = [
                        # 蓝光/臻彩/4K蓝光 —— 一律走 BLAZ
                        ('url_4k蓝光', 'BLAZ', True), ('url_4k臻彩', 'BLAZ', True),
                        ('url_4k_bl', 'BLAZ', True), ('url_4k_zc', 'BLAZ', True),
                        ('url_bl', 'BLAZ', True), ('url_zc', 'BLAZ', True),
                        ('url_zb', 'BLAZ', True), ('url_zhencai', 'BLAZ', True),
                        ('url_bluray', 'BLAZ', True), ('url_uhd', 'BLAZ', True),
                        # ★★★ 2K —— 走 BLAZ（这就是"2K不能播放"的根因：之前被丢进通用流程）★★★
                        ('url_2k', 'BLAZ', True),
                        # 4K —— 优先 BLAZ，其次 JD4K
                        ('url_4k', 'BLAZ', True),
                        # 通用画质 —— 走各自 from，缺省则用主 play_id
                        ('url_1080p', '', False), ('url_1080', '', False),
                        ('url_next', '', False),
                        ('url_hd', '', False), ('url_fhd', '', False), ('url_720p', '', False),
                        ('url', '', False),  # 主 url 放在最后兜底
                    ]

                    # 若主 url 为空，用遍历中第一个可用的画质字段（如蓝光 only 的视频）兜底
                    if not play_url:
                        for fld, _, _ in quality_map:
                            v = pd.get(fld)
                            if v and isinstance(v, str) and v.strip():
                                play_url = v.strip()
                                break

                    if not play_url:
                        return {"parse": 0, "url": 'https://php.doube.eu.org/error.m3u8', "header": play_header}

                    for field, field_from, is_bl in quality_map:
                        q_url = pd.get(field)
                        if not q_url or not isinstance(q_url, str) or not q_url.strip():
                            continue
                        q_url = q_url.strip()

                        # 直链：直接返回（最高清优先，取首个命中即返回）
                        if _is_direct(q_url):
                            print(f"画质直链命中({field}): {q_url[:80]}")
                            return {"parse": 0, "url": q_url, "header": play_header}

                        # 确定本画质使用的解析接口：字段专属 from > 主 play_id > 默认 JD4K
                        use_from = field_from or play_id
                        resolved = None

                        if is_bl or use_from == 'BLAZ':
                            # 蓝光 / 2K 走 BLAZ 独立解析
                            resolved, blaz_header = _resolve_blaz(q_url)
                            if resolved:
                                print(f"蓝光/2K解析成功({field}): {resolved[:80]}")
                                return {"parse": 0, "url": resolved, "header": blaz_header or play_header}
                            # ★关键回退：BLAZ 失败时不丢"无数据"，
                            #   把原始蓝光参数透传为 parse:1，由播放器/框架自行解析
                            #   （网页能播说明该参数本身可解，只是 blzb.tv 这条路不通）
                            print(f"蓝光/2K解析失败({field})，透传原始参数 parse:1 -> {q_url[:80]}")
                            return {"parse": 1, "url": q_url}
                        else:
                            # 通用画质：优先用其专属接口，再降级 JD4K -> YYNB
                            candidates = []
                            if use_from and use_from in api_map:
                                candidates.append((use_from, api_map[use_from]))
                            for name in ['JD4K', 'YYNB', 'QIEBO', 'ZLB', 'FUQI']:
                                if name in api_map and api_map[name] not in [c[1] for c in candidates]:
                                    candidates.append((name, api_map[name]))
                            for api_name, api_url in candidates:
                                resolved = _resolve_token_post(api_url, q_url)
                                if resolved:
                                    print(f"画质解析成功({field} -> {api_name}): {resolved[:80]}")
                                    return {"parse": 0, "url": resolved, "header": play_header}
                    # 所有画质都遍历完仍未返回 → 走到下面兜底逻辑

        except Exception as e:
            print(f"playerContent error: {e}")

        # ===== 兜底：从播放页HTML / player_aaaa 中提取直链 =====
        html_local = locals().get('html', '')
        try:
            if html_local:
                # 优先再解析一次 player_aaaa，检查所有字段是否有直链
                m2 = re.search(r'player_aaaa=(.*?)</script>', html_local, re.S)
                if m2:
                    try:
                        pd2 = json.loads(m2.group(1))
                        for fb_field in ['url', 'url_next', 'url_2k', 'url_4k',
                                         'url_1080p', 'url_bl', 'url_zc', 'url_4k蓝光']:
                            fu = pd2.get(fb_field)
                            if _is_direct(fu):
                                print(f"兜底解析成功({fb_field}直链): {fu[:80]}")
                                return {"parse": 0, "url": fu.strip(), "header": play_header}
                    except Exception:
                        pass
                # 直接从HTML提取 m3u8/mp4 直链
                for pat in [r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
                            r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
                            r'(https?://[^\s"\'<>]{20,}?\.(m3u8|mp4)[^\s"\'<>]*)']:
                    found = re.findall(pat, html_local)
                    if found:
                        cand = found[0] if isinstance(found[0], str) else found[0][0]
                        if cand and 'error' not in cand.lower():
                            print(f"兜底直链命中: {cand[:80]}")
                            return {"parse": 0, "url": cand, "header": play_header}
        except Exception as e:
            print(f"fallback error: {e}")
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
        if u.startswith('//'): return 'https:' + u
        return u.replace('&amp;', '&')

    def _parse_video_list(self, html):
        videos, seen = [], set()
        soup = BeautifulSoup(html, 'html.parser')
        cards = soup.select('a.public-list-exp')
        for a in cards:
            href = a.get('href', '')
            m = re.search(r'/detail/(\d+)\.html', href)
            if not m: continue
            vod_id = m.group(1)
            if vod_id in seen: continue
            seen.add(vod_id)
            span = ','.join([span.text for span in a.select('span.public-prt')])
            # print('span', span)
            vod_name = a.get('title', '') or (a.select_one('img') and a.select_one('img').get('alt', '')) or ''
            pic_el = a.select_one('img')
            vod_pic = self._fix_pic(pic_el.get('data-src', '')) if pic_el else ''
            remark_el = a.select_one('.ft2') or a.select_one('.public-list-prb')
            vod_remarks = remark_el.text.strip() if remark_el else ''
            videos.append(
                {"vod_id": vod_id, "vod_name": vod_name.strip(), "vod_pic": vod_pic, "vod_remarks": vod_remarks, "vod_year": span})
        return videos

    def _parse_search_list(self, html):
        videos, seen = [], set()
        soup = BeautifulSoup(html, 'html.parser')
        cards = soup.select('a.public-list-exp')
        for a in cards:
            href = a.get('href', '')
            m = re.search(r'/detail/(\d+)\.html', href)
            if not m: continue
            vod_id = m.group(1)
            if vod_id in seen: continue
            seen.add(vod_id)
            pic_el = a.select_one('img')
            vod_pic = self._fix_pic(pic_el.get('data-src', '')) if pic_el else ''
            title_el = soup.select_one(f'a.thumb-txt[href="/detail/{vod_id}.html"]')
            if title_el:
                vod_name = title_el.text.strip()
            else:
                vod_name = a.select_one('img') and a.select_one('img').get('alt', '') or ''
            remark_el = a.select_one('.public-list-prb') or a.select_one('.ft2')
            vod_remarks = remark_el.text.strip() if remark_el else ''
            videos.append(
                {"vod_id": vod_id, "vod_name": vod_name.strip(), "vod_pic": vod_pic, "vod_remarks": vod_remarks})
        return videos

    def _parse_section(self, html, section_name):
        """从首页HTML中解析指定分类区块的视频列表"""
        videos, seen = [], set()
        if not html or '安全验证' in html or not section_name:
            return videos
        soup = BeautifulSoup(html, 'html.parser')
        for section in soup.select('.vod-list-b'):
            h2 = section.select_one('h2.this-name')
            if h2 and h2.get_text(strip=True) == section_name:
                for a in section.select('a.public-list-exp'):
                    href = a.get('href', '')
                    m = re.search(r'/detail/(\d+)\.html', href)
                    if not m:
                        continue
                    vod_id = m.group(1)
                    if vod_id in seen:
                        continue
                    seen.add(vod_id)
                    vod_name = a.get('title', '') or ''
                    if not vod_name:
                        img = a.select_one('img')
                        if img:
                            vod_name = img.get('alt', '') or ''
                    pic_el = a.select_one('img')
                    vod_pic = self._fix_pic(pic_el.get('data-src', '')) if pic_el else ''
                    remark_el = a.select_one('.ft2') or a.select_one('.public-list-prb')
                    vod_remarks = remark_el.text.strip() if remark_el else ''
                    span = ','.join([span.text for span in a.select('span.public-prt')])
                    videos.append(
                        {"vod_id": vod_id, "vod_name": vod_name.strip(), "vod_pic": vod_pic, "vod_remarks": vod_remarks, "vod_year": span})
                break
        return videos


if __name__ == '__main__':
    sp = Spider()
    sp.init()
    # 20067-5-189
    print(sp.categoryContent('/label/qq', '1', True, {}))
    # print(sp.playerContent('', '20067-6-189', []))
    # print(sp.playerContent('', '20067-5-189', []))
    pass
