"""Build a standalone, self-contained tester page (share/tester.html) for Pixelcloud.

Injects the seeded-listings snapshot into an HTML template whose search/browse/geo/sort
logic runs entirely client-side (no server, no network). Approximates the live API's
ranking (title weight A > description weight B). Run: uv run python share/build_tester.py
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).parent
SNAPSHOT = pathlib.Path("/tmp/listings_snapshot.json")

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bazaar Search Tester (P3)</title>
<style>
  :root { --bg:#0f1115; --card:#1a1e26; --line:#2a2f3a; --fg:#e6e9ef; --mut:#9aa4b2; --acc:#4f8cff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui,sans-serif; }
  header { padding:14px 18px; border-bottom:1px solid var(--line); }
  header h1 { font-size:16px; margin:0 0 3px; }
  header .note { color:var(--mut); font-size:12px; }
  main { padding:16px 18px; max-width:1100px; margin:0 auto; }
  .controls { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:8px;
    background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; }
  .seg { grid-column:1/-1; display:flex; border:1px solid var(--line); border-radius:8px; overflow:hidden; max-width:240px; }
  .seg button { flex:1; padding:8px; background:#0c0e12; color:var(--fg); border:0; cursor:pointer; font-weight:600; }
  .seg button.on { background:var(--acc); color:#fff; }
  label { display:block; color:var(--mut); font-size:11px; margin-bottom:3px; }
  input, select { width:100%; padding:7px 8px; background:#0c0e12; color:var(--fg); border:1px solid var(--line); border-radius:6px; }
  .full { grid-column:1/-1; }
  .actions { grid-column:1/-1; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .go { padding:9px 16px; background:var(--acc); color:#fff; border:0; border-radius:6px; font-weight:700; cursor:pointer; }
  .preset { padding:6px 10px; background:#0c0e12; color:var(--fg); border:1px solid var(--line); border-radius:6px; cursor:pointer; font-size:12px; }
  .req { grid-column:1/-1; font-family:ui-monospace,monospace; font-size:11px; color:var(--mut); word-break:break-all; }
  .bar { display:flex; align-items:center; gap:10px; margin:14px 0; color:var(--mut); font-size:13px; }
  .bar .sp { flex:1; }
  .bar button { padding:6px 10px; background:var(--card); color:var(--fg); border:1px solid var(--line); border-radius:6px; cursor:pointer; }
  .bar button:disabled { opacity:.4; cursor:default; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:10px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  .thumb { height:78px; display:flex; align-items:center; justify-content:center; font-size:32px; }
  .b { padding:8px 10px; }
  .t { font-weight:600; font-size:13px; margin:0 0 4px; }
  .p { color:var(--acc); font-weight:700; }
  .m { color:var(--mut); font-size:11px; margin-top:2px; text-transform:capitalize; }
  .err { background:#2a1416; border:1px solid #5a2a2a; color:#ffb4b4; padding:10px 12px; border-radius:8px; font-family:ui-monospace,monospace; white-space:pre-wrap; }
</style>
</head>
<body>
<header>
  <h1>Bazaar Search Tester</h1>
  <div class="note">P3 \u00b7 offline snapshot of 150 seeded listings (app_id=demo-app). Search/filter/sort/geo run client-side and <b>approximate</b> the live API ranking (title &gt; description, geo bounding-box, offset paging). The real FastAPI+Postgres API is the source of truth.</div>
</header>
<main>
<div class="controls">
  <div class="seg"><button data-mode="browse" class="on">Browse</button><button data-mode="search">Search</button></div>
  <div class="full" id="qwrap" style="display:none"><label>q (full-text, required for search)</label><input id="q" placeholder="e.g. leather couch"></div>
  <div><label>category</label><select id="category"><option value="">(any)</option><option>furniture</option><option>electronics</option><option>apparel</option><option>baby_kids</option><option>other</option></select></div>
  <div><label>condition</label><select id="condition"><option value="">(any)</option><option>new</option><option>like_new</option><option>good</option><option>fair</option></select></div>
  <div><label>sort</label><select id="sort"></select></div>
  <div><label>price_min ($)</label><input id="pmin" type="number" min="0" placeholder="50"></div>
  <div><label>price_max ($)</label><input id="pmax" type="number" min="0" placeholder="500"></div>
  <div><label>latitude</label><input id="lat" type="number" step="any" placeholder="37.7599"></div>
  <div><label>longitude</label><input id="lng" type="number" step="any" placeholder="-122.4148"></div>
  <div><label>radius_km (max 100)</label><input id="radius" type="number" step="any" placeholder="25"></div>
  <div><label>limit (max 50)</label><input id="limit" type="number" min="1" max="50" value="12"></div>
  <div class="actions">
    <button class="go" id="run">Run</button>
    <button class="preset" data-preset="mission">near Mission (geo)</button>
    <button class="preset" data-preset="cheapElec">cheap electronics</button>
    <button class="preset" data-preset="couch">search leather couch</button>
  </div>
  <div class="req" id="req"></div>
</div>
<div class="bar"><span id="summary">-</span><span class="sp"></span><button id="prev" disabled>Prev</button><button id="next" disabled>Next</button></div>
<div id="out"></div>
</main>
<script type="application/json" id="listings">__DATA__</script>
<script>
(function(){
  var DATA = JSON.parse(document.getElementById('listings').textContent);
  var $ = function(id){ return document.getElementById(id); };
  var EMO = {furniture:'\\uD83D\\uDECB\\uFE0F',electronics:'\\uD83D\\uDCBB',apparel:'\\uD83E\\uDDE5',baby_kids:'\\uD83E\\uDDF8',other:'\\uD83C\\uDFB8'};
  var HUE = {furniture:'#3a2e1e',electronics:'#1e2a3a',apparel:'#2e1e3a',baby_kids:'#1e3a2a',other:'#3a1e2a'};
  var CATS = ['furniture','electronics','apparel','baby_kids','other'];
  var SORTS = { browse:[['newest','newest'],['price_asc','price up'],['price_desc','price down']],
                search:[['relevance','relevance'],['price_asc','price up'],['price_desc','price down']] };
  var mode='browse', offset=0;
  function renderSorts(){ $('sort').innerHTML = SORTS[mode].map(function(s){return '<option value="'+s[0]+'">'+s[1]+'</option>';}).join(''); }
  function setMode(m){ mode=m; offset=0;
    document.querySelectorAll('.seg button').forEach(function(b){ b.classList.toggle('on', b.dataset.mode===m); });
    $('qwrap').style.display = m==='search'?'block':'none'; renderSorts(); }
  function bbox(lat,lng,r){ var dLat=r/111, c=Math.cos(lat*Math.PI/180), dLng=Math.abs(c)<1e-9?180:r/(111*c);
    return {s:lat-dLat,n:lat+dLat,w:lng-Math.abs(dLng),e:lng+Math.abs(dLng)}; }
  function num(v){ return v.trim()===''?null:Number(v); }
  function collect(){ return { q:$('q').value.trim(), category:$('category').value, condition:$('condition').value,
    sort:$('sort').value, pmin:num($('pmin').value), pmax:num($('pmax').value), lat:num($('lat').value),
    lng:num($('lng').value), radius:num($('radius').value), limit:Math.max(1,Math.min(50,num($('limit').value)||12)) }; }
  function validate(p){
    if(mode==='search' && p.q==='') return "query parameter 'q' is required";
    if(p.radius!==null && !(p.radius>0 && p.radius<=100)) return 'radius_km must be between 0 and 100';
    if((p.lat===null)!==(p.lng===null)) return 'both latitude and longitude are required for geo filtering';
    if(p.category!=='' && CATS.indexOf(p.category)<0) return 'invalid category';
    return null; }
  function reqString(p){ var base = mode==='search'?'/v1/listings/search':'/v1/listings'; var q=[];
    var put=function(k,v){ if(v!==null&&v!=='') q.push(k+'='+encodeURIComponent(v)); };
    if(mode==='search') put('q',p.q); put('category',p.category); put('condition',p.condition); put('sort',p.sort);
    if(p.pmin!==null) put('price_min_cents',Math.round(p.pmin*100)); if(p.pmax!==null) put('price_max_cents',Math.round(p.pmax*100));
    put('latitude',p.lat); put('longitude',p.lng); put('radius_km',p.radius); put('limit',p.limit); put('offset',offset);
    return 'GET '+base+'?'+q.join('&'); }
  function query(p){
    var rows = DATA.filter(function(l){
      if(p.category && l.category!==p.category) return false;
      if(p.condition && l.condition!==p.condition) return false;
      if(p.pmin!==null && l.price_cents < p.pmin*100) return false;
      if(p.pmax!==null && l.price_cents > p.pmax*100) return false;
      if(p.lat!==null && p.lng!==null){ var b=bbox(p.lat,p.lng,p.radius===null?25:p.radius);
        if(!(l.latitude>=b.s&&l.latitude<=b.n&&l.longitude>=b.w&&l.longitude<=b.e)) return false; }
      return true; });
    if(mode==='search'){
      var terms=p.q.toLowerCase().split(/\\s+/).filter(Boolean);
      rows = rows.map(function(l){ var t=l.title.toLowerCase(), d=(l.description||'').toLowerCase();
        var all=terms.every(function(x){return t.indexOf(x)>=0||d.indexOf(x)>=0;});
        var sc=0; terms.forEach(function(x){ if(t.indexOf(x)>=0)sc+=2; if(d.indexOf(x)>=0)sc+=1; });
        return {l:l,ok:all,sc:sc}; }).filter(function(r){return r.ok;});
      if(p.sort==='price_asc') rows.sort(function(a,b){return a.l.price_cents-b.l.price_cents||b.l.id-a.l.id;});
      else if(p.sort==='price_desc') rows.sort(function(a,b){return b.l.price_cents-a.l.price_cents||b.l.id-a.l.id;});
      else rows.sort(function(a,b){return b.sc-a.sc||b.l.id-a.l.id;});
      rows=rows.map(function(r){return r.l;});
    } else {
      if(p.sort==='price_asc') rows.sort(function(a,b){return a.price_cents-b.price_cents||b.id-a.id;});
      else if(p.sort==='price_desc') rows.sort(function(a,b){return b.price_cents-a.price_cents||b.id-a.id;});
      else rows.sort(function(a,b){return b.id-a.id;});
    }
    return rows; }
  function esc(s){ return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  function run(){
    var p=collect(); $('req').textContent = reqString(p);
    var err=validate(p);
    if(err){ var code=(mode==='search'&&p.q==='')?'HTTP 400':'HTTP 422'; $('summary').textContent=code;
      $('out').innerHTML='<div class="err">'+code+'\\n'+JSON.stringify({error:err},null,2)+'</div>';
      $('prev').disabled=$('next').disabled=true; return; }
    var all=query(p), total=all.length, page=all.slice(offset,offset+p.limit);
    $('summary').textContent = total+' results \\u00b7 showing '+page.length+' \\u00b7 offset '+offset;
    $('prev').disabled=offset<=0; $('next').disabled=offset+p.limit>=total;
    $('out').innerHTML = page.length ? '<div class="grid">'+page.map(function(l){
      return '<div class="card"><div class="thumb" style="background:'+(HUE[l.category]||'#222')+'">'+(EMO[l.category]||'\\uD83D\\uDCE6')+'</div><div class="b"><p class="t">'+esc(l.title)+'</p><div class="p">$'+(l.price_cents/100).toFixed(2)+'</div><div class="m">'+esc(l.category.replace('_',' '))+' \\u00b7 '+esc(l.condition.replace('_',' '))+'</div></div></div>';
    }).join('')+'</div>' : '<div class="err">{"data": [], "pagination": {"total": 0}}  - no results</div>';
  }
  document.querySelectorAll('.seg button').forEach(function(b){ b.addEventListener('click',function(){ setMode(b.dataset.mode); run(); }); });
  $('run').addEventListener('click',function(){ offset=0; run(); });
  $('prev').addEventListener('click',function(){ offset=Math.max(0,offset-collect().limit); run(); });
  $('next').addEventListener('click',function(){ offset=offset+collect().limit; run(); });
  document.querySelectorAll('.preset').forEach(function(b){ b.addEventListener('click',function(){
    ['q','pmin','pmax','lat','lng','radius'].forEach(function(id){ $(id).value=''; });
    $('category').value=''; $('condition').value='';
    var k=b.dataset.preset;
    if(k==='mission'){ setMode('browse'); $('lat').value='37.7599'; $('lng').value='-122.4148'; $('radius').value='2'; }
    else if(k==='cheapElec'){ setMode('browse'); $('category').value='electronics'; renderSorts(); $('sort').value='price_asc'; }
    else if(k==='couch'){ setMode('search'); $('q').value='leather couch'; renderSorts(); }
    offset=0; run();
  }); });
  setMode('browse'); run();
})();
</script>
</body>
</html>
"""


def main() -> None:
    data = json.loads(SNAPSHOT.read_text())
    compact = json.dumps(data, separators=(",", ":"))
    html = TEMPLATE.replace("__DATA__", compact)
    out = HERE / "tester.html"
    out.write_text(html)
    print(f"Wrote {out} ({len(html)} bytes, {len(data)} listings)")


if __name__ == "__main__":
    main()
