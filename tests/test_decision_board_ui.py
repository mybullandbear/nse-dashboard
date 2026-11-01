"""Actual decision-board controller and SVG logic in a DOM VM, not pixel QA."""
import json
import subprocess
from pathlib import Path
from test_decision_board import response


def test_board_rows_sparklines_replay_selection_stale_failure_and_cleanup(tmp_path):
    fixture=tmp_path/'snapshot.json';fixture.write_text(json.dumps(response(tmp_path)))
    script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class E{constructor(tag='div'){this.tag=tag;this.children=[];this.events={};this.dataset={};this.value='';this.classes=new Set();this.classList={add:(...s)=>s.forEach(x=>this.classes.add(x)),toggle:(s,on)=>on?this.classes.add(s):this.classes.delete(s)};}append(...nodes){this.children.push(...nodes);if(this.tag==='select'&&!this.value&&nodes.length)this.value=nodes[0].value}replaceChildren(...nodes){this.children=[];this.append(...nodes)}setAttribute(k,v){this[k]=v}addEventListener(k,f){this.events[k]=f}get className(){return this._cls||''}set className(v){this._cls=v;this.classes=new Set(v.split(' '))}set innerHTML(s){this.map={};for(const m of s.matchAll(/<(\w+)[^>]*class="([^"]+)"/g)){const n=new E(m[1]);n.className=m[2];for(const c of m[2].split(' '))this.map['.'+c]=n;}this.map.tbody=new E('tbody');this.map['.db-at'].value='15:40';this.children=Object.values(this.map)}querySelector(s){return this.map?.[s]||null}querySelectorAll(s){const results=[];function visit(n){if(s.startsWith('.')&&n.classes.has(s.slice(1)))results.push(n);n.children.forEach(visit)}this.children.forEach(visit);return results}contains(target){return this===target||this.children.some(n=>n.contains(target))}focus(){}}
const sample=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));let fail=false,calls=[],destroyed=0,intervals=[],now=1000;const container=new E();
const context={console,Number,String,Math,Object,Date:class extends Date{static now(){return now}},URLSearchParams,document:{hidden:false,activeElement:null,createElement:t=>new E(t),createElementNS:(_,t)=>new E(t)},Option:class extends E{constructor(t,v){super('option');this.textContent=t;this.value=v;}},setTimeout:()=>1,clearTimeout:()=>{destroyed++},setInterval:f=>{intervals.push(f);return 1},clearInterval:()=>{destroyed++},store:{getState:()=>({activeTab:'dashboard'})},AccessGate:{isUnlocked:()=>true},ApiClient:{get:async url=>{calls.push(url);return fail?null:JSON.parse(JSON.stringify(sample));}},container};
const source=fs.readFileSync('backend/app/static/js/components/decision_board.js','utf8').replace(/^import .*;\n/gm,'').replaceAll('export function','function').replace('export async function','async function');
(async()=>{await vm.runInNewContext('(async()=>{'+source+'\nawait renderDecisionBoard(container);globalThis.destroy=destroyDecisionBoard;})()',context);
let root=container.children[0],body=root.querySelector('tbody');assert.equal(body.children.length,5);assert.equal(body.children[0].children.length,9);assert(body.children[0].children[2].children.some(n=>n.tag==='svg'));assert(root.querySelector('.db-time').textContent.includes('REPLAY'));
body.children[1].children[0].children[0].events.click();assert(root.querySelector('.db-detail').children[0].children[0].textContent.includes('BANKNIFTY'));
root.querySelector('.db-date').value='2026-10-14';root.querySelector('.db-at').value='10:20';await root.querySelector('.db-date').events.change();await new Promise(r=>setImmediate(r));assert(calls.at(-1).includes('10%3A20'));assert.equal(root.querySelector('.db-at').disabled,false);
fail=true;await root.querySelector('.db-refresh').events.click();assert(root.querySelector('.db-status').textContent.includes('stale'));assert(root.querySelector('tbody').children[0].children[8].children[0].textContent.includes('NO TRADE'));context.destroy();assert(destroyed>0);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    subprocess.run(['node','-e',script,str(fixture)],cwd=Path(__file__).parents[1],check=True,capture_output=True,text=True)


def test_switching_to_oi_still_fetches_pair_without_dashboard_side_effects():
    script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');const source=fs.readFileSync('backend/app/static/js/app.js','utf8');const start=source.indexOf('  switchTab(tab) {'),end=source.indexOf('  render(state) {',start);let state={activeTab:'dashboard',symbol1:'NIFTY',symbol2:'BANKNIFTY'},calls=[];
const context={_prevTab:'dashboard',_contentMounted:true,destroyDecisionBoard:()=>{},document:{querySelectorAll:()=>[]},store:{setState:v=>Object.assign(state,v),getState:()=>state,isReplayActive:()=>false},ApiClient:{fetchOIAnalytics:async s=>{calls.push(s);return {symbol:s}}},console};const App=vm.runInNewContext('class App{'+source.slice(start,end)+'};App',context);const app=new App();app.contentMount={innerHTML:''};app.switchTab('oi-analytics');setImmediate(()=>{assert.equal(calls.length,2);assert(state.oiData1);});
'''
    subprocess.run(['node','-e',script],cwd=Path(__file__).parents[1],check=True,capture_output=True,text=True)
