"""Unit tests for the strategy desk DOM behavior; not a browser layout test."""
import subprocess
from pathlib import Path


def test_desk_switches_family_inspects_evidence_and_marks_failed_refresh():
    script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class E{constructor(){this.children=[];this.events={};this.dataset={};this.attrs={};this.value='';this.open=false;this.textContent='';}append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes}setAttribute(k,v){this.attrs[k]=v}addEventListener(k,v){this.events[k]=v}showModal(){this.open=true}close(){this.open=false}}
const source=fs.readFileSync('backend/app/static/js/strategy-desk.js','utf8').replace(/^import .*;\n/gm,'');
const ids=[...source.matchAll(/\$\('([^']+)'\)/g)].map(x=>x[1]);const elements=Object.fromEntries(ids.map(x=>[x,new E()]));
const buttons=[new E(),new E()];buttons[0].dataset.family='opening_range';buttons[1].dataset.family='trend_pullback';let fail=false,calls=[];
const data={trade_date:'2026-11-02',as_of:'2026-11-02T10:00:00+05:30',historical_replay:false,engine_version:'test',session:{session_state:'LIVE MARKET',current_time_ist:'10:00:00',current_date_ist:'2026-11-02',calendar_status:'VERIFIED'},risk:{capital:100000,risk_per_trade_inr:1000,daily_loss_limit_inr:2000,open_positions:0},policy:{max_positions:2,entry_start:'09:45',entry_end:'14:45',force_exit:'15:35'},rows:[{symbol:'NIFTY',lot_size:65,setup:'WAIT',evidence:{spot:25000,atr:20},bars:45,blockers:['STRATEGY_NOT_FORWARD_VALIDATED'],plan:null}]};
const context={console,Intl,Number,String,URLSearchParams,CustomEvent:class{},document:{hidden:false,activeElement:null,getElementById:id=>elements[id],createElement:()=>new E(),querySelectorAll:()=>buttons,querySelector:()=>elements.notice||(elements.notice=new E()),addEventListener:()=>{}},window:{addEventListener:()=>{}},setInterval:()=>{},AccessGate:{ensureAuthorized:async()=>true,isUnlocked:()=>true,lockTerminal:()=>{}},ApiClient:{get:async url=>{calls.push(url);return fail?null:JSON.parse(JSON.stringify(data));}}};
(async()=>{await vm.runInNewContext('(async()=>{'+source+'})()',context);
assert.equal(elements['desk-rows'].children.length,1);assert.equal(elements['risk-positions'].textContent,'0 / 2');
buttons[1].events.click();await new Promise(r=>setImmediate(r));assert(calls.at(-1).includes('trend_pullback'));
const row=elements['desk-rows'].children[0];row.children[4].children[0].events.click();assert(elements['desk-detail'].open);assert(elements['detail-title'].textContent.includes('NIFTY'));
fail=true;await elements['desk-refresh'].events.click();assert(elements['desk-state'].textContent.includes('unavailable'));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    subprocess.run(['node','-e',script],cwd=Path(__file__).parents[1],check=True,capture_output=True,text=True)
