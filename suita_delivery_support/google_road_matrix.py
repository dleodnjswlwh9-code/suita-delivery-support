"""Optional, billing-safe Google Routes Matrix adapter for P2.

Uses a separate SERVER API key. Never sends it to a browser and never calls
Google unless explicitly enabled and a cost budget has been configured.
All-or-nothing: an incomplete/unreachable matrix is not silently mixed into
an assumed Manhattan matrix. Returned matrix indices: north/south hubs, rows.
"""
from __future__ import annotations
import json
import math
import os
import time
import urllib.error
import urllib.request
from threading import RLock

API_URL = 'https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix'
FIELD_MASK = 'originIndex,destinationIndex,duration,distanceMeters,status,condition'
CACHE_LOCK = RLock()
_CACHE = {}


def _positive_int(value, default=0):
    try:
        n = int(value)
        return n if n >= 0 else default
    except (TypeError, ValueError):
        return default


def matrix_configuration(count: int, environ=None):
    """No paid request without explicit enable AND explicitly defined ceiling."""
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
        raise ValueError('invalid coordinates')
    return {'waypoint': {'location': {'latLng': {'latitude':lat, 'longitude':lng}}}}


def _parse_seconds(value):
    if not isinstance(value, str) or not value.endswith('s'):
        raise ValueError('Google duration missing')
    number=float(value[:-1])
    if not math.isfinite(number) or number < 0:
        raise ValueError('Google duration invalid')
    return number


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
        raise ValueError('Google returned non-array matrix response')
    expected=(r1-r0)*(c1-c0)
    if len(elements)!=expected:
        raise ValueError(f'Google matrix returned {len(elements)}/{expected} elements')
    result={}
    for e in elements:
        i=e.get('originIndex');j=e.get('destinationIndex')
        if not isinstance(i,int) or not isinstance(j,int) or i<0 or i>=r1-r0 or j<0 or j>=c1-c0:
            raise ValueError('Google route matrix indices incorrect')
        if e.get('condition')!='ROUTE_EXISTS' or e.get('status',{}).get('code',0) not in (0,None):
            raise ValueError('Google route matrix has an unreachable road section')
        result[(r0+i,c0+j)] = _parse_seconds(e.get('duration'))/60.0
    if len(result)!=expected:
        raise ValueError('Duplicate Google route matrix elements')
    return result


def road_time_matrix(coords, requester=None, environ=None):
    """Return (complete directed time matrix, source label).

    Cost guard is evaluated before any request. Makes 20x20 blocks (<=400
    billable elements each). Failed calls never produce partial time matrices.
    Traffic is a snapshot at request time, not a disaster traffic forecast.
    """
    env=os.environ if environ is None else environ
    if len(coords)<3:
        return None, '必要な地点座標がありません。'
    config=matrix_configuration(len(coords)-2,env)
    if not config['ready']:
        return None,config['reason']
    key=config['key']
    cache_key=(tuple((round(float(p['lat']),6),round(float(p['lng']),6)) for p in coords),
               # Traffic cache expires every 15 minutes.
               int(time.time()//900),key)
    if requester is None:
        with CACHE_LOCK:
            if cache_key in _CACHE:
                return [row[:] for row in _CACHE[cache_key]],'Google Routes Matrix（キャッシュ）'
    n=len(coords)
    result=[[None]*n for _ in range(n)]
    try:
        for r0 in range(0,n,20):
            r1=min(n,r0+20)
            for c0 in range(0,n,20):
                c1=min(n,c0+20)
                entries=_request_block(key,coords,r0,r1,c0,c1,requester)
                for (i,j),minutes in entries.items():result[i][j]=minutes
        if any(not isinstance(x,(float,int)) or not math.isfinite(x) for row in result for x in row):
            raise ValueError('Google did not return every directed arc')
    except (ValueError, KeyError, TypeError, TimeoutError, urllib.error.URLError, OSError) as e:
        # No partial road matrices: metrics must all share the same source.
        return None, f'Google道路時間行列取得不可：{str(e)[:110]}'
    if requester is None:
        with CACHE_LOCK:
            if len(_CACHE)>3:_CACHE.clear()
            _CACHE[cache_key]=result
    return result,'Google Routes Matrix（実道路・現在の交通状況）'
