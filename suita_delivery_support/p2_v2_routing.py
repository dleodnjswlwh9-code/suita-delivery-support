"""P2で車両間の訪問先交換を探索するV2の改善処理。

同じ拠点・同じ配送回の範囲で車両担当のみ変更し、配送量と配送回は固定する。
訪問先7か所以下ではHeld–Karp法で巡回順序を厳密に求め、
それ以上は探索回数を制限した2-optで改善する。
採用前にP2の制約検証を必ず実施する。全体最適性は保証しない。"""
from __future__ import annotations
import copy
import math
import time
from functools import lru_cache
from kit_planning import LOADING_MIN,PREP_MIN,UNLOADING_MIN_PER_KIT


def improve_vehicle_exchanges(clean, seed, *, max_seconds=11., max_checks=250000, max_steps=85):
    from p2_kit_optimizer import (route_drive,validate_plan,schedule_and_check)
    routes,mat,counts,actual=seed
    if clean.get('visitWindows'):
        return None,dict(reason='訪問時間帯があるため車両間交換は省略。')
    if clean['trucks']<2:
        return None,dict(reason='交換可能な別車両がありません。')
    start=time.monotonic();work=copy.deepcopy(routes)
    @lru_cache(maxsize=3000)
    def best_tour(hub,nodes):
        nodes=list(nodes);n=len(nodes)
        if not n:return (0.,())
        def drive(path):return route_drive(path,hub,mat)
        if n<=7:
            # 非対称な時間行列を考慮し、所与の拠点を出発・帰着する最短巡回を求める。
            dp={}
            for i in range(n):dp[(1<<i,i)]=(mat[hub][nodes[i]+2],(i,))
            for mask in range(1,1<<n):
                for end in range(n):
                    pair=(mask,end)
                    if pair not in dp:continue
                    cost,seq=dp[pair]
                    for j in range(n):
                        if mask&(1<<j):continue
                        key=(mask|(1<<j),j)
                        value=cost+mat[nodes[end]+2][nodes[j]+2]
                        if key not in dp or value<dp[key][0]-1e-10:
                            dp[key]=(value,seq+(j,))
            mask=(1<<n)-1
            best=min((dp[(mask,j)][0]+mat[nodes[j]+2][hub],dp[(mask,j)][1]) for j in range(n))
            return best[0],tuple(nodes[j] for j in best[1])
        # 大きな経路は決定的な近似探索を使い、厳密な最短巡回の証明はしない。
        paths=[]
        for first in (min(nodes,key=lambda x:mat[hub][x+2]),
                      min(nodes,key=lambda x:mat[x+2][hub])):
            path=[first];remaining=set(nodes)-{first}
            while remaining:
                choice=min((mat[(path[pos-1]+2) if pos else hub][i+2]+
                            mat[i+2][path[pos]+2 if pos<len(path) else hub]-
                            mat[(path[pos-1]+2) if pos else hub][path[pos]+2 if pos<len(path) else hub],
                            i,pos)
                           for i in remaining for pos in range(len(path)+1))
                _,i,pos=choice;path.insert(pos,i);remaining.remove(i)
            paths.append(path)
        path=min(paths,key=drive)
        for _ in range(3):
            cur=drive(path);best=None
            for a in range(n):
                for b in range(a+1,n):
                    trial=path[:a]+list(reversed(path[a:b+1]))+path[b+1:]
                    score=drive(trial)
                    if score+1e-7<cur:cur=score;best=trial
            for a in range(n):
                for b in range(n):
                    if a==b:continue
                    trial=path.copy();v=trial.pop(a);trial.insert(b,v)
                    score=drive(trial)
                    if score+1e-7<cur:cur=score;best=trial
            if best is None:break
            path=best
        return drive(path),tuple(path)

    def route_time(rt):
        if not rt['stops']:return 0.
        return (PREP_MIN*len(rt['stops'])+
            UNLOADING_MIN_PER_KIT*rt['load']+
            min(route_drive(rt['stops'],rt['hub'],mat),
                best_tour(rt['hub'],tuple(sorted(rt['stops'])))[0]))
    def round_cost(wave,override=None,base_times=None):
        active=[(override or {}).get(rt['truck'],rt) for rt in wave]
        active=[rt for rt in active if rt['stops']]
        if not active:return 0.,0.,0.
        waves=max(math.ceil(sum(rt['hub']==h for rt in active)/clean['loadingParallel'][h]) for h in (0,1))
        base=LOADING_MIN*waves
        scores=[(base_times[rt['truck']-1] if base_times is not None and
                    (override is None or rt['truck'] not in override) else route_time(rt))
                for rt in active]
        return (base+max(scores),sum(scores)+len(active)*base,
                sum(max(0.,x+base-155.)**2 for x in scores))

    # 訪問先や配送量を変更せず、訪問順序のみを改善する。
    initial_order_moves=0
    for wave in work:
        for rt in wave:
            if not rt['stops']:continue
            old=route_drive(rt['stops'],rt['hub'],mat)
            better,order=best_tour(rt['hub'],tuple(sorted(rt['stops'])))
            if better+1e-8<old:
                rt['stops']=list(order);initial_order_moves+=1
    vehicle_times=[[route_time(rt) for rt in wave] for wave in work]
    base_round=[round_cost(wave,base_times=vehicle_times[r]) for r,wave in enumerate(work)]
    current_f2=sum(x[0] for x in base_round)
    start_f2=current_f2
    best_plan=copy.deepcopy(work);best_f2=current_f2
    steps=0;checks=0
    # 同じ配送回・拠点で訪問先を交換し、配送量・回次・F3を変えずに探索する。
    while steps<max_steps and checks<max_checks and time.monotonic()-start<max_seconds:
        best=None
        penalty_sum=sum(x[2] for x in base_round)
        best_quality=current_f2+1e-4*penalty_sum
        for r,wave in enumerate(work):
            if time.monotonic()-start>=max_seconds or checks>=max_checks:break
            for src in wave:
                if not src['stops']:continue
                for dst in wave:
                    if src is dst or src['hub']!=dst['hub']:continue
                    if checks>=max_checks or time.monotonic()-start>=max_seconds:break
                    dest_total=dst['load'];src_total=src['load']
                    for i in list(src['stops']):
                        if checks>=max_checks or time.monotonic()-start>=max_seconds:break
                        qi=src['quantities'][i]
                        choices=[('move',None)] if dest_total+qi<=dst['capacityKits'] else []
                        for j in dst['stops']:
                            qj=dst['quantities'][j]
                            if (src_total-qi+qj<=src['capacityKits'] and
                                dest_total-qj+qi<=dst['capacityKits']):
                                choices.append(('swap',j))
                        for kind,j in choices:
                            if checks>=max_checks or time.monotonic()-start>=max_seconds:break
                            checks+=1
                            ns=dict(src,stops=[v for v in src['stops'] if v!=i],
                                    quantities={k:v for k,v in src['quantities'].items() if k!=i},load=src_total-qi)
                            nd=dict(dst,stops=list(dst['stops']),quantities=dict(dst['quantities']),load=dest_total)
                            if kind=='move':
                                nd['stops'].append(i);nd['quantities'][i]=qi;nd['load']+=qi
                            else:
                                qj=nd['quantities'].pop(j);nd['stops'].remove(j);nd['load']-=qj
                                ns['stops'].append(j);ns['quantities'][j]=qj;ns['load']+=qj
                                nd['stops'].append(i);nd['quantities'][i]=qi;nd['load']+=qi
                            nround,nvehicle,npenalty=round_cost(
                                wave,{src['truck']:ns,dst['truck']:nd},vehicle_times[r])
                            new_f2=current_f2-base_round[r][0]+nround
                            new_quality=(new_f2+1e-4*(penalty_sum-base_round[r][2]+npenalty))
                            if new_quality<best_quality-1e-6:

                                if (clean['maxRoundMinutes'] is not None and nround>clean['maxRoundMinutes']+1e-6 or
                                  clean['maxTotalMinutes'] is not None and new_f2>clean['maxTotalMinutes']+1e-6):
                                    continue
                                best=(r,src['truck'],dst['truck'],ns,nd,nround,nvehicle,npenalty,new_f2)
                                best_quality=new_quality
        if best is None:break
        r,src_id,dst_id,ns,nd,nround,nvehicle,npenalty,new_f2=best
        wave=work[r]
        for t,updated in ((src_id,ns),(dst_id,nd)):
            rt=wave[t-1]
            rt.update(stops=list(updated['stops']),quantities=dict(updated['quantities']),load=updated['load'])
            if rt['stops']:
                better,order=best_tour(rt['hub'],tuple(sorted(rt['stops'])))
                if better+1e-8<route_drive(rt['stops'],rt['hub'],mat):
                    rt['stops']=list(order)
        vehicle_times[r][src_id-1]=route_time(wave[src_id-1])
        vehicle_times[r][dst_id-1]=route_time(wave[dst_id-1])
        base_round[r]=(nround,nvehicle,npenalty);current_f2=new_f2;steps+=1
        if current_f2<best_f2-1e-6:
            best_f2=current_f2;best_plan=copy.deepcopy(work)
    work=best_plan
    try:
        validate_plan(clean,work,actual)
        sched,_=schedule_and_check(clean,work,mat)
        if abs(sum(sched)-best_f2)>1e-5:
            # 積込回数の算定は通常の配送計画と同じ方法を用いる。
            raise ValueError('配送所要時間の独立再計算に差があります。')
    except (Exception) as exc:
        return None,dict(reason='改善候補の検証に失敗: '+str(exc)[:160],checks=checks,steps=steps)
    if not steps and not initial_order_moves:
        return None,dict(reason='改善可能な近傍解なし。',checks=checks,steps=0)
    return (work,mat,counts,actual),dict(
        checked=True,checks=checks,exchangeSteps=steps,orderImprovements=initial_order_moves,
        previousF2=start_f2,improvedF2=sum(sched),seconds=round(time.monotonic()-start,2),
        note='固定配送量・同一回・同一拠点の車両間交換（経路全体の最適性は未証明）。')
