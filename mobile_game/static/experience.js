"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const safeRead = key => {try{return localStorage.getItem(key);}catch(_){return null;}};
  const safeWrite = (key,value) => {try{value===null?localStorage.removeItem(key):localStorage.setItem(key,value);return true;}catch(_){return false;}};
  let packet=null, draftKey=null, typedChoice=null, searchPage=null, searchTerm="", journalVersion=0, submitting=false, scrollTimer=null;
  const text = (tag, value, className) => {const el=document.createElement(tag);el.textContent=value;if(className)el.className=className;return el;};
  const paragraph = (target, value) => target.append(text("p",value));
  function list(target, values) {const ul=document.createElement("ul");values.forEach(v=>ul.append(text("li",v)));target.append(ul);}
  function prefs() {
    document.documentElement.dataset.theme=safeRead("wt:theme")==="night"?"night":"day";
    document.documentElement.dataset.text=safeRead("wt:text")==="large"?"large":"normal";
    $("reading-theme").textContent=document.documentElement.dataset.theme==="night"?"Day reading":"Night reading";
    $("reading-size").textContent=document.documentElement.dataset.text==="large"?"Standard text":"Larger text";
    $("reading-theme").setAttribute("aria-pressed",String(document.documentElement.dataset.theme==="night"));
    $("reading-size").setAttribute("aria-pressed",String(document.documentElement.dataset.text==="large"));
  }
  $("reading-theme").addEventListener("click",()=>{safeWrite("wt:theme",document.documentElement.dataset.theme==="night"?"day":"night");prefs();});
  $("reading-size").addEventListener("click",()=>{safeWrite("wt:text",document.documentElement.dataset.text==="large"?"normal":"large");prefs();});
  prefs();
  function update(next) {
    const previous=packet?.id; packet=next;
    const context=window.whiteTowerPlay.context();
    const nextKey=`wt:draft:${context.playerId}:${packet.id}`;
    if(nextKey!==draftKey){draftKey=nextKey;$("intent-text").value=safeRead(draftKey)||"";typedChoice=null;$("intent-reply").hidden=true;
      const y=Number(safeRead(draftKey+":scroll")||0);
      if(Number.isFinite(y)&&y>0)requestAnimationFrame(()=>requestAnimationFrame(()=>window.scrollTo({top:y,behavior:"instant"})));
    }
    $("draft-status").textContent=$("intent-text").value?"Your unfinished message is kept on this device.":"Questions leave the story unchanged.";
    $("intent-section").hidden=!packet.capabilities?.typed_intents;
    $("intent-text").placeholder=packet.state.completed?"Ask about your progress, study, practise Spark, or enjoy a quiet interval…":"Look around, ask Lysa what happened, or describe an available approach…";
    const c=packet.companion;$("companion").hidden=!c;$("return-card").hidden=!c;
    if(c){
      $("return-location").textContent=`${c.location} · saved turn ${packet.revision}`;
      $("return-objective").textContent=packet.state.completed?"The optional task is complete. Further conversation and practice are yours to choose.":c.objective;
      $("return-recap").replaceChildren();c.recap.split("\n\n").forEach(p=>paragraph($("return-recap"),p));
      const sheet=$("character-sheet");sheet.replaceChildren();
      paragraph(sheet,`${packet.state.character.name} · ${c.sheet.rank} · level ${c.sheet.level}`);
      const grid=document.createElement("div");grid.className="sheet-grid";
      Object.entries(c.sheet.attributes).forEach(([name,value])=>{const cell=text("div",`${name} ${value}`);grid.append(cell);});sheet.append(grid);
      paragraph(sheet,`Capacity ${c.sheet.capacity} · Control ${c.sheet.control}${c.sheet.potential===null?" · Potential undisclosed":` · Potential ${c.sheet.potential}`}`);
      paragraph(sheet,Object.entries(c.sheet.flows).map(([k,v])=>`${k} ${v}`).join(" · "));
      list(sheet,Object.entries(c.sheet.skills).filter(([,v])=>v>0).map(([k,v])=>`${k}: ${v}`));
      const inventory=document.createElement("details");inventory.append(text("summary","Your belongings"));list(inventory,c.sheet.inventory);sheet.append(inventory);
      c.sheet.weaves.forEach(w=>{const card=document.createElement("article");card.className="weave-card";card.append(text("h3",w.name));paragraph(card,w.effect);paragraph(card,`Load ${w.load} · ${w.range_paces} paces · ${w.duration} · Control ${w.control}`);sheet.append(card);});
      const people=$("people-sheet");people.replaceChildren();c.people.forEach(p=>{people.append(text("h3",`${p.name} · ${p.role}`));paragraph(people,p.present?"Here in the gallery.":"Not currently in the gallery.");paragraph(people,p.known);list(people,p.memories.length?p.memories:["No shared events recorded yet."]);});
      const learning=$("learning-sheet");learning.replaceChildren();list(learning,c.evidence.length?c.evidence:["Your evidence will appear here as it is earned."]);list(learning,c.facts);
      Object.values(c.study).forEach(s=>paragraph(learning,`${s.minutes} minutes · ${s.kind} · ${s.status}`));
      if(c.last_cast)paragraph(learning,`Last practice: ${c.last_cast.weave_id} · ${c.last_cast.strain_paid} Strain · released after use · no roll.`);
      $("lore-sheet").replaceChildren();list($("lore-sheet"),c.lore_notes);
    }
    if(previous!==packet.id){journalVersion++;$("journal-results").replaceChildren();$("journal-results").hidden=true;$("events").hidden=false;$("journal-more").hidden=true;$("journal-search-status").textContent="";}
  }
  window.addEventListener("white-tower:state",event=>update(event.detail));
  window.addEventListener("scroll",()=>{clearTimeout(scrollTimer);scrollTimer=setTimeout(()=>{if(draftKey)safeWrite(draftKey+":scroll",String(window.scrollY));},200);},{passive:true});
  if(window.whiteTowerPlay.context().current)update(window.whiteTowerPlay.context().current);
  $("intent-text").addEventListener("input",()=>{
    if(draftKey)$("draft-status").textContent=safeWrite(draftKey,$("intent-text").value)?"Draft kept on this device. It will not send automatically.":"Draft could not be saved on this device.";
  });
  $("intent-form").addEventListener("submit",async event=>{
    event.preventDefault();if(submitting||window.whiteTowerPlay.context().blocked)return;
    const prompt=$("intent-text").value.trim();if(!prompt)return;
    if(!safeWrite(draftKey,prompt)){ $("draft-status").textContent="Enable saved site data before continuing.";return; }
    submitting=true;$("intent-submit").disabled=true;$("intent-submit").textContent="Reading your approach…";
    const began=performance.now();
    try{
      const result=await window.whiteTowerPlay.intent(prompt);
      $("intent-reply").hidden=false;$("intent-reply").textContent=result.message;
      if(result.choice){
        typedChoice={campaign:packet.id,id:result.choice.id,prompt};
        $("intent-reply").textContent=result.choice.requires_roll?"Review the stakes before taking this approach.":"Saving your chosen approach…";
        window.whiteTowerPlay.choose(result.choice);
      }else{$("draft-status").textContent=`Answered in ${((performance.now()-began)/1000).toFixed(1)}s · no game time passed.`;}
    }catch(error){$("intent-reply").hidden=false;$("intent-reply").textContent=error.message;$("draft-status").textContent="Your draft is kept. Try again when connected.";}finally{submitting=false;$("intent-submit").disabled=false;$("intent-submit").textContent="Continue →";}
  });
  window.addEventListener("white-tower:committed",event=>{
    const p=typedChoice,r=event.detail;
    if(p&&p.campaign===r.campaign_id&&p.id===r.request?.choice_id&&$("intent-text").value.trim()===p.prompt){safeWrite(draftKey,null);$("intent-text").value="";$("draft-status").textContent="Your action is saved. Questions leave the story unchanged.";$("intent-reply").hidden=true;typedChoice=null;}
    $("scene-heading").scrollIntoView({block:"start",behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth"});
  });
  async function search(more=false){
    if(!packet)return;const id=packet.id,version=++journalVersion;
    if(!more){searchPage=null;searchTerm=$("journal-query").value.trim();$("journal-results").replaceChildren();}
    $("journal-search-status").textContent="Searching saved moments…";
    try{
      const data=await window.whiteTowerPlay.journal(searchTerm,searchPage);
      if(version!==journalVersion||packet.id!==id)return;
      $("events").hidden=true;$("journal-results").hidden=false;
      data.entries.forEach(e=>{const article=document.createElement("article");article.className="journal-entry";article.append(text("p",`Turn ${e.revision}`,"journal-entry-label"));article.append(text("p",e.narration,"story-prose"));$("journal-results").append(article);});
      searchPage=data.next_before;$("journal-more").hidden=!searchPage;
      $("journal-search-status").textContent=data.entries.length?`${data.entries.length} saved entries loaded.`:"No matching entries. Try another word.";
    }catch(error){if(version===journalVersion&&packet.id===id)$("journal-search-status").textContent=error.message;}
  }
  $("journal-search").addEventListener("submit",e=>{e.preventDefault();search();});
  $("journal-more").addEventListener("click",()=>search(true));
})();
