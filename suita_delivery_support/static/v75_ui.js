/* v75 viewport-safe hover explanations. No sticky click-open tooltips. */
(()=>{
 'use strict';
 const sourceSelector='.condition-help, .p70-tip';
 let active=null, pop=null;
 const remove=()=>{if(pop){pop.remove();pop=null;}active=null;};
 const sourceText=el=>{
   const inner=el.matches('.p70-tip')?el.querySelector(':scope > span'):el.querySelector('.condition-tooltip');
   return inner?inner.textContent.replace(/\s+/g,' ').trim():'';
 };
 function position(){
   if(!active||!pop)return;
   const rect=active.getBoundingClientRect(),pad=12,gap=11;
   const available=Math.max(180,window.innerWidth-pad*2);
   pop.style.maxWidth=`${Math.min(510,available)}px`;
   pop.style.width=`${Math.min(510,Math.max(240,active.dataset.v75TipLen*12||240,0),available)}px`;
   let w=pop.offsetWidth,h=pop.offsetHeight;
   // Use the side of the icon with the most horizontal room, keeping
   // the note entirely inside the viewport at browser zoom 100%.
   let x=rect.left;
   if(x+w>window.innerWidth-pad)x=rect.right-w;
   x=Math.max(pad,Math.min(x,window.innerWidth-w-pad));
   const below=window.innerHeight-rect.bottom-pad-gap;
   const above=rect.top-pad-gap;
   let y=below>=h?rect.bottom+gap:above>=h?rect.top-h-gap:null;
   if(y===null){
     // Near the viewport bottom/right, move to the left or right of the icon.
     const leftSpace=rect.left-pad-gap,rightSpace=window.innerWidth-rect.right-pad-gap;
     if(Math.max(leftSpace,rightSpace)>=w){x=rightSpace>=leftSpace?rect.right+gap:rect.left-gap-w;y=rect.top+(rect.height-h)/2;}
     else y=(below>=above?rect.bottom+gap:rect.top-h-gap);
   }
   y=Math.max(pad,Math.min(y,window.innerHeight-h-pad));
   pop.style.left=`${Math.round(x)}px`;pop.style.top=`${Math.round(y)}px`;
 }
 function show(el){
   const tip=sourceText(el);if(!tip)return;
   if(active===el)return;
   remove();active=el;el.dataset.v75TipLen=String(tip.length);
   pop=document.createElement('div');pop.className='v75-floating-tooltip';pop.setAttribute('role','tooltip');pop.textContent=tip;
   document.body.append(pop);position();
 }
 function ready(){
   document.body.classList.add('v75-tooltip-ready');
   // Shared handlers also cover dynamically created information labels.
   document.addEventListener('pointerover',e=>{
     const target=e.target.closest?.(sourceSelector);
     if(target)show(target);
     else if(active&&!active.contains(e.target))remove();
   });
   document.addEventListener('pointerout',e=>{
     if(active?.contains(e.target)&&!active.contains(e.relatedTarget))remove();
   });
   document.addEventListener('focusin',e=>{const target=e.target.closest?.(sourceSelector);if(target)show(target);else remove();});
   document.addEventListener('focusout',e=>{if(active?.contains(e.target)&&!active.contains(e.relatedTarget))remove();});
   document.addEventListener('click',e=>{
     if(e.target.closest?.('.p70-tip > summary'))e.preventDefault();
   },true);
   document.addEventListener('keydown',e=>{if(e.key==='Escape')remove();});
   window.addEventListener('scroll',()=>{if(active)position();},{passive:true});
   window.addEventListener('resize',()=>{if(active)position();});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();
})();
