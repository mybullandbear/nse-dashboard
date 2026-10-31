"""Pure JS render-key regression without a browser or broker session."""
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_chain_oi_updates_invalidate_render_even_when_spot_is_flat():
    script=r'''
const fs=require('node:fs');const vm=require('node:vm');const assert=require('node:assert/strict');
const source=fs.readFileSync('backend/app/static/js/app.js','utf8');
const start=source.indexOf('function _contentDataKey(s)');const end=source.indexOf('class TerminalApp',start);
const key=vm.runInNewContext(source.slice(start,end)+'; _contentDataKey;');
const state={activeTab:'chain',activeChainSymbol:'NIFTY',optionChain1:{spot_price:25000,strikes:[{strikePrice:25000,CE:{openInterest:100,lastPrice:20},PE:{openInterest:90,lastPrice:22}}]}};
const before=key(state);state.optionChain1.strikes[0].CE.openInterest=200;
assert.notEqual(key(state),before);
const second=key(state);state.optionChain1.strikes[0].CE.lastPrice=21;assert.notEqual(key(state),second);
'''
    subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True,text=True)


def test_ui_cannot_enable_live_mode():
    source=(ROOT/'backend/app/static/js/components/shonya_terminal.js').read_text()
    assert 'id="btn-mode-live" disabled' in source
    assert "setShonyaMode('LIVE')" not in source
