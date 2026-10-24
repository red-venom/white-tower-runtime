const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../mobile_game/static/experience.js'),'utf8');
class Element{constructor(){this.listeners={};this.children=[];this.value='';this.hidden=false;}append(...els){this.children.push(...els);}replaceChildren(...els){this.children=els;}addEventListener(n,f){this.listeners[n]=f;}setAttribute(){}scrollIntoView(){} }
function boot(values=new Map(),owner='owner-a'){
 const els=new Map(),get=id=>{if(!els.has(id))els.set(id,new Element());return els.get(id);};
 const listeners={},choices=[],requests=[];let current={id:'campaign-a',revision:0,state:{completed:false},capabilities:{typed_intents:true}};
 let reply={kind:'answer',message:'A read-only answer.'};
 const window={addEventListener:(n,f)=>listeners[n]=f,scrollTo(){},scrollY:0,matchMedia:()=>({matches:true}),whiteTowerPlay:{context:()=>({current,playerId:owner,blocked:false}),intent:async p=>{requests.push(p);return reply;},choose:c=>choices.push(c),journal:async()=>({entries:[],next_before:null})}};
 const ctx={window,document:{getElementById:get,createElement:()=>new Element(),documentElement:{dataset:{}}},localStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},performance:{now:()=>1},setTimeout,clearTimeout,requestAnimationFrame:f=>f()};
 vm.runInNewContext(script,ctx);
 return {get,values,requests,choices,listeners,setReply:r=>reply=r,context:ctx,change:(p,newOwner=owner)=>{current=p;owner=newOwner;listeners['white-tower:state']({detail:p});}};
}
(async()=>{
 const first=boot();first.get('intent-text').value='An unfinished thought';first.get('intent-text').listeners.input();
 const resumed=boot(first.values);assert.equal(resumed.get('intent-text').value,'An unfinished thought');assert.equal(resumed.requests.length,0);
 const other=boot(first.values,'owner-b');assert.equal(other.get('intent-text').value,'');
 resumed.get('intent-text').value='What can I do?';await resumed.get('intent-form').listeners.submit({preventDefault(){}});
 assert.equal(resumed.choices.length,0);assert.equal(resumed.get('intent-reply').textContent,'A read-only answer.');
 const choice={id:'look_gallery',choice_hash:'hash',requires_roll:false};resumed.setReply({kind:'proposal',message:'Look around.',choice});
 resumed.get('intent-text').value='Look around';await resumed.get('intent-form').listeners.submit({preventDefault(){}});
 assert.equal(resumed.choices.length,1);assert.equal(resumed.values.get('wt:draft:owner-a:campaign-a'),'Look around');
 resumed.listeners['white-tower:committed']({detail:{campaign_id:'campaign-a',request:{choice_id:'look_gallery'}}});
 assert.equal(resumed.get('intent-text').value,'');assert.equal(resumed.values.has('wt:draft:owner-a:campaign-a'),false);
 resumed.get('reading-theme').listeners.click();assert.equal(resumed.context.document.documentElement.dataset.theme,'night');
 const themed=boot(resumed.values);assert.equal(themed.context.document.documentElement.dataset.theme,'night');
 themed.setReply({kind:'answer',message:'<img src=x onerror=alert(1)>'});themed.get('intent-text').value='What?';await themed.get('intent-form').listeners.submit({preventDefault(){}});
 assert.equal(themed.get('intent-reply').textContent,'<img src=x onerror=alert(1)>');assert.equal(themed.get('intent-reply').children.length,0);
 console.log('Experience drafts, ownership, routine action, read-only answers and reading preferences passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
