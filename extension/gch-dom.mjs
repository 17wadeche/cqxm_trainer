// These functions are self-contained so Chrome can inject them into permitted frames.
export function recordContext() {
  const text=document.body?.innerText||'';
  const matches=[...text.matchAll(/Product\s+Event\s*:\s*(\d{6,12})/gi)].map(m=>m[1]);
  if(!matches.length)matches.push(...[...text.matchAll(/\bPE\s*:\s*(\d{6,12})/g)].map(m=>m[1]));
  const status=text.match(/\bStatus\s*:\s*([^\n]{1,80})/i)?.[1]?.trim()||'';
  return {recordIds:[...new Set(matches)],status};
}
export function actionInFrame(label,commit=false) {
  const norm=value=>(value||'').replace(/\s+/g,' ').trim().toLowerCase();
  const target=norm(label);
  const visible=el=>{const style=getComputedStyle(el);return el.getClientRects().length>0&&style.visibility!=='hidden'&&style.display!=='none'&&!el.disabled&&el.getAttribute('aria-disabled')!=='true';};
  const candidates=[];
  // SAP's Print Preview lists plain text in one cell and a blank selection
  // link in another. Match the exact row label, then use that row's own link.
  // IDs contain generated component and row numbers; never hard-code _sel_5.
  const reportRows=new Set();
  if(['detailed event report','product event summary report'].includes(target)){
    for(const row of document.querySelectorAll('tr')){
      if(!visible(row)||norm(row.innerText||row.textContent)!==target)continue;
      const selectors=[...row.querySelectorAll('a[id$="-rowsel"],a[title="Select table row"]')]
        .filter(el=>el.closest('tr')===row&&visible(el));
      if(selectors.length){
        reportRows.add(row);
        for(const el of selectors)candidates.push({el,score:0});
      }
    }
  }
  for(const el of document.querySelectorAll('a,button,input[type=button],input[type=submit],[role=button],[role=menuitem],[onclick]')){
    if(!visible(el))continue;
    if(reportRows.has(el.closest('tr')))continue;
    const text=norm(el.value||el.innerText||el.textContent);
    const score=text===target?0:([el.getAttribute('aria-label'),el.title].some(v=>norm(v)===target)?1:99);
    if(score<99)candidates.push({el,score});
  }
  const score=Math.min(...candidates.map(c=>c.score));
  // Ignore wrapper elements when their exact-label descendant is also actionable.
  const matches=candidates.filter(c=>c.score===score&&!candidates.some(other=>other!==c&&other.score===score&&c.el.contains(other.el)));
  if(commit&&matches.length===1){matches[0].el.focus?.({preventScroll:true});matches[0].el.click();return {clicked:true,count:1,score};}
  return {clicked:false,count:matches.length,score:Number.isFinite(score)?score:99};
}
