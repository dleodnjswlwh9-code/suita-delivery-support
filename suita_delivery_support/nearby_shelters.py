"""Google Routes API (WALK) near-shelter matching; never substitute aerial distance.

Distance request is explicitly user initiated and requires its own billable opt-in.
Master dataset validation prevents turning this paid endpoint into a generic proxy.
"""
from __future__ import annotations
import json
import math
import os
import hashlib
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API_URL = 'https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix'
FIELD_MASK = 'originIndex,destinationIndex,status,condition,distanceMeters'
CACHE = {}
LOCK = threading.RLock()

class NearbyError(ValueError): pass

def haversine_m(a,b):
    r=math.pi/180
    dlat=(b['lat']-a['lat'])*r
    dlng=(b['lng']-a['lng'])*r
    v=math.sin(dlat/2)**2+math.cos(a['lat']*r)*math.cos(b['lat']*r)*math.sin(dlng/2)**2
    return 12742000*math.asin(min(1,math.sqrt(v)))

def eligible_master():
    data=json.loads((Path(__file__).resolve().parent/'data'/'allocation_shelters.json').read_text(encoding='utf-8'))
    return [s for s in data if float(s['stock'].get('retortRice') or 0)>0 and float(s['stock'].get('water500ml') or 0)>0]

def validate_shelters(submitted):
    master=eligible_master()
    if not isinstance(submitted,list) or len(submitted)!=len(master):
        raise NearbyError(f'登録済みの対象避難所{len(master)}か所を使用してください。')
    by_name={str(x['name']).strip():x for x in master}
    names=[]
    for v in submitted:
        if not isinstance(v,dict):raise NearbyError('避難所データが不正です。')
        name=str(v.get('name','')).strip()
        if name not in by_name or name in names:raise NearbyError('対象避難所名を確認してください。')
        names.append(name)
        base=by_name[name]
        try: lat=float(v['lat']);lng=float(v['lng'])
        except (KeyError,ValueError,TypeError):raise NearbyError('緯度・経度を確認してください。')
        if not math.isfinite(lat) or not math.isfinite(lng) or haversine_m({'lat':lat,'lng':lng},base)>2000:
            raise NearbyError('補正座標が登録避難所から2km以上離れています。施設名・位置を確認してください。')
    if len(names)!=len(set(names)):raise NearbyError('重複する避難所があります。')
    return submitted

def candidate_pairs(master, max_distance=500):
    return [(i,j,round(haversine_m(a,b),2)) for i,a in enumerate(master) for j,b in enumerate(master) if i<j and haversine_m(a,b)<=max_distance+0.05]

def _point(p):
    return {'waypoint':{'location':{'latLng':{'latitude':float(p['lat']),'longitude':float(p['lng'])}}}}

def _request_for_origin(origin, targets, key, opener=None):
    body={'origins':[_point(origin)],'destinations':[_point(v) for v in targets], 'travelMode':'WALK','languageCode':'ja','regionCode':'JP'}
    req=urllib.request.Request(API_URL, data=json.dumps(body).encode('utf-8'),method='POST',headers={
        'Content-Type':'application/json','X-Goog-Api-Key':key,'X-Goog-FieldMask':FIELD_MASK})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=35) as resp:
            res=json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as err:
        try: reason=json.loads(err.read().decode('utf-8')).get('error',{}).get('message','')
        except Exception:reason=''
        raise NearbyError('Google Routes API応答エラー ('+str(err.code)+'): '+str(reason)[:180]) from err
    if not isinstance(res,list) or len(res)!=len(targets):
        raise NearbyError('徒歩距離行列の応答件数が不正です。')
    vals={}
    for e in res:
        j=e.get('destinationIndex')
        if e.get('originIndex')!=0 or not isinstance(j,int) or j<0 or j>=len(targets) or j in vals:
            raise NearbyError('徒歩距離行列の応答番号が不正です。')
        if e.get('condition')=='ROUTE_EXISTS' and e.get('status',{}).get('code',0) in (None,0):
            d=e.get('distanceMeters')
            if not isinstance(d,(float,int)) or d<0:
                raise NearbyError('徒歩距離が取得できませんでした。')
            vals[j]=int(d)
        elif e.get('condition')=='ROUTE_NOT_FOUND':
            vals[j]=None
        else:
            raise NearbyError('一部の徒歩経路を取得できませんでした。自動で直線距離に切り替えません。')
    return vals

def walking_pairs(submitted, max_distance=500, environ=None, requester=None):
    """Return verified WALK distances for all candidate pairs within requested radius.

    The ceiling and billable-element budget prevent unbounded API requests.
    No unsuccessful or incomplete results are cached.
    """
    validate_shelters(submitted)
    if isinstance(max_distance,bool) or not isinstance(max_distance,int) or not 1<=max_distance<=2000:
        raise NearbyError('避難所間の距離は1〜2000mの整数にしてください。')
    env=environ if environ is not None else os.environ
    if str(env.get('GOOGLE_NEARBY_WALK_ENABLED','')).lower() not in ('1','true','yes'):
        raise NearbyError('徒歩距離APIは無効です。GOOGLE_NEARBY_WALK_ENABLED=true を設定してください。')
    key=str(env.get('GOOGLE_ROUTES_SERVER_API_KEY','')).strip()
    if not key:raise NearbyError('GOOGLE_ROUTES_SERVER_API_KEY が設定されていません。')
    try:budget=int(env.get('GOOGLE_NEARBY_MAX_ELEMENTS','0'))
    except ValueError:budget=0
    submitted_by_name={s['name']:s for s in submitted}
    coords=[submitted_by_name[s['name']] for s in eligible_master()]
    pairs=candidate_pairs(coords,max_distance=max_distance)
    if budget<len(pairs):
        raise NearbyError(f'徒歩距離の取得には{len(pairs)}要素が必要です。GOOGLE_NEARBY_MAX_ELEMENTS を{len(pairs)}以上に設定してください。')
    fingerprint=hashlib.sha256(json.dumps([(s['name'],s['lat'],s['lng']) for s in coords],ensure_ascii=False).encode()).hexdigest()
    with LOCK:
        # If a wider radius was already obtained, safely reuse its verified distances.
        eligible_cache=[(radius,rows) for (sig,radius),rows in CACHE.items() if sig==fingerprint and radius>=max_distance]
        if eligible_cache:
            radius,known=min(eligible_cache,key=lambda item:item[0])
            rows=[p for p in known if p['straightMeters']<=max_distance+0.05]
            if len(rows)==len(pairs):
                return {'pairs':rows,'candidateCount':len(pairs),'coverageMeters':max_distance,
                        'distanceMode':'google-walking','cached':True}
    by_origin={}
    for i,j,d in pairs:by_origin.setdefault(i,[]).append((j,d))
    output=[]
    def work(i,neighbors):
        targets=[coords[j] for j,_ in neighbors]
        distances=_request_for_origin(coords[i],targets,key,opener=requester)
        return [{'a':coords[i]['name'],'b':coords[j]['name'], 'straightMeters':direct,'walkingMeters':distances[n]}
                for n,(j,direct) in enumerate(neighbors)]
    # Restrict burst/concurrency. Endpoint must only run when user initiates request.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(work,i,neighbors) for i,neighbors in by_origin.items()]
        for f in as_completed(futures):output.extend(f.result())
    output.sort(key=lambda x:(x['walkingMeters'] is None,x['walkingMeters'] if x['walkingMeters'] is not None else float('inf'),x['a'],x['b']))
    with LOCK:CACHE[(fingerprint,max_distance)]=output
    return {'pairs':output,'candidateCount':len(pairs),'coverageMeters':max_distance,
            'distanceMode':'google-walking','cached':False}
