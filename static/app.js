const { createApp, reactive, computed, watch, onMounted } = Vue;

/* ------------------------------------------------------------------ icons (lucide paths) */
const ICONS = {
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  shieldCheck: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  shieldX: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m14.5 9.5-5 5"/><path d="m9.5 9.5 5 5"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  minus: '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>',
  ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
  zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
  home: '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
  play: '<circle cx="12" cy="12" r="10"/><path d="m10 8 6 4-6 4z"/>',
  list: '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>',
  server: '<rect width="20" height="8" x="2" y="2" rx="2"/><rect width="20" height="8" x="2" y="14" rx="2"/><path d="M6 6h.01"/><path d="M6 18h.01"/>',
  key: '<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/><path d="m21 2-9.6 9.6"/><circle cx="7.5" cy="15.5" r="5.5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  monitor: '<rect width="20" height="14" x="2" y="3" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  edit: '<path d="M21.17 6.81a1 1 0 0 0-3.98-3.98L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  eye: '<path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.53 13.53 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><path d="m2 2 20 20"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/>',
  plug: '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  arrowRight: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  star: '<path d="M11.53 2.3a.53.53 0 0 1 .94 0l2.31 4.68a2.12 2.12 0 0 0 1.6 1.16l5.16.76a.53.53 0 0 1 .3.9l-3.74 3.63a2.12 2.12 0 0 0-.61 1.88l.88 5.14a.53.53 0 0 1-.77.56l-4.62-2.43a2.12 2.12 0 0 0-1.97 0L6.4 21.01a.53.53 0 0 1-.77-.56l.88-5.13a2.12 2.12 0 0 0-.61-1.88L2.16 9.8a.53.53 0 0 1 .3-.9l5.16-.76a2.12 2.12 0 0 0 1.6-1.16z"/>',
  dollar: '<path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
  activity: '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
  flask: '<path d="M14 2v6a2 2 0 0 0 .245.96l5.51 10.08A2 2 0 0 1 18 22H6a2 2 0 0 1-1.755-2.96l5.51-10.08A2 2 0 0 0 10 8V2"/><path d="M6.453 15h11.094"/><path d="M8.5 2h7"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
};

const UiIcon = {
  props: { name: String, size: { type: [Number, String], default: 16 }, stroke: { type: [Number, String], default: 2 } },
  computed: { body() { return ICONS[this.name] || ''; } },
  template: `<svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    :stroke-width="stroke" stroke-linecap="round" stroke-linejoin="round" v-html="body" style="flex-shrink:0"></svg>`,
};

/* ------------------------------------------------------------------ verdict vocabulary */
const VERDICTS = {
  pass: { label: '通过', icon: 'shieldCheck', desc: '官方成功校验签名，确认是真 Claude 生成' },
  forged: { label: '掺假', icon: 'shieldX', desc: '官方拒绝了签名，thinking 块是伪造或被篡改的' },
  suspicious: { label: '可疑', icon: 'alert', desc: '签名真实，但模型被替换，或上下文被中转站改动' },
  undetectable: { label: '无法检测', icon: 'minus', desc: '没有 thinking / 没有签名 / 非原生格式' },
  invalid: { label: '检测无效', icon: 'ban', desc: '对照实验失败，本次结论不可信' },
  error: { label: '出错', icon: 'zap', desc: '网络、Key 失效、额度不足等请求失败' },
};
const STATUS = { queued: '排队中', minting: '中转站铸造', replaying: '官方回放', control: '阴性对照' };

const VerdictBadge = {
  props: { v: String, status: String, size: String },
  computed: {
    running() { return this.status && this.status !== 'done'; },
    cls() { return this.running ? 'v-running' : this.v ? 'v-' + this.v : 'v-none'; },
    label() { return this.running ? (STATUS[this.status] || '进行中') : (VERDICTS[this.v]?.label || '—'); },
  },
  template: `<span class="badge" :class="cls" :style="size==='lg' ? 'height:32px;font-size:14px;padding:0 13px 0 11px' : ''">
    <span v-if="running" class="spinner" style="width:11px;height:11px"></span><span v-else class="dot"></span>{{ label }}</span>`,
};

/* ------------------------------------------------------------------ helpers */
async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = msg.map(d => d.msg).join('；');
    throw new Error(msg || `请求失败 (${res.status})`);
  }
  return data;
}

function storageGet(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }

const pad = n => String(n).padStart(2, '0');
function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function relTime(ts) {
  if (!ts) return '从未检测';
  const s = Date.now() / 1000 - ts;
  if (s < 60) return '刚刚';
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} 天前`;
  return fmtTime(ts).slice(0, 10);
}
function money(x) {
  x = x || 0;
  if (x === 0) return '$0';
  if (x < 0.01) return '$' + x.toFixed(4);
  return '$' + x.toFixed(x < 1 ? 3 : 2);
}
function host(url) { try { return new URL(url).host; } catch { return url; } }
const AVATAR_COLORS = ['#c9643f', '#2f6fd6', '#1f8a5b', '#8a52c9', '#c2458a', '#0f8b8d', '#b07a12', '#5867dd', '#d0543f', '#3f8f3a', '#7a6ad8', '#2b8ac0'];
function avatarColor(name) {
  let h = 0;
  for (const ch of name || '') h = (Math.imul(h ^ ch.charCodeAt(0), 2654435761)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function parseRoute() {
  const raw = location.hash.replace(/^#/, '') || '/';
  const [path, qs] = raw.split('?');
  const parts = path.split('/').filter(Boolean);
  const query = Object.fromEntries(new URLSearchParams(qs || ''));
  if (!parts.length) return { name: 'overview', query };
  if (parts[0] === 'new') return { name: 'new', query };
  if (parts[0] === 'tasks' && parts[1]) return { name: 'task', id: +parts[1], query };
  if (parts[0] === 'records' && parts[1]) return { name: 'record', id: +parts[1], query };
  if (parts[0] === 'records') return { name: 'records', query };
  if (parts[0] === 'relays') return { name: 'relays', query };
  if (parts[0] === 'keys') return { name: 'keys', query };
  return { name: 'overview', query };
}

/* ------------------------------------------------------------------ app */
const app = createApp({
  setup() {
    const s = reactive({
      route: parseRoute(),
      theme: storageGet('theme', 'system'),
      meta: { models: [], reasons: {} },
      relays: [], keys: [], settings: { official_concurrency: 3 },
      overview: null, task: null, tasks: [], record: null,
      records: { total: 0, items: [] },
      recTab: 'records',
      recFilter: { relay_id: '', model: '', verdict: '', offset: 0 },
      newTask: { relay_ids: [], models: ['claude-opus-5-5'], rounds: 1, stream_mode: 'default', official_key_id: null },
      modal: null,
      keyTests: {},
      toasts: [],
      busy: false,
      loaded: false,
    });

    const PAGE = 20;

    function toast(text, err = false) {
      const t = { id: Math.random(), text, err };
      s.toasts.push(t);
      setTimeout(() => { s.toasts = s.toasts.filter(x => x !== t); }, err ? 5000 : 2600);
    }
    async function guard(fn) {
      try { return await fn(); } catch (e) { toast(e.message, true); }
    }

    /* theme */
    function applyTheme() {
      const el = document.documentElement;
      if (s.theme === 'system') delete el.dataset.theme; else el.dataset.theme = s.theme;
      storageSet('theme', s.theme);
    }
    watch(() => s.theme, applyTheme);

    /* data loading */
    const modelName = id => s.meta.models.find(m => m.id === id)?.name.replace('Claude ', '') || id;
    const reasonText = code => s.meta.reasons[code] || code || '';

    async function loadBase() {
      const [meta, relays, keys, settings] = await Promise.all([
        api('GET', '/api/meta'), api('GET', '/api/relays'), api('GET', '/api/keys'), api('GET', '/api/settings'),
      ]);
      Object.assign(s, { meta, relays, keys, settings });
      if (!s.newTask.official_key_id) s.newTask.official_key_id = keys.find(k => k.is_default)?.id || keys[0]?.id || null;
    }
    async function loadRoute() {
      const r = s.route;
      if (r.name === 'overview') s.overview = await api('GET', '/api/overview');
      if (r.name === 'task') s.task = await api('GET', `/api/tasks/${r.id}`);
      if (r.name === 'record') s.record = await api('GET', `/api/records/${r.id}`);
      if (r.name === 'records') { if (r.query.tab) s.recTab = r.query.tab; await loadRecords(); }
      if (r.name === 'relays') s.relays = await api('GET', '/api/relays');
      if (r.name === 'keys') s.keys = await api('GET', '/api/keys');
      if (r.name === 'new') {
        s.relays = await api('GET', '/api/relays');
        s.keys = await api('GET', '/api/keys');
        if (r.query.relay) s.newTask.relay_ids = [+r.query.relay];
        s.newTask.relay_ids = s.newTask.relay_ids.filter(id => s.relays.some(x => x.id === id));
        if (!s.keys.some(k => k.id === s.newTask.official_key_id))
          s.newTask.official_key_id = s.keys.find(k => k.is_default)?.id || s.keys[0]?.id || null;
      }
    }
    async function loadRecords() {
      if (s.recTab === 'tasks') { s.tasks = await api('GET', '/api/tasks'); return; }
      const f = s.recFilter;
      const q = new URLSearchParams({ limit: PAGE, offset: f.offset });
      for (const k of ['relay_id', 'model', 'verdict']) if (f[k]) q.set(k, f[k]);
      s.records = await api('GET', '/api/records?' + q);
    }
    watch(() => [s.recFilter.relay_id, s.recFilter.model, s.recFilter.verdict], () => { s.recFilter.offset = 0; guard(loadRecords); });
    watch(() => s.recTab, () => guard(loadRecords));

    window.addEventListener('hashchange', () => {
      s.route = parseRoute();
      s.modal = null;
      window.scrollTo({ top: 0 });
      guard(loadRoute);
    });

    /* live refresh while things are running */
    let tick = 0;
    setInterval(async () => {
      tick++;
      const r = s.route;
      if (r.name === 'task' && s.task?.status === 'running') {
        const t = await api('GET', `/api/tasks/${r.id}`).catch(() => null);
        if (t && s.route.name === 'task' && s.route.id === t.id) s.task = t;
      } else if (r.name === 'overview' && s.overview?.totals.running && tick % 2 === 0) {
        s.overview = await api('GET', '/api/overview').catch(() => s.overview);
      }
    }, 1500);

    window.addEventListener('keydown', e => { if (e.key === 'Escape' && s.modal && !s.busy) s.modal = null; });

    onMounted(async () => {
      applyTheme();
      await guard(async () => { await loadBase(); await loadRoute(); });
      s.loaded = true;
    });

    const go = path => { location.hash = path; };

    /* ---------------------------------------------------------------- overview */
    const hasKey = computed(() => s.keys.length > 0);
    function meterParts(st) {
      const d = st.decided || 0;
      if (!d) return [];
      return [
        { w: (st.pass || 0) / d * 100, c: 'var(--pass)' },
        { w: (st.suspicious || 0) / d * 100, c: 'var(--susp)' },
        { w: (st.forged || 0) / d * 100, c: 'var(--forged)' },
      ];
    }
    const passRate = st => st.decided ? Math.round((st.pass || 0) / st.decided * 100) + '%' : '—';

    /* ---------------------------------------------------------------- new task */
    function toggle(list, v) {
      const i = list.indexOf(v);
      i >= 0 ? list.splice(i, 1) : list.push(v);
    }
    const nt = computed(() => {
      const r = s.newTask.relay_ids.length, m = s.newTask.models.length, n = s.newTask.rounds;
      const cells = r * m;
      return { cells, official: m * 2 + cells * (n + 1), relay: cells * n };
    });
    const canStart = computed(() => nt.value.cells > 0 && s.newTask.official_key_id);
    function confirmStart() {
      const m = s.newTask.models.length, cells = nt.value.cells;
      s.modal = {
        type: 'confirm', title: '开始检测？', okText: '开始检测',
        text: `将检测 ${s.newTask.relay_ids.length} 个中转站 × ${m} 个模型，共 ${cells} 项。\n` +
          `官方 API 约 ${nt.value.official} 次请求（含对照实验），中转站约 ${nt.value.relay} 次请求（没有 thinking 时最多重试 3 次）。`,
        onOk: startTask,
      };
    }
    async function startTask() {
      const { id } = await api('POST', '/api/tasks', s.newTask);
      s.modal = null;
      toast('检测已开始');
      go(`/tasks/${id}`);
    }

    /* ---------------------------------------------------------------- task detail */
    const taskView = computed(() => {
      const t = s.task;
      if (!t) return null;
      const rows = [];
      const byRelay = new Map();
      for (const r of t.records) {
        if (!byRelay.has(r.relay_id)) { byRelay.set(r.relay_id, { id: r.relay_id, name: r.relay_name, url: r.relay_url, deleted: r.relay_deleted, cells: {} }); rows.push(byRelay.get(r.relay_id)); }
        byRelay.get(r.relay_id).cells[r.model] = r;
      }
      const done = t.records.filter(r => r.status === 'done').length;
      const cost = t.records.reduce((a, r) => a + r.cost_official, 0) + t.controls.reduce((a, c) => a + c.cost_official, 0);
      const costRelay = t.records.reduce((a, r) => a + r.cost_relay, 0);
      const counts = {};
      for (const r of t.records) if (r.verdict) counts[r.verdict] = (counts[r.verdict] || 0) + 1;
      return { rows, done, total: t.records.length, pct: t.records.length ? done / t.records.length * 100 : 0, cost, costRelay, counts };
    });
    function rerun() {
      const t = s.task;
      const alive = new Set(s.relays.map(r => r.id));
      Object.assign(s.newTask, { relay_ids: t.relay_ids.filter(id => alive.has(id)), models: [...t.models], rounds: t.rounds, stream_mode: t.stream_mode });
      go('/new');
    }
    const controlFor = model => s.task?.controls.find(c => c.model === model);
    const STREAM_MODE = { default: '按中转站设置', stream: '全部流式', nonstream: '全部非流式' };

    /* ---------------------------------------------------------------- records */
    function deleteRecord(rec, back) {
      s.modal = {
        type: 'confirm', title: '删除这条记录？', text: `${rec.relay_name} · ${modelName(rec.model)} 的检测记录将被永久删除。`,
        danger: true, okText: '删除',
        onOk: async () => {
          await api('DELETE', `/api/records/${rec.id}`);
          s.modal = null; toast('已删除');
          back ? go('/records') : loadRecords();
        },
      };
    }
    function deleteTask(t) {
      s.modal = {
        type: 'confirm', title: `删除任务 #${t.id}？`, text: '该任务下的全部检测记录会一起删除。',
        danger: true, okText: '删除',
        onOk: async () => { await api('DELETE', `/api/tasks/${t.id}`); s.modal = null; toast('已删除'); loadRecords(); },
      };
    }
    const pageInfo = computed(() => {
      const f = s.recFilter, total = s.records.total;
      return { from: total ? f.offset + 1 : 0, to: Math.min(f.offset + PAGE, total), total, prev: f.offset > 0, next: f.offset + PAGE < total };
    });
    function page(dir) { s.recFilter.offset = Math.max(0, s.recFilter.offset + dir * PAGE); guard(loadRecords); }

    /* ---------------------------------------------------------------- record detail */
    function heurChips(h) {
      if (!h || !Object.keys(h).length) return [];
      const c = [];
      c.push({ ok: h.id_prefix_ok, t: h.id_prefix_ok ? 'ID 前缀 msg_' : `ID 异常：${h.id ?? '缺失'}` });
      c.push({ ok: h.model_match, warn: !h.model_match, t: `模型回显：${h.model_echo ?? '缺失'}` });
      c.push({ ok: h.usage_ok, t: h.usage_ok ? `usage ${h.input_tokens} / ${h.output_tokens}` : 'usage 缺失或异常' });
      if (h.signature_len) c.push({ ok: h.signature_b64, t: `签名 ${h.signature_len} 字符${h.signature_b64 ? '' : '（非 base64）'}` });
      c.push(h.thinking_text_nonempty
        ? { warn: true, t: 'thinking 文本非空（官方默认为空）' }
        : { ok: true, t: 'thinking 文本为空（符合默认）' });
      c.push({ ok: h.has_tool_use, warn: !h.has_tool_use, t: h.has_tool_use ? '按要求调用了工具' : '未调用工具' });
      if (h.answer_correct !== null && h.answer_correct !== undefined) c.push({ ok: h.answer_correct, t: h.answer_correct ? '计算结果正确' : '计算结果错误' });
      if (h.nonce_ok !== null && h.nonce_ok !== undefined) c.push({ ok: h.nonce_ok, t: h.nonce_ok ? '验证编号一致' : '验证编号不一致' });
      if (h.latency_ms) c.push({ t: `耗时 ${(h.latency_ms / 1000).toFixed(1)}s` });
      if (h.attempts > 1) c.push({ warn: true, t: `重试 ${h.attempts} 次才拿到 thinking` });
      return c;
    }
    const chipCls = c => c.ok === true ? 'ok' : c.warn ? 'warn' : c.ok === false ? 'bad' : '';
    const pretty = o => JSON.stringify(o, null, 2);
    function transText(t) {
      if (t === undefined || t === null) return '—';
      if (!t.length) return '[]（未丢弃任何块）';
      return t.map(x => `${x.reason}（${x.type} @ ${x.path}）`).join('；');
    }
    const heroColor = v => ({ pass: 'var(--pass)', forged: 'var(--forged)', suspicious: 'var(--susp)', undetectable: 'var(--undet)', invalid: 'var(--invalid)', error: 'var(--error)' }[v] || 'var(--border)');

    /* ---------------------------------------------------------------- relays */
    function openRelay(r) {
      const map = {};
      for (const m of s.meta.models) map[m.id] = r?.model_map?.[m.id] || '';
      s.modal = {
        type: 'relay', showKey: false,
        form: r ? { id: r.id, name: r.name, base_url: r.base_url, api_key: '', auth_mode: r.auth_mode, stream: !!r.stream, note: r.note, model_map: map, masked: r.api_key_masked }
          : { name: '', base_url: '', api_key: '', auth_mode: 'auto', stream: false, note: '', model_map: map },
      };
    }
    async function saveRelay() {
      const f = s.modal.form;
      const body = { name: f.name, base_url: f.base_url, api_key: f.api_key, auth_mode: f.auth_mode, stream: f.stream, note: f.note, model_map: f.model_map };
      await guard(async () => {
        if (f.id) await api('PUT', `/api/relays/${f.id}`, body); else await api('POST', '/api/relays', body);
        s.modal = null; toast('已保存');
        s.relays = await api('GET', '/api/relays');
      });
    }
    function deleteRelay(r) {
      s.modal = {
        type: 'confirm', title: `删除中转站「${r.name}」？`, danger: true, okText: '删除',
        text: '中转站配置和 Key 会被删除，历史检测记录会保留，显示为「已删除」。',
        onOk: async () => { await api('DELETE', `/api/relays/${r.id}`); s.modal = null; toast('已删除'); s.relays = await api('GET', '/api/relays'); },
      };
    }
    function openRelayTest(r) {
      s.modal = { type: 'relayTest', relay: r, model: '', loading: false, result: null };
    }
    async function runRelayTest() {
      const m = s.modal;
      m.loading = true; m.result = null;
      await guard(async () => { m.result = await api('POST', `/api/relays/${m.relay.id}/test`, { model: m.model || null }); });
      m.loading = false;
    }

    /* ---------------------------------------------------------------- keys */
    function openKey(k) {
      s.modal = {
        type: 'key', showKey: false,
        form: k ? { id: k.id, name: k.name, api_key: '', is_default: !!k.is_default, note: k.note, masked: k.api_key_masked }
          : { name: '', api_key: '', is_default: s.keys.length === 0, note: '' },
      };
    }
    async function saveKey() {
      const f = s.modal.form;
      await guard(async () => {
        const body = { name: f.name, api_key: f.api_key, is_default: f.is_default, note: f.note };
        if (f.id) await api('PUT', `/api/keys/${f.id}`, body); else await api('POST', '/api/keys', body);
        s.modal = null; toast('已保存');
        s.keys = await api('GET', '/api/keys');
      });
    }
    async function setDefaultKey(k) {
      await guard(async () => {
        await api('PUT', `/api/keys/${k.id}`, { name: k.name, api_key: '', is_default: true, note: k.note });
        s.keys = await api('GET', '/api/keys');
      });
    }
    function deleteKey(k) {
      s.modal = {
        type: 'confirm', title: `删除官方 Key「${k.name}」？`, danger: true, okText: '删除', text: '历史记录不受影响。',
        onOk: async () => { await api('DELETE', `/api/keys/${k.id}`); s.modal = null; toast('已删除'); s.keys = await api('GET', '/api/keys'); },
      };
    }
    async function testKey(k) {
      s.keyTests[k.id] = { loading: true };
      try { s.keyTests[k.id] = await api('POST', `/api/keys/${k.id}/test`); }
      catch (e) { s.keyTests[k.id] = { ok: false, error: e.message }; }
    }
    async function saveSettings() {
      await guard(async () => { s.settings = await api('PUT', '/api/settings', s.settings); toast('设置已保存'); });
    }

    async function modalOk() {
      if (s.busy) return;
      s.busy = true;
      try { await s.modal.onOk(); } catch (e) { toast(e.message, true); }
      s.busy = false;
    }

    return {
      s, VERDICTS, STATUS, STREAM_MODE,
      fmtTime, relTime, money, host, avatarColor, modelName, reasonText, go,
      hasKey, meterParts, passRate,
      toggle, nt, canStart, confirmStart,
      taskView, controlFor, rerun,
      deleteRecord, deleteTask, pageInfo, page,
      heurChips, chipCls, pretty, transText, heroColor,
      openRelay, saveRelay, deleteRelay, openRelayTest, runRelayTest,
      openKey, saveKey, setDefaultKey, deleteKey, testKey, saveSettings,
      modalOk,
    };
  },
});

app.component('ui-icon', UiIcon);
app.component('verdict-badge', VerdictBadge);
app.mount('#app');
