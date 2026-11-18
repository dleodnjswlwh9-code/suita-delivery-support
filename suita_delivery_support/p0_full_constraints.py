"""食料と飲料水を一体で評価するP0（論文4.2項の研究上の拡張）。

避難所ごとに一つの希求水準を設定し、食料・飲料水のうち不足が大きい方を評価する。
最大不足度と総不足度を目的関数とする線形計画で、
物資の重量予算内で品目別配分量を決定する。"""
from __future__ import annotations
import math
from scipy.optimize import linprog
from p0_optimizer import P0InputError

ALLOWED_TARGETS=(.7,.8,.85,.9)
EPS=1e-8
MAX_ROUNDS=1000
MAX_VEHICLES=2000


def optimize_joint_p0(food_rows,water_rows,total_kg,
                      rho,min_delivery_kg,rounds,vehicles,target_rate):
    if not isinstance(food_rows,list) or not isinstance(water_rows,list) or not 1<=len(food_rows)==len(water_rows)<=500:
        raise P0InputError('避難所の食料・飲料水データが一致しません。')
    try:
        rho=float(rho);delta=float(min_delivery_kg);total=float(total_kg);R=int(rounds);target=float(target_rate)
    except (ValueError, TypeError, OverflowError):
        raise P0InputError('入力された数値を確認してください。')
    if not all(math.isfinite(v) for v in (rho,delta,total,target)) or not 0<rho<=1 or delta<=0 or total<0 or not 1<=R<=MAX_ROUNDS or not any(abs(target-a)<1e-9 for a in ALLOWED_TARGETS):
        raise P0InputError('物資総量・希求水準（70/80/85/90%）・詳細設定を確認してください。')
    if not isinstance(vehicles,list) or not vehicles or len(vehicles)>2:
        raise P0InputError('車両は2t・4tトラックのみ設定してください。')
    by_class={2000:0,4000:0}
    try:
        for entry in vehicles:
            q=float(entry['capacityKg']);count=int(entry['count'])
            if q not in by_class or count<0 or count>50:raise ValueError()
            by_class[q]+=count
    except (TypeError,ValueError,KeyError,OverflowError):
        raise P0InputError('車両は2t・4tトラックのみ設定してください。')
    if sum(by_class.values())<1 or sum(by_class.values())>50:
        raise P0InputError('2t・4tの合計台数を1～50台にしてください。')
    vehicle_capacity=sum(q*n for q,n in by_class.items())
    max_capacity=max(q for q,n in by_class.items() if n>0)
    slots_per_round=sum(n*math.floor(q/delta+EPS) for q,n in by_class.items())

    weight=1/(1-target)
    data=[];visited=[]
    for i,(fr,wr) in enumerate(zip(food_rows,water_rows)):
        if bool(fr.get('visited'))!=bool(wr.get('visited')):
            raise P0InputError(f'{i+1}番の訪問状況が一致しません。')
        visited.append(bool(fr.get('visited')))
        one=[]
        for r in (fr,wr):
            try:
                d=float(r['demandKg']); b=float(r['securedKg']); a=float(r['targetRate'])
            except (KeyError,TypeError,ValueError,OverflowError):
                raise P0InputError(f'{i+1}番の必要量と備蓄量を確認してください。')
            if not math.isfinite(d) or not math.isfinite(b) or not math.isfinite(a) or d<=0 or b<0 or abs(a-target)>1e-8:
                raise P0InputError(f'{i+1}番の必要量・備蓄量・希求水準を確認してください。')
            one.append((d,b,max(0.,d-b)))
        data.append(one)

    n=len(data);m=2*n;theta_idx=m;z_start=m+1;v_count=m+1+n
    residual=[sum(data[i][c][2] for c in (0,1)) for i in range(n)]
    active=[i for i in range(n) if residual[i]>=delta-EPS]
    mandatory=[i for i in active if not visited[i]]
    budget=R*vehicle_capacity
    if not active:
        return dict(allocationsFoodKg=[0.]*n,allocationsWaterKg=[0.]*n,
                    objectiveF1=None,theta=None,usedFoodKg=0.,usedWaterKg=0.,
                    unusedTotalKg=total,vehicleBudgetKg=budget,
                    mandatoryCount=0,activeCount=0,microCount=sum(0<x<delta for x in residual),
                    minDeliveryKg=delta,remainingTrips=R,weight=weight,targetRate=target,
                    model='unified_two_commodity_p0',note='追加配分できる避難所がありません。')
    if len(mandatory)*delta>total+EPS:
        raise P0InputError('最低配送量の合計が、使える物資量を超えています。')
    if R*slots_per_round<len(mandatory):
        raise P0InputError('2t・4tトラックの台数・回数では、全避難所を訪問できません。')

    # 食料・飲料水の配送量、自由なθと施設別不足度を用いる。ρが正なので不足度変数は必要な値まで下がる。
    bounds=[]
    for i in range(n):
        for c in (0,1):
            remaining=data[i][c][2]
            bounds.append((0.,min(remaining,R*max_capacity) if i in active else 0.))
    bounds.append((None,None))
    bounds += [(None,None)]*n
    obj=[0.]*v_count;obj[theta_idx]=1.
    for i in range(n):obj[z_start+i]=rho
    A=[];upper=[]
    def add(terms,limit):
        line=[0.]*v_count
        for k,v in terms:line[k]=v
        A.append(line);upper.append(limit)
    # 両品目を一つの重量予算で管理し、配分量は最適化で決める。
    add([(j,1.) for j in range(m)],min(total,budget))
    for i in range(n):
        add([(2*i,1.),(2*i+1,1.)],min(residual[i],R*max_capacity) if i in active else 0.)
    for i in mandatory:
        add([(2*i,-1.),(2*i+1,-1.)],-delta)
    for i in range(n):
        # 品目ごとに目標に対する正規化不足度の制約を課す。
        for c in (0,1):
            d,b,_=data[i][c]
            add([(2*i+c,-weight/d),(z_start+i,-1.)],-weight*(target-b/d))
        if i in active:
            add([(z_start+i,1.),(theta_idx,-1.)],0.)

    sol=linprog(obj,A_ub=A,b_ub=upper,bounds=bounds,method='highs',
        options={'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
    if not sol.success:
        raise P0InputError('配分量を計算できませんでした。物資量・車両数・最小配送量を確認してください。')
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
    gaps=[weight*(target-rate) for rate in rates]
    theta=max(gaps[i] for i in active)
    f1=theta+rho*sum(gaps)
    if (sum(food)+sum(water)>min(total,budget)+1e-5
        or any(food[i]+water[i]<delta-1e-5 for i in mandatory)):
        raise P0InputError('配分結果が物資量または配送能力を超えています。')
    return dict(allocationsFoodKg=food,allocationsWaterKg=water,
                objectiveF1=f1,theta=theta,weight=weight,targetRate=target,
                combinedRates=rates,usedFoodKg=sum(food),usedWaterKg=sum(water),
                unusedTotalKg=max(0.,total-sum(food)-sum(water)),
                vehicleBudgetKg=budget,mandatoryCount=len(mandatory),activeCount=len(active),
                microCount=sum(0<x<delta for x in residual),minDeliveryKg=delta,
                remainingTrips=R,model='unified_two_commodity_p0',note=None)
