"""P1: 目標供給率（希求水準）に基づく線形計画。

v23 is a *planning trial*. Physical delivery, mandatory-visit/minimum-delivery
constraints and multi-commodity vehicle coupling are explicitly NOT resolved
until P0/P2. This module only computes the ideal P1 achievement function.

Per commodity and stage, x_k is NEW allocation, b_k is already secured
supply (stored stock + previous *planned* allocation in this prototype),
d_k is demand, a_k the aspiration level, w_k=1/(1-a_k).
F1 = theta + rho * sum_k w_k*(a_k - (b_k+x_k)/d_k),
theta >= w_k*(a_k-(b_k+x_k)/d_k).
For P1: 0<=x_k<=max(0,d_k-b_k), sum x_k <= supply.
"""
from __future__ import annotations
import math

class P1InputError(ValueError):
    pass


def solve_p1(rows, available_kg, rho):
    if not isinstance(rows, list) or not rows or len(rows) > 500:
        raise P1InputError('避難所数を確認してください（1～500件）。')
    try:
        supply = float(available_kg)
        rho = float(rho)
    except (TypeError, ValueError):
        raise P1InputError('供給量とρは数値で入力してください。')
    if not math.isfinite(supply) or supply < 0 or supply > 1e12:
        raise P1InputError('供給量は0以上の有効な数値にしてください。')
    if not math.isfinite(rho) or not 0 < rho <= 1:
        raise P1InputError('ρは0より大きく1以下で指定してください。')

    prepared = []
    for pos, row in enumerate(rows):
        if not isinstance(row, dict):
            raise P1InputError(f'{pos+1}番目の避難所データが不正です。')
        try:
            demand = float(row['demandKg'])
            already = float(row['securedKg'])
            target = float(row['targetRate'])
        except (ValueError, TypeError, KeyError):
            raise P1InputError(f'{pos+1}番目の避難所：需要量・確保量・希求水準を確認してください。')
        if not all(map(math.isfinite, (demand, already, target))):
            raise P1InputError(f'{pos+1}番目の避難所に無効な数値があります。')
        if demand < 0 or already < 0 or demand > 1e12 or already > 1e12:
            raise P1InputError(f'{pos+1}番目の避難所：負の数量は使用できません。')
        if target < 0 or target >= 1:
            raise P1InputError(f'{pos+1}番目の避難所：希求水準は0%以上100%未満にしてください。')
        prepared.append((demand, already, target))

    active = [(idx, d, min(b, d), a) for idx, (d, b, a) in enumerate(prepared)
              if d > 0 and b < d - 1e-9]
    # Objective constants from fully satisfied (but positive-demand) shelters
    # must remain in the aggregate augmentation term.
    valid = [(idx, d, min(b, d), a) for idx,(d,b,a) in enumerate(prepared) if d > 0]

    if not active:
        allocations = [0.0]*len(prepared)
        min_rate = min((min(1, b/d) for d,b,_ in prepared if d>0),default=1.)
        return {'allocationsKg':allocations,'usedKg':0.0,'unusedKg':supply,
                'minimumRateBefore':min_rate,'minimumRate':min_rate,
                'objectiveF1':None,'theta':None,'rho':rho,
                'note':'追加供給を必要とする避難所がないためP1最適化は省略しました。'}

    # The original paper minimizes F1 over shelters with positive remaining
    # demands; rows already at 100% still enter the summation term as constants.
    from scipy.optimize import linprog
    n=len(active)
    c=[-rho/(1-a)/d for _,d,b,a in active]+[1.0]
    A_ub=[]; b_ub=[]
    # Supply budget
    A_ub.append([1.0]*n+[0.0]); b_ub.append(supply)
    for j,(idx,d,b,a) in enumerate(active):
        w=1/(1-a)
        constraint=[0.0]*(n+1)
        constraint[j]=-w/d
        constraint[-1]=-1.0
        A_ub.append(constraint)
        b_ub.append(-w*(a-b/d))
    bounds=[(0.0,max(0.0,d-b)) for _,d,b,a in active]+[(None,None)]
    solved=linprog(c,A_ub=A_ub,b_ub=b_ub,bounds=bounds,method='highs',
                   options={'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
    if not solved.success:
        raise P1InputError(f'P1の最適化に失敗しました（{solved.message}）。入力条件を確認してください。')
    result=[0.0]*len(prepared)
    for j,(idx,d,b,a) in enumerate(active):
        result[idx]=max(0.0,min(d-b,float(solved.x[j])))
    used=sum(result)
    if used > supply + 1e-5:
        raise P1InputError('P1の計算誤差が許容範囲を超えました。')
    # Evaluate on capped secured amounts to avoid initial stock > demand.
    score_terms=[(1/(1-a))*(a - (min(b,d)+result[idx])/d)
                 for idx,(d,b,a) in enumerate(prepared) if d>0]
    theta=max((1/(1-a))*(a-(b+result[idx])/d) for idx,d,b,a in active)
    f1=theta+rho*sum(score_terms)
    min_before=min((min(1,b/d) for d,b,a in prepared if d>0),default=1.)
    min_after=min((min(1,(b+result[idx])/d) for idx,(d,b,a) in enumerate(prepared) if d>0),default=1.)
    return {'allocationsKg':result,'usedKg':used,'unusedKg':max(0.0,supply-used),
            'minimumRateBefore':min_before,'minimumRate':min_after,
            'objectiveF1':f1,'theta':theta,'rho':rho,'note':None}
