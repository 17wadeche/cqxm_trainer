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
  const matches=candidates.filter(c=>c.score===score&&!candidates.some(other=>other!==c&&other.score===score&&c.el.contains(other.el)));
  if(commit&&matches.length===1){matches[0].el.focus?.({preventScroll:true});matches[0].el.click();return {clicked:true,count:1,score};}
  return {clicked:false,count:matches.length,score:Number.isFinite(score)?score:99};
}
export function attachmentsInFrame(command='scan', key=null) {
  const norm=value=>(value||'').replace(/\s+/g,' ').trim();
  const visible=el=>{const style=getComputedStyle(el);return el.getClientRects().length>0&&style.visibility!=='hidden'&&style.display!=='none'&&!el.disabled&&el.getAttribute('aria-disabled')!=='true';};
  const cells=[...document.querySelectorAll('td[id*="GUIDE-AttachmentsTable"][id$="-Name"]')].filter(visible);
  const tables=[...new Set(cells.map(cell=>cell.closest('table')))];
  if(!tables.length)return {found:false,rows:[]};
  if(tables.length!==1)return {found:true,error:'More than one attachment table is visible. Open one event and try again.'};
  const table=tables[0];
  const rows=cells.filter(cell=>cell.closest('table')===table).map(cell=>{
    const row=cell.closest('tr'),type=norm(row.querySelector('td[id$="-Type"]')?.textContent);
    const name=norm(cell.innerText||cell.textContent);
    const links=[...cell.querySelectorAll('a,button,[role="button"]')].filter(visible);
    const fingerprint=JSON.stringify([name,type,norm(row.textContent)]);
    const media=/\.(jpe?g|png|gif|bmp|tiff?|webp|heic|svg|mp4|mov|avi|mkv|wmv|mpe?g|webm|m4v)$/i.test(name)||/^(image|video)\//i.test(type)||/\b(image|video|movie)\b/i.test(type)||/^(jpe?g|png|gif|bmp|tiff?|mp4|mov|avi)$/i.test(type);
    return {key:fingerprint,name,type,excluded:media,downloadable:links.length===1,links};
  }).filter(row=>row.name);
  const footer=document.getElementById(table.id.replace(/_TableHeader$/,'-footer'));
  const controls=footer?[...footer.querySelectorAll('a,button,[role="button"],input[type="button"]')].filter(visible):[];
  const pages=label=>controls.filter(el=>[el.title,el.getAttribute('aria-label'),el.innerText,el.value].some(value=>new RegExp('^'+label+'(?: page)?$','i').test(norm(value))));
  const next=pages('next'),first=pages('first');
  const range=norm(footer?.textContent).match(/(\d+)\s*[-–]\s*(\d+)\s+(?:of|\/)\s*(\d+)/i);
  const incomplete=range&&((Number(range[1])>1&&first.length===0)||(Number(range[2])<Number(range[3])&&next.length===0));
  if(command==='download'){
    const matches=rows.filter(row=>row.key===key&&!row.excluded&&row.downloadable);
    if(matches.length!==1)return {found:true,error:'The attachment row changed or has more than one download link.'};
    matches[0].links[0].click();return {clicked:true};
  }
  if(command==='next'||command==='first'){
    const choices=command==='next'?next:first;
    if(choices.length!==1)return {found:true,error:'The attachment page control could not be identified uniquely.'};
    choices[0].click();return {clicked:true};
  }
  return {found:true,rows:rows.map(({links,...row})=>row),pageKey:JSON.stringify(rows.map(row=>row.key)),
    next:next.length===1,first:first.length===1,
    error:incomplete?'Additional attachment pages exist, but their controls could not be identified.':next.length>1||first.length>1?'The attachment page controls are ambiguous.':null,
    coverageUnknown:!footer,
    paginationUnknown:controls.some(el=>/next|first/i.test(norm(el.title||el.getAttribute('aria-label')))&&!next.includes(el)&&!first.includes(el))};
}