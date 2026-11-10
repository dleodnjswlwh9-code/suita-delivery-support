"""Auditable reference implementation of P2, complete-kit heuristic.

F2 / F3 / visit / vehicle constraints from professor rev21. The 100-shelter
solution is NOT claimed globally optimal (heuristic route construction).
Basic pooled integer-kit P0 is solved with the identical P1 F1 scalarization.
P0 optimality and P2 heuristic routing are reported separately. Two-hub stocks,
road closures and conditional time constraints are not certified.
Two-hub pooling and centerline/Manhattan distance are stated assumptions.
"""
from __future__ import annotations
import math
import copy
import random
from collections import defaultdict
from p0_kit_optimizer import optimize_p0_kits, p0_problem_signature
from kit_planning import (clean_input,solve_p1,round_integer_p1,f1_score,
    KitInputError,TRUCK_CAP_KITS,KIT_KG,LOADING_MIN,PREP_MIN,
    UNLOADING_MIN_PER_KIT,ROAD_SPEED_KMH)

HUBS = [
 dict(id=0,name='北部輸送拠点（パナソニックスタジアム吹田）',lat=34.80275,lng=135.53815),
 dict(id=1,name='南部輸送拠点（ASKUL関西DC）',lat=34.770248,lng=135.536069),
]


def time_matrix(rows):
    coords=[(h['lat'],h['lng']) for h in HUBS]+[(r['lat'],r['lng']) for r in rows]
    mat=[]
    for lat,lng in coords:
        row=[]
        for la,lo in coords:
            km=(abs(la-lat)*111.32 + abs(lo-lng)*111.32*math.cos(math.radians((lat+la)/2)))
            row.append(km/ROAD_SPEED_KMH*60.)
        mat.append(row)
    return mat


def route_drive_breakdown(stops, hub, mat):
    """Directed road time: hub -> every shelter -> the SAME hub.

    Outbound includes all between-shelter arcs; return is the final shelter
    -> hub arc. This is used in GA, 2-opt and F2 (not merely on the map).
    """
    if not stops:
        return 0.0, 0.0
    cur = hub
    outbound = 0.0
    for shelter in stops:
        outbound += mat[cur][shelter + 2]
        cur = shelter + 2
    return outbound, mat[cur][hub]


def route_drive(stops, hub, mat):
    outbound, homeward = route_drive_breakdown(stops, hub, mat)
    return outbound + homeward


def route_total(route,mat):
    return 0. if not route['stops'] else (LOADING_MIN + PREP_MIN*len(route['stops'])+
        UNLOADING_MIN_PER_KIT*route['load']+route_drive(route['stops'],route['hub'],mat))


def insert_best(route,i,mat):
    stops=route['stops'];hub=route['hub']
    if i in stops:return 0.,stops.index(i)
    best=(math.inf,0)
    for pos in range(len(stops)+1):
        pre=(stops[pos-1]+2 if pos else hub)
        aft=(stops[pos]+2 if pos<len(stops) else hub)
        inc=mat[pre][i+2]+mat[i+2][aft]-mat[pre][aft]
        if inc<best[0]:best=(inc,pos)
    return best


def improve_2opt(route,mat):
    stops=route['stops']
    if len(stops)<4:return
    for _ in range(2):
        changed=False
        for a in range(len(stops)-2):
            for b in range(a+2,len(stops)):
                proposal=stops[:a]+list(reversed(stops[a:b+1]))+stops[b+1:]
                if route_drive(proposal,route['hub'],mat)+1e-6<route_drive(stops,route['hub'],mat):
                    stops[:]=proposal;changed=True
        if not changed:break


def improve_ga_route(route, mat):
    """Small, deterministic permutation GA for visit order, then 2-opt/Or-opt.

    Vehicle/round and delivery quantities were seeded by a separate capacity-
    feasible insertion heuristic. This does not certify a global optimum.
    """
    start=tuple(route['stops']); n=len(start)
    if n<4:return
    rng=random.Random(7919+route['truck']*173+route['round']*47+n)
    size=12; gens=14
    pop=[start]
    for _ in range(size-1):
        p=list(start);rng.shuffle(p);pop.append(tuple(p))
    def key(x):return route_drive(x,route['hub'],mat)
    for _ in range(gens):
        pop=sorted(set(pop),key=key)
        elite=pop[:max(2,min(4,len(pop)))]
        nextpop=list(elite)
        while len(nextpop)<size:
            p1,p2=rng.sample(elite,2)
            a,b=sorted(rng.sample(range(n),2))
            child=[None]*n;child[a:b]=p1[a:b]
            pool=[j for j in p2 if j not in child]
            for i in range(n):
                if child[i] is None:child[i]=pool.pop(0)
            if rng.random()<0.72:
                i,j=rng.sample(range(n),2)
                if rng.random()<0.5:child[i],child[j]=child[j],child[i]
                else:
                    item=child.pop(i);child.insert(j,item)
            nextpop.append(tuple(child))
        pop=nextpop
    best=min(pop+[start],key=key)
    if key(best)+1e-9<key(start):route['stops'][:]=best
    improve_2opt(route,mat)
    # Or-opt single-node relocation further improves noncritical paths.
    for _ in range(2):
        seq=route['stops'];base=route_drive(seq,route['hub'],mat);found=None
        for a in range(len(seq)):
            for b in range(len(seq)):
                if a==b:continue
                candidate=list(seq);item=candidate.pop(a);candidate.insert(b,item)
                t=route_drive(candidate,route['hub'],mat)
                if t+1e-7<base:
                    base=t;found=candidate
        if found is None:break
        route['stops'][:]=found


def allocate_trucks(clean, additions,mat):
    T=clean['trucks']; R=clean['rounds']; rows=clean['rows']
    # Use BOTH outward and homeward journeys for hub assignment.
    distance=[[mat[h][i+2]+mat[i+2][h] for h in range(2)] for i in range(len(rows))]
    assignment=[min(range(2),key=lambda h:distance[i][h]) for i in range(len(rows))]
    if T==1:
        best_h=min((0,1),key=lambda h:sum(additions[i]*distance[i][h] for i in range(len(rows))))
        assignment=[best_h]*len(rows)
        counts=[int(best_h==0),int(best_h==1)]
        return assignment,counts
    # Estimate necessary trips for each hub, balancing trucks without pretending
    # that the physical stock split is known (derived from the proposed plan).
    amounts=[sum(additions[i] for i,x in enumerate(assignment) if x==h) for h in range(2)]
    counts=[max(1,round(T*amounts[0]/max(1,sum(amounts)))),0]
    counts[0]=min(T-1,counts[0]);counts[1]=T-counts[0]
    # Reassign demand near boundary if one hub lacks enough round slots.
    for _ in range(len(rows)*2):
        bad=[h for h in range(2) if sum(additions[i] for i,a in enumerate(assignment) if a==h)>counts[h]*R*TRUCK_CAP_KITS]
        if not bad:break
        h=bad[0];other=1-h
        currentOther=sum(additions[i] for i,a in enumerate(assignment) if a==other)
        options=[i for i,a in enumerate(assignment) if a==h and additions[i]>0 and currentOther+additions[i]<=counts[other]*R*TRUCK_CAP_KITS]
        if not options:break
        i=min(options,key=lambda k:(distance[k][other]-distance[k][h])/max(1,additions[k]))
        assignment[i]=other
    if any(sum(additions[i] for i,a in enumerate(assignment) if a==h)>counts[h]*R*TRUCK_CAP_KITS for h in range(2)):
        raise KitInputError('拠点別の車両容量で物資を運べません。車両台数または配送回数を増やしてください。')
    return assignment,counts


def balance_round_makespan(wave,mat):
    """Local F2 makespan improvement without changing quantities or F3."""
    if sum(bool(r['stops']) for r in wave)<2:return
    for _ in range(32):
        durations=[route_total(rt,mat) for rt in wave]
        baseline=max(durations)
        critical=[rt for rt,time in zip(wave,durations) if time>=baseline-0.01]
        best=None;best_value=baseline
        for origin in critical:
            for target in wave:
                if target is origin or target['hub']!=origin['hub']:continue
                # One shelter changes trucks within the SAME delivery round.
                for i in origin['stops']:
                    qi=origin['quantities'][i]
                    if target['load']+qi<=target['capacityKits']:
                        oo=[q for q in origin['stops'] if q!=i]
                        tt=target['stops']+[i]
                        t1=(LOADING_MIN+PREP_MIN*len(oo)+UNLOADING_MIN_PER_KIT*(origin['load']-qi)+route_drive(oo,origin['hub'],mat)) if oo else 0
                        t2=LOADING_MIN+PREP_MIN*len(tt)+UNLOADING_MIN_PER_KIT*(target['load']+qi)+route_drive(tt,target['hub'],mat)
                        val=max(t1,t2,max((d for rt,d in zip(wave,durations) if rt is not origin and rt is not target),default=0))
                        if val+0.05<best_value:
                            best=('move',origin,target,i,None);best_value=val
                    # Capacity-compatible swap of two shelter deliveries.
                    for j in target['stops']:
                        qj=target['quantities'][j]
                        if origin['load']-qi+qj>origin['capacityKits'] or target['load']-qj+qi>target['capacityKits']:continue
                        oo=[j if v==i else v for v in origin['stops']]
                        tt=[i if v==j else v for v in target['stops']]
                        t1=LOADING_MIN+PREP_MIN*len(oo)+UNLOADING_MIN_PER_KIT*(origin['load']-qi+qj)+route_drive(oo,origin['hub'],mat)
                        t2=LOADING_MIN+PREP_MIN*len(tt)+UNLOADING_MIN_PER_KIT*(target['load']-qj+qi)+route_drive(tt,target['hub'],mat)
                        val=max(t1,t2,max((d for rt,d in zip(wave,durations) if rt is not origin and rt is not target),default=0))
                        if val+0.05<best_value:
                            best=('swap',origin,target,i,j);best_value=val
        if best is None:break
        typ,origin,target,i,j=best
        qi=origin['quantities'].pop(i);origin['stops'].remove(i);origin['load']-=qi
        if typ=='move':
            target['stops'].append(i);target['quantities'][i]=qi;target['load']+=qi
        else:
            qj=target['quantities'].pop(j);target['stops'].remove(j);target['load']-=qj
            origin['stops'].append(j);origin['quantities'][j]=qj;origin['load']+=qj
            target['stops'].append(i);target['quantities'][i]=qi;target['load']+=qi
        improve_2opt(origin,mat);improve_2opt(target,mat)



def absorb_subminimum_remainder(i,left,routes,hubs,delta,mat):
    """Prevent illegal 1..delta-1 deliveries produced by greedy chunk packing.

    First expand an existing visit. If no space, relocate a small previous visit,
    or shift delta kits from a larger previous visit to another round.
    """
    old=[]
    for wave in routes:
        for rt in wave:
            if i in rt['quantities']:
                old.append(rt)
    for rt in old:
        if rt['load']+left<=TRUCK_CAP_KITS:
            rt['quantities'][i]+=left;rt['load']+=left
            return True
    for origin in sorted(old,key=lambda r:r['quantities'][i]):
        q=origin['quantities'][i]
        shift=delta if q>=2*delta else q
        target_qty=left+shift
        candidates=[]
        for wave in routes:
            for dest in wave:
                if (dest is origin or dest['hub']!=hubs[i] or dest['load']+target_qty>TRUCK_CAP_KITS
                    or (dest['round']==origin['round'] and q>shift)):
                    continue
                # One vehicle per shelter per round, except when the original
                # visit will disappear after relocation.
                collision=any(i in r['quantities'] for r in wave if r is not origin)
                if collision:continue
                inc,pos=insert_best(dest,i,mat)
                candidates.append((dest['round'],inc,dest['truck'],dest,pos))
        if not candidates:continue
        _,_,_,dest,pos=min(candidates,key=lambda q:q[:3])
        if q==shift:
            origin['stops'].remove(i);del origin['quantities'][i];origin['load']-=q
        else:
            origin['quantities'][i]-=shift;origin['load']-=shift
        dest['stops'].insert(pos,i);dest['quantities'][i]=target_qty;dest['load']+=target_qty
        return True
    return False

def build_route_plan(clean, additions, mat=None):
    n=len(clean['rows']);T=clean['trucks'];R=clean['rounds'];mat=mat if mat is not None else time_matrix(clean['rows'])
    hubs,counts=allocate_trucks(clean,additions,mat)
    truck_hubs=[h for h in range(2) for _ in range(counts[h])]
    routes=[[dict(round=r+1,truck=t+1,hub=truck_hubs[t],stops=[],quantities={},load=0,
                  capacityKits=clean['fleet'][t]['capacityKits'],vehicleType=clean['fleet'][t]['type'])
             for t in range(T)] for r in range(R)]
    assigned=[0]*n
    # The first delivery to every shelter is mandatory unless it has been visited.
    mandatory=[i for i,row in enumerate(clean['rows']) if additions[i]>0 and not row['visited']]
    mandatory.sort(key=lambda i:(-min(mat[0][i+2]+mat[i+2][0],mat[1][i+2]+mat[i+2][1]),-additions[i]))
    for i in mandatory:
        cand=[]
        for r in range(R):
            for t in range(T):
                route=routes[r][t]
                if route['hub']!=hubs[i] or route['load']+clean['delta']>TRUCK_CAP_KITS:continue
                inc,pos=insert_best(route,i,mat)
                # Travel impact, minus a small bias toward earlier rounds (F3).
                est=max(route_total(q,mat) for q in routes[r])
                obj=max(est,route_total(route,mat)+inc+PREP_MIN+(LOADING_MIN if not route['stops'] else 0))+r*1000
                cand.append((obj,r,t,pos))
        if not cand:
            raise KitInputError('フィードバック制約により必須訪問の経路を作れません。')
        _,r,t,pos=min(cand)
        route=routes[r][t]
        route['stops'].insert(pos,i);route['quantities'][i]=clean['delta']
        route['load']+=clean['delta'];assigned[i]+=clean['delta']
    # Remaining kit volume: earliest round first with suitable truck capacity.
    todo=sorted(range(n),key=lambda i: (additions[i], clean['a']-(clean['rows'][i]['stock']+assigned[i])/max(1,clean['rows'][i]['demand'])),reverse=True)
    for i in todo:
        left=additions[i]-assigned[i]
        while left>0:
            if left<clean['delta']:
                if absorb_subminimum_remainder(i,left,routes,hubs,clean['delta'],mat):
                    assigned[i]+=left
                    left=0
                    break
                raise KitInputError('最小配送単位に満たない残量を既存配送にまとめられません。')
            choices=[]
            for r in range(R):
                occupied=any(i in rt['quantities'] for rt in routes[r])
                for t in range(T):
                    route=routes[r][t]
                    if route['hub']!=hubs[i] or route['load']>=TRUCK_CAP_KITS:continue
                    if occupied and i not in route['quantities']:continue
                    if i not in route['quantities'] and (left<clean['delta'] or TRUCK_CAP_KITS-route['load']<clean['delta']):continue
                    inc,pos=insert_best(route,i,mat)
                    choices.append((r,0 if i in route['quantities'] else inc,t,pos))
            if not choices:
                # A shelter may only be served by one truck per round. Free
                # capacity on another truck by relocating one of the OTHER
                # stops from the shelter's current route within that round.
                repaired=False
                for rr,wave in enumerate(routes):
                    if repaired:break
                    for origin in wave:
                        if i not in origin['quantities']:continue
                        for j in sorted((q for q in origin['stops'] if q!=i),key=lambda q:origin['quantities'][q]):
                            qty=origin['quantities'][j]
                            candidates=[dest for dest in wave if dest is not origin and dest['hub']==origin['hub']
                                        and j not in dest['quantities'] and dest['load']+qty<=TRUCK_CAP_KITS]
                            if not candidates:continue
                            dest=min(candidates,key=lambda q:insert_best(q,j,mat)[0]);_,pos=insert_best(dest,j,mat)
                            dest['stops'].insert(pos,j);dest['quantities'][j]=qty;dest['load']+=qty
                            origin['stops'].remove(j);origin['load']-=qty;del origin['quantities'][j]
                            repaired=True;break
                        if repaired:break
                if repaired:continue
                raise KitInputError('指定回数では一部避難所への配送量を割り当てられません。配送回数・車両台数を確認してください。')
            r,inc,t,pos=min(choices);route=routes[r][t]
            amount=min(left,TRUCK_CAP_KITS-route['load'])
            if i not in route['quantities']:
                if amount<clean['delta']:raise KitInputError('配送単位を満たせません。')
                route['stops'].insert(pos,i);route['quantities'][i]=0
            route['quantities'][i]+=amount;route['load']+=amount;left-=amount;assigned[i]+=amount
    for wave in routes:
        for route in wave: improve_ga_route(route,mat)
        balance_round_makespan(wave,mat)
    return routes,mat,counts,assigned


def _fallback_whole_visit_milp(clean, additions, mat=None):
    """Small/medium exact capacity assignment fallback when greedy packing fails.

    This MILP proves *packing feasibility*, not optimal P2 routes or P0. Each
    positive shelter is delivered in one visit, so splitting is not attempted.
    Return None if inapplicable or if MILP cannot establish feasibility within
    its time budget; never label a timeout as a mathematical impossibility.
    """
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import lil_matrix
    positive=[i for i,q in enumerate(additions) if q>0]
    T=clean['trucks'];R=clean['rounds'];n=len(positive)
    if not positive:return None
    if (n>45 or T*R>100 or n*T*R>2800 or
        any(additions[i]>TRUCK_CAP_KITS or additions[i]<clean['delta'] for i in positive)):
        return None
    if sum(additions)>T*R*TRUCK_CAP_KITS:return None
    mat=mat if mat is not None else time_matrix(clean['rows'])
    # Capacity-repair hub costs must also contain the return trip.
    dist=[[mat[h][i+2]+mat[i+2][h] for h in range(2)] for i in positive]
    expected=sum(additions[i]*(dist[k][0]<=dist[k][1]) for k,i in enumerate(positive))
    best_north=round(T*expected/max(1,sum(additions)))
    if T==1: candidates=[0,1]
    else: candidates=sorted(range(T+1), key=lambda v:(abs(v-best_north), v))
    slots=T*R
    # Each item is placed in one truck/round slot; each slot has a capacity.
    # The hub of a truck is constant across its successive rounds.
    A=lil_matrix((n+slots,n*slots),dtype=float)
    for ii,i in enumerate(positive):
        for j in range(slots):
            z=ii*slots+j
            A[ii,z]=1
            A[n+j,z]=additions[i]
    A=A.tocsc()
    lb=[1.]*n+[0.]*slots
    ub=[1.]*n+[float(TRUCK_CAP_KITS)]*slots
    constraints=LinearConstraint(A,lb,ub)
    rng=Bounds(0,1)
    for north in candidates:
        truck_hubs=[0]*north+[1]*(T-north)
        costs=[]
        for ii,i in enumerate(positive):
            for r in range(R):
                for t in range(T):
                    h=truck_hubs[t]
                    # Dispatch earlier (F3) and reduce travel-distance proxy.
                    costs.append(r*1000+dist[ii][h]*.1+(t+.01)*.00001)
        ans=milp(costs, integrality=[1]*(n*slots),bounds=rng,
                 constraints=constraints,options={'time_limit':4.0,'mip_rel_gap':.025})
        if ans.x is None or any(abs(sum(ans.x[ii*slots+j] for j in range(slots))-1)>1e-3 for ii in range(n)):
            continue
        routes=[[dict(round=r+1,truck=t+1,hub=truck_hubs[t],stops=[],quantities={},load=0,
                      capacityKits=clean['fleet'][t]['capacityKits'],vehicleType=clean['fleet'][t]['type'])
                 for t in range(T)] for r in range(R)]
        for ii,i in enumerate(positive):
            j=max(range(slots),key=lambda v:ans.x[ii*slots+v]);r,t=divmod(j,T)
            rt=routes[r][t];q=additions[i]
            _,pos=insert_best(rt,i,mat)
            rt['stops'].insert(pos,i);rt['quantities'][i]=q;rt['load']+=q
        if any(rt['load']>rt['capacityKits'] for wave in routes for rt in wave):continue
        for wave in routes:
            for rt in wave:improve_ga_route(rt,mat)
            balance_round_makespan(wave,mat)
        assigned=list(additions)
        validate_plan(clean,routes,assigned)
        return routes,mat,[north,T-north],assigned
    return None


def validate_plan(clean, routes, assigned):
    rows=clean['rows'];R=clean['rounds'];T=clean['trucks'];d=clean['delta']
    if any(assigned[i]>r['remaining'] for i,r in enumerate(rows)):raise KitInputError('需要量を超える配送です。')
    if sum(assigned)>clean['available']:raise KitInputError('拠点在庫を超える配送です。')
    if len(routes)!=R or any(len(wave)!=T for wave in routes):raise KitInputError('車両・回数の割当が不正です。')
    for wave in routes:
        seen=set()
        for route in wave:
            if clean.get('vehicleHubCounts') is not None and route['hub']!=clean['fleet'][route['truck']-1]['hub']:
                raise KitInputError('車両が指定拠点以外から出発しています。')
            if route['load']>clean['fleet'][route['truck']-1]['capacityKits'] or route['load']!=sum(route['quantities'].values()):raise KitInputError('車両容量を超えています。')
            if len(route['stops'])!=len(route['quantities']) or set(route['stops'])!=set(route['quantities']):raise KitInputError('経路の接続が不正です。')
            for i,q in route['quantities'].items():
                if i in seen or q<d:raise KitInputError('重複訪問・最小配送量に違反しています。')
                seen.add(i)
    if clean.get('hubStockKits') is not None:
        for h in (0,1):
            total=sum(rt['load'] for wave in routes for rt in wave if rt['hub']==h)
            if total>clean['hubStockKits'][h]:raise KitInputError(f'{h+1}番拠点の在庫不足：{total} > {clean["hubStockKits"][h]}キット')
    if any(not r['visited'] and r['remaining']>=d and assigned[i]<d for i,r in enumerate(rows)):
        raise KitInputError('必須訪問が満たされていません。')
    if [sum(1 for rt in wave if rt['load'])>0 for wave in routes].count(False) and any(
        any(rt['load'] for rt in routes[r+1]) and not any(rt['load'] for rt in routes[r]) for r in range(R-1)):
        raise KitInputError('配送回の連続使用制約が満たされていません。')


def build_p0_seed_routes(clean, p0, mat):
    """Construct actual hub-return routes from a certified/feasible reduced-P0
    *vehicle-round-quantity* assignment. This preserves F1 and every visit,
    but depot availability/closure/time constraints remain unverified.
    """
    n=len(clean['rows']);T=clean['trucks'];R=clean['rounds']
    by_truck=[[] for _ in range(T)]
    for assignment in p0['assignment']:
        by_truck[assignment['truck']-1].extend(v['index'] for v in assignment['visits'])
    # In expanded mode the physical hub is fixed in P0 and P2 alike.
    truck_hubs=[]
    for t,stops in enumerate(by_truck):
        hub=(clean['fleet'][t]['hub'] if 'hub' in clean['fleet'][t] else
             min((0,1),key=lambda h:sum(mat[h][i+2]+mat[i+2][h] for i in stops)))
        truck_hubs.append(hub)
    routes=[[dict(round=r+1,truck=t+1,hub=truck_hubs[t],stops=[],quantities={},load=0,
                  capacityKits=clean['fleet'][t]['capacityKits'],vehicleType=clean['fleet'][t]['type'])
             for t in range(T)] for r in range(R)]
    additions=[0]*n
    for assignment in p0['assignment']:
        rt=routes[assignment['round']-1][assignment['truck']-1]
        for visit in assignment['visits']:
            i=visit['index'];q=int(visit['kits'])
            _,pos=insert_best(rt,i,mat)
            rt['stops'].insert(pos,i);rt['quantities'][i]=q;rt['load']+=q
            additions[i]+=q
    for wave in routes:
        for rt in wave:improve_2opt(rt,mat)
        balance_round_makespan(wave,mat)
    validate_plan(clean,routes,additions)
    return routes,mat,[truck_hubs.count(0),truck_hubs.count(1)],additions


def schedule_and_check(clean, routes, mat):
    """Actual route order with shared loading waves and per-shelter time windows.

    Time windows use minutes since the beginning of the plan (all rounds);
    a vehicle may wait for a shelter to open. The final return counts in F2.
    This is an exact validation of THIS candidate route, not a MILP proof.
    """
    elapsed=0.;scheduled=[];round_times=[]
    for wave in routes:
        active=[rt for rt in wave if rt['stops']]
        waves=max((math.ceil(sum(rt['hub']==h for rt in active)/clean['loadingParallel'][h]) for h in (0,1)),default=0)
        load_min=LOADING_MIN*waves if active else 0.
        durations=[];wave_scheduled={}
        for rt in active:
            clock=elapsed+load_min;cur=rt['hub'];times=[]
            for i in rt['stops']:
                clock+=mat[cur][i+2]
                name=clean['rows'][i]['name'];win=clean['visitWindows'].get(name)
                if win:
                    clock=max(clock,float(win[0]))
                    if clock>win[1]+1e-6:
                        raise KitInputError(f'訪問時間帯に到着できません：{name}（第{rt["round"]}回）')
                arrival=clock;clock+=PREP_MIN+UNLOADING_MIN_PER_KIT*rt['quantities'][i]
                if win and clock>win[1]+1e-6:
                    raise KitInputError(f'訪問時間帯内に荷卸しが完了しません：{name}')
                times.append((i,arrival))
                cur=i+2
            clock+=mat[cur][rt['hub']]
            durations.append(clock-elapsed)
            wave_scheduled[rt['truck']]=(times,clock-elapsed,load_min)
        span=max(durations,default=0.)
        if clean['maxRoundMinutes'] is not None and span>clean['maxRoundMinutes']+1e-5:
            raise KitInputError(f'第{len(round_times)+1}回の所要時間{span:.1f}分が上限{clean["maxRoundMinutes"]}分を超過')
        round_times.append(span);scheduled.append(wave_scheduled);elapsed+=span
    if clean['maxTotalMinutes'] is not None and elapsed>clean['maxTotalMinutes']+1e-5:
        raise KitInputError(f'累積所要時間{elapsed:.1f}分が上限{clean["maxTotalMinutes"]}分を超過')
    return round_times,scheduled


def candidate_f3(clean, routes):
    """Cumulative shortage after each non-final delivery round (same K+ as P0)."""
    cum=[0]*len(clean['rows']);total=0.
    last_used=max((r for r,wave in enumerate(routes) if any(rt['stops'] for rt in wave)),default=-1)
    weight=1/(1-clean['a'])
    for r,wave in enumerate(routes):
        for rt in wave:
            for i,q in rt['quantities'].items():cum[i]+=q
        if r<last_used:
            total+=sum(weight*max(0.,clean['a']-(row['stock']+cum[i])/row['demand'])
                for i,row in enumerate(clean['rows']) if row['remaining']>=clean['delta'] and row['demand']>0)
    return float(total)



def diversified_p0_route_candidates(clean, seed):
    """Feasible-candidate search beyond the single mixed-fleet P0 route.

    Keep the EXACT per-facility integer quantity and vehicle hub. Explore
    alternate visit orders and distribute different shelters across rounds of
    the SAME vehicle. Routes are only accepted after the full scheduler and
    F1/capacity/inventory checks; no claim of a global F2 optimum.
    """
    base,mat,counts,additions=seed
    # Intra-route genetic+2opt improvement (retains visit round and stock).
    ga=copy.deepcopy(base)
    for wave in ga:
        for rt in wave: improve_ga_route(rt,mat)
        balance_round_makespan(wave,mat)
    yield 'P0-MILP-incumbent-GA-and-2opt', (ga,mat,counts,additions)

    if clean['rounds']<2:
        return
    # Planned split policies: change only the round of a shelter assigned to
    # the SAME truck, leaving quantities, hub and vehicle capacity unchanged.
    # They are alternative candidate starts, not a promise of completion time
    # reduction; F3 explicitly penalizes delayed supply.
    for ratio,label in ((.35,'35'),(.55,'55')):
        waves=copy.deepcopy(ga)
        moved=0
        # Split the first occupied round into two consecutive waves.
        for rt in waves[0]:
            if len(rt['stops'])<2:continue
            target=waves[1][rt['truck']-1]
            if target['hub']!=rt['hub'] or target['stops']:continue
            size=min(len(rt['stops'])-1,max(1,round(len(rt['stops'])*ratio)))
            # Alternate stops instead of naively removing the farthest: this
            # starts two compact routes after 2-opt improves their orders.
            selected=rt['stops'][::2][:size]
            for i in selected:
                q=rt['quantities'].pop(i)
                rt['stops'].remove(i);rt['load']-=q
                target['stops'].append(i);target['quantities'][i]=q;target['load']+=q
                moved+=1
        if not moved:continue
        for wave in waves[:2]:
            for rt in wave:improve_ga_route(rt,mat)
            balance_round_makespan(wave,mat)
        yield 'P0-MILP-round-split-'+label+'pct', (waves,mat,counts,additions)


def _checked_route_candidate(clean, method, route_bundle):
    routes,mat,counts,actual=route_bundle
    validate_plan(clean,routes,actual)
    round_times,_=schedule_and_check(clean,routes,mat)
    return dict(method=method,bundle=route_bundle,
        f1=float(f1_score(clean['rows'],actual,clean['a'],clean['rho'],clean['delta'])),
        f2=float(max(round_times,default=0.)),totalMinutes=float(sum(round_times)),
        f3=candidate_f3(clean,routes))


def _valid_reused_p0(data,clean,p1,prior):
    """Server-side reuse ONLY when the entire P0 snapshot still matches.

    This accepts a server-owned cached result, not an arbitrary browser result.
    Validate the complete integer visit assignment and conservative route
    before bypassing the P0 MILP; stale/incorrect cache values are discarded.
    """
    if not isinstance(prior,dict) or not prior.get('feasible') or not prior.get('assignment'):
        return False
    if prior.get('p0InputSignature')!=p0_problem_signature(data,clean=clean):
        return False
    if abs(float(prior.get('f1Star',float('inf')))-p1['f1'])>1e-6:
        return False
    try:
        trial=build_p0_seed_routes(clean,prior,time_matrix(clean['rows']))
        routes,mat,_,additions=trial
        scheduled,_=schedule_and_check(clean,routes,mat)
        if any(not isinstance(x,int) or x<0 for x in additions):return False
        if additions!=prior['plannedAdditions']:return False
        f1=f1_score(clean['rows'],additions,clean['a'],clean['rho'],clean['delta'])
        if abs(f1-float(prior['f1Feasible']))>1e-6:return False
        if abs(max(0.,f1-p1['f1'])-float(prior['etaUpperBound']))>1e-6:return False
        return True
    except (KitInputError,IndexError,KeyError,TypeError,ValueError,OverflowError):
        return False


def optimize_p2_kit(data, driving_matrix=None, matrix_source=None, matrix_note=None, p0_result=None):
    if (data or {}).get('roadMode', 'all') != 'all':
        raise KitInputError('緊急交通路優先は現在未実装です。すべての道路を利用してください。')
    c=clean_input(data);p1=solve_p1(c)
    # P0 is always evaluated on original facility records. P2 may use a
    # centroid as its travel stop without collapsing any facility's demand.
    route_clean=copy.deepcopy(c)
    delivery_points=(data or {}).get('deliveryPoints')
    if delivery_points is not None:
        if not isinstance(delivery_points,list) or len(delivery_points)!=len(c['rows']):
            raise KitInputError('代表点の施設対応が一致しません。配送条件を再保存してください。')
        for i,dp in enumerate(delivery_points):
            if not isinstance(dp,dict) or not str(dp.get('name') or '').strip():
                raise KitInputError('配送代表点の名称が不正です。')
            try:lat=float(dp['lat']);lng=float(dp['lng'])
            except (KeyError,TypeError,ValueError,OverflowError):
                raise KitInputError('配送代表点の位置が不正です。')
            if not math.isfinite(lat) or not math.isfinite(lng) or not (33<lat<36 and 134<lng<138):
                raise KitInputError('配送代表点の位置が大阪周辺の有効座標ではありません。')
            route_clean['rows'][i].update(lat=lat,lng=lng,deliveryPointName=str(dp['name']))
    if driving_matrix is not None:
        n=len(c['rows'])+2
        if len(driving_matrix)!=n or any(len(row)!=n for row in driving_matrix):
            raise KitInputError('Google道路時間行列のサイズが不正です。')
        if any(not math.isfinite(float(t)) or float(t)<0 for row in driving_matrix for t in row):
            raise KitInputError('Google道路時間行列に無効な値があります。')
    # P1 delivers its ideal objective value; the delivery stage must use an
    # identical input snapshot, not silently recompute a different P1 case.
    reference=(data or {}).get('p1ReferenceF1')
    if reference is not None:
        try:reference=float(reference)
        except (TypeError,ValueError,OverflowError):
            raise KitInputError('P1の評価値が不正です。配分計画を再計算してください。')
        if not math.isfinite(reference) or abs(reference-p1['f1'])>max(1e-5,1e-7*abs(p1['f1'])):
            raise KitInputError('P1とP2の入力条件が一致しません。希求水準・在庫・避難者数・配送条件を確認して配分計画から再計算してください。')
    # The basic P0 MILP is solved on the EXACT SAME grouped (or ungrouped)
    # shelter snapshot as this P2. A feasible P0 incumbent is an operational
    # evaluation bound, but not a global optimum unless certified.
    p0_reused=_valid_reused_p0(data,c,p1,p0_result)
    p0=p0_result if p0_reused else optimize_p0_kits(data,clean=c,p1=p1)
    if not p0.get('feasible'):
        raise KitInputError('P0で実行可能な配分案を得られませんでした。条件を確認してP0から再計算してください。')
    mat=driving_matrix if driving_matrix is not None else time_matrix(route_clean['rows'])
    delta_f1=float((data or {}).get('p2DeltaF1',0) or 0)
    if not math.isfinite(delta_f1) or not 0<=delta_f1<=10:
        raise KitInputError('P2の許容幅Δは0～10の数値で入力してください。')
    candidates=[];candidate_errors=[]
    try:
        if any(v['type']=='4t' for v in c['fleet']):
            raise KitInputError('混合車種はP0のMILP割当を用います。')
        xs=round_integer_p1(c,p1)
        try:
            cand=build_route_plan(route_clean,xs,mat)
            method='greedy-with-local-improvement'
        except KitInputError as primary_error:
            recovered=_fallback_whole_visit_milp(route_clean,xs,mat)
            if recovered is None:raise primary_error
            cand=recovered;method='MILP-capacity-repair'
        candidates.append(_checked_route_candidate(route_clean,method,cand))
    except KitInputError as error:candidate_errors.append(str(error))
    try:
        seed=build_p0_seed_routes(route_clean,p0,mat)
        candidates.append(_checked_route_candidate(route_clean,'P0-MILP-incumbent-route-seed',seed))
        for method,variant in diversified_p0_route_candidates(route_clean,seed):
            try:candidates.append(_checked_route_candidate(route_clean,method,variant))
            except KitInputError as error:candidate_errors.append(method+': '+str(error)[:100])
    except KitInputError as error:candidate_errors.append(str(error))
    if not candidates:
        raise KitInputError('配送条件を満たす経路を構成できませんでした。'+(' '.join(candidate_errors)[:240] if candidate_errors else ''))
    # Hard constraint: NEVER publish an over-limit route as the P2 final plan.
    # The feasible P0 *upper* bound is the reference when η* is not certified.
    allowed=float(p0['f1Feasible'])+delta_f1+1e-5
    within=[opt for opt in candidates if opt['f1']<=allowed]
    if not within:
        raise KitInputError('P0配分評価の許容上限を守る配送経路を作成できません。'
            ' Δを変更するかP0を再計算してください。超過案は最終計画として採用しません。')
    # Professor-style MAXIMUM single-round makespan F2 first; cumulative shortage F3 and F1
    # distinguish otherwise-equal plans. This is a HEURISTIC lexicographic
    # candidate comparison, not global multiobjective Pareto optimization.
    best=min(within,key=lambda opt:(round(opt['f2'],6),opt['f3'],opt['totalMinutes'],opt['f1']))
    assignment_method=best['method']
    routes,mat,truck_counts,actual=best['bundle']
    scheduled_round_times,scheduled_visits=schedule_and_check(c,routes,mat)
    score=best['f1']
    gap=max(0.,score-p1['f1'])
    bound_satisfied=bool(score<=float(p0['f1Feasible'])+delta_f1+1e-5)
    certified_basic=bool(p0.get('certified') and bound_satisfied)
    # P2 may discover an improved bound, but its route is NOT P0's original
    # integer assignment. Do not mutate p0's F1/eta independently of its plan.
    p2_better_than_p0=score+1e-6<float(p0['f1Feasible'])
    p2_eta_upper=min(float(p0['etaUpperBound']),gap)
    pareto=[]
    for cand in within:
        dominated=any(other is not cand and
            other['f2']<=cand['f2']+1e-8 and other['f3']<=cand['f3']+1e-8 and
            (other['f2']<cand['f2']-1e-8 or other['f3']<cand['f3']-1e-8)
            for other in within)
        if not dominated:
            pareto.append(dict(method=cand['method'],f1=round(cand['f1'],6),
                                f2=round(cand['f2'],3),f3=round(cand['f3'],6)))
    wave_times=[];real_routes=[];round_f3=[]
    last_used_round=max((r for r,wave in enumerate(routes) if any(rt['stops'] for rt in wave)),default=-1)
    cum=[0]*len(c['rows']);active_vehicles=set()
    for r,wave in enumerate(routes):
        timed=[]
        for rt in wave:
            if not rt['stops']:continue
            active_vehicles.add(rt['truck'])
            clock=scheduled_visits[r][rt['truck']][2];cur=rt['hub'];stops=[]
            absolute_arrivals=dict(scheduled_visits[r][rt['truck']][0])
            for k in rt['stops']:
                clock+=mat[cur][k+2]
                q=rt['quantities'][k]
                arrival=absolute_arrivals[k] - sum(scheduled_round_times[:r])
                clock=max(clock,arrival)
                clock+=PREP_MIN+UNLOADING_MIN_PER_KIT*q
                cum[k]+=q
                stops.append(dict(index=k,name=c['rows'][k]['name'],kits=q,arrivalMin=round(arrival,2),
                                  lat=route_clean['rows'][k]['lat'],lng=route_clean['rows'][k]['lng'],
                                  deliveryPoint=route_clean['rows'][k].get('deliveryPointName',c['rows'][k]['name']),
                                  afterRate=round((c['rows'][k]['stock']+cum[k])/max(1,c['rows'][k]['demand']),5)))
                cur=k+2
            outbound_min,return_min=route_drive_breakdown(rt['stops'],rt['hub'],mat)
            # All visits finished is NOT operation completion: the truck must
            # return to its loading hub before it can serve the next round.
            last_shelter_departure=clock
            clock+=return_min
            handling_min=scheduled_visits[r][rt['truck']][2]+PREP_MIN*len(rt['stops'])+UNLOADING_MIN_PER_KIT*rt['load']
            if abs(clock-scheduled_visits[r][rt['truck']][1])>1e-5:
                raise KitInputError('訪問時間帯と帰着所要時間の計算が一致しません。')
            real_routes.append(dict(round=r+1,truck=rt['truck'],hub=rt['hub'],hubName=HUBS[rt['hub']]['name'],
                kits=rt['load'],capacityKits=rt['capacityKits'],vehicleType=rt['vehicleType'],timeMin=round(clock,3),stops=stops,
                outboundDriveMin=round(outbound_min,3),returnDriveMin=round(return_min,3),
                totalDriveMin=round(outbound_min+return_min,3),handlingMin=round(handling_min,3),
                departLastShelterMin=round(last_shelter_departure,3),returnToHubMin=round(clock,3),
                routeClosure='hub-to-hub',
                lat=HUBS[rt['hub']]['lat'],lng=HUBS[rt['hub']]['lng']))
            timed.append(clock)
        wave_times.append(max(timed,default=0.))
        # Avoid counting leftover shortfall again after the last USED trip.
        if r<last_used_round:
            w=1/(1-c['a'])
            round_f3.append(sum(w*max(0.,c['a']-(row['stock']+cum[i])/max(1,row['demand']))
                                for i,row in enumerate(c['rows']) if row['remaining']>=c['delta']))
    f2=max(wave_times,default=0.);total_time=sum(wave_times);f3=sum(round_f3)
    if abs(f2-best['f2'])>1e-5 or abs(f3-best['f3'])>1e-5 or abs(total_time-best['totalMinutes'])>1e-5:
        raise KitInputError('P2のF2・F3評価に不一致があります。')
    results=[dict(index=i,name=row['name'],demandKits=row['demand'],stockKits=row['stock'],
                  deliveredKits=actual[i],coverageBefore=round(row['stock']/max(1,row['demand']),5),
                  coverageAfter=round((row['stock']+actual[i])/max(1,row['demand']),5),
                  visits=sum(i in rt['quantities'] for wave in routes for rt in wave),
                  originalLat=row['lat'],originalLng=row['lng'],
                  deliveryPoint=route_clean['rows'][i].get('deliveryPointName',row['name']),
                  lat=route_clean['rows'][i]['lat'],lng=route_clean['rows'][i]['lng'])
             for i,row in enumerate(c['rows'])]
    used_hub=[sum(rt['kits'] for rt in real_routes if rt['hub']==h) for h in range(2)]
    return dict(p2AlgorithmRevision=82,preservedFacilityEvaluation=True,deliveryPointCount=len(set(r.get('deliveryPointName',r['name']) for r in route_clean['rows'])),p0Reused=p0_reused,p2CandidateCount=len(candidates),
        p2WithinBoundCount=len(within),p2CandidatePareto=pareto,
        p2SelectionRule='F2=最大配送回所要時間を最小化、F3→累積作業時間を同点判定（全体最適性は未証明）',
        p2ImprovesEtaBound=p2_better_than_p0,p2BestVerifiedEtaUpperBound=p2_eta_upper,
        status=('basic_p0_bound_within_tolerance' if certified_basic else
                        'basic_p0_incumbent_bound' if bound_satisfied else
                        'p0_not_certified_or_bound_not_met'),
        isValidatedP2=False,isValidatedBasicP2=certified_basic,
        verifiedRouteConstraints=True,hubStockKits=c.get('hubStockKits'),maxRoundMinutes=c.get('maxRoundMinutes'),maxTotalMinutes=c.get('maxTotalMinutes'),
        loadingParallel=c.get('loadingParallel'),visitWindowsCount=len(c.get('visitWindows') or {}),
        p0BoundSatisfied=bound_satisfied,isGloballyOptimal=False,
        solver='P0 MILP (basic pooled kit allocation) + route heuristic (GA / 2-opt)',
        assignmentMethod=assignment_method,roadTimeSource=matrix_source or 'manhattan-20kmh',
        roadTimeNote=matrix_note or ('Google道路時間行列による参考評価' if driving_matrix is not None else 'マンハッタン距離÷20km/hによる暫定推定'),
        minimumRequiredKits=c['delta']*p1['mandatory'],
        mandatoryShelters=p1['mandatory'],microShelters=sum(0<row['remaining']<c['delta'] for row in c['rows']),
        zeroDemandShelters=sum(row['demand']==0 for row in c['rows']),
        message=('配送ルートの積載量・拠点別在庫・時間条件を検証済み。経路最適性は未証明。' if certified_basic else
                 '基本P0の実行可能な評価上界内で配送案を構成。P0最小ギャップの証明・経路最適性は未確認。' if bound_satisfied else
                 'P0の配分評価上限を守る経路のみ確定。'),
        f1Star=p1['f1'],f1Route=score,etaAssumed=p0.get('etaUpperBound'),
        etaStar=p0.get('etaStar'),p0=p0,p2DeltaF1=delta_f1,f1Excess=gap,
        rho=c['rho'],targetRate=c['a'],
        f2Minutes=round(f2,2),totalCompletionMinutes=round(total_time,2),f2Definition='max_round_makespan',f3=round(f3,6),f3ByRound=[round(x,6) for x in round_f3],
        usedRounds=sum(x>0 for x in wave_times),maxRounds=c['rounds'],usedTrucks=len(active_vehicles),
        trucksConfigured=c['trucks'],fleet=c['fleet'],trucksByHub=truck_counts,hubOutgoingKits=used_hub,
        visitedShelters=sum(r['visits']>0 for r in results),shelterCount=len(results),
        deliveredKits=sum(actual),availableKits=c['available'],
        roundTimesMinutes=[round(x,2) for x in wave_times],
        routes=real_routes,shelters=results,hubs=HUBS,
        assumptions={'kit':'レトルトご飯3食＋飲料水500ml6本','truckKg':'2t・4t','fleet':c['fleet'],'kitKg':KIT_KG,
            'truckKits':TRUCK_CAP_KITS,'loadingMin':LOADING_MIN,'shelterPrepMin':PREP_MIN,
            'unloadingMinPerKit':UNLOADING_MIN_PER_KIT,'roadSpeedKmh':ROAD_SPEED_KMH,
            'travel':('Google Routes Matrix（実道路・交通情報）' if driving_matrix is not None else '市街地（マンハッタン）距離÷一般道想定20km/h：実道路のルート・到着時間ではない'),
            'hubStocks':('入力した拠点別シナリオ在庫を車両出庫に適用' if c.get('hubStockKits') is not None else '総量から二拠点へ仮割当：実拠点在庫は未確認'),
            'arrival':'各車両は出発拠点に必ず帰着。F2は各配送回の最長帰着時間の最大値。累積作業時間は別表示',
            'eta':'施設別F1は100施設ごとに評価し、P0で得られた上界を遵守。最適性は未証明の場合あり。',
            'deliveryGroups':'代表点は配送の訪問座標のみ変更。複数施設の総需要・配分評価は統合しない。停車・荷卸し未検証。',
            'stage':'実績確定後は次期P1→P0→P2を再計算。避難者数は実績データがなければ据置' })
