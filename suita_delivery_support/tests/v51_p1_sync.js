const assert=require('assert');
const fs=require('fs');const vm=require('vm');const path=require('path');
const sandbox={window:{},Date,JSON,Number,Math,Error,Array,console};vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/p1_sync.js'),'utf8'),sandbox);
const sync=sandbox.window.syncAllocationForDeliverySettings;
const plan={createdAt:'old',targetRate:.8,rho:.001,stages:[{totalKg:25}],
 p1DeliverySettings:{delta:1,trips:1,vehicles:[{capacityKg:2000,count:1}]},
 food:{rows:[],stageSummaries:[{objectiveF1:2}],totalUsedKg:0},
 water:{rows:[],stageSummaries:[{objectiveF1:2}],totalUsedKg:0}};
for(const name of ['A','B'])for(const kind of ['food','water']){
  plan[kind].rows.push({name,lat:34.7,lng:135.5,demandKg:40,stageDemandsKg:[40],
   initialStockKg:10,stageOpeningStocks:[10],stageAllocations:[0],stageClosingStocks:[10],
   stageRates:[0.25],currentStockKg:10});
}
const settings={t2:2,delta:10,trips:3};
(async()=>{
 let sent=null;
 const revised=await sync(plan,settings,async(url,req)=>{
   sent=JSON.parse(req.body);return {ok:true,json:async()=>({allocations:[10,15],objectiveF1:3.14,theta:.2,mandatoryCount:2,activeCount:2})};
 });
 assert.strictEqual(sent.minKits,10);assert.strictEqual(sent.truckCount,2);
 assert.strictEqual(sent.shelters[0].stockKits,10);
 assert.strictEqual(revised.food.rows[0].currentStockKg,20);
 assert.strictEqual(revised.water.rows[1].stageAllocations[0],15);
 assert.strictEqual(revised.food.stageSummaries[0].objectiveF1,3.14);
 assert.strictEqual(revised.food.stageSummaries[0].usedKg,12.5);
 assert.strictEqual(revised.p1DeliverySettings.delta,10);
 assert.strictEqual(plan.food.rows[0].currentStockKg,10);
 assert.strictEqual(plan.createdAt,'old');
 // If the P1 re-solve fails no old allocation is mutated.
 await assert.rejects(()=>sync(plan,settings,async()=>({ok:false,json:async()=>({error:'在庫不足'})})),/在庫不足/);
 assert.strictEqual(plan.createdAt,'old');
 console.log('v51 P1 save synchronization: OK');
})().catch(e=>{console.error(e);process.exit(1)});
