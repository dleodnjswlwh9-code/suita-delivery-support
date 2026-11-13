"""吹田市の避難所間の直線距離と代表点を計算する。

標準の代表点は構成施設の緯度・経度の算術平均である。
旧方式の道路上代表点計算は残しているが、現在の主要処理では使用しない。
重心が通行可能な道路上にあるとは限らない。"""
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from nearby_shelters import NearbyError, validate_shelters, eligible_master, haversine_m

ROAD_URL='https://roads.googleapis.com/v1/nearestRoads'
REPRESENTATIVE_METHOD='road-minimax-v72'


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
    # 明示的に設定したRoads用APIキーだけを使用する。他のキーへの自動切替によるプロジェクト不一致を防ぐ。
    key=str(env.get('GOOGLE_ROADS_SERVER_API_KEY') or '').strip()
    if not key:
        raise NearbyError('GOOGLE_ROADS_SERVER_API_KEY が未設定です。既存のGoogle APIキーをこの環境変数に設定してください。GOOGLE_ROUTES_SERVER_API_KEYには自動切替しません。')
    if key.startswith(('\"', "'")) or key.endswith(('\"', "'")):
        raise NearbyError('GOOGLE_ROADS_SERVER_API_KEY の値に引用符が含まれています。Renderには引用符なしで入力してください。')
    allowed=set(names)
    possible=[p for p in pair_data if p.get('a') in allowed and p.get('b') in allowed and isinstance(p.get('straightMeters'),(int,float))]
    if not possible:raise NearbyError('代表点を作るための直線距離がありません。')
    furthest=max(possible,key=lambda p:p['straightMeters'])
    a,b=(sites[furthest['a']],sites[furthest['b']])
    d=haversine_m(a,b)
    if d<1:raise NearbyError('2施設の座標が同じ場所にあります。位置データを確認してください。')
    # Googleの道路最近傍取得は1回100地点まで。両施設間の全区間と平行道路の候補を調べ、中点に道路があると仮定しない。
    lat_scale=111320.0
    lng_scale=lat_scale*max(0.01,math.cos(math.radians((a['lat']+b['lat'])/2)))
    dx=(b['lng']-a['lng'])*lng_scale
    dy=(b['lat']-a['lat'])*lat_scale
    chord=math.hypot(dx,dy)
    nx=-dy/chord; ny=dx/chord  # 局所座標での垂直方向の単位ベクトル。
    samples=[]
    def add_sample(frac, side_m=0):
        samples.append((frac,{'lat':a['lat']+(b['lat']-a['lat'])*frac+ny*side_m/lat_scale,
                              'lng':a['lng']+(b['lng']-a['lng'])*frac+nx*side_m/lng_scale}))
    for i in range(41): add_sample(i/40)                 # 始点から終点まで2.5%刻みで調べる。
    for i in range(1,10):
        for side in (-40.0,40.0,-90.0,90.0): add_sample(i/10,side)
    for i in range(2,9):
        for side in (-160.0,160.0): add_sample(i/10,side)
    # 合計91地点を1回の有料要求で調べる。
    params=urllib.parse.urlencode({'points':'|'.join(f"{p['lat']:.7f},{p['lng']:.7f}" for _,p in samples),'key':key})
    req=urllib.request.Request(ROAD_URL+'?'+params)
    try:
        with (opener or urllib.request.urlopen)(req,timeout=25) as response:
            payload=json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        try:
            info=str(json.loads(e.read().decode()).get('error',{}).get('message',''))
        except Exception:
            info=''
        # APIのエラーには実際に使用されたプロジェクトの情報が含まれる場合がある。APIキー自体は表示・記録しない。
        info=re.sub(r'AIza[0-9A-Za-z_\-]+','[APIキー非表示]',info)
        project_match=re.search(r'\bproject\s+(\d{8,20})\b',info,re.I)
        if e.code in (401,403):
            if project_match:
                detail=(f'使用中の GOOGLE_ROADS_SERVER_API_KEY は Google Cloud プロジェクト番号 '
                        f'{project_match.group(1)} として拒否されました。'
                        'Roads API を有効にしたプロジェクトのキーと一致するか確認してください。')
            else:
                detail='GOOGLE_ROADS_SERVER_API_KEY のAPI制限・アプリケーション制限・課金状態を確認してください。'
            raise NearbyError(f'Google道路APIのエラー（{e.code}）：{detail} 詳細：{info[:220]}') from e
        raise NearbyError(f'Google道路APIのエラー（{e.code}）：{info[:240]}') from e
    except Exception as e:raise NearbyError('Google Roads APIで道路位置を取得できません。') from e
    options=[]
    for s in payload.get('snappedPoints',[]):
        ix=s.get('originalIndex')
        if type(ix) is not int or not 0<=ix<len(samples):continue
        try:position={'lat':float(s['location']['latitude']),'lng':float(s['location']['longitude'])}
        except (KeyError,TypeError,ValueError):continue
        if not (math.isfinite(position['lat']) and math.isfinite(position['lng'])):continue
        if not (-90 <= position['lat'] <= 90 and -180 <= position['lng'] <= 180):continue
        relative_x=(position['lng']-a['lng'])*lng_scale
        relative_y=(position['lat']-a['lat'])*lat_scale
        projection=max(0.0,min(1.0,(relative_x*dx+relative_y*dy)/(chord*chord)))
        # 道路上の候補点と施設間線分の最短距離を評価する。並行する近傍道路は許容するが、離れすぎた道路は除く。
        corridor_offset=math.hypot(relative_x-projection*dx,relative_y-projection*dy)
        if corridor_offset>300:continue
        distances=[haversine_m(position,sites[n]) for n in names]
        da=haversine_m(position,a);db=haversine_m(position,b)
        fraction=da/(da+db) if da+db else .5
        # 最大アクセス距離を優先し、同点では総距離・中心線からの距離・位置の均衡で比較する。
        score=(max(distances),sum(distances),corridor_offset,abs(fraction-.5))
        options.append((score,position,distances,da,db,fraction,corridor_offset,projection))
    if not options:
        raise NearbyError('近くの道路上に代表点候補が見つかりません。施設座標またはRoads APIの応答を確認してください。')
    options.sort(key=lambda x:x[0])
    _,point,distances,dist_a,dist_b,ratio,offset,projection=options[0]
    per={n:round(m,1) for n,m in zip(names,distances)}
    a_pct=round(100*ratio)
    b_pct=100-a_pct
    far_road_warning=('（直線区間から離れた道路のため現地確認推奨）' if offset>120 else '')

    return {'lat':point['lat'],'lng':point['lng'],
            'sourcePair':[a['name'],b['name']], 'routeMeters':round(d,1),
            'geometryRatio':round(ratio,4),'ratioLabel':f'{a_pct}:{b_pct}',
            'representativeMethod':REPRESENTATIVE_METHOD,
            'roadConfirmed':True,'roadSnapOffsetMeters':round(offset,1),
            'chordPositionPercent':round(100*projection,1),
            'memberDistances':per,
            'warning':'道路上の候補点（各施設までの直線距離で比較・車両進入と荷卸しは要確認）'+far_road_warning}


def centroid_representative(members, submitted, pair_data, environ=None, opener=None):
    """v76の代表点：構成施設の緯度・経度の算術平均。
    
    道路への吸着を確認した点ではなく、仮想的な配送地点である。
    2施設なら中点、3施設以上なら座標の重心を使用する。"""
    validate_shelters(submitted)
    names=[str(x) for x in members]
    if len(names)<2 or len(names)!=len(set(names)):
        raise NearbyError('代表点の対象施設が不正です。')
    sites={s['name']:s for s in submitted}
    if any(n not in sites for n in names):
        raise NearbyError('対象避難所名を確認してください。')
    point={'lat':sum(float(sites[n]['lat']) for n in names)/len(names),
           'lng':sum(float(sites[n]['lng']) for n in names)/len(names)}
    distances={n:round(haversine_m(point,sites[n]),1) for n in names}
    pairs=[(haversine_m(sites[a],sites[b]),a,b) for i,a in enumerate(names) for b in names[i+1:]]
    maxdist,a,b=max(pairs)
    return {'lat':point['lat'],'lng':point['lng'],
            'sourcePair':[a,b],'routeMeters':round(maxdist,1),
            'geometryRatio':0.5 if len(names)==2 else None,
            'ratioLabel':'50:50' if len(names)==2 else '座標の平均',
            'representativeMethod':'geometric-centroid-v76',
            'roadConfirmed':False,'roadSnapOffsetMeters':None,
            'memberDistances':distances,
            'warning':'仮想代表点：道路への接続・停車・荷卸しの可否は未確認です。'}
