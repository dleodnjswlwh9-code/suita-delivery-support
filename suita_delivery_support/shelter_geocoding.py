"""Suita master-name-only Google Places lookup and real Google WALK route polyline."""
from __future__ import annotations
import json, os, math, urllib.request, urllib.error
from nearby_shelters import eligible_master, haversine_m, NearbyError

class PlaceLookupError(ValueError): pass

def _post(url, body, key, fields, opener=None):
    req=urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',headers={
        'Content-Type':'application/json','X-Goog-Api-Key':key,'X-Goog-FieldMask':fields})
    try:
        with (opener or urllib.request.urlopen)(req,timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try: message=json.loads(e.read().decode('utf-8')).get('error',{}).get('message','')
        except Exception: message=''
        raise PlaceLookupError(f'Google APIエラー ({e.code}): {message[:150]}') from e
    except Exception as e: raise PlaceLookupError('Google APIへの接続に失敗しました。') from e

def search_master_place(name,environ=None,opener=None):
    env=environ if environ is not None else os.environ
    names={s['name']:s for s in eligible_master()}
    if not isinstance(name,str) or name not in names: raise PlaceLookupError('登録済みの対象避難所を選択してください。')
    if str(env.get('GOOGLE_PLACES_SEARCH_ENABLED','')).lower() not in ('true','1','yes'):
        raise PlaceLookupError('Places APIは無効です。GOOGLE_PLACES_SEARCH_ENABLED=true を設定してください。')
    key=str(env.get('GOOGLE_PLACES_SERVER_API_KEY','')).strip()
    if not key: raise PlaceLookupError('GOOGLE_PLACES_SERVER_API_KEY が設定されていません。')
    source=names[name]
    body={'textQuery':f'{name} 大阪府吹田市','languageCode':'ja','regionCode':'JP',
          'pageSize':5,'locationBias':{'circle':{'center':{'latitude':source['lat'],'longitude':source['lng']},'radius':1300.0}}}
    result=_post('https://places.googleapis.com/v1/places:searchText',body,key,
                 'places.id,places.displayName,places.formattedAddress,places.location',opener)
    choices=[]
    for v in result.get('places',[]):
        loc=v.get('location',{})
        try: lat=float(loc['latitude']);lng=float(loc['longitude'])
        except (KeyError,ValueError,TypeError):continue
        if not math.isfinite(lat) or not math.isfinite(lng):continue
        distance=round(haversine_m(source,{'lat':lat,'lng':lng}))
        if distance>2000: continue
        choices.append({'placeId':str(v.get('id','')),'name':str(v.get('displayName',{}).get('text','')),
                        'address':str(v.get('formattedAddress','')),'lat':lat,'lng':lng,'offsetMeters':distance})
    return {'shelter':name,'choices':choices}

def walk_route_geometry(a,b,submitted, environ=None, opener=None):
    env=environ if environ is not None else os.environ
    from nearby_shelters import validate_shelters
    validate_shelters(submitted)
    sites={s['name']:s for s in submitted}
    if a not in sites or b not in sites or a==b: raise PlaceLookupError('対象避難所名が不正です。')
    if str(env.get('GOOGLE_NEARBY_WALK_ENABLED','')).lower() not in ('true','1','yes'):
        raise PlaceLookupError('GOOGLE_NEARBY_WALK_ENABLED=true を設定してください。')
    key=str(env.get('GOOGLE_ROUTES_SERVER_API_KEY','')).strip()
    if not key: raise PlaceLookupError('GOOGLE_ROUTES_SERVER_API_KEY が設定されていません。')
    if haversine_m(sites[a],sites[b])>2000.1: raise PlaceLookupError('2km以上の組合せは表示できません。')
    def loc(x):return {'location':{'latLng':{'latitude':float(x['lat']),'longitude':float(x['lng'])}}}
    body={'origin':loc(sites[a]),'destination':loc(sites[b]),'travelMode':'WALK',
          'polylineQuality':'HIGH_QUALITY','languageCode':'ja','units':'METRIC'}
    result=_post('https://routes.googleapis.com/directions/v2:computeRoutes',body,key,
                 'routes.distanceMeters,routes.polyline.encodedPolyline',opener)
    best=next(iter(result.get('routes',[])),{})
    encoded=best.get('polyline',{}).get('encodedPolyline')
    if not isinstance(encoded,str) or not encoded: raise PlaceLookupError('Google徒歩経路の線形を取得できませんでした。')
    return {'a':a,'b':b,'walkingMeters':best.get('distanceMeters'),'encodedPolyline':encoded,'mode':'WALK'}

# v58: automatic name-based location lookup with per-process cache.
import threading
from concurrent.futures import ThreadPoolExecutor,as_completed
_AUTO_PLACES_CACHE={}
_AUTO_PLACES_LOCK=threading.RLock()

def _canonical_name(s):
    import re,unicodedata
    text=unicodedata.normalize('NFKC',str(s or ''))
    text=re.sub(r'^(大阪府)?吹田市立|^(大阪府)?吹田市', '',text)
    return re.sub(r'[\s\u3000・（）()]','',text)

def auto_resolve_places(environ=None,opener=None,offset=0,limit=8):
    """Match master 100 by precise facility name (do not silently trust ambiguous POIs)."""
    env=environ if environ is not None else os.environ
    if str(env.get('GOOGLE_PLACES_SEARCH_ENABLED','')).lower() not in ('true','1','yes'):
        raise PlaceLookupError('GOOGLE_PLACES_SEARCH_ENABLED=true を設定してください。')
    master=eligible_master()
    if type(offset) is not int or not 0<=offset<len(master) or type(limit) is not int or not 1<=limit<=8:
        raise PlaceLookupError('施設名の照会範囲が不正です。')
    page=master[offset:offset+limit]
    verified=[]
    def worker(item):
        name=item['name']
        with _AUTO_PLACES_LOCK:
            if name in _AUTO_PLACES_CACHE:return dict(_AUTO_PLACES_CACHE[name])
        try:
            response=search_master_place(name,environ=env,opener=opener)
            matches=[c for c in response.get('choices',[]) if _canonical_name(c['name'])==_canonical_name(name)
                    and 0<=c['offsetMeters']<=2000 and ('吹田市' in c['address'] or 'Suita' in c['address'])]
            if len(matches)==1:
                c=matches[0]
                out={'name':name,'lat':c['lat'],'lng':c['lng'],'placeId':c['placeId'],
                     'placeName':c['name'],'address':c['address'],'status':'google-verified'}
            else:out={'name':name,'status':'unverified','reason':'名前の一致がないか、候補が複数あります。'}
        except PlaceLookupError as e:out={'name':name,'status':'unverified','reason':str(e)[:150]}
        with _AUTO_PLACES_LOCK:_AUTO_PLACES_CACHE[name]=dict(out)
        return out
    with ThreadPoolExecutor(max_workers=3) as pool:
        future=[pool.submit(worker,m) for m in page]
        for task in as_completed(future):verified.append(task.result())
    verified.sort(key=lambda x:x['name'])
    return {'results':verified,'verified':sum(x['status']=='google-verified' for x in verified),
            'unverified':sum(x['status']!='google-verified' for x in verified),
            'masterCount':len(master),'offset':offset,'limit':len(page)}
