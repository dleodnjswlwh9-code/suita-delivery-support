"""P0 (professor paper eq. 34--39), reduced operational MILP for the app's
single-commodity *integer complete-kit* extension.

P1 and P0 share exactly kit_planning.f1_score / solve_p1 and the SAME input
snapshot. This is a basic, pooled-inventory / pooled-vehicle model: road arcs,
per-hub vehicle and commodity stocks, traffic closures, time windows, loading
parallelism and round/cumulative time limits are NOT in the feasible set.
P0's incumbent gives a valid feasible F1 upper bound, but is not called eta* until
MIP optimality is certified within solver tolerance. Integer kits are an app-
specific strengthening of the paper's continuous shipment x variables.
"""
from __future__ import annotations
import math
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix
from kit_planning import (clean_input, solve_p1, f1_score, KitInputError,
                          TRUCK_CAP_KITS, KIT_KG)

MAX_ASSIGNMENT_CELLS = 12500
P0_MODEL_NAME = 'basic-pooled-integer-kit-p0'


def _preflight(clean, p1):
    rows=clean['rows'];T=clean['trucks'];R=clean['rounds'];q=TRUCK_CAP_KITS;delta=clean['delta']
    active=[i for i,row in enumerate(rows) if row['remaining']>=delta]
    mandatory=[i for i in active if not rows[i]['visited']]
    if not active:return active,mandatory,'終了：追加可能な残余需要なし'
    if not mandatory and all((r['stock']/r['demand']>=clean['a']-1e-9) for r in rows if r['demand']>0):
        return active,mandatory,'終了：全避難所が希求水準を達成（必須未訪問なし）'
    if clean['available']<delta:return active,mandatory,'一時停止：最小配送量未満の在庫'
    if q<delta:return active,mandatory,'一時停止：最小配送量を運べる車両がない'
    if clean['available']<delta*len(mandatory):
        return active,mandatory,'構造的実行不能：必須訪問分の在庫不足'
    if R*T*(q//delta)<len(mandatory):
        return active,mandatory,'構造的実行不能：必須訪問の車両枠不足'
    return active,mandatory,None


def optimize_p0_kits(payload, *, time_limit=None, relative_gap=None, clean=None, p1=None):
    # Both /api/p0-optimize and /api/p2-kits must honor the saved P0 controls.
    # Do not allow unlimited solver time through unvalidated user input.
    try:
        time_limit=float((payload or {}).get('p0TimeLimitSec',60) if time_limit is None else time_limit)
        gap_percent=float((payload or {}).get('p0MipGapPercent',0.2) if relative_gap is None else 100*relative_gap)
    except (TypeError,ValueError,OverflowError):
        raise KitInputError('P0計算時間・許容ギャップを確認してください。')
    if not math.isfinite(time_limit) or not 5<=time_limit<=60 or not math.isfinite(gap_percent) or not 0.1<=gap_percent<=10:
        raise KitInputError('P0計算時間は5～60秒、最適性許容ギャップは0.1～10%です。')
    relative_gap=gap_percent/100.0
    c=clean if clean is not None else clean_input(payload)
    base=p1 if p1 is not None else solve_p1(c)
    n=len(c['rows']);T=c['trucks'];R=c['rounds'];slots=T*R;Q=TRUCK_CAP_KITS
    delta=c['delta'];a=c['a'];rho=c['rho'];w=1/(1-a)
    active,mandatory,problem=_preflight(c,base)
    common=dict(model=P0_MODEL_NAME,scope='pooled-kit-assignment-basic-no-road-or-hub-stock',
                minDeliveryKg=float((payload or {}).get('p0MinimumKg',delta*KIT_KG)),
                minDeliveryInterpretation='integer_4.5kg_complete_kits_ceiling',
                effectiveMinKg=float(delta*KIT_KG),
                f1Star=base['f1'],mandatoryCount=len(mandatory),activeCount=len(active),
                vehicleCapacityKits=Q,truckCount=T,maxRounds=R,deltaKits=delta,
                availableKits=c['available'],requiredMinimumKits=delta*len(mandatory),
                totalPossibleVisitSlots=R*T*(Q//delta),
                timeLimitSec=time_limit,mipGapPercent=gap_percent,
                limitations=['2拠点別実在庫・拠点別車両・通行不能・時間上限・道路経路・時間窓は未検証',
                             '教授論文の連続量xに対し、本アプリは完成キットの整数配送量xを採用',
                             '最大配送回数Rmaxと最小量δはP1・P0・P2で共通、現在回はh=1のみ',
                             '原論文の品目ごとの需要・車両への詳細な配送弧／積込時間制約は実装していない'])
    if problem:
        return dict(common,status='stopped' if '終了' in problem or '一時停止' in problem else 'precheck_infeasible',
                    reason=problem,feasible=False,certified=False,etaStar=None,
                    etaUpperBound=None,etaLowerBound=None,assignment=[])
    if n*slots>MAX_ASSIGNMENT_CELLS:
        return dict(common,status='not_solved',feasible=False,certified=False,etaStar=None,
                    etaUpperBound=None,etaLowerBound=None,assignment=[],
                    reason=f'計算量上限：避難所×車両×配送回={n*slots} > {MAX_ASSIGNMENT_CELLS}。条件を縮小してください。')
    # Variables x_iks (integer complete kits), y_iks (binary visits),
    # v_s (binary dispatch), u_r (binary used round), unrestricted theta.
    x0=0;y0=n*slots;v0=2*n*slots;u0=v0+slots;theta=u0+R;N=theta+1
    def xx(i,s):return x0+i*slots+s
    def yy(i,s):return y0+i*slots+s
    def vv(s):return v0+s
    def uu(r):return u0+r
    def slot(t,r):return r*T+t
    lo=np.zeros(N);hi=np.zeros(N);integ=np.ones(N,dtype=np.intc)
    lo[theta]=-np.inf;hi[theta]=np.inf;integ[theta]=0
    for i,row in enumerate(c['rows']):
        for s in range(slots):
            hi[xx(i,s)]=min(Q,row['remaining']) if i in active else 0
            hi[yy(i,s)]=1 if i in active else 0
    hi[v0:u0]=1;hi[u0:theta]=1
    co=np.zeros(N);co[theta]=1
    for i,row in enumerate(c['rows']):
        if row['demand']>0:
            for s in range(slots):co[xx(i,s)]=-rho*w/row['demand']
    rr=[];cc=[];value=[];low=[];high=[]
    def add(terms,l=-np.inf,h=np.inf):
        j=len(low);low.append(l);high.append(h)
        for col,val in terms:
            if val:rr.append(j);cc.append(col);value.append(float(val))
    # Shared stock (53): necessary for the full two-depot formulation, not
    # proof of either individual depot's stock availability.
    add(((xx(i,s),1) for i in active for s in range(slots)),h=c['available'])
    for i,row in enumerate(c['rows']):
        if i not in active:continue
        # Effective residual and upper bound (52), including at most R visits.
        add(((xx(i,s),1) for s in range(slots)),h=min(row['remaining'],R*Q))
        if i in mandatory:add(((yy(i,s),1) for s in range(slots)),l=1)
        for r in range(R):
            add(((yy(i,slot(t,r)),1) for t in range(T)),h=1)  # (58)
        for s in range(slots):
            add([(xx(i,s),1),(yy(i,s),-delta)],l=0)   # (55) lower
            add([(xx(i,s),1),(yy(i,s),-min(Q,row['remaining']))],h=0) # (55) upper
            add([(yy(i,s),1),(vv(s),-1)],h=0)         # (57)
        # tight theta epigraph (46), same K+ as P1 (28)
        add([(theta,1)]+[(xx(i,s),w/row['demand']) for s in range(slots)],
            l=w*(a-row['stock']/row['demand']))
    for r in range(R):
        for t in range(T):
            s=slot(t,r)
            add([(xx(i,s),1) for i in active]+[(vv(s),-Q)],h=0)    # (56)
            add([(vv(s),1),(uu(r),-1)],h=0)                # (59)
            add([(vv(s),1)]+[(yy(i,s),-1) for i in active],h=0) # (39)
        add([(uu(r),1)]+[(vv(slot(t,r)),-1) for t in range(T)],h=0) # (60)
        if r<R-1:add([(uu(r+1),1),(uu(r),-1)],h=0) # (61)
    add([(uu(0),1)],l=1) # (62): current round must be used
    # Symmetry removal (83) valid only for identical pooled vehicles.
    for r in range(R):
        for t in range(T-1):
            add([(vv(slot(t+1,r)),1),(vv(slot(t,r)),-1)],h=0)
    A=coo_matrix((value,(rr,cc)),shape=(len(low),N)).tocsr()
    try:
        sol=milp(c=co,integrality=integ,bounds=Bounds(lo,hi),
            constraints=LinearConstraint(A,np.asarray(low),np.asarray(high)),
            options={'time_limit':float(time_limit),'mip_rel_gap':relative_gap,'presolve':True})
    except Exception as e:
        return dict(common,status='solver_error',feasible=False,certified=False,etaStar=None,
                    etaUpperBound=None,etaLowerBound=None,assignment=[],reason=str(e)[:180])
    if sol.x is None:
        return dict(common,status='infeasible' if sol.status==2 else 'no_incumbent',feasible=False,certified=False,
                    etaStar=None,etaUpperBound=None,etaLowerBound=None,assignment=[],
                    solverStatus=int(sol.status),reason=('MILPが実行不能であることを証明しました。' if sol.status==2 else '計算時間内に実行可能解を確認できませんでした。'))
    X=sol.x;additions=[0]*n;assignment=[];used=0
    for r in range(R):
        for t in range(T):
            s=slot(t,r)
            if X[vv(s)]<.5:continue
            visits=[]
            for i in active:
                if X[yy(i,s)]>.5:
                    q=int(round(X[xx(i,s)]))
                    visits.append(dict(index=i,kits=q))
                    additions[i]+=q
            if visits:
                used+=1
                assignment.append(dict(round=r+1,truck=t+1,visits=visits,
                                       loadKits=sum(v['kits'] for v in visits)))
    # Independent recheck on the rounded app-specific integer plan.
    if (any(v['kits']<delta for a0 in assignment for v in a0['visits'])
        or any(a0['loadKits']>Q for a0 in assignment)
        or any(additions[i]>c['rows'][i]['remaining'] for i in range(n))
        or sum(additions)>c['available']
        or any(additions[i]<delta for i in mandatory)
        or not any(a0['round']==1 for a0 in assignment)
        or any(len({v['index'] for a0 in assignment if a0['round']==r for v in a0['visits']}) !=
               sum(len(a0['visits']) for a0 in assignment if a0['round']==r) for r in range(1,R+1))):
        return dict(common,status='incumbent_validation_failed',feasible=False,certified=False,
                    etaStar=None,etaUpperBound=None,etaLowerBound=None,assignment=[],
                    reason='最小配送量、訪問保証または車両容量の検証に失敗しました。')
    f1=f1_score(c['rows'],additions,a,rho,delta)
    eta_upper=max(0.,float(f1-base['f1']))
    dual=getattr(sol,'mip_dual_bound',None)
    constant=rho*sum(w*(a-r['stock']/r['demand']) for r in c['rows'] if r['demand']>0)
    eta_lower=(max(0.,float(dual)+constant-base['f1'])
               if dual is not None and math.isfinite(float(dual)) else None)
    mipgap=getattr(sol,'mip_gap',None)
    certified=bool(sol.status==0 and mipgap is not None and math.isfinite(float(mipgap)) and float(mipgap)<=relative_gap+1e-7)
    return dict(common,status='optimal_with_tolerance' if certified else 'feasible_upper_bound',
        feasible=True,certified=certified,etaStar=eta_upper if certified else None,
        etaUpperBound=eta_upper,etaLowerBound=eta_lower,
        f1Feasible=float(f1),assignment=assignment,plannedAdditions=additions,
        mipRelativeGap=float(mipgap) if mipgap is not None else None,
        solverStatus=int(sol.status),vehiclesUsed=used,totalKits=sum(additions),
        reason=('MILPの指定許容誤差内で最小実装可能性ギャップを確認。' if certified else
                '実行可能な上界のみ。最小ギャップη*は未証明。'))
