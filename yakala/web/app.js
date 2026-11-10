'use strict';

/* ================================================================== temel */
const TOKEN = document.querySelector('meta[name="token"]').content;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const PNAMES = { youtube: 'YouTube', twitter: 'X', tiktok: 'TikTok', instagram: 'Instagram', other: 'Diğer site' };
const LOGIN_HINT = 'Hesap çerezleri';

let settings = {};
let system = {};
let current = null;          // son analiz sonucu
let sel = {};                // sonuç kartındaki seçimler
let analyzeSeq = 0;
const usedUrls = new Set();     // pano önerisinde tekrar gösterilmesin

async function api(name, body = {}) {
  const r = await fetch('/api/' + name, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN },
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || 'İstek başarısız.');
  return j.data;
}
const thumbSrc = tok => tok ? `/thumb/${encodeURIComponent(tok)}?t=${encodeURIComponent(TOKEN)}` : '';
const hthumbSrc = f => f ? `/hthumb/${encodeURIComponent(f)}?t=${encodeURIComponent(TOKEN)}` : '';

/* küçük DOM kurucu: metinler her zaman textContent ile girer */
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function icon(id, cls = '') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  if (cls) svg.setAttribute('class', cls);
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#' + id);
  svg.append(use);
  return svg;
}
function img(src, cls = '', onFail) {
  if (!src) return null;
  const el = h('img', { src, class: cls, alt: '', loading: 'lazy', decoding: 'async' });
  el.addEventListener('error', () => { onFail ? onFail(el) : el.remove(); });
  return el;
}

/* ================================================================== biçimlendirme */
const nf1 = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 1 });
function bytes(n) {
  if (!n || n < 0) return '';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (n >= 100 || i === 0 ? Math.round(n).toLocaleString('tr-TR') : nf1.format(n)) + ' ' + u[i];
}
function dur(s) {
  if (s == null || isNaN(s)) return '';
  s = Math.round(s);
  const hh = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return (hh ? hh + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0');
}
function count(n) {
  if (n == null) return '';
  if (n >= 1e9) return nf1.format(n / 1e9) + ' Mr';
  if (n >= 1e6) return nf1.format(n / 1e6) + ' Mn';
  if (n >= 1e3) return nf1.format(n / 1e3) + ' B';
  return String(n);
}
function etaText(s) {
  if (s == null || !isFinite(s)) return '';
  if (s < 60) return `${Math.max(1, Math.round(s))} sn kaldı`;
  if (s < 3600) return `${Math.round(s / 60)} dk kaldı`;
  return `${Math.floor(s / 3600)} sa ${Math.round((s % 3600) / 60)} dk kaldı`;
}
const pct = p => '%' + Math.floor(p * 100);
function clock(ts) { return new Date(ts * 1000).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }); }
function dayLabel(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const t = d.getTime();
  if (t >= start) return 'Bugün';
  if (t >= start - 864e5) return 'Dün';
  if (t >= start - 6 * 864e5) return 'Bu hafta';
  if (d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()) return 'Bu ay';
  return d.toLocaleDateString('tr-TR', { month: 'long', year: 'numeric' });
}

/* ================================================================== bağlantı tanıma */
const URL_RE = /(?:https?:\/\/[^\s<>"'`]+)|(?:\b(?:www\.|m\.|vm\.|vt\.|mobile\.)?(?:youtube\.com|youtu\.be|x\.com|twitter\.com|tiktok\.com|instagram\.com)\/[^\s<>"'`]+)/gi;
function findUrls(text) {
  const out = [];
  for (const m of (text || '').matchAll(URL_RE)) {
    let u = m[0].replace(/[).,;!?'"\]]+$/, '');
    if (!/^https?:\/\//i.test(u)) u = 'https://' + u;
    if (!out.includes(u)) out.push(u);
  }
  return out;
}
function hostOf(u) { try { return new URL(u).hostname.toLowerCase(); } catch { return ''; } }
function detect(u) {
  const host = hostOf(u);
  const is = d => host === d || host.endsWith('.' + d);
  if (['youtube.com', 'youtu.be', 'youtube-nocookie.com'].some(is)) return 'youtube';
  if (['twitter.com', 'x.com', 'fxtwitter.com', 'vxtwitter.com', 'fixupx.com', 'fixvx.com'].some(is)) return 'twitter';
  if (is('tiktok.com')) return 'tiktok';
  if (['instagram.com', 'instagr.am', 'ddinstagram.com'].some(is)) return 'instagram';
  return 'other';
}
function kindOf(u) {
  let p;
  try { p = new URL(u); } catch { return 'Bağlantı'; }
  const path = p.pathname.toLowerCase(), q = p.search.toLowerCase();
  switch (detect(u)) {
    case 'youtube':
      if (path.includes('/shorts/')) return 'Shorts';
      if (q.includes('list=') && !q.includes('v=')) return 'Oynatma listesi';
      if (/^\/(@|channel\/|c\/)/.test(path)) return 'Kanal';
      return 'Video';
    case 'instagram':
      if (path.includes('/stories/highlights/') || path.startsWith('/s/')) return 'Öne çıkan';
      if (path.includes('/stories/')) return 'Hikâye';
      if (/\/reels?\//.test(path)) return 'Reels';
      if (/\/(p|tv)\//.test(path)) return 'Gönderi';
      return 'Profil';
    case 'tiktok':
      if (path.includes('/photo/')) return 'Fotoğraf';
      if (path.includes('/video/') || /^(vm|vt)\./.test(p.hostname) || path.startsWith('/t/')) return 'Video';
      return 'Profil';
    case 'twitter':
      return path.includes('/status/') ? 'Gönderi' : 'Profil';
    default:
      return 'Bağlantı';
  }
}

/* ================================================================== bildirimler */
function toast(msg, kind = 'info', action) {
  const ic = kind === 'ok' ? 'i-check' : kind === 'err' ? 'i-alert' : 'i-download';
  const el = h('div', { class: 'toast ' + kind }, icon(ic), h('span', { text: msg }),
    action ? h('button', { onclick: () => { action.fn(); close(); } , text: action.label }) : null);
  $('#toasts').append(el);
  let timer = setTimeout(close, kind === 'err' ? 7000 : 4200);
  function close() { clearTimeout(timer); el.classList.add('out'); setTimeout(() => el.remove(), 260); }
  while ($('#toasts').children.length > 4) $('#toasts').firstElementChild.remove();
}
let actx;
function chime() {
  if (!settings.sound) return;
  try {
    actx = actx || new AudioContext();
    const t = actx.currentTime;
    [[784, 0], [1174.7, 0.1]].forEach(([f, d]) => {
      const o = actx.createOscillator(), g = actx.createGain();
      o.type = 'sine'; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t + d);
      g.gain.exponentialRampToValueAtTime(0.16, t + d + 0.015);
      g.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.38);
      o.connect(g).connect(actx.destination);
      o.start(t + d); o.stop(t + d + 0.42);
    });
  } catch { /* ses yoksa sessiz geç */ }
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* yedek yol */ }
  const ta = h('textarea', { style: 'position:fixed;opacity:0' });
  ta.value = text; document.body.append(ta); ta.select();
  const ok = document.execCommand('copy'); ta.remove(); return ok;
}

/* ================================================================== görünümler */
function show(view) {
  $$('.rail-btn[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach(v => { v.hidden = v.id !== 'view-' + view; });
  $('.main').scrollTop = 0;
  if (view === 'history') loadHistory();
  if (view === 'settings') refreshSystem();
  if (view === 'home') setTimeout(() => $('#urlInput').focus(), 30);
}
$$('.rail-btn[data-view]').forEach(b => b.addEventListener('click', () => show(b.dataset.view)));

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  $('#themeBtn use').setAttribute('href', t === 'dark' ? '#i-sun' : '#i-moon');
  $('#themeBtn').setAttribute('aria-label', t === 'dark' ? 'Açık temaya geç' : 'Koyu temaya geç');
}
$('#themeBtn').addEventListener('click', () => saveSetting({ theme: settings.theme === 'dark' ? 'light' : 'dark' }));

/* ================================================================== yakalayıcı */
const input = $('#urlInput'), catcher = $('#catcher'), lens = $('#lens'), lensLabel = $('#lensLabel');

function autosize() {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 132) + 'px';
}
function setLens() {
  const urls = findUrls(input.value);
  let p = 'none';
  lensLabel.replaceChildren();
  if (urls.length > 1) {
    p = 'multi';
    lensLabel.append(`${urls.length} bağlantı`);
  } else if (urls.length === 1) {
    p = detect(urls[0]);
    lensLabel.append(PNAMES[p], ' ', h('span', { class: 'kind', text: kindOf(urls[0]) }));
  } else {
    lensLabel.append('Bağlantı');
  }
  if (catcher.dataset.platform !== p) {
    catcher.dataset.platform = p;
    catcher.classList.toggle('has-platform', p !== 'none');
    const id = p === 'none' ? 'i-link' : p === 'multi' ? 'i-download' : 'p-' + p;
    $('use', lens).setAttribute('href', '#' + id);
    lens.classList.remove('snap');
    void lens.offsetWidth;
    if (p !== 'none') lens.classList.add('snap');
  }
  return urls;
}
input.addEventListener('input', () => { autosize(); setLens(); if (input.value.trim()) $('#clipHint').hidden = true; });
input.addEventListener('paste', () => setTimeout(() => { autosize(); if (setLens().length) analyze(); }, 0));
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); analyze(); }
  if (e.key === 'Escape') { resetCatcher(); }
});
$('#goBtn').addEventListener('click', analyze);
$('#pasteBtn').addEventListener('click', pasteFromClipboard);

function resetCatcher(keepStage = false) {
  input.value = '';
  autosize(); setLens();
  if (!keepStage) setStage(null);
}
function setStage(node) {
  const stage = $('#stage');
  stage.replaceChildren();
  if (node) stage.append(node);
  $('#platformsIntro').hidden = !!node || !$('#queueSection').hidden;
}

async function pasteFromClipboard() {
  try {
    const { text, urls } = await api('clipboard');
    if (!urls.length) { toast('Panoda bir bağlantı yok. Önce bir bağlantı kopyala.', 'err'); return; }
    input.value = urls.map(u => u.url).join('\n');
    autosize(); setLens();
    hideClipHint(text);
    analyze();
  } catch (e) { toast(e.message, 'err'); }
}

async function analyze() {
  const urls = setLens();
  if (!urls.length) {
    input.focus();
    if (input.value.trim()) toast('Bu bir bağlantıya benzemiyor. https:// ile başlayan bir adres yapıştır.', 'err');
    return;
  }
  urls.forEach(u => usedUrls.add(u));
  $('#clipHint').hidden = true;
  if (urls.length > 1) { renderMulti(urls); return; }
  const seq = ++analyzeSeq;
  const url = urls[0];
  setStage(renderLoading(url));
  $('#goBtn').classList.add('busy');
  try {
    const r = await api('analyze', { url });
    if (seq !== analyzeSeq) return;
    current = r;
    setStage(renderResult(r));
  } catch (e) {
    if (seq !== analyzeSeq) return;
    setStage(renderProblem(e.message, url));
  } finally {
    if (seq === analyzeSeq) $('#goBtn').classList.remove('busy');
  }
}

/* ================================================================== sonuç kartları */
function renderLoading(url) {
  const p = detect(url);
  const notes = {
    youtube: 'YouTube videosu inceleniyor', twitter: 'Gönderi inceleniyor', tiktok: 'TikTok içeriği inceleniyor',
    instagram: 'Instagram içeriği inceleniyor; hikâye ve galeriler biraz sürebilir', other: 'Bağlantı inceleniyor',
  };
  return h('div', { class: 'card skeleton' },
    h('div', { class: 'result' },
      h('div', { class: 'media sk' }),
      h('div', {},
        h('div', { class: 'sk sk-line', style: 'width:30%' }),
        h('div', { class: 'sk sk-title' }),
        h('div', { class: 'sk sk-line', style: 'width:55%' }),
        h('div', { class: 'sk sk-line', style: 'width:90%;height:44px;margin-top:22px;border-radius:13px' }),
      )),
    h('div', { class: 'loading-note' }, h('span', { class: 'spinner' }), notes[p] + '…'));
}

function renderProblem(msg, url) {
  const needsLogin = msg.includes(LOGIN_HINT);
  const needsFf = msg.includes('FFmpeg');
  return h('div', { class: 'card problem' }, icon('i-alert'),
    h('div', {},
      h('h3', { text: 'Bu bağlantı açılamadı' }),
      h('p', { text: msg }),
      h('div', { class: 'btn-row' },
        h('button', { class: 'soft-btn', onclick: analyze }, icon('i-retry'), 'Tekrar dene'),
        needsLogin ? h('button', { class: 'soft-btn', onclick: () => openSettingsAt('cookies') }, 'Çerez ayarlarını aç') : null,
        needsFf ? h('button', { class: 'soft-btn', onclick: () => openSettingsAt('system') }, 'FFmpeg ayarlarını aç') : null,
        h('button', { class: 'text-btn', onclick: () => copyText(url).then(() => toast('Bağlantı kopyalandı.', 'ok')) }, icon('i-copy'), 'Bağlantıyı kopyala'),
      )));
}

function head(r, extra = []) {
  const media = h('div', { class: 'media' });
  const src = thumbSrc(r.thumb);
  if (src) {
    media.append(img(src, 'bg'), img(src, 'fg', el => { el.remove(); media.querySelector('.bg')?.remove(); media.append(h('div', { class: 'ph' }, icon('i-film'))); }));
  } else {
    media.append(h('div', { class: 'ph' }, icon(r.type === 'gallery' ? 'i-image' : 'i-film')));
  }
  if (r.duration) media.append(h('span', { class: 'dur', text: dur(r.duration) }));
  const sub = [];
  if (r.uploader) sub.push(h('span', { text: r.uploader }));
  for (const x of extra) if (x) sub.push(h('span', { text: x }));
  const info = h('div', { class: 'info' },
    h('div', { class: 'tagline' },
      h('span', { class: 'ptag p-' + r.platform }, icon('p-' + r.platform), r.platform_name),
      h('span', { class: 'kind', text: r.kind_name })),
    h('h2', { class: 'r-title', text: r.title, title: r.title }),
    h('div', { class: 'r-sub' }, sub));
  return { media, info };
}

function modeSwitch(options, value, onChange) {
  const wrap = h('div', { class: 'modes', role: 'tablist' });
  for (const [v, label, ic] of options) {
    wrap.append(h('button', {
      class: v === value ? 'on' : '', role: 'tab', 'aria-selected': String(v === value),
      onclick: () => onChange(v),
    }, icon(ic), label));
  }
  return wrap;
}
function pills(options, value, onChange) {
  const wrap = h('div', { class: 'pills' });
  for (const [v, label] of options) {
    wrap.append(h('button', { class: 'pill' + (String(v) === String(value) ? ' on' : ''), onclick: () => onChange(v), text: label }));
  }
  return wrap;
}
function field(label, ctrl) { return h('div', {}, h('div', { class: 'opt-label', text: label }), ctrl); }

const AUDIO_FORMATS = [['mp3', 'MP3'], ['m4a', 'M4A'], ['opus', 'OPUS'], ['flac', 'FLAC'], ['wav', 'WAV']];
const AUDIO_QUALS = [['320', '320 kbps'], ['256', '256'], ['192', '192'], ['128', '128'], ['best', 'Kaynak']];
const GENERIC_Q = [['best', 'En iyi'], ['2160', '4K'], ['1440', '1440p'], ['1080', '1080p'], ['720', '720p'], ['480', '480p'], ['360', '360p']];

function audioEstimate(seconds, fallback) {
  if (!seconds) return fallback || 0;
  const kbps = { flac: 900, wav: 1411 }[sel.audio_format] || (sel.audio_quality === 'best' ? 0 : +sel.audio_quality);
  return kbps ? kbps * 1000 / 8 * seconds : fallback;
}

function audioOptions(rerender) {
  const lossless = ['flac', 'wav'].includes(sel.audio_format);
  return h('div', { class: 'row-opts' },
    field('Ses biçimi', pills(AUDIO_FORMATS, sel.audio_format, v => { sel.audio_format = v; rerender(); })),
    lossless ? null : field('Kalite', pills(AUDIO_QUALS, sel.audio_quality, v => { sel.audio_quality = v; rerender(); })));
}

function defaultQuality(qualities) {
  if (!qualities.length) return 'best';
  const want = settings.video_quality;
  if (want === 'best') return qualities[0].res;
  const fit = qualities.find(q => q.res <= +want);
  return fit ? fit.res : qualities[qualities.length - 1].res;
}

function baseSel(r) {
  return {
    mode: r.type === 'video' && !r.has_video ? 'audio' : 'video',
    quality: r.type === 'video' ? defaultQuality(r.qualities || []) : settings.video_quality,
    container: settings.video_container,
    audio_format: settings.audio_format,
    audio_quality: settings.audio_quality,
    subtitles: !!(settings.subtitles && r.subtitles && r.subtitles.length),
    entries: new Set((r.entries || []).map(e => e.index)),
    items: new Set((r.items || []).map(i => i.index)),
  };
}

function renderResult(r) {
  sel = baseSel(r);
  const card = h('div', { class: 'card' });
  const draw = () => {
    const scroll = card.querySelector('.entries, .gallery')?.scrollTop;
    card.replaceChildren(...(r.type === 'gallery' ? galleryCard(r, draw) : r.type === 'playlist' ? playlistCard(r, draw) : videoCard(r, draw)));
    if (scroll) { const el = card.querySelector('.entries, .gallery'); if (el) el.scrollTop = scroll; }
  };
  draw();
  return card;
}

function videoCard(r, rerender) {
  const extras = [r.views != null ? count(r.views) + ' izlenme' : null, r.likes != null ? count(r.likes) + ' beğeni' : null, r.date || null];
  const { media, info } = head(r, extras);
  const opts = h('div', { class: 'opts' });
  if (r.has_video) {
    opts.append(modeSwitch([['video', 'Video', 'i-film'], ['audio', 'Sadece ses', 'i-music']], sel.mode, v => { sel.mode = v; rerender(); }));
  }
  let estimate = 0;
  if (sel.mode === 'video') {
    const qs = r.qualities || [];
    if (qs.length) {
      const grid = h('div', { class: 'qgrid' });
      for (const q of qs) {
        const on = String(q.res) === String(sel.quality);
        if (on) estimate = q.size;
        grid.append(h('button', { class: 'q' + (on ? ' on' : ''), onclick: () => { sel.quality = q.res; rerender(); } },
          q.res >= 2160 ? h('i', { class: 'tag4k', text: q.res >= 4320 ? '8K' : '4K' }) : null,
          h('b', {}, `${q.res}p`, q.fps >= 50 ? h('sup', { text: q.fps }) : null),
          h('span', { text: q.size ? '≈ ' + bytes(q.size) : 'boyut ?' })));
      }
      opts.append(field('Kalite', grid));
    }
    opts.append(h('div', { class: 'row-opts' },
      field('Biçim', pills([['mp4', 'MP4'], ['mkv', 'MKV']], sel.container, v => { sel.container = v; rerender(); })),
      r.subtitles && r.subtitles.length ? field('Altyazı', h('label', { class: 'check' },
        Object.assign(h('input', { type: 'checkbox', onchange: e => { sel.subtitles = e.target.checked; } }), { checked: sel.subtitles }),
        `Ekle (${r.subtitles.slice(0, 4).join(', ')}${r.subtitles.length > 4 ? '…' : ''})`)) : null));
  } else {
    opts.append(audioOptions(rerender));
    estimate = audioEstimate(r.duration, r.audio_size);
  }
  const note = estimate ? h('span', { class: 'dl-note' }, 'Tahmini boyut ', h('b', { text: '≈ ' + bytes(estimate) })) :
    h('span', { class: 'dl-note', text: r.is_live ? 'Canlı yayın, kayıt bitene kadar sürer.' : '' });
  opts.append(h('div', { class: 'dl-row' }, note,
    h('button', { class: 'dl-btn', onclick: e => startDownload(r, e.currentTarget) }, icon('i-download'),
      sel.mode === 'audio' ? 'Sesi indir' : 'Videoyu indir')));
  return [h('div', { class: 'result' }, media, h('div', {}, info, opts))];
}

function playlistCard(r, rerender) {
  const { media, info } = head(r, [`${r.count} video`]);
  const opts = h('div', { class: 'opts' },
    modeSwitch([['video', 'Video', 'i-film'], ['audio', 'Sadece ses', 'i-music']], sel.mode, v => { sel.mode = v; rerender(); }));
  if (sel.mode === 'video') {
    opts.append(h('div', { class: 'row-opts' },
      field('Kalite', pills(GENERIC_Q, String(sel.quality), v => { sel.quality = v; rerender(); })),
      field('Biçim', pills([['mp4', 'MP4'], ['mkv', 'MKV']], sel.container, v => { sel.container = v; rerender(); }))));
  } else {
    opts.append(audioOptions(rerender));
  }
  const list = h('div', { class: 'entries' });
  for (const e of r.entries) {
    const on = sel.entries.has(e.index);
    const cb = h('input', { type: 'checkbox', tabindex: '-1' });
    cb.checked = on;
    list.append(h('label', { class: 'entry' + (on ? '' : ' off'), onclick: ev => {
      ev.preventDefault();
      sel.entries.has(e.index) ? sel.entries.delete(e.index) : sel.entries.add(e.index);
      rerender();
    } },
      h('span', { class: 'check' }, cb),
      h('span', { class: 'n', text: e.index }),
      img(thumbSrc(e.thumb), '', el => el.replaceWith(h('span', { class: 'noimg' }))) || h('span', { class: 'noimg' }),
      h('span', { class: 't', text: e.title, title: e.title }),
      h('span', { class: 'd', text: dur(e.duration) })));
  }
  const n = sel.entries.size;
  return [
    h('div', { class: 'result' }, media, h('div', {}, info, opts)),
    h('div', { class: 'pick-head' },
      h('div', { class: 'opt-label', text: `${n} / ${r.entries.length} video seçili` }),
      h('div', { class: 'pick-tools' },
        h('button', { class: 'text-btn', onclick: () => { sel.entries = new Set(r.entries.map(e => e.index)); rerender(); }, text: 'Tümünü seç' }),
        h('button', { class: 'text-btn', onclick: () => { sel.entries.clear(); rerender(); }, text: 'Seçimi kaldır' }))),
    list,
    h('div', { class: 'dl-row' },
      h('span', { class: 'dl-note', text: 'Videolar listenin adını taşıyan bir klasöre kaydedilir.' }),
      h('button', { class: 'dl-btn', disabled: n === 0, onclick: e => startDownload(r, e.currentTarget) }, icon('i-download'),
        n === r.entries.length ? `${n} videonun tümünü indir` : `${n} videoyu indir`)),
  ];
}

function galleryCard(r, rerender) {
  const parts = [];
  if (r.images) parts.push(`${r.images} fotoğraf`);
  if (r.videos) parts.push(`${r.videos} video`);
  const { media, info } = head(r, [parts.join(', ')]);
  const grid = h('div', { class: 'gallery' });
  for (const it of r.items) {
    const on = sel.items.has(it.index);
    const tile = h('button', { class: 'tile' + (on ? ' on' : ''), 'aria-pressed': String(on), title: `${it.index}. ${it.kind === 'video' ? 'video' : 'fotoğraf'}`,
      onclick: () => { sel.items.has(it.index) ? sel.items.delete(it.index) : sel.items.add(it.index); rerender(); } });
    const im = img(thumbSrc(it.thumb), '', el => el.replaceWith(h('div', { class: 'ph' }, icon(it.kind === 'video' ? 'i-film' : 'i-image'))));
    tile.append(im || h('div', { class: 'ph' }, icon(it.kind === 'video' ? 'i-film' : 'i-image')));
    if (it.kind === 'video') tile.append(h('span', { class: 'vbadge' }, icon('i-play'), 'Video'));
    tile.append(h('span', { class: 'tick' }, icon('i-check')));
    grid.append(tile);
  }
  const n = sel.items.size;
  const single = r.items.length === 1;
  return [
    h('div', { class: 'result' }, media, h('div', {}, info,
      h('div', { class: 'opts' }, h('p', { class: 'dl-note', style: 'margin:0',
        text: 'Fotoğraflar orijinal çözünürlükte, videolar en iyi kalitede indirilir. İstemediklerinin seçimini kaldır.' })))),
    single ? null : h('div', { class: 'pick-head' },
      h('div', { class: 'opt-label', text: `${n} / ${r.items.length} medya seçili` + (r.truncated ? ' (ilk 400 öğe gösteriliyor)' : '') }),
      h('div', { class: 'pick-tools' },
        h('button', { class: 'text-btn', onclick: () => { sel.items = new Set(r.items.map(i => i.index)); rerender(); }, text: 'Tümünü seç' }),
        h('button', { class: 'text-btn', onclick: () => { sel.items.clear(); rerender(); }, text: 'Seçimi kaldır' }))),
    single ? null : grid,
    h('div', { class: 'dl-row' }, h('span'),
      h('button', { class: 'dl-btn', disabled: n === 0, onclick: e => startDownload(r, e.currentTarget) }, icon('i-download'),
        n === 1 ? 'Medyayı indir' : n === r.items.length ? `${n} medyanın tümünü indir` : `${n} medyayı indir`)),
  ];
}

function renderMulti(urls) {
  const list = h('ul', { class: 'multi-list' });
  for (const u of urls) {
    const p = detect(u);
    list.append(h('li', { class: 'p-' + p, dataset: { p } }, icon('p-' + p), h('span', { class: 'k', text: kindOf(u) }), h('span', { class: 'u', text: u, title: u })));
  }
  const go = async (mode, btn) => {
    btn.disabled = true;
    try {
      const jobs = await api('batch', { text: urls.join('\n'), mode });
      toast(`${jobs.length} indirme kuyruğa eklendi.`, 'ok');
      resetCatcher();
      poll(true);
    } catch (e) { toast(e.message, 'err'); btn.disabled = false; }
  };
  setStage(h('div', { class: 'card' },
    h('h2', { class: 'multi-title', text: `${urls.length} bağlantı bulundu` }),
    h('p', { class: 'lede', style: 'font-size:14px;margin-top:4px', text: `Her biri varsayılan ayarlarınla indirilir (video: ${settings.video_quality === 'best' ? 'en iyi kalite' : settings.video_quality + 'p'} ${settings.video_container.toUpperCase()}, ses: ${settings.audio_format.toUpperCase()}). Fotoğraflı gönderilerdeki tüm medya alınır.` }),
    list,
    h('div', { class: 'btn-row' },
      h('button', { class: 'dl-btn secondary', onclick: e => go('audio', e.currentTarget) }, icon('i-music'), 'Hepsini ses olarak indir'),
      h('button', { class: 'dl-btn', onclick: e => go('video', e.currentTarget) }, icon('i-download'), 'Hepsini indir'))));
}

async function startDownload(r, btn) {
  btn.disabled = true;
  const body = {
    aid: r.aid, url: r.url,
    mode: r.type === 'gallery' ? 'gallery' : sel.mode,
    quality: String(sel.quality), container: sel.container,
    audio_format: sel.audio_format, audio_quality: sel.audio_quality,
    subtitles: sel.subtitles,
  };
  if (r.type === 'playlist') body.entries = sel.entries.size === r.entries.length ? [] : [...sel.entries];
  if (r.type === 'gallery') body.items = sel.items.size === r.items.length ? [] : [...sel.items];
  try {
    await api('download', body);
    toast('Kuyruğa eklendi: ' + r.title.slice(0, 60), 'ok');
    resetCatcher();
    current = null;
    poll(true);
    input.focus();
  } catch (e) {
    toast(e.message, 'err');
    btn.disabled = false;
  }
}

/* ================================================================== kuyruk */
const jobEls = new Map();
const lastStatus = new Map();
let jobsCache = [];
let pollTimer = null;
let ffState = {}, updState = {};

async function poll(immediate) {
  clearTimeout(pollTimer);
  let active = false;
  try {
    const d = await api('jobs');
    jobsCache = d.jobs;
    renderJobs(d.jobs);
    ffState = d.ffmpeg; updState = d.update;
    renderSysProgress();
    active = d.jobs.some(j => j.status === 'running' || j.status === 'queued') || d.ffmpeg.running || d.update.running;
  } catch { /* sunucu kısa süreliğine meşgul olabilir */ }
  pollTimer = setTimeout(poll, document.hidden ? 3000 : active ? 450 : 2000);
}

function jobActions(j) {
  const b = (ic, label, fn, cls = '') => h('button', { class: 'icon-btn ' + cls, title: label, 'aria-label': label, onclick: fn }, icon(ic));
  const act = a => () => api('job', { id: j.id, action: a }).then(() => poll(true)).catch(e => toast(e.message, 'err'));
  const file = j.files && j.files[0];
  switch (j.status) {
    case 'running': return [b('i-pause', 'Duraklat', act('pause')), b('i-x', 'İptal et', act('cancel'), 'danger')];
    case 'queued': return [b('i-pause', 'Beklet', act('pause')), b('i-x', 'İptal et', act('cancel'), 'danger')];
    case 'paused': return [b('i-play', 'Devam et', act('resume')), b('i-x', 'İptal et', act('cancel'), 'danger')];
    case 'done': return [
      b('i-open', j.files.length > 1 ? 'İlk dosyayı aç' : 'Dosyayı aç', () => api('open', { path: file }).then(ok => ok || toast('Dosya bulunamadı; taşınmış olabilir.', 'err'))),
      b('i-folder', 'Klasörde göster', () => api('reveal', { path: file })),
      b('i-x', 'Listeden kaldır', act('remove')),
    ];
    default: return [b('i-retry', 'Tekrar dene', act('retry')), b('i-x', 'Listeden kaldır', act('remove'))];
  }
}

function jobInfo(j) {
  const parts = [];
  if (j.status === 'running') {
    if (j.progress > 0) parts.push(pct(j.progress));
    if (j.total_bytes && j.mode !== 'gallery') parts.push(`${bytes(j.done_bytes)} / ${bytes(j.total_bytes)}`);
    if (j.speed) parts.push(bytes(j.speed) + '/sn');
    if (j.eta != null && j.eta > 0) parts.push(etaText(j.eta));
  } else if (j.status === 'done') {
    parts.push(j.label);
    if (j.size) parts.push(bytes(j.size));
    if (j.files.length > 1) parts.push(`${j.files.length} dosya`);
  } else {
    parts.push(j.label);
  }
  return parts.filter(Boolean);
}

function stageText(j) {
  switch (j.status) {
    case 'queued': return 'Sırada';
    case 'paused': return 'Duraklatıldı';
    case 'canceled': return 'İptal edildi';
    case 'error': return 'İndirilemedi';
    case 'done': return 'Tamamlandı';
    default: {
      let s = j.stage || 'Hazırlanıyor';
      if (j.item_count > 1 && !s.includes('(')) s += ` (${j.item_index}/${j.item_count})`;
      return s;
    }
  }
}

function renderJobs(jobs) {
  const ul = $('#jobs');
  $('#queueSection').hidden = jobs.length === 0;
  $('#platformsIntro').hidden = jobs.length > 0 || $('#stage').children.length > 0;
  const ids = new Set(jobs.map(j => j.id));
  for (const [id, el] of jobEls) if (!ids.has(id)) { el.remove(); jobEls.delete(id); }
  let prev = null;
  for (const j of jobs) {
    let el = jobEls.get(j.id);
    if (!el) {
      el = $('#tpl-job').content.firstElementChild.cloneNode(true);
      jobEls.set(j.id, el);
    }
    const indet = j.status === 'running' && !(j.progress > 0);
    el.className = `job ${j.status} p-${j.platform}` + (indet ? ' indet' : '');
    const im = $('.job-thumb img', el);
    const src = thumbSrc(j.thumb);
    if (src && im.dataset.src !== src) { im.dataset.src = src; im.src = src; im.hidden = false; im.onerror = () => { im.hidden = true; }; }
    if (!src) im.hidden = true;
    $('.job-plat use', el).setAttribute('href', '#p-' + j.platform);
    const title = $('.job-title', el);
    if (title.textContent !== j.title) { title.textContent = j.title; title.title = j.title; }
    $('.job-stage', el).textContent = stageText(j);
    const info = $('.job-info', el);
    const infoParts = jobInfo(j);
    if (info.dataset.v !== infoParts.join('|')) {
      info.dataset.v = infoParts.join('|');
      info.replaceChildren(...infoParts.map(t => h('span', { text: t })));
    }
    info.classList.toggle('job-warn', !!j.warning && j.status === 'done');
    if (j.warning && j.status === 'done') info.title = j.warning;
    $('.bar i', el).style.width = (j.status === 'running' || j.status === 'paused' ? Math.max(j.progress * 100, 0) : 0) + '%';
    const err = $('.job-error', el);
    err.hidden = !(j.error || (j.warning && j.status === 'done'));
    err.textContent = j.error || j.warning || '';
    err.style.color = j.error ? '' : 'var(--muted)';
    const acts = $('.job-actions', el);
    if (acts.dataset.status !== j.status) { acts.dataset.status = j.status; acts.replaceChildren(...jobActions(j)); }
    // sıra
    if (prev ? prev.nextElementSibling !== el : ul.firstElementChild !== el) {
      prev ? prev.after(el) : ul.prepend(el);
    }
    prev = el;
    // durum geçişleri
    const before = lastStatus.get(j.id);
    if (before && before !== j.status) {
      if (j.status === 'done') {
        chime();
        toast('İndirildi: ' + j.title.slice(0, 60), 'ok', { label: 'Aç', fn: () => api('open', { path: j.files[0] }) });
      } else if (j.status === 'error') {
        toast(j.title.slice(0, 40) + ': ' + j.error, 'err');
      }
    }
    lastStatus.set(j.id, j.status);
  }
  const active = jobs.filter(j => j.status === 'running' || j.status === 'queued').length;
  const badge = $('#activeBadge');
  badge.hidden = !active; badge.textContent = active;
  const running = jobs.filter(j => j.status === 'running');
  const avg = running.length ? running.reduce((a, j) => a + j.progress, 0) / running.length : 0;
  document.title = active ? `${pct(avg)} (${active}) Yakala` : 'Yakala';
}
$('#clearBtn').addEventListener('click', () => api('clear').then(() => poll(true)));
$('#openFolderBtn').addEventListener('click', () => api('open_folder'));

/* ================================================================== geçmiş */
let historyItems = [];
let historyFilter = 'all';
async function loadHistory() {
  try { historyItems = await api('history'); } catch (e) { toast(e.message, 'err'); historyItems = []; }
  renderHistory();
}
function renderHistory() {
  const q = $('#historySearch').value.trim().toLocaleLowerCase('tr');
  const list = $('#historyList');
  const items = historyItems.filter(it =>
    (historyFilter === 'all' || it.platform === historyFilter) &&
    (!q || (it.title + ' ' + (it.uploader || '')).toLocaleLowerCase('tr').includes(q)));
  const total = historyItems.reduce((a, it) => a + (it.size || 0), 0);
  $('#historySummary').textContent = historyItems.length
    ? `${historyItems.length} indirme, toplam ${bytes(total)}.`
    : 'İndirdiğin her şey burada listelenecek.';
  list.replaceChildren();
  $('#historyClear').hidden = historyItems.length === 0;
  if (!items.length) {
    list.append(h('li', { class: 'empty' },
      h('b', { text: historyItems.length ? 'Eşleşen indirme yok' : 'Henüz bir şey indirmedin' }),
      historyItems.length ? 'Aramayı ya da filtreyi değiştir.' : 'İndir sekmesine bir bağlantı yapıştırarak başla.'));
    return;
  }
  let group = null;
  for (const it of items) {
    const g = dayLabel(it.date);
    if (g !== group) { group = g; list.append(h('li', { class: 'h-group', text: g })); }
    const file = (it.files || [])[0];
    const thumb = h('div', { class: 'h-thumb' });
    const im = img(hthumbSrc(it.thumb_file));
    if (im) thumb.append(im);
    thumb.append(icon('p-' + it.platform, 'h-plat'));
    const meta = [PNAMES[it.platform] || '', it.label, bytes(it.size), clock(it.date)].filter(Boolean);
    const b = (ic, label, fn, cls = '') => h('button', { class: 'icon-btn ' + cls, title: label, 'aria-label': label, onclick: fn }, icon(ic));
    list.append(h('li', { class: `h-item p-${it.platform}` + (it.exists ? '' : ' missing') }, thumb,
      h('div', { class: 'job-body' },
        h('b', { class: 'h-title', text: it.title, title: it.title }),
        h('div', { class: 'h-meta' }, meta.map(m => h('span', { text: m })),
          it.exists ? null : h('span', { class: 'h-missing', text: 'Dosya taşınmış ya da silinmiş' }))),
      h('div', { class: 'h-actions' },
        it.exists ? b('i-open', 'Dosyayı aç', () => api('open', { path: file })) : null,
        it.exists ? b('i-folder', 'Klasörde göster', () => api('reveal', { path: file })) : null,
        b('i-retry', 'Yeniden indir', () => { show('home'); input.value = it.url; autosize(); setLens(); analyze(); }),
        b('i-copy', 'Bağlantıyı kopyala', () => copyText(it.url).then(() => toast('Bağlantı kopyalandı.', 'ok'))),
        b('i-trash', 'Geçmişten sil', async () => { await api('history_remove', { id: it.id }); loadHistory(); }, 'danger'))));
  }
}
$('#historySearch').addEventListener('input', renderHistory);
$$('#historyFilter .chip').forEach(c => {
  c.dataset.p = c.dataset.f;
  c.addEventListener('click', () => {
    historyFilter = c.dataset.f;
    $$('#historyFilter .chip').forEach(x => x.classList.toggle('active', x === c));
    renderHistory();
  });
});
$('#historyClear').addEventListener('click', async () => {
  if (!confirm('Tüm geçmiş silinsin mi? İndirilen dosyalar silinmez.')) return;
  await api('history_clear');
  loadHistory();
  toast('Geçmiş temizlendi.', 'ok');
});

/* ================================================================== ayarlar */
async function saveSetting(changes) {
  try {
    settings = await api('settings', { changes });
    syncSettings();
  } catch (e) { toast(e.message, 'err'); }
}
function syncSettings() {
  applyTheme(settings.theme);
  $$('[data-s]').forEach(el => {
    const k = el.dataset.s, v = settings[k];
    if (el.classList.contains('seg')) $$('button', el).forEach(b => b.classList.toggle('on', b.dataset.v === String(v)));
    else if (el.type === 'checkbox') el.checked = !!v;
    else if (document.activeElement !== el) el.value = v ?? '';
  });
  $('#sDir').textContent = settings.download_dir;
  $('#sCookieFile').textContent = settings.cookies_file || 'Seçilmedi';
  $('#rowBrowser').hidden = settings.cookies_mode !== 'browser';
  $('#rowCookieFile').hidden = settings.cookies_mode !== 'file';
  $('#concVal').textContent = settings.concurrency;
}
$$('[data-s]').forEach(el => {
  const k = el.dataset.s;
  if (el.classList.contains('seg')) {
    $$('button', el).forEach(b => b.addEventListener('click', () => saveSetting({ [k]: b.dataset.v })));
  } else if (el.type === 'checkbox') {
    el.addEventListener('change', () => saveSetting({ [k]: el.checked }));
  } else {
    el.addEventListener('change', () => saveSetting({ [k]: el.value.trim() }));
  }
});
$('#concMinus').addEventListener('click', () => saveSetting({ concurrency: Math.max(1, settings.concurrency - 1) }));
$('#concPlus').addEventListener('click', () => saveSetting({ concurrency: Math.min(6, settings.concurrency + 1) }));
$('#sDirOpen').addEventListener('click', () => api('open_folder'));
$('#sDirPick').addEventListener('click', async e => {
  e.currentTarget.disabled = true;
  try {
    const p = await api('pick_folder');
    if (p) { await saveSetting({ download_dir: p }); toast('İndirme klasörü değiştirildi.', 'ok'); }
  } finally { e.currentTarget.disabled = false; }
});
$('#sCookiePick').addEventListener('click', async e => {
  e.currentTarget.disabled = true;
  try {
    const p = await api('pick_file');
    if (p) saveSetting({ cookies_file: p, cookies_mode: 'file' });
  } finally { e.currentTarget.disabled = false; }
});
$('#ffInstall').addEventListener('click', async () => {
  await api('install_ffmpeg');
  poll(true);
});
$('#engUpdate').addEventListener('click', async () => {
  await api('update_engines');
  poll(true);
});

function openSettingsAt(which) {
  show('settings');
  const target = which === 'cookies' ? $('#rowBrowser').closest('.set-group') : $('#sysFfmpeg').closest('.set-group');
  setTimeout(() => target.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
}

async function refreshSystem() {
  try { system = await api('system'); } catch { return; }
  renderSystem();
}
function renderSystem() {
  const ff = system.ffmpeg || {};
  const text = {
    full: 'Tam sürüm kurulu (ffmpeg ve ffprobe).',
    system: ff.ffprobe ? 'Bilgisayarındaki FFmpeg kullanılıyor.' : 'Bilgisayarındaki FFmpeg kullanılıyor; ffprobe eksik.',
    bundled: 'Temel sürüm kullanılıyor. Birleştirme ve ses dönüştürme çalışır; bazı X ve canlı yayın videolarının onarımı için tam sürüm önerilir.',
    none: 'Bulunamadı. Görüntü ile sesi birleştirmek ve MP3 üretmek için gerekli.',
  }[ff.source] || '';
  $('#sysFfmpeg').textContent = text;
  $('#ffInstall').hidden = ff.source === 'full' || (ff.source === 'system' && ff.ffprobe);
  $('#sysEngines').textContent = `yt-dlp ${system.ytdlp}, gallery-dl ${system.gallerydl}` +
    (system.deno ? '. YouTube imza çözücü hazır.' : '. Deno bulunamadı; bazı YouTube kaliteleri görünmeyebilir.');
  $('#appFoot').textContent = `Yakala ${window.APP_VERSION || ''}. Ayarlar ve geçmiş: ${system.app_dir}`;
}
let ffWasRunning = false;
function renderSysProgress() {
  const bar = $('#ffBar');
  if (ffState.running) {
    bar.hidden = false;
    $('i', bar).style.width = (ffState.progress * 100).toFixed(1) + '%';
    $('#ffInstall').disabled = true;
    $('#ffInstall').textContent = 'İndiriliyor ' + pct(ffState.progress);
    ffWasRunning = true;
  } else if (ffWasRunning) {
    ffWasRunning = false;
    bar.hidden = true;
    $('#ffInstall').disabled = false;
    $('#ffInstall').textContent = 'Tam sürümü kur';
    if (ffState.error) toast(ffState.error, 'err'); else { toast('FFmpeg kuruldu.', 'ok'); refreshSystem(); }
  }
  const up = $('#engUpdate');
  up.disabled = !!updState.running;
  $('#sysUpdate').textContent = updState.message || '';
}

/* ================================================================== pano önerisi */
let clipSeen = '';
let clipTimer = null;
function hideClipHint(text) { if (text != null) clipSeen = text; $('#clipHint').hidden = true; }
async function checkClipboard() {
  if (!settings.clipboard_watch || document.hidden || $('#view-home').hidden || input.value.trim()) return;
  try {
    const { text, urls } = await api('clipboard');
    const known = urls.filter(u => u.platform !== 'other');
    if (!known.length || text === clipSeen || known.every(u => usedUrls.has(u.url))) return;
    const u = known[0];
    const hint = $('#clipHint');
    hint.dataset.p = u.platform;
    $('use', $('.clip-hint-icon', hint)).setAttribute('href', '#p-' + u.platform);
    const t = $('#clipHintText');
    const what = known.length > 1 ? `${known.length} bağlantı` : `${u.platform_name} bağlantısı`;
    t.replaceChildren('Panoda ', h('b', { text: what }), ' var.');
    hint.hidden = false;
    hint.dataset.text = text;
  } catch { /* sessiz */ }
}
$('#clipHintUse').addEventListener('click', () => {
  const text = $('#clipHint').dataset.text || '';
  input.value = findUrls(text).join('\n');
  autosize(); setLens(); hideClipHint(text); analyze();
});
$('#clipHintClose').addEventListener('click', () => hideClipHint($('#clipHint').dataset.text || ''));
window.addEventListener('focus', checkClipboard);

/* ================================================================== sürükle bırak, kısayollar */
let dragDepth = 0;
window.addEventListener('dragenter', e => {
  if (![...e.dataTransfer.types].some(t => t === 'text/uri-list' || t === 'text/plain')) return;
  dragDepth++; $('#dropVeil').hidden = false;
});
window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('#dropVeil').hidden = true; });
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => {
  e.preventDefault();
  dragDepth = 0; $('#dropVeil').hidden = true;
  const text = e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain');
  const urls = findUrls(text);
  if (!urls.length) { toast('Bırakılan şeyde bağlantı bulunamadı.', 'err'); return; }
  show('home');
  input.value = urls.join('\n'); autosize(); setLens(); analyze();
});
document.addEventListener('keydown', e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
  if (!typing && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') { e.preventDefault(); show('home'); pasteFromClipboard(); }
  else if (!typing && (e.key === '/' || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l'))) { e.preventDefault(); show('home'); input.focus(); }
  else if (e.altKey && ['1', '2', '3'].includes(e.key)) { e.preventDefault(); show(['home', 'history', 'settings'][+e.key - 1]); }
});
document.addEventListener('visibilitychange', () => { if (!document.hidden) { poll(true); checkClipboard(); } });

/* ================================================================== başlangıç */
(async function boot() {
  try {
    const b = await api('bootstrap');
    settings = b.settings; system = b.system; window.APP_VERSION = b.version;
    syncSettings(); renderSystem();
  } catch (e) { toast('Başlatılamadı: ' + e.message, 'err'); }
  autosize(); setLens();
  input.focus();
  poll(true);
  checkClipboard();
  clipTimer = setInterval(checkClipboard, 2000);
})();
