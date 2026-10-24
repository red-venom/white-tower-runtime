"use strict";
(() => {
 const $=id=>document.getElementById(id);
 const line=(parent,value)=>{const p=document.createElement('p');p.textContent=value;parent.append(p);};
 function show(packet){
  const world=packet.sandbox; $('sandbox-panel').hidden=!world;if(!world)return;
  $('sandbox-supervision').textContent=world.supervised_practice_available?'A supervisor is available for supported practice here.':'No supervised practice is available here now.';
  const objects=$('sandbox-objects');objects.replaceChildren();
  world.objects.forEach(o=>line(objects,`${o.name} · ${o.location==='inventory'?'carried':o.elevated?'on the high shelf':'here'}${o.lit?' · lit':''}`));
  line(objects,'Your belongings: '+world.character.inventory.join(', '));
  const sheet=$('sandbox-character');sheet.replaceChildren();
  line(sheet,`${world.character.name} · ${world.character.rank} · Capacity ${world.character.capacity} · Control ${world.character.control}`);
  line(sheet,Object.entries(world.character.attributes).map(([k,v])=>`${k} ${v}`).join(' · '));
  line(sheet,'Known forms: '+world.character.known_weaves.join(', '));
  const limits=$('sandbox-limits');limits.replaceChildren();world.limits.forEach(v=>line(limits,v));
 }
 window.addEventListener('white-tower:state',event=>show(event.detail));
 const current=window.whiteTowerPlay.context().current;if(current)show(current);
})();
