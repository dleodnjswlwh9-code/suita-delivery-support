"""Paper rev21 §4.2 P1 (eq. 25–31), extended to *two* commodities.

The source paper is a one-depot/one-commodity model. The extension here uses
one shared vehicle-mass budget across both commodities; upper bound for any
single shelter is also applied to the combined mass of both commodities.
One trip/delivery visit minimum δ is enforced *only* on currently unvisited
shelters as the relaxed P1 lower bound, not on each positive delivery (P0).

Inputs ``securedKg`` combine onsite stocks and planned allocations in this
existing app. This is a planning adaptation, NOT the paper's observed
already-delivered quantity S^b. These are documented separately in README.
"""
from __future__ import annotations
import math
from scipy.optimize import linprog
from p1_optimizer import P1InputError

MAX_ROUNDS=1000
MAX_VEHICLES=2000


def optimize_joint_p1(food_rows, water_rows, food_kg, water_kg,
                      rho, min_delivery_kg, rounds, vehicles):
    if not (isinstance(food_rows,list) and isinstance(water_rows,list)
            and 1 <= len(food_rows) == len(water_rows) <= 500):
        raise P1InputError('食料・飲料水の避難所データ件数が一致しません。')
    try:
        rho=float(rho); delta=float(min_delivery_kg)
        food_stock=float(food_kg); water_stock=float(water_kg)
        n_rounds=int(rounds)
    except (TypeError, ValueError, OverflowError):
        raise P1InputError('ρ、最小配送量、物資量、配送回数を確認してください。')
    if not all(math.isfinite(v) for v in (rho,delta,food_stock,water_stock)):
        raise P1InputError('入力に無効な数値があります。')
    if rho <= 0 or rho > 100 or delta <= 0 or not(1<=n_rounds<=MAX_ROUNDS):
        raise P1InputError('ρ>0、最小配送量δ>0、配送回数1以上を指定してください。')
    if min(food_stock,water_stock)<0:
        raise P1InputError('輸送拠点物資量は0以上で指定してください。')
    if not isinstance(vehicles,list) or not vehicles:
        raise P1InputError('車両条件を設定してください（2t・4t・10tの台数）。')
    vehicle_capacities=[]
    for v in vehicles:
        if not isinstance(v,dict): raise P1InputError('車両条件が不正です。')
        try: cap=float(v['capacityKg']); count=int(v['count'])
        except (ValueError,TypeError,KeyError,OverflowError): raise P1InputError('車両容量と台数を確認してください。')
        if not math.isfinite(cap) or cap<=0 or count<0 or count>MAX_VEHICLES:
            raise P1InputError('車両容量・台数が不正です。')
        vehicle_capacities.extend([cap]*count)
    if not vehicle_capacities:
        raise P1InputError('車両が0台です。少なくとも1台を設定してください。')
    n=len(food_rows)
    data=[]
    visited=[]
    for i in range(n):
        v0=food_rows[i].get('visited',False)
        v1=water_rows[i].get('visited',False)
        if bool(v0)!=bool(v1):
            raise P1InputError('同じ避難所の訪問履歴が物資間で一致していません。')
        visited.append(bool(v0))
        for commodity,row in enumerate((food_rows[i], water_rows[i])):
            try:
                d=float(row['demandKg']); b=float(row['securedKg']); a=float(row['targetRate'])
            except (KeyError,ValueError,TypeError,OverflowError):
                raise P1InputError(f'{i+1}番目の避難所の必要量・確保量・希求水準が不正です。')
            if (not all(map(math.isfinite,(d,b,a))) or d<=0 or b<0 or not(0<=a<1-1e-8)):
                raise P1InputError(f'{i+1}番目の避難所は必要量>0、確保量>=0、希求水準0～100%未満で指定してください。')
            data.append((i,commodity,d,b,a,max(0,d-b)))

    # Paper (12), (14), (17): the combined-commodity extension treats a
    # single visit as delivering total food+water mass >= delta.
    residual=[data[2*i][5]+data[2*i+1][5] for i in range(n)]
    active_shelters=[i for i in range(n) if residual[i]>=delta-1e-10]
    required=[i for i in active_shelters if not visited[i]]
    if not active_shelters:
        return {'allocationsFoodKg':[0.0]*n,'allocationsWaterKg':[0.0]*n,
                'objectiveF1':None,'theta':None,'usedFoodKg':0.0,'usedWaterKg':0.0,
                'vehicleBudgetKg':n_rounds*sum(vehicle_capacities),
                'mandatoryCount':0,'microCount':sum(0<r<delta for r in residual),
                'note':'追加配送できる避難所がありません。'}
    # Paper assumption (22): mandatory minimum supply and visit slots.
    if delta*len(required)>food_stock+water_stock+1e-6:
        raise P1InputError(f'必要訪問{len(required)}か所の最低配送量（合計{delta*len(required):g}kg）が在庫を超えます。')
    visit_slots=n_rounds*sum(math.floor((q+1e-10)/delta) for q in vehicle_capacities)
    if visit_slots<len(required):
        raise P1InputError(f'訪問可能枠{visit_slots}か所が必須訪問{len(required)}か所より少ないため実行できません。')
    max_cap=max(vehicle_capacities)
    capacity_budget=n_rounds*sum(vehicle_capacities)
    # variables x_food_i, x_water_i (both for every shelter) and θ.
    m=2*n
    bounds=[]
    for i,c,d,b,a,r in data:
        max_kg=r if i in active_shelters else 0.0
        bounds.append((0,max_kg))
    bounds.append((None,None))
    # Every commodity contributes to F1 augmentation, even if stopped.
    c_obj=[-rho/((1-a)*d) for i,c,d,b,a,r in data]+[1.0]
    A=[]; ub=[]
    # Paper (25)+(30): ONE vehicle capacity budget shared across both goods.
    A.append([1.0]*m+[0]); ub.append(capacity_budget)
    # Commodity depot stock conservation (two-commodity extension).
    for commodity, stock in ((0,food_stock),(1,water_stock)):
        row=[0.0]*(m+1)
        for i in range(n): row[2*i+commodity]=1
        A.append(row); ub.append(stock)
    # Paper (26): per-shelter cap = min(residual demand, trips*max Qt)
    # shared between food and water to avoid double-counting vehicle capacity.
    for i in range(n):
        row=[0.0]*(m+1);row[2*i]=row[2*i+1]=1
        A.append(row);ub.append(min(residual[i],n_rounds*max_cap) if i in active_shelters else 0.0)
    # Required unvisited shelters must receive >= δ in total in P1.
    for i in required:
        row=[0.0]*(m+1); row[2*i]=row[2*i+1]=-1.0
        A.append(row);ub.append(-delta)
    # Paper (28): θ bounds only for active facility/commodity objectives.
    # For a facility active due to food+water remaining, include both terms
    # if they are capable of positive delivery; unchangeable terms are constants.
    for j,(i,c,d,b,a,r) in enumerate(data):
        if i in active_shelters and r>0:
            w=1/(1-a)
            row=[0.0]*(m+1);row[j]=-w/d;row[-1]=-1.0
            A.append(row);ub.append(-w*(a-b/d))
    solved=linprog(c_obj,A_ub=A,b_ub=ub,bounds=bounds,method='highs',
                   options={'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
    if not solved.success:
        raise P1InputError('P1計算の実行可能解がありません。物資量・車両・最小配送量の条件を確認してください。')
    f=[max(0.,float(solved.x[2*i])) for i in range(n)]
    w=[max(0.,float(solved.x[2*i+1])) for i in range(n)]
    theta=max((1/(1-a))*(a-(b+(f[i] if c==0 else w[i]))/d)
              for i,c,d,b,a,r in data if i in active_shelters and r>0)
    objective=theta+rho*sum((1/(1-a))*(a-(b+(f[i] if c==0 else w[i]))/d)
                            for i,c,d,b,a,r in data)
    # Verify primal constraints with explicit tolerances.
    for i in required:
        if f[i]+w[i]<delta-1e-5:
            raise P1InputError('P1の必須訪問下限制約で誤差が発生しました。')
    if sum(f)+sum(w)>capacity_budget+1e-5 or sum(f)>food_stock+1e-5 or sum(w)>water_stock+1e-5:
        raise P1InputError('P1の在庫・積載量上限で誤差が発生しました。')
    return {'allocationsFoodKg':f,'allocationsWaterKg':w,
            'objectiveF1':objective,'theta':theta,
            'usedFoodKg':sum(f),'usedWaterKg':sum(w),
            'unusedFoodKg':max(0.,food_stock-sum(f)),
            'unusedWaterKg':max(0.,water_stock-sum(w)),
            'vehicleBudgetKg':capacity_budget,
            'mandatoryCount':len(required),
            'activeCount':len(active_shelters),
            'microCount':sum(0<r<delta for r in residual),
            'minDeliveryKg':delta,'remainingTrips':n_rounds,
            'note':None}
