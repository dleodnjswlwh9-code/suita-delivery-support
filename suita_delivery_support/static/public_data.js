(()=>{
  'use strict';
  const $=id=>document.getElementById(id);
  const panel=$('v53-data-preview'), sheetSelect=$('v53-sheet-select'), search=$('v53-search-input');
  const table=$('v53-preview-table'), state=$('v53-preview-state'), pageInfo=$('v53-page-info');
  const pageSize=40;
  const cache=new Map();
  let selected=null, sheets=[], page=0, requestId=0;

  function render(){
    table.replaceChildren();
    const sheet=sheets[Number(sheetSelect.value)]||null;
    if(!sheet){state.textContent='表示するシートがありません。';pageInfo.textContent='';return;}
    const rows=Array.isArray(sheet.rows)?sheet.rows:[];
    const keyword=search.value.trim().toLocaleLowerCase('ja-JP');
    const filtered=rows.filter(row=>!keyword||row.some(cell=>String(cell??'').toLocaleLowerCase('ja-JP').includes(keyword)));
    const pages=Math.max(1,Math.ceil(filtered.length/pageSize));
    page=Math.min(page,pages-1);
    const shown=filtered.slice(page*pageSize,(page+1)*pageSize);
    const colCount=Math.min(30,Math.max(1,...shown.map(r=>r.length),...rows.slice(0,2).map(r=>r.length)));
    // セルの内容は必ずtextContentを使用し、Excel内のHTML文字列を実行しない。
    const tbody=document.createElement('tbody');
    for(const row of shown){
      const tr=document.createElement('tr');
      for(let c=0;c<colCount;c++){
        const td=document.createElement('td');
        td.textContent=String(row[c]??'');
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody);
    state.textContent=`${sheet.name}：${filtered.length.toLocaleString('ja-JP')} 行`;
    pageInfo.textContent=`${page+1} / ${pages} ページ`;
    $('v53-prev').disabled=page===0;
    $('v53-next').disabled=page>=pages-1;
  }

  async function openDataset(key, button){
    const id=++requestId;
    for(const el of document.querySelectorAll('.v53-data-preview-btn')){
      el.setAttribute('aria-expanded',String(el===button));
    }
    selected=key;panel.hidden=false;
    $('v53-preview-title').textContent=button.closest('.v53-data-card').querySelector('h2').textContent;
    state.textContent='データを読み込んでいます。';
    table.replaceChildren();sheetSelect.replaceChildren();pageInfo.textContent='';
    search.value='';page=0;
    try{
      if(!cache.has(key)){
        const response=await fetch(`/api/public-data/${encodeURIComponent(key)}`);
        const result=await response.json();
        if(!response.ok||!Array.isArray(result.sheets))throw new Error(result.error||'データを読み込めませんでした。');
        cache.set(key,result.sheets);
      }
      if(id!==requestId||selected!==key)return;
      sheets=cache.get(key);
      for(let i=0;i<sheets.length;i++){
        const option=document.createElement('option');
        option.value=String(i);option.textContent=sheets[i].name;
        sheetSelect.append(option);
      }
      if(key==='shelters'){
        const index=sheets.findIndex(sheet=>sheet.name==='地域別検索・並替');
        if(index>=0)sheetSelect.value=String(index);
      }
      render();
      panel.scrollIntoView({behavior:'smooth',block:'start'});
    }catch(error){
      if(id!==requestId)return;
      state.textContent=error.message;
    }
  }

  document.querySelectorAll('.v53-data-preview-btn').forEach(button=>button.addEventListener('click',()=>openDataset(button.dataset.dataset,button)));
  sheetSelect.addEventListener('change',()=>{page=0;render()});
  search.addEventListener('input',()=>{page=0;render()});
  $('v53-prev').addEventListener('click',()=>{if(page>0){page--;render()}});
  $('v53-next').addEventListener('click',()=>{page++;render()});
  $('v53-preview-close').addEventListener('click',()=>{
    requestId++;selected=null;panel.hidden=true;
    document.querySelectorAll('.v53-data-preview-btn').forEach(btn=>btn.setAttribute('aria-expanded','false'));
  });
})();
