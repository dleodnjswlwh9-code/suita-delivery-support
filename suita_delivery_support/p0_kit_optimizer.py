"""P0 (professor paper eq. 34--39), reduced operational MILP for the app's
single-commodity *integer complete-kit* extension with 2t/4t fleet.

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
    rows=clean['rows'];T=clean['trucks'];R=clean['rounds'];delta=clean['delta']
    capacities=[v['capacityKits'] for v in clean['fleet']]
    active=[i for i,row in enumerate(rows) if row['remaining']>=delta]
    mandatory=[i for i in active if not rows[i]['visited']]
    if not active:return active,mandatory,'終了：追加可能な残余需要なし'
    if not mandatory and all((r['stock']/r['demand']>=clean['a']-1e-9) for r in rows if r['demand']>0):
        return active,mandatory,'終了：全避難所が希求水準を達成（必須未訪問なし）'
    if clean['available']<delta:return active,mandatory,'一時停止：最小配送量未満の在庫'
    if not any(q>=delta for q in capacities):return active,mandatory,'一時停止：最小配送量を運べる車両がない'
    if clean['available']<delta*len(mandatory):
        return active,mandatory,'構造的実行不能：必須訪問分の在庫不足'
    if R*sum(q//delta for q in capacities)<len(mandatory):
        return active,mandatory,'構造的実行不能：必須訪問の車両枠不足'
    return active,mandatory,None


def _greedy_time_feasible_seed(c, base, common):
    """Conservative assignment seed for large MILPs that time out.

    Every route's 20km/h hub-star upper-bound, loading waves, stock and capacity
    is checked. Never reported as a proven MILP optimum or exact route-window
    feasibility. The visit-window earliest-finish test is only necessary.
    """
    from p2_kit_optimizer import HUBS
    from kit_planning import ROAD_SPEED_KMH,LOADING_MIN,PREP_MIN,UNLOADING_MIN_PER_KIT
    rows=c['rows'];T=c['trucks'];R=c['rounds'];delta=c['delta'];fleet=c['fleet'];N=len(rows)
    hs=c['hubStockKits'][:] if c.get('hubStockKits') is not None else [c['available'],c['available']]
    available=c['available'];left=[r['remaining'] for r in rows];used=[0]*N
    x=[[{} for _ in range(T)] for _ in range(R)]
    cap=[[v['capacityKits'] for v in fleet] for _ in range(R)]
    times=[[0. for _ in range(T)] for _ in range(R)]
    def hub(t):return fleet[t].get('hub',0)
    def km(i,t):
        h=HUBS[hub(t)];r=rows[i]
        return abs(r['lat']-h['lat'])*111.32+abs(r['lng']-h['lng'])*111.32*math.cos(math.radians((r['lat']+h['lat'])/2))
    def waves(r):
        if not any(x[r][t] for t in range(T)):return 0
        return max(math.ceil(sum(bool(x[r][t]) and hub(t)==h for t in range(T))/c['loadingParallel'][h]) for h in (0,1))
    def makespans():return [(max(times[r]) if T else 0)+LOADING_MIN*waves(r) for r in range(R)]
    def allowed():
        m=makespans();return (c['maxRoundMinutes'] is None or max(m)<=c['maxRoundMinutes']+1e-7) and (c['maxTotalMinutes'] is None or sum(m)<=c['maxTotalMinutes']+1e-7)
    def assign(i,r,t,q):
        if q<=0 or cap[r][t]<q or hs[hub(t)]<q or availableLeft[0]<q:return False
        if i in x[r][t]:added=False
        else:
            if any(i in x[r][tt] for tt in range(T)):return False
            if q<delta:return False
            window=c['visitWindows'].get(rows[i]['name'])
            if window and LOADING_MIN+km(i,t)/ROAD_SPEED_KMH*60+PREP_MIN+UNLOADING_MIN_PER_KIT*q>window[1]:return False
            added=True
        x[r][t][i]=x[r][t].get(i,0)+q
        cap[r][t]-=q;hs[hub(t)]-=q;availableLeft[0]-=q;left[i]-=q;used[i]+=q
        times[r][t]+=(PREP_MIN+2*km(i,t)/ROAD_SPEED_KMH*60 if added else 0)+UNLOADING_MIN_PER_KIT*q
        if not allowed():
            if added:del x[r][t][i]
            else:x[r][t][i]-=q
            cap[r][t]+=q;hs[hub(t)]+=q;availableLeft[0]+=q;left[i]+=q;used[i]-=q
            times[r][t]-=(PREP_MIN+2*km(i,t)/ROAD_SPEED_KMH*60 if added else 0)+UNLOADING_MIN_PER_KIT*q
            return False
        return True
    availableLeft=[available]
    mandatory=[i for i,v in enumerate(rows) if not v['visited'] and v['remaining']>=delta]
    # Harder distant shelters first, then earliest rounds and nearer hubs.
    mandatory.sort(key=lambda i:-min(km(i,t) for t in range(T)))
    for i in mandatory:
        candidates=sorted(((r,t) for r in range(R) for t in range(T)),
            key=lambda rt:(rt[0],times[rt[0]][rt[1]]+2*km(i,rt[1])/ROAD_SPEED_KMH*60,rt[1]))
        if not any(assign(i,r,t,delta) for r,t in candidates):return None
    # Increment all already-visited shelters toward the most under-supplied
    # normalized rate. Chunk size keeps O(100 shelters) realistic.
    for iteration in range(10000):
        candidates=[]
        for i,v in enumerate(rows):
            if left[i]<=0:continue
            deficit=c['a']-(v['stock']+used[i])/v['demand']
            if deficit<=-0.01:continue
            for r in range(R):
                for t in range(T):
                    if i not in x[r][t]:continue
                    availableQty=min(left[i],cap[r][t],hs[hub(t)],availableLeft[0])
                    if availableQty>0:candidates.append((-deficit,r,t,i,availableQty))
        if not candidates:break
        _,r,t,i,q=min(candidates)
        # Increment 50 kits or less; never exceed the target coverage by much.
        target=math.ceil(max(1,c['a']*rows[i]['demand']-rows[i]['stock']-used[i]))
        q=min(q,max(1,min(50,target)))
        if not assign(i,r,t,q):
            # Avoid retrying a full-time route by setting its remaining capacity
            # to zero; this only affects the seed heuristic.
            cap[r][t]=0
    assignments=[]
    for r in range(R):
        for t in range(T):
            if not x[r][t]:continue
            assignments.append(dict(round=r+1,truck=t+1,visits=[dict(index=i,kits=q) for i,q in x[r][t].items()],
                loadKits=sum(x[r][t].values()),vehicleType=fleet[t]['type'],capacityKits=fleet[t]['capacityKits']))
    if not assignments or not any(a['round']==1 for a in assignments):return None
    f1=f1_score(rows,used,c['a'],c['rho'],c['delta']);gap=max(0.,f1-base['f1'])
    return dict(common,status='heuristic_feasible_upper_bound',feasible=True,certified=False,
        certifiedConservativeBound=False,etaStar=None,etaUpperBound=gap,etaLowerBound=None,
        f1Feasible=f1,assignment=assignments,plannedAdditions=used,vehiclesUsed=len(assignments),totalKits=sum(used),
        reason='MILP探索で解を確定できず、安全側の配送時間条件を満たす参考配分を作成。最適性未証明。')


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
    n=len(c['rows']);T=c['trucks'];R=c['rounds'];slots=T*R
    capacities=[v['capacityKits'] for v in c['fleet']]
    delta=c['delta'];a=c['a'];rho=c['rho'];w=1/(1-a)
    active,mandatory,problem=_preflight(c,base)
    has_extra=any((c.get('hubStockKits') is not None,c.get('maxRoundMinutes') is not None,c.get('maxTotalMinutes') is not None,bool(c.get('visitWindows'))))
    common=dict(model=P0_MODEL_NAME,scope=('hub-stock-and-conservative-time-screen' if has_extra else 'pooled-kit-assignment-basic'),
                minDeliveryKg=float((payload or {}).get('p0MinimumKg',delta*KIT_KG)),
                minDeliveryInterpretation='integer_4.5kg_complete_kits_ceiling',
                effectiveMinKg=float(delta*KIT_KG),
                f1Star=base['f1'],mandatoryCount=len(mandatory),activeCount=len(active),
                vehicleCapacityKits=max(capacities),fleet=c['fleet'],truckCount=T,maxRounds=R,deltaKits=delta,
                availableKits=c['available'],requiredMinimumKits=delta*len(mandatory),
                totalPossibleVisitSlots=R*sum(q//delta for q in capacities),
                timeLimitSec=time_limit,mipGapPercent=gap_percent,
                hubStockKits=c.get('hubStockKits'),maxRoundMinutes=c.get('maxRoundMinutes'),maxTotalMinutes=c.get('maxTotalMinutes'),loadingParallel=c.get('loadingParallel'),visitWindowsCount=len(c.get('visitWindows') or {}),
                limitations=['道路・時間窓を含む完全な経路MILPではなく、安全側の往復上界による時間検証。P2は生成経路で再検証',
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
    use_time=c.get('maxRoundMinutes') is not None or c.get('maxTotalMinutes') is not None
    h0=N if use_time else None
    lam0=(N+R) if use_time else None
    if use_time:N+=R*2
    def xx(i,s):return x0+i*slots+s
    def yy(i,s):return y0+i*slots+s
    def vv(s):return v0+s
    def uu(r):return u0+r
    def slot(t,r):return r*T+t
    def capacity(s):return capacities[s%T]
    lo=np.zeros(N);hi=np.zeros(N);integ=np.ones(N,dtype=np.intc)
    lo[theta]=-np.inf;hi[theta]=np.inf;integ[theta]=0
    if use_time:
        for r in range(R):
            integ[h0+r]=0;hi[h0+r]=1000000
            hi[lam0+r]=T
    for i,row in enumerate(c['rows']):
        for s in range(slots):
            hi[xx(i,s)]=min(capacity(s),row['remaining']) if i in active else 0
            hi[yy(i,s)]=1 if i in active else 0
            # Necessary earliest-finish window test (not complete sequencing).
            window=c.get('visitWindows',{}).get(row['name'])
            if window and c['fleet'][s%T].get('hub') is not None:
                from p2_kit_optimizer import HUBS
                from kit_planning import LOADING_MIN,PREP_MIN,UNLOADING_MIN_PER_KIT,ROAD_SPEED_KMH
                h=HUBS[c['fleet'][s%T]['hub']]
                km=abs(row['lat']-h['lat'])*111.32+abs(row['lng']-h['lng'])*111.32*math.cos(math.radians((row['lat']+h['lat'])/2))
                if LOADING_MIN+km/ROAD_SPEED_KMH*60+PREP_MIN+UNLOADING_MIN_PER_KIT*delta>window[1]:
                    hi[xx(i,s)]=0;hi[yy(i,s)]=0
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
    if c.get('hubStockKits') is not None:
        for h in (0,1):
            add(((xx(i,s),1) for i in active for s in range(slots) if c['fleet'][s%T]['hub']==h),h=c['hubStockKits'][h])
    for i,row in enumerate(c['rows']):
        if i not in active:continue
        # Effective residual and upper bound (52), including at most R visits.
        add(((xx(i,s),1) for s in range(slots)),h=min(row['remaining'],R*max(capacities)))
        if i in mandatory:add(((yy(i,s),1) for s in range(slots)),l=1)
        for r in range(R):
            add(((yy(i,slot(t,r)),1) for t in range(T)),h=1)  # (58)
        for s in range(slots):
            add([(xx(i,s),1),(yy(i,s),-delta)],l=0)   # (55) lower
            add([(xx(i,s),1),(yy(i,s),-min(capacity(s),row['remaining']))],h=0) # (55) upper
            add([(yy(i,s),1),(vv(s),-1)],h=0)         # (57)
        # tight theta epigraph (46), same K+ as P1 (28)
        add([(theta,1)]+[(xx(i,s),w/row['demand']) for s in range(slots)],
            l=w*(a-row['stock']/row['demand']))
    for r in range(R):
        for t in range(T):
            s=slot(t,r)
            add([(xx(i,s),1) for i in active]+[(vv(s),-capacities[t])],h=0)    # (56)
            add([(vv(s),1),(uu(r),-1)],h=0)                # (59)
            add([(vv(s),1)]+[(yy(i,s),-1) for i in active],h=0) # (39)
        add([(uu(r),1)]+[(vv(slot(t,r)),-1) for t in range(T)],h=0) # (60)
        if r<R-1:add([(uu(r+1),1),(uu(r),-1)],h=0) # (61)
    add([(uu(0),1)],l=1) # (62): current round must be used
    # Symmetry removal (83) valid only for identical pooled vehicles.
    for r in range(R):
        for t in range(T-1):
            if capacities[t]==capacities[t+1]:
                add([(vv(slot(t+1,r)),1),(vv(slot(t,r)),-1)],h=0)
    if use_time:
        # For the fixed 20 km/h city-block metric, returning to the hub after
        # EACH shelter is an UPPER bound on the fastest actual tour duration.
        # Enforcing this upper bound is conservative (sufficient, not necessary).
        from p2_kit_optimizer import HUBS
        from kit_planning import ROAD_SPEED_KMH,LOADING_MIN,PREP_MIN,UNLOADING_MIN_PER_KIT
        for r in range(R):
            for h in (0,1):
                add([(lam0+r,-c['loadingParallel'][h])]+[(vv(slot(t,r)),1)
                    for t in range(T) if c['fleet'][t].get('hub')==h],h=0)
            add([(lam0+r,1)]+[(vv(slot(t,r)),-1) for t in range(T)],h=0)
            for t in range(T):
                s=slot(t,r);hub=c['fleet'][t].get('hub',0)
                terms=[(h0+r,1),(lam0+r,-LOADING_MIN)]
                for i in active:
                    shelter=c['rows'][i];hobj=HUBS[hub]
                    km=abs(shelter['lat']-hobj['lat'])*111.32 + abs(shelter['lng']-hobj['lng'])*111.32*math.cos(math.radians((shelter['lat']+hobj['lat'])/2))
                    terms.append((yy(i,s),-(PREP_MIN+2*km/ROAD_SPEED_KMH*60)))
                    terms.append((xx(i,s),-UNLOADING_MIN_PER_KIT))
                add(terms,l=0)
            if c.get('maxRoundMinutes') is not None:add([(h0+r,1)],h=c['maxRoundMinutes'])
        if c.get('maxTotalMinutes') is not None:add([(h0+r,1) for r in range(R)],h=c['maxTotalMinutes'])
        # Custom shelter windows are checked against actual P2 visit order.
        # They are NOT an exact time-window MILP and are not certified as such.
    A=coo_matrix((value,(rr,cc)),shape=(len(low),N)).tocsr()
    try:
        sol=milp(c=co,integrality=integ,bounds=Bounds(lo,hi),
            constraints=LinearConstraint(A,np.asarray(low),np.asarray(high)),
            options={'time_limit':float(time_limit),'mip_rel_gap':relative_gap,'presolve':True})
    except Exception as e:
        return dict(common,status='solver_error',feasible=False,certified=False,etaStar=None,
                    etaUpperBound=None,etaLowerBound=None,assignment=[],reason=str(e)[:180])
    if sol.x is None:
        if sol.status!=2 and use_time and c.get('hubStockKits') is not None:
            seed=_greedy_time_feasible_seed(c,base,common)
            if seed is not None:return seed
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
                                       loadKits=sum(v['kits'] for v in visits),
                                       vehicleType=c['fleet'][t]['type'],capacityKits=capacities[t]))
    # Independent recheck on the rounded app-specific integer plan.
    if (any(v['kits']<delta for a0 in assignment for v in a0['visits'])
        or any(a0['loadKits']>capacities[a0['truck']-1] for a0 in assignment)
        or any(additions[i]>c['rows'][i]['remaining'] for i in range(n))
        or sum(additions)>c['available']
        or any(additions[i]<delta for i in mandatory)
        or not any(a0['round']==1 for a0 in assignment)
        or any(len({v['index'] for a0 in assignment if a0['round']==r for v in a0['visits']}) !=
               sum(len(a0['visits']) for a0 in assignment if a0['round']==r) for r in range(1,R+1))):
        return dict(common,status='incumbent_validation_failed',feasible=False,certified=False,
                    etaStar=None,etaUpperBound=None,etaLowerBound=None,assignment=[],
                    reason='最小配送量、訪問保証または車両容量の検証に失敗しました。')
    if c.get('hubStockKits') is not None:
        if any(sum(a0['loadKits'] for a0 in assignment if c['fleet'][a0['truck']-1]['hub']==h)>c['hubStockKits'][h] for h in (0,1)):
            raise KitInputError('拠点別の在庫制約を満たさない計算結果です。')
    f1=f1_score(c['rows'],additions,a,rho,delta)
    eta_upper=max(0.,float(f1-base['f1']))
    dual=getattr(sol,'mip_dual_bound',None)
    constant=rho*sum(w*(a-r['stock']/r['demand']) for r in c['rows'] if r['demand']>0)
    eta_lower=(max(0.,float(dual)+constant-base['f1'])
               if dual is not None and math.isfinite(float(dual)) else None)
    mipgap=getattr(sol,'mip_gap',None)
    certified=bool(sol.status==0 and mipgap is not None and math.isfinite(float(mipgap)) and float(mipgap)<=relative_gap+1e-7)
    return dict(common,status='optimal_with_tolerance' if certified else 'feasible_upper_bound',
        feasible=True,certified=(certified and not use_time and not c.get('visitWindows')),etaStar=eta_upper if certified and not use_time and not c.get('visitWindows') else None,
        certifiedConservativeBound=bool(certified and use_time),
        etaUpperBound=eta_upper,etaLowerBound=(None if use_time or c.get('visitWindows') else eta_lower),
        f1Feasible=float(f1),assignment=assignment,plannedAdditions=additions,
        mipRelativeGap=float(mipgap) if mipgap is not None else None,
        solverStatus=int(sol.status),vehiclesUsed=used,totalKits=sum(additions),
        reason=('経路上界による時間条件を満たす実行可能案。訪問時間帯はP2で最終確認。最適性は未証明。' if use_time or c.get('visitWindows') else
                'MILPの指定許容誤差内で最小実装可能性ギャップを確認。' if certified else
                '実行可能な上界のみ。最小ギャップη*は未証明。'))
