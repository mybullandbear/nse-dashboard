// Local SVG renderer: no CDN, network calls, or injected HTML.
const NS='http://www.w3.org/2000/svg';
function svg(tag,attrs={},text){const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!=null)n.textContent=text;return n;}
export function chart(root,bars,series=[],{oi=false,trades=[],selected=-1,limit=78}={}){
  root.replaceChildren();if(!bars.length){const p=document.createElement('p');p.className='empty';p.textContent='No recorded closed candles for this selection.';root.append(p);return;}
  const end=selected>=0?Math.min(bars.length,Math.max(limit,selected+Math.ceil(limit/2))):bars.length,start=Math.max(0,end-limit),data=bars.slice(start,end),w=Math.max(260,root.clientWidth||1000),h=oi?150:350,left=12,right=85,top=20,bottom=30;
  const values=oi?data.flatMap(b=>[b.ce_oi,b.pe_oi]):data.flatMap((b,j)=>[b.low,b.high,series[start+j]?.line,series[start+j]?.reference,series[start+j]?.upper]);
  const valid=values.filter(v=>Number.isFinite(v));if(!valid.length)return;
  let min=Math.min(...valid),max=Math.max(...valid);const pad=(max-min)*.08||1;min-=pad;max+=pad;
  const dx=(w-left-right)/data.length,x=i=>left+(i+.5)*dx,y=v=>top+(max-v)/(max-min)*(h-top-bottom);
  const el=svg('svg',{viewBox:`0 0 ${w} ${h}`,preserveAspectRatio:'none','aria-hidden':'true'});root.append(el);
  for(let j=0;j<5;j++){const value=min+(max-min)*j/4,yy=y(value);el.append(svg('line',{x1:left,x2:w-right,y1:yy,y2:yy,stroke:'#263140','stroke-width':1}),svg('text',{x:w-right+9,y:yy+4},oi?(value/1e6).toFixed(1)+'m':value.toFixed(2)));}
  const poly=(get,color,dash)=>{let run=[];const flush=()=>{if(run.length)el.append(svg('polyline',{points:run.join(' '),fill:'none',stroke:color,'stroke-width':2,...(dash?{'stroke-dasharray':'5 4'}:{})}));run=[];};data.forEach((b,i)=>{const value=get(b,i);if(Number.isFinite(value))run.push(`${x(i)},${y(value)}`);else flush();});flush();};
  if(oi){poly(b=>b.ce_oi,'#ee7990');poly(b=>b.pe_oi,'#45cfaa');}
  else {data.forEach((b,i)=>{const color=b.close>=b.open?'#45cfaa':'#ee7990';el.append(svg('line',{x1:x(i),x2:x(i),y1:y(b.high),y2:y(b.low),stroke:color}),svg('rect',{x:x(i)-Math.max(1,dx*.28),y:Math.min(y(b.open),y(b.close)),width:Math.max(2,dx*.56),height:Math.max(1,Math.abs(y(b.open)-y(b.close))),fill:b.complete?color:'none',stroke:color}));const entry=trades.find(t=>t.entry_at===b.time);if(entry)el.append(svg('circle',{cx:x(i),cy:y(b.low)+12,r:4,fill:entry.direction>0?'#45cfaa':'#ee7990',stroke:'#dce4ef'}));});poly((b,i)=>series[start+i]?.line,'#87aafa');poly((b,i)=>series[start+i]?.reference,'#d5b774',true);poly((b,i)=>series[start+i]?.upper,'#d5b774',true);}
  const cursor=selected-start;if(cursor>=0&&cursor<data.length)el.append(svg('line',{x1:x(cursor),x2:x(cursor),y1:top,y2:h-bottom,stroke:'#c4d5ed','stroke-dasharray':'3 4'}));
  const stride=Math.max(1,Math.ceil(data.length/(w<600?3:6)));data.forEach((b,i)=>{if(i%stride===0)el.append(svg('text',{x:x(i),y:h-7,'text-anchor':'middle'},b.time.slice(11,16)));});
}
