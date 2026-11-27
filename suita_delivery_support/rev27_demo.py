"""MATLAB rev27 6-shelter case: transparent Python reduced-model verification.

Source: new_モデル/rev27_matlab/rev27_example.m, README_step7.md,
latest user-provided scenario A-D screenshot. We solve P1/P0/P0′ using SciPy
LP/MILP and construct feasible visit routes; P2 is *heuristic*, not an exact
translation of rev27_solve_p2.m. Do NOT assert equality to MATLAB Pareto fronts.
This module has no Flask dependency and can be unit-tested offline.
"""
from __future__ import annotations
import math
import itertools
from functools import lru_cache
from typing import Any
import numpy as np
from scipy.optimize import linprog, milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix

K=6
COORDS=[(0,0),(2,1),(5,1),(1,4),(6,4),(2,7),(7,7)]
INITIAL_DEMAND=[30,20,10,10,10,10]
DEFAULT_GAMMA=[0.9,1.7,1.0,0.7,0.5,1.2]
VALID_SCENARIOS=['A','B','C','D']
VALID_METHODS=['keep','quantity','replan']
MIN_BOXES=1
MAX_TRUCKS=2
ROUND_LIMIT=3
BOX_UNIT=5 # material units per cardboard box, in MATLAB rev27; not 4.5kg Suita kit


def _safe_number(v,default,lower,upper):
    try:x=float(v if v is not None else default)
    except (ValueError,TypeError):raise ValueError('入力パラメータは数値で指定してください。')
    if not math.isfinite(x) or not lower<=x<=upper:raise ValueError('パラメータの範囲を確認してください。')
    return x


def state_factory(urgency=False,stock=40,target=.5,rho=1e-4):
    target=_safe_number(target,.5,.05,.95)
    rho=_safe_number(rho,1e-4,1e-7,.1)
    return {'demand':INITIAL_DEMAND.copy(),'received':[0]*K,
            'visited':[False]*K,'stock':int(stock),'target':target,'rho':rho,
            'gamma':DEFAULT_GAMMA.copy() if urgency else [1.0]*K,
            'truckCapacity':[10,10],'coords':list(COORDS),'roadFactor':1.,
            'roadSegment':[0,2], 'h':1}


def f1(state,additions=None):
    d=state['demand'];a=state['target'];rho=state['rho'];r=state['received']
    adds=additions or [0]*K
    g=[(a-(r[i]+adds[i])/d[i])/(1-a) for i in range(K)]
    active=[i for i in range(K) if d[i]-r[i]>=MIN_BOXES]
    theta=max((g[i] for i in active),default=0)
    return theta+rho*sum(g)


def lp_p1(state,rounds):
    d=state['demand'];received=state['received'];stock=state['stock']
    a=state['target'];rho=state['rho'];w=1/(1-a)
    active=[i for i in range(K) if d[i]-received[i]>=1]
    if not active:return {'f1star':f1(state), 'added':[0]*K,'status':'no_demand'}
    max_supply=min(stock,rounds*sum(state['truckCapacity']))
    bounds=[]
    for i in range(K):
        lo=1. if i in active and not state['visited'][i] else 0.
        hi=float(d[i]-received[i]) if i in active else 0.
        if lo>hi:raise ValueError('必須訪問に必要な最低需要がありません。')
        bounds.append((lo,hi))
    bounds.append((None,None))
    coeff=[-rho*w/d[i] for i in range(K)]+[1.]
    A=[[1.]*K+[0.]];b=[max_supply]
    for i in active:
        z=[0.]*(K+1);z[i]=-w/d[i];z[-1]=-1.
        A.append(z);b.append(-w*(a-received[i]/d[i]))
    sol=linprog(coeff,A_ub=np.asarray(A),b_ub=np.asarray(b),bounds=bounds,method='highs')
    if not sol.success:raise ValueError('P1の線形計画が実行不能です：'+str(sol.message))
    adds=sol.x[:K].tolist()
    # Compute score from original formulas, not just the objective's transformed constant.
    return {'f1star':f1(state,adds),'added':[round(x,4) for x in adds],
            'status':'optimal_lp'}


def _model(state,rounds,goal,fairness_cap=None,time_limit=8):
    """MATLAB rev27_p0_model.m reduced basic P0/P0′, unit=integer box.

    Variables n[k,t,r],y[k,t,r],v[t,r],u[r],theta. Current round used.
    The original P2 edge/routing variables are intentionally not here.
    """
    if rounds<1 or rounds>ROUND_LIMIT:raise ValueError('配送回数は1～3回です。')
    d=state['demand'];sh=state['received'];a=state['target'];rho=state['rho'];w=1/(1-a)
    cap=state['truckCapacity'];T=len(cap);J=T*rounds
    active=[k for k in range(K) if d[k]-sh[k]>=1]
    req=[k for k in active if not state['visited'][k]]
    x0=0;y0=K*J;v0=2*K*J;u0=v0+J;th=u0+rounds;N=th+1
    def xx(k,j):return x0+k*J+j
    def yy(k,j):return y0+k*J+j
    def vv(j):return v0+j
    def uu(r):return u0+r
    lo=np.zeros(N);hi=np.zeros(N);integral=np.ones(N,dtype=np.intc)
    lo[th]=-np.inf;hi[th]=np.inf;integral[th]=0
    hi[v0:u0]=1;hi[u0:th]=1
    for k in range(K):
        for j in range(J):
            hi[xx(k,j)]=min(cap[j%T],d[k]-sh[k]) if k in active else 0
            hi[yy(k,j)]=1 if k in active else 0
    obj=np.zeros(N)
    if goal=='f1':
        obj[th]=1
        for k in range(K):
            for j in range(J):obj[xx(k,j)]=-rho*w/d[k]
    elif goal=='quantity':
        for k in range(K):
            for j in range(J):obj[xx(k,j)]=-1
    else:raise ValueError('未知の最適化目的')
    rr=[];cc=[];vvv=[];lower=[];upper=[]
    def add(terms,l=-np.inf,h=np.inf):
        row=len(lower);lower.append(l);upper.append(h)
        for col,val in terms:
            if val:rr.append(row);cc.append(col);vvv.append(float(val))
    add(((xx(k,j),1) for k in active for j in range(J)),h=state['stock'])
    for k in active:
        add([(xx(k,j),1) for j in range(J)],h=d[k]-sh[k])
        if k in req:add(((yy(k,j),1) for j in range(J)),l=1)
        for r in range(rounds):
            add([(yy(k,r*T+t),1) for t in range(T)],h=1)
        for j in range(J):
            add([(xx(k,j),1),(yy(k,j),-1)],l=0)
            add([(xx(k,j),1),(yy(k,j),-min(cap[j%T],d[k]-sh[k]))],h=0)
            add([(yy(k,j),1),(vv(j),-1)],h=0)
        add([(th,1)]+[(xx(k,j),w/d[k]) for j in range(J)],l=w*(a-sh[k]/d[k]))
    for r in range(rounds):
        for t in range(T):
            j=r*T+t
            add([(xx(k,j),1) for k in active]+[(vv(j),-cap[t])],h=0)
            add([(vv(j),1),(uu(r),-1)],h=0)
            add([(vv(j),1)]+[(yy(k,j),-1) for k in active],h=0)
        add([(uu(r),1)]+[(vv(r*T+t),-1) for t in range(T)],h=0)
        if r+1<rounds:add([(uu(r+1),1),(uu(r),-1)],h=0)
    add([(uu(0),1)],l=1)
    if goal=='quantity':
        const=rho*sum(w*(a-sh[k]/d[k]) for k in range(K))
        add([(th,1.)]+[(xx(k,j),-rho*w/d[k]) for k in active for j in range(J)],
            h=fairness_cap-const+1e-8)
    A=coo_matrix((vvv,(rr,cc)),shape=(len(lower),N)).tocsr()
    sol=milp(c=obj,integrality=integral,bounds=Bounds(lo,hi),
             constraints=LinearConstraint(A,np.asarray(lower),np.asarray(upper)),
             options={'time_limit':time_limit,'mip_rel_gap':0.000001,'presolve':True})
    if sol.x is None:raise ValueError('P0/P0′の整数計画に実行可能解がありません：'+str(sol.message))
    assign=[];adds=[0]*K
    for r in range(rounds):
        wave=[]
        for t in range(T):
            j=r*T+t
            a0={k:int(round(sol.x[xx(k,j)])) for k in active if sol.x[xx(k,j)]>.5}
            assert sum(a0.values())<=cap[t]
            wave.append(a0)
            for k,q in a0.items():adds[k]+=q
        assign.append(wave)
    if sum(adds)>state['stock'] or any(adds[k]+sh[k]>d[k] for k in range(K)):
        raise RuntimeError('受領量の再計算に失敗')
    if goal=='quantity' and f1(state,adds)>fairness_cap+5e-6:
        raise RuntimeError('P0′の公平性許容条件違反')
    return {'adds':adds,'assignment':assign,'f1':f1(state,adds),
            'total':sum(adds),'certified':sol.status==0,
            'solverStatus':int(sol.status),'dualBound':(float(sol.mip_dual_bound) if getattr(sol,'mip_dual_bound',None) is not None else None)}


def optimize(state,remaining=3,delta=0.0,sec=8):
    ideal=lp_p1(state,remaining)
    p0=_model(state,remaining,'f1',time_limit=sec)
    cap=p0['f1']+delta
    if p0['total']==min(state['stock'],sum(max(0,state['demand'][i]-state['received'][i]) for i in range(K)),
                        remaining*sum(state['truckCapacity'])):
        prime=p0.copy();prime['source']='upper_bound_reached'
    else:
        prime=_model(state,remaining,'quantity',fairness_cap=cap,time_limit=sec)
        prime['source']='MILP'
    return {'p1':ideal,'p0':p0,'p0prime':prime,'cap':cap,'etaUpper':p0['f1']-ideal['f1star'],
            'delta':delta,'rounds':remaining,'allCertified':bool(p0['certified'] and prime['certified'])}


def route_length(stops,road_factor=1.):
    if not stops:return 0.
    locations=[0]+list(stops)+[0]
    total=0.
    for i,j in zip(locations,locations[1:]):
        xy1=COORDS[i];xy2=COORDS[j]
        minutes=2*(abs(xy1[0]-xy2[0])+abs(xy1[1]-xy2[1]))
        if {i,j}=={0,2}:minutes*=road_factor # scenario D: chosen edge 0 <-> shelter 2
        total+=minutes
    return total


@lru_cache(maxsize=1024)
def optimal_tour(keys,road_factor):
    if not keys:return [],0.
    # At most 6 shelters; exact TSP permutation for each fixed truck assignment.
    variants=itertools.permutations(keys)
    route=min(variants,key=lambda t:route_length(t,road_factor))
    return list(route),route_length(route,road_factor)


def inspect_plan(state,assignment, *, horizon=3):
    received=list(state['received']);w=1/(1-state['target']);rounds=[];f3=0.;elapsed=0.
    for r,wave in enumerate(assignment):
        visit_rows=[];times=[]
        for t,quantities in enumerate(wave):
            active=tuple(sorted(k+1 for k,q in quantities.items() if q>0))
            path,travel=optimal_tour(active,float(state['roadFactor']))
            boxes=sum(quantities.values())
            duration=0 if boxes==0 else 5+travel+.5*boxes
            times.append(duration)
            visit_rows.append({'truck':t+1,'route':[0]+path+[0] if active else [],
                               'boxes':boxes,'delivery':[{'shelter':k+1,'boxes':int(quantities[k])} for k in range(K) if quantities.get(k,0)>0],
                               'minutes':round(duration,3)})
            for k,q in quantities.items():received[k]+=q
        makespan=max(times,default=0)
        elapsed+=makespan
        shortage=sum((state['gamma'][k]*w)*max(0,state['target']-received[k]/state['demand'][k]) for k in range(K))
        # Fixed evaluation horizon: do not evaluate shortage after the final candidate round.
        if r<horizon-1:f3+=shortage
        rounds.append({'round':state['h']+r,'minutes':round(makespan,3),
                       'f3Shortage':round(shortage,6),'trucks':visit_rows,
                       'cumulativeBoxes':sum(received),'coverage':[round(received[k]/state['demand'][k],4) for k in range(K)]})
    return {'f2':round(elapsed,4),'f3':round(f3,6),'rounds':rounds,'received':received,
            'added':sum(received)-sum(state['received'])}


def _fixed_quantities(state,remaining_assignment):
    """Refit integer quantities to *existing* visit locations and vehicle order.

    We keep previous per-slot stops, assign the additional stock to high shortages,
    and never invent new stops. Existing route order is preserved in comparisons.
    """
    out=[[dict(v) for v in wave] for wave in remaining_assignment]
    rem=state['stock']-sum(q for wave in out for tr in wave for q in tr.values())
    if rem<=0:return out
    for _ in range(rem):
        candidates=[]
        current=[0]*K
        for wave in out:
            for visits in wave:
                for k,q in visits.items():current[k]+=q
        for r,wave in enumerate(out):
            for t,visits in enumerate(wave):
                if sum(visits.values())>=state['truckCapacity'][t]:continue
                for k in visits:
                    if state['received'][k]+current[k]>=state['demand'][k]:continue
                    trial=current.copy();trial[k]+=1
                    weight=(state['target']-(state['received'][k]+current[k])/state['demand'][k])/state['demand'][k]
                    candidates.append((-weight,r,t,k))
        if not candidates:break
        _,r,t,k=min(candidates)
        out[r][t][k]+=1
    return out


def scenario_after_round(first_plan,scenario,base_state):
    nxt=dict(base_state)
    nxt['received']=list(base_state['received'])
    nxt['visited']=list(base_state['visited'])
    nxt['demand']=list(base_state['demand'])
    nxt['truckCapacity']=list(base_state['truckCapacity'])
    delivered=0
    for tr in first_plan:
        for k,q in tr.items():nxt['received'][k]+=q;nxt['visited'][k]=True;delivered+=q
    nxt['stock']=base_state['stock']-delivered
    nxt['h']=2
    if scenario=='B':nxt['stock']+=5
    if scenario=='C':nxt['demand'][1]+=5
    if scenario=='D':nxt['roadFactor']=1.5
    return nxt


def _evaluate_result(original,first,second,state_after,method,scenario,base):
    all_rounds=[first]+second
    # Always evaluate on the updated demand and updated travel metric.
    ref=dict(state_after,received=[0]*K)
    # Real initial conditions at first round were unchanged even in scenario D.
    first_metrics=inspect_plan(base,[first],horizon=3)
    remaining_metrics=inspect_plan(state_after,second,horizon=2)
    covered=list(remaining_metrics['received'])
    # For consistent F3 over three rounds evaluate all end-of-round shortages
    # using the UPDATED demand/urgency for C, same 3-round evaluation horizon.
    summation=inspect_plan(ref,all_rounds,horizon=3)
    rounds=summation['rounds']
    # First-round travel is computed with baseline road time; later rounds scenario road time.
    rounds[0]['minutes']=first_metrics['f2']
    for i,rr in enumerate(remaining_metrics['rounds'],1):
        rounds[i]['minutes']=rr['minutes']
        rounds[i]['trucks']=rr['trucks']
    f2=sum(rr['minutes'] for rr in rounds)
    f3=summation['f3']
    stock_final=max(0,int(state_after['stock']-sum(sum(q for tr in wave for q in tr.values()) for wave in second)))
    min_cov=min(covered[k]/state_after['demand'][k] for k in range(K))
    miss=sum(not (covered[k]>0) for k in range(K))
    return {'scenario':scenario,'method':method,'name':{'keep':'初期計画を維持','quantity':'訪問先・経路固定で数量のみ調整',
             'replan':'配送量・訪問先・経路を再計画'}[method],
            'f2':round(f2,3),'f3':round(f3,6),'totalDelivered':sum(covered),
            'stockFinal':stock_final,'minCoverage':round(min_cov,5),
            'unvisited':miss,'finalCoverage':[round(covered[k]/state_after['demand'][k],5) for k in range(K)],
            'coverageByRound':[r['coverage'] for r in rounds],
            'rounds':rounds,'updatedDemand':state_after['demand'],
            'candidateCertified':bool(original['allCertified']) if method=='keep' else False,
            'note':'P1・P0・P0′は縮約MILP。P2の経路は各車両内で厳密順序探索する近似計画。MATLABの厳密P2とは異なる。'}


def run_scenario(scenario='A', *, urgency=False,target=.5,rho=1e-4,delta=0.0):
    if scenario not in VALID_SCENARIOS:raise ValueError('シナリオはA～Dを指定してください。')
    delta=_safe_number(delta,0,0,.5)
    base=state_factory(urgency,target=target,rho=rho)
    original=optimize(base,3,delta=delta,sec=7)
    assignment=original['p0prime']['assignment']
    first=assignment[0]
    state_after=scenario_after_round(first,scenario,base)
    # ① Initial plan, no re-optimisation even when environment changes.
    keep=[[dict(x) for x in wave] for wave in assignment[1:]]
    # ② fixed visits and visit order, quantities may be adjusted within capacity.
    quantity=_fixed_quantities(state_after,keep)
    # ③ recalculate all remaining decisions from new state, may change visit sets.
    try:
        recalculated=optimize(state_after,2,delta=delta,sec=7)
        replan=recalculated['p0prime']['assignment']
        replan_status={'p1F1star':recalculated['p1']['f1star'],
                       'p0F1':recalculated['p0']['f1'],
                       'p0PrimeTotal':recalculated['p0prime']['total'],
                       'certifiedBasicMilp':recalculated['allCertified']}
    except Exception as exc:
        # DO NOT claim replanning worked. Return a readable error to the caller.
        raise ValueError('改訂モデルの再計画に失敗しました：'+str(exc)) from exc
    plans=[_evaluate_result(original,first,wave,state_after,mode,scenario,base)
           for mode,wave in [('keep',keep),('quantity',quantity),('replan',replan)]]
    return {'source':'rev27 6避難所説明例（SciPy簡易移植）',
            'scenario':scenario,'scenarioTitle':{'A':'変化なし','B':'追加補給（5箱）',
                  'C':'避難所2の需要増（20→25箱）','D':'道路移動時間の悪化（指定区間×1.5）'}[scenario],
            'unit':'1箱＝5物資単位（MATLABの例。吹田市の4.5kgキットとは異なる）',
            'inputs':{'shelters':6,'vehicles':2,'maxRounds':3,'initialStock':40,
                      'targetRate':target,'rho':rho,'delta':delta,'gamma':base['gamma'],
                      'roadDeteriorationEdge':'拠点0↔避難所2' if scenario=='D' else None},
            'initial':{'p1F1star':original['p1']['f1star'],
                       'p0F1':original['p0']['f1'],'etaUpper':original['etaUpper'],
                       'p0PrimeTotal':original['p0prime']['total'],'p0PrimeCertified':original['allCertified'],
                       'firstRoundDelivered':sum(sum(tr.values()) for tr in first)},
            'afterRound1':{'demand':state_after['demand'],'stock':state_after['stock'],
                            'received':state_after['received']},
            'replan':replan_status,'comparisons':plans,
            'limitations':['F2・F3の厳密パレート集合は未計算です。各方式の代表配送案のみ比較します。',
                           'P0/P0′は縮約した基本整数モデル。経路・時刻を含む完全なMATLABモデルとは別です。',
                           'シナリオDの変更区間は拠点0↔避難所2の仮設定です。',
                           '配送時間やケース比較はMATLAB参考値の転載ではなくこのWeb実装の計算値です。']}


def matlab_reference():
    return {'instance':'6避難所・車両2台（各10箱）・最大3回・在庫40箱',
            'p1F1star':0.1112,'p0F1':0.2,'etaStar':0.0889,
            'maxShippableBoxes':40,'rho':1e-4,'targetRate':.5,
            'fronts':{'delta0_uniform':[[112,2.667],[117,2.533]],
                      'delta002_uniform':[[100,2.867],[112,2.667],[117,2.533]],
                      'delta0_urgent':[[112,3.14],[124,2.99],[128,2.84],[145,2.80]]},
            'note':'rev27_matlab/README.md の既定条件に掲載された既検算値。Webの近似経路結果とは別の参考資料。'}
