import json
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app

ROOT=Path(__file__).resolve().parents[1]/'backend/app/static'

def test_manifest_local_icons_and_shell():
    c=TestClient(app)
    manifest=c.get('/manifest.json').json()
    assert manifest['display']=='standalone' and manifest['scope']=='/'
    for icon in manifest['icons']:
        assert icon['src'].startswith('/static/icons/')
        assert c.get(icon['src']).status_code==200
        size=int(icon['sizes'].split('x')[0])
        assert Image.open(ROOT/icon['src'].removeprefix('/static/')).size==(size,size)
    assert c.get('/static/offline.html').status_code==200
    html=c.get('/').text
    assert 'user-scalable=no' not in html
    assert 'modern-terminal.css' in html


def test_five_modules_preserved():
    html=(ROOT/'index.html').read_text()
    for name in ['dashboard','option-confluence','shonya-terminal','oi-analytics','chain']:
        assert html.count(f'data-tab="{name}"')==2


def test_service_worker_never_intercepts_api_or_caches_navigation():
    import subprocess
    script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const handlers={};const cached=[];
const context={URL,Promise,self:{location:{origin:'https://terminal.test'},addEventListener:(name,cb)=>handlers[name]=cb,skipWaiting:()=>{},clients:{claim:()=>{}}},caches:{match:async path=>({offline:path}),open:async()=>({addAll:async list=>cached.push(...list)}),keys:async()=>[]},fetch:async()=>{throw Error('offline')}};
vm.runInNewContext(fs.readFileSync('backend/app/static/sw.js','utf8'),context);
(async()=>{
let intercepted=false;
for(const [method,path] of [['GET','/api/market/indices'],['GET','/ws/live'],['POST','/api/shonya/trade/manual']]){
 handlers.fetch({request:{method,url:'https://terminal.test'+path,mode:'cors'},respondWith:()=>intercepted=true});
 assert.equal(intercepted,false);
}
let fallback;handlers.fetch({request:{method:'GET',url:'https://terminal.test/',mode:'navigate'},respondWith:p=>fallback=p});
assert.equal((await fallback).offline,'/static/offline.html');
let install;handlers.install({waitUntil:p=>install=p});await install;
assert(!cached.includes('/'));assert(cached.every(path=>path.startsWith('/static/')));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    subprocess.run(['node','-e',script],cwd=ROOT.parents[2],check=True,capture_output=True,text=True)
