const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class El{constructor(){this.listeners={};this.value='';this.hidden=false;this.open=false;}addEventListener(n,f){this.listeners[n]=f;}}
const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,new El());return elements.get(id);};
const values=new Map(),listeners={};let owner='one',current={id:'story'},saved={text:'',version:0},fail=false,delay=null,calls=0;
const context={document:{getElementById:el},localStorage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},window:{addEventListener:(n,f)=>listeners[n]=f,whiteTowerPlay:{context:()=>({playerId:owner,current}),notes:async(id,update)=>{calls++;if(delay)return delay;if(fail)throw Error('Offline');if(update){if(update.expected_version!==saved.version)throw Object.assign(Error('Conflict'),{status:409});saved={text:update.text,version:saved.version+1};}return {...saved};}}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../mobile_game/static/notes.js'),'utf8'),context);
const flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
 assert.equal(calls,0);el('personal-notes').open=true;el('personal-notes').listeners.toggle();await flush();
 assert.equal(el('notes-text').disabled,false);
 el('notes-text').value='My plan';el('notes-text').listeners.input();assert.equal(saved.text,'');
 fail=true;await el('notes-form').listeners.submit({preventDefault(){}});assert.match(el('notes-status').textContent,/Offline/);assert(values.has('wt:notes:one:story'));
 fail=false;saved={text:'Other device plan',version:1};await el('notes-reload').listeners.click();
 assert.equal(el('notes-text').value,'My plan');assert.equal(el('notes-server').textContent,'Other device plan');assert.equal(el('notes-save').disabled,true);
 el('notes-reviewed').listeners.click();assert.equal(saved.text,'Other device plan');
 await el('notes-form').listeners.submit({preventDefault(){}});assert.equal(saved.text,'My plan');assert.equal(saved.version,2);assert.equal(values.size,0);
 el('notes-text').value='Unsent';el('notes-text').listeners.input();
 let resolve;delay=new Promise(r=>resolve=r);el('notes-reload').listeners.click();
 owner='two';el('personal-notes').open=false;listeners['white-tower:state']();assert.equal(el('notes-text').value,'');
 resolve({text:'Private old owner copy',version:3});await flush();assert.equal(el('notes-text').value,'');
 owner='one';listeners['white-tower:state']();assert.equal(el('notes-text').value,'Unsent');
 console.log('Notes offline drafts, conflict review, explicit save and owner isolation passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
