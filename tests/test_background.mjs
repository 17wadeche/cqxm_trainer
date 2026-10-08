import test from 'node:test';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';

const wait=ms=>new Promise(r=>setTimeout(r,ms));
function event(){const listeners=[];return{addListener:fn=>listeners.push(fn),fire:(...args)=>listeners.map(fn=>fn(...args)),listeners};}
async function fixture(options={}){
  const values={},calls=[],clicks=[],clickedTabs=[],notices=[],portMessages=event(),disconnect=event();
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
    alarms:{create:async()=>{},clear:async()=>{},onAlarm:event()},
    webNavigation:{onCreatedNavigationTarget:event(),onBeforeNavigate:event(),getAllFrames:async({tabId})=>{
      if(options.frames){const result=await options.frames(tabId);if(result!==undefined)return result;}
      return[{frameId:0,url:tabs.find(t=>t.id===tabId)?.url||tab.url},{frameId:8,url:'chrome-extension://'+id+'/panel.html'}];
    }},
    scripting:{executeScript:async spec=>{
      assert.deepEqual(spec.target.frameIds,[0]);
      if(spec.func.name==='recordContext')return[{frameId:0,result:{recordIds:['708930960'],status:'Re-Open'}}];
      if(spec.args[1]){clicks.push(spec.args[0]);clickedTabs.push({label:spec.args[0],tabId:spec.target.tabId});}
      if(spec.args[0]==='Print'&&spec.args[1]&&options.onPrint)await options.onPrint({tabs,events:chrome});
      if(options.onScript)await options.onScript(spec);
      let count=spec.args[0]==='Detailed Event Report'&&options.summaryTabs&&!options.summaryTabs.includes(spec.target.tabId)?0:1;
      if(spec.args[0]==='Detailed Event Report'&&options.noDetailed)count=0;
      if(spec.args[0]==='Product Event Summary Report')count=options.noDetailed?1:0;
      return[{frameId:0,result:{count,score:0,clicked:count>0&&!!spec.args[1]}}];
    }},
    downloads:{onCreated:event(),onChanged:event(),search:async()=>[],download:async data=>{calls.push({method:'chrome_download',data});return 9;}},
    webRequest:{onHeadersReceived:event()}
  };
  await import(pathToFileURL(resolve('extension/background.js')).href+'?fixture='+Math.random());
  const sender={id,url:chrome.runtime.getURL('panel.html'),tab};
  const send=(message,from=sender)=>new Promise(resolve=>chrome.runtime.onMessage.listeners[0](message,from,resolve));
  const download=()=>chrome.downloads.onCreated.fire({id:1,url:tab.url+'report.pdf',filename:'C:\\Downloads\\report.pdf',mime:'application/pdf',state:'complete',startTime:new Date().toISOString()});
  const until=async predicate=>{for(let i=0;i<150;i++){if(predicate())return;await wait(10);}assert.fail('Expected workflow state did not arrive');};
  return{values,calls,clicks,clickedTabs,notices,send,download,until,tab,tabs,events:chrome};
}
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
