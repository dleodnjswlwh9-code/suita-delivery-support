"""P0: operational allocation feasibility gap for the current *pooled-hub* P1.

Uses a single shared inventory/vehicle pool, **not** certified north/south hub
stocks, roads, real travel time, or P2 routes. F1 is exactly the joint food/water
scalarization used by p1_full_constraints.py. A binary visit and continuous
commodity amounts are assigned for each truck and delivery round. P0 is a MILP.

The initial shelter stock is the model's baseline coverage, NOT evidence that a
vehicle already visited: when no actual visit history is supplied, every shelter
with >= delta residual demand is a mandatory first visit.
"""
from __future__ import annotations
import math
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix
from p1_full_constraints import optimize_joint_p1
from p1_optimizer import P1InputError

CAPACITY = 2000.0


def optimize_p0(food_rows, water_rows, total_kg, rho, delta, rounds, trucks, target_rate,
                *, time_limit=20.0):
    # The identical P1 implementation supplies the ideal scalarization value.
    # All shelters start unvisited unless actual visit records become available.
    if not isinstance(food_rows, list) or not isinstance(water_rows, list):
        raise P1InputError('P0の食料・飲料水データを確認してください。')
    if len(food_rows) > 200:
        raise P1InputError('P0の対象避難所は200か所以下にしてください。')
    try:
        R=int(rounds); T=int(trucks); delta=float(delta); total=float(total_kg)
        rho=float(rho); target=float(target_rate)
    except (TypeError, ValueError, OverflowError):
        raise P1InputError('P0の車両・回数・物資量を確認してください。')
    if R>12 or T>20 or len(food_rows)*R*T>2500:
        raise P1InputError('現在のP0計算上限（避難所×台数×回数 ≤ 2500、台数 ≤ 20、回数 ≤ 12）を超えています。')
    frows = [dict(r, visited=bool(r.get('visited',False))) for r in food_rows]
    wrows = [dict(r, visited=bool(r.get('visited',False))) for r in water_rows]
    base = optimize_joint_p1(frows,wrows,total,rho,delta,R,[{'capacityKg':CAPACITY,'count':T}],target)
    n=len(frows)
    if base['objectiveF1'] is None:
        return dict(status='no_remaining_demand',optimal=True,objectiveP1=None,objectiveP0=None,
                    gapEta=None,totalFoodKg=0.,totalWaterKg=0.,rows=[],roundAssignments=[],
                    mandatoryCount=0,visitedShelters=0,note='追加配送可能な避難所がありません。',
                    verifiedScope='pooled_vehicle_allocation_only')
    D=np.zeros((n,2)); B=np.zeros((n,2)); V=[]
    for i,(f,w) in enumerate(zip(frows,wrows)):
        if bool(f['visited'])!=bool(w['visited']):
            raise P1InputError(f'{i+1}番の訪問履歴が一致しません。')
        V.append(bool(f['visited']))
        for c,r in enumerate((f,w)):
            D[i,c]=float(r['demandKg']);B[i,c]=float(r['securedKg'])
    rest=np.maximum(D-B,0.)
    residual=rest.sum(axis=1)
    active=[i for i in range(n) if residual[i]>=delta-1e-8]
    mandatory=[i for i in active if not V[i]]
    slots=T*R
    x_count=n*2*slots
    y_base=x_count; y_count=n*slots
    v_base=y_base+y_count; u_base=v_base+slots
    theta_index=u_base+R; z_base=theta_index+1; N=z_base+n
    def si(t,r):return r*T+t
    def xi(i,c,s):return (i*2+c)*slots+s
    def yi(i,s):return y_base+i*slots+s
    def vi(s):return v_base+s
    def ui(r):return u_base+r
    lower=np.zeros(N);upper=np.full(N,np.inf); integ=np.zeros(N,dtype=np.intc)
    # z and theta may be negative when aspiration is exceeded.
    lower[theta_index]=-np.inf;lower[z_base:]=-np.inf
    for i in range(n):
        for c in (0,1):
            for s in range(slots): upper[xi(i,c,s)]=min(CAPACITY,rest[i,c]) if i in active else 0.
        for s in range(slots):
            j=yi(i,s);upper[j]=1. if i in active else 0.;integ[j]=1
    upper[v_base:u_base]=1.;integ[v_base:u_base]=1
    upper[u_base:theta_index]=1.;integ[u_base:theta_index]=1
    objective=np.zeros(N);objective[theta_index]=1.;objective[z_base:]=rho
    ri=[];ci=[];vv=[];lhs=[];rhs=[]
    def row(terms,low=-np.inf,high=np.inf):
        k=len(lhs);lhs.append(low);rhs.append(high)
        for col,val in terms:
            if val:ri.append(k);ci.append(col);vv.append(val)
    # Available aggregate stock and each good/shelter residual upper limits.
    row([(xi(i,c,s),1.) for i in range(n) for c in (0,1) for s in range(slots)],high=total)
    for i in range(n):
        for c in (0,1):row([(xi(i,c,s),1.) for s in range(slots)], high=rest[i,c])
        # Any mandatory shelter must be visited at least once during remaining rounds.
        if i in mandatory:row([(yi(i,s),1.) for s in range(slots)],low=1.)
        for r in range(R):
            # One truck only per shelter and delivery round.
            row([(yi(i,si(t,r)),1.) for t in range(T)],high=1.)
        for s in range(slots):
            shipment=[(xi(i,c,s),1.) for c in (0,1)]
            # delta*y <= food+water <= min(2000, residual)*y.
            row(shipment+[(yi(i,s),-delta)],low=0.)
            row(shipment+[(yi(i,s),-min(CAPACITY,residual[i]))],high=0.)
            # A visit requires dispatch of its assigned truck.
            row([(yi(i,s),1.),(vi(s),-1.)],high=0.)
    for r in range(R):
        for t in range(T):
            s=si(t,r)
            row([(xi(i,c,s),1.) for i in range(n) for c in (0,1)]+[(vi(s),-CAPACITY)],high=0.)
            row([(vi(s),1.),(ui(r),-1.)],high=0.)
            # A dispatched vehicle must visit at least one shelter; basic P0 reduced (39).
            row([(vi(s),1.)]+[(yi(i,s),-1.) for i in range(n)],high=0.)
        row([(ui(r),1.)]+[(vi(si(t,r)),-1.) for t in range(T)],high=0.)
        if r<R-1:row([(ui(r+1),1.),(ui(r),-1.)],high=0.)
    row([(ui(0),1.)],low=1.)
    # Symmetry reduction for homogeneous trucks.
    for r in range(R):
        for t in range(T-1):row([(vi(si(t+1,r)),1.),(vi(si(t,r)),-1.)],high=0.)
    # Exactly the joint two-good P1 scalarization: z=max(g_food,g_water).
    wgt=1./(1.-target)
    for i in range(n):
        for c in (0,1):
            # z_i >= weight * (target - (baseline+delivery)/d)
            terms=[(z_base+i,1.)]+[(xi(i,c,s),wgt/D[i,c]) for s in range(slots)]
            row(terms,low=wgt*(target-B[i,c]/D[i,c]))
        if i in active:row([(theta_index,1.),(z_base+i,-1.)],low=0.)
    A=coo_matrix((vv,(ri,ci)),shape=(len(lhs),N)).tocsr()
    sol=milp(c=objective,integrality=integ,bounds=Bounds(lower,upper),
             constraints=LinearConstraint(A,np.asarray(lhs),np.asarray(rhs)),
             options={'time_limit':float(time_limit),'mip_rel_gap':1e-4,'presolve':True})
    if sol.x is None:
        raise P1InputError('P0の実行可能な割当を確認できませんでした。車両数・回数・物資総量を確認してください。'
                           + (' 計算時間内に解が見つからない場合もあります。' if sol.status==1 else ''))
    x=sol.x
    allocations=np.zeros((n,2));assignments=[];visited_set=set();used_rounds=set();used_trucks=set()
    for r in range(R):
        for t in range(T):
            s=si(t,r)
            if x[vi(s)]<.5:continue
            used_rounds.add(r+1);used_trucks.add(t+1)
            visits=[]
            for i in range(n):
                if x[yi(i,s)]>.5:
                    food=max(0.,float(x[xi(i,0,s)]));water=max(0.,float(x[xi(i,1,s)]))
                    allocations[i,0]+=food;allocations[i,1]+=water;visited_set.add(i)
                    visits.append(dict(index=i,foodKg=food,waterKg=water,totalKg=food+water))
            assignments.append(dict(round=r+1,truck=t+1,loadKg=sum(v['totalKg'] for v in visits),
                                    visits=visits))
    rates=np.min((B+allocations)/D,axis=1)
    gap_values=wgt*(target-rates)
    f1_p0=float(max(gap_values[i] for i in active)+rho*sum(gap_values))
    f1_p1=float(base['objectiveF1'])
    eta=f1_p0-f1_p1
    if eta < -1e-4 or np.any(allocations-rest>1e-5) or allocations.sum()>total+1e-4:
        raise P1InputError('P0計算結果の整合性を確認できませんでした。')
    # When solver stopped early, do not claim the minimum gap is certified.
    certified=(sol.status==0 and sol.mip_gap is not None and sol.mip_gap<=1.01e-4)
    rows=[dict(index=i,foodKg=float(allocations[i,0]),waterKg=float(allocations[i,1]),
               combinedRate=float(rates[i]),p1FoodKg=float(base['allocationsFoodKg'][i]),
               p1WaterKg=float(base['allocationsWaterKg'][i]),visited=bool(i in visited_set))
          for i in range(n)]
    return dict(status='optimal' if certified else 'feasible_unproven',optimal=certified,
                objectiveP1=f1_p1,objectiveP0=f1_p0,gapEta=max(0.,eta),
                totalFoodKg=float(allocations[:,0].sum()),totalWaterKg=float(allocations[:,1].sum()),
                rows=rows,roundAssignments=assignments,mandatoryCount=len(mandatory),
                visitedShelters=len(visited_set),usedRounds=len(used_rounds),usedTrucks=len(used_trucks),
                targetRate=target,rho=rho,deltaKg=delta,vehicleCapacityKg=CAPACITY,
                gapIsMinimum=certified,relativeMipGap=None if sol.mip_gap is None else float(sol.mip_gap),
                verifiedScope='pooled_vehicle_allocation_only',
                note='共通在庫・共通車両プールによるP0基本形。2拠点別在庫、道路、実際の移動時間は未検証。')
