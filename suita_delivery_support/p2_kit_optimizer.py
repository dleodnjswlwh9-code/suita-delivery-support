"""整数キットによるP2経路計画の検証可能な実装。

論文のF2・F3と訪問・車両制約を扱うが、100施設の全体最適解は主張しない。
P1の最適性とP2の近似経路探索を区別して報告し、
2拠点の在庫・道路閉鎖・時間制限をそれぞれ確認する。"""
from __future__ import annotations
import math
import copy
import random
from collections import defaultdict
from p1_kit_optimizer import optimize_p1_kits, p1_problem_signature
from kit_planning import (clean_input,solve_p0,round_integer_p0,f1_score,
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
    """拠点から避難所を順に訪問し、同じ拠点に戻る方向別走行時間を計算する。
    
    往路には避難所間の移動を含め、復路は最後の避難所から拠点への移動とする。
    経路改善とF2の計算の双方で使用する。"""
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
    """訪問順序を遺伝的アルゴリズムと2-optで改善する。
    
    車両・配送回・物資量は別の容量確認済み処理で決められている。
    得られる経路の全体最適性は保証しない。"""
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
            p0,p2=rng.sample(elite,2)
            a,b=sorted(rng.sample(range(n),2))
            child=[None]*n;child[a:b]=p0[a:b]
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
    # 訪問先を1件ずつ移動させる局所改善も行う。
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
    # 拠点の選択には往路と復路の両方の時間を考慮する。
    distance=[[mat[h][i+2]+mat[i+2][h] for h in range(2)] for i in range(len(rows))]
    assignment=[min(range(2),key=lambda h:distance[i][h]) for i in range(len(rows))]
    if clean['fleet'] and all('hub' in v for v in clean['fleet']):
        # 車両所属拠点と拠点在庫は利用者の設定値を守り、勝手に車両配分を変えない。
        counts=[sum(v['hub']==h for v in clean['fleet']) for h in (0,1)]
        cap=[R*sum(v['capacityKits'] for v in clean['fleet'] if v['hub']==h) for h in (0,1)]
        if clean.get('hubStockKits') is not None:
            cap=[min(cap[h],clean['hubStockKits'][h]) for h in (0,1)]
        usable=[h for h in (0,1) if cap[h]>0]
        if not usable:
            raise KitInputError('拠点の車両または在庫がありません。')
        assignment=[min(usable,key=lambda h:distance[i][h]) for i in range(len(rows))]
        def load(h):return sum(additions[i] for i,a in enumerate(assignment) if a==h)
        for _ in range(len(rows)*2):
            bad=[h for h in (0,1) if load(h)>cap[h]]
            if not bad:break
            h=bad[0];other=1-h
            options=[i for i,a in enumerate(assignment) if a==h and additions[i]>0
                     and load(other)+additions[i]<=cap[other]]
            if not options:break
            i=min(options,key=lambda k:(distance[k][other]-distance[k][h])/max(1,additions[k]))
            assignment[i]=other
        if any(load(h)>cap[h] for h in (0,1)):
            raise KitInputError('拠点別の車両容量・在庫で物資を運べません。車両台数・在庫・配送回数を確認してください。')
        return assignment,counts
    if T==1:
        best_h=min((0,1),key=lambda h:sum(additions[i]*distance[i][h] for i in range(len(rows))))
        assignment=[best_h]*len(rows)
        counts=[int(best_h==0),int(best_h==1)]
        return assignment,counts
    # 拠点別の必要配送回数を概算するが、実在庫の配分が確定したと仮定しない。
    amounts=[sum(additions[i] for i,x in enumerate(assignment) if x==h) for h in range(2)]
    counts=[max(1,round(T*amounts[0]/max(1,sum(amounts)))),0]
    counts[0]=min(T-1,counts[0]);counts[1]=T-counts[0]
    # 片方の拠点に訪問可能回数が足りない場合、境界付近の需要を再割当する。
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
    """配送量とF3を変えずに、各配送回の最大帰着時間F2を局所的に改善する。"""
    if sum(bool(r['stops']) for r in wave)<2:return
    for _ in range(32):
        durations=[route_total(rt,mat) for rt in wave]
        baseline=max(durations)
        critical=[rt for rt,time in zip(wave,durations) if time>=baseline-0.01]
        best=None;best_value=baseline
        for origin in critical:
            for target in wave:
                if target is origin or target['hub']!=origin['hub']:continue
                # 同じ配送回の中で一つの避難所の担当車両を変更する。
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
                    # 車両容量を守れる二つの避難所配送を交換する。
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
    """貪欲法が生成した最小配送単位未満の追加配送を修正する。
    
    既存訪問先への追加、他の訪問先の移動、または別回への配送量振替を試みる。"""
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
                # 同一回の同一施設への訪問は1台まで。ただし元の訪問を削除する移動は許容する。
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
    if all('hub' in v for v in clean['fleet']):
        truck_hubs=[v['hub'] for v in clean['fleet']]
    else:
        truck_hubs=[h for h in range(2) for _ in range(counts[h])]
    routes=[[dict(round=r+1,truck=t+1,hub=truck_hubs[t],stops=[],quantities={},load=0,
                  capacityKits=clean['fleet'][t]['capacityKits'],vehicleType=clean['fleet'][t]['type'])
             for t in range(T)] for r in range(R)]
    assigned=[0]*n
    # まだ訪問していない避難所への初回配送を必須とする。
    mandatory=[i for i,row in enumerate(clean['rows']) if additions[i]>0 and not row['visited']]
    mandatory.sort(key=lambda i:(-min(mat[0][i+2]+mat[i+2][0],mat[1][i+2]+mat[i+2][1]),-additions[i]))
    for i in mandatory:
        cand=[]
        for r in range(R):
            for t in range(T):
                route=routes[r][t]
                if route['hub']!=hubs[i] or route['load']+clean['delta']>TRUCK_CAP_KITS:continue
                inc,pos=insert_best(route,i,mat)
                # 走行時間への影響に早い配送回をわずかに優先する評価を加える。
                est=max(route_total(q,mat) for q in routes[r])
                obj=max(est,route_total(route,mat)+inc+PREP_MIN+(LOADING_MIN if not route['stops'] else 0))+r*1000
                cand.append((obj,r,t,pos))
        if not cand:
            raise KitInputError('フィードバック制約により必須訪問の経路を作れません。')
        _,r,t,pos=min(cand)
        route=routes[r][t]
        route['stops'].insert(pos,i);route['quantities'][i]=clean['delta']
        route['load']+=clean['delta'];assigned[i]+=clean['delta']
    # 残余キット量は容量を満たす車両のうち早い配送回から割り当てる。
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
                # 同じ回に同じ避難所を2台が訪問しないよう、必要に応じて他の訪問先を移動し容量を確保する。
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
    """貪欲法で割当できない小・中規模問題の車両容量割当を厳密に確認する。
    
    証明対象は積載・割当の実行可能性であり、P1やP2の経路最適性ではない。
    適用できない場合や時間内に実行可能性が判定できない場合は結果を返さない。"""
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
    # 容量調整に使う拠点間の費用には復路も含める。
    dist=[[mat[h][i+2]+mat[i+2][h] for h in range(2)] for i in positive]
    expected=sum(additions[i]*(dist[k][0]<=dist[k][1]) for k,i in enumerate(positive))
    best_north=round(T*expected/max(1,sum(additions)))
    if T==1: candidates=[0,1]
    else: candidates=sorted(range(T+1), key=lambda v:(abs(v-best_north), v))
    slots=T*R
    # 物資を車両と配送回の組に割り当て、容量制約を課す。車両の所属拠点は全回で固定する。
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
    fixed_hubs=([v['hub'] for v in clean['fleet']]
                if all('hub' in v for v in clean['fleet']) else None)
    if fixed_hubs is not None:candidates=[sum(h==0 for h in fixed_hubs)]
    for north in candidates:
        truck_hubs=fixed_hubs if fixed_hubs is not None else [0]*north+[1]*(T-north)
        costs=[]
        for ii,i in enumerate(positive):
            for r in range(R):
                for t in range(T):
                    h=truck_hubs[t]
                    # 早い配送回への出動を優先し、走行距離の概算を抑える。
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


def build_p1_seed_routes(clean, p1, mat):
    """実行可能なP1の車両・回次・配送量を基に拠点帰着経路を構成する。
    
    F1と各訪問を維持する。ただし実道路・閉鎖道路の可用性や時間条件は
    別途検証が必要である。"""
    n=len(clean['rows']);T=clean['trucks'];R=clean['rounds']
    by_truck=[[] for _ in range(T)]
    for assignment in p1['assignment']:
        by_truck[assignment['truck']-1].extend(v['index'] for v in assignment['visits'])
    # 拡張条件ではP1とP2の両方で車両の実際の所属拠点を固定する。
    truck_hubs=[]
    for t,stops in enumerate(by_truck):
        hub=(clean['fleet'][t]['hub'] if 'hub' in clean['fleet'][t] else
             min((0,1),key=lambda h:sum(mat[h][i+2]+mat[i+2][h] for i in stops)))
        truck_hubs.append(hub)
    routes=[[dict(round=r+1,truck=t+1,hub=truck_hubs[t],stops=[],quantities={},load=0,
                  capacityKits=clean['fleet'][t]['capacityKits'],vehicleType=clean['fleet'][t]['type'])
             for t in range(T)] for r in range(R)]
    additions=[0]*n
    for assignment in p1['assignment']:
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
    """同時積込と施設別の訪問時間帯を考慮して候補経路を検証する。
    
    時刻は全配送回の開始からの経過分で、開設前の待機を許容する。
    拠点への帰着までをF2に含める。候補経路の検証であり全体最適性の証明ではない。"""
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
    """最終回を除く各回の終了後に残る不足度を加算する。
    
    評価期間はRmaxに固定し、実際に使用しなかった回の残余不足も計上する。
    途中終了を理由に不足量の評価が小さくならないようにする。"""
    cum=[0]*len(clean['rows']);total=0.
    weight=1/(1-clean['a'])
    for r,wave in enumerate(routes):
        for rt in wave:
            for i,q in rt['quantities'].items():cum[i]+=q
        if r<len(routes)-1:
            total+=sum(weight*max(0.,clean['a']-(row['stock']+cum[i])/row['demand'])
                for i,row in enumerate(clean['rows']) if row['remaining']>=clean['delta'] and row['demand']>0)
    return float(total)



def diversified_p1_route_candidates(clean, seed):
    """単一のP1初期経路に限定せず、実行可能なP2候補を探索する。
    
    施設ごとの整数物資量と所属拠点を保持し、訪問順や同じ車両の配送回を変える。
    採用前に時間・容量・在庫・F1の制約を再検証する。"""
    base,mat,counts,additions=seed
    # 車両内の訪問順序を遺伝的アルゴリズムと2-optで改善し、訪問回と在庫は保持する。
    ga=copy.deepcopy(base)
    for wave in ga:
        for rt in wave: improve_ga_route(rt,mat)
        balance_round_makespan(wave,mat)
    yield 'P1-MILP-incumbent-GA-and-2opt', (ga,mat,counts,additions)

    if clean['rounds']<2:
        return
    # 同じ車両の配送回だけを変更する候補を作成する。物資量・拠点・容量は変更せず、必ず改善するとは限らない。遅延配送はF3で評価する。
    for ratio,label in ((.35,'35'),(.55,'55')):
        waves=copy.deepcopy(ga)
        moved=0
        # 最初に使われる配送回を連続した二つの回に分割する。
        for rt in waves[0]:
            if len(rt['stops'])<2:continue
            target=waves[1][rt['truck']-1]
            if target['hub']!=rt['hub'] or target['stops']:continue
            size=min(len(rt['stops'])-1,max(1,round(len(rt['stops'])*ratio)))
            # 遠方の訪問先を単純に分離せず交互に振り分け、2-optで経路を改善する。
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
        yield 'P1-MILP-round-split-'+label+'pct', (waves,mat,counts,additions)


def _checked_route_candidate(clean, method, route_bundle):
    routes,mat,counts,actual=route_bundle
    validate_plan(clean,routes,actual)
    round_times,_=schedule_and_check(clean,routes,mat)
    # 論文式(44)に従い、F2は各配送回の最大所要時間の合計とする。
    return dict(method=method,bundle=route_bundle,
        f1=float(f1_score(clean['rows'],actual,clean['a'],clean['rho'],clean['delta'])),
        f2=float(sum(round_times)),totalMinutes=float(sum(round_times)),
        maxRoundMinutes=float(max(round_times,default=0.)),
        f3=candidate_f3(clean,routes))


def _valid_reused_p1(data,clean,p0,prior):
    """入力条件が完全に一致する場合のみサーバー保存済みP1結果を再利用する。
    
    ブラウザから渡された任意の結果は使用せず、訪問割当と保守的な時間条件を
    検証する。古い結果や矛盾のある結果は破棄する。"""
    if not isinstance(prior,dict) or not prior.get('feasible') or not prior.get('assignment'):
        return False
    if prior.get('p1InputSignature')!=p1_problem_signature(data,clean=clean):
        return False
    if abs(float(prior.get('f1Star',float('inf')))-p0['f1'])>1e-6:
        return False
    try:
        trial=build_p1_seed_routes(clean,prior,time_matrix(clean['rows']))
        routes,mat,_,additions=trial
        scheduled,_=schedule_and_check(clean,routes,mat)
        if any(not isinstance(x,int) or x<0 for x in additions):return False
        if additions!=prior['plannedAdditions']:return False
        f1=f1_score(clean['rows'],additions,clean['a'],clean['rho'],clean['delta'])
        if abs(f1-float(prior['f1Feasible']))>1e-6:return False
        if abs(max(0.,f1-p0['f1'])-float(prior['etaUpperBound']))>1e-6:return False
        return True
    except (KitInputError,IndexError,KeyError,TypeError,ValueError,OverflowError):
        return False


def optimize_p2_kit(data, driving_matrix=None, matrix_source=None, matrix_note=None, p1_result=None):
    if (data or {}).get('roadMode', 'all') != 'all':
        raise KitInputError('緊急交通路優先は現在未実装です。すべての道路を利用してください。')
    c=clean_input(data);p0=solve_p0(c)
    # P1の公平性は元の施設別に評価し、P2では需要を統合せず代表点を訪問座標として使える。
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
    # P0の理想評価値を引き継ぐ際は、入力条件が同一であることを確認する。
    reference=(data or {}).get('p0ReferenceF1')
    if reference is not None:
        try:reference=float(reference)
        except (TypeError,ValueError,OverflowError):
            raise KitInputError('P0の評価値が不正です。配分計画を再計算してください。')
        if not math.isfinite(reference) or abs(reference-p0['f1'])>max(1e-5,1e-7*abs(p0['f1'])):
            raise KitInputError('P0とP2の入力条件が一致しません。希求水準・在庫・避難者数・配送条件を確認して配分計画から再計算してください。')
    # P1とP2で施設の統合状態を一致させる。実行可能なP1案の評価値は上界であり、最適性を証明しない。
    p1_reused=_valid_reused_p1(data,c,p0,p1_result)
    p1=p1_result if p1_reused else optimize_p1_kits(data,clean=c,p0=p0)
    if not p1.get('feasible'):
        raise KitInputError('P1で実行可能な配分案を得られませんでした。条件を確認してP1から再計算してください。')
    mat=driving_matrix if driving_matrix is not None else time_matrix(route_clean['rows'])
    delta_f1=float((data or {}).get('p2DeltaF1',0) or 0)
    if not math.isfinite(delta_f1) or not 0<=delta_f1<=10:
        raise KitInputError('P2の許容幅Δは0～10の数値で入力してください。')
    candidates=[];candidate_errors=[]
    try:
        if any(v['type']=='4t' for v in c['fleet']):
            raise KitInputError('混合車種はP1のMILP割当を用います。')
        xs=round_integer_p0(c,p0)
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
        seed=build_p1_seed_routes(route_clean,p1,mat)
        candidates.append(_checked_route_candidate(route_clean,'P1-MILP-incumbent-route-seed',seed))
        # V2では改善済みの経路から開始し、配送量を保持したまま同一拠点・同一回の車両間で訪問先を交換する。
        ga_candidate=None
        for method,variant in diversified_p1_route_candidates(route_clean,seed):
            try:
                candidates.append(_checked_route_candidate(route_clean,method,variant))
                if ga_candidate is None:ga_candidate=variant
            except KitInputError as error:candidate_errors.append(method+': '+str(error)[:100])
        if ga_candidate is not None:
            from p2_v2_routing import improve_vehicle_exchanges
            exchanged,exchange_info=improve_vehicle_exchanges(route_clean,ga_candidate)
            if exchanged is not None:
                candidates.append(_checked_route_candidate(route_clean,
                    'P1-vehicle-exchange-v2',exchanged))
    except KitInputError as error:candidate_errors.append(str(error))
    if not candidates:
        raise KitInputError('配送条件を満たす経路を構成できませんでした。'+(' '.join(candidate_errors)[:240] if candidate_errors else ''))
    # 時間超過の経路は絶対に確定案にしない。η*が未証明の場合はP1の上界を基準にする。
    allowed=float(p1['f1Feasible'])+delta_f1+1e-5
    within=[opt for opt in candidates if opt['f1']<=allowed]
    if not within:
        raise KitInputError('P1配分評価の許容上限を守る配送経路を作成できません。'
            ' Δを変更するかP1を再計算してください。超過案は最終計画として採用しません。')
    # F2を優先し、同点の場合はF3とF1で判定する近似的な辞書式候補比較。全体のパレート最適性は保証しない。
    best=min(within,key=lambda opt:(round(opt['f2'],6),opt['f3'],opt['f1']))
    assignment_method=best['method']
    routes,mat,truck_counts,actual=best['bundle']
    scheduled_round_times,scheduled_visits=schedule_and_check(c,routes,mat)
    score=best['f1']
    gap=max(0.,score-p0['f1'])
    bound_satisfied=bool(score<=float(p1['f1Feasible'])+delta_f1+1e-5)
    certified_basic=bool(p1.get('certified') and bound_satisfied)
    # P2でより良い上界が得られても元のP1整数計画とは異なる場合がある。P1のF1やηを勝手に変更しない。
    p2_better_than_p1=score+1e-6<float(p1['f1Feasible'])
    p2_eta_upper=min(float(p1['etaUpperBound']),gap)
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
            # すべての訪問が終わっても、車両が拠点に帰着するまで配送回は完了しない。
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
        # 固定評価期間では使用しなかった回も最終回以外は不足度を計上する。
        if r<len(routes)-1:
            w=1/(1-c['a'])
            round_f3.append(sum(w*max(0.,c['a']-(row['stock']+cum[i])/max(1,row['demand']))
                                for i,row in enumerate(c['rows']) if row['remaining']>=c['delta']))
    f2=sum(wave_times);total_time=f2;f3=sum(round_f3)
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
    return dict(p2AlgorithmRevision=83,preservedFacilityEvaluation=True,deliveryPointCount=len(set(r.get('deliveryPointName',r['name']) for r in route_clean['rows'])),p1Reused=p1_reused,p2CandidateCount=len(candidates),
        p2WithinBoundCount=len(within),p2CandidatePareto=pareto,
        p2SelectionRule='F2=各配送回の所要時間の合計（論文式(44)）を最小化、同点はF3（固定期間R_max）→F1で判定（全体最適性は未証明）',
        p2ImprovesEtaBound=p2_better_than_p1,p2BestVerifiedEtaUpperBound=p2_eta_upper,
        status=('basic_p1_bound_within_tolerance' if certified_basic else
                        'basic_p1_incumbent_bound' if bound_satisfied else
                        'p1_not_certified_or_bound_not_met'),
        isValidatedP2=False,isValidatedBasicP2=certified_basic,
        verifiedRouteConstraints=True,hubStockKits=c.get('hubStockKits'),maxRoundMinutes=c.get('maxRoundMinutes'),maxTotalMinutes=c.get('maxTotalMinutes'),
        loadingParallel=c.get('loadingParallel'),visitWindowsCount=len(c.get('visitWindows') or {}),
        p1BoundSatisfied=bound_satisfied,isGloballyOptimal=False,
        solver='P1は訪問先固定の整数再最適化、P2は遺伝的アルゴリズム・短距離の厳密巡回・車両間交換による近似探索',
        assignmentMethod=assignment_method,roadTimeSource=matrix_source or 'manhattan-20kmh',
        roadTimeNote=matrix_note or ('Google道路時間行列による参考評価' if driving_matrix is not None else 'マンハッタン距離÷20km/hによる暫定推定'),
        minimumRequiredKits=c['delta']*p0['mandatory'],
        mandatoryShelters=p0['mandatory'],microShelters=sum(0<row['remaining']<c['delta'] for row in c['rows']),
        zeroDemandShelters=sum(row['demand']==0 for row in c['rows']),
        message=('配送ルートの積載量・拠点別在庫・時間条件を検証済み。経路最適性は未証明。' if certified_basic else
                 '基本P1の実行可能な評価上界内で配送案を構成。P1最小ギャップの証明・経路最適性は未確認。' if bound_satisfied else
                 'P1の配分評価上限を守る経路のみ確定。'),
        f1Star=p0['f1'],f1Route=score,etaAssumed=p1.get('etaUpperBound'),
        etaStar=p1.get('etaStar'),p1=p1,p2DeltaF1=delta_f1,f1Excess=gap,
        rho=c['rho'],targetRate=c['a'],
        f2Minutes=round(f2,2),totalCompletionMinutes=round(total_time,2),f2Definition='sum_round_makespan',
        longestRoundMinutes=round(max(wave_times,default=0.),2),f3=round(f3,6),f3ByRound=[round(x,6) for x in round_f3],
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
            'arrival':'各車両は出発拠点に必ず帰着。F2は各配送回の最長帰着時間の合計（論文式(44)）。最長の1回は別表示',
            'eta':'施設別F1は100施設ごとに評価し、P1で得られた上界を遵守。最適性は未証明の場合あり。',
            'deliveryGroups':'代表点は配送の訪問座標のみ変更。複数施設の総需要・配分評価は統合しない。停車・荷卸し未検証。',
            'stage':'実績確定後は次期P0→P1→P2を再計算。避難者数は実績データがなければ据置' })
