import { FACTORS, FACTOR_NAMES, escapeHtml, normalizeWeights, responseText, parseAnswer, renderCard, renderMarkdown, number, safeUrl } from './cards.js';

const $ = selector => document.querySelector(selector);
const state = {history:[],mode:'home',weights:Object.fromEntries(FACTORS.map(k=>[k,25])),controller:null,requestId:0,sessionId:crypto.randomUUID(),config:{}};
const titles = {home:'Intelligence assistant',dashboard:'Dashboard',quantitative:'Quantitative analysis',recommendation:'Recommendation'};
const prompts = {
  quantitative:'Analyze the current active IFC portfolio using project_whole. Summarize funded exposure, project performance, weighted internal risk, environmental categories and product mix. Explain data-quality limitations and show the SQL evidence. Use actual Genie results only.',
  recommendation:'Generate the four client recommendation cards: two Continue Investing clients and two Reduce / Review clients. Apply the current four-factor weights, calculate separate rankings across all eligible clients, and include evidence, qualitative context and detailed explanations. Return the structured cards object.',
};

function showView(mode) {
  state.mode = mode;
  $('#welcome').hidden = mode !== 'home';
  $('#dashboard-view').hidden = mode !== 'dashboard';
  $('#conversation').hidden = !['quantitative','recommendation','chat'].includes(mode);
  $('#composer-wrap').hidden = mode === 'dashboard';
  $('#weights-panel').hidden = mode !== 'recommendation';
  $('#page-title').textContent = titles[mode] || titles.home;
  $('#conversation-title').textContent = mode === 'recommendation' ? 'Your next move, backed by evidence.' : mode === 'quantitative' ? 'Let’s look at the numbers.' : 'Let’s explore your portfolio.';
  $('#conversation-eyebrow').textContent = mode === 'recommendation' ? 'CLIENT RECOMMENDATIONS' : 'PORTFOLIO INTELLIGENCE';
  document.querySelectorAll('.nav-item').forEach(button => {const active=button.dataset.mode === (mode === 'chat' ? 'home' : mode);button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  if (mode === 'dashboard') {
    history.replaceState(null,'', '/dashboard');
    configureDashboard();
  } else if (location.pathname === '/dashboard') history.replaceState(null,'','/');
  window.scrollTo({top:0,behavior:'instant'});
}

function configureDashboard() {
  const url = safeUrl(state.config.dashboard_url);
  $('#dashboard-placeholder').hidden = !!url;
  $('#dashboard-frame').hidden = !url;
  $('#dashboard-external').hidden = !url;
  if (url) {if ($('#dashboard-frame').src !== url) $('#dashboard-frame').src=url;$('#dashboard-external').href=url;}
}

function appendUser(text) {
  const node=document.createElement('div');node.className='message message-user';
  const bubble=document.createElement('div');bubble.className='user-bubble';bubble.textContent=text;
  node.append(bubble);$('#messages').append(node);
}

function assistantNode() {
  const node=document.createElement('div');node.className='message message-assistant';
  node.innerHTML='<div class="assistant-label"><svg class="icon" aria-hidden="true"><use href="#icon-spark"/></svg> IFC INTELLIGENCE</div><div class="assistant-body"></div>';
  $('#messages').append(node);return node.querySelector('.assistant-body');
}

function appendAnswer(text, weights) {
  const body=assistantNode();let data;
  try {data=parseAnswer(text,weights);}
  catch(error){body.innerHTML=`<div class="limitations">The returned recommendation data could not be formatted: ${escapeHtml(error.message)}</div><details><summary>View the original agent response</summary><pre class="unformatted-answer">${escapeHtml(text)}</pre></details>`;return;}
  if (!data.cards) {body.innerHTML=renderMarkdown(text);return;}
  if(data.summary)body.innerHTML=renderMarkdown(data.summary);
  if(data.limitations?.length){const box=document.createElement('div');box.className='limitations';box.innerHTML=`<strong>Evidence & limitations</strong><ul>${data.limitations.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>`;body.append(box);}
  if(data.cards.length){
    const label=document.createElement('p');label.className='applied-weights';label.textContent=`Applied weights · ${FACTORS.map((k,i)=>`${FACTOR_NAMES[i]} ${number(weights[k],1)}%`).join(' · ')} · USD millions`;
    body.append(label);
    const cards=document.createElement('div');cards.className='recommendation-list';cards.innerHTML=data.cards.map(renderCard).join('');body.append(cards);
  }
}

function busy(value) {
  $('#request-status').hidden=!value;
  $('#send-button').disabled=value;
  $('#weights-form button').disabled=value;
  $('#request-status-text').textContent=state.mode==='recommendation'?'Analyzing eligible clients and preparing recommendations…':'Reviewing portfolio evidence…';
  $('#conversation').setAttribute('aria-busy',String(value));
}

async function sendMessage(text, displayText=text) {
  if(state.controller||!text.trim())return;
  if(state.mode==='home')showView('chat');
  const requestId=++state.requestId;
  const weights={...state.weights};
  const mode=state.mode;
  appendUser(displayText);
  const controller=new AbortController();state.controller=controller;
  let timedOut=false;
  const timer=setTimeout(()=>{timedOut=true;controller.abort();},300000);
  busy(true);
  const userMessage={role:'user',content:text};
  const messages=[...state.history,userMessage];
  // Keep a browser-tab conversation. Do not send greetings or demo answers as
  // fabricated portfolio evidence; the full successful exchange is replayed.
  try{
    const response=await fetch('/invocations',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({input:messages,stream:false,custom_inputs:{session_id:state.sessionId,ui_mode:mode,weights}})});
    if(!response.ok){let detail='';try{const error=await response.json();if(typeof error.detail==='string')detail=error.detail;}catch{}throw new Error(detail||`The agent could not complete this request (${response.status}). Please try again.`);}
    const result=await response.json();
    if(requestId!==state.requestId)return;
    const answer=responseText(result);
    if(!answer.trim())throw new Error('The agent returned no answer. Please try again.');
    state.history.push(userMessage,{role:'assistant',content:answer});
    appendAnswer(answer,weights);
  }catch(error){
    if(requestId!==state.requestId)return;
    const body=assistantNode();
    const message=error.name==='AbortError'?(timedOut?'This analysis exceeded the five-minute request limit. Try a narrower question.':'The request was stopped.'):error.message;
    const box=document.createElement('div');box.className='error-message';box.textContent=message;
    const retry=document.createElement('button');retry.type='button';retry.className='retry-button';retry.textContent='Try again';retry.addEventListener('click',()=>{if(!state.controller)sendMessage(text,displayText);});box.append(retry);body.append(box);
  }finally{clearTimeout(timer);if(requestId===state.requestId){state.controller=null;busy(false);}}
}

document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{
  if(state.controller)return;
  const mode=button.dataset.mode;showView(mode);
  if(prompts[mode])sendMessage(prompts[mode],mode==='recommendation'?'Recommend two clients to continue investing in and two clients for risk review.':'Give me a quantitative overview of the active portfolio.');
}));

function newConversation(){
  state.controller?.abort();state.requestId++;state.controller=null;state.history=[];state.sessionId=crypto.randomUUID();$('#messages').replaceChildren();$('#chat-input').value='';$('#chat-input').style.height='auto';busy(false);showView('home');$('#chat-input').focus();
}
$('#new-chat').addEventListener('click',newConversation);
$('#mobile-new-chat').addEventListener('click',newConversation);
$('#cancel-request').addEventListener('click',()=>state.controller?.abort());
$('#chat-form').addEventListener('submit',event=>{
  event.preventDefault();const input=$('#chat-input'),text=input.value.trim();if(!text||state.controller)return;
  input.value='';input.style.height='auto';sendMessage(text);
});
$('#chat-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('#chat-form').requestSubmit();}});
$('#chat-input').addEventListener('input',event=>{event.target.style.height='auto';event.target.style.height=`${Math.min(event.target.scrollHeight,130)}px`;});
$('#weights-form').addEventListener('submit',event=>{
  event.preventDefault();if(state.controller)return;
  try{
    const values=Object.fromEntries(new FormData(event.currentTarget));
    state.weights=normalizeWeights(Object.fromEntries(FACTORS.map(k=>[k,values[k].trim()===''?NaN:Number(values[k])])));
    $('#weights-error').hidden=true;
    $('#weights-summary').textContent=FACTORS.map(k=>`${number(state.weights[k],1)}%`).join(' · ');
    sendMessage(`${prompts.recommendation}\nRecalculate the full eligible population with the latest weights. Preserve the same underlying factor definitions and data snapshot where available. Clearly explain verified changes versus the previous run.`,`Regenerate recommendations with ${FACTORS.map((k,i)=>`${FACTOR_NAMES[i]} ${number(state.weights[k],1)}%`).join(', ')}.`);
  }catch(error){$('#weights-error').textContent=error.message;$('#weights-error').hidden=false;}
});

async function loadConfig(){
  try{const response=await fetch('/api/ui-config');if(!response.ok)throw new Error();state.config=await response.json();$('#preview-notice').hidden=!state.config.preview;}
  catch{state.config={};}
  if(location.pathname==='/dashboard')showView('dashboard');
}
loadConfig();
