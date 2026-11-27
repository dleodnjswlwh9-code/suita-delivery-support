"""Validate a REPORTED actual delivery round before carrying it into the next P1.

The previous P1/P0/P2 is a plan, never automatically an actual delivery.
No internet, no implied proof of real-world delivery. The researcher must
explicitly confirm each amount after the vehicles return.
"""
from math import isfinite

class ActualDeliveryError(ValueError):
    pass


def confirm_round(p2, round_number, quantities, actual_minutes=None):
    if not isinstance(p2, dict) or not p2.get('verifiedRouteConstraints') or not p2.get('p0BoundSatisfied'):
        raise ActualDeliveryError('検証済みのP2配送計画が必要です。')
    if isinstance(round_number,bool) or not isinstance(round_number,int) or round_number!=1:
        raise ActualDeliveryError('現在の計画では第1回の実績のみ次期に引き継げます。')
    shelters=p2.get('shelters'); routes=p2.get('routes')
    if not isinstance(shelters,list) or not isinstance(routes,list) or not shelters:
        raise ActualDeliveryError('配送計画の施設別データがありません。')
    if not isinstance(quantities,list) or len(quantities)!=len(shelters):
        raise ActualDeliveryError('実配送量は対象施設すべてについて入力してください。')
    permitted=[0]*len(shelters); source=[None]*len(shelters)
    for route in routes:
        if route.get('round') != round_number:continue
        hub=route.get('hub')
        if hub not in (0,1):raise ActualDeliveryError('車両の出発拠点が不正です。')
        for stop in route.get('stops',[]):
            idx=stop.get('index');q=stop.get('kits')
            if not isinstance(idx,int) or isinstance(idx,bool) or idx<0 or idx>=len(shelters) or not isinstance(q,int) or q<0:
                raise ActualDeliveryError('配送量・施設番号が不正です。')
            if source[idx] is not None and source[idx]!=hub:
                raise ActualDeliveryError('同一施設の出庫拠点が複数あります。')
            source[idx]=hub;permitted[idx]+=q
    actual=[]; per_hub=[0,0]; update=[]
    for i,(s,value) in enumerate(zip(shelters,quantities)):
        if isinstance(value,bool) or not isinstance(value,int) or value<0 or value>permitted[i]:
            raise ActualDeliveryError(f'{s.get("name","避難所")}：実配送量は0～{permitted[i]}人日分です。')
        stock=s.get('stockKits');demand=s.get('demandKits')
        if not isinstance(stock,int) or stock<0 or not isinstance(demand,int) or demand<=0:
            raise ActualDeliveryError('施設別の初期備蓄・必要量が不正です。')
        if stock+value>demand:
            raise ActualDeliveryError('実配送量が必要量を超えています：'+str(s.get('name')))
        if value:
            if source[i] is None:raise ActualDeliveryError('計画外の配送先が含まれています。')
            per_hub[source[i]]+=value
        actual.append(value)
        update.append(dict(name=s['name'],plannedKits=permitted[i],actualKits=value,
            stockBeforeKits=stock,stockAfterKits=stock+value,
            demandKits=demand,coverageAfter=(stock+value)/demand,
            visited=value>0))
    hub_stocks=p2.get('hubStockKits'); available=p2.get('availableKits')
    if not isinstance(hub_stocks,list) or len(hub_stocks)!=2 or any(not isinstance(x,int) or x<0 for x in hub_stocks):
        raise ActualDeliveryError('北南部の在庫情報がありません。')
    if not isinstance(available,int) or available<0:
        raise ActualDeliveryError('総物資量が不正です。')
    remaining=[hub_stocks[h]-per_hub[h] for h in (0,1)]
    if any(v<0 for v in remaining):raise ActualDeliveryError('拠点在庫を超えて出庫しています。')
    if available!=sum(hub_stocks):
        raise ActualDeliveryError('総在庫量と拠点別在庫が一致しません。')
    total=sum(actual)
    if total<=0:raise ActualDeliveryError('実配送量を1人日分以上入力してください。')
    max_rounds=p2.get('maxRounds')
    if isinstance(max_rounds,bool) or not isinstance(max_rounds,int) or max_rounds<1:
        raise ActualDeliveryError('残りの配送回数が不正です。')
    finalized=max_rounds==1
    # Paper (79)-(80): the time budget of the next period is the old budget minus
    # the time ACTUALLY used (H_nu^ex). Default to the planned round time only
    # when no actual time is reported.
    planned_minutes=max((float(rt.get('timeMin',0)) for rt in routes if rt.get('round')==round_number),default=0.)
    if actual_minutes is None or actual_minutes=='':
        used_minutes=planned_minutes;minutes_source='planned'
    else:
        if isinstance(actual_minutes,bool):raise ActualDeliveryError('実際の所要時間（分）が不正です。')
        try:used_minutes=float(actual_minutes)
        except (TypeError,ValueError):raise ActualDeliveryError('実際の所要時間（分）が不正です。')
        if not isfinite(used_minutes) or used_minutes<0 or used_minutes>100000:
            raise ActualDeliveryError('実際の所要時間（分）は0～100000で入力してください。')
        minutes_source='actual'
    total_limit=p2.get('maxTotalMinutes')
    remaining_minutes=(max(0.,float(total_limit)-used_minutes)
                       if isinstance(total_limit,(int,float)) and not isinstance(total_limit,bool) else None)
    return dict(round=round_number,finalized=finalized,canContinue=not finalized,
        actualKits=total,actualByHub=per_hub,
        remainingHubStockKits=remaining,remainingTotalKits=available-total,
        remainingRounds=max_rounds-round_number,
        usedMinutes=used_minutes,usedMinutesSource=minutes_source,
        remainingTotalMinutes=remaining_minutes,
        shelters=update)
