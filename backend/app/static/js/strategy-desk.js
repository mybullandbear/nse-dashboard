import { ApiClient } from './api.js';
import { AccessGate } from './components/access_gate.js';
const $=id=>document.getElementById(id);
let family='opening_range',sequence=0,dateChosen=false;
const money=value=>Number.isFinite(value)?new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(value):'—';
const label=value=>String(value).replaceAll('_',' ').toLowerCase().replace(/^./,c=>c.toUpperCase());
function node(tag,text,cls){const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;}
function details(row){
  $('detail-title').textContent=`${row.symbol} · signal evidence`;
  const box=$('detail-content');box.replaceChildren();
  box.append(node('p',`Lot quantity ${row.lot_size} · ${label(row.setup)} · ${row.bar_closed_at||'No completed bar'}`));
  const dl=node('dl');for(const [key,value] of Object.entries(row.evidence||{})){dl.append(node('dt',label(key)),node('dd',value==null?'Unavailable':String(value)));}box.append(dl);
  if(row.plan){box.append(node('h3','Hypothetical risk plan'));const plan=node('dl');for(const key of ['entry_reference','stop','target','one_lot_planned_loss_inr','risk_budget_inr'])plan.append(node('dt',label(key)),node('dd',money(row.plan[key])));box.append(plan);}
  box.append(node('h3','Execution blockers'));const list=node('ul');for(const reason of row.blockers)list.append(node('li',label(reason)));box.append(list);
  $('desk-detail').showModal();
}
function render(data){
  if(!dateChosen)$('desk-date').value=data.trade_date;
  $('desk-date').max=data.session.current_date_ist;
  $('risk-capital').textContent=money(data.risk.capital);$('risk-entry').textContent=money(data.risk.risk_per_trade_inr);$('risk-day').textContent=money(data.risk.daily_loss_limit_inr);$('risk-positions').textContent=`${data.risk.open_positions} / ${data.policy.max_positions}`;
  $('desk-state').textContent=data.historical_replay?'Historical replay · execution blocked':`${data.session.session_state} · paper preview only`;
  $('desk-clock').textContent=`${data.trade_date} · ${data.historical_replay?data.as_of.slice(11,16):data.session.current_time_ist} IST · ${label(data.session.calendar_status)}`;
  $('desk-engine').textContent=`${data.engine_version} · forward validation required`;
  const body=$('desk-rows');body.replaceChildren();
  for(const row of data.rows){
    const tr=node('tr'),index=node('td');index.append(node('strong',row.symbol),node('small',`${row.lot_size} units / lot`));
    const setup=node('td'),badge=node('span',label(row.setup),'desk-status');badge.dataset.tone=row.setup==='BULLISH_SETUP'?'bull':row.setup==='BEARISH_SETUP'?'bear':'';setup.append(badge,node('small',row.evidence.spot!=null?`Spot ${row.evidence.spot} · ATR ${row.evidence.atr}`:`${row.bars} completed bars`));
    const plan=node('td');plan.append(node('strong',row.plan?`${row.plan.quantity} units · ${row.plan.option_type}`:'Not executable'),node('small',row.plan?row.plan.quantity?`Stop ${row.plan.stop} · Target ${row.plan.target}`:`One lot ${money(row.plan.one_lot_planned_loss_inr)} risk · ${money(row.plan.risk_budget_inr)} budget`:'Fresh contract, spread and risk checks required'));
    const gate=node('td'),blocked=node('span','Blocked','desk-status');blocked.dataset.tone='bad';gate.append(blocked,node('small',row.blockers.slice(0,2).map(label).join(' · ')));
    const action=node('td'),button=node('button','Inspect');button.type='button';button.setAttribute('aria-label',`Inspect ${row.symbol} evidence`);button.addEventListener('click',()=>details(row));action.append(button);tr.append(index,setup,plan,gate,action);body.append(tr);
  }
  const rules=$('desk-entry-rules');rules.replaceChildren();
  const texts=family==='opening_range'?['Complete the 09:15–09:30 range and 30 contiguous closed five-minute warmup bars.','EMA trend, 25-minute momentum and recent OI flow agree.','Two closed five-minute breakout bars; reject an extension beyond 1.5 ATR.']:['At least 30 contiguous completed five-minute bars with a directional EMA trend.','Prior bar tests the fast EMA; the next closes beyond the prior high/low.','Require momentum and recent OI flow in the same direction.'];
  for(const text of texts)rules.append(node('li',text));
  $('desk-cutoffs').textContent=`Entry ${data.policy.entry_start}–${data.policy.entry_end} · force exit ${data.policy.force_exit} · normal close 15:40`;
}
async function load(){
  if(document.hidden||!AccessGate.isUnlocked())return;
  const current=++sequence;$('desk-refresh').disabled=true;
  try{
    const params=new URLSearchParams({family});if(dateChosen&&$('desk-date').value)params.set('trade_date',$('desk-date').value);
    if($('desk-at').value)params.set('at',$('desk-at').value);
    const data=await ApiClient.get('/api/strategy/workspace?'+params);
    if(current!==sequence)return;
    if(!data)throw Error('No authenticated strategy snapshot returned');
    render(data);document.querySelector('.desk-notice').dataset.error='false';
  }catch(e){$('desk-state').textContent='Evidence unavailable · entry blocked';document.querySelector('.desk-notice').dataset.error='true';$('desk-clock').textContent='Previous values may be stale';}
  finally{if(current===sequence)$('desk-refresh').disabled=false;}
}
document.querySelectorAll('[data-family]').forEach(button=>button.addEventListener('click',()=>{family=button.dataset.family;document.querySelectorAll('[data-family]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));load();}));
$('desk-date').addEventListener('change',()=>{dateChosen=Boolean($('desk-date').value);load();});
$('desk-at').addEventListener('change',load);
$('desk-current').addEventListener('click',()=>{dateChosen=false;$('desk-at').value='';load();});$('desk-refresh').addEventListener('click',load);$('desk-lock').addEventListener('click',()=>AccessGate.lockTerminal());$('detail-close').addEventListener('click',()=>$('desk-detail').close());
await AccessGate.ensureAuthorized();await load();
setInterval(()=>{if(!$('desk-detail').open&&!document.activeElement?.closest('#desk-rows'))load();},30000);
window.addEventListener('terminal:unlocked',load);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
