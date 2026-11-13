"""V2：訪問先・車両・配送回を固定したP1整数配送量の再最適化。

論文の経路変数を含む完全なP1ではなく、制限付きの整数混合計画である。
在庫と保守的な時間上限を再検証した場合だけ暫定解を更新する。
この部分問題の解法結果から全体の最小ηを証明したとは扱わない。"""
from __future__ import annotations
import math
import time
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix
from kit_planning import f1_score, LOADING_MIN, PREP_MIN, UNLOADING_MIN_PER_KIT, ROAD_SPEED_KMH


def improve_fixed_visit_quantities(c, p0, result, *, seconds=10.0, gap_percent=0.2):
    """訪問先・車両・配送回・拠点を保持して配分を改善する。
    
    正の配送量がある訪問ごとの整数キット数と最大不足度を決定する。
    現在のP1で用いる保守的な拠点往復時間と積込回数を反映する。"""
    report=dict(result)
    report.update(fixedVisitMILPAttempted=False, fixedVisitMILPImproved=False)
    if not result.get('feasible') or not result.get('assignment'):
        report['fixedVisitMILPNote']='実行可能なP1車両割当がないため未実行。'
        return report
    if c.get('visitWindows'):
        report['fixedVisitMILPNote']='訪問時間帯が設定されているため再配分を省略（到着時間との整合を優先）。'
        return report
    assignments=result['assignment'];rows=c['rows'];nrows=len(rows)
    visits=[(ai,int(v['index']),int(v['kits'])) for ai,ass in enumerate(assignments) for v in ass['visits']]
    if not visits:
        return report
    if any(i<0 or i>=nrows or q<c['delta'] for _,i,q in visits):
        report['fixedVisitMILPNote']='元の割当の検証に失敗したため未実行。'
        return report
    start=time.monotonic();m=len(visits);R=c['rounds'];T=c['trucks'];w=1/(1-c['a'])
    used_rounds=sorted({a['round'] for a in assignments})
    with_time=c.get('maxRoundMinutes') is not None or c.get('maxTotalMinutes') is not None
    rindex={r:m+1+j for j,r in enumerate(used_rounds)} if with_time else {}
    theta=m;nvar=m+1+len(rindex)
    obj=np.zeros(nvar);obj[theta]=1.
    lb=np.zeros(nvar);ub=np.full(nvar,np.inf);integ=np.zeros(nvar,dtype=np.intc)
    lb[theta]=-np.inf
    for vi,(_,i,_) in enumerate(visits):
        lb[vi]=c['delta'];ub[vi]=min(rows[i]['remaining'],c['fleet'][assignments[visits[vi][0]]['truck']-1]['capacityKits'])
        integ[vi]=1
        if rows[i]['demand']>0:obj[vi]=-c['rho']*w/rows[i]['demand']
    rr=[];cc=[];vv=[];lo=[];hi=[]
    def constraint(terms,low=-np.inf,high=np.inf):
        j=len(lo);lo.append(low);hi.append(high)
        for col,x in terms:
            if x:rr.append(j);cc.append(col);vv.append(float(x))
    constraint(((v,1) for v in range(m)),high=c['available'])
    by_shelter={i:[] for i in range(nrows)}
    by_assignment=[[] for _ in assignments]
    for vi,(ai,i,_) in enumerate(visits):
        by_shelter[i].append(vi);by_assignment[ai].append(vi)
    for i,inds in by_shelter.items():
        if not inds and rows[i]['remaining']>=c['delta']:
            # 訪問が固定されていても非訪問の活性施設はK+に属し、θの評価制約に含める。
            constraint([(theta,1)],
                       low=w*(c['a']-rows[i]['stock']/rows[i]['demand']))
        if not inds:continue
        constraint(((v,1) for v in inds),high=rows[i]['remaining'])
        if rows[i]['remaining']>=c['delta']:
            constraint([(theta,1)]+[(v,w/rows[i]['demand']) for v in inds],
                       low=w*(c['a']-rows[i]['stock']/rows[i]['demand']))
    for ai,ass in enumerate(assignments):
        t=ass['truck']-1
        constraint(((v,1) for v in by_assignment[ai]),high=c['fleet'][t]['capacityKits'])
    if c.get('hubStockKits') is not None:
        for h in (0,1):
            constraint(((v,1) for ai,ass in enumerate(assignments)
                if c['fleet'][ass['truck']-1].get('hub',0)==h for v in by_assignment[ai]),
                       high=c['hubStockKits'][h])
    # 訪問有無を固定すれば積込回数は確定するが、拠点往復の移動時間は引き続き保守的な近似である。
    if with_time:
        from p2_kit_optimizer import HUBS
        for r in used_rounds:
            ar=[ai for ai,ass in enumerate(assignments) if ass['round']==r]
            waves=max(math.ceil(sum(c['fleet'][assignments[ai]['truck']-1].get('hub',0)==h for ai in ar)
                            /c['loadingParallel'][h]) for h in (0,1))
            loading=LOADING_MIN*waves
            for ai in ar:
                ass=assignments[ai];hub=HUBS[c['fleet'][ass['truck']-1].get('hub',0)]
                star=0.
                for visit in ass['visits']:
                    s=rows[visit['index']]
                    km=abs(s['lat']-hub['lat'])*111.32+abs(s['lng']-hub['lng'])*111.32*math.cos(math.radians((s['lat']+hub['lat'])/2))
                    star+=PREP_MIN+2*km/ROAD_SPEED_KMH*60
                constraint([(rindex[r],1)]+[(vi,-UNLOADING_MIN_PER_KIT) for vi in by_assignment[ai]],
                           low=loading+star)
            if c.get('maxRoundMinutes') is not None:
                ub[rindex[r]]=c['maxRoundMinutes']
        if c.get('maxTotalMinutes') is not None:
            constraint(((idx,1) for idx in rindex.values()),high=c['maxTotalMinutes'])
    matrix=coo_matrix((vv,(rr,cc)),shape=(len(lo),nvar)).tocsr()
    report['fixedVisitMILPAttempted']=True
    try:
        solution=milp(obj,integrality=integ,bounds=Bounds(lb,ub),
           constraints=LinearConstraint(matrix,np.asarray(lo),np.asarray(hi)),
           options={'time_limit':float(seconds),
                    'mip_rel_gap':min(0.001,float(gap_percent)/100.),
                    'presolve':True})
    except Exception as exc:
        report['fixedVisitMILPNote']='追加MILPを実行できませんでした: '+str(exc)[:150]
        return report
    report['fixedVisitMILPSolverStatus']=int(solution.status)
    report['fixedVisitMILPSeconds']=round(time.monotonic()-start,3)
    gap=getattr(solution,'mip_gap',None)
    report['fixedVisitMILPSolverGap']=float(gap) if gap is not None and math.isfinite(float(gap)) else None
    if solution.x is None:
        report['fixedVisitMILPNote']='固定訪問MILPで改善候補なし。元の実行可能案を保持。'
        return report
    q=[int(round(v)) for v in solution.x[:m]]
    if any(abs(v-solution.x[j])>1e-5 or v<c['delta'] for j,v in enumerate(q)):
        report['fixedVisitMILPNote']='整数配送量の再検証に失敗。元の案を保持。'
        return report
    allocations=[0]*nrows
    updated=[]
    for ai,ass in enumerate(assignments):
        new=dict(ass)
        new['visits']=[dict(index=visits[vi][1],kits=q[vi]) for vi in by_assignment[ai]]
        new['loadKits']=sum(q[vi] for vi in by_assignment[ai])
        if new['loadKits']>c['fleet'][ass['truck']-1]['capacityKits']:
            return report
        updated.append(new)
    for vi,(_,i,_) in enumerate(visits):allocations[i]+=q[vi]
    if (sum(allocations)>c['available'] or
        any(x>row['remaining'] for x,row in zip(allocations,rows)) or
        any((not row['visited'] and row['remaining']>=c['delta'] and allocations[i]<c['delta']) for i,row in enumerate(rows))):
        return report
    if c.get('hubStockKits') is not None:
        if any(sum(ass['loadKits'] for ass in updated if c['fleet'][ass['truck']-1].get('hub',0)==h)>c['hubStockKits'][h] for h in (0,1)):
            return report
    if with_time:
        from p2_kit_optimizer import HUBS
        makespans=[]
        for r in range(1,R+1):
            ar=[ass for ass in updated if ass['round']==r]
            if not ar:
                makespans.append(0.);continue
            waves=max(math.ceil(sum(c['fleet'][ass['truck']-1].get('hub',0)==h for ass in ar)/c['loadingParallel'][h]) for h in (0,1))
            durations=[]
            for ass in ar:
                hub=HUBS[c['fleet'][ass['truck']-1].get('hub',0)]
                star=0.
                for visit in ass['visits']:
                    s=rows[visit['index']]
                    km=abs(s['lat']-hub['lat'])*111.32+abs(s['lng']-hub['lng'])*111.32*math.cos(math.radians((s['lat']+hub['lat'])/2))
                    star+=PREP_MIN+2*km/ROAD_SPEED_KMH*60
                durations.append(LOADING_MIN*waves+star+UNLOADING_MIN_PER_KIT*ass['loadKits'])
            makespans.append(max(durations))
        if (c.get('maxRoundMinutes') is not None and max(makespans)>c['maxRoundMinutes']+1e-5 or
            c.get('maxTotalMinutes') is not None and sum(makespans)>c['maxTotalMinutes']+1e-5):
            report['fixedVisitMILPNote']='保守的配送時間の検証に失敗。元の案を保持。'
            return report
    new_f1=float(f1_score(rows,allocations,c['a'],c['rho'],c['delta']))
    new_eta=max(0.,new_f1-float(p0['f1']))
    if not new_f1+1e-7<float(result['f1Feasible']):
        report['fixedVisitMILPNote']='既存の配分評価が改善候補以上のため、元の案を保持。'
        return report
    report.update(assignment=updated,plannedAdditions=allocations,
       f1Feasible=new_f1,etaUpperBound=new_eta,totalKits=sum(allocations),
       fixedVisitMILPImproved=True,
       fixedVisitMILPF1Before=float(result['f1Feasible']),
       fixedVisitMILPEtaBefore=float(result['etaUpperBound']),
       fixedVisitMILPNote='訪問先・車両・回を固定した追加整数MILPで配分評価を改善（全経路の最適性は未証明）。')
    report['reason']=(report.get('reason') or '')+' 固定訪問MILPで実行可能なη上界を改善。'
    # この制限付き問題によって全体最適性を証明することはできない。
    if report.get('certified'):
        report.update(certified=False,etaStar=None,status='feasible_upper_bound')
    return report
