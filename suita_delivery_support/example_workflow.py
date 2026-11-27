"""Transport example input/output adapter for the SAME Suita planning engine.

No optimization or saved result data in this module. The example's box is
one integer quantity unit; the real Suita quantity unit remains 人日分.
"""
from __future__ import annotations
import copy
import math
import kit_planning
import p2_kit_optimizer
import rolling_actual

# Input presets only, from rev27_example.m and the manual §12.
PRESETS={
    'six':dict(xy=[(2,1),(5,1),(1,4),(6,4),(2,7),(7,7)],d=[30,20,10,10,10,10],g=[1]*6,stock=40,cap=10),
    'four':dict(xy=[(1,2),(4,1),(2,5),(5,4)],d=[20,10,10,10],g=[1,1.5,1,.5],stock=18,cap=6),
}


def defaults(mode='six'):
    m=PRESETS[mode]
    return dict(mode=mode,unit='箱',target=.5,delta=0.,rounds=3,round=1,minVisit=1,
        hubs=[dict(name='拠点',stock=m['stock'],vehicles=[dict(capacity=m['cap'],count=2)])],
        shelters=[dict(id=i+1,name=f'避難所{i+1}',x=x,y=y,demand=m['d'][i],received=0,visited=False,gamma=m['g'][i]) for i,(x,y) in enumerate(m['xy'])],history=[])


def num(x,name,lo,hi,integer=False):
    try:
        if isinstance(x,bool):raise ValueError()
        v=float(x)
    except (ValueError,TypeError,OverflowError):raise ValueError(name+'：数値を入力してください。')
    if not math.isfinite(v) or not lo<=v<=hi or (integer and v!=int(v)):
        raise ValueError(f'{name}：{lo}～{hi}の'+('整数' if integer else '数値')+'を入力してください。')
    return int(v) if integer else v


def config(data,previous=None):
    mode=data.get('mode','six')
    if mode not in PRESETS:raise ValueError('例題を選択してください。')
    s=copy.deepcopy(previous) if previous is not None else defaults(mode)
    if s['mode']!=mode:raise ValueError('例題を変更する場合は初期化してください。')
    if s['rounds']<1:raise ValueError('配送回数の上限に達しました。')
    s['target']=num(data.get('target',s['target']),'目標配分率',.5,.9)
    if not any(abs(s['target']-a)<1e-9 for a in kit_planning.ALLOWED_A):raise ValueError('吹田市と同じ目標配分率の選択肢を使用してください。')
    s['delta']=num(data.get('delta',s['delta']),'配分評価許容幅',0,2)
    if previous is None:
        s['hubs'][0]['stock']=num(data.get('stock',s['hubs'][0]['stock']),'在庫',0,1000,True)
        s['rounds']=num(data.get('rounds',3),'最大配送回数',1,3,True)
        s['hubs'][0]['vehicles'][0]['capacity']=num(data.get('capacity',s['hubs'][0]['vehicles'][0]['capacity']),'車両容量',1,20,True)
        s['minVisit']=num(data.get('minVisit',1),'最小配送量',1,20,True)
    d=data.get('demand',[r['demand'] for r in s['shelters']]);g=data.get('gamma',[r['gamma'] for r in s['shelters']])
    if not isinstance(d,list) or not isinstance(g,list) or len(d)!=len(s['shelters']) or len(g)!=len(d):raise ValueError('避難所の入力数を確認してください。')
    for r,v,w in zip(s['shelters'],d,g):
        r['demand']=num(v,'需要',1,1000,True);r['gamma']=num(w,'緊急度',.001,100)
        if r['received']>r['demand']:raise ValueError('需要は供給済量以上を入力してください。')
    return s


def shared_input(s):
    """Adapt input ONLY. Hub index 1 is an inactive slot in the existing
    two-hub interface; there is physically one virtual depot and two trucks.
    Synthetic lat/lng fields satisfy the shared input schema; the route
    matrix always comes from the input grid, never the city coordinates.
    """
    stock=s['hubs'][0]['stock'];cap=s['hubs'][0]['vehicles'][0]['capacity']
    payload=dict(targetRate=s['target'],rho=.0001,totalKits=stock,truckCount=2,
        maxRounds=s['rounds'],minKits=s['minVisit'],
        vehicles=[dict(capacityKg=2000,count=2)],
        hubStockKits=[stock,0],vehicleHubCounts=[{'2t':2,'4t':0},{'2t':0,'4t':0}],loadingParallel=[2,1],
        p2DeltaF1=s['delta'],p0TimeLimitSec=20,p0MipGapPercent=.1,
        shelters=[dict(name=r['name'],lat=34.78+r['y']*.001,lng=135.53+r['x']*.001,
            demandKits=r['demand'],stockKits=r['received'],visited=r['visited'],urgency=r['gamma']) for r in s['shelters']])
    clean=kit_planning.clean_input(payload,example_capacity=cap)
    # Two identical coordinate rows only for the inactive second slot.
    xy=[(0,0),(0,0)]+[(r['x'],r['y']) for r in s['shelters']]
    matrix=p2_kit_optimizer.TravelMatrix([[2*(abs(x-a)+abs(y-b)) for a,b in xy] for x,y in xy],loading=5,prep=0,unloading=.5)
    return payload,clean,matrix


def solve(s,*,return_raw=False):
    """Use exactly the city's P1 LP, P0/P0′ MILP and P2 route search."""
    payload,clean,matrix=shared_input(s)
    ideal=kit_planning.solve_p1(clean)
    raw=p2_kit_optimizer.optimize_p2_kit(payload,driving_matrix=matrix,
        matrix_source='example-grid',matrix_note='仮想格子：縦横1区画2分',clean=clean)
    p0=raw['p0'];prime=raw['p0Prime'];front=[]
    for q in raw['p2Alternatives']:
        routes=[];cov=[];cumulative=[r['received'] for r in s['shelters']]
        for route in q['routes']:
            stops=[dict(id=t['index']+1,name=t['name'],qty=t['kits']) for t in route['stops']]
            routes.append(dict(round=route['round']+s['round']-1,truck=route['truck'],total=route['kits'],minutes=route['timeMin'],stops=stops))
        for i in range(s['rounds']):
            for rt in routes:
                if rt['round']==s['round']+i:
                    for stop in rt['stops']:cumulative[stop['id']-1]+=stop['qty']
            cov.append([v/r['demand'] for v,r in zip(cumulative,s['shelters'])])
        front.append(dict(id=q['candidateId'],f1=q['f1Route'],f2=q['f2Minutes'],f3=q['f3'],total=q['deliveredKits'],
            allocation=[r['deliveredKits'] for r in q['shelters']],routes=routes,coverage=cov,roundTimes=q['roundTimesMinutes']))
    result=dict(shelters=copy.deepcopy(s['shelters']),round=s['round'],remainingRounds=s['rounds'],keep=True,
        p1=dict(f1=ideal['f1'],allocation=ideal['allocations']),
        p0=dict(f1=p0['f1Feasible'],allocation=p0['plannedAdditions'],etaUpper=p0['etaUpperBound'],certified=bool(p0['certified'])),
        prime=dict(total=prime['totalKits'],allocation=prime['plannedAdditions'],certified=prime['maxCertifiedReduced']),
        cap=p0['f1Feasible']+s['delta'],front=front,recommended=raw['recommendedId'],
        method='吹田市と共通の配分・配送計算（探索候補内の比較）')
    return (result,raw) if return_raw else result


def advance(state,result,body,raw):
    """Use shared actual-delivery validation, then adapt the next input."""
    s=copy.deepcopy(state);now=s['round'];pid=num(body['id'],'計画ID',1,1000,True)
    plan=next((q for q in result['front'] if q['id']==pid),None)
    candidate=next((q for q in raw['p2Alternatives'] if q['candidateId']==pid),None)
    if plan is None or candidate is None:raise ValueError('配送計画を選択してください。')
    allowed={str(t['id']):t['qty'] for route in plan['routes'] if route['round']==now for t in route['stops']}
    actual=body.get('actual',{})
    if not isinstance(actual,dict) or set(actual)!=set(allowed):raise ValueError('今回の配送実績を確認してください。')
    q={k:num(v,'実配送量',0,allowed[k],True) for k,v in actual.items()}
    supp=num(body.get('replenishment',0),'追加補給量',0,1000,True)
    minutes=num(body.get('minutes',plan['roundTimes'][0]),'実所要時間',0,10000)
    try:
        confirmed=rolling_actual.confirm_round(candidate,1,[q.get(str(r['id']),0) for r in s['shelters']],minutes)
    except rolling_actual.ActualDeliveryError as e:
        raise ValueError(str(e).replace('人日分','箱').replace('北南部','拠点')) from e
    for r,u in zip(s['shelters'],confirmed['shelters']):
        r['received']=u['stockAfterKits'];r['visited']=r['visited'] or u['visited']
    s['hubs'][0]['stock']=confirmed['remainingTotalKits']+supp
    s['history'].append(dict(round=now,id=pid,planned=sum(allowed.values()),actual=confirmed['actualKits'],replenishment=supp,stock=s['hubs'][0]['stock'],minutes=confirmed['usedMinutes']))
    s['round']+=1;s['rounds']=confirmed['remainingRounds']
    return s
