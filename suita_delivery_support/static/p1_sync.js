/* P1／配送条件の一括更新。配送計画画面からP1の保存済み入力を厳密に再計算する。 */
(function(root){
  'use strict';
  async function syncAllocationForDeliverySettings(plan, settings, transport){
    if (!plan || !Array.isArray(plan.food?.rows) || !Array.isArray(plan.water?.rows) ||
        !Array.isArray(plan.stages) || plan.stages.length !== 1 ||
        plan.food.rows.length !== plan.water.rows.length) {
      throw Error('配分データが不足しています。配分計画を再計算してください。');
    }
    const food=plan.food.rows;
    const shelters=food.map((r,i)=>{
      const demand=Math.round(Number(r.stageDemandsKg?.[0] ?? r.demandKg));
      const stock=Math.round(Number(r.stageOpeningStocks?.[0] ?? r.initialStockKg));
      const lat=Number(r.lat),lng=Number(r.lng);
      if (![demand,stock,lat,lng].every(Number.isFinite) || demand<0 || stock<0)
        throw Error(`${i+1}番避難所のP1入力を復元できません。`);
      return {name:r.name,lat,lng,demandKits:demand,stockKits:stock,visited:false};
    });
    const payload={shelters,totalKits:Math.floor(Number(plan.stages[0].totalKg)),
       targetRate:Number(plan.targetRate),rho:Number(plan.rho),
       minKits:settings.delta,maxRounds:settings.trips,truckCount:settings.t2};
    if (![payload.totalKits,payload.targetRate,payload.rho].every(Number.isFinite))
      throw Error('保存された物資量・希求水準・ρを確認してください。');
    const request=transport || fetch;
    const response=await request('/api/p1-kits',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const answer=await response.json();
    if(!response.ok) throw Error(answer.error||'P1再計算に失敗しました。');
    const adds=answer.allocations;
    if(!Array.isArray(adds)||adds.length!==shelters.length||adds.some(v=>!Number.isFinite(Number(v))||Number(v)<0))
      throw Error('P1再計算結果の配分量が不正です。');
    const revised=JSON.parse(JSON.stringify(plan));
    const allocations=adds.map(Number);
    const used=allocations.reduce((a,b)=>a+b,0);
    for(const kind of ['food','water']){
      const commodity=revised[kind];
      commodity.rows.forEach((row,i)=>{
        const stock=shelters[i].stockKits,demand=shelters[i].demandKits,qty=allocations[i];
        row.stageOpeningStocks=[stock];
        row.stageAllocations=[qty];
        row.stageClosingStocks=[stock+qty];
        row.stageRates=[demand>0?Math.min(1,(stock+qty)/demand):1];
        row.currentStockKg=stock+qty;
        row.demandKg=demand;
        row.finalRate=row.stageRates[0];
        row.plannedVisited=qty>=settings.delta-1e-6;
      });
      const current=commodity.stageSummaries?.[0];
      if(!current)throw Error('配分集計が不足しています。');
      const candidates=shelters.filter(s=>s.demandKits>0);
      const initialMin=candidates.length?Math.min(...candidates.map(s=>Math.min(1,s.stockKits/s.demandKits))):1;
      const finalMin=candidates.length?Math.min(...shelters.map((s,i)=>s.demandKits>0?Math.min(1,(s.stockKits+allocations[i])/s.demandKits):1)):1;
      current.usedKg=used/2;
      current.unusedKg=Math.max(0,payload.totalKits-used);
      current.vehicleBudgetKg=settings.trips*settings.t2*444;
      current.objectiveF1=answer.objectiveF1;
      current.theta=answer.theta;
      current.mandatoryCount=answer.mandatoryCount;
      current.activeCount=answer.activeCount;
      current.minimumRateBefore=initialMin;
      current.minimumRate=finalMin;
      current.minDeliveryKg=settings.delta;
      commodity.finalMinimumRate=finalMin;
      commodity.totalUsedKg=used/2;
    }
    revised.p1DeliverySettings={delta:settings.delta,trips:settings.trips,vehicles:[{capacityKg:2000,count:settings.t2}]};
    revised.createdAt=new Date().toISOString();
    return revised;
  }
  root.syncAllocationForDeliverySettings=syncAllocationForDeliverySettings;
})(typeof window!=='undefined'?window:globalThis);
