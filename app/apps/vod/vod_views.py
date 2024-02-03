#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : views.py
# Author: DaShenHan&道长-----先苦后甜，任凭晚风拂柳颜------
# Author's Blog: https://blog.csdn.net/qq_32394351
# Date  : 2023/12/7
import base64
import json

from fastapi import APIRouter, Request, Depends, Response, Query, File, UploadFile
from fastapi.responses import RedirectResponse
from typing import Any
from sqlalchemy.orm import Session

from .gen_vod import Vod
from common import error_code
from common.resp import respVodJson, respErrorJson, abort
from urllib.parse import quote, unquote
import requests
from apps.permission.models.user import Users
from apps.vod.curd.curd_configs import curd_vod_configs

from common import deps
from core.logger import logger

router = APIRouter()

access_name = 'vod:generate'
api_url = ''


# u: Users = Depends(deps.user_perm([f"{access_name}:get"]))
# @router.get(api_url + "/{api:path}", summary="生成Vod")
@router.api_route(methods=['GET', 'POST', 'HEAD'], path=api_url + "/{api:path}", summary="生成Vod")
def vod_generate(*, api: str = "", request: Request,
                 db: Session = Depends(deps.get_db),
                 ) -> Any:
    """
    这个接口千万不要写async def 否则类似这种内部接口文件请求将无法实现 http://192.168.31.49:5707/files/hipy/两个BT.json
    通过动态import的形式，统一处理vod:爬虫源T4接口
    ext参数默认为空字符串，传入api配置里对应的ext，可以是文本和链接
    """

    def getParams(key=None, value=''):
        return request.query_params.get(key) or value

    # 拿到query参数的字典
    params_dict = request.query_params.__dict__['_dict']
    # 拿到网页host地址
    host = str(request.base_url)
    # 拿到完整的链接
    whole_url = str(request.url)
    # 拼接字符串得到t4_api本地代理接口地址
    api_url = str(request.url).split('?')[0]
    t4_api = f'{api_url}?proxy=true&do=py'
    # 获取请求类型
    req_method = request.method.lower()

    # 本地代理所需参数
    proxy = getParams('proxy')
    do = getParams('do')
    # 是否为本地代理请求
    is_proxy = proxy and do == 'py'

    # 判断head请求但不是本地代理直接干掉
    # if req_method == 'head' and (t4_api + '&') not in whole_url:
    if req_method == 'head' and not is_proxy:
        return abort(403)

    if not is_proxy:
        # 非本地代理请求需要验证密码
        pwd = getParams('pwd')
        try:
            vod_configs_obj = curd_vod_configs.getByKey(db, key='vod_passwd')
            vod_passwd = vod_configs_obj.get('value') if vod_configs_obj.get('status') == 1 else ''
        except Exception as e:
            logger.info(f'获取vod_passwd发生错误:{e}')
            vod_passwd = ''
        if vod_passwd and pwd != vod_passwd:
            return abort(403)

    try:
        vod = Vod(api=api, query_params=request.query_params, t4_api=t4_api).module
    except Exception as e:
        return respErrorJson(error_code.ERROR_INTERNAL.set_msg(f"内部服务器错误:{e}"))

    ac = getParams('ac')
    ids = getParams('ids')
    filters = getParams('f')  # t1 筛选 {'cid':'1'}
    ext = getParams('ext')  # t4筛选传入base64加密的json字符串
    api_ext = getParams('api_ext')  # t4初始化api的扩展参数
    extend = getParams('extend')  # t4初始化配置里的ext参数
    filterable = getParams('filter')  # t4能否筛选
    if req_method == 'post':  # t4 ext网络数据太长会自动post,此时强制可筛选
        filterable = True
    wd = getParams('wd')
    quick = getParams('quick')
    play_url = getParams('play_url')  # 类型为t1的时候播放链接带这个进行解析
    play = getParams('play')  # 类型为4的时候点击播放会带上来
    flag = getParams('flag')  # 类型为4的时候点击播放会带上来
    t = getParams('t')
    pg = getParams('pg', '1')
    pg = int(pg)
    q = getParams('q')
    ad_remove = getParams('adRemove')
    ad_url = getParams('url')
    ad_headers = getParams('headers')
    ad_name = getParams('name') or 'm3u8'

    extend = extend or api_ext
    vod.setExtendInfo(extend)

    # 获取依赖项
    depends = vod.getDependence()
    modules = []
    module_names = []
    for lib in depends:
        try:
            module = Vod(api=lib, query_params=request.query_params, t4_api=t4_api).module
            modules.append(module)
            module_names.append(lib)
        except Exception as e:
            logger.info(f'装载依赖{lib}发生错误:{e}')
            # return respErrorJson(error_code.ERROR_INTERNAL.set_msg(f"内部服务器错误:{e}"))

    if len(module_names) > 0:
        logger.info(f'当前依赖列表:{module_names}')

    vod.init(modules)

    if ext and not ext.startswith('http'):
        try:
            # ext = json.loads(base64.b64decode(ext).decode("utf-8"))
            filters = base64.b64decode(ext).decode("utf-8")
        except Exception as e:
            logger.error(f'解析发生错误:{e}。未知的ext:{ext}')

    # rule_title = vod.getName().encode('utf-8').decode('latin1')
    rule_title = vod.getName()
    if rule_title:
        logger.info(f'加载爬虫源:{rule_title}')

    if is_proxy:
        # 测试地址:
        # http://192.168.31.49:5707/api/v1/vod/base_spider?proxy=1&do=py&url=https://s1.bfzycdn.com/video/renmindemingyi/%E7%AC%AC07%E9%9B%86/index.m3u8&adRemove=reg:/video/adjump(.*?)ts
        if ad_remove.startswith('reg:') and ad_url.endswith('.m3u8'):
            headers = {}
            if ad_headers:
                try:
                    headers = json.loads(unquote(ad_headers))
                except:
                    pass

            try:
                r = requests.get(ad_url, headers=headers)
                text = r.text
                # text = vod.replaceAll(text, ad_remove[4:], '')
                m3u8_text = vod.fixAdM3u8(text, ad_url, ad_remove)
                # return Response(status_code=200, media_type='video/MP2T', content=m3u8_text)
                media_type = 'text/plain' if 'txt' in ad_name else 'video/MP2T'
                return Response(status_code=200, media_type=media_type, content=m3u8_text)
            except Exception as e:
                error_msg = f"localProxy执行ad_remove发生内部服务器错误:{e}"
                logger.error(error_msg)
                return respErrorJson(error_code.ERROR_INTERNAL.set_msg(error_msg))

        try:
            back_resp_list = vod.localProxy(params_dict)
            status_code = back_resp_list[0]
            media_type = back_resp_list[1]
            content = back_resp_list[2]
            headers = back_resp_list[3] if len(back_resp_list) > 3 else None
            # if isinstance(content, str):
            #     content = content.encode('utf-8')
            return Response(status_code=status_code, media_type=media_type, content=content, headers=headers)
        except Exception as e:
            error_msg = f"localProxy执行发生内部服务器错误:{e}"
            logger.error(error_msg)
            return respErrorJson(error_code.ERROR_INTERNAL.set_msg(error_msg))

    if play:  # t4播放
        try:
            play_url = vod.playerContent(flag, play, vipFlags=None)
            if isinstance(play_url, str):
                player_dict = {'parse': 0, 'playUrl': '', 'jx': 0, 'url': play_url}
            elif isinstance(play_url, dict):
                player_dict = play_url.copy()
            else:
                return abort(404, f'不支持的返回类型:{type(play_url)}\nplay_url:{play_url}')

            if str(player_dict.get('parse')) == '1' and not player_dict.get('isVideo'):
                player_dict['isVideo'] = vod.isVideo()
            if not player_dict.get('adRemove'):
                player_dict['adRemove'] = vod.adRemove()

            # 有 adRemove参数并且不需要嗅探,并且地址以http开头.m3u8结尾 并且不是本地代理地址
            proxy_url = vod.getProxyUrl()
            if player_dict.get('adRemove') and str(player_dict.get('parse')) == '0' \
                    and str(player_dict.get('url')).startswith('http') and str(player_dict.get('url')).endswith('.m3u8') \
                    and not str(player_dict.get('url')).startswith(proxy_url):
                # 删除字段并给url字段加代理
                adRemove = player_dict['adRemove']
                del player_dict['adRemove']
                player_dict['url'] = proxy_url + '&url=' + player_dict[
                    'url'] + f'&adRemove={quote(adRemove)}&name=1.m3u8'

            return respVodJson(player_dict)

        except Exception as e:
            error_msg = f"playerContent执行发生内部服务器错误:{e}"
            logger.error(error_msg)
            return respErrorJson(error_code.ERROR_INTERNAL.set_msg(error_msg))

    if play_url:  # t1播放
        play_url = vod.playerContent(flag, play_url, vipFlags=None)
        if isinstance(play_url, str):
            return RedirectResponse(play_url, status_code=301)
        elif isinstance(play_url, dict):
            return respVodJson(play_url)
        else:
            return play_url

    if ac and t:  # 一级
        try:
            fl = {}
            if filters and filters.find('{') > -1 and filters.find('}') > -1:
                fl = json.loads(filters)
            # print(filters,type(filters))
            # print(fl,type(fl))
            logger.info(fl)
            data = vod.categoryContent(t, pg, filterable, fl)
            return respVodJson(data)
        except Exception as e:
            error_msg = f"categoryContent执行发生内部服务器错误:{e}"
            logger.error(error_msg)
            return respErrorJson(error_code.ERROR_INTERNAL.set_msg(error_msg))

    if ac and ids:  # 二级
        try:
            id_list = ids.split(',')
            data = vod.detailContent(id_list)
            return respVodJson(data)
        except Exception as e:
            error_msg = f"detailContent执行发生内部服务器错误:{e}"
            logger.error(error_msg)
            return respErrorJson(error_code.ERROR_INTERNAL.set_msg(error_msg))
    if wd:  # 搜索
        try:
            data = vod.searchContent(wd, quick, pg)
            return respVodJson(data)
        except Exception as e:
            error_msg = f"searchContent执行发生内部服务器错误:{e}"
            logger.error(error_msg)
            return respErrorJson(error_code.ERROR_INTERNAL.set_msg(error_msg))

    home_data = vod.homeContent(filterable) or {}
    home_video_data = vod.homeVideoContent() or {}
    home_data.update(home_video_data)

    return respVodJson(home_data)
