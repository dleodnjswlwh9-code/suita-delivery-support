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
