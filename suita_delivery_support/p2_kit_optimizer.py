"""Auditable reference implementation of P2, complete-kit heuristic.

F2 / F3 / visit / vehicle constraints from professor rev21. The 100-shelter
solution is NOT claimed globally optimal (heuristic route construction).
P0 remains paused: eta is an explicitly temporary 0 and strict P1 evaluation
may therefore fail, reported as preview not an admissible P2 solution.
Two-hub pooling and centerline/Manhattan distance are stated assumptions.
"""
from __future__ import annotations
import math
import random
from collections import defaultdict
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


def route_drive(stops,hub,mat):
    cur=hub; total=0.
    for s in stops:
        total+=mat[cur][s+2];cur=s+2
    return total+mat[cur][hub]


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
    distance=[[mat[h][i+2] for h in range(2)] for i in range(len(rows))]
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
                    if target['load']+qi<=TRUCK_CAP_KITS:
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
                        if origin['load']-qi+qj>TRUCK_CAP_KITS or target['load']-qj+qi>TRUCK_CAP_KITS:continue
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

def build_route_plan(clean, additions):
    n=len(clean['rows']);T=clean['trucks'];R=clean['rounds'];mat=time_matrix(clean['rows'])
    hubs,counts=allocate_trucks(clean,additions,mat)
    truck_hubs=[h for h in range(2) for _ in range(counts[h])]
    routes=[[dict(round=r+1,truck=t+1,hub=truck_hubs[t],stops=[],quantities={},load=0)
             for t in range(T)] for r in range(R)]
    assigned=[0]*n
    # The first delivery to every shelter is mandatory unless it has been visited.
    mandatory=[i for i,row in enumerate(clean['rows']) if additions[i]>0 and not row['visited']]
    mandatory.sort(key=lambda i:(-min(mat[0][i+2],mat[1][i+2]),-additions[i]))
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
    todo=sorted(range(n),key=lambda i: (additions[i], clean['a']-(clean['rows'][i]['stock']+assigned[i])/clean['rows'][i]['demand']),reverse=True)
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


def validate_plan(clean, routes, assigned):
    rows=clean['rows'];R=clean['rounds'];T=clean['trucks'];d=clean['delta']
    if any(assigned[i]>r['remaining'] for i,r in enumerate(rows)):raise KitInputError('需要量を超える配送です。')
    if sum(assigned)>clean['available']:raise KitInputError('拠点在庫を超える配送です。')
    if len(routes)!=R or any(len(wave)!=T for wave in routes):raise KitInputError('車両・回数の割当が不正です。')
    for wave in routes:
        seen=set()
        for route in wave:
            if route['load']>TRUCK_CAP_KITS or route['load']!=sum(route['quantities'].values()):raise KitInputError('車両容量を超えています。')
            if len(route['stops'])!=len(route['quantities']) or set(route['stops'])!=set(route['quantities']):raise KitInputError('経路の接続が不正です。')
            for i,q in route['quantities'].items():
                if i in seen or q<d:raise KitInputError('重複訪問・最小配送量に違反しています。')
                seen.add(i)
    if any(not r['visited'] and r['remaining']>=d and assigned[i]<d for i,r in enumerate(rows)):
        raise KitInputError('必須訪問が満たされていません。')
    if [sum(1 for rt in wave if rt['load'])>0 for wave in routes].count(False) and any(
        any(rt['load'] for rt in routes[r+1]) and not any(rt['load'] for rt in routes[r]) for r in range(R-1)):
        raise KitInputError('配送回の連続使用制約が満たされていません。')


def optimize_p2_kit(data):
    if (data or {}).get('roadMode', 'all') != 'all':
        raise KitInputError('緊急交通路優先は現在未実装です。すべての道路を利用してください。')
    c=clean_input(data);p1=solve_p1(c)
    xs=round_integer_p1(c,p1)
    routes,mat,truck_counts,actual=build_route_plan(c,xs)
    validate_plan(c,routes,actual)
    score=f1_score(c['rows'],actual,c['a'],c['rho'])
    gap=max(0.,score-p1['f1'])
    exact=(gap<=max(1e-7,1e-8*abs(p1['f1'])))
    wave_times=[];real_routes=[];round_f3=[]
    cum=[0]*len(xs);active_vehicles=set()
    for r,wave in enumerate(routes):
        timed=[]
        for rt in wave:
            if not rt['stops']:continue
            active_vehicles.add(rt['truck'])
            clock=LOADING_MIN;cur=rt['hub'];stops=[]
            for k in rt['stops']:
                clock+=mat[cur][k+2]
                q=rt['quantities'][k]
                arrival=clock
                clock+=PREP_MIN+UNLOADING_MIN_PER_KIT*q
                stops.append(dict(index=k,name=c['rows'][k]['name'],kits=q,arrivalMin=round(arrival,2),
                                  lat=c['rows'][k]['lat'],lng=c['rows'][k]['lng'],afterRate=round((c['rows'][k]['stock']+actual[k])/c['rows'][k]['demand'],5)))
                cum[k]+=q;cur=k+2
            clock+=mat[cur][rt['hub']]
            real_routes.append(dict(round=r+1,truck=rt['truck'],hub=rt['hub'],hubName=HUBS[rt['hub']]['name'],
                kits=rt['load'],capacityKits=TRUCK_CAP_KITS,timeMin=round(clock,3),stops=stops,
                lat=HUBS[rt['hub']]['lat'],lng=HUBS[rt['hub']]['lng']))
            timed.append(clock)
        wave_times.append(max(timed,default=0.))
        # Exactly R-1 fixed evaluation points, regardless of used trips.
        if r<c['rounds']-1:
            w=1/(1-c['a'])
            round_f3.append(sum(w*max(0.,c['a']-(row['stock']+cum[i])/row['demand'])
                                for i,row in enumerate(c['rows']) if row['remaining']>=c['delta']))
    f2=sum(wave_times);f3=sum(round_f3)
    results=[dict(index=i,name=row['name'],demandKits=row['demand'],stockKits=row['stock'],
                  deliveredKits=actual[i],coverageBefore=round(row['stock']/row['demand'],5),
                  coverageAfter=round((row['stock']+actual[i])/row['demand'],5),
                  visits=sum(i in rt['quantities'] for wave in routes for rt in wave),lat=row['lat'],lng=row['lng'])
             for i,row in enumerate(c['rows'])]
    used_hub=[sum(rt['kits'] for rt in real_routes if rt['hub']==h) for h in range(2)]
    return dict(status='feasible_under_eta0' if exact else 'evaluation_gap_with_eta0',
        isValidatedP2=exact,isGloballyOptimal=False,solver='capacity-feasible insertion + permutation GA / 2-opt / Or-opt (approximate)',
        message=('η=0の配分評価条件を検証済み（最適性は未証明）。' if exact else
                '車両・訪問・在庫の制約を満たす参考配送案ですが、η=0のP1評価条件を満たさず、厳密なP2実行可能解ではありません。'),
        f1Star=p1['f1'],f1Route=score,etaAssumed=0.,f1Excess=gap,rho=c['rho'],targetRate=c['a'],
        f2Minutes=round(f2,2),f3=round(f3,6),f3ByRound=[round(x,6) for x in round_f3],
        usedRounds=sum(x>0 for x in wave_times),maxRounds=c['rounds'],usedTrucks=len(active_vehicles),
        trucksConfigured=c['trucks'],trucksByHub=truck_counts,hubOutgoingKits=used_hub,
        visitedShelters=sum(r['visits']>0 for r in results),shelterCount=len(results),
        deliveredKits=sum(actual),availableKits=c['available'],
        roundTimesMinutes=[round(x,2) for x in wave_times],
        routes=real_routes,shelters=results,hubs=HUBS,
        assumptions={'kit':'レトルトご飯3食＋飲料水500ml6本','truckKg':2000,'kitKg':KIT_KG,
            'truckKits':TRUCK_CAP_KITS,'loadingMin':LOADING_MIN,'shelterPrepMin':PREP_MIN,
            'unloadingMinPerKit':UNLOADING_MIN_PER_KIT,'roadSpeedKmh':ROAD_SPEED_KMH,
            'travel':'市街地（マンハッタン）距離÷一般道想定20km/h：実道路のルート・到着時間ではない',
            'hubStocks':'総量から計画上で二拠点へ仮割当：実拠点在庫は未確認',
            'eta':'P0未計算のためη=0を暫定代入','stage':'24時間更新未連結、現時点の単一計画'})
