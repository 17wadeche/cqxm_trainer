import {recordContext, actionInFrame, attachmentsInFrame} from './gch-dom.mjs';
const HOST='com.gch.check_my_work', GCH='https://crm.medtronic.com/';
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let nativePort=null, sequence=0, startBusy=false, downloadQueue=Promise.resolve();
const pending=new Map(), polling=new Set();

function native(method,data={}) {
  if(!nativePort) {
    nativePort=chrome.runtime.connectNative(HOST);
    nativePort.onMessage.addListener(message=>{
      const request=pending.get(message.id);if(!request)return;
      pending.delete(message.id);clearTimeout(request.timer);
      if(message.ok)request.resolve(message.result);
      else request.reject(new Error(message.error||'The background check did not finish.'));
    });
    nativePort.onDisconnect.addListener(()=>{
      void chrome.runtime.lastError;nativePort=null;
      for(const request of pending.values()) {
        clearTimeout(request.timer);
        request.reject(new Error('The background helper is unavailable. Ask your trainer or IT team to finish the one-time installation, then try again.'));
      }
      pending.clear();
    });
  }
  return new Promise((resolve,reject)=>{
    const id=++sequence;
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('The connection is taking too long. Check your Medtronic network and try again.'));},method==='token'?300000:135000);
    pending.set(id,{resolve,reject,timer});
    try{nativePort.postMessage({id,method,data});}
    catch{pending.delete(id);clearTimeout(timer);reject(new Error('The background helper could not start. Ask your trainer for help.'));}
  });
}
const stateKey=tabId=>'flow-'+tabId;
async function state(tabId){return(await chrome.storage.session.get(stateKey(tabId)))[stateKey(tabId)]||{phase:'idle'};}
async function update(tabId,values){
  const next={...await state(tabId),...values};
  await chrome.storage.session.set({[stateKey(tabId)]:next});
  chrome.runtime.sendMessage({type:'GCH_STATE_CHANGED',tabId,state:next}).catch(()=>{});
  return next;
}
async function capture(){return(await chrome.storage.session.get('capture')).capture||null;}
async function finishCapture(){
  const active=await capture();
  if(active)await native('capture_cancel',{capture_id:active.captureId}).catch(()=>{});
  await chrome.storage.session.remove('capture');await chrome.alarms.clear('capture-expiry');
}
async function fail(tabId,error){
  const active=await capture();if(active?.tabId===tabId)await finishCapture();
  return update(tabId,{phase:'error',message:error.message||String(error)});
}
async function tabFor(sender){return sender.tab||(await chrome.tabs.query({active:true,currentWindow:true}))[0];}
async function permittedFrames(tabId){return((await chrome.webNavigation.getAllFrames({tabId}))||[]).filter(f=>f.url.startsWith(GCH)).map(f=>f.frameId);}
const navigationKey=tabId=>'gch-navigation-'+tabId;
const parentKey=tabId=>'gch-parent-'+tabId;
// Chrome exposes popups as tabs in another window. Retain browser-provided
// parent links, including when SAP does not set tabs.Tab.openerTabId.
chrome.webNavigation.onCreatedNavigationTarget.addListener(details=>{
  if(!details.url.startsWith(GCH)&&details.url!=='about:blank')return;
  chrome.storage.session.set({[parentKey(details.tabId)]:{parent:details.sourceTabId,at:Date.now()}}).catch(()=>{});
});
chrome.webNavigation.onBeforeNavigate.addListener(details=>{
  if(details.frameId!==0||!details.url.startsWith(GCH))return;
  chrome.storage.session.set({[navigationKey(details.tabId)]:{at:Date.now()}}).catch(()=>{});
});
chrome.tabs.onRemoved.addListener(tabId=>{
  chrome.storage.session.remove(navigationKey(tabId)).catch(()=>{});
  chrome.storage.session.remove(parentKey(tabId)).catch(()=>{});
});
async function navigationInfo(tabId){
  const [parent,nav]=await Promise.all([chrome.storage.session.get(parentKey(tabId)),chrome.storage.session.get(navigationKey(tabId))]);
  return{parent:parent[parentKey(tabId)]?.parent,at:Math.max(parent[parentKey(tabId)]?.at||0,nav[navigationKey(tabId)]?.at||0)};
}
async function reportTabs(active){
  const tabs=await chrome.tabs.query({url:GCH+'*'});
  const nodes=await Promise.all(tabs.map(async tab=>({tab,nav:await navigationInfo(tab.id)})));
  const related=new Set([active.tabId]);
  for(let depth=0;depth<5;depth++){
    let changed=false;
    for(const {tab,nav} of nodes){
      if(related.has(tab.id)||!tab.url?.startsWith(GCH))continue;
      const fresh=!(active.existingTabIds||[]).includes(tab.id)||nav.at>=active.started;
      const parent=Number.isInteger(tab.openerTabId)?tab.openerTabId:nav.parent;
      if(fresh&&related.has(parent)){related.add(tab.id);changed=true;}
    }
    if(!changed)break;
  }
  return [...related];
}
async function context(tab){
  if(!tab?.id||!tab.url?.startsWith(GCH))throw new Error('Open a product event in GCH first.');
  const frameIds=await permittedFrames(tab.id);
  if(!frameIds.length)throw new Error('GCH is still loading. Try again in a moment.');
  const frames=await chrome.scripting.executeScript({target:{tabId:tab.id,frameIds},func:recordContext});
  const ids=[...new Set(frames.flatMap(f=>f.result?.recordIds||[]))];
  if(ids.length!==1)throw new Error('Open one product event in GCH, then click Check my work again.');
  const statuses=[...new Set(frames.filter(f=>f.result?.recordIds?.includes(ids[0])).map(f=>f.result.status).filter(Boolean))];
  return{recordId:ids[0],stage:statuses.length===1?'Displayed saved GCH status: '+statuses[0]:'Stage unknown — assess only what the supplied record establishes'};
}
async function clickUnique(tabIds,label,captureId=null){
  if(!Array.isArray(tabIds))tabIds=[tabIds];
  const frames=(await Promise.all(tabIds.map(async tabId=>{
    try{
      const frameIds=await permittedFrames(tabId);if(!frameIds.length)return[];
      return(await chrome.scripting.executeScript({target:{tabId,frameIds},func:actionInFrame,args:[label,false]})).map(frame=>({...frame,tabId}));
    }catch{return[];} // A newly opened/closed or navigating popup can be retried.
  }))).flat();
  const found=frames.filter(f=>f.result?.count>0);if(!found.length)return false;
  const score=Math.min(...found.map(f=>f.result.score)),choices=found.filter(f=>f.result.score===score);
  if(choices.length!==1||choices[0].result.count!==1)throw new Error('GCH has more than one '+label+' action. Ask your trainer to check this screen.');
  if(captureId&&(await capture())?.captureId!==captureId)return false;
  const result=await chrome.scripting.executeScript({target:{tabId:choices[0].tabId,frameIds:[choices[0].frameId]},func:actionInFrame,args:[label,true]});
  if(!result[0]?.result?.clicked)throw new Error('The GCH screen changed. Wait for it to finish loading and try again.');
  return true;
}
async function attachmentTable(tabId){
  const frameIds=await permittedFrames(tabId);
  const frames=frameIds.length?await chrome.scripting.executeScript({target:{tabId,frameIds},func:attachmentsInFrame,args:['scan']}):[];
  const found=frames.filter(frame=>frame.result?.found);
  if(found.length>1)throw new Error('More than one attachment table is visible. Open one event and try again.');
  return found[0]||null;
}
async function attachmentCommand(active,frame,command,key=null){
  const current=await capture();if(current?.captureId!==active.captureId)return false;
  const ctx=await context(await chrome.tabs.get(active.tabId));
  if(ctx.recordId!==active.recordId)throw new Error('The selected event changed while collecting attachments. Start again on the correct event.');
  const result=await chrome.scripting.executeScript({target:{tabId:active.tabId,frameIds:[frame.frameId]},func:attachmentsInFrame,args:[command,key]});
  if(!result[0]?.result?.clicked)throw new Error(result[0]?.result?.error||'The attachment table changed. Try again.');
  return true;
}
async function collectAttachments(active){
  const limits=[],seen=new Set(),pages=new Set();
  let frame=await attachmentTable(active.tabId);
  if(!frame&&await clickUnique(active.tabId,'Attachments',active.captureId)){
    for(let i=0;i<20&&!frame;i++){await delay(250);frame=await attachmentTable(active.tabId);}
  }
  if(!frame)limits.push('Attachment section was unavailable; incoming files could not be collected.');
  if(frame?.result.first){
    const previous=frame.result.pageKey;
    if(!await attachmentCommand(active,frame,'first'))return false;
    let changed=false;
    for(let i=0;i<40;i++){await delay(250);frame=await attachmentTable(active.tabId);if(frame&&!frame.result.first){changed=true;break;}if(frame&&frame.result.pageKey!==previous){changed=true;break;}}
    if(!changed)throw new Error('The first attachment page did not load. Start again after GCH finishes loading.');
  }
  while(frame){
    const page=frame.result;
    if(page.error)throw new Error(page.error);
    if(page.coverageUnknown)limits.push('Attachment pagination was unavailable; only the visible attachment rows were collected.');
    if(pages.has(page.pageKey))throw new Error('Attachment pagination repeated a page. The complete list could not be collected.');
    pages.add(page.pageKey);
    for(const row of page.rows){
      if(row.excluded)continue;
      if(seen.has(row.key))throw new Error('Duplicate attachment rows cannot be identified uniquely. Ask your trainer to check the table.');
      if(seen.size>=100)throw new Error('This event exceeds 100 text attachments. Review the remaining files with your trainer.');
      seen.add(row.key);
      if(!row.downloadable){limits.push('Incoming attachment '+row.name.slice(0,180)+' has no unique download link.');continue;}
      const current=await capture();if(current?.captureId!==active.captureId)return false;
      await chrome.storage.session.set({capture:{...current,role:'attachment',downloadId:null,requestedDownload:false,processing:false,
        currentAttachment:{name:row.name.slice(0,240),started:Date.now(),done:false,error:null}}});
      await update(active.tabId,{message:'Reading incoming file '+seen.size+'…'});
      if(!await attachmentCommand(active,frame,'download',row.key))return false;
      let result=null;
      for(let i=0;i<120;i++){
        const latest=await capture();if(latest?.captureId!==active.captureId)return false;
        if(latest.currentAttachment?.done){result=latest.currentAttachment;break;}
        await delay(250);
      }
      if(!result)throw new Error('Incoming attachment '+row.name.slice(0,180)+' did not download. Use its Download button, then try Check my work again.');
      if(result.error)limits.push('Incoming attachment '+row.name.slice(0,180)+' could not be collected: '+result.error.slice(0,220));
    }
    if(page.paginationUnknown)throw new Error('The attachment page controls are unsupported. Ask your trainer to check for additional pages.');
    if(!page.next)break;
    if(!await attachmentCommand(active,frame,'next'))return false;
    let next=null;
    for(let i=0;i<40;i++){await delay(250);next=await attachmentTable(active.tabId);if(next&&next.result.pageKey!==page.pageKey)break;}
    if(!next||next.result.pageKey===page.pageKey)throw new Error('The next attachment page did not load. Wait for GCH and try again.');
    frame=next;
  }
  if(frame&&seen.size===0)limits.push('Attachment section contained no text files; incoming information could not be compared.');
  const current=await capture();if(current?.captureId!==active.captureId)return false;
  await chrome.storage.session.set({capture:{...current,role:'report',currentAttachment:null,downloadId:null,requestedDownload:false,processing:false,attachmentLimits:limits,reportStarted:Date.now()}});
  return true;
}
async function start(tab){
  if(startBusy)throw new Error('A check is starting. Please wait.');
  startBusy=true;
  try{
    const active=await capture(),previous=await state(tab.id);
    if(active?.tabId===tab.id||['reviewing','exporting'].includes(previous.phase))return previous;
    if(active)throw new Error('A check is already running in another GCH tab. Wait for it to finish.');
    const ctx=await context(tab);
    const runId=crypto.randomUUID();
    await update(tab.id,{phase:'preparing',runId,recordId:ctx.recordId,jobId:null,filename:null,message:'Getting ready…'});
    const setup=await native('status');
    if((await state(tab.id)).runId!==runId)return state(tab.id);
    if(setup.missing_procedures.length)return update(tab.id,{phase:'setup',message:setup.procedure_setup_errors?.[0]||'A training procedure is missing. Open Training setup to add it.'});
    if(!setup.token_present)return update(tab.id,{phase:'token',environment:'production',rememberSupported:setup.remember_supported,message:'Enter your MDT-GPT token to start. You only need to do this once if you choose Remember.'});
    const lease=await native('capture_start',{record_id:ctx.recordId,stage:ctx.stage});
    if((await state(tab.id)).runId!==runId){await native('capture_cancel',{capture_id:lease.capture_id});return state(tab.id);}
    const existingTabIds=(await chrome.tabs.query({url:GCH+'*'})).map(t=>t.id);
    const activeCapture={captureId:lease.capture_id,tabId:tab.id,recordId:ctx.recordId,existingTabIds,started:Date.now(),downloadId:null,processing:false,requestedDownload:false,role:'collecting',attachmentDownloadIds:[]};
    await chrome.storage.session.set({capture:activeCapture});
    await chrome.alarms.create('capture-expiry',{when:Date.now()+((lease.expires_in||900)-10)*1000});
    await update(tab.id,{phase:'exporting',message:'Getting the incoming information…',progress:3});
    if(!await collectAttachments(activeCapture))return state(tab.id);
    await update(tab.id,{phase:'exporting',message:'Getting your saved GCH report…',progress:5});
    const printed=await clickUnique(tab.id,'Print',lease.capture_id);
    if((await capture())?.captureId!==lease.capture_id)return state(tab.id);
    if(!printed)throw new Error('The Print button was not found on this GCH screen. Ask your trainer to check the page.');
    let selected=false;
    for(let i=0;i<80;i++){
      const current=await capture();if(current?.captureId!==lease.capture_id)return state(tab.id);
      const candidates=await reportTabs(current);
      if(await clickUnique(candidates,'Detailed Event Report',lease.capture_id)){selected=true;break;}
      // Allow the related SAP popup time to populate before using the older export.
      if(i>=12&&await clickUnique(candidates,'Product Event Summary Report',lease.capture_id)){
        selected=true;
        await update(tab.id,{message:'Using the available Product Event Summary Report…'});
        break;
      }
      await delay(250);
    }
    if(!selected)throw new Error('Neither Detailed Event Report nor Product Event Summary Report could be selected in GCH or its Print Preview popup. Check whether Chrome blocked the popup, then try again.');
    return state(tab.id);
  }catch(error){await fail(tab.id,error);return state(tab.id);}
  finally{startBusy=false;}
}
function fromGCH(item){return[item.url,item.finalUrl,item.referrer].some(value=>{try{return new URL(value).origin===new URL(GCH).origin;}catch{return false;}});}
async function consider(item){
  const active=await capture();
  if(!active||active.processing||!fromGCH(item)||!Number.isFinite(Date.parse(item.startTime))||Date.parse(item.startTime)<active.started-2000)return;
  if(active.attachmentDownloadIds?.includes(item.id))return;
  if(active.role==='collecting')return;
  if(active.role==='attachment'){
    const expected=active.currentAttachment;
    if(!expected||expected.done||Date.parse(item.startTime)<expected.started-1000)return;
    const filename=(item.filename||'').split(/[\\/]/).pop().replace(/ \(\d+\)(?=\.[^.]+$)/,'').toLowerCase();
    const name=expected.name.toLowerCase();
    if(/\.[a-z0-9]{2,5}$/i.test(name)&&filename!==name)return;
    if(active.downloadId!==null&&active.downloadId!==item.id)throw new Error('More than one incoming file downloaded for the selected attachment.');
    active.downloadId=item.id;await chrome.storage.session.set({capture:active});
    if(item.state!=='complete')return;
    active.processing=true;await chrome.storage.session.set({capture:active});
    let error=null;
    try{await native('capture_attachment',{capture_id:active.captureId,path:item.filename});}
    catch(exc){error=exc.message;}
    const latest=await capture();if(latest?.captureId!==active.captureId)return;
    latest.attachmentDownloadIds.push(item.id);latest.processing=false;
    latest.currentAttachment={...expected,done:true,error};
    await chrome.storage.session.set({capture:latest});return;
  }
  if(Date.parse(item.startTime)<(active.reportStarted||active.started)-1000)return;
  if(!(/\.(pdf|docx|txt)$/i.test(item.filename||'')||/pdf|wordprocessingml|text\/plain/i.test(item.mime||'')))return;
  if(active.downloadId!==null&&active.downloadId!==item.id){await fail(active.tabId,new Error('More than one report downloaded. Please finish other downloads and check this record again.'));return;}
  active.downloadId=item.id;await chrome.storage.session.set({capture:active});
  if(item.state!=='complete')return;
  active.processing=true;await chrome.storage.session.set({capture:active});
  try{
    const job=await native('capture_complete',{capture_id:active.captureId,path:item.filename,attachment_limits:active.attachmentLimits||[]});
    if((await capture())?.captureId!==active.captureId){await native('cancel_job',{id:job.id});return;}
    await chrome.storage.session.remove('capture');await chrome.alarms.clear('capture-expiry');
    await update(active.tabId,{phase:'reviewing',jobId:job.id,progress:10,message:'Comparing your record with incoming information and procedures…'});
    void follow(active.tabId,job.id);
  }catch(error){await fail(active.tabId,error);}
}
function enqueue(item){downloadQueue=downloadQueue.then(()=>consider(item)).catch(async error=>{const active=await capture();if(active)await fail(active.tabId,error);});}
chrome.downloads.onCreated.addListener(enqueue);
chrome.downloads.onChanged.addListener(change=>{
  if(change.state?.current==='complete')chrome.downloads.search({id:change.id}).then(items=>items[0]&&enqueue(items[0])).catch(()=>{});
  if(change.state?.current==='interrupted')capture().then(active=>{if(active?.downloadId===change.id)void fail(active.tabId,new Error('GCH’s report download was interrupted. Try again.'));});
});
// Automatically download a related PDF-viewer GET response using Chrome's session.
// Native print dialogs, blob viewers and POST-only exports are not guessed at.
chrome.webRequest.onHeadersReceived.addListener(details=>{
  const contentType=details.responseHeaders?.find(h=>h.name.toLowerCase()==='content-type')?.value||'';
  if(details.method!=='GET'||!['main_frame','sub_frame'].includes(details.type)||!/^(application\/(pdf|vnd\.|msword|rtf)|text\/(plain|csv|rtf)|message\/rfc822)/i.test(contentType))return;
  const requestCapture=capture();
  setTimeout(async()=>{
    const active=await capture();if(!active||!['report','attachment'].includes(active.role)||active.currentAttachment?.done||active.downloadId!==null||active.requestedDownload||active.processing)return;
    const original=await requestCapture;
    if(original?.captureId!==active.captureId||original.role!==active.role||original.currentAttachment?.started!==active.currentAttachment?.started)return;
    const tab=await chrome.tabs.get(details.tabId).catch(()=>null);
    const related=await reportTabs(active);
    const nav=await navigationInfo(details.tabId);
    const fresh=!(active.existingTabIds||[]).includes(details.tabId)||nav.at>=active.started;
    if(!related.includes(details.tabId)&&!(fresh&&(related.includes(tab?.openerTabId)||related.includes(nav.parent))))return;
    const latest=await capture();
    if(latest?.captureId!==active.captureId||latest.downloadId!==null||latest.requestedDownload||latest.processing)return;
    latest.requestedDownload=true;await chrome.storage.session.set({capture:latest});
    try{
      await chrome.downloads.download({url:details.url,saveAs:false,conflictAction:'uniquify'});
      if(details.tabId!==active.tabId&&tab?.active){
        try{
          await chrome.tabs.update(active.tabId,{active:true});
          const owner=await chrome.tabs.get(active.tabId);
          if(Number.isInteger(owner.windowId))await chrome.windows.update(owner.windowId,{focused:true});
        }catch{} // A focus failure must not cancel an already requested download.
      }
    }
    catch{await fail(active.tabId,new Error('GCH opened a viewer that could not download automatically. Use the viewer’s Download button, then try the check again.'));}
  },800);
},{urls:[GCH+'*']},['responseHeaders']);
async function follow(tabId,jobId){
  if(polling.has(jobId))return;polling.add(jobId);
  try{
    for(;;){
      if((await state(tabId)).jobId!==jobId)return;
      const job=await native('job',{id:jobId});
      if((await state(tabId)).jobId!==jobId)return;
      if(job.status==='ready'){await update(tabId,{phase:'done',progress:100,filename:job.filename,message:'Your Word report is ready in Downloads.',needsEvidence:job.needs_evidence});return;}
      if(job.status==='failed'&&job.needs_token){await update(tabId,{phase:'token',jobId:null,environment:'production',rememberSupported:job.remember_supported,message:'Your MDT-GPT token has expired or was rejected. Enter a new token to check this record again.'});return;}
      if(job.status==='failed')throw new Error(job.error||'The review did not finish. Try again.');
      if(job.status==='cancelled'){await update(tabId,{phase:'idle',jobId:null,message:'Check cancelled.'});return;}
      await update(tabId,{phase:'reviewing',progress:job.progress,message:job.message});await delay(1500);
    }
  }catch(error){await fail(tabId,error);}
  finally{polling.delete(jobId);}
}
chrome.alarms.onAlarm.addListener(alarm=>{
  if(alarm.name==='capture-expiry')capture().then(active=>{if(active)void fail(active.tabId,new Error('GCH did not download the report. If a print or save dialog is open, finish it and try again.'));});
});
chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
  if(!['START','GET_STATE','TOKEN','CANCEL','OPEN_REPORT','OPEN_SETUP','ADMIN'].includes(message?.type))return false;
  (async()=>{
    if(sender.id!==chrome.runtime.id||!sender.url?.startsWith(chrome.runtime.getURL('')))throw new Error('Open the Check my work control in GCH.');
    if(message.type==='OPEN_SETUP'){await chrome.runtime.openOptionsPage();return{};}
    if(message.type==='ADMIN'){
      if(sender.url!==chrome.runtime.getURL('options.html'))throw new Error('Open training setup to change these settings.');
      if(!['status','settings','procedure','clear_token'].includes(message.method))throw new Error('Unsupported setting.');
      return native(message.method,message.data||{});
    }
    const tab=await tabFor(sender);
    if(!tab?.id||!tab.url?.startsWith(GCH))throw new Error('Open a product event in GCH first.');
    if(message.type==='GET_STATE'){const current=await state(tab.id);if(current.phase==='reviewing')void follow(tab.id,current.jobId);return{tabId:tab.id,state:current};}
    if(message.type==='START')return{tabId:tab.id,state:await start(tab)};
    if(message.type==='TOKEN'){await native('token',{token:message.token,remember:message.remember,environment:'production'});return{tabId:tab.id,state:await start(tab)};}
    if(message.type==='CANCEL'){
      const current=await state(tab.id),active=await capture();
      if(active?.tabId===tab.id)await finishCapture();
      if(current.jobId)await native('cancel_job',{id:current.jobId});
      return{tabId:tab.id,state:await update(tab.id,{phase:'idle',runId:null,jobId:null,message:'Check cancelled.'})};
    }
    if(message.type==='OPEN_REPORT'){const current=await state(tab.id);return native('open_report',{id:current.jobId});}
  })().then(result=>sendResponse({ok:true,...result})).catch(error=>sendResponse({ok:false,error:error.message}));
  return true;
});
