// Exercise the real app module's navigation and transport with a minimal DOM
// adapter. No browser, model, network, or real financial records are used.
import assert from 'node:assert/strict';

class Element {
  constructor(){this.hidden=false;this.disabled=false;this.value='';this.textContent='';this.innerHTML='';this.style={};this.dataset={};this.listeners={};this.children=[];this.attributes={};this.scrollHeight=25;this.classes=new Set();this.classList={toggle:(key,on)=>on?this.classes.add(key):this.classes.delete(key)};}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  fire(name,extra={}){return Promise.all((this.listeners[name]||[]).map(fn=>fn({preventDefault(){},currentTarget:this,target:this,...extra})));}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  querySelector(){return this.body??=new Element();}
  setAttribute(key,value){this.attributes[key]=value;}
  removeAttribute(key){delete this.attributes[key];}
  focus(){this.focused=true;}
  requestSubmit(){return this.fire('submit');}
}
const elements=new Map();
const element=selector=>{if(!elements.has(selector))elements.set(selector,new Element());return elements.get(selector);};
const modes=['home','dashboard','quantitative','recommendation'];
const navigation=modes.map(mode=>{const button=new Element();button.dataset.mode=mode;return button;});
globalThis.document={querySelector:element,querySelectorAll:selector=>selector==='.nav-item'||selector==='[data-mode]'?navigation:[],createElement:()=>new Element()};
globalThis.window={scrollTo(){}};
globalThis.location={pathname:'/'};
globalThis.history={replaceState(_state,_title,path){location.pathname=path;}};
globalThis.FormData=class{constructor(form){this.values=form.values;}[Symbol.iterator](){return Object.entries(this.values)[Symbol.iterator]();}};

const requests=[];
let nextAnswer='Verified test response';
let failRequest=false;
let pendingRequest=false;
globalThis.fetch=async(url,options)=>{
  if(url==='/api/ui-config')return {ok:true,json:async()=>({preview:true,dashboard_url:null})};
  const body=JSON.parse(options.body);requests.push(body);
  if(pendingRequest)return new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>{const error=new Error('Stopped');error.name='AbortError';reject(error);}));
  if(failRequest)return {ok:false,status:503,json:async()=>({detail:'Test data connection unavailable'})};
  return {ok:true,json:async()=>({output:[{type:'message',role:'assistant',content:[{type:'output_text',text:nextAnswer}]}]})};
};
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
await import('../agent_server/static/app.js');
await flush();

await navigation[1].fire('click');
assert.equal(location.pathname,'/dashboard');assert.equal(element('#dashboard-placeholder').hidden,false);assert.equal(requests.length,0);
console.log('PASS Dashboard navigation does not send an agent request');

await navigation[2].fire('click');await flush();
assert.equal(requests.length,1);assert.equal(requests[0].custom_inputs.ui_mode,'quantitative');assert.equal(element('#conversation').hidden,false);assert.equal(element('#send-button').disabled,false);
console.log('PASS Quantitative analysis calls /invocations and completes');

await navigation[3].fire('click');await flush();
assert.equal(requests.length,2);assert.equal(requests[1].input.length,3);assert.equal(requests[1].custom_inputs.ui_mode,'recommendation');assert.equal(element('#weights-panel').hidden,false);
console.log('PASS Recommendation calls the agent with conversation history');

element('#weights-form').values={disbursed:'1',risk:'2',environmental:'3',product:'4'};
await element('#weights-form').fire('submit');await flush();
assert.deepEqual(requests.at(-1).custom_inputs.weights,{disbursed:10,risk:20,environmental:30,product:40});assert.ok(requests.at(-1).input.at(-1).content.includes('full eligible population'));
console.log('PASS Apply & regenerate sends normalized custom weights and asks for full re-ranking');

const before=requests.length;element('#weights-form').values={disbursed:'0',risk:'0',environmental:'0',product:'0'};
await element('#weights-form').fire('submit');await flush();
assert.equal(requests.length,before);assert.equal(element('#weights-error').hidden,false);
console.log('PASS All-zero weights show an error without sending a request');

failRequest=true;element('#chat-input').value='A follow-up';await element('#chat-form').fire('submit');await flush();
assert.equal(element('#send-button').disabled,false);assert.equal(element('#request-status').hidden,true);
const last=element('#messages').children.at(-1);assert.equal(last.body.children[0].textContent,'Test data connection unavailable');
console.log('PASS Connection failures show an error and restore composer controls');

failRequest=false;pendingRequest=true;element('#chat-input').value='Long analysis';await element('#chat-form').fire('submit');await flush();
assert.equal(element('#send-button').disabled,true);const pendingCount=requests.length;await navigation[2].fire('click');await flush();assert.equal(requests.length,pendingCount);
await element('#cancel-request').fire('click');await flush();assert.equal(element('#send-button').disabled,false);
console.log('PASS Duplicate requests are prevented and Stop cancels an in-flight request');

pendingRequest=false;await element('#new-chat').fire('click');assert.equal(element('#messages').children.length,0);assert.equal(element('#welcome').hidden,false);
element('#chat-input').value='New analysis';await element('#chat-form').fire('submit');await flush();assert.equal(requests.at(-1).input.length,1);
console.log('PASS New conversation resets history and restores the welcome screen');
console.log('8 application interaction checks passed.');
