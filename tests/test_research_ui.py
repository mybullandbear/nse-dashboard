"""Exercise actual renderer/controller in a DOM VM; not browser pixel QA."""
import json
import subprocess
from pathlib import Path
from datetime import datetime
from app.core.market_hours import IST
from app.services.research_workbench import closed_bars,indicators,replay


def test_research_controls_charts_comparison_and_failure(tmp_path):
    rows=[dict(id=i,timestamp=f'2026-10-14T{9+(15+i)//60:02}:{(15+i)%60:02}:00+05:30',price=20000+i,ce_oi=10000+i,pe_oi=12000+i*2) for i in range(180)]
    bars=closed_bars(rows,datetime(2026,10,14,12,15,tzinfo=IST));studies={k:dict(series=v,research=replay(bars,v)) for k,v in indicators(bars).items()}
    data=dict(symbol='NIFTY',trade_date='2026-10-14',as_of='2026-10-14T12:15:00+05:30',bars=bars,studies=studies,available_strikes=[20000],option=dict(bars=[],studies={},strike=None),parameters=dict(oi_filter=False,exit_mode='trailing_flip',atr_multiple=2),version='test',quality=dict(incomplete_bars=0,warmup_sessions=1,limitations=['Sampled OHLC']))
    fixture=tmp_path/'data.json';fixture.write_text(json.dumps(data))
    script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class E{constructor(tag='div'){this.tag=tag;this.children=[];this.events={};this.value='';this.textContent='';this.checked=false;}append(...items){this.children.push(...items);if(this.tag==='select'&&!this.value&&items.length)this.value=items[0].value;}replaceChildren(...items){this.children=[];if(this.tag==='select')this.value='';this.append(...items);}setAttribute(k,v){this[k]=v}addEventListener(k,f){this.events[k]=f}querySelector(){return this.button||(this.button=new E('button'))}get options(){return this.children}click(){this.events.click?.()}}
const html=fs.readFileSync('backend/app/static/research.html','utf8'),elements={};for(const m of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"/g))elements[m[2]]=new E(m[1]);
for(const [id,value] of Object.entries({indicator:'hull',window:'78',at:'15:40',atr:'2',exit:'trailing_flip','option-type':'CE'}))elements[id].value=value;
const sample=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));let fail=false,calls=[];
const context={console,Number,String,Math,Object,Set,Map,URLSearchParams,setTimeout,document:{getElementById:id=>elements[id],createElement:t=>new E(t),createElementNS:(_,t)=>new E(t)},window:{addEventListener:()=>{}},Option:class extends E{constructor(text,value){super('option');this.textContent=text;this.value=value;}},AccessGate:{ensureAuthorized:async()=>true,isUnlocked:()=>true},ApiClient:{get:async url=>{calls.push(url);if(fail)return null;if(url.includes('catalog'))return {sessions:[{symbol:'NIFTY',trade_date:'2026-10-14'}]};if(url.includes('/compare'))return {trade_date:sample.trade_date,as_of:sample.as_of,rows:[{symbol:'NIFTY',indicator:'ott',closed_trades:0,gross_index_points:0,win_rate:null,unresolved:0}]};return JSON.parse(JSON.stringify(sample));}}};
const chartSource=fs.readFileSync('backend/app/static/js/research-chart.js','utf8').replace('export function','function');const controller=fs.readFileSync('backend/app/static/js/research.js','utf8').replace(/^import .*;\n/gm,'');
(async()=>{await vm.runInNewContext('(async()=>{'+chartSource+'\n'+controller+'})()',context);assert.equal(elements.metrics.children.length,4);assert.equal(elements['price-chart'].children[0].tag,'svg');assert.equal(elements.comparison.children.length,4);assert(elements['candle-info'].textContent.includes('12:10'));
elements.indicator.value='ott';elements.indicator.events.change();assert(elements['chart-title'].textContent.includes('OTT'));
await elements['compare-indices'].events.click();assert.equal(elements['index-comparison'].children.length,1);assert(calls.at(-1).includes('12%3A15'));
elements.cursor.value='0';elements.cursor.events.input();assert(elements['candle-info'].textContent.includes('09:15'));
fail=true;await elements.controls.events.submit({preventDefault:()=>{}});await new Promise(r=>setImmediate(r));assert(elements.status.textContent.includes('unavailable'));assert.equal(elements.metrics.children.length,0);assert(elements.export.disabled);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    subprocess.run(['node','-e',script,str(fixture)],cwd=Path(__file__).parents[1],check=True,capture_output=True,text=True)
