import {ApiClient} from '../api.js';
import {AccessGate} from './access_gate.js';
import {store} from '../state.js';
const NAMES={hull:'Hull',alphatrend:'Alpha',shonya:'Shonya',ott:'OTT'};
const NS='http://www.w3.org/2000/svg';
const num=v=>Number.isFinite(v)?v.toLocaleString('en-IN',{maximumFractionDigits:2}):'—';
const oi=v=>Number.isFinite(v)?Math.abs(v)>=1e7?(v/1e7).toFixed(2)+'Cr':Math.abs(v)>=1e5?(v/1e5).toFixed(2)+'L':num(v):'—';
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
let mounted=null,timer=null,watchdog=null,sequence=0,data=null,selected='NIFTY',received=0,failed=false;
export function destroyDecisionBoard(){sequence++;clearTimeout(timer);clearInterval(watchdog);mounted=null;data=null;}
export function sparkline(values,times,label,tone='neutral'){
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 116 22');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('role','img');svg.setAttribute('aria-label',label);svg.classList.add('db-spark',`db-${tone}`);
  const valid=values.filter(Number.isFinite);if(valid.length<2){const t=document.createElementNS(NS,'text');t.setAttribute('x','2');t.setAttribute('y','15');t.textContent='No trend yet';svg.append(t);return svg;}
  const lo=Math.min(...valid),span=Math.max(...valid)-lo;let run=[];
  const flush=()=>{if(run.length>1){const p=document.createElementNS(NS,'polyline');p.setAttribute('points',run.join(' '));p.setAttribute('fill','none');p.setAttribute('stroke','currentColor');p.setAttribute('stroke-width','1.5');p.setAttribute('vector-effect','non-scaling-stroke');svg.append(p);}run=[];};
  values.forEach((value,i)=>{if(i&&Date.parse(times[i])-Date.parse(times[i-1])>300000)flush();if(Number.isFinite(value))run.push(`${2+i*112/Math.max(1,values.length-1)},${span?20-(value-lo)/span*18:11}`);else flush();});flush();return svg;
}
function metric(value,series,times,label,tone='neutral',sub=''){
  const td=node('td');td.dataset.label=label;td.append(node('strong',value),sparkline(series,times,label+' · completed 5m trend',tone));if(sub)td.append(node('small',sub));return td;
}
function details(root){
  const row=data?.rows.find(r=>r.symbol===selected)||data?.rows[0],box=root.querySelector('.db-detail');box.replaceChildren();if(!row)return;
  const heading=node('div',null,'db-detail-title');heading.append(node('h3',row.symbol+' · decision evidence'),node('small',row.closed_at?'Last closed candle '+row.closed_at.slice(11,16)+' IST':'No recorded closed candle'));box.append(heading);
  const signals=node('div',null,'db-indicator-list');for(const [key,value]of Object.entries(row.signal.indicators)){const item=node('div',null,value.direction>0?'db-bull':value.direction<0?'db-bear':'db-neutral');item.append(node('span',NAMES[key]),node('strong',value.ready?value.state:'WARMUP / GAP'));signals.append(item);}box.append(signals);
  const action=node('div',null,'db-playbook');action.append(node('strong',failed?'NO TRADE · connection/data unavailable':row.guidance),node('span',row.signal.reason),node('small',`ATR ${num(row.atr)} · Opening range ${num(row.opening_range.low)}–${num(row.opening_range.high)} · Lot ${row.lot_size}`));box.append(action);
  const contract=node('div',null,'db-contract');const c=row.contract;contract.append(node('strong',c?`${c.strike} ${c.side} · ₹${num(c.ltp)}`:'No verified contract quote'),node('small',c?`Bid ₹${num(c.bid)} / ask ₹${num(c.ask)} · ${c.expiry||'Expiry unavailable'}`:'Use option chain to inspect strike, expiry and liquidity.'),node('small',(row.blockers||[]).map(b=>b.replaceAll('_',' ').toLowerCase()).join(' · ')));if(row.paper_plan){const p=row.paper_plan;contract.append(node('small',`Paper illustration · stop ₹${num(p.stop)} / target ₹${num(p.target)} · qty ${p.quantity||0}`));}box.append(contract);
}
function render(root){
  if(!data)return;const focus=root.contains(document.activeElement)?document.activeElement?.dataset?.symbol:null;
  const body=root.querySelector('tbody');body.replaceChildren();let bulls=0,bears=0;
  for(const row of data.rows){const s=row.signal,tone=s.direction>0?'bull':s.direction<0?'bear':'neutral';if(s.direction>0)bulls++;if(s.direction<0)bears++;
    const tr=node('tr',null,row.symbol===selected?'db-selected':'');tr.dataset.symbol=row.symbol;
    const index=node('td');index.dataset.label='Index';const button=node('button',row.symbol,'db-index');button.type='button';button.dataset.symbol=row.symbol;button.setAttribute('aria-pressed',String(row.symbol===selected));button.setAttribute('aria-label','Inspect '+row.symbol+' signal evidence');button.addEventListener('click',()=>{selected=row.symbol;render(root);});index.append(button,node('small',`Lot ${row.lot_size} · ${row.closed_at?row.closed_at.slice(11,16)+' IST':'No data'}`));
    const price=metric(num(row.current_spot??row.spot),row.trends.price,row.times,'Index / 5m',row.session_change_pct>0?'bull':row.session_change_pct<0?'bear':'neutral',row.current_spot!=null?'5m close '+num(row.spot):row.session_change_pct==null?'No session samples':`${row.session_change_pct>=0?'+':''}${num(row.session_change_pct)}% from session first sample`);
    const call=metric(oi(row.ce_oi),row.trends.ce_oi,row.times,'Call OI','call');const put=metric(oi(row.pe_oi),row.trends.pe_oi,row.times,'Put OI','put');
    const flow=metric(oi(row.oi_flow),row.trends.oi_flow,row.times,'Δ OI · 5m',row.oi_flow>0?'bull':row.oi_flow<0?'bear':'neutral','Net P−C '+oi(row.net_oi));
    const pcr=metric(num(row.pcr),row.trends.pcr,row.times,'PCR','neutral');
    const signal=metric(s.ready?`${s.bulls}↑ ${s.bears}↓ / ${s.ready}`:'Warming up',row.trends.signal,row.times,'5m alignment',tone,'Hull · Alpha · Shonya · OTT');signal.classList.add('db-signal');
    const range=node('td',null,'db-range');range.dataset.label='Opening range';range.append(node('strong',row.opening_range.state),node('small',num(row.opening_range.high)+' H'),node('small',num(row.opening_range.low)+' L'));
    const action=node('td',null,'db-action');action.dataset.label='Action / data';action.append(node('strong',failed?'NO TRADE · STALE':row.guidance,failed?'db-warn':`db-${tone}`),node('small',failed?'Refresh to restore current evidence':data.historical_replay?'Historical · no order routing':row.source+' · '+(row.quote_age_seconds==null?'no fresh quote':Math.round(row.quote_age_seconds)+'s receipt age')));
    tr.append(index,price,call,put,flow,pcr,signal,range,action);body.append(tr);
  }
  root.querySelector('.db-alignment').textContent=`${bulls} bullish · ${bears} bearish · ${data.rows.length-bulls-bears} mixed / warming`;
  root.querySelector('.db-time').textContent=`${data.historical_replay?'REPLAY':'CURRENT SESSION'} · ${data.trade_date} · as of ${data.as_of.slice(11,16)} IST`;
  root.querySelector('.db-risk').textContent=`Capital ₹${num(data.risk?.capital)} · free ₹${num(data.risk?.available)} · ${data.risk?.open_positions??0} open`;
  root.querySelector('.db-status').textContent=failed?'Data stale / unavailable · action guidance blocked':`Closed 5m signals · ${data.session.session_state.toLowerCase()} · auto-refresh ${data.historical_replay?'paused for replay':'10s'}`;
  root.classList.toggle('db-stale',failed);details(root);
  if(focus){const button=[...root.querySelectorAll('.db-index')].find(b=>b.dataset.symbol===focus);button?.focus({preventScroll:true});}
}
async function load(root){
  if(mounted!==root||!AccessGate.isUnlocked())return;const current=++sequence;clearTimeout(timer);const refresh=root.querySelector('.db-refresh');refresh.disabled=true;
  try{const params=new URLSearchParams();const date=root.querySelector('.db-date').value;if(date){params.set('trade_date',date);params.set('at',root.querySelector('.db-at').value||'15:40');}const result=await ApiClient.get('/api/dashboard/board?'+params);if(current!==sequence||mounted!==root)return;if(!result)throw Error('No board snapshot');data=result;failed=false;received=Date.now();
    const dateSelect=root.querySelector('.db-date'),previous=dateSelect.value;dateSelect.replaceChildren(new Option('Latest / current',''));for(const day of data.available_dates)dateSelect.append(new Option(day,day));dateSelect.value=previous;render(root);
  }catch(e){if(current===sequence&&mounted===root){failed=true;if(data)render(root);else root.querySelector('.db-status').textContent='Board unavailable. Sign in and check the data service, then refresh.';}}
  finally{if(current===sequence&&mounted===root){refresh.disabled=false;if(!root.querySelector('.db-date').value)timer=setTimeout(()=>{if(!document.hidden&&store.getState().activeTab==='dashboard')load(root);else schedule(root);},10000);}}
}
function schedule(root){clearTimeout(timer);if(mounted===root)timer=setTimeout(()=>{if(!document.hidden&&store.getState().activeTab==='dashboard')load(root);else schedule(root);},10000);}
export async function renderDecisionBoard(container){
  if(mounted&&container.contains(mounted))return;destroyDecisionBoard();
  const root=node('section',null,'decision-board');root.id='decision-board';root.setAttribute('aria-label','All-index decision board');mounted=root;
  // Static template contains no API or user text. Every dynamic value uses textContent.
  root.innerHTML=`<div class="db-toolbar"><div><h2>All-index decision board</h2><span class="db-alignment">Awaiting recorded data</span></div><div class="db-controls"><label>Session<select class="db-date"><option value="">Latest / current</option></select></label><label>As of · IST<input class="db-at" type="time" value="15:40" min="09:15" max="15:40" step="300" disabled></label><button class="db-refresh" type="button">Refresh</button></div></div><div class="db-meta"><span class="db-time"></span><span class="db-risk"></span><span class="db-status" role="status" aria-live="polite">Loading all configured indices…</span></div><div class="db-table-wrap"><table><caption class="db-sr-only">Five-index overview: OI, closed five-minute indicators and watchlist guidance. Sparklines have independent scales.</caption><thead><tr><th>Index</th><th>Index / 5m</th><th>Call OI</th><th>Put OI</th><th>Δ OI · 5m</th><th>PCR</th><th>5m alignment</th><th>Opening range</th><th>Action / data</th></tr></thead><tbody></tbody></table></div><div class="db-key"><span>Call OI <i class="db-call">━</i> · Put OI <i class="db-put">━</i> · Δ OI = Δ put − Δ call · alignment ↑ / ↓ / ready indicators</span><span>Watchlist context · independent spark scales · no calibrated accuracy score</span></div><div class="db-detail"></div><div class="db-links"><a href="/research">Full charts & historical research ↗</a><a href="/strategy">Entry / exit rules & risk ↗</a><span>All live orders disabled</span></div>`;
  container.replaceChildren(root);root.querySelector('.db-refresh').addEventListener('click',()=>load(root));root.querySelector('.db-date').addEventListener('change',()=>{root.querySelector('.db-at').disabled=!root.querySelector('.db-date').value;load(root);});root.querySelector('.db-at').addEventListener('change',()=>load(root));
  watchdog=setInterval(()=>{if(mounted!==root||!data||data.historical_replay)return;if(Date.now()-received>25000&&!failed){failed=true;render(root);}},1000);
  await load(root);
}
