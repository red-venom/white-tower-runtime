'use strict';
(() => {
  const el = id => document.getElementById(id);
  const authorization = Object.fromEntries(new URLSearchParams(location.search));
  let csrf;
  async function api(path, body) {
    const response = await fetch(path, {method:body===undefined?'GET':'POST',credentials:'same-origin',
      headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf||''},
      body:body===undefined?undefined:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || 'The connection could not be completed. Try again.');
    return data;
  }
  function signedIn(data) {
    csrf=data.csrf_token;
    el('connect-login').hidden=true;
    el('connect-status').textContent='Signed in to your White Tower account · '+data.player_id.slice(-8);
    el('connect-consent').hidden=!authorization.client_id;
    el('connect-manage').hidden=!!authorization.client_id;
  }
  async function check() {
    try {signedIn(await api('/api/session'));}
    catch {el('connect-status').textContent='Sign in before connecting ChatGPT.';el('connect-login').hidden=false;}
  }
  el('connect-login').addEventListener('submit',async event=>{
    event.preventDefault();const input=el('connect-code');const code=input.value;input.value='';
    try {signedIn(await api('/api/session/recover',{recovery_code:code}));}
    catch(error){el('connect-status').textContent=error.message;}
  });
  el('connect-check').addEventListener('click',check);
  async function consent(allow) {
    el('connect-allow').disabled=true;el('connect-deny').disabled=true;
    try {
      const result=await api('/api/oauth/authorize',{authorization,allow});
      const redirect=new URL(result.redirect);
      if(redirect.origin!=='https://chatgpt.com'||redirect.pathname!=='/connector_platform_oauth_redirect') throw new Error('Unexpected callback. Start again from ChatGPT.');
      location.assign(redirect.href);
    } catch(error){el('connect-status').textContent=error.message;el('connect-allow').disabled=false;el('connect-deny').disabled=false;}
  }
  el('connect-allow').addEventListener('click',()=>consent(true));
  el('connect-deny').addEventListener('click',()=>consent(false));
  el('connect-revoke').addEventListener('click',async()=>{
    try {await api('/api/oauth/disconnect',{});el('connect-status').textContent='ChatGPT disconnected. Your saved games are unchanged.';}
    catch(error){el('connect-status').textContent=error.message;}
  });
  check();
})();
