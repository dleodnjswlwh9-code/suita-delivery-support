"""P2でGoogle Routesの道路時間行列を安全に取得する機能。

サーバー専用APIキーを使用し、ブラウザへ公開しない。
明示的な有効化と課金上限の設定がない場合は外部通信しない。
不完全な行列を推定時間と混在させず、全地点の時間が得られた場合のみ採用する。"""
from __future__ import annotations
import json
import math
import os
import time
import urllib.error
import urllib.request
from threading import RLock
from collections import deque

API_URL = 'https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix'
FIELD_MASK = 'originIndex,destinationIndex,duration,distanceMeters,status,condition'
CACHE_LOCK = RLock()
_CACHE = {}
# Googleの行列要素数の上限より低い、単一プロセスの保守的な要求制限を適用する。
_RATE_LOCK = RLock()
_RATE_EVENTS = deque()



def _positive_int(value, default=0):
    try:
        n = int(value)
        return n if n >= 0 else default
    except (TypeError, ValueError):
        return default


def matrix_configuration(count: int, environ=None):
    """利用許可と上限額が明示されていなければ有料の要求を行わない。"""
    env = os.environ if environ is None else environ
    enabled = str(env.get('GOOGLE_ROAD_MATRIX_ENABLED', '')).lower() in ('1', 'true', 'yes')
    key = str(env.get('GOOGLE_ROUTES_SERVER_API_KEY', '')).strip()
    budget = min(_positive_int(env.get('GOOGLE_MATRIX_MAX_ELEMENTS'), 0), 12000)
    elements = (count + 2) ** 2
    if not enabled:
        return dict(ready=False, reason='道路時間行列は無効です。推定時間を使用します。', elements=elements)
    if not key:
        return dict(ready=False, reason='サーバー用Google Routes APIキーがありません。', elements=elements)
    if budget < elements:
        return dict(ready=False, reason=f'Google道路時間行列は{elements}要素が必要ですが、API予算上限は{budget}要素です。', elements=elements)
    return dict(ready=True, reason='', elements=elements, key=key)


def _coordinate_waypoint(c):
    lat, lng = float(c['lat']), float(c['lng'])
    if not all(math.isfinite(v) for v in (lat, lng)) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError('緯度・経度の値が不正です。')
    return {'waypoint': {'location': {'latLng': {'latitude':lat, 'longitude':lng}}}}


def _parse_seconds(value):
    if not isinstance(value, str) or not value.endswith('s'):
        raise ValueError('Googleから所要時間が返されませんでした。')
    number=float(value[:-1])
    if not math.isfinite(number) or number < 0:
        raise ValueError('Googleから返された所要時間が不正です。')
    return number



def _wait_for_matrix_quota(elements, env):
    if elements<=0:return
    limit=min(max(_positive_int(env.get('GOOGLE_MATRIX_ELEMENTS_PER_MINUTE'),2800),400),2800)
    while True:
        with _RATE_LOCK:
            now=time.monotonic()
            while _RATE_EVENTS and now-_RATE_EVENTS[0][0]>61.0:
                _RATE_EVENTS.popleft()
            used=sum(cost for _,cost in _RATE_EVENTS)
            if used+elements <= limit:
                _RATE_EVENTS.append((now,elements))
                return
            remaining=61.0-(now-_RATE_EVENTS[0][0]) if _RATE_EVENTS else 1.0
        time.sleep(max(.1,remaining))

def _request_block(key, coords, r0, r1, c0, c1, requester=None):
    origins=[_coordinate_waypoint(p) for p in coords[r0:r1]]
    destinations=[_coordinate_waypoint(p) for p in coords[c0:c1]]
    body={'origins': origins, 'destinations': destinations,
          'travelMode':'DRIVE','routingPreference':'TRAFFIC_AWARE'}
    raw=json.dumps(body).encode('utf-8')
    req=urllib.request.Request(API_URL,data=raw,method='POST',headers={
        'Content-Type':'application/json','X-Goog-Api-Key':key,
        'X-Goog-FieldMask':FIELD_MASK})
    with (requester or urllib.request.urlopen)(req,timeout=18) as response:
        elements=json.loads(response.read().decode('utf-8'))
    if not isinstance(elements,list):
        raise ValueError('Googleの時間行列の応答形式が不正です。')
    expected=(r1-r0)*(c1-c0)
    if len(elements)!=expected:
        raise ValueError(f'Googleの道路時間行列は{expected}件中{len(elements)}件しか返されませんでした。')
    result={}
    for e in elements:
        i=e.get('originIndex');j=e.get('destinationIndex')
        if not isinstance(i,int) or not isinstance(j,int) or i<0 or i>=r1-r0 or j<0 or j>=c1-c0:
            raise ValueError('Googleの時間行列の地点番号が不正です。')
        if e.get('condition')!='ROUTE_EXISTS' or e.get('status',{}).get('code',0) not in (0,None):
            raise ValueError('Googleの道路時間行列に通行できない区間があります。')
        result[(r0+i,c0+j)] = _parse_seconds(e.get('duration'))/60.0
    if len(result)!=expected:
        raise ValueError('Googleの時間行列に重複した区間があります。')
    return result


def road_time_matrix(coords, requester=None, environ=None, progress_callback=None):
    """全地点間の方向別所要時間行列と取得元を返す。
    
    課金上限を事前確認し、分割して取得する。失敗時は部分的な行列を返さない。
    交通情報は要求時点のものであり、災害時の将来予測ではない。"""
    env=os.environ if environ is None else environ
    if len(coords)<3:
        return None, '必要な地点座標がありません。'
    config=matrix_configuration(len(coords)-2,env)
    if not config['ready']:
        return None,config['reason']
    key=config['key']
    cache_key=(tuple((round(float(p['lat']),6),round(float(p['lng']),6)) for p in coords),
               # 交通時間の保存結果は15分で更新する。
               int(time.time()//900),key)
    if requester is None:
        with CACHE_LOCK:
            if cache_key in _CACHE:
                return [row[:] for row in _CACHE[cache_key]],'Google道路時間行列（保存済み）'
    n=len(coords)
    result=[[None]*n for _ in range(n)]
    try:
        completed=0
        for r0 in range(0,n,20):
            r1=min(n,r0+20)
            for c0 in range(0,n,20):
                c1=min(n,c0+20)
                if requester is None:
                    _wait_for_matrix_quota((r1-r0)*(c1-c0),env)
                entries=_request_block(key,coords,r0,r1,c0,c1,requester)
                for (i,j),minutes in entries.items():result[i][j]=minutes
                completed+=len(entries)
                if progress_callback is not None:
                    progress_callback(completed,n*n)
        if any(not isinstance(x,(float,int)) or not math.isfinite(x) for row in result for x in row):
            raise ValueError('Googleの道路時間行列に不足している方向別区間があります。')
    except (ValueError, KeyError, TypeError, TimeoutError, urllib.error.URLError, OSError) as e:
        # 不完全な道路時間行列は使用せず、計算元を統一する。
        return None, f'Google道路時間行列取得不可：{str(e)[:110]}'
    if requester is None:
        with CACHE_LOCK:
            if len(_CACHE)>3:_CACHE.clear()
            _CACHE[cache_key]=result
    return result,'Google道路時間行列（実道路・現在の交通状況）'
