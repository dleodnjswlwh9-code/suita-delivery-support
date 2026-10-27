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


def _whole_kits(value, field):
    # 1人日分はレトルト3食＋水6本の完成セット。小数を黙って切り捨てない。
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise KitInputError(f'{field}は整数で入力してください。')
    if not math.isfinite(number) or not number.is_integer() or abs(number) > 2**53 - 1:
        raise KitInputError(f'{field}は整数で入力してください。')
    return int(number)


def clean_input(data):
    if not isinstance(data, dict):
        raise KitInputError('入力が不正です。')
    try:
        a = float(data['targetRate'])
        rho = float(data.get('rho', 0.005))
        available = _whole_kits(data['totalKits'], '輸送拠点物資量（人日分）')
        trucks = _whole_kits(data['truckCount'], '車両台数')
        rounds = _whole_kits(data['maxRounds'], '配送回数上限')
        delta = _whole_kits(data.get('minKits', 1), '最小配送量')
    except KitInputError:
        raise
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
            d=_whole_kits(r.get('demandKits', r.get('capacity')), f'{i+1}番避難所の必要量')
            b=_whole_kits(r.get('stockKits', stock_to_kits(r.get('stock',{}))[0]), f'{i+1}番避難所の備蓄量')
            lat=float(r['lat']); lng=float(r['lng'])
        except KitInputError:
            raise
        except (TypeError,ValueError,KeyError,OverflowError):
            raise KitInputError(f'{i+1}番避難所の位置・需要・備蓄を確認してください。')
        if not (math.isfinite(lat) and math.isfinite(lng) and 33<lat<36 and 134<lng<138) or d<0 or b<0:
            raise KitInputError(f'{i+1}番避難所の入力値が不正です。')
        rows.append(dict(id=i,name=str(r.get('name') or f'避難所{i+1}'),lat=lat,lng=lng,
                         demand=d,stock=b,remaining=max(0,d-b),visited=bool(r.get('visited',False))))
    return dict(a=a,rho=rho,available=available,trucks=trucks,rounds=rounds,delta=delta,rows=rows)


def f1_score(rows, additions, a, rho, delta=1):
    weight = 1/(1-a)
    # Zero-demand shelters are inactive, not artificial one-kit destinations.
    terms = [weight*(a-(r['stock']+add)/r['demand']) if r['demand']>0 else 0.
             for r,add in zip(rows,additions)]
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
    minimum=len(mandatory)*delta
    if minimum>avail:
        raise KitInputError(f'最小配送単位δ={delta}人日分：必須訪問{len(mandatory)}か所に最低{minimum}人日分が必要ですが、利用可能量は{avail}人日分です（不足{minimum-avail}人日分）。')
    visits=count*rounds*(TRUCK_CAP_KITS//delta)
    if len(mandatory)>visits:
        raise KitInputError(f'訪問可能箇所数が不足：必須訪問{len(mandatory)}か所、上限{visits}か所（車両{count}台×{rounds}回×1台当たり{TRUCK_CAP_KITS//delta}か所）。')
    lower=[float(delta if i in mandatory else 0) for i in range(n)]
    # Paper (26): in a round only one truck may visit the same shelter.
    # Even with many vehicles, the per-shelter upper bound is R * max_t Q_t.
    upper=[float(min(r['remaining'],rounds*TRUCK_CAP_KITS) if i in active else 0)
           for i,r in enumerate(rows)]
    if not active:
        return dict(f1=f1_score(rows,[0]*n,a,rho,delta),allocations=[0.]*n,
                    theta=-1.0,available=avail,active=0,mandatory=0)
    # x_0...x_n-1, theta
    N=n+1; w=1/(1-a)
    c=[-rho*w/r['demand'] if r['demand']>0 else 0. for r in rows]+[1.]
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
    upper=[min(r['remaining'],clean['rounds']*TRUCK_CAP_KITS) if r['remaining']>=delta else 0
           for r in rows]
    x=[min(upper[i],max(lows[i],int(math.floor(v+1e-8))))
       for i,v in enumerate(p1['allocations'])]
    # Previously visited shelters are optional this horizon, but any *new*
    # positive delivery still has to meet the per-visit minimum delta.
    x=[0 if 0<v<delta else v for v in x]
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
    to_assign=min(budget-sum(x),sum(upper[i]-x[i] for i,r in enumerate(rows) if r['remaining']>=delta))
    a=clean['a']
    while to_assign>0:
        candidates=[i for i,r in enumerate(rows) if r['remaining']>=delta and
                    x[i]<upper[i] and (x[i]>=delta or to_assign>=delta)]
        if not candidates:break
        i=max(candidates,key=lambda j:(a-(rows[j]['stock']+x[j])/rows[j]['demand'],
                                       (p1['allocations'][j]-x[j])/max(1,rows[j]['demand'])))
        deficit=a-(rows[i]['stock']+x[i])/rows[i]['demand']
        second=max([a-(rows[j]['stock']+x[j])/rows[j]['demand'] for j in candidates if j!=i],default=-10.)
        jump=max(1,int((deficit-second)*rows[i]['demand']))
        minjump=delta if x[i]==0 else 1
        z=min(to_assign,upper[i]-x[i],max(minjump,jump))
        if z < minjump:
            break
        x[i]+=z;to_assign-=z
    assert all(v==0 or v>=delta for v in x), 'minimum delivery invariant broken'
    return x
