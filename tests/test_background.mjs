import test from 'node:test';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const wait=ms=>new Promise(r=>setTimeout(r,ms));
function event(){const listeners=[];return{addListener:fn=>listeners.push(fn),fire:(...args)=>listeners.map(fn=>fn(...args)),listeners};}
async function fixture(options={}){
  const values={},calls=[],clicks=[],clickedTabs=[],notices=[],alarms=new Map(),portMessages=event(),disconnect=event();
  const tab={id:4,url:'https://crm.medtronic.com/sap/',windowId:1},id='abcdefghijklmnopabcdefghijklmnop';
  const tabs=[tab,...(options.initialTabs||[])];
  let token=options.token!==false;
  const native=async(method,data)=>{
    calls.push({method,data});
    if(options.handler){const result=await options.handler(method,data);if(result!==undefined)return result;}
    if(method==='status')return{token_present:token,remember_supported:true,missing_procedures:options.missing||[]};
    if(method==='token'){token=true;return{};}
    if(method==='capture_start')return{capture_id:'capture-1'};
    if(method==='capture_complete')return{id:'job-1'};
    if(method==='job')return{id:'job-1',status:'ready',filename:'GCH_Review_TEST.docx',needs_evidence:3};
    return{};
  };
  globalThis.chrome={
    runtime:{id,lastError:null,getURL:path=>'chrome-extension://'+id+'/'+path,onMessage:event(),
      connectNative:()=>({onMessage:portMessages,onDisconnect:disconnect,postMessage:request=>{
        queueMicrotask(async()=>{try{portMessages.fire({id:request.id,ok:true,result:await native(request.method,request.data)});}catch(error){portMessages.fire({id:request.id,ok:false,error:error.message});}});
      }}),sendMessage:async message=>{notices.push(message);},openOptionsPage:async()=>{}},
    storage:{session:{get:async key=>({[key]:structuredClone(values[key])}),set:async value=>Object.assign(values,structuredClone(value)),remove:async key=>{delete values[key];}}},
    tabs:{query:async query=>query?.url?tabs:[tab],get:async id=>tabs.find(t=>t.id===id)||({id,openerTabId:4,active:true}),onRemoved:event(),update:async(id,data)=>{calls.push({method:'focus_gch',id,data});},create:async()=>{assert.fail('Trainee workflow must not open a new app tab');}},
    windows:{update:async(id,data)=>{calls.push({method:'focus_window',id,data});}},
    alarms:{create:async(name,data)=>alarms.set(name,data),clear:async name=>alarms.delete(name),onAlarm:event()},
    webNavigation:{onCreatedNavigationTarget:event(),onBeforeNavigate:event(),getAllFrames:async({tabId})=>{
      if(options.frames){const result=await options.frames(tabId);if(result!==undefined)return result;}
      return[{frameId:0,url:tabs.find(t=>t.id===tabId)?.url||tab.url},{frameId:8,url:'chrome-extension://'+id+'/panel.html'}];
    }},
    scripting:{executeScript:async spec=>{
      assert.deepEqual(spec.target.frameIds,[0]);
      if(spec.func.name==='htmlAttachmentBody')return options.htmlBody?options.htmlBody(spec):[{frameId:0,result:null}];
      if(spec.func.name==='recordContext')return[{frameId:0,result:{recordIds:['708930960'],status:'Re-Open'}}];
      if(spec.func.name==='attachmentsInFrame')return options.attachments?options.attachments(spec,chrome):[{frameId:0,result:{found:false,rows:[]}}];
      if(spec.args[1]){clicks.push(spec.args[0]);clickedTabs.push({label:spec.args[0],tabId:spec.target.tabId});}
      if(spec.args[0]==='Print'&&spec.args[1]&&options.onPrint)await options.onPrint({tabs,events:chrome});
      if(options.onScript)await options.onScript(spec);
      let count=spec.args[0]==='Detailed Event Report'&&options.summaryTabs&&!options.summaryTabs.includes(spec.target.tabId)?0:1;
      if(spec.args[0]==='Detailed Event Report'&&options.noDetailed)count=0;
      if(spec.args[0]==='Product Event Summary Report')count=options.noDetailed?1:0;
      if(spec.args[0]==='Attachments')count=0;
      return[{frameId:0,result:{count,score:0,clicked:count>0&&!!spec.args[1]}}];
    }},
    downloads:{onCreated:event(),onChanged:event(),search:async query=>options.downloadSearch?options.downloadSearch(query):[],
      resume:async id=>{calls.push({method:'resume_download',id});if(options.resume)await options.resume(id);},
      cancel:async id=>calls.push({method:'cancel_download',id}),
      download:async data=>{calls.push({method:'chrome_download',data});if(options.download)return options.download(data);return 9;}},    webRequest:{onHeadersReceived:event()}
  };
  await import(pathToFileURL(resolve('extension/background.js')).href+'?fixture='+Math.random());
  const sender={id,url:chrome.runtime.getURL('panel.html'),tab};
  const send=(message,from=sender)=>new Promise(resolve=>chrome.runtime.onMessage.listeners[0](message,from,resolve));
  const download=()=>chrome.downloads.onCreated.fire({id:1,url:tab.url+'report.pdf',filename:'C:\\Downloads\\report.pdf',mime:'application/pdf',state:'complete',startTime:new Date().toISOString()});
  const until=async predicate=>{for(let i=0;i<150;i++){if(predicate())return;await wait(10);}assert.fail('Expected workflow state did not arrive');};
  return{values,calls,clicks,clickedTabs,notices,alarms,send,download,until,tab,tabs,events:chrome};
}
test('interrupted report resumes after a 30 second alarm without starting a new capture',async()=>{
  const item={id:7,url:'https://crm.medtronic.com/sap/report.pdf',filename:'C:\\Downloads\\report.pdf',mime:'application/pdf',state:'interrupted',canResume:true,startTime:new Date().toISOString()};
  const f=await fixture({downloadSearch:()=>[item]});await f.send({type:'START'});
  const before=Date.now();f.events.downloads.onCreated.fire(item);
  await f.until(()=>f.alarms.has('download-retry'));
  assert.ok(f.alarms.get('download-retry').when>=before+30000);
  assert.equal(f.calls.some(c=>c.method==='resume_download'),false);
  f.events.alarms.onAlarm.fire({name:'download-retry'});
  await f.until(()=>f.calls.some(c=>c.method==='resume_download'));
  item.state='complete';f.events.downloads.onChanged.fire({id:7,state:{current:'complete'}});
  await f.until(()=>f.values['flow-4']?.phase==='done');
  assert.equal(f.calls.filter(c=>c.method==='capture_start').length,1);
  assert.equal(f.calls.filter(c=>c.method==='capture_complete').length,1);
  assert.deepEqual(f.clicks,['Print','Detailed Event Report']);
});
test('non-resumable report is downloaded again and the failed file is ignored',async()=>{
  const item={id:7,url:'https://crm.medtronic.com/sap/report.pdf',filename:'C:\\Downloads\\report.pdf',mime:'application/pdf',state:'interrupted',canResume:false,startTime:new Date().toISOString()};
  const f=await fixture({downloadSearch:()=>[item]});await f.send({type:'START'});
  f.events.downloads.onCreated.fire(item);await f.until(()=>f.alarms.has('download-retry'));
  f.events.alarms.onAlarm.fire({name:'download-retry'});
  await f.until(()=>f.calls.some(c=>c.method==='chrome_download'));
  f.events.downloads.onCreated.fire({...item,state:'complete'});
  f.events.downloads.onCreated.fire({...item,id:9,state:'complete'});
  await f.until(()=>f.values['flow-4']?.phase==='done');
  assert.equal(f.calls.filter(c=>c.method==='capture_complete').length,1);
});
test('viewer download failure retries the same URL and cancellation clears the retry',async()=>{
  const f=await fixture({download:()=>{throw new Error('Network failed');}});await f.send({type:'START'});
  const url=f.tab.url+'generated.pdf';
  f.events.webRequest.onHeadersReceived.fire({method:'GET',type:'main_frame',tabId:5,url,responseHeaders:[{name:'Content-Type',value:'application/pdf'}]});
  await f.until(()=>f.alarms.has('download-retry'));
  f.events.alarms.onAlarm.fire({name:'download-retry'});
  await f.until(()=>f.calls.filter(c=>c.method==='chrome_download').length===2&&f.values.capture.downloadRetry);
  assert.equal(f.calls.filter(c=>c.method==='chrome_download')[1].data.url,url);
  await f.send({type:'CANCEL'});assert.equal(f.alarms.has('download-retry'),false);
  f.events.alarms.onAlarm.fire({name:'download-retry'});await wait(20);
  assert.equal(f.calls.filter(c=>c.method==='chrome_download').length,2);
  assert.equal(f.values['flow-4'].phase,'idle');
});
test('viewer HTTP 503 preserves the capture and schedules its failed URL',async()=>{
  const f=await fixture();await f.send({type:'START'});
  const url=f.tab.url+'generated.pdf';
  f.events.webRequest.onHeadersReceived.fire({method:'GET',type:'main_frame',tabId:5,url,statusCode:503,responseHeaders:[{name:'Content-Type',value:'text/html'}]});
  await f.until(()=>f.alarms.has('download-retry'));
  assert.equal(f.values.capture.downloadRetry.url,url);
  assert.equal(f.values['flow-4'].phase,'exporting');
  await f.send({type:'CANCEL'});
});
test('one click exports, reviews and saves without opening an app tab',async()=>{
  const f=await fixture();const start=await f.send({type:'START'});
  assert.equal(start.state.phase,'exporting');
  assert.deepEqual(f.clicks,['Print','Detailed Event Report']);
  f.download();await f.until(()=>f.values['flow-4']?.phase==='done');
  assert.equal(f.values['flow-4'].filename,'GCH_Review_TEST.docx');
  assert.equal(f.calls.filter(c=>c.method==='capture_complete').length,1);
});
test('missing token is prompted and successful entry resumes the same button workflow',async()=>{
  const f=await fixture({token:false});
  assert.equal((await f.send({type:'START'})).state.phase,'token');
  assert.equal(f.clicks.length,0);
  assert.equal((await f.send({type:'TOKEN',token:'test-only',remember:true})).state.phase,'exporting');
  assert.equal(JSON.stringify(f.values).includes('test-only'),false);
  await f.send({type:'CANCEL'});
});
test('the token flow is locked to Production even if a stale panel requests Development',async()=>{
  const f=await fixture({token:false,handler:(method)=>method==='status'?{token_present:false,environment:'production',remember_supported:true,missing_procedures:[]}:undefined});
  assert.equal((await f.send({type:'START'})).state.environment,'production');
  await f.send({type:'TOKEN',token:'test-only',remember:false,environment:'development'});
  const tokenCall=f.calls.find(c=>c.method==='token');
  assert.equal(tokenCall.data.environment,'production');
  assert.equal(JSON.stringify(f.values).includes('test-only'),false);
});
test('a failed model lookup stays at the token prompt without exporting the record',async()=>{
  const f=await fixture({token:false,handler:(method)=>{if(method==='token')throw new Error('No Opus 4.8 entry found.');}});
  await f.send({type:'START'});
  const result=await f.send({type:'TOKEN',token:'test-only',remember:false,environment:'production'});
  assert.equal(result.ok,false);
  assert.equal(f.values['flow-4'].phase,'token');
  assert.equal(f.clicks.length,0);
});
test('missing references ask for trainer setup and never click Print',async()=>{
  const f=await fixture({missing:['027-P043']});
  assert.equal((await f.send({type:'START'})).state.phase,'setup');assert.equal(f.clicks.length,0);
});
test('repeated clicks preserve the active capture rather than starting it twice',async()=>{
  const f=await fixture();await f.send({type:'START'});await f.send({type:'START'});
  assert.equal(f.calls.filter(c=>c.method==='capture_start').length,1);
  assert.equal(f.calls.filter(c=>c.method==='capture_cancel').length,0);
  await f.send({type:'CANCEL'});assert.equal(f.values['flow-4'].phase,'idle');
});
test('GCH page content cannot submit credential commands',async()=>{
  const f=await fixture();const response=await f.send({type:'TOKEN',token:'bad'}, {id:f.events.runtime.id,url:f.tab.url,tab:f.tab});
  assert.equal(response.ok,false);assert.equal(f.calls.length,0);
});
test('PDF viewer GET is downloaded automatically for the related GCH tab',async()=>{
  const f=await fixture();await f.send({type:'START'});
  f.events.webRequest.onHeadersReceived.fire({requestId:'r1',method:'GET',type:'main_frame',tabId:5,url:f.tab.url+'generated.pdf',responseHeaders:[{name:'Content-Type',value:'application/pdf'}]});
  await f.until(()=>f.calls.some(c=>c.method==='chrome_download'));
  assert.equal(f.calls.find(c=>c.method==='chrome_download').data.saveAs,false);
  assert.equal(f.calls.find(c=>c.method==='focus_gch').id,4);
  await f.send({type:'CANCEL'});
});
test('expired token returns to the inline credential prompt',async()=>{
  const f=await fixture({handler:async method=>method==='job'?{status:'failed',needs_token:true,remember_supported:true}:undefined});
  await f.send({type:'START'});f.download();await f.until(()=>f.values['flow-4']?.phase==='token');
  assert.match(f.values['flow-4'].message,/expired/);
});
test('cancel during export handoff cancels the returned review and leaves the panel idle',async()=>{
  let release;
  const complete=new Promise(resolve=>{release=resolve;});
  const f=await fixture({handler:async method=>method==='capture_complete'?await complete:undefined});
  await f.send({type:'START'});f.download();
  await f.until(()=>f.calls.some(c=>c.method==='capture_complete'));
  await f.send({type:'CANCEL'});release({id:'job-1'});
  await f.until(()=>f.calls.some(c=>c.method==='cancel_job'));
  assert.equal(f.values['flow-4'].phase,'idle');
  assert.equal(f.calls.filter(c=>c.method==='job').length,0);
});
const preview=(id=5,extra={})=>({id,url:'https://crm.medtronic.com/sap/bc/bsp/sap/bsp_wd_base/popup_test.htm',openerTabId:4,windowId:20,...extra});
function incomingDownload(chrome,id,name){
  chrome.downloads.onCreated.fire({id,url:'https://crm.medtronic.com/sap/'+name,filename:'C:\\Downloads\\'+name,mime:'text/plain',state:'complete',startTime:new Date().toISOString()});
}
test('retrying one attachment keeps earlier attachments and exports the report once',async()=>{
  const interrupted={id:21,url:'https://crm.medtronic.com/sap/patient.txt',filename:'C:\\Downloads\\patient.txt',mime:'text/plain',state:'interrupted',canResume:true,startTime:new Date().toISOString()};
  const f=await fixture({downloadSearch:()=>[interrupted],attachments:(spec,chrome)=>{
    if(spec.args[0]==='scan')return[{frameId:0,result:{found:true,rows:[{key:'rep',name:'rep.txt',downloadable:true},{key:'patient',name:'patient.txt',downloadable:true}],pageKey:'one'}}];
    if(spec.args[1]==='rep')incomingDownload(chrome,20,'rep.txt');
    else{interrupted.startTime=new Date().toISOString();chrome.downloads.onCreated.fire(interrupted);}
    return[{frameId:0,result:{clicked:true}}];
  }});
  const starting=f.send({type:'START'});
  await f.until(()=>f.alarms.has('download-retry'));
  assert.equal(f.calls.filter(c=>c.method==='capture_attachment').length,1);
  f.events.alarms.onAlarm.fire({name:'download-retry'});
  await f.until(()=>f.calls.some(c=>c.method==='resume_download'));
  interrupted.state='complete';f.events.downloads.onChanged.fire({id:21,state:{current:'complete'}});
  assert.equal((await starting).state.phase,'exporting');
  assert.equal(f.calls.filter(c=>c.method==='capture_attachment').length,2);
  assert.equal(f.calls.filter(c=>c.method==='capture_start').length,1);
  assert.deepEqual(f.clicks,['Print','Detailed Event Report']);
  await f.send({type:'CANCEL'});
});
test('persistent viewer download failure stops after three retries',async()=>{
  const f=await fixture({download:()=>{throw new Error('Network failed');}});await f.send({type:'START'});
  f.events.webRequest.onHeadersReceived.fire({method:'GET',type:'main_frame',tabId:5,url:f.tab.url+'generated.pdf',responseHeaders:[{name:'Content-Type',value:'application/pdf'}]});
  await f.until(()=>f.alarms.has('download-retry'));
  for(let attempt=1;attempt<=3;attempt++){
    f.events.alarms.onAlarm.fire({name:'download-retry'});
    await f.until(()=>f.calls.filter(c=>c.method==='chrome_download').length===attempt+1&&(attempt===3?f.values['flow-4']?.phase==='error':f.values.capture?.downloadRetry));
  }
  assert.equal(f.calls.filter(c=>c.method==='chrome_download').length,4);
  assert.match(f.values['flow-4'].message,/three automatic retries/);
  assert.equal(f.calls.filter(c=>c.method==='capture_complete').length,0);
});
test('all incoming files across attachment pages are added before the event export',async()=>{
  let page=1,sequence=20;
  const downloaded=[];
  const pages=[
    [{key:'rep',name:'rep.eml',excluded:false,downloadable:true},{key:'photo',name:'photo.png',excluded:true,downloadable:true}],
    [{key:'patient',name:'patient.txt',excluded:false,downloadable:true}]
  ];
  const f=await fixture({attachments:(spec,chrome)=>{
    const [command,key]=spec.args;
    if(command==='scan')return[{frameId:0,result:{found:true,rows:pages[page],pageKey:'page-'+page,first:page>0,next:page<1}}];
    if(command==='first')page=0;
    if(command==='next')page++;
    if(command==='download'){
      const row=pages[page].find(row=>row.key===key);downloaded.push(row.name);incomingDownload(chrome,++sequence,row.name);
    }
    return[{frameId:0,result:{clicked:true}}];
  }});
  assert.equal((await f.send({type:'START'})).state.phase,'exporting');
  assert.deepEqual(downloaded,['rep.eml','patient.txt']);
  assert.equal(f.calls.filter(c=>c.method==='capture_attachment').length,2);
  assert.deepEqual(f.clicks,['Print','Detailed Event Report']);
  f.download();await f.until(()=>f.values['flow-4']?.phase==='done');
  const complete=f.calls.find(c=>c.method==='capture_complete');
  assert.deepEqual(complete.data.attachment_limits,[]);
  assert.equal(f.calls.filter(c=>c.method==='capture_complete').length,1);
});
test('an attachment transfer failure is included in the review coverage',async()=>{
  const f=await fixture({handler:method=>{if(method==='capture_attachment')throw new Error('The attachment exceeds 20 MB.');},
    attachments:(spec,chrome)=>{
      if(spec.args[0]==='scan')return[{frameId:0,result:{found:true,rows:[{key:'rep',name:'rep.txt',excluded:false,downloadable:true}],pageKey:'one',next:false,first:false}}];
      incomingDownload(chrome,20,'rep.txt');return[{frameId:0,result:{clicked:true}}];
    }});
  await f.send({type:'START'});f.download();await f.until(()=>f.values['flow-4']?.phase==='done');
  assert.match(f.calls.find(c=>c.method==='capture_complete').data.attachment_limits[0],/rep.txt.*20 MB/);
});
test('HTML content-server attachment body is collected without a download',async()=>{
  const url='https://crm.medtronic.com/sap/bc/contentserver/010?docId=synthetic&secKey=not-a-real-key';
  const text='Original Text\nFrom: rep@example.test\nSynthetic incoming patient information.';
  const f=await fixture({summaryTabs:[4],htmlBody:spec=>{
    assert.equal(spec.target.tabId,5);assert.equal(spec.args[0],url);
    globalThis.location={href:url};
    globalThis.document={readyState:'complete',contentType:'text/html',body:{innerText:text}};
    try{
      assert.equal(spec.func(url+'wrong'),null);
      document.readyState='loading';assert.equal(spec.func(url),null);
      document.readyState='complete';document.body.innerText='x'.repeat(500001);
      assert.match(spec.func(url).error,/text limit/);
      document.body.innerText=text;
      return[{frameId:0,result:spec.func(url)}];
    }finally{delete globalThis.location;delete globalThis.document;}
  },attachments:(spec,chrome)=>{
    if(spec.args[0]==='scan')return[{frameId:0,result:{found:true,rows:[{key:'email',name:'rep.html',excluded:false,downloadable:true}],pageKey:'one'}}];
    chrome.webNavigation.onCreatedNavigationTarget.fire({tabId:5,sourceTabId:4,url});
    chrome.webNavigation.onBeforeNavigate.fire({tabId:5,frameId:0,url});
    chrome.webRequest.onHeadersReceived.fire({method:'GET',type:'main_frame',tabId:5,frameId:0,url,responseHeaders:[{name:'Content-Type',value:'text/html; charset=utf-8'}]});
    return[{frameId:0,result:{clicked:true}}];
  }});
  f.tabs.push({id:5,url,openerTabId:4});
  await f.send({type:'START'});
  const added=f.calls.find(c=>c.method==='capture_attachment_text');
  assert.equal(added.data.text,text);assert.equal(added.data.name,'rep.html');
  assert.equal(JSON.stringify(added).includes('secKey'),false);
  assert.equal(f.calls.some(c=>c.method==='chrome_download'),false);
  f.download();await f.until(()=>f.values['flow-4']?.phase==='done');
});
test('cancelling while HTML body is being read prevents attachment transfer',async()=>{
  let release,reading=false;
  const blocked=new Promise(resolve=>{release=resolve;});
  const url='https://crm.medtronic.com/sap/bc/contentserver/010?docId=synthetic';
  const f=await fixture({htmlBody:async()=>{reading=true;await blocked;return[{frameId:0,result:{text:'Synthetic email'}}];},
    attachments:(spec,chrome)=>{
      if(spec.args[0]==='scan')return[{frameId:0,result:{found:true,rows:[{key:'email',name:'rep.html',excluded:false,downloadable:true}],pageKey:'one'}}];
      chrome.webNavigation.onCreatedNavigationTarget.fire({tabId:5,sourceTabId:4,url});
      chrome.webNavigation.onBeforeNavigate.fire({tabId:5,frameId:0,url});
      chrome.webRequest.onHeadersReceived.fire({method:'GET',type:'main_frame',tabId:5,url,responseHeaders:[{name:'Content-Type',value:'text/html'}]});
      return[{frameId:0,result:{clicked:true}}];
    }});
  f.tabs.push({id:5,url,openerTabId:4});
  const starting=f.send({type:'START'});await f.until(()=>reading);
  await f.send({type:'CANCEL'});release();await starting;
  assert.equal(f.calls.some(c=>c.method==='capture_attachment_text'),false);
  assert.equal(f.clicks.includes('Print'),false);
});
test('unrelated HTML viewers are never scraped for an attachment',async()=>{
  const url='https://crm.medtronic.com/sap/bc/contentserver/010?docId=unrelated';
  const f=await fixture({htmlBody:()=>assert.fail('Unrelated page must not be read'),
    attachments:(spec,chrome)=>{
      if(spec.args[0]==='scan')return[{frameId:0,result:{found:true,rows:[{key:'rep',name:'rep.txt',excluded:false,downloadable:true}],pageKey:'one'}}];
      chrome.webNavigation.onBeforeNavigate.fire({tabId:9,frameId:0,url});
      chrome.webRequest.onHeadersReceived.fire({method:'GET',type:'main_frame',tabId:9,url,responseHeaders:[{name:'Content-Type',value:'text/html'}]});
      setTimeout(()=>incomingDownload(chrome,20,'rep.txt'),1100);
      return[{frameId:0,result:{clicked:true}}];
    }});
  f.tabs.push({id:9,url,openerTabId:99});
  await f.send({type:'START'});
  assert.equal(f.calls.some(c=>c.method==='capture_attachment_text'),false);
  await f.send({type:'CANCEL'});
});
test('unrecognized attachment pagination stops before generating a partial review',async()=>{
  const f=await fixture({attachments:()=>[{frameId:0,result:{found:true,rows:[],pageKey:'one',paginationUnknown:true}}]});
  assert.equal((await f.send({type:'START'})).state.phase,'error');
  assert.equal(f.clicks.includes('Print'),false);assert.equal(f.calls.some(c=>c.method==='capture_complete'),false);
});
test('cancelling attachment collection prevents the event export and review',async()=>{
  let release;
  const transfer=new Promise(resolve=>{release=resolve;});
  const f=await fixture({handler:async method=>method==='capture_attachment'?await transfer:undefined,
    attachments:(spec,chrome)=>{
      if(spec.args[0]==='scan')return[{frameId:0,result:{found:true,rows:[{key:'rep',name:'rep.txt',excluded:false,downloadable:true}],pageKey:'one',next:false,first:false}}];
      incomingDownload(chrome,20,'rep.txt');return[{frameId:0,result:{clicked:true}}];
    }});
  const starting=f.send({type:'START'});
  await f.until(()=>f.calls.some(c=>c.method==='capture_attachment'));
  await f.send({type:'CANCEL'});release({added:true});await starting;
  assert.equal(f.values['flow-4'].phase,'idle');assert.equal(f.clicks.includes('Print'),false);
  assert.equal(f.calls.some(c=>c.method==='capture_complete'),false);
});
test('PESR is used only when the Detailed Event Report is absent',async()=>{
  const f=await fixture({noDetailed:true});
  assert.equal((await f.send({type:'START'})).state.phase,'exporting');
  assert.deepEqual(f.clicks,['Print','Product Event Summary Report']);
  await f.send({type:'CANCEL'});
});
test('the report action is found in the separate Print Preview window',async()=>{
  const f=await fixture({summaryTabs:[5],onPrint:({tabs})=>tabs.push(preview())});
  assert.equal((await f.send({type:'START'})).state.phase,'exporting');
  assert.deepEqual(f.clickedTabs,[{label:'Print',tabId:4},{label:'Detailed Event Report',tabId:5}]);
  f.download();await f.until(()=>f.values['flow-4']?.phase==='done');
});
test('browser navigation target identifies a popup with no openerTabId',async()=>{
  const f=await fixture({summaryTabs:[5],onPrint:({tabs,events})=>{
    const popup=preview(5,{openerTabId:undefined});tabs.push(popup);
    events.webNavigation.onCreatedNavigationTarget.fire({tabId:5,sourceTabId:4,url:popup.url});
    events.webNavigation.onBeforeNavigate.fire({tabId:5,frameId:0,url:popup.url});
  }});
  assert.equal((await f.send({type:'START'})).state.phase,'exporting');
  assert.equal(f.clickedTabs.at(-1).tabId,5);
  await f.send({type:'CANCEL'});
});
test('an unrelated GCH tab and a stale popup are not searched for the action',async()=>{
  const scans=[];
  const f=await fixture({initialTabs:[preview(6),preview(9,{openerTabId:90})],summaryTabs:[5,6,9],
    onPrint:({tabs})=>tabs.push(preview()),onScript:spec=>scans.push(spec.target.tabId)});
  assert.equal((await f.send({type:'START'})).state.phase,'exporting');
  assert.equal(scans.includes(6),false);assert.equal(scans.includes(9),false);
  assert.equal(f.clickedTabs.at(-1).tabId,5);
  await f.send({type:'CANCEL'});
});
test('a named popup reused by SAP becomes eligible after fresh navigation',async()=>{
  const popup=preview();
  const f=await fixture({initialTabs:[popup],summaryTabs:[5],onPrint:({events})=>{
    events.webNavigation.onBeforeNavigate.fire({tabId:5,frameId:0,url:popup.url});
  }});
  assert.equal((await f.send({type:'START'})).state.phase,'exporting');
  assert.equal(f.clickedTabs.at(-1).tabId,5);
  await f.send({type:'CANCEL'});
});
test('a popup still navigating is retried before selecting the report',async()=>{
  let checks=0;
  const f=await fixture({summaryTabs:[5],onPrint:({tabs})=>tabs.push(preview()),frames:tabId=>{
    if(tabId===5&&checks++===0)throw new Error('Frame is navigating');
  }});
  assert.equal((await f.send({type:'START'})).state.phase,'exporting');
  assert.ok(checks>=2);assert.equal(f.clickedTabs.at(-1).tabId,5);
  await f.send({type:'CANCEL'});
});
test('matching reports in two related popups stop without selecting either',async()=>{
  const f=await fixture({summaryTabs:[5,6],onPrint:({tabs})=>tabs.push(preview(5),preview(6))});
  const result=await f.send({type:'START'});
  assert.equal(result.state.phase,'error');assert.match(result.state.message,/more than one/);
  assert.deepEqual(f.clicks,['Print']);
});
test('a PDF opened from the Print Preview popup is downloaded for the parent review',async()=>{
  const f=await fixture({summaryTabs:[5],onPrint:({tabs})=>tabs.push(preview())});
  await f.send({type:'START'});
  f.tabs.push({id:6,url:f.tab.url+'generated.pdf',openerTabId:5,active:true});
  f.events.webRequest.onHeadersReceived.fire({requestId:'r2',method:'GET',type:'main_frame',tabId:6,url:f.tab.url+'generated.pdf',responseHeaders:[{name:'Content-Type',value:'application/pdf'}]});
  await f.until(()=>f.calls.some(c=>c.method==='chrome_download'));
  assert.equal(f.calls.find(c=>c.method==='chrome_download').data.saveAs,false);
  assert.equal(f.calls.find(c=>c.method==='focus_gch').id,4);
  assert.equal(f.calls.find(c=>c.method==='focus_window').id,1);
  await f.send({type:'CANCEL'});
});
test('cancelling while the popup is inspected prevents the report click',async()=>{
  let release,inspected=false;
  const blocked=new Promise(resolve=>{release=resolve;});
  const f=await fixture({summaryTabs:[5],onPrint:({tabs})=>tabs.push(preview()),onScript:async spec=>{
    if(spec.target.tabId===5&&!spec.args[1]){inspected=true;await blocked;}
  }});
  const starting=f.send({type:'START'});
  await f.until(()=>inspected);await f.send({type:'CANCEL'});release();await starting;
  assert.deepEqual(f.clicks,['Print']);assert.equal(f.values['flow-4'].phase,'idle');
});
