"""Research-stage one-person-day relief kit model.

One kit = three retort meals + six 500-ml water bottles. Stock conversion
uses COMPLETE kits only. Spare component stock is reported, not consumed.
P1 is continuous LP; P2 rounds to integer kits and returns a disclosed
heuristic, *not* a certified optimum or P0-equivalent solution.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from scipy.optimize import linprog

KIT_KG = 4.5  # 3*0.5kg + 6*0.5kg: research assumption, packaging excluded
TRUCK_CAP_KITS = math.floor(2000.0 / KIT_KG)
LOADING_MIN = 30.0       # research scenario, not a measured 2t truck standard
PREP_MIN = 15.0          # shelter visit: Yagi precedent
UNLOADING_MIN_PER_KIT = 120.0 / 3000.0  # sensitivity assumption
ROAD_SPEED_KMH = 20.0    # city-block distance approximation, NOT road-network ETA
ALLOWED_A = (0.7, 0.8, 0.9)

class KitInputError(ValueError):
    pass


def stock_to_kits(stock):
    rice = max(0, int(float((stock or {}).get('retortRice', 0) or 0)))
    water = max(0, int(float((stock or {}).get('water500ml', 0) or 0)))
    kits = min(rice // 3, water // 6)
    return kits, rice - 3 * kits, water - 6 * kits


def clean_input(data):
    if not isinstance(data, dict):
        raise KitInputError('入力が不正です。')
    try:
        a = float(data['targetRate'])
        rho = float(data.get('rho', 0.005))
        available = int(float(data['totalKits']))
        trucks = int(data['truckCount'])
        rounds = int(data['maxRounds'])
        delta = int(data.get('minKits', 1))
    except (TypeError, ValueError, KeyError, OverflowError):
        raise KitInputError('希求水準・物資量・車両台数・配送回数を確認してください。')
    if not any(abs(a-x)<1e-9 for x in ALLOWED_A) or not 0 < rho <= 1 or available < 0 or not 1<=trucks<=50 or not 1<=rounds<=50 or not 1<=delta<=TRUCK_CAP_KITS:
        raise KitInputError('希求水準70/80/90％、物資量、車両数、配送回数、最小配送量を確認してください。')
    shelters = data.get('shelters')
    if not isinstance(shelters, list) or not 1<=len(shelters)<=200:
        raise KitInputError('対象避難所は1～200か所です。')
    rows=[]
    for i,r in enumerate(shelters):
        try:
            d=int(float(r.get('demandKits', r.get('capacity'))))
            b=int(float(r.get('stockKits', stock_to_kits(r.get('stock',{}))[0])))
            lat=float(r['lat']); lng=float(r['lng'])
        except (TypeError,ValueError,KeyError,OverflowError):
            raise KitInputError(f'{i+1}番避難所の位置・需要・備蓄を確認してください。')
        if not (math.isfinite(lat) and math.isfinite(lng) and 33<lat<36 and 134<lng<138) or d<=0 or b<0:
            raise KitInputError(f'{i+1}番避難所の入力値が不正です。')
        rows.append(dict(id=i,name=str(r.get('name') or f'避難所{i+1}'),lat=lat,lng=lng,
                         demand=d,stock=b,remaining=max(0,d-b),visited=bool(r.get('visited',False))))
    return dict(a=a,rho=rho,available=available,trucks=trucks,rounds=rounds,delta=delta,rows=rows)


def f1_score(rows, additions, a, rho, delta=1):
    weight = 1/(1-a)
    terms = [weight*(a-(r['stock']+add)/r['demand']) for r,add in zip(rows,additions)]
    active=[i for i,r in enumerate(rows) if r['remaining']>=delta]
    # Professor paper §4.4: the maximum is taken over K+ only;
    # micro-residual and fully stocked shelters remain in the rho-sum.
    return (max(terms[i] for i in active) if active else -1.0) + rho*sum(terms)


def solve_p1(clean):
    """Exact continuous P1 on one complete-kit commodity, NOT integer P0."""
    rows=clean['rows']; a=clean['a']; rho=clean['rho'];delta=clean['delta']
    n=len(rows); count=clean['trucks']; rounds=clean['rounds']
    mandatory=[i for i,r in enumerate(rows) if not r['visited'] and r['remaining']>=delta]
    active=[i for i,r in enumerate(rows) if r['remaining']>=delta]
    avail=min(clean['available'],rounds*count*TRUCK_CAP_KITS)
    if len(mandatory)*delta>avail:
        raise KitInputError('最低配送量を全避難所へ届けるための物資・輸送能力が不足しています。')
    if len(mandatory)>count*rounds*TRUCK_CAP_KITS//delta:
        raise KitInputError('配送回数・車両容量では全避難所へ最低配送量を届けられません。')
    lower=[float(delta if i in mandatory else 0) for i in range(n)]
    upper=[float(r['remaining'] if i in active else 0) for i,r in enumerate(rows)]
    if not active:
        return dict(f1=f1_score(rows,[0]*n,a,rho,delta),allocations=[0.]*n,
                    theta=-1.0,available=avail,active=0,mandatory=0)
    # x_0...x_n-1, theta
    N=n+1; w=1/(1-a)
    c=[-rho*w/r['demand'] for r in rows]+[1.]
    A=[[1.]*n+[0.]]; ub=[float(avail)]
    for i in active:
        line=[0.]*N;line[i]=-w/rows[i]['demand'];line[-1]=-1.
        A.append(line);ub.append(-w*(a-rows[i]['stock']/rows[i]['demand']))
    ans=linprog(c,A_ub=A,b_ub=ub,bounds=[(lower[i],upper[i]) for i in range(n)]+[(None,None)],method='highs')
    if not ans.success:
        raise KitInputError('P1の理想配分を計算できません。')
    xs=[max(0.,float(x)) for x in ans.x[:n]]
    theta=max(w*(a-(r['stock']+xs[i])/r['demand']) for i,r in enumerate(rows) if i in active)
    return dict(f1=f1_score(rows,xs,a,rho,delta),allocations=xs,theta=theta,
                available=avail,active=len(active),mandatory=len(mandatory))


def round_integer_p1(clean, p1):
    """Integer feasible per-shelter approximation: preserve min visits and kit budget."""
    rows=clean['rows']; delta=clean['delta']; budget=int(p1['available'])
    lows=[delta if r['remaining']>=delta and not r['visited'] else 0 for r in rows]
    x=[min(r['remaining'],max(lows[i],int(math.floor(v+1e-8)))) for i,(r,v) in enumerate(zip(rows,p1['allocations']))]
    # Numerical allocations can sum to one unit above the available stock after rounding up mandatory lows.
    while sum(x)>budget:
        candidates=[i for i in range(len(rows)) if x[i]>lows[i]]
        if not candidates:raise KitInputError('最小訪問量と在庫が矛盾しています。')
        i=min(candidates,key=lambda j:(p1['allocations'][j]-x[j],-rows[j]['demand']))
        x[i]-=1
    # Only positive deliveries >= delta are legal.  Remnants with 0 < demand <
    # delta are micro-residuals: they cannot be given a sub-minimum shipment.
    # Re-distribute integer leftovers among active destinations while preserving
    # the per-visit minimum.  This fixes the failure when minKits=10.
    to_assign=min(budget-sum(x),sum(r['remaining']-x[i] for i,r in enumerate(rows) if r['remaining']>=delta))
    a=clean['a']
    while to_assign>0:
        candidates=[i for i,r in enumerate(rows) if r['remaining']>=delta and
                    x[i]<r['remaining'] and (x[i]>=delta or to_assign>=delta)]
        if not candidates:break
        i=max(candidates,key=lambda j:(a-(rows[j]['stock']+x[j])/rows[j]['demand'],
                                       (p1['allocations'][j]-x[j])/max(1,rows[j]['demand'])))
        deficit=a-(rows[i]['stock']+x[i])/rows[i]['demand']
        second=max([a-(rows[j]['stock']+x[j])/rows[j]['demand'] for j in candidates if j!=i],default=-10.)
        jump=max(1,int((deficit-second)*rows[i]['demand']))
        minjump=delta if x[i]==0 else 1
        z=min(to_assign,rows[i]['remaining']-x[i],max(minjump,jump))
        if z < minjump:
            break
        x[i]+=z;to_assign-=z
    assert all(v==0 or v>=delta for v in x), 'minimum delivery invariant broken'
    return x
