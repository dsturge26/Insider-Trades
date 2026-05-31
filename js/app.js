// Signal Tracker — one unified feed across all sources.
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const fmtUSD = n => n >= 1e6 ? '$' + (n / 1e6).toFixed(1) + 'M'
  : n >= 1e3 ? '$' + Math.round(n / 1e3) + 'K' : '$' + n;
const fmtDate = s => { const d = new Date(s); return isNaN(d) ? s : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const flames = s => '🔥'.repeat(Math.max(1, Math.min(5, Math.round((s || 0) / 20))));

// Source registry: label + emoji. New sources just add a row here.
const SOURCES = {
  Trump: '🚨', News: '📰', Contract: '📑', Insider: '🏦', Congress: '🏛️', Buzz: '🔥',
};
const isBuy = t => /purchase|buy/i.test(t || '');
const isSell = t => /sale|sell/i.test(t || '');

const state = { filter: 'All', sort: 'strength', signals: [] };

async function getJSON(p) {
  try { const r = await fetch(p, { cache: 'no-store' }); if (!r.ok) throw 0; return await r.json(); }
  catch { return null; }
}

async function boot() {
  setupTabs();
  const dis = $('#dismiss'); if (dis) dis.onclick = () => $('#disclaimer').remove();

  const [congress, trump, tickers, meta, insiders, wsb] = await Promise.all([
    getJSON('data/congress_trades.json'),
    getJSON('data/trump_signals.json'),
    getJSON('data/trump_tickers.json'),
    getJSON('data/last_updated.json'),
    getJSON('data/insider_signals.json'),
    getJSON('data/wsb_signals.json'),
  ]);
  state.tickers = tickers;
  state.meta = meta;
  state.signals = collectSignals({ congress, trump, insiders, wsb });

  renderFreshness();
  renderChips();
  renderFeed();
  renderTickers();

  $('#feed-sort').onchange = () => { state.sort = $('#feed-sort').value; renderFeed(); };
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
  const when = (state.meta && state.meta.updated_at);
  el.textContent = (state.meta && state.meta.live ? '● Live · ' : '○ ') + 'updated ' + fmtDate(when);
  el.classList.toggle('live', !!(state.meta && state.meta.live));
}

// ---------- Normalize every source into one shape ----------
// { source, ticker, direction, strength, reason, date, url, text?, price_since?, explicit? }
function collectSignals({ congress, trump, insiders, wsb }) {
  const out = [];

  // Trump posts / news / contracts (already classified, share one file)
  ((trump && trump.events) || []).forEach(e => {
    if (!(e.curated || (e.classified && e.is_market))) return;
    if (!e.curated && (e.strength || 0) < 35) return; // hide weak noise
    const src = /contract/i.test(e.platform) ? 'Contract' : /news/i.test(e.platform) ? 'News' : 'Trump';
    out.push({
      source: src, ticker: e.primary_ticker, direction: (e.direction || 'WATCH').toUpperCase(),
      strength: e.strength || 0, reason: e.reason || '', date: e.date, url: e.url,
      text: e.text, price_since: e.price_since, explicit: e.explicit,
    });
  });

  // Corporate insider buys
  ((insiders && insiders.signals) || []).forEach(s => out.push({
    source: 'Insider', ticker: s.ticker, direction: 'BUY', strength: s.strength || 0,
    reason: s.reason || '', date: s.date, url: s.url,
  }));

  // Congress: aggregate buys per ticker (last ~year) into one signal each
  const cutoff = Date.now() - 365 * 86400000;
  const agg = {};
  ((congress && congress.trades) || []).forEach(t => {
    if (!t.ticker || new Date(t.date).getTime() < cutoff || !isBuy(t.type)) return;
    const a = agg[t.ticker] || (agg[t.ticker] = { buyers: new Set(), buys: 0, date: t.date, url: t.disclosure_url });
    a.buyers.add(t.politician); a.buys++;
    if (t.date > a.date) { a.date = t.date; a.url = t.disclosure_url; }
  });
  Object.entries(agg).forEach(([ticker, a]) => {
    const n = a.buyers.size;
    out.push({
      source: 'Congress', ticker, direction: 'BUY',
      strength: Math.min(100, 35 + n * 12 + a.buys * 2),
      reason: `${n} member${n !== 1 ? 's' : ''} buying (${a.buys} trade${a.buys !== 1 ? 's' : ''})`,
      date: a.date, url: a.url,
    });
  });

  // Reddit / WSB buzz (attention, not a buy/sell call)
  ((wsb && wsb.signals) || []).forEach(s => {
    const chg = s.change_pct;
    out.push({
      source: 'Buzz', ticker: s.ticker, direction: 'WATCH',
      strength: Math.max(15, 85 - (s.rank || 25) * 3),
      reason: `${s.mentions} WSB mentions${chg != null ? ` (${chg >= 0 ? '+' : ''}${chg}% /24h)` : ''}`,
      date: state.metaWsb || s.date || new Date().toISOString(),
      url: 'https://apewisdom.io/stocks/' + encodeURIComponent(s.ticker || ''),
    });
  });

  return out.filter(s => s.ticker);
}

// ---------- Filter chips ----------
function renderChips() {
  const counts = { All: state.signals.length };
  state.signals.forEach(s => { counts[s.source] = (counts[s.source] || 0) + 1; });
  const order = ['All', ...Object.keys(SOURCES).filter(k => counts[k])];
  $('#source-chips').innerHTML = order.map(k => {
    const label = k === 'All' ? 'All' : `${SOURCES[k]} ${k}`;
    return `<button class="chip ${state.filter === k ? 'active' : ''}" data-src="${k}">${label} <span class="muted">${counts[k] || 0}</span></button>`;
  }).join('');
  $$('#source-chips .chip').forEach(c => c.onclick = () => {
    state.filter = c.dataset.src; renderChips(); renderFeed();
  });
}

// ---------- The feed ----------
function renderFeed() {
  let rows = state.signals.filter(s => state.filter === 'All' || s.source === state.filter);
  rows.sort(state.sort === 'recent'
    ? (a, b) => String(b.date).localeCompare(String(a.date)) || (b.strength - a.strength)
    : (a, b) => (b.strength - a.strength) || String(b.date).localeCompare(String(a.date)));
  rows = rows.slice(0, 150);

  $('#feed-count').textContent = `${rows.length} signal${rows.length !== 1 ? 's' : ''}`;
  const wrap = $('#feed-list');
  if (!rows.length) { wrap.innerHTML = '<div class="empty">No signals here yet — the data job populates these.</div>'; return; }

  wrap.innerHTML = rows.map(s => {
    const dir = (s.direction || 'WATCH').toLowerCase();
    const ps = s.price_since;
    return `<details class="card dir-${dir}">
      <summary class="sighead">
        <span class="srctag">${SOURCES[s.source] || ''} ${esc(s.source)}</span>
        <span class="bigticker">$${esc(s.ticker)}</span>
        <span class="badge ${dir}">${esc((s.direction || 'WATCH').toUpperCase())}</span>
        ${s.explicit ? '<span class="star" title="explicit single-company call">⭐</span>' : ''}
        <span class="flames" title="strength ${s.strength}/100">${flames(s.strength)} <span class="muted">${s.strength}</span></span>
        ${ps ? `<span class="since ${ps.pct >= 0 ? 'up' : 'down'}">${ps.pct >= 0 ? '+' : ''}${ps.pct}%</span>` : ''}
        <span class="chev">▸</span>
      </summary>
      <div class="cardbody">
        ${s.reason ? `<div class="why">↳ ${esc(s.reason)}</div>` : ''}
        ${s.text ? `<div class="quote">“${esc(s.text)}”</div>` : ''}
        ${ps ? `<div class="since ${ps.pct >= 0 ? 'up' : 'down'}">$${esc(ps.ticker)} ${ps.pct >= 0 ? '+' : ''}${ps.pct}% since signal</div>` : ''}
        <div class="tagrow">
          <span class="when">${esc(s.source)} · ${fmtDate(s.date)}</span>
          ${s.url ? `<a class="tag" href="${esc(s.url)}" target="_blank" rel="noopener">source ↗</a>` : ''}
        </div>
      </div>
    </details>`;
  }).join('');
}

// ---------- Prices ----------
function sparkline(prices) {
  if (!prices || prices.length < 2) return '<div class="muted">price data populates after the data job runs</div>';
  const vals = prices.map(p => p.close);
  const min = Math.min(...vals), max = Math.max(...vals), W = 280, H = 48;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * W).toFixed(1)},${(H - (v - min) / ((max - min) || 1) * H).toFixed(1)}`).join(' ');
  const up = vals[vals.length - 1] >= vals[0];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <polyline fill="none" stroke="${up ? '#27c281' : '#ef5b6b'}" stroke-width="2" points="${pts}"/></svg>`;
}
function renderTickers() {
  const wrap = $('#tickers-list');
  const list = (state.tickers && state.tickers.tickers) || [];
  const asOf = (state.tickers && state.tickers.last_updated) ? new Date(state.tickers.last_updated) : null;
  wrap.innerHTML = list.map(t => {
    const live = t.last, up = (t.day_pct ?? 0) >= 0;
    const head = live != null
      ? `<div class="price">$${live.toFixed(2)}${t.day_pct != null ? ` <span class="chg ${up ? 'up' : 'down'}">${up ? '+' : ''}${t.day_pct}% today</span>` : ''}</div>` : '';
    return `<div class="card">
      <div class="quote">$${esc(t.ticker)} <span class="muted" style="font-weight:400">${esc(t.company)}</span></div>
      ${head}${sparkline(t.prices)}
      <div class="muted" style="font-size:.75rem;margin-top:.2rem">${asOf ? 'as of ' + asOf.toLocaleString() + ' · 3-mo trend' : ''}</div>
      <div class="muted" style="margin-top:.4rem">${esc(t.why || '')}</div>
    </div>`;
  }).join('');
}

boot();
