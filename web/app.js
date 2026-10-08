'use strict';
const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
const token = fragment.get('token') || sessionStorage.getItem('gch-session') || '';
if (token) sessionStorage.setItem('gch-session', token);
const initialJob = fragment.get('job');
history.replaceState(null, '', location.pathname);
const state = { status: null, job: null, evidence: null, timer: null, finished: null };
const labels = {done_properly:'Done properly', needs_trainer_review:'Trainer review', potential_gap:'Potential gap', not_assessable:'Not assessable', not_applicable:'Not applicable'};

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function notice(message, success=false) {
  $('notice').textContent=message;
  $('notice').className='notice'+(success?' success':'');
  $('notice').scrollIntoView({block:'nearest',behavior:'smooth'});
}
function clearNotice() { $('notice').classList.add('hidden'); }
function view(name) {
  document.querySelectorAll('.view').forEach(e=>e.classList.toggle('active',e.id==='view-'+name));
  document.querySelectorAll('.tab').forEach(e=>e.classList.toggle('active',e.dataset.view===name));
}
document.querySelectorAll('[data-view]').forEach(e=>e.addEventListener('click',()=>view(e.dataset.view)));
document.querySelectorAll('[data-go]').forEach(e=>e.addEventListener('click',()=>view(e.dataset.go)));

async function api(path, data, method) {
  const response = await fetch(path,{method:method||(data?'POST':'GET'),headers:{Authorization:'Bearer '+token,...(data?{'Content-Type':'application/json'}:{})},body:data?JSON.stringify(data):undefined});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'The request failed.');
  return result;
}
async function download(path, filename) {
  const response=await fetch(path,{headers:{Authorization:'Bearer '+token}});
  if(!response.ok){const data=await response.json();throw new Error(data.error||'Download failed.');}
  const url=URL.createObjectURL(await response.blob());
  const a=node('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),10000);
}
async function busy(button, label, work) {
  const previous=button.textContent;button.textContent=label;button.disabled=true;clearNotice();
  try{return await work();}catch(error){notice(error.message);}
  finally{button.textContent=previous;button.disabled=false;readiness();}
}
function fileData(file,kind) {
  return new Promise((resolve,reject)=>{
    if(!file){reject(new Error('Choose the required report.'));return;}
    if(file.size>20*1024*1024){reject(new Error(file.name+' exceeds 20 MB.'));return;}
    const reader=new FileReader();
    reader.onload=()=>resolve({name:file.name,data:String(reader.result).split(',')[1],...(kind?{kind}: {})});
    reader.onerror=()=>reject(new Error('Could not read '+file.name));
    reader.readAsDataURL(file);
  });
}
function readiness() {
  const info=state.status;
  const running=state.job&&['queued','running'].includes(state.job.status);
  const ready=info&&info.token_present&&info.procedure_count>0;
  $('check-button').disabled=!ready||running;
  if(!info)return;
  const core=info.procedures.filter(p=>!p.document_id.startsWith('D')).length;
  $('readiness').textContent=!info.token_present?'Add your MDT-GPT token in Connection.':!info.procedure_count?'Add approved documents in Procedures.':core+' of 6 core procedures loaded. Missing inputs will be marked not assessable.';
  $('connection-badge').textContent=info.connection_tested?'MDT-GPT connected':info.token_present?'Token entered · test connection':'Setup needed';
  $('connection-badge').className='pill '+(info.connection_tested?'ready':'warning');
  $('procedure-count').textContent=info.procedure_count;
  $('reference-summary').textContent=core+' of 6 core documents';
}
async function refreshStatus(populate=false) {
  state.status=await api('/api/status');
  const info=state.status;
  $('version').textContent='v'+info.version;
  $('endpoint').textContent=info.endpoint;$('data-directory').textContent=info.data_directory;
  if(populate){$('model-id').value=info.model;$('auth-style').value=info.auth_style;$('downloads-path').value=info.downloads;}
  if(!$('procedure-id').options.length)for(const p of info.expected_procedures){const o=node('option',p.id+' — '+p.name);o.value=p.id;$('procedure-id').append(o);}
  renderProcedures();readiness();
}
function renderProcedures() {
  const area=$('procedure-list');area.replaceChildren();
  for(const spec of state.status.expected_procedures){
    const current=state.status.procedures.find(p=>p.document_id===spec.id);
    const row=node('div',undefined,'procedure-row');const detail=node('div');
    detail.append(node('strong',spec.id),node('p',spec.name));
    if(current){
      detail.append(node('p',current.name+' · '+(current.origin==='bundled'?'Included default':'Uploaded revision')+' · '+current.chunks+' text sections','filename'));
      const remove=node('button','Remove active copy','text-button danger-text');
      remove.addEventListener('click',async()=>{
        if(!confirm('Remove '+spec.id+' from active references?'))return;
        await busy(remove,'Removing…',async()=>{await api('/api/procedures/'+current.id,null,'DELETE');await refreshStatus();});
      });detail.append(remove);
      if(current.warnings.length){const d=node('details'),s=node('summary','Extraction notes ('+current.warnings.length+')');d.append(s);for(const w of current.warnings)d.append(node('p',w));detail.append(d);}
    }
    row.append(detail,node('span',current?'Rev '+current.revision:'Not loaded','pill '+(current?'ready':'muted')));area.append(row);
  }
}
for(const kind of ['pesr','mdr']) {
  const input=$(kind+'-file'),zone=$(kind+'-zone');
  function label(){const f=input.files[0];$(kind+'-name').textContent=f?f.name:(kind==='pesr'?'PDF, DOCX or TXT · up to 20 MB':'Add for form and cross-record checks');}
  input.addEventListener('change',label);
  zone.addEventListener('dragover',e=>{e.preventDefault();zone.classList.add('dragging');});
  zone.addEventListener('dragleave',()=>zone.classList.remove('dragging'));
  zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('dragging');if(e.dataTransfer.files.length){const dt=new DataTransfer();dt.items.add(e.dataTransfer.files[0]);input.files=dt.files;label();}});
}
$('review-form').addEventListener('submit',async e=>{
  e.preventDefault();await busy($('check-button'),'Starting review…',async()=>{
    const files=[await fileData($('pesr-file').files[0],'PRIMARY')];
    if($('mdr-file').files[0])files.push(await fileData($('mdr-file').files[0],'MDR'));
    const job=await api('/api/reviews',{record_id:$('record-id').value.trim(),stage:$('stage').value,policy_selection:$('policy-basis').value,files});
    await follow(job);
  });
});
$('procedure-form').addEventListener('submit',async e=>{
  e.preventDefault();await busy($('upload-procedure'),'Reading document…',async()=>{
    await api('/api/procedures',{document_id:$('procedure-id').value,revision:$('revision').value.trim(),approved:$('approved').checked,file:await fileData($('procedure-file').files[0])});
    $('procedure-file').value='';$('revision').value='';$('approved').checked=false;
    await refreshStatus();notice('Procedure added. This revision will be used for new reviews.',true);
  });
});
$('connection-form').addEventListener('submit',async e=>{
  e.preventDefault();await busy($('save-connection'),'Saving…',async()=>{
    await api('/api/connection',{token:$('api-token').value,model:$('model-id').value.trim(),auth_style:$('auth-style').value,downloads:$('downloads-path').value.trim()});
    $('api-token').value='';await refreshStatus(true);$('connection-result').textContent='Saved. Use Test connection to verify model access.';notice('Connection settings saved.',true);
  });
});
$('test-connection').addEventListener('click',()=>busy($('test-connection'),'Testing…',async()=>{
  const result=await api('/api/connection/test',{});await refreshStatus();$('connection-result').textContent='Connected to '+state.status.model+'. '+(result.structured_mode==='validated_json'?'JSON will be validated locally.':'Structured output accepted.');notice('MDT-GPT connection verified.',true);
}));
$('clear-token').addEventListener('click',()=>busy($('clear-token'),'Clearing…',async()=>{await api('/api/connection/clear',{});await refreshStatus();$('connection-result').textContent='The API token has been cleared from memory.';}));
$('pairing-code').value=token;
$('copy-pairing').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(token);notice('Pairing code copied. Paste it in the extension’s options.',true);}catch{$('pairing-code').type='text';$('pairing-code').select();notice('Select and copy the displayed pairing code.');}});
$('get-extension').addEventListener('click',()=>busy($('get-extension'),'Preparing…',()=>download('/api/extension','GCH_Extension.zip')));
$('demo-button').addEventListener('click',()=>busy($('demo-button'),'Opening example…',async()=>{await follow(await api('/api/demo',{}));}));
$('cancel-button').addEventListener('click',async()=>{if(!state.job)return;try{await api('/api/jobs/'+state.job.id+'/cancel',{});$('cancel-button').disabled=true;$('progress-message').textContent='Cancelling after the current request returns';}catch(e){notice(e.message);}});
$('filter').addEventListener('change',renderFindings);
$('download-word').addEventListener('click',()=>busy($('download-word'),'Downloading…',()=>download('/api/jobs/'+state.job.id+'/word','GCH_Training_Review_'+state.job.record_id+'.docx')));
$('download-evidence').addEventListener('click',()=>busy($('download-evidence'),'Downloading…',()=>download('/api/jobs/'+state.job.id+'/evidence','GCH_Evidence_'+state.job.record_id+'.json')));

async function follow(job) {
  clearTimeout(state.timer);state.job=job;view('review');readiness();
  const active=['queued','running'].includes(job.status);
  $('empty-state').classList.add('hidden');$('progress-panel').classList.toggle('hidden',!active);
  $('result-panel').classList.toggle('hidden',job.status!=='ready');
  $('result-label').textContent=active?'Review in progress':job.status==='ready'?(job.demo?'Example review':'Review ready'):job.status;
  if(active){$('progress-message').textContent=job.message;$('progress-bar').value=job.progress;$('cancel-button').disabled=false;state.timer=setTimeout(poll,1500);}
  if(job.status==='ready'&&state.finished!==job.id){
    state.evidence=await api('/api/jobs/'+job.id+'/evidence');state.finished=job.id;renderResult();
  }
  if(job.status==='failed'||job.status==='cancelled'){$('empty-state').classList.remove('hidden');notice(job.error||'Review cancelled. You can start another check.');}
}
async function poll(){if(!state.job)return;try{await follow(await api('/api/jobs/'+state.job.id));}catch(e){notice(e.message);}}
function renderResult() {
  const result=state.job.result,review=result.review;
  $('result-record').textContent='RECORD '+result.record_id;
  $('overall-summary').textContent=review.overall_summary;
  $('demo-banner').classList.toggle('hidden',!result.demo);
  $('counts').replaceChildren();
  const counts=[['Done properly',review.findings.filter(f=>f.assessment==='done_properly').length],['Discuss with trainer',review.findings.filter(f=>['needs_trainer_review','potential_gap'].includes(f.assessment)).length],['Needs more evidence',review.findings.filter(f=>f.assessment==='not_assessable').length]];
  for(const [label,count]of counts){const item=node('div',undefined,'count');item.append(node('strong',count),node('span',label));$('counts').append(item);}
  const limits=[...new Set([...result.limitations,...review.limitations])];
  $('limit-count').textContent='('+limits.length+')';$('limitations-list').replaceChildren(...limits.map(t=>node('li',t)));
  $('filter').value='all';renderFindings();
}
function renderFindings() {
  if(!state.job?.result)return;
  const items=state.job.result.review.findings,filter=$('filter').value;
  const shown=items.filter(f=>filter==='all'||f.assessment===filter);
  $('findings-count').textContent=shown.length+' of '+items.length+' findings';$('findings').replaceChildren();
  for(const finding of shown){
    const card=node('article',undefined,'finding'),head=node('div',undefined,'finding-head');
    head.append(node('h4',(items.indexOf(finding)+1)+'. '+finding.record_element),node('span',labels[finding.assessment],'assessment '+finding.assessment));
    card.append(head,node('p',finding.what_was_done),node('p',finding.feedback,'feedback'));
    if(finding.study_action)card.append(node('div',finding.priority.toUpperCase()+' STUDY PRIORITY · '+finding.study_action,'study-action'));
    const refs=[...finding.record_evidence,...finding.procedure_references];
    if(refs.length){const detail=node('details');detail.append(node('summary','View cited evidence ('+refs.length+')'));
      for(const ref of refs){const source=state.evidence?.sources.find(s=>s.id===ref.source_id);const chunk=source?.chunks.find(c=>c.id===ref.chunk_id);const e=node('div',undefined,'evidence-item');e.append(node('strong',(source?.document_id||ref.source_id)+(source?.revision?' · Rev '+source.revision:'')+' · '+(chunk?.locator||ref.chunk_id)),node('blockquote',ref.quote));detail.append(e);}
      card.append(detail);
    }
    $('findings').append(card);
  }
  if(!shown.length)$('findings').append(node('p','No findings match this filter.','support'));
}

(async()=>{
  if(!token){notice('Start the companion using Start-Windows.cmd or start.sh. The launcher opens this workspace with its local session code.');return;}
  try{await refreshStatus(true);if(initialJob)await follow(await api('/api/jobs/'+initialJob));}
  catch(error){notice(error.message);}
})();
