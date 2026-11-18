import json,time,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from p2_kit_optimizer import optimize_p2_kit
raw=json.load(open(ROOT/'data'/'allocation_shelters.json'))
raw=[r for r in raw if r['stock'].get('retortRice',0)>0 and r['stock'].get('water500ml',0)>0]
assert len(raw)==100
rows=[dict(name=r['name'],lat=r['lat'],lng=r['lng'],demandKits=max(3,int(r['capacity'])),stockKits=min(int(r['stock']['retortRice'])//3,int(r['stock']['water500ml'])//6),visited=False) for r in raw]
points=[]
for i,row in enumerate(rows):
 j=i//2 if i<40 else 20+i-40
 repr_row=rows[j*2] if i<40 else row
 points.append(dict(name=f'配送代表点{j+1}',lat=repr_row['lat'],lng=repr_row['lng']))
assert len(set(x['name'] for x in points))==80
payload=dict(shelters=rows,deliveryPoints=points,totalKits=1777,targetRate=.8,rho=.001,minKits=3,maxRounds=5,
 truckCount=10,vehicles=[dict(capacityKg=2000,count=10)],hubStockKits=[889,888],vehicleHubCounts=[dict(zip(['2t','4t'],[5,0])),dict(zip(['2t','4t'],[5,0]))],
 maxRoundMinutes=360,maxTotalMinutes=1080,loadingParallel=[5,5],visitWindows={},roadMode='all',
 p1TimeLimitSec=8,p1MipGapPercent=.2,p1MinimumKg=13.5,p1MandatoryVisitPolicy='professor',p1ModelMode='basic',maxStopsPerRoute=8,p2ExtraTimePercent=10)
t=time.time()
r=optimize_p2_kit(payload)
assert r['deliveryPointCount']==80
assert r['shelterCount']==100 and r['visitedShelters']==100
assert r['peakFacilitiesPerVehicleRound']<=8
assert r['peakPhysicalStopsPerVehicleRound']<=8
for rt in r['routes']:
 names=[s['deliveryPoint'] for s in rt['stops']]
 for name in set(names):
  idx=[i for i,n in enumerate(names) if n==name]
  assert idx==list(range(min(idx),max(idx)+1)),(rt['truck'],rt['round'],name,names)
assert r['f2Minutes']<1080 and r['longestRoundMinutes']<360
assert sum(r['hubOutgoingKits'])==r['deliveredKits']
print(json.dumps({k:r.get(k) for k in ('deliveryPointCount','visitedShelters','peakFacilitiesPerVehicleRound','peakPhysicalStopsPerVehicleRound','f2Minutes','longestRoundMinutes','f3','p2CandidateCount','assignmentMethod')},ensure_ascii=False,indent=2));print('Seconds',round(time.time()-t,2))
with open(ROOT/'verification'/'100施設80代表点_試験結果.json','w') as f:
 json.dump({k:r.get(k) for k in ('deliveryPointCount','visitedShelters','peakFacilitiesPerVehicleRound','peakPhysicalStopsPerVehicleRound','f2Minutes','longestRoundMinutes','f3','p2CandidateCount','assignmentMethod','hubOutgoingKits','usedTrucks','usedRounds','p2CandidatePareto','p2SelectionRule','roadTimeSource')},f,ensure_ascii=False,indent=2)
