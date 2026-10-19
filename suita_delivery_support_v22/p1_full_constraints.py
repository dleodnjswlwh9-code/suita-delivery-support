"""Unified P1 for food and water (research extension of paper §4.2).

One shelter has one aspiration of 80% and one normalized shortage:
    g_k = max(g_food, g_water)
        = (0.8 - min(food coverage, water coverage)) / (1 - 0.8).
The LP minimizes theta + rho * sum(g_k), theta >= g_k over active shelters.
Food and water stocks are never interchangeable. Vehicle and visit bounds in
P1 are necessary aggregate bounds ONLY; feasibility P0 and routing P2 remain
unimplemented. Stock on hand is a baseline approximation to paper's Sbar.
"""
from __future__ import annotations
import math
from scipy.optimize import linprog
from p1_optimizer import P1InputError

TARGET=.8
WEIGHT=1/(1-TARGET)
EPS=1e-8
MAX_ROUNDS=1000
MAX_VEHICLES=2000


def optimize_joint_p1(food_rows,water_rows,food_kg,water_kg,
                      rho,min_delivery_kg,rounds,vehicles):
    if not isinstance(food_rows,list) or not isinstance(water_rows,list) or not 1<=len(food_rows)==len(water_rows)<=500:
        raise P1InputError('避難所の食料・飲料水データが一致しません。')
    try:
        rho=float(rho);delta=float(min_delivery_kg);fs=float(food_kg);ws=float(water_kg);R=int(rounds)
    except (ValueError, TypeError, OverflowError):
        raise P1InputError('入力された数値を確認してください。')
    if not all(math.isfinite(v) for v in (rho,delta,fs,ws)) or not 0<rho<=1 or delta<=0 or fs<0 or ws<0 or not 1<=R<=MAX_ROUNDS:
        raise P1InputError('物資量・ρ・最小配送量・配送回数を確認してください。')
    if not isinstance(vehicles,list) or len(vehicles)!=1:
        raise P1InputError('車両は2tトラックのみ設定してください。')
    try:
        q=float(vehicles[0]['capacityKg']);count=int(vehicles[0]['count'])
    except (TypeError,ValueError,KeyError,OverflowError):
        raise P1InputError('2tトラックの台数を確認してください。')
    if q!=2000 or not 1<=count<=MAX_VEHICLES:
        raise P1InputError('2tトラックの台数は1台以上で設定してください。')

    data=[];visited=[]
    for i,(fr,wr) in enumerate(zip(food_rows,water_rows)):
        if bool(fr.get('visited'))!=bool(wr.get('visited')):
            raise P1InputError(f'{i+1}番の訪問状況が一致しません。')
        visited.append(bool(fr.get('visited')))
        one=[]
        for r in (fr,wr):
            try:
                d=float(r['demandKg']); b=float(r['securedKg']); a=float(r['targetRate'])
            except (KeyError,TypeError,ValueError,OverflowError):
                raise P1InputError(f'{i+1}番の必要量と備蓄量を確認してください。')
            if not math.isfinite(d) or not math.isfinite(b) or not math.isfinite(a) or d<=0 or b<0 or abs(a-TARGET)>1e-8:
                raise P1InputError(f'{i+1}番の必要量・備蓄量・希求水準（80%）を確認してください。')
            one.append((d,b,max(0.,d-b)))
        data.append(one)

    n=len(data);m=2*n;theta_idx=m;z_start=m+1;v_count=m+1+n
    residual=[sum(data[i][c][2] for c in (0,1)) for i in range(n)]
    active=[i for i in range(n) if residual[i]>=delta-EPS]
    mandatory=[i for i in active if not visited[i]]
    budget=R*q*count
    if not active:
        return dict(allocationsFoodKg=[0.]*n,allocationsWaterKg=[0.]*n,
                    objectiveF1=None,theta=None,usedFoodKg=0.,usedWaterKg=0.,
                    unusedFoodKg=fs,unusedWaterKg=ws,vehicleBudgetKg=budget,
                    mandatoryCount=0,activeCount=0,microCount=sum(0<x<delta for x in residual),
                    minDeliveryKg=delta,remainingTrips=R,weight=WEIGHT,targetRate=TARGET,
                    model='unified_two_commodity_p1',note='追加配分できる避難所がありません。')
    if len(mandatory)*delta>fs+ws+EPS:
        raise P1InputError('最低配送量の合計が、使える物資量を超えています。')
    if R*count*math.floor(q/delta+EPS)<len(mandatory):
        raise P1InputError('2tトラックの台数・回数では、全避難所を訪問できません。')

    # x_food, x_water, unrestricted theta, and per-shelter combined shortage z_k.
    # z_k = max(g_food,g_water) is driven to equality by positive rho.
    bounds=[]
    for i in range(n):
        for c in (0,1):
            remaining=data[i][c][2]
            bounds.append((0.,min(remaining,R*q) if i in active else 0.))
    bounds.append((None,None))
    bounds += [(None,None)]*n
    obj=[0.]*v_count;obj[theta_idx]=1.
    for i in range(n):obj[z_start+i]=rho
    A=[];upper=[]
    def add(terms,limit):
        line=[0.]*v_count
        for k,v in terms:line[k]=v
        A.append(line);upper.append(limit)
    add([(j,1.) for j in range(m)],budget)
    add([(2*i,1.) for i in range(n)],fs)
    add([(2*i+1,1.) for i in range(n)],ws)
    for i in range(n):
        add([(2*i,1.),(2*i+1,1.)],min(residual[i],R*q) if i in active else 0.)
    for i in mandatory:
        add([(2*i,-1.),(2*i+1,-1.)],-delta)
    for i in range(n):
        # z_i >= (0.8-(b+x)/d)/0.2 for EACH good.
        for c in (0,1):
            d,b,_=data[i][c]
            add([(2*i+c,-WEIGHT/d),(z_start+i,-1.)],-WEIGHT*(TARGET-b/d))
        if i in active:
            add([(z_start+i,1.),(theta_idx,-1.)],0.)

    sol=linprog(obj,A_ub=A,b_ub=upper,bounds=bounds,method='highs',
        options={'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
    if not sol.success:
        raise P1InputError('配分量を計算できませんでした。物資量・車両数・最小配送量を確認してください。')
    # F1が同じ解は複数ある。改善につながらない物資を使わないよう、
    # 最適F1を保ったまま予定配分量が最小の解を選ぶ。
    tie=[1.]*m+[0.]*(n+1)
    tie_solve=linprog(tie,A_ub=A+[obj],b_ub=upper+[sol.fun+1e-10*max(1.,abs(sol.fun))],
                      bounds=bounds,method='highs')
    if tie_solve.success:
        sol=tie_solve
    food=[max(0.,float(sol.x[2*i])) for i in range(n)]
    water=[max(0.,float(sol.x[2*i+1])) for i in range(n)]
    rates=[]
    for i in range(n):
        rates.append(min((data[i][0][1]+food[i])/data[i][0][0],
                         (data[i][1][1]+water[i])/data[i][1][0]))
    gaps=[WEIGHT*(TARGET-rate) for rate in rates]
    theta=max(gaps[i] for i in active)
    f1=theta+rho*sum(gaps)
    if (sum(food)>fs+1e-5 or sum(water)>ws+1e-5 or sum(food)+sum(water)>budget+1e-5
        or any(food[i]+water[i]<delta-1e-5 for i in mandatory)):
        raise P1InputError('配分結果が物資量または配送能力を超えています。')
    return dict(allocationsFoodKg=food,allocationsWaterKg=water,
                objectiveF1=f1,theta=theta,weight=WEIGHT,targetRate=TARGET,
                combinedRates=rates,usedFoodKg=sum(food),usedWaterKg=sum(water),
                unusedFoodKg=max(0.,fs-sum(food)),unusedWaterKg=max(0.,ws-sum(water)),
                vehicleBudgetKg=budget,mandatoryCount=len(mandatory),activeCount=len(active),
                microCount=sum(0<x<delta for x in residual),minDeliveryKg=delta,
                remainingTrips=R,model='unified_two_commodity_p1',note=None)
