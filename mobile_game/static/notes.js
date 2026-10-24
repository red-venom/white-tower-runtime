"use strict";
(() => {
  const $=id=>document.getElementById(id);
  let key=null,id=null,version=null,epoch=0,dirty=false,busy=false,server=null;
  const status=s=>{$("notes-status").textContent=s;};
  function keep(){try{localStorage.setItem(key,JSON.stringify({text:$("notes-text").value,version}));return true;}catch(_){status("Draft could not be kept on this device. Keep a copy before leaving.");return false;}}
  function controls(){ $("notes-text").disabled=busy||version===null;$("notes-save").disabled=busy||version===null||!!server;$("notes-reload").disabled=busy; }
  function clearDraft(){try{localStorage.removeItem(key);}catch(_){}dirty=false;}
  function bind(){
    const c=window.whiteTowerPlay.context();if(!c.current)return;
    const next=`wt:notes:${c.playerId}:${c.current.id}`;if(key===next)return;
    epoch++;key=next;id=c.current.id;version=null;dirty=false;busy=false;server=null;
    $("notes-text").value="";$("notes-conflict").hidden=true;
    try{const draft=JSON.parse(localStorage.getItem(key)||"null");if(draft&&typeof draft.text==="string"&&Number.isSafeInteger(draft.version)&&draft.version>=0){$("notes-text").value=draft.text;version=draft.version;dirty=true;}}catch(_){}
    controls();status(dirty?"Unfinished notes restored on this device.":"Open the notebook to load your saved notes.");
    if($("personal-notes").open)load();
  }
  async function load(){
    if(!id||busy)return;const ticket=epoch;busy=true;controls();status("Checking saved notes…");
    try{
      const saved=await window.whiteTowerPlay.notes(id);if(ticket!==epoch)return;
      if(dirty&&saved.text!==$("notes-text").value&&saved.version!==version){
        server=saved;$("notes-server").textContent=saved.text||"(Empty notebook)";$("notes-conflict").hidden=false;status("Another saved copy exists. Your draft is preserved below; review both before saving.");
      }else{
        if(!dirty||saved.text===$("notes-text").value){$("notes-text").value=saved.text;clearDraft();}
        version=saved.version;server=null;$("notes-conflict").hidden=true;status(dirty?"Your draft is kept on this device. Save when ready.":"Notes loaded from your online save.");
      }
    }catch(e){if(ticket===epoch)status(e.message+" Your local draft has been kept.");}
    finally{if(ticket===epoch){busy=false;controls();}}
  }
  $("personal-notes").addEventListener("toggle",()=>{if($("personal-notes").open)load();});
  $("notes-reload").addEventListener("click",load);
  $("notes-text").addEventListener("input",()=>{dirty=true;if(keep())status("Draft kept on this device. Save online to use it on another phone or browser.");});
  $("notes-reviewed").addEventListener("click",()=>{if(!server)return;version=server.version;server=null;$("notes-conflict").hidden=true;keep();controls();status("Continue editing your draft, then save. No changes have been sent yet.");});
  $("notes-form").addEventListener("submit",async e=>{
    e.preventDefault();if(busy||version===null||server)return;
    if(!keep())return;const ticket=epoch;const update={expected_version:version,text:$("notes-text").value};busy=true;controls();status("Saving notes…");let conflict=false;
    try{const saved=await window.whiteTowerPlay.notes(id,update);if(ticket!==epoch)return;version=saved.version;clearDraft();status("Notes saved online. No game time passed.");}
    catch(error){if(ticket===epoch){status(error.message+" Your draft is kept. Check the saved copy or retry.");conflict=error.status===409;}}
    finally{if(ticket===epoch){busy=false;controls();if(conflict)load();}}
  });
  window.addEventListener("white-tower:state",bind);bind();
})();
