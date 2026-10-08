const $=id=>document.getElementById(id);
async function send(message){const response=await chrome.runtime.sendMessage(message);if(!response?.ok)throw new Error(response?.error||'Extension request failed.');return response;}
async function run(button,work){button.disabled=true;try{await work();}catch(e){$('status').textContent=e.message;}finally{button.disabled=false;}}
$('start').onclick=()=>run($('start'),async()=>{const r=await send({type:'START_CAPTURE'});$('status').textContent='Waiting for the report download for '+r.recordId+'.';});
$('cancel').onclick=()=>run($('cancel'),async()=>{await send({type:'CANCEL_CAPTURE'});$('status').textContent='Capture cancelled.';});
$('open').onclick=()=>run($('open'),()=>send({type:'OPEN_APP'}));
$('options').onclick=()=>send({type:'OPEN_OPTIONS'});
function read(file,kind){return new Promise((resolve,reject)=>{if(!file)return reject(new Error('Choose the Detailed Event Report or PESR.'));if(file.size>20*1024*1024)return reject(new Error('Files must be smaller than 20 MB.'));const reader=new FileReader();reader.onload=()=>resolve({kind,name:file.name,data:String(reader.result).split(',')[1]});reader.onerror=()=>reject(new Error('The file could not be read.'));reader.readAsDataURL(file);});}
$('manual').onclick=()=>run($('manual'),async()=>{const files=[await read($('pesr').files[0],'PRIMARY')];if($('mdr').files[0])files.push(await read($('mdr').files[0],'MDR'));await send({type:'MANUAL_REVIEW',recordId:$('record-id').value.trim(),files});$('status').textContent='Review started in the companion.';});
(async()=>{const context=await send({type:'GET_CONTEXT'});$('record-id').value=context.recordId;const status=await send({type:'GET_STATUS'});if(status.lastStatus)$('status').textContent=status.lastStatus.message;})().catch(e=>$('status').textContent=e.message);
