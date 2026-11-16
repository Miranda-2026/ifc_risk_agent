import assert from 'node:assert/strict';
import {normalizeWeights, parseAnswer, renderCard, renderMarkdown, safeUrl, money, responseText} from '../agent_server/static/cards.js';

const weights = {disbursed:25,risk:25,environmental:25,product:25};
const card = (id,status='continue') => ({
  client_id:id, client_name:`Test client ${id}`, recommendation_status:status,
  final_score:50, applied_weights:{...weights}, factor_scores:{disbursed:20,risk:40,environmental:60,product:80},
  quantitative_metrics:{active_disbursed_musd:1794.94,estimated_undisbursed_musd:null,weighted_internal_risk:1.62},
  project_performance:{active:21,performing:21,past_due:0,watchlist:0},
  quantitative_rationale:'Test evidence only. <img src=x onerror=alert(1)>',
  qualitative_notes:{}, news:[], data_quality_flags:[],
});
const full = () => ({cards:[card('A'),card('B'),card('C','review'),card('D','review')],limitations:[]});
let checks=0;
function check(label,fn){fn();checks++;console.log(`PASS ${label}`);}
check('normalizes custom weights',()=>assert.deepEqual(normalizeWeights({disbursed:1,risk:2,environmental:3,product:4}),{disbursed:10,risk:20,environmental:30,product:40}));
check('rejects zero, negative and nonfinite weights',()=>{
  for(const value of [0,-1,NaN,Infinity,'25',true])assert.throws(()=>normalizeWeights({disbursed:value,risk:0,environmental:0,product:0}));
});
check('accepts two continue and two distinct review clients',()=>assert.equal(parseAnswer(JSON.stringify(full()),weights).cards.length,4));
check('accepts fenced card JSON',()=>assert.equal(parseAnswer('```json\n'+JSON.stringify(full())+'\n```',weights).cards.length,4));
check('requires explanations for missing candidates',()=>{
  assert.throws(()=>parseAnswer(JSON.stringify({cards:[],limitations:[]})));
  assert.equal(parseAnswer(JSON.stringify({cards:[],limitations:['No data connection']})).cards.length,0);
});
check('rejects duplicate client IDs',()=>{const data=full();data.cards[1].client_id='A';assert.throws(()=>parseAnswer(JSON.stringify(data),weights));});
check('rejects wrong category counts and ordering',()=>{
  const data=full();data.cards[2].recommendation_status='continue';assert.throws(()=>parseAnswer(JSON.stringify(data),weights));
  const shuffled=full();[shuffled.cards[0],shuffled.cards[2]]=[shuffled.cards[2],shuffled.cards[0]];assert.throws(()=>parseAnswer(JSON.stringify(shuffled),weights));
});
check('rejects stale weights',()=>assert.throws(()=>parseAnswer(JSON.stringify(full()),{disbursed:10,risk:20,environmental:30,product:40})));
check('rejects a score that contradicts weighted contributions',()=>{const data=full();data.cards[0].final_score=99;assert.throws(()=>parseAnswer(JSON.stringify(data),weights));});
check('formats USD millions without unit conversion',()=>{assert.equal(money(1794.94),'$1,794.94M');assert.equal(money(null),'—');assert.equal(money(0),'$0.00M');});
check('renders independent expandable details and escapes model HTML',()=>{
  const html=renderCard(card('A'),0);
  assert.ok(html.includes('<details class="card-details">'));
  assert.ok(html.includes('More details'));
  assert.ok(html.includes('Quantitative score breakdown'));
  assert.ok(html.includes('1.62'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(!html.includes('<img'));
});
check('blocks executable source links',()=>{
  for(const url of ['javascript:alert(1)','data:text/html,test','http://example.com','https://user:pass@example.com'])assert.equal(safeUrl(url),null);
  assert.equal(safeUrl('https://example.com/article'),'https://example.com/article');
});
check('does not render raw HTML in conversational answers',()=>assert.ok(!renderMarkdown('<script>alert(1)</script>').includes('<script>')));
check('reads final text without displaying tool payloads',()=>assert.equal(responseText({output:[{type:'function_call_output',output:'secret raw tool payload'},{type:'message',role:'assistant',content:[{type:'output_text',text:'Final answer'}]}]}),'Final answer'));
console.log(`${checks} frontend checks passed.`);
