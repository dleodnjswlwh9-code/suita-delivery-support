"""Professor rev21, Section 4.2 equations (24)-(31): uncapped aspiration-based P1.

The published P1 is ONE commodity and ONE hub; this application has TWO.
For two goods, it minimizes the SUM of two original F1 objective terms,
each with its OWN worst normalized shortfall theta_c, sharing one combined
vehicle-capacity budget and facility-visit minimum across goods.
No aspiration ceiling, lexicographic fairness step, or hand-coded priority.
This is a clearly labeled multi-commodity extension, NOT an exact replication
of the professor's single-commodity problem. Paper Sbar denotes actually
received shipments; existing app uses onsite stock as its starting baseline.
P0/P2 are not implemented, so the provisional allocation is NOT guaranteed
to be operationally deliverable at the planned vehicle/visit resolution.
"""
from __future__ import annotations
import math
from scipy.optimize import linprog
from p1_optimizer import P1InputError

MAX_ROUNDS = 1000
MAX_VEHICLES = 2000
EPS=1e-8


def _validation(food_rows,water_rows,food_kg,water_kg,rho,delta,rounds,vehicles):
    if not (isinstance(food_rows,list) and isinstance(water_rows,list) and
            len(food_rows)==len(water_rows) and 1<=len(food_rows)<=500):
        raise P1InputError('食料・飲料水の避難所データ件数が一致しません。')
    try:
        rho=float(rho);delta=float(delta);fs=float(food_kg);ws=float(water_kg);R=int(rounds)
    except (TypeError, ValueError, OverflowError):
        raise P1InputError('ρ・最小配送量・物資量・配送回数が無効です。')
    if not all(math.isfinite(z) for z in (rho,delta,fs,ws)) or not (0<rho<=100 and delta>0 and fs>=0 and ws>=0 and 1<=R<=MAX_ROUNDS):
        raise P1InputError('ρ>0、δ>0、在庫0以上、配送回数1以上で設定してください。')
    if not isinstance(vehicles,list):raise P1InputError('使用車両が未設定です。')
    caps=[]
    for v in vehicles:
        try:q=float(v['capacityKg']);count=int(v['count'])
        except (KeyError,ValueError,TypeError,OverflowError):raise P1InputError('車両の容量と台数を確認してください。')
        if not math.isfinite(q) or q<=0 or count<0 or count>MAX_VEHICLES:raise P1InputError('車両の容量・台数が無効です。')
        caps.extend([q]*count)
    if not caps:raise P1InputError('使用車両が0台です。')
    data=[];visited=[]
    for i,(fr,wr) in enumerate(zip(food_rows,water_rows)):
        if bool(fr.get('visited',False))!=bool(wr.get('visited',False)):
            raise P1InputError('食料と飲料水の訪問履歴が一致していません。')
        visited.append(bool(fr.get('visited',False)))
        pair=[]
        for r in (fr,wr):
            try:d=float(r['demandKg']);b=float(r['securedKg']);a=float(r['targetRate'])
            except (KeyError,ValueError,TypeError,OverflowError):raise P1InputError(f'避難所{i+1}：必要量・確保量・希求水準を確認してください。')
            if not all(math.isfinite(z) for z in (d,b,a)) or d<=0 or b<0 or not 0<=a<1-1e-8:
                raise P1InputError(f'避難所{i+1}：必要量>0、確保量≥0、希求水準0%以上100%未満で指定してください。')
            pair.append((d,b,a,max(0.,d-b)))
        data.append(pair)
    return rho,delta,fs,ws,R,caps,data,visited


def optimize_joint_p1(food_rows,water_rows,food_kg,water_kg,
                      rho,min_delivery_kg,rounds,vehicles):
    rho,delta,fs,ws,R,caps,data,visited=_validation(food_rows,water_rows,food_kg,water_kg,rho,min_delivery_kg,rounds,vehicles)
    n=len(data);m=2*n
    # For extension: a single visit may carry food and water, so its minimum
    # is based on combined residual. Equation (12) in paper is per commodity.
    remain=[sum(data[i][c][3] for c in (0,1)) for i in range(n)]
    active=[i for i in range(n) if remain[i]>=delta-EPS]
    required=[i for i in active if not visited[i]]
    budget=R*sum(caps)
    if not active:
        return {'allocationsFoodKg':[0.]*n,'allocationsWaterKg':[0.]*n,
                'objectiveF1':None,'objectiveByCommodity':{'food':None,'water':None},
                'thetaByCommodity':{'food':None,'water':None},
                'usedFoodKg':0.,'usedWaterKg':0.,'unusedFoodKg':fs,'unusedWaterKg':ws,
                'vehicleBudgetKg':budget,'mandatoryCount':0,'activeCount':0,
                'microCount':sum(0<r<delta for r in remain),
                'model':'professor_F1_sum_two_commodity_extension',
                'note':'追加配分できる避難所がありません。'}
    if delta*len(required)>fs+ws+1e-6:
        raise P1InputError(f'必須訪問先{len(required)}か所の最低配送量{delta*len(required):g}kgが在庫を超えます。')
    slots=R*sum(math.floor(q/delta+1e-10) for q in caps)
    if slots<len(required):
        raise P1InputError(f'訪問可能枠{slots}か所が必須訪問数{len(required)}か所より少ないため計算できません。')
    # Decisions: x[k, food], x[k, water], theta_food, theta_water.
    # Each F1 exactly follows paper eqs (24), (27)-(28), including sum over
    # ALL facilities, even inactive ones. Each theta is unrestricted in sign.
    active_goods=[]
    for c in (0,1):
        if any(data[i][c][3]>EPS for i in active):active_goods.append(c)
    bounds=[]
    for i in range(n):
        for c in (0,1):
            d,b,a,res=data[i][c]
            bounds.append((0.,min(res,R*max(caps)) if i in active and res>EPS else 0.))
    bounds+= [(None,None) if c in active_goods else (0.,0.) for c in (0,1)]
    objective=[]
    for i in range(n):
        for c in (0,1):
            d,b,a,res=data[i][c]
            objective.append(-rho/((1-a)*d) if c in active_goods else 0.)
    objective.extend([1. if c in active_goods else 0. for c in (0,1)])
    A=[];U=[]
    A.append([1.]*m+[0.,0.]);U.append(budget)
    for c,stock in ((0,fs),(1,ws)):
        row=[0.]*(m+2)
        for i in range(n):row[2*i+c]=1.
        A.append(row);U.append(stock)
    for i in range(n):
        row=[0.]*(m+2);row[2*i]=1.;row[2*i+1]=1.
        A.append(row);U.append(min(remain[i],R*max(caps)) if i in active else 0.)
    for i in required:
        row=[0.]*(m+2);row[2*i]=-1.;row[2*i+1]=-1.
        A.append(row);U.append(-delta)
    for c in active_goods:
        for i in active:
            d,b,a,res=data[i][c]
            # When a commodity cannot be improved, its constant g is included
            # in the augmentation, but not the theta max over active commodities.
            if res<=EPS: continue
            weight=1/(1-a)
            row=[0.]*(m+2);row[2*i+c]=-weight/d;row[m+c]=-1.
            A.append(row);U.append(-weight*(a-b/d))
    result=linprog(objective,A_ub=A,b_ub=U,bounds=bounds,method='highs',
        options={'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
    if not result.success:
        raise P1InputError('教授P1の実行可能解がありません。積載量・物資量・δ・訪問回数を確認してください。')
    f=[max(0.,float(result.x[2*i])) for i in range(n)]
    w=[max(0.,float(result.x[2*i+1])) for i in range(n)]
    if sum(f)+sum(w)>budget+1e-5 or sum(f)>fs+1e-5 or sum(w)>ws+1e-5:
        raise P1InputError('P1の在庫・積載上限制約に数値誤差があります。')
    if any(f[i]+w[i]<delta-1e-5 for i in required):
        raise P1InputError('P1の必須訪問最低配分に数値誤差があります。')
    objectives={};thetas={}; keys=('food','water')
    for c,key in enumerate(keys):
        if c not in active_goods:
            objectives[key]=None;thetas[key]=None;continue
        terms=[];g_active=[]
        for i in range(n):
            d,b,a,res=data[i][c];alloc=f[i] if c==0 else w[i]
            g=(a-(b+alloc)/d)/(1-a)
            terms.append(g)
            if i in active and res>EPS:g_active.append(g)
        theta=max(g_active)
        thetas[key]=theta
        objectives[key]=theta+rho*sum(terms)
    total=sum(x for x in objectives.values() if x is not None)
    return {'allocationsFoodKg':f,'allocationsWaterKg':w,
            'objectiveF1':total,'objectiveByCommodity':objectives,'thetaByCommodity':thetas,
            'theta':max(x for x in thetas.values() if x is not None),
            'usedFoodKg':sum(f),'usedWaterKg':sum(w),
            'unusedFoodKg':max(0.,fs-sum(f)),'unusedWaterKg':max(0.,ws-sum(w)),
            'vehicleBudgetKg':budget,'mandatoryCount':len(required),
            'activeCount':len(active),'microCount':sum(0<r<delta for r in remain),
            'minDeliveryKg':delta,'remainingTrips':R,
            'model':'professor_F1_sum_two_commodity_extension',
            'note':None}
