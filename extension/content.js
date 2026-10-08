// An extension-origin iframe isolates the token prompt from GCH page scripts.
(() => {
  if (window !== window.top || document.getElementById('gch-check-my-work-launcher')) return;
  if (/\/bsp_wd_base\/popup/i.test(window.location.pathname)) return;
  const host = document.createElement('div');
  host.id = 'gch-check-my-work-launcher';
  Object.assign(host.style, {position:'fixed',top:'12px',right:'18px',zIndex:'2147483647',width:'210px',height:'64px'});
  const shadow = host.attachShadow({mode:'closed'});
  const frame = document.createElement('iframe');
  const source = chrome.runtime.getURL('panel.html');
  frame.src = source;frame.title = 'Check my work';
  frame.style.cssText = 'border:0;width:100%;height:100%;color-scheme:light;display:block;';
  shadow.append(frame);document.documentElement.append(host);
  window.addEventListener('message', event => {
    if (event.source !== frame.contentWindow || event.origin !== new URL(source).origin || event.data?.type !== 'GCH_PANEL_SIZE') return;
    const width = Math.min(370,Math.max(210,Number(event.data.width)||210));
    const height = Math.min(window.innerHeight-24,Math.max(64,Number(event.data.height)||64));
    host.style.width = width+'px';host.style.maxWidth = 'calc(100vw - 24px)';host.style.height = height+'px';
  });
})();
