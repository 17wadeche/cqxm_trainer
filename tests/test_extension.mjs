import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {recordContext, actionInFrame, attachmentsInFrame} from '../extension/gch-dom.mjs';
function element(text, attrs={}) {
  return {innerText:text, textContent:text, title:attrs.title||'', value:'', disabled:!!attrs.disabled,
    children:[], clicks:0, getAttribute(name){return attrs[name]??null;},
    closest(){return this.row||null;},querySelectorAll(){return this.children.filter(el=>el.selector);},
    getClientRects(){return attrs.hidden?[]:[{}];},
    contains(other){return this.children.includes(other);}, click(){this.clicks++;}};
}
function page(elements=[], text='', rows=[]) {
  globalThis.document={body:{innerText:text},querySelectorAll:selector=>selector==='tr'?rows:elements};
  globalThis.getComputedStyle=()=>({display:'block',visibility:'visible'});
}
test('visible record identifiers are deduplicated',()=>{
  page([], 'Product Event: 708930960\nProduct Event: 708930960');
  assert.deepEqual(recordContext().recordIds,['708930960']);
});
test('conflicting product event identifiers remain detectable',()=>{
  page([], 'Product Event: 708930960\nProduct Event: 708930961');
  assert.equal(recordContext().recordIds.length,2);
});
test('Print text is preferred over a printer icon title',()=>{
  const text=element('Print'),icon=element('',{title:'Print'});page([icon,text]);
  assert.equal(actionInFrame('Print',true).clicked,true);
  assert.equal(text.clicks,1);assert.equal(icon.clicks,0);
});
test('ambiguous Print actions do not click either control',()=>{
  const first=element('Print'),second=element('Print');page([first,second]);
  assert.equal(actionInFrame('Print',true).clicked,false);
  assert.equal(first.clicks+second.clicks,0);
});
test('hidden and disabled summary actions are ignored',()=>{
  const hidden=element('Product Event Summary Report',{hidden:true});
  const disabled=element('Product Event Summary Report',{disabled:true});
  const selected=element('Product Event Summary Report');page([hidden,disabled,selected]);
  assert.equal(actionInFrame('Product Event Summary Report',true).clicked,true);
  assert.equal(selected.clicks,1);assert.equal(hidden.clicks+disabled.clicks,0);
});
test('an actionable wrapper is not double-counted with its child',()=>{
  const wrapper=element('Print'),child=element('Print');wrapper.children=[child];page([wrapper,child]);
  assert.equal(actionInFrame('Print',true).count,1);
  assert.equal(child.clicks,1);assert.equal(wrapper.clicks,0);
});

function sapRow(label,attrs={}){
  const row=element(label,attrs),selector=element('',{title:'Select table row',...attrs});
  selector.selector=true;selector.row=row;row.children=[selector];
  return{row,selector};
}
test('SAP plain report label clicks the blank selector in the same row',()=>{
  const exact=sapRow('Product Event Summary Report'),pli=sapRow('Product Event Summary Report - PLI');
  page([exact.selector,pli.selector],'',[exact.row,pli.row]);
  assert.equal(actionInFrame('Product Event Summary Report',true).clicked,true);
  assert.equal(exact.selector.clicks,1);assert.equal(pli.selector.clicks,0);
});
test('SAP row matching ignores row numbers and collapses whitespace',()=>{
  const exact=sapRow('  Product\n Event\u00a0Summary Report  ');
  page([exact.selector],'',[exact.row]);
  assert.equal(actionInFrame('Product Event Summary Report',true).clicked,true);
});
test('SAP PLI-only row never matches the requested report',()=>{
  const pli=sapRow('Product Event Summary Report - PLI');
  page([pli.selector],'',[pli.row]);
  assert.equal(actionInFrame('Product Event Summary Report',true).count,0);
  assert.equal(pli.selector.clicks,0);
});
test('duplicate exact SAP report rows stop without clicking',()=>{
  const first=sapRow('Product Event Summary Report'),second=sapRow('Product Event Summary Report');
  page([first.selector,second.selector],'',[first.row,second.row]);
  const result=actionInFrame('Product Event Summary Report',true);
  assert.equal(result.count,2);assert.equal(result.clicked,false);
  assert.equal(first.selector.clicks+second.selector.clicks,0);
});
test('hidden and disabled SAP selectors are not chosen',()=>{
  const hidden=sapRow('Product Event Summary Report',{hidden:true});
  const disabled=sapRow('Product Event Summary Report',{disabled:true});
  page([hidden.selector,disabled.selector],'',[hidden.row,disabled.row]);
  assert.equal(actionInFrame('Product Event Summary Report',true).count,0);
});
test('SAP text link and selector in one row are a single report action',()=>{
  const exact=sapRow('Product Event Summary Report'),label=element('Product Event Summary Report');label.row=exact.row;
  page([exact.selector,label],'',[exact.row]);
  assert.equal(actionInFrame('Product Event Summary Report',true).count,1);
  assert.equal(exact.selector.clicks,1);assert.equal(label.clicks,0);
});
test('the floating button is not injected into SAP Print Preview',()=>{
  const window={location:{pathname:'/sap(===)/bc/bsp/sap/bsp_wd_base/popup_test.htm'}};window.top=window;
  const document={getElementById:()=>null,createElement:()=>assert.fail('Print Preview should not receive a launcher')};
  vm.runInNewContext(readFileSync(new URL('../extension/content.js',import.meta.url),'utf8'),{window,document});
});
test('Detailed Event Report uses its own SAP blank row selector',()=>{
  const detailed=sapRow('Detailed Event Report'),summary=sapRow('Product Event Summary Report'),pli=sapRow('Detailed Event Report - PLI');
  page([summary.selector,detailed.selector,pli.selector],'',[summary.row,detailed.row,pli.row]);
  assert.equal(actionInFrame('Detailed Event Report',true).clicked,true);
  assert.equal(detailed.selector.clicks,1);assert.equal(summary.selector.clicks+pli.selector.clicks,0);
});
test('ambiguous Detailed Event Report rows are never clicked',()=>{
  const a=sapRow('Detailed Event Report'),b=sapRow('Detailed Event Report');
  page([a.selector,b.selector],'',[a.row,b.row]);
  assert.equal(actionInFrame('Detailed Event Report',true).clicked,false);
  assert.equal(a.selector.clicks+b.selector.clicks,0);
});
function attachmentPage(entries, controls=[], footerText='1-3 of 3') {
  const table={id:'C27_W86_V87_Table_TableHeader'};
  const cells=entries.map(({name,type='',links=1,metadata=''})=>{
    const row={textContent:name+' '+type+' '+metadata,querySelector:()=>({textContent:type})};
    const cell=element(name);cell.links=Array.from({length:links},()=>element(name));
    cell.closest=selector=>selector==='table'?table:row;
    cell.querySelectorAll=()=>cell.links;
    return cell;
  });
  const footer={textContent:footerText,querySelectorAll:()=>controls};
  globalThis.document={querySelectorAll:()=>cells,getElementById:id=>id==='C27_W86_V87_Table-footer'?footer:null};
  globalThis.getComputedStyle=()=>({display:'block',visibility:'visible'});
  return cells;
}
test('SAP attachment names and types exclude media and keep incoming text files',()=>{
  attachmentPage([{name:'rep.msg',type:'Outlook message'},{name:'patient.pdf'},{name:'photo.jpg'},{name:'movie.mov'},{name:'scan',type:'image/png'},{name:'details.csv'}],[],'1-6 of 6');
  const scan=attachmentsInFrame();
  assert.equal(scan.found,true);
  assert.deepEqual(scan.rows.filter(row=>!row.excluded).map(row=>row.name),['rep.msg','patient.pdf','details.csv']);
});
test('attachment download uses its own name cell rather than a broad matching label',()=>{
  const cells=attachmentPage([{name:'rep.txt',metadata:'created yesterday'},{name:'rep.txt',metadata:'created today'}],[],'1-2 of 2');
  const scan=attachmentsInFrame();
  assert.equal(attachmentsInFrame('download',scan.rows[1].key).clicked,true);
  assert.equal(cells[0].links[0].clicks,0);assert.equal(cells[1].links[0].clicks,1);
});
test('ambiguous and excluded attachment links are never clicked',()=>{
  const cells=attachmentPage([{name:'rep.txt',links:2},{name:'photo.png'}],[],'1-2 of 2');
  const scan=attachmentsInFrame();
  for(const row of scan.rows)assert.match(attachmentsInFrame('download',row.key).error,/changed|more than one/);
  assert.equal(cells.flatMap(cell=>cell.links).reduce((n,link)=>n+link.clicks,0),0);
});
test('attachment pagination targets only the table footer',()=>{
  const next=element('',{title:'Next Page'}),first=element('',{title:'First Page'});
  attachmentPage([{name:'rep.txt'}],[next,first],'11-20 of 30');
  const scan=attachmentsInFrame();assert.equal(scan.next,true);assert.equal(scan.first,true);
  assert.equal(attachmentsInFrame('next').clicked,true);assert.equal(next.clicks,1);assert.equal(first.clicks,0);
});
test('attachment pagination cannot silently stop when more rows exist',()=>{
  attachmentPage([{name:'rep.txt'}],[],'1-10 of 30');
  assert.match(attachmentsInFrame().error,/Additional attachment pages/);
});
test('attachment scan reports an unavailable table',()=>{
  globalThis.document={querySelectorAll:()=>[]};
  assert.deepEqual(attachmentsInFrame(),{found:false,rows:[]});
});