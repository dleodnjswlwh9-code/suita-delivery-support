/* v52: Visual-only separation of shared outbound/return road sections.
 * Original Google route coordinates and travel-time evaluation are never mutated.
 * Pixel offsets are recomputed after zoom changes so the lines remain legible.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RouteOverlap = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const R = 6378137, DEG = Math.PI / 180;
  const MAX_SAMPLE_M = 6, GRID_M = 12, MATCH_M = 5.5;
  const MATCH_COS = Math.cos(24 * DEG), MIN_SHARED_M = 18;

  function validPoint(p) {
    const lat = typeof p.lat === 'function' ? p.lat() : p.lat;
    const lng = typeof p.lng === 'function' ? p.lng() : p.lng;
    if (!Number.isFinite(Number(lat)) || !Number.isFinite(Number(lng))) return null;
    return {lat:Number(lat),lng:Number(lng)};
  }
  function localXY(p,cosLat){return {x:R*p.lng*DEG*cosLat,y:R*p.lat*DEG};}
  function samplePath(path,cosLat){
    const raw = (path||[]).map(validPoint).filter(Boolean);
    if(raw.length < 2) return raw.map(p=>({...p,...localXY(p,cosLat)}));
    const output=[];
    for(let i=0;i<raw.length-1;i++){
      const a=raw[i],b=raw[i+1],pa=localXY(a,cosLat),pb=localXY(b,cosLat);
      const d=Math.hypot(pb.x-pa.x,pb.y-pa.y);
      const steps=Math.max(1,Math.ceil(d/MAX_SAMPLE_M));
      for(let j=0;j<steps;j++){
        const t=j/steps;
        output.push({lat:a.lat+(b.lat-a.lat)*t,lng:a.lng+(b.lng-a.lng)*t,x:pa.x+(pb.x-pa.x)*t,y:pa.y+(pb.y-pa.y)*t});
      }
    }
    const last=raw[raw.length-1];output.push({...last,...localXY(last,cosLat)});
    return output;
  }
  function segments(points){
    const arr=[];
    for(let i=0;i<points.length-1;i++){
      const a=points[i],b=points[i+1],dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy);
      arr.push({a,b,mx:(a.x+b.x)/2,my:(a.y+b.y)/2,dx:len?dx/len:0,dy:len?dy/len:0,len,index:i});
    }
    return arr;
  }
  function gridKey(x,y){return `${Math.floor(x/GRID_M)}|${Math.floor(y/GRID_M)}`;}
  function buildIndex(segs){
    const index=new Map();
    for(const s of segs){
      if(s.len<0.02)continue;
      const lowX=Math.floor((Math.min(s.a.x,s.b.x)-MATCH_M)/GRID_M),highX=Math.floor((Math.max(s.a.x,s.b.x)+MATCH_M)/GRID_M);
      const lowY=Math.floor((Math.min(s.a.y,s.b.y)-MATCH_M)/GRID_M),highY=Math.floor((Math.max(s.a.y,s.b.y)+MATCH_M)/GRID_M);
      for(let x=lowX;x<=highX;x++)for(let y=lowY;y<=highY;y++){
        const key=`${x}|${y}`;if(!index.has(key))index.set(key,[]);index.get(key).push(s);
      }
    }
    return index;
  }
  function distanceToSegmentSq(px,py,s){
    const vx=s.b.x-s.a.x,vy=s.b.y-s.a.y,n=vx*vx+vy*vy;
    const t=n?Math.max(0,Math.min(1,((px-s.a.x)*vx+(py-s.a.y)*vy)/n)):0;
    const dx=px-(s.a.x+vx*t),dy=py-(s.a.y+vy*t);
    return dx*dx+dy*dy;
  }
  function findMatches(segs,index){
    const found=segs.map(s=>{
      if(s.len<0.02)return {match:false,dot:0};
      const candidates=index.get(gridKey(s.mx,s.my))||[];
      let bestDist=MATCH_M*MATCH_M,bestDot=0,found=false;
      for(const c of candidates){
        const dot=s.dx*c.dx+s.dy*c.dy;
        if(Math.abs(dot)<MATCH_COS)continue; // A crossing street is not a shared road.
        const dist=distanceToSegmentSq(s.mx,s.my,c);
        if(dist<=bestDist){bestDist=dist;bestDot=dot;found=true;}
      }
      return {match:found,dot:bestDot};
    });
    // Reject incidental intersections and very short roadside proximity.
    for(let i=0;i<segs.length;){
      if(!found[i].match){i++;continue;}
      let j=i,meters=0;
      while(j<segs.length&&found[j].match){meters+=segs[j].len;j++;}
      if(meters<MIN_SHARED_M)for(let k=i;k<j;k++)found[k]={match:false,dot:0};
      i=j;
    }
    return found;
  }
  function toWorld(p){
    const sin=Math.min(.9999,Math.max(-.9999,Math.sin(p.lat*DEG)));
    return {x:(p.lng+180)/360*256,y:(.5-Math.log((1+sin)/(1-sin))/(4*Math.PI))*256};
  }
  function fromWorld(x,y){
    return {lat:Math.atan(Math.sinh(Math.PI*(1-2*y/256)))/DEG,lng:x/256*360-180};
  }
  function offsetPath(points,matched,zoom,pixels,isReturn){
    if(!matched.some(m=>m.match))return points.map(p=>({lat:p.lat,lng:p.lng}));
    const scale=2**Math.max(0,Math.min(22,zoom));
    const world=points.map(p=>toWorld(p));
    return points.map((p,i)=>{
      if(i===0 || i===points.length-1)return {lat:p.lat,lng:p.lng};
      // Smooth the entry and exit to shared sections. Do not shift other roads.
      const weights=[.12,.23,.30,.23,.12];let amount=0,total=0,heading=0;
      for(let d=-2;d<=2;d++){
        const at=i-1+d,w=weights[d+2];if(at<0||at>=matched.length)continue;
        total+=w;if(matched[at].match){amount+=w;heading+=w*matched[at].dot;}
      }
      if(total===0||amount===0)return {lat:p.lat,lng:p.lng};
      const before=world[i-1],after=world[i+1],dx=(after.x-before.x)*scale,dy=(after.y-before.y)*scale;
      const len=Math.hypot(dx,dy);
      if(len<.001)return {lat:p.lat,lng:p.lng};
      // Each vehicle's right-hand edge. Reverse traffic naturally has an
      // opposite right side. Same-direction shared geometry needs the other side.
      const side=(isReturn && heading>0)?-1:1;
      const delta=pixels*Math.min(1,amount/total)*side/scale;
      return fromWorld(world[i].x-dy/len*delta,world[i].y+dx/len*delta);
    });
  }
  function separate(legs,zoom,pixels=3.3){
    if(!Array.isArray(legs)||legs.length<2)return (legs||[]).map(l=>(l.path||[]).map(validPoint).filter(Boolean));
    const allPoints=legs.flatMap(l=>l.path||[]).map(validPoint).filter(Boolean);
    const latitude=allPoints.length?allPoints.reduce((s,p)=>s+p.lat,0)/allPoints.length:35;
    const cosLat=Math.cos(latitude*DEG);
    const pieces=legs.map(l=>samplePath(l.path||[],cosLat));
    const out=pieces.slice(0,-1),back=pieces.at(-1);
    const outSegments=out.map(segments),backSegments=segments(back);
    const idxBack=buildIndex(backSegments),idxOut=buildIndex(outSegments.flat());
    return pieces.map((points,i)=>{
      const isReturn=i===pieces.length-1;
      const m=findMatches(isReturn?backSegments:outSegments[i],isReturn?idxOut:idxBack);
      return offsetPath(points,m,zoom,pixels,isReturn);
    });
  }
  return {separate, samplePath, segments, buildIndex,findMatches,offsetPath};
});
