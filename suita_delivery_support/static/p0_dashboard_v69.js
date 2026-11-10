(()=>{
 'use strict';
 const $=id=>document.getElementById(id),KIT_KG=4.5;
 const get=k=>{try{return JSON.parse(sessionStorage.getItem(k)||'null')}catch(_){return null}};
 const latestP1=()=>get('allocationPlan');
 // All P0 scenario inputs start empty. Only P1 supply is read-only and auto-synced.
 // Saved scenarios remain in the history; there is no locked/default mode.
 const fields=['v65-min-kg','v65-trips','v65-trucks','v67-trucks-4t','p69-n2','p69-n4','p69-stock-n',
   'p69-round-min','p69-total-min','p69-load-n','p69-load-s','v65-time','v65-gap'];
 const p1Stock=plan=>{const x=Number(plan?.stages?.[0]?.totalKg);return Number.isSafeInteger(x)&&x>=0?x:null};
 for(const id of fields){const el=$(id);el.value='';el.readOnly=false;el.classList.remove('v76-locked');}
 let scenarioEdited=false;
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
   // 最小配送量は4.5kg（1人日分）単位に切り上げて適用する。表示は適用最小配送量の欄に出す。
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
   const rolling=get('rollingProgress');
   // Paper (79)-(80): the total-time limit of this period is the previous limit
   // minus the time actually used, so it can never exceed what is left.
   if(rolling?.remainingTotalMinutes!=null&&x.maxTotalMinutes>Math.floor(Number(rolling.remainingTotalMinutes)))
     throw Error('累積作業時間上限は、実績反映後の残り時間'+Math.floor(Number(rolling.remainingTotalMinutes))+'分以下にしてください。');
   if(rolling?.remainingRounds!=null){
     if(x.rounds>Number(rolling.remainingRounds))throw Error('実績確定後の残り配送回数は'+rolling.remainingRounds+'回です。');
     const hubs=rolling.hubStocks||[];
     if(hubs.length===2&&(x.northStock<Number(hubs[0])||x.southStock<Number(hubs[1])))
         throw Error('確認済みの残余在庫を下回っています。北部'+hubs[0]+'・南部'+hubs[1]+'人日分以上を入力してください。新規搬入分は各拠点に配分してください。');
   }
   if(x.delta>Math.floor((x.t4>0?4000:2000)/KIT_KG))throw Error('最小配送量が車両容量を超過');
   return x;
 }
 function cfgOf(x){return {settingsVersion:2,p0UiRevision:76,stockSourceTotalKits:x.available,
   minDeliveryKg:x.minKg,timeLimitSec:x.seconds,mipGapPercent:x.gap,mandatoryVisit:'professor',modelMode:'basic',
   n2:x.n2,n4:x.n4,northStock:x.northStock,southStock:x.southStock,
   maxRoundMinutes:x.maxRoundMinutes,maxTotalMinutes:x.maxTotalMinutes,
   loadingNorth:x.loadingNorth,loadingSouth:x.loadingSouth,visitWindows:{}};}
 const stamp=x=>JSON.stringify(x);
 const currentStamp=()=>{try{return stamp(cfgOf(read()))}catch(_){return null}};
 const val=x=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toFixed(5);
 const historyKey='suitaP0ScenarioHistoryV76';
 const savedHistory=()=>{try{const rows=JSON.parse(localStorage.getItem(historyKey)||'[]');return Array.isArray(rows)?rows:[]}catch(_){return []}};
 const historySet=rows=>{try{localStorage.setItem(historyKey,JSON.stringify(rows.slice(0,100)))}catch(_){show('履歴をブラウザに保存できません。CSVを利用してください。',true)}};
 // Compare only scenarios using the same original shelter demands, base stocks,
 // available supply, aspiration target and rho; changed fleet need not alter it.
 function cohortKey(payload){return JSON.stringify({shelters:payload.shelters.map(r=>[r.name,r.demandKits,r.stockKits]),
     total:payload.totalKits,target:payload.targetRate,rho:payload.rho});}
 function saveRun(x,p,plan,payload){
   const entry={id:Date.now()+'-'+Math.random().toString(36).slice(2,7),date:new Date().toISOString(),
     cohort:cohortKey(payload),p1Date:plan.createdAt,
     deltaKg:x.minKg,appliedKg:x.delta*KIT_KG,rounds:x.rounds,t2:x.t2,t4:x.t4,
     north2:x.n2,north4:x.n4,south2:x.s2,south4:x.s4,
     stock:x.available,northStock:x.northStock,southStock:x.southStock,
     roundMin:x.maxRoundMinutes,totalMin:x.maxTotalMinutes,loadN:x.loadingNorth,loadS:x.loadingSouth,
     solveSec:x.seconds,solveGap:x.gap,f1Star:p.f1Star,eta:p.etaUpperBound,
     etaLower:p.etaLowerBound,f1:p.f1Feasible,certified:!!p.certified,feasible:!!p.feasible};
   historySet([entry,...savedHistory()]);renderHistory(entry.cohort);
 }
 const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const num=x=>x===null||x===undefined||!Number.isFinite(Number(x))?'—':Number(x).toFixed(5);
 function renderHistory(activeCohort){
   const rows=savedHistory();const body=$('v76-history-body');
   if(!rows.length){body.innerHTML='<tr><td colspan="8">まだ比較結果はありません。</td></tr>';return;}
   const candidates=rows.filter(r=>r.feasible&&Number.isFinite(Number(r.eta))&&(!activeCohort||r.cohort===activeCohort));
   const min=candidates.length?Math.min(...candidates.map(r=>Number(r.eta))):null;
   body.innerHTML=rows.map(r=>{
     const same=!activeCohort||r.cohort===activeCohort;
     const best=same&&min!==null&&r.feasible&&Math.abs(r.eta-min)<1e-9;
     const status=!r.feasible?'実行可能解なし':'計算済み';
     return `<tr class="${best?'v76-best':''}${same?'':' v76-different'}"><td>${esc(r.date.slice(0,16).replace('T',' '))}${same?'':'<small>別のP1入力</small>'}</td>`+
        `<td>δ ${esc(r.deltaKg)}kg / ${esc(r.rounds)}回<br>2t ${esc(r.t2)}台・4t ${esc(r.t4)}台</td>`+
        `<td>北 ${esc(r.northStock)}・南 ${esc(r.southStock)} 人日分<br>北 2t ${esc(r.north2)} / 4t ${esc(r.north4)}台</td>`+
        `<td>${esc(r.roundMin)} / ${esc(r.totalMin)}分<br>積込 ${esc(r.loadN)} / ${esc(r.loadS)}台</td>`+
        `<td>${num(r.f1Star)}</td><td><b>${num(r.eta)}</b>${best?'<small>同一入力で最小の評価差</small>':''}</td>`+
        `<td>${num(r.f1)}</td><td>${status}<small>${esc(r.solveSec)}秒・${esc(r.solveGap)}%</small></td></tr>`;}).join('');
   $('v76-history-note').textContent=`保存 ${rows.length}件 / 最小のηは同一P1入力の計算結果だけで比較します。`;
 }
 const csvFields=[['date','計算日時'],['deltaKg','最小配送量kg'],['appliedKg','実適用kg'],['rounds','最大配送回数'],['t2','2t総数'],['t4','4t総数'],['north2','北部2t'],['south2','南部2t'],['north4','北部4t'],['south4','南部4t'],['stock','総物資量人日分'],['northStock','北部物資量'],['southStock','南部物資量'],['roundMin','配送回時間上限分'],['totalMin','累積作業時間上限分'],['loadN','北部同時積込'],['loadS','南部同時積込'],['solveSec','計算時間秒'],['solveGap','許容ギャップ%'],['f1Star','F1*'],['eta','理想配分との差（η）'],['f1','F1'],['feasible','実行可能'],['cohort','比較用P1入力識別']];
 function downloadHistory(){
   const rows=savedHistory();if(!rows.length){$('v76-history-note').textContent='保存済み履歴がありません。';return;}
   const csvSafe=v=>{let x=String(v??'');if(x && '=+-@'.includes(x[0]))x="'"+x;return '"'+x.replaceAll('"','""')+'"';};
   const lines=[csvFields.map(p=>csvSafe(p[1])).join(','),...rows.map(r=>csvFields.map(p=>csvSafe(r[p[0]])).join(','))];
   const file=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'});
   const url=URL.createObjectURL(file),a=document.createElement('a');a.href=url;a.download='P0_条件比較_'+new Date().toISOString().slice(0,10)+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 $('v76-csv').addEventListener('click',downloadHistory);
 $('v76-clear-history').addEventListener('click',()=>{if(confirm('保存したP0比較履歴を削除しますか？')){localStorage.removeItem(historyKey);renderHistory(null);}});
 let lastSampleResult=null;
 function renderEtaAnalysis(result){
   lastSampleResult=result;
   const improved=$('v80-refinement-note');
   if(improved){const change=Number(result?.etaImprovement||0),original=Number(result?.etaBeforeRefinement);
     improved.hidden=!(change>1e-8 && Number.isFinite(original));
     improved.textContent=improved.hidden?'':`同一車両・同一配送回の物資配分を調整：η ${original.toFixed(6)} → ${Number(result.etaUpperBound).toFixed(6)}（改善 ${change.toFixed(6)}、${result.refinementMoves||0}回）`;
   }
   const arr=Array.isArray(result?.candidateSamples)?result.candidateSamples:[];
   if(!arr.length){$('v77-bars').innerHTML='';$('v77-candidate-body').innerHTML='<tr><td colspan="4">配分候補はありません。</td></tr>';return;}
   const high=Math.max(0.00001,...arr.map(x=>Number(x.eta)||0));
   $('v77-bars').innerHTML=arr.slice(0,24).map((c,i)=>`<div class="v77-bar-row"><span>${esc(c.label)}</span><div class="v77-bar-track"><div class="v77-bar" style="width:${Math.max(1,Math.min(100,(Number(c.eta)||0)/high*100))}%"></div></div><b>${num(c.eta)}</b></div>`).join('');
   $('v77-candidate-body').innerHTML=arr.map((c,i)=>`<tr><td>${esc(c.label)}${i===0?'（基準）':''}</td><td>${num(c.f1)}</td><td>${num(c.eta)}</td><td>${c.changes?.length?c.changes.map(e=>esc(e.name)+' '+(e.changeKits>0?'+':'')+esc(e.changeKits)+'人日分').join(' / '):'最適化で得た配分案'}</td></tr>`).join('');
 }
 function csvCandidates(){
   const arr=lastSampleResult?.candidateSamples||[];
   if(!arr.length)return;
   const safe=v=>'"'+String(v??'').replaceAll('"','""')+'"';
   const rows=[['候補','F1','η','物資移動内容'],...arr.map(c=>[c.label,c.f1,c.eta,(c.changes||[]).map(x=>x.name+':'+x.changeKits+'人日分').join('; ')])];
   const file=new Blob(['\ufeff'+rows.map(r=>r.map(safe).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});
   const url=URL.createObjectURL(file),a=document.createElement('a');a.href=url;a.download='P0_配分候補_η比較.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 $('v77-candidate-csv').addEventListener('click',csvCandidates);
 function renderCoverage(p){
   const body=$('v81-p0-coverage');if(!body)return;
   const rows=latestP1()?.food?.rows||[],added=p?.plannedAdditions;
   if(!p?.feasible||!Array.isArray(added)||added.length!==rows.length){body.innerHTML='<tr><td colspan="8">有効なP0配分案がありません。</td></tr>';return;}
   body.innerHTML=rows.map((r,i)=>{
     const demand=Number(r.stageDemandsKg?.[0]??r.demandKg),stock=Number(r.stageOpeningStocks?.[0]??r.initialStockKg);
     const ideal=Number(r.stageAllocations?.[0]||0),q=Number(added[i]||0);
     const idealRate=demand>0?(stock+ideal)/demand:0,actualRate=demand>0?(stock+q)/demand:0;
     const percent=x=>(x*100).toFixed(1)+'%';
     return `<tr><td>${esc(r.name)}</td><td>${esc(demand)}</td><td>${esc(stock)}</td><td>${esc(ideal.toFixed(1))}</td><td>${percent(idealRate)}</td><td>${esc(q)}</td><td>${percent(actualRate)}</td><td>${((actualRate-idealRate)*100).toFixed(1)}pt</td></tr>`;
   }).join('');
 }
 function display(p){
   renderEtaAnalysis(p);renderCoverage(p);
  $('v65-f1').textContent=val(p?.f1Star);
  $('v65-eta').textContent=val(p?.etaUpperBound);
  $('v65-feasible-f1').textContent=val(p?.f1Feasible);
  $('v65-stock').innerHTML=p?.availableKits!=null?`<span class="v75-stat-primary">${Number(p.availableKits).toLocaleString('ja-JP')} 人日分</span><small>${(Number(p.availableKits)*KIT_KG).toLocaleString('ja-JP')} kg相当</small>`:'—';
  $('v83-active').textContent=p?.activeCount!=null?`${p.activeCount}か所`:'—';
  $('v86-planned').innerHTML=p?.feasible&&Number.isFinite(Number(p.totalKits))?`<span class="v75-stat-primary">${Number(p.totalKits).toLocaleString('ja-JP')} 人日分</span><small>${(Number(p.totalKits)*KIT_KG).toLocaleString('ja-JP')} kg相当</small>`:'—';
  $('v65-effective-min').textContent=p?.effectiveMinKg!=null?`${Number(p.effectiveMinKg).toLocaleString('ja-JP')}kg（${Number(p.deltaKits).toLocaleString('ja-JP')}人日分）`:'—';
  $('v65-used').textContent=p?.feasible&&p.vehiclesUsed!=null?`${p.vehiclesUsed}回`:'—';
  $('v65-result-badge').textContent=p?.feasible?'計算完了':p?'未成立':'未計算';
  const note=$('v65-result-note');note.hidden=true;note.textContent='';
  if(p&&!p.feasible){note.hidden=false;note.textContent=p.reason||'実行可能案なし';}
  const link=$('v65-p2-link');link.setAttribute('aria-disabled',String(!p?.feasible));
  if(p?.feasible)link.href='/plan';else link.removeAttribute('href');
 }
 const show=(s,bad=false)=>{const el=$('v65-p0-status');el.textContent=s;el.className=bad?'p69-error':'p69-status';};
 function refresh(){updateDerived();
  const plan=latestP1(),saved=get('p0Result'),s=get('p0SolveSettings');
  // Preserve the previous completed P0 result without silently filling any
  // numeric fields. As soon as a researcher starts editing, this is a new
  // as-yet-uncalculated comparison scenario.
  if(!scenarioEdited&&fields.every(id=>$(id).value.trim()==='')&&saved&&plan&&s&&
    saved.planCreatedAt===plan.createdAt&&saved.result?.p0AlgorithmRevision===82&&saved.settingsStamp===stamp(s)){
    display(saved.result);show('前回の保存済み結果です。新しい比較条件は空欄から入力できます。');return;
  }
  const signature=currentStamp();
  if(saved&&plan&&s&&saved.planCreatedAt===plan.createdAt&&
    saved.result?.p0AlgorithmRevision===82&&saved.settingsStamp===signature&&stamp(s)===signature){display(saved.result);show('');return;}
  display(null);
  show(scenarioEdited?'入力した条件は未計算です。「P0を計算する」で比較結果を追加できます。':'');
 }
 function inputPayload(x,plan){const rows=plan?.food?.rows;
   if(!Array.isArray(rows)||!rows.length)throw Error('P1の避難所データがありません。');
   const shelters=rows.map((r,i)=>{
    const d=Math.round(Number(r.stageDemandsKg?.[0]??r.demandKg)),stock=Math.round(Number(r.stageOpeningStocks?.[0]??r.initialStockKg));
    const lat=Number(r.lat),lng=Number(r.lng);
    if(![d,stock,lat,lng].every(Number.isFinite)||d<=0||stock<0)throw Error(`避難所${i+1}のデータを確認`);
    return {name:r.name,lat,lng,demandKits:d,stockKits:stock,visited:!!r.actualVisited};
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
   const payload=inputPayload(x,plan);
   show('P0計算中');const result=await calculate(payload);
   const resultStamp=stamp(cfg);
   sessionStorage.setItem('p0Result',JSON.stringify({planCreatedAt:plan.createdAt,settingsStamp:resultStamp,
    conditions:{t2:x.t2,t4:x.t4,trips:x.rounds,delta:x.delta,p0MinimumKg:x.minKg,
     p0TimeLimitSec:x.seconds,p0MipGapPercent:x.gap},result}));
   saveRun(x,result,plan,payload);display(result);show(result.feasible?'P0計算完了':result.reason||'実行可能案なし',!result.feasible);
  }catch(err){display(null);show('計算エラー：'+(err?.message||'設定・Renderログを確認'),true);}
  finally{btn.disabled=false;updateDerived();}
 }
 $('v65-run').addEventListener('click',run);
 for(const id of fields)$(id).addEventListener('input',()=>{scenarioEdited=true;refresh();});
 renderHistory(null);refresh();
})();
