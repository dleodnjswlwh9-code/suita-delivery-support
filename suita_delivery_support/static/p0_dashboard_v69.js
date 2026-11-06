(()=>{
 'use strict';
 const $=id=>document.getElementById(id),KIT_KG=4.5;
 const get=k=>{try{return JSON.parse(sessionStorage.getItem(k)||'null')}catch(_){return null}};
 const latestP1=()=>get('allocationPlan');
 const old=get('p0SolveSettings')||{}, oldDelivery=get('p1DeliverySettings')||{};
 const v70=Number(old.p0UiRevision)===70;
 const n2=Number(oldDelivery.t2??10),n4=Number(oldDelivery.t4??0);
 const p1Stock=plan=>{const x=Number(plan?.stages?.[0]?.totalKg);return Number.isSafeInteger(x)&&x>=0?x:null};
 const planTotal=p1Stock(latestP1());
 const previousSplit=v70&&Number(old.stockSourceTotalKits)===planTotal&&Number.isInteger(Number(old.northStock));
 const initialNorth=previousSplit?Number(old.northStock):(planTotal===null?'':Math.ceil(planTotal/2));
 const fields=['v65-min-kg','v65-trips','v65-trucks','v67-trucks-4t','p69-n2','p69-n4','p69-stock-n',
   'p69-round-min','p69-total-min','p69-load-n','p69-load-s','v65-time','v65-gap'];
 const init={
  'v65-min-kg':v70?old.minDeliveryKg:'',
  'v65-trips':v70?oldDelivery.trips:'',
  'v65-trucks':n2,'v67-trucks-4t':n4,
  'p69-n2':v70?old.n2:Math.ceil(n2/2),
  'p69-n4':v70?old.n4:Math.ceil(n4/2),
  'p69-stock-n':initialNorth,
  'p69-round-min':v70?old.maxRoundMinutes:360,
  'p69-total-min':v70?old.maxTotalMinutes:1080,
  'p69-load-n':v70?old.loadingNorth:5,
  'p69-load-s':v70?old.loadingSouth:5,
  'v65-time':v70?old.timeLimitSec:60,
  'v65-gap':v70?old.mipGapPercent:0.2
 };
 for(const [key,v] of Object.entries(init))$(key).value=v==null?'':String(v);
 const isIntegerValue=x=>x!==''&&Number.isSafeInteger(Number(x))&&Number(x)>=0;
 function updateDerived(){
   const total=p1Stock(latestP1());
   $('p70-stock-total').value=total===null?'—':`${total.toLocaleString('ja-JP')} 人日分（${(total*KIT_KG).toLocaleString('ja-JP')} kg相当）`;
   const north=$('p69-stock-n').value.trim();
   const remain=total!==null&&isIntegerValue(north)&&Number(north)<=total?total-Number(north):null;
   $('p69-stock-s').value=remain===null?'':String(remain);
   $('p70-north-equivalent').textContent=isIntegerValue(north)?`${(Number(north)*KIT_KG).toLocaleString('ja-JP')} kg相当`:'— kg相当';
   $('p70-south-equivalent').textContent=remain!==null?`${(remain*KIT_KG).toLocaleString('ja-JP')} kg相当`:'— kg相当';
   const total2=$('v65-trucks').value.trim(),total4=$('v67-trucks-4t').value.trim();
   const north2=$('p69-n2').value.trim(),north4=$('p69-n4').value.trim();
   $('p70-s2').value=isIntegerValue(total2)&&isIntegerValue(north2)&&+north2<=+total2?String(+total2-+north2):'';
   $('p70-s4').value=isIntegerValue(total4)&&isIntegerValue(north4)&&+north4<=+total4?String(+total4-+north4):'';
   const x=$('v65-min-kg').value.trim(),el=$('v65-conversion');
   if(x!==''&&Number.isFinite(+x)&&+x>=.1){const kits=Math.ceil((+x-1e-10)/KIT_KG);
     el.textContent=`1か所を訪問する場合の最低量。${x}kg指定時の実際の最低量：${(kits*KIT_KG).toFixed(1)}kg（${kits}人日分）。4.5kg単位`;}
   else el.textContent='1か所を訪問する場合の最低量。1人日分=4.5kg相当として計算。10kg指定時は13.5kg（3人日分）';
 }
 function whole(id,min,max){const e=$(id),t=e.value.trim(),v=Number(t);
   if(!t||!Number.isSafeInteger(v)||v<min||v>max)throw Error(`${e.closest('.p69-field')?.querySelector('label')?.textContent||id}：${min}～${max}の整数`);return v;
 }
 function read(){updateDerived();const p1=latestP1(),stock=p1Stock(p1);
   if(!p1||stock===null)throw Error('先にP1配分計画を計算してください。');
   const kgField=$('v65-min-kg').value.trim(),gapField=$('v65-gap').value.trim();
   const kg=Number(kgField),gap=Number(gapField);
   if(!kgField||!Number.isFinite(kg)||kg<.1||kg>3996)throw Error('最小配送量：0.1～3996kgを入力');
   if(!gapField||!Number.isFinite(gap)||gap<.1||gap>10)throw Error('最適性許容ギャップ：0.1～10%を入力');
   const x={minKg:kg,gap,rounds:whole('v65-trips',1,50),t2:whole('v65-trucks',0,50),
    t4:whole('v67-trucks-4t',0,50),n2:whole('p69-n2',0,50),n4:whole('p69-n4',0,50),
    northStock:whole('p69-stock-n',0,10000000),available:stock,
    maxRoundMinutes:whole('p69-round-min',1,100000),maxTotalMinutes:whole('p69-total-min',1,100000),
    loadingNorth:whole('p69-load-n',1,50),loadingSouth:whole('p69-load-s',1,50),
    seconds:whole('v65-time',5,60)};
   x.delta=Math.ceil((kg-1e-10)/KIT_KG);x.s2=x.t2-x.n2;x.s4=x.t4-x.n4;
   if(x.t2+x.t4<1||x.t2+x.t4>50||x.s2<0||x.s4<0)throw Error('拠点別の車両台数を確認してください。');
   if(x.northStock>stock)throw Error('北部在庫がP1の総物資量を超過');
   x.southStock=stock-x.northStock;
   if(x.delta>Math.floor((x.t4>0?4000:2000)/KIT_KG))throw Error('最小配送量が車両容量を超過');
   return x;
 }
 function cfgOf(x){return {settingsVersion:2,p0UiRevision:70,stockSourceTotalKits:x.available,
   minDeliveryKg:x.minKg,timeLimitSec:x.seconds,mipGapPercent:x.gap,mandatoryVisit:'professor',modelMode:'basic',
   n2:x.n2,n4:x.n4,northStock:x.northStock,southStock:x.southStock,
   maxRoundMinutes:x.maxRoundMinutes,maxTotalMinutes:x.maxTotalMinutes,
   loadingNorth:x.loadingNorth,loadingSouth:x.loadingSouth,visitWindows:{}};}
 const stamp=x=>JSON.stringify(x);
 const currentStamp=()=>{try{return stamp(cfgOf(read()))}catch(_){return null}};
 const val=x=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toFixed(5);
 function display(p){
  $('v65-f1').textContent=val(p?.f1Star);
  $('v65-eta').textContent=val(p?.etaUpperBound);
  $('v65-feasible-f1').textContent=val(p?.f1Feasible);
  $('v65-mandatory').textContent=p?.mandatoryCount!=null?`${p.mandatoryCount}か所`:'—';
  $('v65-stock').innerHTML=p?.availableKits!=null?`<span class="v75-stat-primary">${Number(p.availableKits).toLocaleString('ja-JP')} 人日分</span><small>${(Number(p.availableKits)*KIT_KG).toLocaleString('ja-JP')} kg相当</small>`:'—';
  $('v65-eta-lower').textContent=val(p?.etaLowerBound);
  $('v65-effective-min').textContent=p?.effectiveMinKg!=null?`${p.effectiveMinKg}kg（${p.deltaKits}人日分）`:'—';
  $('v65-slots').textContent=p?.totalPossibleVisitSlots!=null?`${p.totalPossibleVisitSlots}枠`:'—';
  $('v65-used').textContent=p?.vehiclesUsed!=null?`${p.vehiclesUsed}延べ台`:'—';
  $('v65-result-badge').textContent=p?.certified?'最適性確認':p?.feasible?'実行可能案':p?'未成立':'未計算';
  $('v65-eta-kind').textContent=p?.feasible?(p?.certified?'最適値':'上界・最適性未証明'):'';
  const note=$('v65-result-note');note.hidden=true;note.textContent='';
  if(p&&!p.feasible){note.hidden=false;note.textContent=p.reason||'実行可能案なし';}
  const link=$('v65-p2-link');link.setAttribute('aria-disabled',String(!p?.feasible));
  if(p?.feasible)link.href='/plan';else link.removeAttribute('href');
 }
 const show=(s,bad=false)=>{const el=$('v65-p0-status');el.textContent=s;el.className=bad?'p69-error':'p69-status';};
 function refresh(){updateDerived();
  const plan=latestP1(),saved=get('p0Result'),s=get('p0SolveSettings'),signature=currentStamp();
  if(saved&&plan&&s&&saved.planCreatedAt===plan.createdAt&&
    saved.settingsStamp===signature&&stamp(s)===signature){display(saved.result);show('');return;}
  display(null);show('');
 }
 function inputPayload(x,plan){const rows=plan?.food?.rows;
   if(!Array.isArray(rows)||!rows.length)throw Error('P1の避難所データがありません。');
   const shelters=rows.map((r,i)=>{
    const d=Math.round(Number(r.stageDemandsKg?.[0]??r.demandKg)),stock=Math.round(Number(r.stageOpeningStocks?.[0]??r.initialStockKg));
    const lat=Number(r.lat),lng=Number(r.lng);
    if(![d,stock,lat,lng].every(Number.isFinite)||d<=0||stock<0)throw Error(`避難所${i+1}のデータを確認`);
    return {name:r.name,lat,lng,demandKits:d,stockKits:stock,visited:false};
   });
   return {shelters,totalKits:x.available,targetRate:Number(plan.targetRate),rho:Number(plan.rho),
     minKits:x.delta,maxRounds:x.rounds,truckCount:x.t2+x.t4,
     vehicles:[{capacityKg:2000,count:x.t2},{capacityKg:4000,count:x.t4}],
     p0TimeLimitSec:x.seconds,p0MipGapPercent:x.gap,p0MinimumKg:x.minKg,
     p0MaxRounds:x.rounds,p0MandatoryVisitPolicy:'professor',p0ModelMode:'basic',
     hubStockKits:[x.northStock,x.southStock],
     vehicleHubCounts:[{'2t':x.n2,'4t':x.n4},{'2t':x.s2,'4t':x.s4}],
     maxRoundMinutes:x.maxRoundMinutes,maxTotalMinutes:x.maxTotalMinutes,
     loadingParallel:[x.loadingNorth,x.loadingSouth],visitWindows:{}};
 }
 // Always inspect the HTTP response before attempting JSON parsing. Render may
 // return an empty 502/504 response when the worker dies or a request times out.
 async function requestJSON(url,opts){let response;
  try{response=await fetch(url,opts);}catch(_){throw Error('サーバーに接続できません。Renderの状態を確認');}
  const body=await response.text();let data;
  try{data=body?JSON.parse(body):null;}catch(_){data=null;}
  if(!response.ok)throw Error(data?.error||`サーバーエラー（HTTP ${response.status}）。Renderログを確認`);
  if(!data||typeof data!=='object')throw Error(`サーバーの応答が不完全（HTTP ${response.status}）。Renderログを確認`);
  return data;
 }
 const pause=ms=>new Promise(done=>setTimeout(done,ms));
 async function calculate(payload){
  const queued=await requestJSON('/api/p0-job',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(!queued.jobId)throw Error('P0計算を開始できませんでした。');
  const started=Date.now(),limit=(payload.p0TimeLimitSec+30)*1000;
  while(Date.now()-started<limit){
   await pause(1250);
   const job=await requestJSON('/api/p0-job/'+encodeURIComponent(queued.jobId));
   if(job.status==='done')return job.result;
   if(job.status==='error')throw Error(job.error||'P0計算エラー。Renderログを確認');
   if(job.status!=='working')throw Error('P0の計算状態を確認できません。');
  }
  throw Error('計算結果の取得時間を超過。Renderの状態を確認');
 }
 async function run(){const btn=$('v65-run');btn.disabled=true;
  try{
   const before=latestP1();if(!before||before.version!==window.P0_ALLOCATION_VERSION)throw Error('配分計画（P1）の再計算が必要');
   const x=read();const cfg=cfgOf(x);
   const settings={unit:'kit',t2:x.t2,t4:x.t4,trips:x.rounds,delta:x.delta,p0SettingsVersion:2};
   const prev=get('p1DeliverySettings')||{};
   let plan=before;
   const changed=Number(prev.t2)!==x.t2||Number(prev.t4||0)!==x.t4||Number(prev.trips)!==x.rounds||Number(prev.delta)!==x.delta;
   if(changed){show('P1再計算中');plan=await syncAllocationForDeliverySettings(before,settings);
    sessionStorage.setItem('allocationPlan',JSON.stringify(plan));}
   sessionStorage.setItem('p1DeliverySettings',JSON.stringify(settings));
   sessionStorage.setItem('p0SolveSettings',JSON.stringify(cfg));
   sessionStorage.removeItem('p0Result');sessionStorage.removeItem('p2Result');
   show('P0計算中');const result=await calculate(inputPayload(x,plan));
   const resultStamp=stamp(cfg);
   sessionStorage.setItem('p0Result',JSON.stringify({planCreatedAt:plan.createdAt,settingsStamp:resultStamp,
    conditions:{t2:x.t2,t4:x.t4,trips:x.rounds,delta:x.delta,p0MinimumKg:x.minKg,
     p0TimeLimitSec:x.seconds,p0MipGapPercent:x.gap},result}));
   display(result);show(result.feasible?'P0計算完了':result.reason||'実行可能案なし',!result.feasible);
  }catch(err){display(null);show('計算エラー：'+(err?.message||'設定・Renderログを確認'),true);}
  finally{btn.disabled=false;updateDerived();}
 }
 $('v65-run').addEventListener('click',run);
 for(const id of fields)$(id).addEventListener('input',()=>{sessionStorage.removeItem('p0Result');refresh();});
 refresh();
})();
