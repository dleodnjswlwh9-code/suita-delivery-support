(()=>{
'use strict';
const $=id=>document.getElementById(id),KIT_KG=4.5;
const get=k=>{try{return JSON.parse(sessionStorage.getItem(k)||'null')}catch(_){return null}};
const p1=get('allocationPlan'),old=get('p0SolveSettings')||{},savedDelivery=get('p1DeliverySettings')||{};
const n2=Number(savedDelivery.t2??10),n4=Number(savedDelivery.t4??0),available=Math.floor(Number(p1?.stages?.[0]?.totalKg||0));
const ids=['v65-min-kg','v65-trips','v65-trucks','v67-trucks-4t','p69-n2','p69-n4','p69-stock-n','p69-stock-s','p69-round-min','p69-total-min','p69-load-n','p69-load-s','v65-time','v65-gap'];
const init={
 'v65-min-kg':old.minDeliveryKg??10,'v65-trips':savedDelivery.trips??3,'v65-trucks':n2,'v67-trucks-4t':n4,
 'p69-n2':old.n2??Math.ceil(n2/2),'p69-n4':old.n4??Math.ceil(n4/2),
 'p69-stock-n':old.northStock??Math.ceil(available/2),'p69-stock-s':old.southStock??Math.floor(available/2),
 'p69-round-min':old.maxRoundMinutes??360,'p69-total-min':old.maxTotalMinutes??1080,
 'p69-load-n':old.loadingNorth??5,'p69-load-s':old.loadingSouth??5,'v65-time':old.timeLimitSec??60,'v65-gap':old.mipGapPercent??0.2};
for(const [key,val] of Object.entries(init))$(key).value=String(val);
const winList=$('p69-window-list'),search=$('p69-window-search');
const windowsSaved=old.visitWindows||{};
function makeWindows(){
 winList.replaceChildren();const rows=p1?.food?.rows||[];
 if(!rows.length){winList.textContent='P1の配分計画が必要';return;}
 for(const row of rows){const name=String(row.name||'');const span=windowsSaved[name]||[0,1440];
  const entry=document.createElement('div');entry.className='p69-window-row';entry.dataset.name=name.toLowerCase();
  const label=document.createElement('strong');label.textContent=name;entry.appendChild(label);
  for(const [cls,val] of [['start',span[0]],['end',span[1]]]){
   const input=document.createElement('input');input.type='number';input.min='0';input.max='100000';input.step='1';
   input.value=String(val);input.dataset.field=cls;input.setAttribute('aria-label',name+(cls==='start'?'開始':'終了'));entry.appendChild(input);
  }winList.appendChild(entry);
 }
}
makeWindows();
search.addEventListener('input',()=>{const q=search.value.trim().toLowerCase();for(const row of winList.querySelectorAll('.p69-window-row'))row.hidden=!row.dataset.name.includes(q)});
const show=(m,error=false)=>{const e=$('v65-p0-status');e.textContent=m;e.className=error?'p69-error':'p69-status'};
function whole(id,min,max){const el=$(id),n=Number(el.value);if(el.value.trim()===''||!Number.isInteger(n)||n<min||n>max)throw Error(el.closest('label')?.querySelector('strong')?.textContent+'：入力範囲の確認');return n}
function read(){const kg=Number($('v65-min-kg').value),gap=Number($('v65-gap').value);
 if(!Number.isFinite(kg)||kg<.1||kg>3996||!Number.isFinite(gap)||gap<.1||gap>10)throw Error('最小配送量・許容ギャップの入力確認');
 const x={minKg:kg,gap,rounds:whole('v65-trips',1,50),t2:whole('v65-trucks',0,50),t4:whole('v67-trucks-4t',0,50),
    n2:whole('p69-n2',0,50),n4:whole('p69-n4',0,50),northStock:whole('p69-stock-n',0,10000000),southStock:whole('p69-stock-s',0,10000000),
    maxRoundMinutes:whole('p69-round-min',1,100000),maxTotalMinutes:whole('p69-total-min',1,100000),
    loadingNorth:whole('p69-load-n',1,50),loadingSouth:whole('p69-load-s',1,50),
    seconds:whole('v65-time',5,60)};
 x.delta=Math.ceil((kg-1e-10)/KIT_KG);x.s2=x.t2-x.n2;x.s4=x.t4-x.n4;
 if(x.t2+x.t4<1||x.t2+x.t4>50||x.s2<0||x.s4<0)throw Error('北部・南部の車両台数と総台数の不一致');
 if(x.delta>Math.floor((x.t4>0?4000:2000)/KIT_KG))throw Error('最小配送量が車両容量を超過');
 const stockRequired=Math.floor(Number(p1?.stages?.[0]?.totalKg||0));
 if(x.northStock+x.southStock<stockRequired)throw Error('拠点在庫の合計がP1の配分可能量より不足');
 x.windows={};
 for(const row of winList.querySelectorAll('.p69-window-row')){
  const inputs=row.querySelectorAll('input'),a=Number(inputs[0].value),b=Number(inputs[1].value);
  if(inputs[0].value===''||inputs[1].value===''||!Number.isInteger(a)||!Number.isInteger(b)||a<0||a>=b||b>100000)throw Error(row.querySelector('strong').textContent+'：訪問時間帯の入力確認');
  if(a!==0||b!==1440)x.windows[row.querySelector('strong').textContent]=[a,b];
 }
 return x;
}
function cfgOf(x){return {settingsVersion:2,minDeliveryKg:x.minKg,timeLimitSec:x.seconds,mipGapPercent:x.gap,mandatoryVisit:'professor',modelMode:'basic',
 n2:x.n2,n4:x.n4,northStock:x.northStock,southStock:x.southStock,maxRoundMinutes:x.maxRoundMinutes,maxTotalMinutes:x.maxTotalMinutes,
 loadingNorth:x.loadingNorth,loadingSouth:x.loadingSouth,visitWindows:x.windows};}
const stamp=cfg=>JSON.stringify(cfg);
function currentStamp(){try{return stamp(cfgOf(read()))}catch(_){return null}}
function display(result){const p=result;
 $('v65-f1').textContent=val(p?.f1Star);$('v65-eta').textContent=val(p?.etaUpperBound);$('v65-feasible-f1').textContent=val(p?.f1Feasible);
 $('v65-mandatory').textContent=p?.mandatoryCount!=null?p.mandatoryCount+'か所':'—';
 $('v65-stock').textContent=p?.availableKits!=null?p.availableKits+'キット':'—';
 $('v65-eta-lower').textContent=val(p?.etaLowerBound);$('v65-effective-min').textContent=p?.effectiveMinKg!=null?p.effectiveMinKg+'kg':'—';
 $('v65-slots').textContent=p?.totalPossibleVisitSlots!=null?p.totalPossibleVisitSlots+'枠':'—';
 $('v65-used').textContent=p?.vehiclesUsed!=null?p.vehiclesUsed+'延べ台':'—';
 $('v65-result-badge').textContent=p?.certified?'基本モデルで最適性確認':p?.feasible?'実行可能案':p?'未成立':'未計算';
 $('v65-eta-kind').textContent=p?.certified?'基本P0の最適値':p?.feasible?'評価差の上限（最適性未証明）':'小さいほどP1の理想に近い評価';
 $('v65-result-note').textContent=p?.reason||'※ 時間条件は保守的な判定。訪問時間帯はP2の経路計算で最終確認';
 const link=$('v65-p2-link');link.setAttribute('aria-disabled',String(!p?.feasible));if(p?.feasible)link.href='/plan';else link.removeAttribute('href');
}
function val(x){return x==null||!Number.isFinite(Number(x))?'—':Number(x).toFixed(5)}
function refresh(){let x;try{x=read();$('v65-conversion').textContent=`計算上：${(x.delta*KIT_KG).toFixed(1)}kg（${x.delta}キット）`;}catch(e){$('v65-conversion').textContent=e.message;display(null);show(e.message,true);return;}
 const planNow=get('allocationPlan'),saved=get('p0Result'),stored=get('p0SolveSettings');
 if(saved&&planNow&&saved.planCreatedAt===planNow.createdAt&&stored&&stamp(stored)===currentStamp()&&saved.settingsStamp===currentStamp()){
  display(saved.result);show('');return;
 }display(null);if(!p1){show('先にP1の計算が必要');}else if(p1.version!==window.P0_ALLOCATION_VERSION)show('P1の再計算が必要',true);else show('');
}
function inputPayload(x,plan){const shelterRows=plan.food.rows;
 const shelters=shelterRows.map((r,i)=>{
  const d=Math.round(Number(r.stageDemandsKg?.[0]??r.demandKg)),s=Math.round(Number(r.stageOpeningStocks?.[0]??r.initialStockKg));
  const lat=Number(r.lat),lng=Number(r.lng);
  if(![d,s,lat,lng].every(Number.isFinite)||d<=0||s<0)throw Error(`避難所${i+1}のデータ不一致`);
  return {name:r.name,lat,lng,demandKits:d,stockKits:s,visited:false};
 });
 return {shelters,totalKits:Math.floor(Number(plan.stages[0].totalKg)),targetRate:Number(plan.targetRate),rho:Number(plan.rho),
 minKits:x.delta,maxRounds:x.rounds,truckCount:x.t2+x.t4,vehicles:[{capacityKg:2000,count:x.t2},{capacityKg:4000,count:x.t4}],
 p0TimeLimitSec:x.seconds,p0MipGapPercent:x.gap,p0MinimumKg:x.minKg,p0MaxRounds:x.rounds,p0MandatoryVisitPolicy:'professor',p0ModelMode:'basic',
 hubStockKits:[x.northStock,x.southStock],vehicleHubCounts:[{'2t':x.n2,'4t':x.n4},{'2t':x.s2,'4t':x.s4}],
 maxRoundMinutes:x.maxRoundMinutes,maxTotalMinutes:x.maxTotalMinutes,loadingParallel:[x.loadingNorth,x.loadingSouth],visitWindows:x.windows};
}
async function run(){const btn=$('v65-run');btn.disabled=true;try{
 if(!p1||p1.version!==window.P0_ALLOCATION_VERSION)throw Error('配分計画（P1）の計算が必要');
 const x=read();const cfg=cfgOf(x);const settings={unit:'kit',t2:x.t2,t4:x.t4,trips:x.rounds,delta:x.delta,p0SettingsVersion:2};
 let plan=get('allocationPlan');const oldSettings=get('p1DeliverySettings')||{};
 const updateNeeded=Number(oldSettings.t2)!==x.t2||Number(oldSettings.t4||0)!==x.t4||Number(oldSettings.trips)!==x.rounds||Number(oldSettings.delta)!==x.delta;
 if(updateNeeded){show('P1の評価を更新中');plan=await syncAllocationForDeliverySettings(plan,{t2:x.t2,t4:x.t4,trips:x.rounds,delta:x.delta});sessionStorage.setItem('allocationPlan',JSON.stringify(plan));}
 sessionStorage.setItem('p1DeliverySettings',JSON.stringify(settings));sessionStorage.setItem('p0SolveSettings',JSON.stringify(cfg));
 sessionStorage.removeItem('p0Result');sessionStorage.removeItem('p2Result');
 show('P0を計算中');const response=await fetch('/api/p0-optimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(inputPayload(x,plan))});
 const result=await response.json();if(!response.ok)throw Error(result.error||'P0計算エラー');
 sessionStorage.setItem('p0Result',JSON.stringify({planCreatedAt:plan.createdAt,settingsStamp:stamp(cfg),
 conditions:{t2:x.t2,t4:x.t4,trips:x.rounds,delta:x.delta,p0MinimumKg:x.minKg,p0TimeLimitSec:x.seconds,p0MipGapPercent:x.gap},result}));
 display(result);show(result.feasible?'P0計算完了':result.reason||'実行可能案なし',!result.feasible);
 }catch(e){show('計算エラー：'+e.message,true);}finally{btn.disabled=false;}}
$('v65-run').addEventListener('click',run);
for(const id of ids)$(id).addEventListener('input',()=>{sessionStorage.removeItem('p0Result');refresh()});
winList.addEventListener('input',()=>{sessionStorage.removeItem('p0Result');refresh()});
refresh();
})();
