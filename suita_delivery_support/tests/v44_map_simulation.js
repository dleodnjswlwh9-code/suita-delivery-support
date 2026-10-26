const fs=require('fs'),vm=require('vm'),assert=require('assert');
const path=require('path');
const requests=[],polys=[],allPins=[],allOverlays=[],boundsCalls=[];
const settings={t2:7,trips:1,delta:1};
const alloc={version:'v45-complete-kit-p1',food:{rows:[]},stages:[{totalKg:500}],p1DeliverySettings:{vehicles:[{count:7}],trips:1,delta:1},createdAt:'now1'};
const hubs=[{id:0,lat:34.8,lng:135.53,name:'北部'},{id:1,lat:34.7,lng:135.49,name:'南部'}];
let shelters=[],routes=[];
for(let k=0;k<9;k++){shelters.push({index:k,name:'避難所'+k,lat:34.73+k*.004,lng:135.51+k*.001,stockKits:5,demandKits:100}); alloc.food.rows.push({name:'避難所'+k});}
for(let k=1;k<=7;k++){const inds=k===7?[6,8,7]:[k-1];routes.push({round:1,truck:k,hub:k%2,stops:inds.map(i=>({index:i,name:shelters[i].name,lat:shelters[i].lat,lng:shelters[i].lng,kits:5})),timeMin:33,kits:5*inds.length});}
const result={hubs,shelters,routes,maxRounds:1,usedRounds:1,usedTrucks:7,trucksConfigured:7,deliveredKits:55,visitedShelters:9,shelterCount:9,f1Star:0,f1Route:0,f1Excess:0,f3:0,hubOutgoingKits:[25,30],f2Minutes:44,isValidatedP2:true};
const storage={allocationPlan:JSON.stringify(alloc),p1DeliverySettings:JSON.stringify(settings),p2Result:JSON.stringify({p1CreatedAt:'now1',roadMode:'all',result})};
let listItems=[];
class Element{
 constructor(id=''){this.id=id;this.value='all';this.dataset={};this.style={};this.hidden=false;this.classList={toggle(){},add(){},remove(){}};this.listeners={};this._innerHTML='';this.checked=false;this.textContent='';this.title='';}
 get innerHTML(){return this._innerHTML;}
 set innerHTML(txt){this._innerHTML=txt;
  if(this.id==='p2-vehicle-list'){
   listItems=[...txt.matchAll(/<button[^>]+class="p2-tour-item"[^>]+data-round="([^"]+)" data-truck="([^"]+)"/g)].map(m=>{
     const el=new Element('truck'+m[2]);el.dataset={round:m[1],truck:m[2]};el.childrenCache={};return el;
   });
  }
 }
 addEventListener(ev,fn){this.listeners[ev]=fn;}
 fire(ev,payload){assert(this.listeners[ev]);this.listeners[ev](payload);}
 setAttribute(){}
 querySelectorAll(q){if(this.id==='p2-vehicle-list'&&q==='.p2-tour-item')return listItems;return [];}
 querySelector(q){this.childrenCache??={};return this.childrenCache[q]??(this.childrenCache[q]=new Element(q));}
 appendChild(){} remove(){};
}
const els={};const toolbarBtns=['all','out','back'].map(k=>{const b=new Element('button-'+k);b.dataset.journey=k;return b;});
const document={getElementById(id){return els[id]??(els[id]=new Element(id))},createElement(){return new Element()},querySelectorAll(q){
 if(q.includes('p2-journey-toolbar'))return toolbarBtns;
 if(q.includes('#p2-vehicle-list'))return listItems;
 return [];
}};
class OverlayView{setMap(map){this.map=map;if(map){allOverlays.push(this);this.onAdd?.();this.draw?.();}else{this.onRemove?.();}}getPanes(){return {overlayMouseTarget:new Element()}}getProjection(){return {fromLatLngToDivPixel(){return {x:1,y:1}}}}}
class Polyline{constructor(opts){this.opts=opts;this.map=opts.map;polys.push(this)}setMap(map){this.map=map}}
const google={maps:{Map:class{constructor(){}fitBounds(bounds){boundsCalls.push(bounds.coords.map(x=>({...x}))) }},Polyline,SymbolPath:{FORWARD_CLOSED_ARROW:'FORWARD_CLOSED_ARROW'},LatLngBounds:class{constructor(){this.coords=[]}extend(pt){this.coords.push(pt)}},Marker:class{constructor(opts){this.map=opts.map;allPins.push(this)}setMap(map){this.map=map}},OverlayView,InfoWindow:class{},
importLibrary:async()=>({Route:{computeRoutes:async req=>{
 requests.push(req);
 const intermediates=req.intermediates.map(p=>p.location);
 const order=intermediates.map((x,i)=>i);
 if(req.optimizeWaypointOrder&&intermediates.length>1)order.reverse();
 const nodes=[req.origin,...order.map(i=>intermediates[i]),req.destination];
 const legs=nodes.slice(1).map((b,i)=>({path:[nodes[i],{lat:34.93,lng:135.60},b],distanceMeters:2000,durationMillis:360000}));
 return {routes:[{path:legs.flatMap(l=>l.path),legs,optimizedIntermediateWaypointIndices:req.optimizeWaypointOrder?order:[],durationMillis:legs.length*360000,distanceMeters:legs.length*2000}]};
}}})}};
const window={google};const sessionStorage={getItem(k){return storage[k]||null},setItem(k,v){storage[k]=v}};
const ctx={document,google,window,sessionStorage,console,fetch:()=>{},setTimeout};
const routeHtml=fs.readFileSync(path.join(__dirname,'../templates/routes.html'),'utf8');
const script=routeHtml.match(/<script>([\s\S]*?)<\/script>/)[1].replace('{{ allocation_schema_version | tojson }}',"'v45-complete-kit-p1'");
vm.runInNewContext(script,ctx);
const pause=m=>new Promise(r=>setTimeout(r,m));
(async()=>{
 window.initP2GoogleMap(); await pause(2600);
 assert.equal(requests.length,7,'seven truck routes requested in overall view');
 assert(requests.find(x=>x.intermediates.length===3).optimizeWaypointOrder,'Google automatic stop reordering for truck 7');
 const live=JSON.parse(storage.p2Result).traffic;
 assert(live&&live.routes.length===7,'live F2 saved');
 assert.equal(live.routes.find(x=>x.truck===7).orderedStopIndexes.join(','),'7,8,6','truck 7 reordered using road time');
 assert.equal(els['p2-f2'].textContent,'1時間40分','largest run duration + work time includes traffic');
 assert.equal(els['p2-traffic-summary'].textContent.includes('全7出動'),true);
 const coords=boundsCalls.at(-1);
 assert(coords.some(p=>p.lat===34.93&&p.lng===135.60),'zoom includes actual detour path not just shelter points');
 assert(polys.some(p=>p.opts.strokeColor==='#d62833'&&p.map),'outbound red rendered');
 assert(polys.some(p=>p.opts.strokeColor==='#246bda'&&p.map),'return blue rendered');
 els['p2-round'].value='1';els['p2-truck'].value='7';els['p2-round'].fire('change'); await pause(75);
 assert.equal(allOverlays.filter(o=>o.map).length,3,'only truck 7 shelter circles');
 assert.equal(allPins.filter(o=>o.map).length,1,'only truck 7 hub');
 assert.equal(els['p2-route-detail'].hidden,false);
 assert(els['p2-route-detail'].innerHTML.includes('3. 避難所6'));
 assert(els['p2-route-detail'].innerHTML.includes('帰着：'));
 assert(els['p2-route-detail'].innerHTML.includes('① 配送（赤）'));
 assert(els['p2-route-detail'].innerHTML.includes('② 拠点へ帰着（青）'));
 assert(els['p2-route-detail'].innerHTML.includes('1. 避難所7'));
 assert(els['p2-route-detail'].innerHTML.includes('避難所7'));
 assert(!els['p2-route-detail'].innerHTML.includes('避難所0'));
 const before=requests.length;
 toolbarBtns[2].fire('click');await pause(50);
 assert.equal(requests.length,before,'mode filter does not refetch cached data');
 assert.equal(polys.filter(p=>p.map&&p.opts.strokeColor==='#d62833').length,0,'return mode hides outbound');
 assert(polys.filter(p=>p.map&&p.opts.strokeColor==='#246bda').length>0,'return mode shows inbound');
 assert.equal(boundsCalls.at(-1).some(p=>p.lat===34.93),true,'return path fit includes highway detour');
 els['p2-avoid-expressway'].checked=true;
 els['p2-avoid-expressway'].fire('change');await pause(80);
 assert.equal(requests.length,before+1,'avoid expressway triggers new real route request');
 assert(requests.at(-1).routeModifiers.avoidHighways===true&&requests.at(-1).routeModifiers.avoidTolls===true);
 els['p2-avoid-expressway'].checked=false;
 els['p2-avoid-expressway'].fire('change');await pause(70);
 assert.equal(requests.length,before+1,'original route cache reused when normal mode restored');
 console.log('PASS v44 mock: 7 trucks, optimized route #7, start/end sequence, red out/blue back, bounds along actual path, no truncated stops, selection filtered');
})().catch(e=>{console.error(e.stack);process.exit(1)});
