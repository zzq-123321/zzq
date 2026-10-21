# -*- coding: utf-8 -*-
# ============================================================
# 咪咕体育直播爬虫  (TVBox / FongMi  type=3 lives 爬虫源)
#
# 配置方法 (lives 数组中新增一条, 替换原来失效的"咪咕直播"):
#   {
#       "name": "咪咕体育",
#       "type": 3,
#       "api": "./lib/migu.py",
#       "ext": {},
#       "timeout": 10
#   }
#
# ext 支持 (JSON 字符串或对象, 均可省略):
#   {"stbid": "自定义设备号", "list_url": "远程m3u更新地址", "timeout": 10}
#   - stbid    : 请求里的机顶盒设备号, 默认 MiguSpider, 一般无需改
#   - list_url : 填了则每次初始化时拉取该 m3u 更新频道表, 失败自动回退内置表
#   - timeout  : 网络超时(秒)
#
# 播放链路: 本爬虫只负责生成频道表; 播放地址沿用咪咕官方
# GSLB 302 调度, 由播放器自行跟随跳转拿到 CDN 签名流。
# 注意: 不要在代码里改写 CDN 域名 (签名与原 Host 绑定, 改了会 403),
#       域名调度请用配置里的 hosts 规则(App 层 DNS 改写)。
# ============================================================

import json
import re
import sys
import base64

sys.path.append('..')
from base.spider import Spider

# 内置频道表: base64(JSON) 数组, 元素 = {name, group, tvg-name, logo, pid}
# pid 即咪咕 Contentid; 更新时只需用新表重新 base64 编码后替换本段
CHANNELS_B64 = (
    "W3sibmFtZSI6ICLnnZvlvanlub/lnLroiJ4iLCAiZ3JvdXAiOiAi552b5b2pIiwgInR2Zy1uYW1lIjogIuedm+W9qeW5v+Wc"
    "uuiIniIsICJsb2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v552b5b2p5bm/5Zy66IieLndlYnAiLCAi"
    "cGlkIjogIjMwMDAwMDAwMjAwMDAwMTE1MjMifSwgeyJuYW1lIjogIuedm+W9qemdkuWwkSIsICJncm91cCI6ICLnnZvlvaki"
    "LCAidHZnLW5hbWUiOiAi552b5b2p6Z2S5bCRIiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54eXovbG9nby/n"
    "nZvlvanpnZLlsJEud2VicCIsICJwaWQiOiAiMzAwMDAwMDAyMDAwMDAxMTUyNSJ9LCB7Im5hbWUiOiAi552b5b2p56ue5oqA"
    "IiwgImdyb3VwIjogIuedm+W9qSIsICJ0dmctbmFtZSI6ICLnnZvlvannq57mioAiLCAibG9nbyI6ICJodHRwczovL2lwdHYu"
    "eWFuZy0xOTg5Lnh5ei9sb2dvL+edm+W9qeernuaKgC53ZWJwIiwgInBpZCI6ICIzMDAwMDAwMDIwMDAwMDExNTI4In0sIHsi"
    "bmFtZSI6ICLnnZvlvannr67nkIMiLCAiZ3JvdXAiOiAi552b5b2pIiwgInR2Zy1uYW1lIjogIuedm+W9qeevrueQgyIsICJs"
    "b2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v552b5b2p56+u55CDLndlYnAiLCAicGlkIjogIjMwMDAw"
    "MDAwMjAwMDAwMTE1MjkifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi00Sy0xIiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIs"
    "ICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRwczovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WS"
    "quinhueVjDRLLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMTAwMDAwMDUxODAifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi00"
    "Sy0yIiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRw"
    "czovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WSquinhueVjDRLLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMTAwMDAwMTU2"
    "ODYifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi0wMSIsICJncm91cCI6ICLlkqrlkpXkvZPogrIiLCAidHZnLW5hbWUiOiAi"
    "5ZKq5ZKV5L2T6IKyIiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54eXovbG9nby/lkqrop4bnlYwud2VicCIs"
    "ICJwaWQiOiAiMzAwMDAwMDAwMTAwMDAwNTMwOCJ9LCB7Im5hbWUiOiAi5ZKq5ZKV5L2T6IKyLTAyIiwgImdyb3VwIjogIuWS"
    "quWSleS9k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRwczovL2lwdHYueWFuZy0xOTg5"
    "Lnh5ei9sb2dvL+WSquinhueVjC53ZWJwIiwgInBpZCI6ICIzMDAwMDAwMDAxMDAwMDA1OTY5In0sIHsibmFtZSI6ICLlkqrl"
    "kpXkvZPogrItMDMiLCAiZ3JvdXAiOiAi5ZKq5ZKV5L2T6IKyIiwgInR2Zy1uYW1lIjogIuWSquWSleS9k+iCsiIsICJsb2dv"
    "IjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v5ZKq6KeG55WMLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMDEw"
    "MDAwMDcyMTgifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi0wNCIsICJncm91cCI6ICLlkqrlkpXkvZPogrIiLCAidHZnLW5h"
    "bWUiOiAi5ZKq5ZKV5L2T6IKyIiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54eXovbG9nby/lkqrop4bnlYwu"
    "d2VicCIsICJwaWQiOiAiMzAwMDAwMDAwMTAwMDAwODAwMSJ9LCB7Im5hbWUiOiAi5ZKq5ZKV5L2T6IKyLTA1IiwgImdyb3Vw"
    "IjogIuWSquWSleS9k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRwczovL2lwdHYueWFu"
    "Zy0xOTg5Lnh5ei9sb2dvL+WSquinhueVjC53ZWJwIiwgInBpZCI6ICIzMDAwMDAwMDAxMDAwMDA4MTc2In0sIHsibmFtZSI6"
    "ICLlkqrlkpXkvZPogrItMDYiLCAiZ3JvdXAiOiAi5ZKq5ZKV5L2T6IKyIiwgInR2Zy1uYW1lIjogIuWSquWSleS9k+iCsiIs"
    "ICJsb2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v5ZKq6KeG55WMLndlYnAiLCAicGlkIjogIjMwMDAw"
    "MDAwMDEwMDAwMDgzNzkifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi0wNyIsICJncm91cCI6ICLlkqrlkpXkvZPogrIiLCAi"
    "dHZnLW5hbWUiOiAi5ZKq5ZKV5L2T6IKyIiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54eXovbG9nby/lkqro"
    "p4bnlYwud2VicCIsICJwaWQiOiAiMzAwMDAwMDAwMTAwMDAxMDEyOSJ9LCB7Im5hbWUiOiAi5ZKq5ZKV5L2T6IKyLTA4Iiwg"
    "Imdyb3VwIjogIuWSquWSleS9k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRwczovL2lw"
    "dHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WSquinhueVjC53ZWJwIiwgInBpZCI6ICIzMDAwMDAwMDAxMDAwMDEwOTQ4In0sIHsi"
    "bmFtZSI6ICLlkqrlkpXkvZPogrItMDkiLCAiZ3JvdXAiOiAi5ZKq5ZKV5L2T6IKyIiwgInR2Zy1uYW1lIjogIuWSquWSleS9"
    "k+iCsiIsICJsb2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v5ZKq6KeG55WMLndlYnAiLCAicGlkIjog"
    "IjMwMDAwMDAwMDEwMDAwMjg2MzgifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi0xMCIsICJncm91cCI6ICLlkqrlkpXkvZPo"
    "grIiLCAidHZnLW5hbWUiOiAi5ZKq5ZKV5L2T6IKyIiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54eXovbG9n"
    "by/lkqrop4bnlYwud2VicCIsICJwaWQiOiAiMzAwMDAwMDAwMTAwMDAzMTQ5NCJ9LCB7Im5hbWUiOiAi5ZKq5ZKV5L2T6IKy"
    "LTExIiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRw"
    "czovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WSquinhueVjC53ZWJwIiwgInBpZCI6ICIzMDAwMDAwMDEwMDAwMDAwMDk3"
    "In0sIHsibmFtZSI6ICLlkqrlkpXkvZPogrItMTIiLCAiZ3JvdXAiOiAi5ZKq5ZKV5L2T6IKyIiwgInR2Zy1uYW1lIjogIuWS"
    "quWSleS9k+iCsiIsICJsb2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v5ZKq6KeG55WMLndlYnAiLCAi"
    "cGlkIjogIjMwMDAwMDAwMTAwMDAwMDIwMTkifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi0xMyIsICJncm91cCI6ICLlkqrl"
    "kpXkvZPogrIiLCAidHZnLW5hbWUiOiAi5ZKq5ZKV5L2T6IKyIiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54"
    "eXovbG9nby/lkqrop4bnlYwud2VicCIsICJwaWQiOiAiMzAwMDAwMDAxMDAwMDAwMjgwOSJ9LCB7Im5hbWUiOiAi5ZKq5ZKV"
    "5L2T6IKyLTE0IiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6"
    "ICJodHRwczovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WSquinhueVjC53ZWJwIiwgInBpZCI6ICIzMDAwMDAwMDEwMDAw"
    "MDAzOTE1In0sIHsibmFtZSI6ICLlkqrlkpXkvZPogrItMTUiLCAiZ3JvdXAiOiAi5ZKq5ZKV5L2T6IKyIiwgInR2Zy1uYW1l"
    "IjogIuWSquWSleS9k+iCsiIsICJsb2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v5ZKq6KeG55WMLndl"
    "YnAiLCAicGlkIjogIjMwMDAwMDAwMTAwMDAwMDQxOTMifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi0xNiIsICJncm91cCI6"
    "ICLlkqrlkpXkvZPogrIiLCAidHZnLW5hbWUiOiAi5ZKq5ZKV5L2T6IKyIiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2Lnlhbmct"
    "MTk4OS54eXovbG9nby/lkqrop4bnlYwud2VicCIsICJwaWQiOiAiMzAwMDAwMDAxMDAwMDAwNTgzNyJ9LCB7Im5hbWUiOiAi"
    "5ZKq5ZKV5L2T6IKyLTE3IiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAi"
    "bG9nbyI6ICJodHRwczovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WSquinhueVjC53ZWJwIiwgInBpZCI6ICIzMDAwMDAw"
    "MDEwMDAwMDA2MDc3In0sIHsibmFtZSI6ICLlkqrlkpXkvZPogrItMTgiLCAiZ3JvdXAiOiAi5ZKq5ZKV5L2T6IKyIiwgInR2"
    "Zy1uYW1lIjogIuWSquWSleS9k+iCsiIsICJsb2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v5ZKq6KeG"
    "55WMLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMTAwMDAwMDY2NTgifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi0xOSIsICJn"
    "cm91cCI6ICLlkqrlkpXkvZPogrIiLCAidHZnLW5hbWUiOiAi5ZKq5ZKV5L2T6IKyIiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2"
    "LnlhbmctMTk4OS54eXovbG9nby/lkqrop4bnlYwud2VicCIsICJwaWQiOiAiMzAwMDAwMDAxMDAwMDAwOTc4OCJ9LCB7Im5h"
    "bWUiOiAi5ZKq5ZKV5L2T6IKyLTIwIiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPo"
    "grIiLCAibG9nbyI6ICJodHRwczovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WSquinhueVjC53ZWJwIiwgInBpZCI6ICIz"
    "MDAwMDAwMDEwMDAwMDEwODMzIn0sIHsibmFtZSI6ICLlkqrlkpXkvZPogrItMjEiLCAiZ3JvdXAiOiAi5ZKq5ZKV5L2T6IKy"
    "IiwgInR2Zy1uYW1lIjogIuWSquWSleS9k+iCsiIsICJsb2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v"
    "5ZKq6KeG55WMLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMTAwMDAwMTEyOTcifSwgeyJuYW1lIjogIuWSquWSleS9k+iCsi0y"
    "MiIsICJncm91cCI6ICLlkqrlkpXkvZPogrIiLCAidHZnLW5hbWUiOiAi5ZKq5ZKV5L2T6IKyIiwgImxvZ28iOiAiaHR0cHM6"
    "Ly9pcHR2LnlhbmctMTk4OS54eXovbG9nby/lkqrop4bnlYwud2VicCIsICJwaWQiOiAiMzAwMDAwMDAxMDAwMDAxMTUxOCJ9"
    "LCB7Im5hbWUiOiAi5ZKq5ZKV5L2T6IKyLTIzIiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrl"
    "kpXkvZPogrIiLCAibG9nbyI6ICJodHRwczovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WSquinhueVjC53ZWJwIiwgInBp"
    "ZCI6ICIzMDAwMDAwMDEwMDAwMDEyNTU4In0sIHsibmFtZSI6ICLlkqrlkpXkvZPogrItMjQiLCAiZ3JvdXAiOiAi5ZKq5ZKV"
    "5L2T6IKyIiwgInR2Zy1uYW1lIjogIuWSquWSleS9k+iCsiIsICJsb2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5ODkueHl6"
    "L2xvZ28v5ZKq6KeG55WMLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMTAwMDAwMTI2MTYifSwgeyJuYW1lIjogIuWSquWSleS9"
    "k+iCsi0yNSIsICJncm91cCI6ICLlkqrlkpXkvZPogrIiLCAidHZnLW5hbWUiOiAi5ZKq5ZKV5L2T6IKyIiwgImxvZ28iOiAi"
    "aHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54eXovbG9nby/lkqrop4bnlYwud2VicCIsICJwaWQiOiAiMzAwMDAwMDAxMDAwMDAx"
    "NTQ3MCJ9LCB7Im5hbWUiOiAi5ZKq5ZKV5L2T6IKyLTI2IiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIsICJ0dmctbmFtZSI6"
    "ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRwczovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WSquinhueVjC53ZWJw"
    "IiwgInBpZCI6ICIzMDAwMDAwMDEwMDAwMDE1NTYwIn0sIHsibmFtZSI6ICLlkqrlkpXkvZPogrItMjciLCAiZ3JvdXAiOiAi"
    "5ZKq5ZKV5L2T6IKyIiwgInR2Zy1uYW1lIjogIuWSquWSleS9k+iCsiIsICJsb2dvIjogImh0dHBzOi8vaXB0di55YW5nLTE5"
    "ODkueHl6L2xvZ28v5ZKq6KeG55WMLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMTAwMDAwMTk4MzkifSwgeyJuYW1lIjogIuWS"
    "quWSleS9k+iCsi0yOCIsICJncm91cCI6ICLlkqrlkpXkvZPogrIiLCAidHZnLW5hbWUiOiAi5ZKq5ZKV5L2T6IKyIiwgImxv"
    "Z28iOiAiaHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54eXovbG9nby/lkqrop4bnlYwud2VicCIsICJwaWQiOiAiMzAwMDAwMDAx"
    "MDAwMDAyMTkwNCJ9LCB7Im5hbWUiOiAi5ZKq5ZKV5L2T6IKyLTI5IiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIsICJ0dmct"
    "bmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRwczovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WSquinhueV"
    "jC53ZWJwIiwgInBpZCI6ICIzMDAwMDAwMDEwMDAwMDIzNDM0In0sIHsibmFtZSI6ICLlkqrlkpXkvZPogrItMzAiLCAiZ3Jv"
    "dXAiOiAi5ZKq5ZKV5L2T6IKyIiwgInR2Zy1uYW1lIjogIuWSquWSleS9k+iCsiIsICJsb2dvIjogImh0dHBzOi8vaXB0di55"
    "YW5nLTE5ODkueHl6L2xvZ28v5ZKq6KeG55WMLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMTAwMDAwMjUzODAifSwgeyJuYW1l"
    "IjogIuWSquWSleS9k+iCsi0zMSIsICJncm91cCI6ICLlkqrlkpXkvZPogrIiLCAidHZnLW5hbWUiOiAi5ZKq5ZKV5L2T6IKy"
    "IiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54eXovbG9nby/lkqrop4bnlYwud2VicCIsICJwaWQiOiAiMzAw"
    "MDAwMDAxMDAwMDAyNzY5MSJ9LCB7Im5hbWUiOiAi5ZKq5ZKV5L2T6IKyLTMyIiwgImdyb3VwIjogIuWSquWSleS9k+iCsiIs"
    "ICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRwczovL2lwdHYueWFuZy0xOTg5Lnh5ei9sb2dvL+WS"
    "quinhueVjC53ZWJwIiwgInBpZCI6ICIzMDAwMDAwMDIwMDAwMDExNTE4In0sIHsibmFtZSI6ICLlkqrlkpXkvZPogrItMzMi"
    "LCAiZ3JvdXAiOiAi5ZKq5ZKV5L2T6IKyIiwgInR2Zy1uYW1lIjogIuWSquWSleS9k+iCsiIsICJsb2dvIjogImh0dHBzOi8v"
    "aXB0di55YW5nLTE5ODkueHl6L2xvZ28v5ZKq6KeG55WMLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMjAwMDAwMTE1MTkifSwg"
    "eyJuYW1lIjogIuWSquWSleS9k+iCsi0zNCIsICJncm91cCI6ICLlkqrlkpXkvZPogrIiLCAidHZnLW5hbWUiOiAi5ZKq5ZKV"
    "5L2T6IKyIiwgImxvZ28iOiAiaHR0cHM6Ly9pcHR2LnlhbmctMTk4OS54eXovbG9nby/lkqrop4bnlYwud2VicCIsICJwaWQi"
    "OiAiMzAwMDAwMDAyMDAwMDAxMTUyMCJ9LCB7Im5hbWUiOiAi5ZKq5ZKV5L2T6IKyLTM1IiwgImdyb3VwIjogIuWSquWSleS9"
    "k+iCsiIsICJ0dmctbmFtZSI6ICLlkqrlkpXkvZPogrIiLCAibG9nbyI6ICJodHRwczovL2lwdHYueWFuZy0xOTg5Lnh5ei9s"
    "b2dvL+WSquinhueVjC53ZWJwIiwgInBpZCI6ICIzMDAwMDAwMDIwMDAwMDExNTIxIn0sIHsibmFtZSI6ICLlkqrlkpXkvZPo"
    "grItMzYiLCAiZ3JvdXAiOiAi5ZKq5ZKV5L2T6IKyIiwgInR2Zy1uYW1lIjogIuWSquWSleS9k+iCsiIsICJsb2dvIjogImh0"
    "dHBzOi8vaXB0di55YW5nLTE5ODkueHl6L2xvZ28v5ZKq6KeG55WMLndlYnAiLCAicGlkIjogIjMwMDAwMDAwMjAwMDAwMTE1"
    "MjIifV0="
)


class Spider(Spider):

    def getName(self):
        return "咪咕体育"

    def init(self, extend):
        self.timeout = 10
        self.stbid = "MiguSpider"
        self.list_url = ""
        try:
            ext = extend
            if isinstance(ext, str) and ext.strip():
                ext = json.loads(ext)
            if isinstance(ext, dict):
                self.stbid = str(ext.get("stbid") or self.stbid)
                self.list_url = str(ext.get("list_url") or "")
                self.timeout = int(ext.get("timeout") or self.timeout)
        except Exception:
            pass
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        self.channels = self.load_channels()

    # ---------------- 频道表 ----------------
    def load_channels(self):
        chans = []
        if self.list_url:
            try:
                import requests
                r = requests.get(self.list_url, headers=self.headers, timeout=self.timeout)
                if r.status_code == 200 and "#EXTINF" in r.text:
                    chans = self.parse_m3u(r.text)
            except Exception:
                chans = []
        if not chans:
            chans = json.loads(self.b64decode(CHANNELS_B64))
        return chans

    def parse_m3u(self, text):
        chans = []
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not line.startswith("#EXTINF"):
                continue
            url = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if "Contentid=" not in url:
                continue
            name = line.rsplit(",", 1)[-1].strip()
            tvg = self._attr(line, "tvg-name") or name
            logo = self._attr(line, "tvg-logo")
            group = self._attr(line, "group-title") or "咪咕体育"
            pid = url.split("Contentid=")[-1].split("&")[0]
            chans.append({"name": name, "group": group, "tvg-name": tvg, "logo": logo, "pid": pid})
        return chans

    @staticmethod
    def _attr(s, key):
        m = re.search(key + r'="([^"]*)"', s)
        return m.group(1) if m else ""

    # ---------------- 直播接口 ----------------
    def liveContent(self, url):
        out = ["#EXTM3U"]
        for c in self.channels:
            out.append('#EXTINF:-1 tvg-id="{t}" tvg-name="{t}" tvg-logo="{l}" group-title="{g}",{n}'.format(
                t=c.get("tvg-name", ""), l=c.get("logo", ""), g=c.get("group", "咪咕体育"), n=c["name"]))
            out.append("{p}&fun=mg&pid={pid}".format(p=self.getProxyUrl(), pid=c["pid"]))
        return "\n".join(out)

    def localProxy(self, params):
        if params.get("fun") == "mg":
            return self.fun_mg(params)
        return [302, "text/plain", None, {"Location": ""}]

    def fun_mg(self, params):
        # 返回咪咕 GSLB 入口, 播放器自行完成 302 调度与 CDN 鉴权
        pid = params.get("pid", "")
        play = ("http://gslbserv.itv.cmvideo.cn/index.m3u8?channel-id=FifastbLive"
                "&Contentid=" + pid + "&livemode=1&stbId=" + self.stbid)
        return [302, "text/plain", None, {"Location": play}]

    # ---------------- 以下为爬虫框架必需的空实现 ----------------
    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def homeContent(self, filter):
        return {}

    def homeVideoContent(self):
        return {}

    def categoryContent(self, cid, page, filter, ext):
        return {}

    def detailContent(self, did):
        return {}

    def searchContent(self, key, quick, page='1'):
        return {}

    def searchContentPage(self, keywords, quick, page):
        return {}

    def playerContent(self, flag, pid, vipFlags):
        return {}

    def destroy(self):
        return "正在Destroy"

    def b64encode(self, data):
        return base64.b64encode(data.encode("utf-8")).decode("utf-8")

    def b64decode(self, data):
        return base64.b64decode(data.encode("utf-8")).decode("utf-8")


if __name__ == '__main__':
    pass
