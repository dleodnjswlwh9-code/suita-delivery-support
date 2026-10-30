"""Google WALK geometry and candidate representative road placement.

Google route alternatives are not a global mathematical shortest-path certificate.
No arbitrary straight-line fallback. Road geometry is Roads API based when enabled.
"""
from __future__ import annotations
import json, math, os, threading, urllib.parse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from nearby_shelters import NearbyError, eligible_master, validate_shelters, haversine_m, candidate_pairs

ROUTES_URL='https://routes.googleapis.com/directions/v2:computeRoutes'
ROAD_URL='https://roads.googleapis.com/v1/nearestRoads'
ROUTE_CACHE={}
LOCK=threading.RLock()


def decode_polyline(s):
    pts=[];i=lat=lng=0
    while i<len(s):
        diffs=[]
        for _ in range(2):
            value=shift=0
            while True:
                if i>=len(s):raise NearbyError('Google経路の座標データが不完全です。')
                byte=ord(s[i])-63;i+=1
                value|=(byte&31)<<shift;shift+=5
                if byte<32:break
            diffs.append(~(value>>1) if value&1 else value>>1)
        lat+=diffs[0];lng+=diffs[1]
        pts.append({'lat':lat/1e5,'lng':lng/1e5})
    return pts


def _post(body,key,opener=None):
    req=urllib.request.Request(ROUTES_URL,data=json.dumps(body).encode(),method='POST',headers={
        'Content-Type':'application/json','X-Goog-Api-Key':key,'X-Goog-FieldMask':'routes.distanceMeters,routes.polyline.encodedPolyline'})
    try:
        with (opener or urllib.request.urlopen)(req,timeout=35) as rsp:return json.loads(rsp.read().decode())
    except urllib.error.HTTPError as exc:
        try:msg=json.loads(exc.read().decode()).get('error',{}).get('message','')
        except Exception:msg=''
        raise NearbyError(f'Google Routes API ({exc.code}): {msg[:130]}') from exc
    except Exception as exc:raise NearbyError('Google徒歩経路の取得に失敗しました。') from exc


def google_short_walk(a,b,key,opener=None):
    """Shortest *returned Google candidate* WALK path, not proven global shortest."""
    fingerprint=tuple(round(float(x[k]),7) for x in (a,b) for k in ('lat','lng'))
    with LOCK:
        if fingerprint in ROUTE_CACHE:return dict(ROUTE_CACHE[fingerprint])
    def wp(p):return {'location':{'latLng':{'latitude':float(p['lat']),'longitude':float(p['lng'])}}}
    body={'origin':wp(a),'destination':wp(b),'travelMode':'WALK','computeAlternativeRoutes':True,
          'polylineQuality':'HIGH_QUALITY','languageCode':'ja','units':'METRIC'}
    try:
        result=_post(body,key,opener)
    except NearbyError as exc:
        # Some regions or travel modes may not support alternate WALK routes.
        # If that is the only problem, use the single Google WALK route.
        message=str(exc).lower()
        if 'alternative' not in message and 'alternateroutes' not in message:
            raise
        body['computeAlternativeRoutes']=False
        result=_post(body,key,opener)
    possible=[]
    for route in result.get('routes',[]):
        encoded=route.get('polyline',{}).get('encodedPolyline')
        dist=route.get('distanceMeters')
        if isinstance(encoded,str) and encoded and isinstance(dist,(float,int)) and dist>=0:
            possible.append({'walkingMeters':round(dist),'encodedPolyline':encoded})
    if not possible: return None
    shortest=min(possible,key=lambda item:item['walkingMeters'])
    shortest['alternateCount']=len(possible)
    with LOCK:ROUTE_CACHE[fingerprint]=shortest
    return dict(shortest)


def name_resolved_pair_routes(submitted,maximum=300,environ=None,opener=None):
    validate_shelters(submitted)
    if type(maximum) is not int or not 1<=maximum<=2000:raise NearbyError('距離は1〜2000mの整数で指定してください。')
    env=environ or os.environ
    if str(env.get('GOOGLE_NEARBY_WALK_ENABLED','')).lower() not in ('1','yes','true'):
        raise NearbyError('GOOGLE_NEARBY_WALK_ENABLED=true を設定してください。')
    key=str(env.get('GOOGLE_ROUTES_SERVER_API_KEY','')).strip()
    if not key:raise NearbyError('GOOGLE_ROUTES_SERVER_API_KEY が設定されていません。')
    lookup={s['name']:s for s in submitted}
    coords=[lookup[s['name']] for s in eligible_master()]
    candidates=candidate_pairs(coords,maximum)
    try:budget=int(env.get('GOOGLE_NEARBY_MAX_ELEMENTS','0'))
    except ValueError:budget=0
    if len(candidates)>budget:
        raise NearbyError(f'最短徒歩経路取得には{len(candidates)}件の呼び出しが必要です。GOOGLE_NEARBY_MAX_ELEMENTS を{len(candidates)}以上に設定してください。')
    output=[]
    def run(triple):
        i,j,d=triple
        route=google_short_walk(coords[i],coords[j],key,opener)
        return {'a':coords[i]['name'],'b':coords[j]['name'],'straightMeters':d,
                'walkingMeters':route['walkingMeters'] if route else None,
                'encodedPolyline':route['encodedPolyline'] if route else None,
                'alternatesChecked':route['alternateCount'] if route else 0}
    with ThreadPoolExecutor(max_workers=3) as pool:
        future=[pool.submit(run,p) for p in candidates]
        for task in as_completed(future):output.append(task.result())
    output.sort(key=lambda x:(x['walkingMeters'] is None,x['walkingMeters'] or 1e30,x['a'],x['b']))
    return {'pairs':output,'candidateCount':len(candidates),'coverageMeters':maximum,
            'distanceMode':'google-walking-shortest-returned','cached':False}


def _lengths(points):
    cumulative=[0.0]
    for i in range(1,len(points)):
        cumulative.append(cumulative[-1]+haversine_m(points[i-1],points[i]))
    return cumulative


def along(points,cumulative,fraction):
    target=cumulative[-1]*fraction
    for i in range(1,len(cumulative)):
        if cumulative[i]>=target:
            seg=cumulative[i]-cumulative[i-1]
            ratio=(target-cumulative[i-1])/seg if seg else 0
            return {'lat':points[i-1]['lat']+(points[i]['lat']-points[i-1]['lat'])*ratio,
                    'lng':points[i-1]['lng']+(points[i]['lng']-points[i-1]['lng'])*ratio}
    return dict(points[-1])


def _nearest_roads(pts,key,opener=None):
    query=urllib.parse.urlencode({'points':'|'.join(f"{p['lat']:.7f},{p['lng']:.7f}" for p in pts),'key':key})
    req=urllib.request.Request(ROAD_URL+'?'+query)
    try:
        with (opener or urllib.request.urlopen)(req,timeout=25) as response:
            return json.loads(response.read().decode()).get('snappedPoints',[])
    except Exception:return []


def representative_for_group(members,submitted,pair_data,environ=None,route_opener=None,road_opener=None):
    """Pick central position along furthest pair's Google path; check road within 45-55%.
    Distance A -> rep and rep -> B are REQUERIED, not asserted by geometry fractions.
    """
    validate_shelters(submitted)
    names=[str(x) for x in members]
    if not 2<=len(names)<=100 or len(names)!=len(set(names)):raise NearbyError('代表点の対象施設が不正です。')
    sites={s['name']:s for s in submitted}
    if any(n not in sites for n in names):raise NearbyError('対象避難所名を確認してください。')
    env=environ or os.environ
    key=str(env.get('GOOGLE_ROUTES_SERVER_API_KEY','')).strip()
    if not key:raise NearbyError('GOOGLE_ROUTES_SERVER_API_KEY がありません。')
    allowed=set(names);available=[]
    for x in pair_data:
        if x.get('a') in allowed and x.get('b') in allowed and isinstance(x.get('walkingMeters'),(int,float)):
            available.append(x)
    if not available:raise NearbyError('このグループの徒歩経路を取得してください。')
    longest=max(available,key=lambda x:x['walkingMeters'])
    a,b=longest['a'],longest['b']
    route=google_short_walk(sites[a],sites[b],key,route_opener)
    if not route:raise NearbyError('代表点の徒歩経路を取得できませんでした。')
    points=decode_polyline(route['encodedPolyline'])
    if not points:raise NearbyError('徒歩経路の座標がありません。')
    if len(points)==1:points.append(dict(points[0]))
    cumulative=_lengths(points)
    candidates=[(round(f/100,3),along(points,cumulative,f/100)) for f in range(45,56)]
    roadkey=str(env.get('GOOGLE_ROADS_SERVER_API_KEY') or key).strip()
    road_ok=False;point=candidates[5][1];ratio=0.5
    if str(env.get('GOOGLE_REPRESENTATIVE_ROADS_ENABLED','true')).lower() in ('true','1','yes') and roadkey:
        response=_nearest_roads([c[1] for c in candidates],roadkey,road_opener)
        fits=[]
        for snap in response:
            i=snap.get('originalIndex')
            loc=snap.get('location',{})
            if not isinstance(i,int) or not 0<=i<len(candidates):continue
            try:road={'lat':float(loc['latitude']),'lng':float(loc['longitude'])}
            except (KeyError,ValueError,TypeError):continue
            offset=haversine_m(road,candidates[i][1])
            if offset<=10:fits.append((abs(candidates[i][0]-.5),offset,i,road))
        fits.sort(key=lambda x:(x[0],x[1]))
        if fits:
            _,_,i,point=fits[0];ratio=candidates[i][0];road_ok=True
    # Google WALK distance to final point, because road snap can change both legs.
    per_member={};verified=True
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks={pool.submit(google_short_walk,point,sites[n],key,route_opener):n for n in names}
        for t in as_completed(tasks):
            n=tasks[t];r=t.result()
            if r is None:verified=False
            else:per_member[n]=r['walkingMeters']
    if not verified:raise NearbyError('代表点から避難所への徒歩距離が取得できませんでした。')
    # Accept road snap only when WALK shortest routes still within requested 45-55 split.
    if road_ok:
        d1=per_member.get(a,0);d2=per_member.get(b,0)
        if not d1+d2 or not .45<=d1/(d1+d2)<=.55:
            # Fall back to point along WALK geometry, no claim of drivable road.
            point=candidates[5][1];ratio=.5;road_ok=False
            with ThreadPoolExecutor(max_workers=3) as pool:
                tasks={pool.submit(google_short_walk,point,sites[n],key,route_opener):n for n in names}
                per_member={t_to:res['walkingMeters'] for t,t_to in tasks.items() if (res:=t.result()) is not None}
            if len(per_member)!=len(names):raise NearbyError('徒歩距離が取得できませんでした。')
    return {'lat':point['lat'],'lng':point['lng'],'sourcePair':[a,b],
            'routeMeters':route['walkingMeters'],'geometryRatio':ratio,
            'roadConfirmed':road_ok,'memberDistances':per_member,
            'encodedPolyline':route['encodedPolyline'],
            'warning':('Google Roads上の道路形状に近接（車両アクセスは未確認）' if road_ok
                       else '徒歩経路上の中点・車両通行可能な道路か未確認')}
