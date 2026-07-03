import { simulate, calibrate, metrics, PARAM_NAMES } from './hbv.js';

const COL = { water:'#2c6e9c', deep:'#183f57', accent:'#e0862d', good:'#2e8b6b', ink:'#12303c', grid:'#d7e0e3', muted:'#5c7480' };
const PLOTLY_BASE = {
  font:{ family:'Inter, sans-serif', color:COL.ink, size:12 },
  paper_bgcolor:'#fff', plot_bgcolor:'#fff',
  margin:{ t:34, r:14, b:34, l:52 }, hovermode:'x unified',
  xaxis:{ gridcolor:COL.grid, zeroline:false }, yaxis:{ gridcolor:COL.grid, zeroline:false },
};
const CFG = { displayModeBar:false, responsive:true };
const $ = s => document.querySelector(s);
const fmt = (n,d=2) => (n==null||!isFinite(n)) ? '–' : Number(n).toFixed(d);

// ---- state --------------------------------------------------------------
const state = { catchment:null, series:null, dates:null };

// ---- tabs ---------------------------------------------------------------
document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.setAttribute('aria-selected', x===t));
  document.querySelectorAll('.tabpane').forEach(p =>
    p.toggleAttribute('data-active', p.dataset.tab===t.dataset.tab));
  window.dispatchEvent(new Event('resize'));
});

// ---- map ----------------------------------------------------------------
const map = L.map('map', { scrollWheelZoom:true }).setView([51.2, 10.3], 6);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  { attribution:'© OpenStreetMap', maxZoom:18 }).addTo(map);

fetch('data/basins_de.geojson').then(r=>r.json()).then(gj => {
  L.geoJSON(gj, { style:{ color:'#9aa5b1', weight:1, fillOpacity:0.04 },
    interactive:false }).addTo(map);
}).catch(()=>{});

let selectedMarker = null;
fetch('data/camels_examples.json').then(r=>r.json()).then(list => {
  list.forEach(c => {
    const mk = L.circleMarker([c.lat, c.lon], {
      radius:8, color:'#fff', weight:2, fillColor:COL.water, fillOpacity:0.95 })
      .addTo(map).bindTooltip(`${c.name} · ${c.area_km2} km²`);
    mk.on('click', () => selectCatchment(c, mk));
  });
});

// ERA5 anywhere
map.on('click', e => {
  if (e.originalEvent.target.closest('.leaflet-marker-icon')) return;
  $('#cl-src').value = 'era5';
  loadEra5(e.latlng.lat, e.latlng.lng);
  gotoTab('climate');
});

function gotoTab(name){ document.querySelector(`.tab[data-tab=${name}]`).click(); }

// ---- catchment selection ------------------------------------------------
async function selectCatchment(meta, marker){
  if (selectedMarker) selectedMarker.setStyle({ fillColor:COL.water, radius:8 });
  marker.setStyle({ fillColor:COL.accent, radius:11 }); selectedMarker = marker;
  map.setView([meta.lat, meta.lon], 9);

  $('#c-name').textContent = meta.name + (meta.water ? ` · ${meta.water}` : '');
  $('#c-sub').innerHTML = `<span class="spin"></span>loading ${meta.n_days.toLocaleString()} days of record…`;

  const d = await fetch(`data/camels_${meta.id}.json`).then(r=>r.json());
  const dates = daily(d.start, d.q.length);
  state.catchment = { ...meta, ...d };
  state.series = d; state.dates = dates;

  // stats
  const q = d.q, p = d.p, t = d.t;
  const yrs = q.length / 365.25;
  const meanQ = mean(q), meanP = mean(p) * 365.25, meanT = mean(t);
  const runoff = (meanQ * 365.25) / (mean(p) * 365.25);
  $('#c-sub').innerHTML = `CAMELS-DE gauge <span class="mono">${meta.id}</span> · ${dates[0].getFullYear()}–${dates.at(-1).getFullYear()}`;
  $('#c-stats').innerHTML = stat('Area','km²',meta.area_km2,0)
    + stat('Record','yr',yrs,0) + stat('Mean P','mm/yr',meanP,0)
    + stat('Mean T','°C',meanT,1) + stat('Mean Q','mm/d',meanQ,2)
    + stat('Runoff ratio','',runoff,2);

  drawRegime(dates, p, t);
  setupClimateVars(); if ($('#cl-src').value==='catchment') drawClimate();
  setupModel();
}

function stat(k,u,v,d){ return `<div class="stat"><div class="k">${k}${u?` (${u})`:''}</div><div class="v">${fmt(v,d)}</div></div>`; }

function drawRegime(dates, p, t){
  const mP = Array(12).fill(0), mT = Array(12).fill(0), cnt = Array(12).fill(0);
  dates.forEach((dt,i)=>{ const m=dt.getMonth(); if(p[i]!=null){mP[m]+=p[i];} if(t[i]!=null){mT[m]+=t[i];cnt[m]++;} });
  const years = new Set(dates.map(d=>d.getFullYear())).size;
  const P = mP.map(v=>v/years), T = mT.map((v,i)=>v/cnt[i]);
  const months = ['J','F','M','A','M','J','J','A','S','O','N','D'];
  Plotly.react('c-regime', [
    { type:'bar', x:months, y:P, name:'Precip', marker:{color:COL.water}, yaxis:'y' },
    { type:'scatter', x:months, y:T, name:'Temp', mode:'lines+markers',
      line:{color:COL.accent,width:2}, yaxis:'y2' },
  ], { ...PLOTLY_BASE, title:'Mean monthly regime', height:300, hovermode:'x',
    yaxis:{ title:'mm/month', gridcolor:COL.grid }, legend:{orientation:'h',y:-0.18},
    yaxis2:{ title:'°C', overlaying:'y', side:'right', gridcolor:'transparent' } }, CFG);
}

// ---- climate ------------------------------------------------------------
const ERA5_VARS = [
  ['precipitation_sum','Precipitation (mm)'],['temperature_2m_mean','Mean temp (°C)'],
  ['temperature_2m_max','Max temp (°C)'],['temperature_2m_min','Min temp (°C)'],
  ['et0_fao_evapotranspiration','Ref. ET₀ (mm)'],['snowfall_sum','Snowfall (cm)'],
];
const CAMELS_VARS = [['p','Precipitation (mm)'],['t','Mean temp (°C)'],['pet','PET Hargreaves (mm)'],['q','Discharge (mm)']];
let era5Cache = null;

function setupClimateVars(){
  const src = $('#cl-src').value;
  const vars = src==='catchment' ? CAMELS_VARS : ERA5_VARS;
  $('#cl-var').innerHTML = vars.map(([k,l])=>`<option value="${k}">${l}</option>`).join('');
}
$('#cl-src').onchange = () => { setupClimateVars();
  if ($('#cl-src').value==='catchment') drawClimate();
  else $('#cl-status').textContent = 'Click anywhere on the map to fetch ERA5 there.'; };
$('#cl-var').onchange = drawClimate;
$('#cl-res').onchange = drawClimate;

function drawClimate(){
  const src = $('#cl-src').value;
  if (src==='catchment'){
    if (!state.series){ $('#cl-status').textContent='Select a catchment first.'; return; }
    const v = $('#cl-var').value;
    plotSeries('cl-plot', state.dates, state.series[v], $('#cl-var').selectedOptions[0].text, isFlux(v));
    $('#cl-status').textContent = `${state.catchment.name} · CAMELS-DE`;
  } else {
    if (!era5Cache){ $('#cl-status').textContent='Click the map to fetch ERA5.'; return; }
    const v = $('#cl-var').value;
    plotSeries('cl-plot', era5Cache.dates, era5Cache.d[v], $('#cl-var').selectedOptions[0].text, isFlux(v));
  }
}
const isFlux = v => /precip|snow|et0|pet|^p$|^q$/.test(v);

async function loadEra5(lat, lon){
  gotoTab('climate'); $('#cl-src').value='era5'; setupClimateVars();
  $('#cl-status').innerHTML = `<span class="spin"></span>fetching ERA5 at ${lat.toFixed(2)}, ${lon.toFixed(2)}…`;
  const end = new Date(Date.now()-6*864e5).toISOString().slice(0,10);
  const vars = ERA5_VARS.map(v=>v[0]).join(',');
  const url = `https://archive-api.open-meteo.com/v1/archive?latitude=${lat}&longitude=${lon}&start_date=2010-01-01&end_date=${end}&daily=${vars}&timezone=UTC`;
  try{
    const j = await (await fetch(url)).json();
    const dates = j.daily.time.map(s=>new Date(s+'T00:00'));
    era5Cache = { dates, d:j.daily };
    $('#cl-status').textContent = `ERA5 · ${lat.toFixed(2)}, ${lon.toFixed(2)} · ${dates[0].getFullYear()}–${dates.at(-1).getFullYear()}`;
    drawClimate();
  }catch(e){ $('#cl-status').innerHTML = `<span style="color:#b00">ERA5 fetch failed: ${e.message}</span>`; }
}

function plotSeries(id, dates, vals, label, flux){
  const res = $('#cl-res').value;
  let x = dates, y = vals;
  if (res!=='D'){ [x,y] = resample(dates, vals, res, flux); }
  Plotly.react(id, [{ type:'scatter', mode:'lines', x, y, line:{color:COL.water, width:1.3},
    fill: flux?'tozeroy':'none', fillcolor:'rgba(44,110,156,.12)' }],
    { ...PLOTLY_BASE, title:label, height:340, yaxis:{title:label,gridcolor:COL.grid} }, CFG);
}

// ---- HBV model ----------------------------------------------------------
let modelDates=null, splitYears=null;
function setupModel(){
  if (!state.series){ return; }
  $('#m-need').style.display='none'; $('#m-ui').style.display='block';
  const q = state.series.q, dates = state.dates;
  modelDates = dates;
  const y0 = dates[0].getFullYear()+1, y1 = dates.at(-1).getFullYear();
  splitYears = []; for (let y=y0+1; y<y1; y++) splitYears.push(y);
  const sl = $('#m-split');
  sl.min=0; sl.max=splitYears.length-1; sl.value=Math.floor(splitYears.length*0.6);
  sl.oninput = () => $('#m-splitlab').textContent = splitYears[+sl.value];
  $('#m-splitlab').textContent = splitYears[+sl.value];
  $('#m-stats').innerHTML=''; $('#m-params').innerHTML=''; Plotly.purge('m-plot');
  $('#m-status').textContent='Set the training split and press Calibrate.';
}
$('#m-run').onclick = runCalibration;

function idxByYear(dates, warmupYears=2){
  const t0 = dates[0].getFullYear()+warmupYears;
  return { warmupYear:t0 };
}

async function runCalibration(){
  const s = state.series; const dates = state.dates;
  const P=toArr(s.p), T=toArr(s.t), E=toArr(s.pet), Q=s.q;
  const splitYear = splitYears[+$('#m-split').value];
  const warmupYear = dates[0].getFullYear()+2;
  const objn = $('#m-obj').value, trials = +$('#m-trials').value;

  const trainIdx=[], testIdx=[];
  dates.forEach((dt,i)=>{
    if (Q[i]==null || !isFinite(Q[i]) || P[i]==null) return;
    const y = dt.getFullYear();
    if (y < warmupYear) return;
    if (y <= splitYear) trainIdx.push(i); else testIdx.push(i);
  });
  if (trainIdx.length < 365){ $('#m-status').innerHTML='<span style="color:#b00">Training window too short — move the split later.</span>'; return; }

  $('#m-run').disabled=true;
  $('#m-status').innerHTML=`<span class="spin"></span>calibrating HBV — ${trials} DDS iterations on ${splitYear-warmupYear+1} training years…`;
  await new Promise(r=>setTimeout(r,30)); // let UI paint

  const Qf = Q.map(v=> (v==null||!isFinite(v))?0:v);
  const res = calibrate(P.map(nz), T.map(z), E.map(nz), Qf,
    { objectiveKind:objn, trials, trainIdx });

  const sim = res.simulation;
  const mTr = metrics(Qf, sim, trainIdx), mTe = metrics(Qf, sim, testIdx);
  $('#m-stats').innerHTML =
      statB('Train NSE', mTr.nse, mTr.nse>0.5) + statB('Train KGE', mTr.kge, mTr.kge>0.5)
    + statB('Test NSE', mTe.nse, mTe.nse>0.5) + statB('Test KGE', mTe.kge, mTe.kge>0.5);
  $('#m-params').innerHTML = PARAM_NAMES.map(n=>`<div class="p">${n}<b>${fmt(res.params[n], n==='FC'||n==='UZL'?0:3)}</b></div>`).join('');

  drawHydrograph(dates, Qf, sim, warmupYear, splitYear, mTr, mTe);
  $('#m-status').textContent = `Done. Calibrated on ${warmupYear}–${splitYear}, tested on ${splitYear+1}–${dates.at(-1).getFullYear()}.`;
  $('#m-run').disabled=false;
}

function drawHydrograph(dates, obs, sim, warmupYear, splitYear, mTr, mTe){
  // plot from warmup start for clarity
  const start = dates.findIndex(d=>d.getFullYear()>=warmupYear);
  const x = dates.slice(start), yo = obs.slice(start), ys = sim.slice(start);
  const splitDate = new Date(splitYear+1,0,1), x0=x[0], x1=x.at(-1);
  Plotly.react('m-plot', [
    { type:'scatter', mode:'lines', name:'observed', x, y:yo, line:{color:COL.ink,width:1.3} },
    { type:'scatter', mode:'lines', name:'HBV simulated', x, y:ys, line:{color:COL.water,width:1.3} },
  ], { ...PLOTLY_BASE, title:'Observed vs HBV-simulated discharge (mm/day)', height:360,
    legend:{orientation:'h',y:-0.16}, yaxis:{title:'Q (mm/day)',gridcolor:COL.grid},
    shapes:[
      { type:'rect', xref:'x', yref:'paper', x0, x1:splitDate, y0:0, y1:1, fillcolor:COL.water, opacity:0.06, line:{width:0} },
      { type:'rect', xref:'x', yref:'paper', x0:splitDate, x1, y0:0, y1:1, fillcolor:COL.accent, opacity:0.07, line:{width:0} },
    ],
    annotations:[
      annot(midDate(x0,splitDate), `train · NSE ${fmt(mTr.nse)} · KGE ${fmt(mTr.kge)}`),
      annot(midDate(splitDate,x1), `test · NSE ${fmt(mTe.nse)} · KGE ${fmt(mTe.kge)}`),
    ] }, CFG);
}
function annot(x,text){ return { x, y:1.02, yref:'paper', xref:'x', showarrow:false, text:`<b>${text}</b>`,
  bgcolor:'#fff', bordercolor:COL.line, borderwidth:1, borderpad:4, font:{size:11.5} }; }
function midDate(a,b){ return new Date((a.getTime()+b.getTime())/2); }
function statB(k,v,good){ return `<div class="stat ${good?'good':'warn'}"><div class="k">${k}</div><div class="v">${fmt(v)}</div></div>`; }

// ---- live gauges (PEGELONLINE) -----------------------------------------
let gaugeList=null;
fetch('https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json?includeTimeseries=true')
  .then(r=>r.json()).then(rows=>{
    gaugeList = rows.filter(s=>s.longitude&&s.latitude);
    // add light markers for a subset with discharge to keep the map readable
    const withQ = gaugeList.filter(s=>(s.timeseries||[]).some(t=>t.shortname==='Q'));
    withQ.forEach(s=>{
      L.circleMarker([s.latitude,s.longitude],{radius:3,color:COL.accent,weight:0,
        fillColor:COL.accent,fillOpacity:0.8}).addTo(map)
        .bindTooltip(`${s.longname} (${(s.water||{}).longname||''})`)
        .on('click',()=>{ $('#g-sel').value=s.shortname; gotoTab('gauge'); loadGauge(); });
    });
    $('#g-sel').innerHTML = gaugeList.sort((a,b)=>a.shortname<b.shortname?-1:1)
      .map(s=>`<option value="${s.shortname}">${s.longname} — ${(s.water||{}).longname||''}</option>`).join('');
    $('#g-status').textContent = `${gaugeList.length} gauges. Pick one, or click an orange dot on the map.`;
    loadGauge();
  }).catch(e=>{ $('#g-status').innerHTML=`<span style="color:#b00">gauge list failed: ${e.message}</span>`; });

$('#g-sel').onchange = loadGauge; $('#g-par').onchange = loadGauge;
async function loadGauge(){
  const sh = $('#g-sel').value, par = $('#g-par').value;
  if (!sh) return;
  $('#g-status').innerHTML = `<span class="spin"></span>fetching ${par} at ${sh}…`;
  const base = `https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations/${encodeURIComponent(sh)}`;
  try{
    const meta = await (await fetch(`${base}/${par}.json`)).json();
    const rows = await (await fetch(`${base}/${par}/measurements.json?start=P30D`)).json();
    const x = rows.map(r=>new Date(r.timestamp)), y = rows.map(r=>r.value);
    Plotly.react('g-plot', [{type:'scatter',mode:'lines',x,y,line:{color:COL.water,width:1.2}}],
      { ...PLOTLY_BASE, title:`${sh} — ${meta.shortname||par} [${meta.unit||''}]`, height:360,
        yaxis:{title:`${meta.shortname||par} [${meta.unit||''}]`,gridcolor:COL.grid} }, CFG);
    $('#g-status').textContent = `${sh} · ${par} · ${rows.length} readings (${meta.unit||''})`;
  }catch(e){ $('#g-status').innerHTML=`<span style="color:#b00">no ${par} at this gauge (${e.message})</span>`; }
}

// ---- helpers ------------------------------------------------------------
function daily(start, n){ const d0=new Date(start+'T00:00'), out=[]; for(let i=0;i<n;i++) out.push(new Date(d0.getTime()+i*864e5)); return out; }
function mean(a){ let s=0,n=0; for(const v of a){ if(v!=null&&isFinite(v)){s+=v;n++;} } return s/n; }
function toArr(a){ return a.map(v=> v==null?NaN:v); }
const nz = v => (v==null||!isFinite(v))?0:v;   // fluxes: missing → 0
const z = v => (v==null||!isFinite(v))?0:v;    // temp: missing → 0
function resample(dates, vals, freq, flux){
  const groups=new Map();
  dates.forEach((d,i)=>{ if(vals[i]==null||!isFinite(vals[i]))return;
    const k = freq==='YS'? d.getFullYear() : `${d.getFullYear()}-${d.getMonth()}`;
    if(!groups.has(k)) groups.set(k,{x:freq==='YS'?new Date(d.getFullYear(),0,1):new Date(d.getFullYear(),d.getMonth(),1),s:0,n:0});
    const g=groups.get(k); g.s+=vals[i]; g.n++; });
  const arr=[...groups.values()].sort((a,b)=>a.x-b.x);
  return [arr.map(g=>g.x), arr.map(g=> flux? g.s : g.s/g.n)];
}
