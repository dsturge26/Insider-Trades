// Trump & Congress Trade Tracker — static dashboard.
// Loads /data/*.json (kept fresh by the GitHub Action) and renders everything client-side.
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const fmtUSD = n => n >= 1e6 ? '$' + (n / 1e6).toFixed(1) + 'M'
  : n >= 1e3 ? '$' + Math.round(n / 1e3) + 'K' : '$' + n;
const fmtDate = s => { const d = new Date(s); return isNaN(d) ? s : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const state = { trades: [], signals: null, tickers: null, meta: null };

async function getJSON(path) {
  try { const r = await fetch(path, { cache: 'no-store' }); if (!r.ok) throw 0; return await r.json(); }
  catch { return null; }
}

async function boot() {
  setupTabs();
  $('#dismiss').onclick = () => $('#disclaimer').remove();

  const [congress, signals, tickers, meta] = await Promise.all([
    getJSON('data/congress_trades.json'),
    getJSON('data/trump_signals.json'),
    getJSON('data/trump_tickers.json'),
    getJSON('data/last_updated.json'),
  ]);
  state.trades = (congress && congress.trades) || [];
  state.congressMeta = congress;
  state.signals = signals;
  state.tickers = tickers;
  state.meta = meta;

  // Sample data is historical, so default to "all data" to avoid an empty window.
  if (state.congressMeta && state.congressMeta.is_sample) $('#lookback').value = '100000';

  renderFreshness();
  renderSummary();
  renderSignals();
  renderTopBuys();
  renderTickers();
  renderTrades();

  $('#lookback').onchange = renderTopBuys;
  $('#search').oninput = renderTrades;
  $('#type-filter').onchange = renderTrades;
}

function setupTabs() {
  $$('.tab').forEach(t => t.onclick = () => {
    $$('.tab').forEach(x => x.classList.remove('active'));
    $$('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    $('#' + t.dataset.tab).classList.add('active');
  });
}

function renderFreshness() {
  const el = $('#freshness');
  const live = state.meta && state.meta.live;
  const when = (state.meta && state.meta.updated_at) || (state.congressMeta && state.congressMeta.last_updated);
  el.textContent = (live ? '● Live · ' : '○ Sample data · ') + 'updated ' + fmtDate(when);
  el.classList.toggle('live', !!live);
  el.title = live ? '' : (state.meta && state.meta.message) || 'Add an FMP_API_KEY secret to enable live updates.';
}

// ---------- Trump signals ----------
const flames = s => '🔥'.repeat(Math.max(1, Math.min(5, Math.round((s || 0) / 20))));

// Classified market signals (+ curated), weak noise hidden, strongest first.
function signalList() {
  return ((state.signals && state.signals.events) || [])
    .filter(e => e.curated || (e.classified && e.is_market && (e.strength || 0) >= 35))
    .sort((a, b) => (b.strength || 0) - (a.strength || 0)
      || String(b.date).localeCompare(String(a.date)));
}

// ---------- Summary (snapshot) ----------
function renderSummary() {
  const wrap = $('#summary-content');
  const events = signalList();
  if (!events.length) {
    wrap.innerHTML = '<div class="empty">No signals yet — the next data run will classify his latest posts.</div>';
    return;
  }
  const groups = { BUY: [], SELL: [], WATCH: [] };
  events.forEach(e => (groups[(e.direction || 'WATCH').toUpperCase()] || groups.WATCH).push(e));
  const meta = { BUY: ['buy', '🟢 Buy'], SELL: ['sell', '🔴 Sell'], WATCH: ['watch', '🟡 Watch'] };

  wrap.innerHTML = Object.keys(meta).map(dir => {
    const rows = groups[dir];
    if (!rows.length) return '';
    const [cls, label] = meta[dir];
    return `<div class="sumgroup">
      <div class="sumhead ${cls}">${label} <span class="muted">(${rows.length})</span></div>
      ${rows.map(e => {
        const ps = e.price_since;
        return `<div class="sumrow">
          <span class="sumtk">$${esc(e.primary_ticker || '—')}</span>
          <span class="sumstr" title="strength ${e.strength || 0}/100">${flames(e.strength)} ${e.strength || 0}</span>
          <span class="sumreason">${esc(e.reason || e.text || '')}</span>
          ${ps ? `<span class="since ${ps.pct >= 0 ? 'up' : 'down'}">${ps.pct >= 0 ? '+' : ''}${ps.pct}%</span>` : ''}
          ${e.url ? `<a class="sumsrc" href="${esc(e.url)}" target="_blank" rel="noopener">↗</a>` : ''}
        </div>`;
      }).join('')}
    </div>`;
  }).join('');
}

function renderSignals() {
  const wrap = $('#signals-list');
  $('#signals-howto').textContent = (state.signals && state.signals.how_to_read) || '';
  const events = signalList();
  if (!events.length) {
    wrap.innerHTML = '<div class="empty">No market signals yet — the next data run will classify his latest posts.</div>';
    return;
  }
  // Collapsed by default: just direction + ticker + strength. Tap to expand.
  wrap.innerHTML = events.map(e => {
    const dir = (e.direction || 'WATCH').toUpperCase();
    const others = (e.tickers || []).filter(t => t !== e.primary_ticker)
      .map(t => `<span class="tag">$${esc(t)}</span>`).join('');
    const ps = e.price_since;
    const psHtml = ps ? `<div class="since ${ps.pct >= 0 ? 'up' : 'down'}">$${esc(ps.ticker)} ${ps.pct >= 0 ? '+' : ''}${ps.pct}% since post</div>` : '';
    return `<details class="card dir-${dir.toLowerCase()}">
      <summary class="sighead">
        <span class="badge ${dir.toLowerCase()}">${dir}</span>
        ${e.primary_ticker ? `<span class="bigticker">$${esc(e.primary_ticker)}</span>` : ''}
        <span class="flames" title="strength ${e.strength || 0}/100">${flames(e.strength)} <span class="muted">${e.strength || 0}</span></span>
        <span class="chev">▸</span>
      </summary>
      <div class="cardbody">
        <div class="quote">“${esc(e.text)}”</div>
        ${e.reason ? `<div class="why">↳ ${esc(e.reason)}</div>` : ''}
        ${psHtml}
        ${e.market_reaction ? `<div class="react">📊 ${esc(e.market_reaction)}</div>` : ''}
        <div class="tagrow">
          <span class="when">${esc(e.platform || '')} · ${fmtDate(e.date)}</span>
          ${others}
          ${e.url ? `<a class="tag" href="${esc(e.url)}" target="_blank" rel="noopener">source ↗</a>` : ''}
        </div>
      </div>
    </details>`;
  }).join('');
}

// ---------- Top buys (the signal) ----------
const isBuy = t => /purchase|buy/i.test(t);
const isSell = t => /sale|sell/i.test(t);

function renderTopBuys() {
  const days = +$('#lookback').value;
  const cutoff = Date.now() - days * 86400000;
  $('#topbuys-window').textContent = days >= 100000 ? '(all data)' : `(last ${days} days)`;

  const agg = {};
  for (const t of state.trades) {
    if (new Date(t.date).getTime() < cutoff) continue;
    const k = t.ticker;
    if (!k) continue;
    const a = agg[k] || (agg[k] = { ticker: k, company: t.company, buyers: new Set(), buys: 0, sells: 0, net: 0 });
    if (isBuy(t.type)) { a.buys++; a.buyers.add(t.politician); a.net += t.amount_mid || 0; }
    else if (isSell(t.type)) { a.sells++; a.net -= t.amount_mid || 0; }
  }
  let list = Object.values(agg)
    .map(a => ({ ...a, nbuyers: a.buyers.size, score: a.buyers.size * 2 + a.buys + Math.log10((a.net > 0 ? a.net : 1)) }))
    .filter(a => a.buys > 0)
    .sort((x, y) => y.score - x.score)
    .slice(0, 15);

  const wrap = $('#topbuys-list');
  if (!list.length) { wrap.innerHTML = '<div class="empty">No buys in this window. Try a longer lookback or enable live data.</div>'; return; }
  const max = list[0].score;
  wrap.innerHTML = list.map((a, i) => `
    <div class="rank">
      <div class="num">${i + 1}</div>
      <div style="min-width:120px">
        <div class="tk">$${esc(a.ticker)}</div>
        <div class="meta">${esc((a.company || '').slice(0, 28))}</div>
      </div>
      <div class="bar"><span style="width:${Math.round(a.score / max * 100)}%"></span></div>
      <div class="stat">
        <div><b>${a.nbuyers}</b> buyer${a.nbuyers !== 1 ? 's' : ''}</div>
        <div class="meta">${a.buys}B / ${a.sells}S · ${a.net >= 0 ? '+' : '-'}${fmtUSD(Math.abs(a.net))}</div>
      </div>
    </div>`).join('');
}

// ---------- Trump tickers + sparklines ----------
function sparkline(prices) {
  if (!prices || prices.length < 2) return '<div class="muted">price data populates after the Action runs</div>';
  const vals = prices.map(p => p.close);
  const min = Math.min(...vals), max = Math.max(...vals), W = 280, H = 48;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * W).toFixed(1)},${(H - (v - min) / ((max - min) || 1) * H).toFixed(1)}`).join(' ');
  const up = vals[vals.length - 1] >= vals[0];
  const first = vals[0], last = vals[vals.length - 1], chg = ((last - first) / first * 100);
  return `<div class="price">$${last.toFixed(2)} <span class="chg ${up ? 'up' : 'down'}">${chg >= 0 ? '+' : ''}${chg.toFixed(1)}%</span></div>
    <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <polyline fill="none" stroke="${up ? '#27c281' : '#ef5b6b'}" stroke-width="2" points="${pts}"/>
    </svg>`;
}
function renderTickers() {
  const wrap = $('#tickers-list');
  const list = (state.tickers && state.tickers.tickers) || [];
  wrap.innerHTML = list.map(t => `
    <div class="card">
      <div class="quote">$${esc(t.ticker)} <span class="muted" style="font-weight:400">${esc(t.company)}</span></div>
      ${sparkline(t.prices)}
      <div class="muted" style="margin-top:.4rem">${esc(t.why || '')}</div>
    </div>`).join('');
}

// ---------- All trades table ----------
function renderTrades() {
  const q = $('#search').value.trim().toLowerCase();
  const tf = $('#type-filter').value;
  const rows = state.trades.filter(t => {
    if (tf === 'Purchase' && !isBuy(t.type)) return false;
    if (tf === 'Sale' && !isSell(t.type)) return false;
    if (!q) return true;
    return (t.ticker + ' ' + t.politician + ' ' + t.company).toLowerCase().includes(q);
  }).slice(0, 500);

  $('#trades-table tbody').innerHTML = rows.map(t => {
    const buy = isBuy(t.type), sell = isSell(t.type);
    return `<tr>
      <td>${fmtDate(t.date)}</td>
      <td>${esc(t.politician)}</td>
      <td><b>$${esc(t.ticker)}</b></td>
      <td><span class="pill ${buy ? 'buy' : sell ? 'sell' : ''}">${esc(t.type)}</span></td>
      <td>${esc(t.amount || '')}</td>
      <td>${t.disclosure_url ? `<a href="${esc(t.disclosure_url)}" target="_blank" rel="noopener">filing ↗</a>` : ''}</td>
    </tr>`;
  }).join('');
  $('#trades-count').textContent = `Showing ${rows.length} of ${state.trades.length} disclosures${state.congressMeta && state.congressMeta.is_sample ? ' · sample data — enable live updates in setup' : ''}`;
}

boot();
