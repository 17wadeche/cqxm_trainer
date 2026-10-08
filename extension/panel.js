const $=id=>document.getElementById(id);
let tabId=null,current={phase:'idle'},expanded=false,submitting=false;
const active=()=>['preparing','exporting','reviewing'].includes(current.phase);
function resize(){if(window.parent!==window)window.parent.postMessage({type:'GCH_PANEL_SIZE',width:expanded?370:210,height:Math.ceil($('panel').getBoundingClientRect().height+16)},'https://crm.medtronic.com');}
new ResizeObserver(resize).observe(document.body);
async function send(message){const response=await chrome.runtime.sendMessage(message);if(!response?.ok)throw new Error(response?.error||'The check did not start. Try again.');if(response.tabId)tabId=response.tabId;return response;}
function render(){
  const running=active();
  $('button-label').textContent=running?'Checking…':'Check my work';
  $('check').classList.toggle('working',running);
  $('card').hidden=!expanded;document.body.classList.toggle('expanded',expanded);
  $('message').textContent=current.message||'Save your GCH changes, then check your work.';
  $('heading').textContent=current.phase==='done'?'Your review is ready':current.phase==='token'?'Connect once':current.phase==='setup'?'One-time trainer setup':'Check my work';
  $('token-form').hidden=current.phase!=='token';
  $('remember-row').hidden=!current.rememberSupported;
  if(!current.rememberSupported)$('remember').checked=false;
  $('token-note').textContent=current.rememberSupported?'Your token is sent to MDT-GPT and stored with Windows account protection if you choose Remember.':'Your token is used only while this Chrome session is running.';
  $('progress').hidden=!running;$('progress').value=current.progress||5;
  $('done').hidden=current.phase!=='done';$('filename').textContent=current.filename||'';
  $('setup').hidden=current.phase!=='setup';$('retry').hidden=current.phase!=='error';
  $('cancel').hidden=!running;$('connect').disabled=submitting;
  resize();
}
async function run(work){$('error').hidden=true;try{const response=await work();if(response.state)current=response.state;}catch(error){expanded=true;$('error').textContent=error.message;$('error').hidden=false;}finally{render();}}
$('check').addEventListener('click',()=>{
  expanded=true;
  if(active()){render();return;}
  current={phase:'preparing',message:'Getting ready…'};render();
  run(()=>send({type:'START'}));
});
$('retry').addEventListener('click',()=>{current={phase:'preparing',message:'Trying again…'};render();run(()=>send({type:'START'}));});
$('close').addEventListener('click',()=>{expanded=false;render();});
$('token-form').addEventListener('submit',async event=>{
  event.preventDefault();if(submitting)return;submitting=true;$('connect').textContent='Connecting…';render();
  await run(()=>send({type:'TOKEN',token:$('token').value.trim(),remember:$('remember').checked}));
  $('token').value='';submitting=false;$('connect').textContent='Continue';render();
});
$('open').addEventListener('click',()=>run(()=>send({type:'OPEN_REPORT'})));
$('setup').addEventListener('click',()=>run(()=>send({type:'OPEN_SETUP'})));
$('documents').addEventListener('click',()=>run(()=>send({type:'OPEN_SETUP'})));
$('cancel').addEventListener('click',()=>run(()=>send({type:'CANCEL'})));
chrome.runtime.onMessage.addListener(message=>{
  if(message.type==='GCH_STATE_CHANGED'&&message.tabId===tabId){
    const oldPhase=current.phase;current=message.state;
    if(['done','token','setup','error'].includes(current.phase)&&oldPhase!==current.phase)expanded=true;
    render();
  }
});
(async()=>{try{const response=await send({type:'GET_STATE'});current=response.state;expanded=current.phase!=='idle';}catch(error){current={phase:'idle',message:error.message};}render();})();
