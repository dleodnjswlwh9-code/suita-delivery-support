"""Suita shelter straight-line pair grouping and road-snapped representative points.

Aerial distance is calculated using the haversine formula; this is NOT a travel
route length. Representatives require a Google Roads API match near 45%-55% of
one of the member-to-member chords. No unverified road point is silently used.
"""
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from nearby_shelters import NearbyError, validate_shelters, eligible_master, haversine_m

ROAD_URL='https://roads.googleapis.com/v1/nearestRoads'

def straight_pairs(submitted, maximum=300):
    validate_shelters(submitted)
    if type(maximum) is not int or not 1 <= maximum <= 2000:
        raise NearbyError('距離は1〜2000mの整数で指定してください。')
    lookup={s['name']:s for s in submitted}
    items=[lookup[s['name']] for s in eligible_master()]
    result=[]
    for i,a in enumerate(items):
        for b in items[i+1:]:
            d=haversine_m(a,b)
            if d<=maximum+1e-7:
                result.append({'a':a['name'],'b':b['name'],
                               'straightMeters':round(d,2)})
    result.sort(key=lambda p:(p['straightMeters'],p['a'],p['b']))
    return {'pairs':result,'candidateCount':len(result),
            'coverageMeters':maximum,'distanceMode':'straight-line','cached':False}

def road_representative(members,submitted,pair_data,environ=None,opener=None):
    validate_shelters(submitted)
    names=[str(x) for x in members]
    if len(names)<2 or len(names)!=len(set(names)):
        raise NearbyError('代表点の対象施設が不正です。')
    sites={s['name']:s for s in submitted}
    if any(n not in sites for n in names):raise NearbyError('対象避難所名を確認してください。')
    env=os.environ if environ is None else environ
    key=(env.get('GOOGLE_ROADS_SERVER_API_KEY') or env.get('GOOGLE_ROUTES_SERVER_API_KEY') or '').strip()
    if not key:raise NearbyError('道路上の代表点にはGOOGLE_ROADS_SERVER_API_KEYが必要です。')
    allowed=set(names)
    possible=[p for p in pair_data if p.get('a') in allowed and p.get('b') in allowed and isinstance(p.get('straightMeters'),(int,float))]
    if not possible:raise NearbyError('代表点を作るための直線距離がありません。')
    furthest=max(possible,key=lambda p:p['straightMeters'])
    a,b=(sites[furthest['a']],sites[furthest['b']])
    d=haversine_m(a,b)
    if d<1:raise NearbyError('2施設の座標が同じ場所にあります。位置データを確認してください。')
    # 45-55% of straight-line segment (not WALK). 0.5% resolution.
    samples=[(i/200.0,{'lat':a['lat']+(b['lat']-a['lat'])*(i/200.0),
                            'lng':a['lng']+(b['lng']-a['lng'])*(i/200.0)}) for i in range(90,111)]
    params=urllib.parse.urlencode({'points':'|'.join(f"{p['lat']:.7f},{p['lng']:.7f}" for _,p in samples),'key':key})
    req=urllib.request.Request(ROAD_URL+'?'+params)
    try:
        with (opener or urllib.request.urlopen)(req,timeout=25) as response:
            payload=json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        try:info=json.loads(e.read().decode()).get('error',{}).get('message','')
        except Exception:info=''
        raise NearbyError(f'Google Roads API ({e.code}): {info[:160]}') from e
    except Exception as e:raise NearbyError('Google Roads APIで道路位置を取得できません。') from e
    options=[]
    for s in payload.get('snappedPoints',[]):
        ix=s.get('originalIndex')
        if type(ix) is not int or not 0<=ix<len(samples):continue
        try:position={'lat':float(s['location']['latitude']),'lng':float(s['location']['longitude'])}
        except (KeyError,TypeError,ValueError):continue
        straight_point=samples[ix][1]
        offset=haversine_m(straight_point,position)
        da=haversine_m(position,a);db=haversine_m(position,b)
        fraction=da/(da+db) if da+db else 0
        # Do not snap >25m away to unrelated parallel streets, or away from the 45-55 split.
        if offset <= 25 and .45 <= fraction <= .55:
            options.append((abs(fraction-.5),offset,abs(samples[ix][0]-.5),position,da,db,fraction))
    if not options:raise NearbyError('中央45〜55%で近い道路を特定できません。施設の座標と道路を確認してください。')
    options.sort(key=lambda x:x[:3]);_,offset,_,point,dist_a,dist_b,ratio=options[0]
    per={n:round(haversine_m(point,sites[n]),1) for n in names}
    return {'lat':point['lat'],'lng':point['lng'],
            'sourcePair':[a['name'],b['name']], 'routeMeters':round(d,1),
            'geometryRatio':round(ratio,3),'roadConfirmed':True,
            'roadSnapOffsetMeters':round(offset,1),'memberDistances':per,
            'warning':'Google Roads道路形状上の暫定代表点（車両進入・荷卸し可能性は未検証）'}
