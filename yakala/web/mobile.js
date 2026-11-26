'use strict';
const $ = s => document.querySelector(s);
const PN = { youtube: 'YouTube', twitter: 'X', tiktok: 'TikTok', instagram: 'Instagram', other: 'Diğer' };
let items = [];
let filter = 'all';
let queueTimer = null;

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}
const nf = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 1 });
function bytes(n) {
  if (!n) return '';
  const u = ['B', 'KB', 'MB', 'GB']; let i = 0;
  while (n >= 1024 && i < 3) { n /= 1024; i++; }
  return (n >= 100 || i === 0 ? Math.round(n) : nf.format(n)) + ' ' + u[i];
}
function dayLabel(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d >= start) return 'Bugün';
  if (d >= start - 864e5) return 'Dün';
  if (d >= start - 6 * 864e5) return 'Bu hafta';
  return d.toLocaleDateString('tr-TR', { month: 'long', year: 'numeric' });
}
function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast' + (err ? ' err' : ''); t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}
async function get(path) {
  const r = await fetch(path, { credentials: 'same-origin' });
  if (r.status === 401) { location.reload(); throw new Error('Erişim anahtarı geçersiz.'); }
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || 'Hata');
  return j;
}
const mainKind = it => {
  const kinds = it.files.map(f => f.kind);
  return kinds.includes('video') ? 'video' : kinds.includes('audio') ? 'audio' : kinds.includes('image') ? 'image' : 'file';
};
const KIND_TR = { video: 'Video', audio: 'Ses', image: 'Foto', file: 'Dosya' };

async function load() {
  $('#refreshBtn').classList.add('busy');
  try {
    const j = await get('/api/items');
    items = j.data;
    $('#pcName').textContent = j.pc ? `${j.pc} bilgisayarı` : 'Bilgisayarın';
    $('#sendBox').hidden = !j.allow_send;
    render();
  } catch (e) { toast(e.message, true); }
  finally { $('#refreshBtn').classList.remove('busy'); }
  pollQueue();
}

function render() {
  const q = $('#search').value.trim().toLocaleLowerCase('tr');
  const list = $('#items');
  list.replaceChildren();
  const shown = items.filter(it => (filter === 'all' || mainKind(it) === filter) &&
    (!q || ((it.title || '') + ' ' + (it.uploader || '')).toLocaleLowerCase('tr').includes(q)));
  $('#libTitle').textContent = items.length ? `İndirdiklerin (${items.length})` : 'İndirdiklerin';
  if (!shown.length) {
    list.append(h('li', { class: 'empty' }, h('b', { text: items.length ? 'Eşleşen yok' : 'Henüz bir şey yok' }),
      items.length ? 'Aramayı ya da filtreyi değiştir.' : 'Bilgisayarda indirdiklerin burada görünecek.'));
    return;
  }
  let day = null;
  for (const it of shown) {
    const d = dayLabel(it.date);
    if (d !== day) { day = d; list.append(h('li', { class: 'day', text: d })); }
    const k = mainKind(it);
    const thumb = h('span', { class: 'thumb' });
    if (it.thumb) {
      const im = h('img', { src: `/t/${it.id}`, alt: '', loading: 'lazy' });
      im.addEventListener('error', () => im.remove());
      thumb.append(im);
    }
    thumb.append(h('span', { class: 'kind', text: KIND_TR[k] }));
    const sub = [PN[it.platform] || '', it.label || '', bytes(it.size)].filter(Boolean);
    list.append(h('li', {}, h('button', { class: 'item', onclick: () => open(it) }, thumb,
      h('span', {}, h('b', { text: it.title || 'Başlıksız' }), h('span', { class: 'sub' }, sub.map(t => h('i', { text: t })))))));
  }
}

function open(it) {
  const player = $('#player');
  player.replaceChildren();
  const first = it.files.find(f => ['video', 'audio', 'image'].includes(f.kind));
  if (first) {
    const src = `/f/${it.id}/${first.i}`;
    if (first.kind === 'video') player.append(h('video', { src, controls: true, playsinline: true, preload: 'metadata' }));
    else if (first.kind === 'audio') {
      if (it.thumb) player.append(h('img', { src: `/t/${it.id}`, alt: '' }));
      player.append(h('audio', { src, controls: true, preload: 'metadata' }));
    } else player.append(h('img', { src, alt: '' }));
  }
  $('#sheetTitle').textContent = it.title || 'Başlıksız';
  $('#sheetMeta').replaceChildren(...[PN[it.platform], it.uploader, it.label, bytes(it.size)].filter(Boolean).map(t => h('i', { text: t })));
  const files = $('#sheetFiles');
  files.replaceChildren();
  for (const f of it.files) {
    const playable = ['video', 'audio', 'image'].includes(f.kind) && f !== first;
    files.append(h('li', {},
      h('span', { class: 'fname', text: f.name }),
      h('span', { class: 'fsize', text: bytes(f.size) }),
      playable ? h('a', { class: 'play', href: `/f/${it.id}/${f.i}`, target: '_blank', rel: 'noopener', text: 'Aç' }) : null,
      h('a', { class: 'dl', href: `/f/${it.id}/${f.i}?dl=1`, download: f.name, text: 'İndir' })));
  }
  $('#sheet').hidden = false;
  document.body.style.overflow = 'hidden';
}
function closeSheet() {
  $('#player').replaceChildren();   // oynatmayı durdur
  $('#sheet').hidden = true;
  document.body.style.overflow = '';
}

async function pollQueue() {
  clearTimeout(queueTimer);
  let active = false;
  try {
    const j = await get('/api/queue');
    const live = j.data.filter(x => x.status === 'running' || x.status === 'queued');
    active = live.length > 0;
    $('#queueBox').hidden = !active;
    const ul = $('#queueList');
    ul.replaceChildren(...live.map(x => h('li', {},
      h('div', { class: 'q-title', text: x.title }),
      h('div', { class: 'q-stage', text: x.status === 'queued' ? 'Sırada' : `${x.stage}  %${Math.floor(x.progress * 100)}` }),
      h('div', { class: 'bar' }, Object.assign(h('i'), { style: `width:${Math.round(x.progress * 100)}%` })))));
    if (pollQueue.wasActive && !active) load();
    pollQueue.wasActive = active;
  } catch { /* bilgisayar kapalı olabilir */ }
  queueTimer = setTimeout(pollQueue, document.hidden ? 15000 : active ? 1500 : 6000);
}

async function send() {
  const text = $('#sendText').value.trim();
  if (!text) { $('#sendText').focus(); return; }
  const btn = $('#sendBtn');
  btn.disabled = true;
  try {
    const r = await fetch('/api/send', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Yakala': '1' },
      body: JSON.stringify({ text, mode: document.querySelector('#sendMode .on').dataset.v }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    toast(j.data > 1 ? `${j.data} bağlantı bilgisayarda kuyruğa eklendi.` : 'Bilgisayarda indirme başladı.');
    $('#sendText').value = '';
    pollQueue();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
}

$('#refreshBtn').addEventListener('click', load);
$('#search').addEventListener('input', render);
$('#chips').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  filter = b.dataset.f;
  document.querySelectorAll('#chips button').forEach(x => x.classList.toggle('on', x === b));
  render();
});
$('#sendMode').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#sendMode button').forEach(x => x.classList.toggle('on', x === b));
});
$('#sendBtn').addEventListener('click', send);
$('#sheetBg').addEventListener('click', closeSheet);
$('#sheetClose').addEventListener('click', closeSheet);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
load();
