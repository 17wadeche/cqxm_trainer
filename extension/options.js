const $=id=>document.getElementById(id);
async function call(method,data={}){const result=await chrome.runtime.sendMessage({type:'ADMIN',method,data});if(!result.ok)throw new Error(result.error);return result;}
function topicChoices(topics,selected=[]){
  const choices=document.createElement('fieldset'),legend=document.createElement('legend');
  legend.textContent='Enable AI review for these topics';choices.append(legend);
  for(const topic of topics){
    const label=document.createElement('label'),input=document.createElement('input');
    input.type='checkbox';input.value=topic.id;input.checked=selected.includes(topic.id);
    label.append(input,document.createTextNode(' '+topic.name));choices.append(label);
  }
  return choices;
}
function selectedTopics(container){return [...container.querySelectorAll('input[type="checkbox"]:checked')].map(input=>input.value);}
function paint(info){
  $('build').textContent='Background helper version: '+(info.version||'older build');$('model').value=info.model;$('auth').value=info.auth_style;$('downloads').value=info.downloads;
  $('procedure').replaceChildren();$('references').replaceChildren();
  for(const p of info.expected_procedures){
    const option=document.createElement('option');option.value=p.id;option.textContent=p.id+' — '+p.name;$('procedure').append(option);
    const loaded=info.procedures.find(s=>s.document_id===p.id),row=document.createElement('p');
    row.textContent=p.id+' — '+p.name+': '+(loaded?'Revision '+loaded.revision+' · '+(loaded.origin==='bundled'?'Included default':'Uploaded revision'):'Not loaded');$('references').append(row);
    for(const note of loaded?.warnings||[]){const n=document.createElement('p');n.className='support';n.textContent=note;$('references').append(n);}
  }
  $('local-references').replaceChildren();
  $('local-topics').replaceChildren(topicChoices(info.local_review_topics||[]));
  for(const p of info.procedures.filter(p=>p.document_id.startsWith('LOCAL-'))){
    const row=document.createElement('p'),remove=document.createElement('button');
    row.textContent=p.document_id.slice(6)+' · Revision '+p.revision+' · '+p.name+' ';
    remove.type='button';remove.textContent='Remove';remove.addEventListener('click',()=>run(remove,async()=>paint(await call('remove_local_procedure',{source_id:p.id}))));
    row.append(remove);$('local-references').append(row);
    const choices=topicChoices(info.local_review_topics||[],p.review_check_ids||[]),save=document.createElement('button');
    save.type='button';save.textContent='Save review topics';
    save.addEventListener('click',()=>run(save,async()=>{paint(await call('local_review_scope',{source_id:p.id,review_check_ids:selectedTopics(choices)}));$('status').textContent='Review topics saved. Run Check my work again to use them.';}));
    $('local-references').append(choices,save);
    for(const note of p.warnings||[]){const n=document.createElement('p');n.className='support';n.textContent=note;$('local-references').append(n);}
  }
  $('status').textContent=info.missing_procedures.length?(info.procedure_setup_errors?.[0]||info.missing_procedures.length+' procedures still needed.'):'All default training procedures are ready. Use Check my work in GCH.';
}
async function run(button,work){button.disabled=true;try{await work();}catch(e){$('status').textContent=e.message;}finally{button.disabled=false;}}
function read(file){return new Promise((resolve,reject)=>{if(!file||file.size>20*1024*1024)return reject(new Error('Choose a file smaller than 20 MB.'));const reader=new FileReader();reader.onload=()=>resolve({name:file.name,data:String(reader.result).split(',')[1]});reader.onerror=()=>reject(new Error('Could not read the file.'));reader.readAsDataURL(file);});}
$('procedure-form').addEventListener('submit',e=>{e.preventDefault();run($('add'),async()=>{const docid=$('procedure').value,revision=$('revision').value;paint(await call('procedure',{document_id:docid,revision,approved:$('approved').checked,file:await read($('file').files[0])}));$('status').textContent=docid+' revision '+revision+' saved. Future checks will use this revision.';$('file').value='';$('revision').value='';$('approved').checked=false;});});
$('settings-form').addEventListener('submit',e=>{e.preventDefault();run($('save'),async()=>{paint(await call('settings',{model:$('model').value,auth_style:$('auth').value,downloads:$('downloads').value}));$('status').textContent='Settings saved.';});});
$('clear').addEventListener('click',()=>run($('clear'),async()=>{await call('clear_token');$('status').textContent='API token forgotten. GCH will ask for it on the next check.';}));
call('status').then(paint).catch(e=>$('status').textContent=e.message);
$('local-form').addEventListener('submit',e=>{e.preventDefault();run($('local-add'),async()=>{paint(await call('local_procedure',{document_id:$('local-id').value,revision:$('local-revision').value,approved:$('local-approved').checked,review_check_ids:selectedTopics($('local-topics')),file:await read($('local-file').files[0])}));$('local-form').reset();$('status').textContent='Local instruction saved for future reviews.';});});
