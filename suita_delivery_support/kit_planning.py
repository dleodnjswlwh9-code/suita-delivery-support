"""1人1日分を単位とする研究用救援物資モデル。

1キットはレトルトご飯3食と500mLの飲料水6本からなる。
在庫は完全キット単位で換算し、端数の単品在庫は使用しない。
P0は連続線形計画、配送計画は整数キットの近似解であり、最適性は保証しない。"""
from __future__ import annotations
from dataclasses import dataclass
import math
from scipy.optimize import linprog

KIT_KG = 4.5  # ご飯3食・水6本の換算重量。包装材は含めない研究上の仮定。
TRUCK_CAP_KITS = math.floor(2000.0 / KIT_KG)
TRUCK_4T_CAP_KITS = math.floor(4000.0 / KIT_KG)

def get_fleet(data, trucks):
    """2t車、4t車の順に車両集合を作る。10t車は受け付けない。"""
    fleet=data.get('vehicles')
    if fleet is None:
        # 旧式のAPI要求は2t車のみを使用するものとして扱う。
        return [dict(type='2t',capacityKg=2000,capacityKits=TRUCK_CAP_KITS) for _ in range(trucks)]
    if not isinstance(fleet,list) or not fleet or len(fleet)>2:
        raise KitInputError('車両は2t・4tトラックだけ設定してください。')
    quantities={2000:0,4000:0};seen=set()
    for v in fleet:
        if not isinstance(v,dict):raise KitInputError('車両条件が不正です。')
        try:capacity=float(v['capacityKg']);count=_whole_kits(v['count'],'車両台数')
        except (KeyError,TypeError,ValueError,OverflowError):
            raise KitInputError('車両は2t・4tトラックだけ設定してください。')
        if not math.isfinite(capacity) or capacity not in quantities or not 0<=count<=50:
            raise KitInputError('車両は2t・4tトラックだけ設定してください。')
        if capacity in seen:raise KitInputError('同じ車種を重複して指定できません。')
        seen.add(capacity)
        quantities[capacity]=count
    if sum(quantities.values())!=trucks:
        raise KitInputError('2t・4tトラックの合計台数と車両台数が一致しません。')
    return [dict(type=f'{int(kg/1000)}t',capacityKg=kg,capacityKits=math.floor(kg/KIT_KG))
            for kg in (2000,4000) for _ in range(quantities[kg])]

LOADING_MIN = 30.0       # 研究用の設定値であり、実測した2t車の標準値ではない。
PREP_MIN = 15.0          # 避難所ごとの訪問準備時間：先行研究を参考に設定。
UNLOADING_MIN_PER_KIT = 120.0 / 3000.0  # 感度分析用の仮定値。
ROAD_SPEED_KMH = 20.0    # 市街地距離の概算であり、実道路の到着予想時間ではない。
ALLOWED_A = (0.7, 0.8, 0.85, 0.9)

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
    # 教員モデルの運用条件。配送量は4.5kgの整数キット単位で、10kg指定は3キット＝13.5kgに切り上げる。
    if any(name in data for name in ('p1MinimumKg','p1MaxRounds','p1MandatoryVisitPolicy','p1ModelMode')):
        try:
            minimum_kg=float(data.get('p1MinimumKg',delta*KIT_KG))
        except (TypeError,ValueError,OverflowError):
            raise KitInputError('P1最小配送量（kg）が不正です。')
        if not math.isfinite(minimum_kg) or not 0.1<=minimum_kg<=TRUCK_4T_CAP_KITS*KIT_KG:
            raise KitInputError('P1最小配送量は0.1～3996kgで指定してください。')
        needed_kits=math.ceil((minimum_kg-1e-10)/KIT_KG)
        if delta!=needed_kits:
            raise KitInputError(f'P1最小配送量{minimum_kg}kgには{needed_kits}キット必要です。P0・P1・P2の配送単位が一致しません。')
        if data.get('p1MaxRounds',rounds)!=rounds:
            raise KitInputError('P1の最大配送回数がP0・P2と一致しません。')
        if data.get('p1MandatoryVisitPolicy','professor')!='professor':
            raise KitInputError('必須訪問を変更するモードは未実装です。教授モデル条件を使用してください。')
        if data.get('p1ModelMode','basic')!='basic':
            raise KitInputError('経路・時間上限を含む拡張P1は未実装です。基本モデルのみ計算できます。')
    if not any(abs(a-x)<1e-9 for x in ALLOWED_A) or not 0 < rho <= 1 or available < 0 or not 1<=trucks<=50 or not 1<=rounds<=50 or not 1<=delta<=TRUCK_4T_CAP_KITS:
        raise KitInputError('希求水準70/80/85/90％、物資量、車両数、配送回数、最小配送量を確認してください。')
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
    # 論文の初期条件に関する仮定は明示的なP1設定画面で検証し、旧P0形式の入力は維持する。
    if data.get('p1ModelMode')=='basic' and data.get('p1MandatoryVisitPolicy')=='professor':
        zero=[row['name'] for row in rows if row['demand']<=0]
        undersized=[row['name'] for row in rows if 0<row['demand']<delta]
        if zero:
            raise KitInputError('教授モデルの入力条件(19)：需要量が0の避難所を対象に含められません。対象施設を確認してください：'+', '.join(zero[:3]))
        if undersized:
            raise KitInputError(f'教授モデルの初回条件(21)：需要量が最低配送単位δ={delta}キット未満の避難所があります。対象施設またはδを確認してください：'+', '.join(undersized[:3]))
    fleet=get_fleet(data,trucks)
    # 拡張P1・P2では仮定した拠点在庫と車両の固定所属拠点を使用できる。
    hub_stock=data.get('hubStockKits')
    if hub_stock is not None:
        if not isinstance(hub_stock,list) or len(hub_stock)!=2:
            raise KitInputError('北部・南部の在庫量を設定してください。')
        hub_stock=[_whole_kits(v,'拠点在庫') for v in hub_stock]
        if any(v<0 or v>10000000 for v in hub_stock):
            raise KitInputError('拠点在庫は0以上の整数で入力してください。')
        if available>sum(hub_stock):
            raise KitInputError('P0の総在庫が北部・南部の在庫合計を超えています。P0の総量も変更してください。')
    by_hub=data.get('vehicleHubCounts')
    if by_hub is not None:
        if not isinstance(by_hub,list) or len(by_hub)!=2:
            raise KitInputError('北部・南部の車両台数を確認してください。')
        counts=[]
        for h in by_hub:
            if not isinstance(h,dict):raise KitInputError('拠点別車両台数が不正です。')
            counts.append({c:_whole_kits(h.get(c,0),'拠点別車両台数') for c in ('2t','4t')})
        if any(n<0 or n>50 for h in counts for n in h.values()):
            raise KitInputError('拠点別車両台数は0～50台です。')
        if sum(h['2t'] for h in counts)!=sum(v['type']=='2t' for v in fleet) or sum(h['4t'] for h in counts)!=sum(v['type']=='4t' for v in fleet):
            raise KitInputError('拠点別台数と2t・4tの総台数が一致しません。')
        for typ in ('2t','4t'):
            hseq=[h for h in (0,1) for _ in range(counts[h][typ])]
            inds=[v for v in fleet if v['type']==typ]
            for v,h in zip(inds,hseq):v['hub']=h
    elif hub_stock is not None:
        raise KitInputError('拠点別在庫を使用する場合、拠点別車両台数も指定してください。')
    def optional_minutes(key,maximum=100000):
        val=data.get(key)
        if val is None or val=='':return None
        try:v=float(val)
        except (TypeError,ValueError,OverflowError):raise KitInputError(key+'を確認してください。')
        if not math.isfinite(v) or not 1<=v<=maximum:
            raise KitInputError(key+'は1～'+str(maximum)+'分です。')
        return v
    max_round=optional_minutes('maxRoundMinutes')
    max_total=optional_minutes('maxTotalMinutes')
    loading_parallel=data.get('loadingParallel',[trucks,trucks])
    if not isinstance(loading_parallel,list) or len(loading_parallel)!=2:
        raise KitInputError('同時積込台数を確認してください。')
    loading_parallel=[_whole_kits(x,'同時積込台数') for x in loading_parallel]
    if any(x<1 or x>50 for x in loading_parallel):raise KitInputError('同時積込台数は1～50台です。')
    windows=data.get('visitWindows') or {}
    if not isinstance(windows,dict):raise KitInputError('避難所の訪問時間帯を確認してください。')
    names={r['name'] for r in rows}
    if any(name not in names for name in windows):
        raise KitInputError('訪問時間帯に対象外の避難所が含まれています。')
    validated_windows={}
    for name,span in windows.items():
        if not isinstance(span,list) or len(span)!=2:
            raise KitInputError('訪問時間帯は開始・終了の2つの値です。')
        lo=_whole_kits(span[0],'訪問開始');hi=_whole_kits(span[1],'訪問終了')
        if not 0<=lo<hi<=100000:
            raise KitInputError('避難所の訪問時間帯は開始＜終了で指定してください。')
        validated_windows[name]=(lo,hi)
    if not fleet or delta>max(v['capacityKits'] for v in fleet):
        raise KitInputError('最小配送量を積載できる車両がありません。')
    return dict(a=a,rho=rho,available=available,trucks=trucks,rounds=rounds,delta=delta,rows=rows,fleet=fleet,hubStockKits=hub_stock,vehicleHubCounts=by_hub,maxRoundMinutes=max_round,maxTotalMinutes=max_total,loadingParallel=loading_parallel,visitWindows=validated_windows)


def f1_score(rows, additions, a, rho, delta=1):
    weight = 1/(1-a)
    # 需要ゼロの避難所は非活性とし、配送先に加えない。
    terms = [weight*(a-(r['stock']+add)/r['demand']) if r['demand']>0 else 0.
             for r,add in zip(rows,additions)]
    active=[i for i,r in enumerate(rows) if r['remaining']>=delta]
    # 最大不足度の評価対象はK+のみとし、微少残余・飽和施設もρの総和には含める。
    return (max(terms[i] for i in active) if active else -1.0) + rho*sum(terms)


def solve_p0(clean):
    """整数制約を加えない連続線形計画としてP0を計算する。"""
    rows=clean['rows']; a=clean['a']; rho=clean['rho'];delta=clean['delta']
    n=len(rows); count=clean['trucks']; rounds=clean['rounds']
    mandatory=[i for i,r in enumerate(rows) if not r['visited'] and r['remaining']>=delta]
    active=[i for i,r in enumerate(rows) if r['remaining']>=delta]
    fleet=clean['fleet'];max_capacity=max(v['capacityKits'] for v in fleet)
    avail=min(clean['available'],rounds*sum(v['capacityKits'] for v in fleet))
    minimum=len(mandatory)*delta
    if minimum>avail:
        raise KitInputError(f'最小配送単位δ={delta}人日分：必須訪問{len(mandatory)}か所に最低{minimum}人日分が必要ですが、利用可能量は{avail}人日分です（不足{minimum-avail}人日分）。')
    visits=rounds*sum(v['capacityKits']//delta for v in fleet)
    if len(mandatory)>visits:
        raise KitInputError(f'訪問可能箇所数が不足：必須訪問{len(mandatory)}か所、上限{visits}か所（2t・4t車両別積載量を計算）。')
    lower=[float(delta if i in mandatory else 0) for i in range(n)]
    # 同じ回に同じ避難所を訪問する車両は1台まで。施設別上限は残回数と最大車両容量で決まる。
    upper=[float(min(r['remaining'],rounds*max_capacity) if i in active else 0)
           for i,r in enumerate(rows)]
    if not active:
        return dict(f1=f1_score(rows,[0]*n,a,rho,delta),allocations=[0.]*n,
                    theta=-1.0,available=avail,active=0,mandatory=0)
    # 変数は各施設の配分量と最大不足度を表す。
    N=n+1; w=1/(1-a)
    c=[-rho*w/r['demand'] if r['demand']>0 else 0. for r in rows]+[1.]
    A=[[1.]*n+[0.]]; ub=[float(avail)]
    for i in active:
        line=[0.]*N;line[i]=-w/rows[i]['demand'];line[-1]=-1.
        A.append(line);ub.append(-w*(a-rows[i]['stock']/rows[i]['demand']))
    ans=linprog(c,A_ub=A,b_ub=ub,bounds=[(lower[i],upper[i]) for i in range(n)]+[(None,None)],method='highs')
    if not ans.success:
        raise KitInputError('P0の理想配分を計算できません。')
    xs=[max(0.,float(x)) for x in ans.x[:n]]
    theta=max(w*(a-(r['stock']+xs[i])/r['demand']) for i,r in enumerate(rows) if i in active)
    return dict(f1=f1_score(rows,xs,a,rho,delta),allocations=xs,theta=theta,
                available=avail,active=len(active),mandatory=len(mandatory))


def round_integer_p0(clean, p0):
    """最小訪問量と総キット予算を守り、P0の結果を整数の配分案に近似する。"""
    rows=clean['rows']; delta=clean['delta']; budget=int(p0['available'])
    lows=[delta if r['remaining']>=delta and not r['visited'] else 0 for r in rows]
    upper=[min(r['remaining'],clean['rounds']*max(v['capacityKits'] for v in clean['fleet'])) if r['remaining']>=delta else 0
           for r in rows]
    x=[min(upper[i],max(lows[i],int(math.floor(v+1e-8))))
       for i,v in enumerate(p0['allocations'])]
    # 既訪問施設は今後の訪問を必須としないが、追加配送する場合は1回の最小配送量を守る。
    x=[0 if 0<v<delta else v for v in x]
    # 必須配送量の切り上げ後には、計算誤差により利用可能在庫を1単位超過する場合がある。
    while sum(x)>budget:
        candidates=[i for i in range(len(rows)) if x[i]>lows[i]]
        if not candidates:raise KitInputError('最小訪問量と在庫が矛盾しています。')
        i=min(candidates,key=lambda j:(p0['allocations'][j]-x[j],-rows[j]['demand']))
        x[i]-=1
    # 正の配送量は必ずδ以上とする。微少残余へδ未満を配送せず、整数端数を他の対象施設に再配分する。
    to_assign=min(budget-sum(x),sum(upper[i]-x[i] for i,r in enumerate(rows) if r['remaining']>=delta))
    a=clean['a']
    while to_assign>0:
        candidates=[i for i,r in enumerate(rows) if r['remaining']>=delta and
                    x[i]<upper[i] and (x[i]>=delta or to_assign>=delta)]
        if not candidates:break
        i=max(candidates,key=lambda j:(a-(rows[j]['stock']+x[j])/rows[j]['demand'],
                                       (p0['allocations'][j]-x[j])/max(1,rows[j]['demand'])))
        deficit=a-(rows[i]['stock']+x[i])/rows[i]['demand']
        second=max([a-(rows[j]['stock']+x[j])/rows[j]['demand'] for j in candidates if j!=i],default=-10.)
        jump=max(1,int((deficit-second)*rows[i]['demand']))
        minjump=delta if x[i]==0 else 1
        z=min(to_assign,upper[i]-x[i],max(minjump,jump))
        if z < minjump:
            break
        x[i]+=z;to_assign-=z
    assert all(v==0 or v>=delta for v in x), '最小配送量の条件に違反しています。'
    return x
