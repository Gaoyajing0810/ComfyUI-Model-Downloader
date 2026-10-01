/* =========================================================================
   ComfyUI Model Downloader · 操作台前端
   -------------------------------------------------------------------------
   · 零外部依赖：无 CDN / 无字体下载 / 无图标库 / 无构建步骤
   · 静态文件由 FastAPI 挂在 `/`，因此全部使用相对路径
   · 默认连真实后端；追加 ?mock=1 可切到内置模拟数据层做纯前端演示
   ========================================================================= */

/* eslint-disable */
const USE_MOCK = new URLSearchParams(location.search).get('mock') === '1';

const POLL_MS = 800;

/* =========================================================================
   1. 图标：内联 SVG（不带 xmlns，交由 HTML 解析器补命名空间）
   ========================================================================= */
const ICON_PATHS = {
  drop: '<path d="M8 1.6v7.6"/><path d="M4.6 6.4 8 9.8l3.4-3.4"/><path d="M2 12.6h12"/>',
  file: '<path d="M3.6 1.6h5.6l3.2 3.2v9.6H3.6z"/><path d="M9.2 1.6v3.2h3.2"/>',
  check: '<path d="M2.6 8.4 6 11.8l7.4-7.6"/>',
  chev: '<path d="M4 6.4 8 10.4l4-4"/>',
  alert: '<path d="M8 2.2 14.6 13.6H1.4z"/><path d="M8 6.3v3.5"/><path d="M8 11.5v.5"/>',
  x: '<path d="M4.2 4.2 11.8 11.8"/><path d="M11.8 4.2 4.2 11.8"/>',
  'x-circle': '<circle cx="8" cy="8" r="6.1"/><path d="M6 6l4 4"/><path d="M10 6l-4 4"/>',
  'ok-circle': '<circle cx="8" cy="8" r="6.1"/><path d="M5.2 8.2 7.2 10.2l3.6-4"/>',
  folder: '<path d="M1.8 4.2h4.4l1.2 1.6h6.8v7H1.8z"/>',
  link: '<path d="M6.4 9.6 9.6 6.4"/><path d="M6.2 3.6H4.4a2.7 2.7 0 0 0 0 5.4h.6"/><path d="M9.8 3.6h1.8a2.7 2.7 0 0 1 0 5.4h-.6"/>',
  refresh: '<path d="M13.4 8a5.5 5.5 0 1 1-1.7-3.9"/><path d="M13.8 2.4v3.2h-3.2"/>',
  download: '<path d="M8 2.4v7.4"/><path d="M4.9 6.9 8 10l3.1-3.1"/><path d="M2.4 13.6h11.2"/>',
  clock: '<circle cx="8" cy="8" r="6.1"/><path d="M8 4.6V8l2.4 1.5"/>',
  shield: '<path d="M8 1.8 13.2 3.7v4.1c0 3-2.2 5.4-5.2 6.5-3-1.1-5.2-3.5-5.2-6.5V3.7z"/><path d="M5.9 7.9 7.4 9.4l2.9-2.9"/>',
  search: '<circle cx="7.2" cy="7.2" r="5.2"/><path d="M11 11l3.2 3.2"/>',
  'search-off': '<circle cx="7.2" cy="7.2" r="5.2"/><path d="M11 11l3.2 3.2"/><path d="M3.4 3.4l9 9"/>',
  inbox: '<path d="M2 4.2h12v8H2z"/><path d="M2 8.2l3.2 2.8h5.6l3.2-2.8"/>',
  stop: '<rect x="4.2" y="4.2" width="7.6" height="7.6" rx="1"/>',
  copy: '<path d="M5.6 5.6V2.8h7.6v7.6H9.4"/><path d="M2.8 5.6h7.6v7.6H2.8z"/>',
  info: '<circle cx="8" cy="8" r="6.1"/><path d="M8 7.2v4"/><path d="M8 4.9v.5"/>',
  'arrow-left': '<path d="M13 8H3"/><path d="M6.4 4.4 3 8l3.4 3.6"/>',
  play: '<path d="M5.2 3.2 12.2 8l-7 4.8z"/>',
  check: '<path d="M3 8.4 6.4 11.8 13 5.2"/>',
  settings: '<path d="M2.4 5.2h3.6M9.8 5.2h3.8M2.4 10.8h1.9M7.2 10.8h6.4"/><circle cx="7.9" cy="5.2" r="1.9"/><circle cx="6.1" cy="10.8" r="1.9"/>',
};

function icon(name) {
  const d = ICON_PATHS[name];
  if (!d) return '';
  return (
    '<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
    d +
    '</svg>'
  );
}

function hydrateIcons(root) {
  (root || document).querySelectorAll('[data-icon]').forEach((n) => {
    const name = n.getAttribute('data-icon');
    if (name && ICON_PATHS[name] && !n.firstElementChild) n.innerHTML = icon(name);
  });
}

/* =========================================================================
   2. 文案表
   ========================================================================= */
const CATEGORY_LABELS = {
  checkpoints: '底模',
  loras: 'LoRA',
  vae: 'VAE',
  text_encoders: '文本编码器',
  diffusion_models: '扩散模型',
  clip_vision: 'CLIP Vision',
  controlnet: 'ControlNet',
  style_models: '风格模型',
  embeddings: '文本嵌入',
  upscale_models: '放大模型',
  photomaker: 'PhotoMaker',
  gligen: 'GLIGEN',
  latent_upscale_models: '潜空间放大',
  hypernetworks: '超网络',
  audio_encoders: '音频编码器',
  background_removal: '背景移除',
  frame_interpolation: '帧插值',
  geometry_estimation: '几何估计',
  optical_flow: '光流',
  detection: '目标检测',
  classifiers: '分类器',
  model_patches: '补丁模型',
  configs: '配置',
  diffusers: 'Diffusers',
};

const LOCAL_STATUS = {
  exact: { t: '已存在', tone: 'ok', icon: 'ok-circle' },
  basename: { t: '其他目录', tone: 'ok', icon: 'folder' },
  missing: { t: '缺失', tone: 'warn', icon: 'alert' },
  corrupt: { t: '本地损坏', tone: 'bad', icon: 'x-circle' },
};

const SOURCE_KIND = {
  curated: { t: '精选映射', tone: 'ac', icon: 'shield' },
  search: { t: '站内搜索', tone: 'mute', icon: 'search' },
  filename: { t: '仓库内匹配', tone: 'mute', icon: 'file' },
  override: { t: '人工指定', tone: 'ok', icon: 'check' },
  none: { t: '未找到来源', tone: 'vio', icon: 'info' },
};

const CONFIDENCE = {
  '高': { tone: 'ok', icon: 'ok-circle' },
  '中': { tone: 'warn', icon: 'alert' },
  '低': { tone: 'bad', icon: 'x-circle' },
  '无': { tone: 'vio', icon: 'info' },
};

const DL_STATE = {
  pending: { t: '等待中', tone: 'mute', icon: 'clock' },
  downloading: { t: '下载中', tone: 'ac', icon: 'download' },
  verifying: { t: '校验中', tone: 'ac', icon: 'shield' },
  done: { t: '完成', tone: 'ok', icon: 'check' },
  skipped: { t: '已跳过', tone: 'ok', icon: 'folder' },
  failed: { t: '失败', tone: 'bad', icon: 'x-circle' },
  unresolved: { t: '未解析', tone: 'vio', icon: 'info' },
};

const DL_CANCELLED = { t: '已取消', tone: 'mute', icon: 'stop' };

const TASK_STATE = {
  running: { t: '进行中', tone: 'ac', icon: 'download' },
  done: { t: '已完成', tone: 'ok', icon: 'ok-circle' },
  failed: { t: '失败', tone: 'bad', icon: 'x-circle' },
  cancelled: { t: '已取消', tone: 'mute', icon: 'stop' },
  pending: { t: '排队中', tone: 'mute', icon: 'clock' },
};

const VERIFY_STATUS = {
  ok: { t: '正常', tone: 'ok', icon: 'ok-circle' },
  no_checksum: { t: '无校验和', tone: 'mute', icon: 'shield' },
  missing: { t: '文件缺失', tone: 'bad', icon: 'alert' },
  empty: { t: '空文件', tone: 'bad', icon: 'x-circle' },
  not_a_model: { t: '非模型文件', tone: 'bad', icon: 'x-circle' },
  truncated: { t: '文件截断', tone: 'bad', icon: 'alert' },
  size_mismatch: { t: '大小不符', tone: 'bad', icon: 'alert' },
  sha_mismatch: { t: 'sha256 不符', tone: 'bad', icon: 'x-circle' },
  io_error: { t: '读取失败', tone: 'bad', icon: 'x-circle' },
};

const catLabel = (c) => CATEGORY_LABELS[c] || c || '未判定';

/* =========================================================================
   3. 工具
   ========================================================================= */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.prototype.slice.call(document.querySelectorAll(sel));

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const num = (v) => (typeof v === 'number' && isFinite(v) ? v : null);

function fmtBytes(n) {
  const v = num(n);
  if (v === null || v < 0) return '—';
  if (v < 1024) return Math.round(v) + ' B';
  let u = 'KB', x = v / 1024;
  if (x >= 1024) { u = 'MB'; x /= 1024; }
  if (x >= 1024) { u = 'GB'; x /= 1024; }
  if (x >= 1024) { u = 'TB'; x /= 1024; }
  return x.toFixed(2) + ' ' + u;
}

function fmtSpeed(bps) {
  const v = num(bps);
  if (!v || v <= 0) return '0 B/s';
  return fmtBytes(v) + '/s';
}

function fmtEta(seconds) {
  const s = num(seconds);
  if (s === null || s < 0 || !isFinite(s)) return '—';
  if (s < 1) return '即将完成';
  if (s < 60) return Math.ceil(s) + ' 秒';
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  if (m < 60) return r ? `${m} 分 ${r} 秒` : `${m} 分`;
  const h = Math.floor(m / 60);
  return `${h} 时 ${m % 60} 分`;
}

function fmtPct(p) {
  const v = num(p);
  if (v === null) return '0%';
  return (Math.max(0, Math.min(1, v)) * 100).toFixed(v >= 0.999 || v === 0 ? 0 : 1) + '%';
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtDelta(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return '刚刚';
  if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
  if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
  return Math.floor(s / 86400) + ' 天前';
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clone = (o) => JSON.parse(JSON.stringify(o));
const clamp01 = (v) => Math.max(0, Math.min(1, num(v) || 0));

function basename(p) {
  const s = String(p || '');
  const i = s.lastIndexOf('/');
  return i >= 0 ? s.slice(i + 1) : s;
}

const REPO_ID_RE = /^[\w.-]+\/[\w.-]+$/;
const MS_HOSTS = ['https://www.modelscope.cn/', 'https://modelscope.cn/'];

/**
 * 只放行模型社区域名、且仓库 id 形态合法的链接，
 * 避免接口返回的任意字符串变成可点击的 javascript: 之类的地址。
 */
function repoHref(source) {
  if (!source) return '';
  const id = String(source.repo_id || '');
  if (!REPO_ID_RE.test(id)) return '';
  const raw = String(source.repo_url || '');
  if (MS_HOSTS.some((h) => raw.indexOf(h) === 0)) return raw;
  return MS_HOSTS[0] + 'models/' + id;
}

function chipSpec(m, extraClass) {
  return (
    `<span class="chip${extraClass ? ' ' + extraClass : ''}" data-tone="${m.tone}">` +
    icon(m.icon) + `<span class="chip__t">${esc(m.t)}</span></span>`
  );
}
function chip(map, key, extraClass) {
  return chipSpec((map && map[key]) || { t: key || '—', tone: 'mute', icon: 'info' }, extraClass);
}

const kv = (k, v) =>
  `<span class="kv"><span class="kv__k">${esc(k)}</span>` +
  `<span class="kv__v" title="${esc(v)}">${esc(v)}</span></span>`;

/* =========================================================================
   4. 提示 / 播报
   ========================================================================= */
let toastSeq = 0;
const _TOAST_MAX = 3;
const _TOAST_TIMERS = new Map();

function toast(text, tone = 'ac', ms = 4600) {
  const box = $('#toasts');
  if (!box) return;
  while (box.children.length >= _TOAST_MAX) box.removeChild(box.firstElementChild);
  const id = ++toastSeq;
  const node = document.createElement('div');
  node.className = 'toast';
  node.dataset.tone = tone;
  node.dataset.id = String(id);
  node.innerHTML = `<span class="toast__t">${esc(text)}</span>` +
    `<button type="button" class="btn btn--ghost btn--icon btn--sm toast__x" aria-label="关闭">${icon('x')}</button>`;
  box.appendChild(node);
  const kill = () => {
    clearTimeout(_TOAST_TIMERS.get(id));
    _TOAST_TIMERS.delete(id);
    if (node.parentNode) node.parentNode.removeChild(node);
  };
  node.querySelector('.toast__x').addEventListener('click', kill);
  _TOAST_TIMERS.set(id, setTimeout(kill, ms));
}

/** 只在语义状态变化时播报，避免轮询把读屏刷屏。 */
function say(text) {
  const live = $('#live');
  if (live) live.textContent = text;
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (e) { /* 落到下面的兜底实现 */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (e) {
    return false;
  }
}

/* =========================================================================
   5. 模拟数据层（仅在 USE_MOCK = true 时启用）
   ========================================================================= */
const MS = (repo) => MS_HOSTS[0] + 'models/' + repo;

const MOCK_CONFIG = {
  comfy_root: '/Users/gaoyajing/Downloads/ComfyUI',
  models_dir: '/Users/gaoyajing/Downloads/ComfyUI/models',
  modelscope_token_set: false,
  concurrency: 3,
  version: '0.1.13',
  categories: [
    'checkpoints', 'loras', 'vae', 'text_encoders', 'diffusion_models', 'clip_vision',
    'controlnet', 'style_models', 'embeddings', 'upscale_models', 'photomaker', 'gligen',
  ],
};

function mkSource(o) {
  const s = Object.assign({ kind: 'curated', repo_id: '', file_path: '', size: null, sha256: null, score: 0, candidates: [], url: '' }, o);
  s.repo_url = s.url || (s.repo_id ? MS(s.repo_id) : '');
  return s;
}

function mockItems() {
  return [
    {
      id: 1, filename: 'flux1-dev.safetensors', category: 'diffusion_models', category_dir: 'unet',
      node_id: '3', class_type: 'UNETLoader', input_name: 'unet_name',
      local: { status: 'missing', path: null, size: null, note: '' },
      source: mkSource({
        kind: 'curated', repo_id: 'AI-ModelScope/FLUX.1-dev', file_path: 'flux1-dev.safetensors',
        size: 23579431568, score: 0.97, revision: 'master',
        sha256: 'e1e1c4a9f7d3b82d5f0a6c91e4b7d2350a8c6f19d2b47e0a3c85d16f9b2e47a03',
        candidates: [
          { repo_id: 'MusePublic/FLUX', file_path: 'flux1-dev.safetensors', score: 0.71 },
          { repo_id: 'AI-ModelScope/FLUX.1-dev-fp8', file_path: 'flux1-dev.safetensors', score: 0.42 },
        ],
      }),
    },
    {
      id: 2, filename: 't5xxl_fp8_e4m3fn.safetensors', category: 'text_encoders', category_dir: 'text_encoders',
      node_id: '5', class_type: 'CLIPLoader', input_name: 'clip_name',
      local: { status: 'missing', path: null, size: null, note: '' },
      source: mkSource({
        kind: 'curated', repo_id: 'AI-ModelScope/flux1-dev', file_path: 'text_encoders/t5xxl_fp8_e4m3fn.safetensors',
        size: 4894653216, score: 0.93, revision: 'master',
        sha256: 'b7c14f2a90d63e85c4a1f60d28b93e5710cd4a9628f3b507e1d4c6a2b98f305',
        candidates: [
          { repo_id: 'MusePublic/t5-v1_1-xxl-encoder-bf16', file_path: 't5xxl_fp8.safetensors', score: 0.55 },
        ],
      }),
    },
    {
      id: 3, filename: 'CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors', category: 'clip_vision', category_dir: 'clip_vision',
      node_id: '6', class_type: 'CLIPVisionLoader', input_name: 'clip_name',
      local: { status: 'missing', path: null, size: null, note: '' },
      source: mkSource({
        kind: 'curated', repo_id: 'AI-ModelScope/CLIP-ViT-H-14',
        file_path: 'open_clip_pytorch_model.bin', size: 2554664960, score: 0.95,
        candidates: [],
      }),
    },
    {
      id: 4, filename: 'flux1-dev-controlnet-canny.safetensors', category: 'controlnet', category_dir: 'controlnet',
      node_id: '11', class_type: 'ControlNetLoader', input_name: 'control_net_name',
      local: { status: 'missing', path: null, size: null, note: '' },
      source: mkSource({
        kind: 'search', repo_id: 'AI-ModelScope/FLUX.1-dev-Controlnet-Canny',
        file_path: 'diffusion_pytorch_model.safetensors', size: 1531121056, score: 0.84,
        candidates: [{ repo_id: 'MusePublic/FLUX-Controlnet', file_path: 'canny.safetensors', score: 0.66 }],
      }),
    },
    {
      id: 5, filename: 'majicMIX_realistic_v7.safetensors', category: 'loras', category_dir: 'loras',
      node_id: '18', class_type: 'LoraLoader', input_name: 'lora_name',
      local: { status: 'missing', path: null, size: null, note: '' },
      source: mkSource({
        kind: 'search', repo_id: 'AI-ModelScope/majicMIX-realistic',
        file_path: 'majicMIX_realistic_v7.safetensors', size: 246415296, score: 0.78,
        candidates: [{ repo_id: 'MusePublic/MagicMIX', file_path: 'majicMIX_realistic_v7.safetensors', score: 0.49 }],
      }),
    },
    {
      id: 6, filename: 'DetailTweaker-Local-Lora.safetensors', category: 'loras', category_dir: 'loras',
      node_id: '22', class_type: 'LoraLoaderModelOnly', input_name: 'lora_name',
      local: { status: 'missing', path: null, size: null, note: '' },
      source: mkSource({
        kind: 'filename', repo_id: 'MusePublic/comfyui-loras',
        file_path: 'DetailTweaker/DetailTweaker-Local-Lora.safetensors', size: 331911720, score: 0.61,
        candidates: [],
      }),
    },
    {
      id: 7, filename: 'EasyNegative.pt', category: 'embeddings', category_dir: 'embeddings',
      node_id: '4', class_type: 'CLIPTextEncode', input_name: 'text',
      local: { status: 'missing', path: null, size: null, note: '' },
      source: mkSource({
        kind: 'search', repo_id: 'AI-ModelScope/EasyNegative', file_path: 'EasyNegative.pt',
        size: 27647, score: 0.72, candidates: [],
      }),
    },
    {
      id: 8, filename: 'ae.safetensors', category: 'vae', category_dir: 'vae',
      node_id: '7', class_type: 'VAELoader', input_name: 'vae_name',
      local: {
        status: 'basename', size: 335304388,
        path: '/Users/gaoyajing/Downloads/ComfyUI/models/vae/VAE/ae.safetensors',
        note: '已存在于 vae/VAE/ae.safetensors',
      },
      source: mkSource({ kind: 'curated', repo_id: 'AI-ModelScope/FLUX.1-schnell', file_path: 'ae.safetensors', size: 335304388, score: 0.99, candidates: [] }),
    },
    {
      id: 9, filename: '4nz-illusustrious-Realistic-XL.safetensors', category: 'checkpoints', category_dir: 'checkpoints',
      node_id: '1', class_type: 'CheckpointLoaderSimple', input_name: 'ckpt_name',
      local: {
        status: 'exact', size: 6463910342,
        path: '/Users/gaoyajing/Downloads/ComfyUI/models/checkpoints/4nz-illusustrious-Realistic-XL.safetensors',
        note: '',
      },
      source: mkSource({ kind: 'curated', repo_id: 'AI-ModelScope/4nz-illustrious-realistic-xl', file_path: '4nz-illusustrious-Realistic-XL.safetensors', size: 6463910342, score: 0.96, candidates: [] }),
    },
    {
      id: 10, filename: '4x-UltraSharp.paf', category: 'upscale_models', category_dir: 'upscale_models',
      node_id: '30', class_type: 'UpscaleModelLoader', input_name: 'model_name',
      local: {
        status: 'corrupt', size: 67231,
        path: '/Users/gaoyajing/Downloads/ComfyUI/models/upscale_models/4x-UltraSharp.paf',
        note: '文件存在但内容损坏（疑似错误页/截断），建议重新下载',
      },
      source: mkSource({
        kind: 'curated', repo_id: 'AI-ModelScope/ESRGAN', file_path: '4x-UltraSharp.paf',
        size: 67406080, score: 0.9,
        candidates: [{ repo_id: 'AI-ModelScope/4x-UltraSharp', file_path: '4x-UltraSharp.paf', score: 0.88 }],
      }),
    },
    {
      id: 11, filename: 'PuLora_Flux_560_v111.safetensors', category: 'loras', category_dir: 'loras',
      node_id: '27', class_type: 'DiffusionSelectorCustom', input_name: 'pp_lora',
      local: { status: 'missing', path: null, size: null, note: '' },
      source: mkSource({
        kind: 'none', repo_id: '', file_path: '', size: null, score: 0,
        candidates: [
          { repo_id: 'AI-ModelScope/FLUX.1-dev-LoRA', file_path: 'PuLora_Flux_560_v111.safetensors', score: 0.38 },
          { repo_id: 'MusePublic/flux-lora-collection', file_path: 'lora/PuLora_Flux_560_v111.safetensors', score: 0.24 },
        ],
      }),
    },
  ];
}

function computeTotals(items) {
  let present = 0, corrupt = 0, toDownload = 0, bytes = 0, unresolved = 0;
  items.forEach((it) => {
    const st = (it.local && it.local.status) || 'missing';
    if (st === 'exact' || st === 'basename') present++;
    if (st === 'corrupt') corrupt++;
    if (isUnresolved(it)) { unresolved++; return; }
    if (st === 'exact' || st === 'basename') return;
    toDownload++;
    bytes += num(it.source && it.source.size) || 0;
  });
  return {
    total: items.length, present: present, missing: items.length - present,
    corrupt: corrupt, to_download: toDownload, unresolved: unresolved,
    bytes_to_download: bytes,
  };
}

function mockPlan(file) {
  const items = mockItems();
  const byCategory = {};
  items.forEach((it) => {
    if (it.category) byCategory[it.category] = (byCategory[it.category] || 0) + 1;
  });
  return {
    job_id: 'j_ab12',
    workflow_name: (file && file.name) || 'flux_dev_基础文生图.json',
    comfy_root: MOCK_CONFIG.comfy_root,
    models_dir: MOCK_CONFIG.models_dir,
    parse: {
      format: 'ui', nodes_scanned: 42, subgraphs: 0,
      models_resolved: items.length - 1, models_unresolved: 1,
      by_category: byCategory,
      notes: ['工作流含 1 个自定义节点，类别由文件名规则兜底判定', '同一 LoRA 被 2 个节点引用，已合并为一条'],
    },
    by_category: byCategory,
    totals: computeTotals(items),
    items: items.map((it) => Object.assign({ selected: !localPresent(it) && !isUnresolved(it) }, it)),
  };
}

const mockTasks = new Map();
let mockTaskSeq = 0;

const MOCK_TICK_MS = 120;
const MOCK_TICK_SHARE = 0.12;

function mockSpeedFor(size) {
  const plausible = 2.4e6 + Math.random() * 5.6e6;
  const target = (size || 0) / (4 + Math.random() * 5);
  return Math.min(Math.max(plausible, target), 1.6e9);
}

function mockStartDownload(payload) {
  const ids = Array.isArray(payload.item_ids) ? payload.item_ids : null;
  const planItems = lastPlan ? lastPlan.items : [];
  const picked = planItems.filter((it) => !ids || ids.indexOf(it.id) >= 0);
  const taskId = 't_' + (++mockTaskSeq).toString(16) + Date.now().toString(36).slice(-4);

  const items = picked.map((it) => {
    const total = num(it.source.size) || num(it.size) || 1;
    return {
      id: it.id,
      filename: it.filename,
      category_dir: it.category_dir,
      class_type: it.class_type,
      node_id: it.node_id,
      target_rel: targetRel(it),
      total: total,
      downloaded: 0,
      state: localPresent(it) ? 'skipped' : isUnresolved(it) ? 'unresolved' : 'pending',
      progress: localPresent(it) || isUnresolved(it) ? (localPresent(it) ? 1 : 0) : 0,
      speed_bps: 0,
      message: localPresent(it) ? '本地已存在，未重复下载' : isUnresolved(it) ? '未找到可信来源，需人工指定' : '',
      error: null,
      _rate: mockSpeedFor(total) * (it.source && it.source.kind === 'search' ? 0.7 : 1),
      _fail: it.id === 5,
    };
  });

  const task = {
    task_id: taskId, state: 'running', items,
    log: [
      '[' + new Date().toISOString().slice(11, 19) + '] 已创建下载任务，来源：模型社区',
      '[' + new Date().toISOString().slice(11, 19) + '] 模拟数据模式：传输过程已按演示节奏压缩，不会真实等待',
    ],
    created_at: new Date().toISOString(),
    workflow_name: lastPlan ? lastPlan.workflow_name : '工作流',
  };
  mockTasks.set(taskId, task);
  mockHistory.unshift({
    task_id: taskId, created_at: task.created_at, workflow_name: task.workflow_name,
    state: 'running', done: 0, total: items.length, bytes: items.reduce((a, b) => a + b.total, 0),
  });
  task._timer = setInterval(() => mockTick(task), MOCK_TICK_MS);
  return { task_id: taskId };
}

function mockLog(task, text) {
  task.log.push('[' + new Date().toISOString().slice(11, 19) + '] ' + text);
  if (task.log.length > 200) task.log.splice(0, task.log.length - 200);
}

function mockTick(task) {
  const conc = MOCK_CONFIG.concurrency || 3;
  let active = task.items.filter((i) => i.state === 'downloading').length;
  let verifying = task.items.filter((i) => i.state === 'verifying').length;
  if (verifying < conc) {
    task.items.forEach((it) => {
      if (active >= conc) return;
      if (it.state !== 'pending') return;
      it.state = 'downloading';
      it._vLeft = 1200 + Math.random() * 1600;
      active++;
      mockLog(task, `开始下载 ${it.filename} → models/${it.category_dir}/`);
    });
  }
  task.items.forEach((it) => {
    if (it.state === 'downloading') {
      const jitter = 0.72 + Math.random() * 0.56;
      const inc = (it._rate * jitter * MOCK_TICK_SHARE) / it.total;
      it.progress = Math.min(1, it.progress + inc);
      it.downloaded = Math.min(it.total, it.progress * it.total);
      it.speed_bps = it._rate * jitter;
      it.message = '已下载 ' + fmtBytes(it.downloaded);
      if (it.progress >= 0.998) {
        it.progress = 1;
        it.downloaded = it.total;
        it.state = 'verifying';
        it.speed_bps = 0;
        it.message = '正在校验 sha256…';
        mockLog(task, `校验中 ${it.filename}`);
      }
    } else if (it.state === 'verifying') {
      it._vLeft -= MOCK_TICK_MS;
      if (it._vLeft <= 0) {
        if (it._fail) {
          it.state = 'failed';
          it.error = '远端返回 502 Bad Gateway，连接被重置（已重试 2 次）';
          it.message = it.error;
          mockLog(task, `失败 ${it.filename}：502 Bad Gateway`);
        } else {
          it.state = 'done';
          it.message = 'sha256 校验通过';
          mockLog(task, `完成 ${it.filename}`);
        }
      }
    }
  });
  const busy = task.items.some((i) => i.state === 'pending' || i.state === 'downloading' || i.state === 'verifying');
  if (!busy) {
    clearInterval(task._timer);
    task._timer = null;
    task.state = task.items.some((i) => i.state === 'failed') ? 'failed' : 'done';
    const rec = mockHistory.find((h) => h.task_id === task.task_id);
    if (rec) {
      rec.state = task.state;
      rec.done = task.items.filter((i) => i.state === 'done' || i.state === 'skipped').length;
    }
  }
}

function mockSnapshot(task) {
  const totalBytes = task.items.reduce((a, b) => a + b.total, 0);
  const bytes = task.items.reduce((a, b) => a + (b.state === 'done' || b.state === 'skipped' ? b.total : b.downloaded), 0);
  const done = task.items.filter((i) => i.state === 'done' || i.state === 'skipped').length;
  return {
    task_id: task.task_id, state: task.state,
    overall: { done: done, total: task.items.length, bytes: bytes, total_bytes: totalBytes },
    items: task.items.map((i) => ({
      id: i.id, state: i.state, progress: i.progress, speed_bps: i.speed_bps,
      filename: i.filename, category_dir: i.category_dir, class_type: i.class_type, target_rel: i.target_rel,
      downloaded: i.downloaded, total: i.total, message: i.message, error: i.error,
    })),
  };
}

const mockHistory = [
  {
    task_id: 't_9f21', created_at: '2026-09-26T13:41:02Z', workflow_name: 'sdxl_人物写真_高清修复.json',
    state: 'done', done: 6, total: 6, bytes: 12884901888,
  },
  {
    task_id: 't_7b04', created_at: '2026-09-25T09:12:47Z', workflow_name: 'hunyuan_video_图生视频.json',
    state: 'failed', done: 3, total: 5, bytes: 24159191040,
  },
  {
    task_id: 't_2c58', created_at: '2026-09-24T21:05:33Z', workflow_name: '基础文生图.json',
    state: 'cancelled', done: 1, total: 4, bytes: 4294967296,
  },
];

function mkPastItem(filename, category_dir, class_type, total, state, extra) {
  const settled = state === 'done' || state === 'skipped';
  return Object.assign({
    filename: filename, category_dir: category_dir, class_type: class_type,
    target_rel: category_dir + '/' + filename,
    total: total, state: state,
    downloaded: settled ? total : Math.round(total * 0.42),
    progress: settled ? 1 : 0.42,
    speed_bps: 0,
    message: settled ? 'sha256 校验通过' : '',
    error: null,
  }, extra || {});
}

const MOCK_PAST = [
  {
    task_id: 't_9f21', created_at: '2026-09-26T13:41:02Z', workflow_name: 'sdxl_人物写真_高清修复.json',
    state: 'done',
    log: [
      '[13:41:02] 已创建下载任务，来源：模型社区',
      '[13:41:03] 解析 6 个模型，5 个需要下载',
      '[13:52:40] 全部文件 sha256 校验通过',
    ],
    items: [
      mkPastItem('4nz-illusustrious-Realistic-XL.safetensors', 'checkpoints', 'CheckpointLoaderSimple', 6463910342, 'done'),
      mkPastItem('majicMIX_realistic_v7.safetensors', 'loras', 'LoraLoader', 246415296, 'done'),
      mkPastItem('DetailTweaker-Local-Lora.safetensors', 'loras', 'LoraLoader', 331911720, 'done'),
      mkPastItem('ae.safetensors', 'vae/VAE', 'VAELoader', 335304388, 'done'),
      mkPastItem('clip_l.safetensors', 'text_encoders', 'CLIPLoader', 246144512, 'done'),
      mkPastItem('4x-UltraSharp.pth', 'upscale_models', 'UpscaleModelLoader', 67108864, 'skipped',
        { message: '本地已存在，未重复下载' }),
    ],
  },
  {
    task_id: 't_7b04', created_at: '2026-09-25T09:12:47Z', workflow_name: 'hunyuan_video_图生视频.json',
    state: 'failed',
    log: [
      '[09:12:47] 已创建下载任务，来源：模型社区',
      '[09:48:19] 失败 qwen_2.5_vl_7b.safetensors：远端返回 502 Bad Gateway',
      '[09:48:19] 任务结束，1 个文件失败',
    ],
    items: [
      mkPastItem('hunyuan_video_720_cfgdistill_fp8_e4m3fn.safetensors', 'diffusion_models', 'UNETLoader', 12923718656, 'done'),
      mkPastItem('hunyuan_video_image_encoder.safetensors', 'clip_vision', 'CLIPVisionLoader', 1273108992, 'done'),
      mkPastItem('llava-llama-3-8b-v1_5.safetensors', 'text_encoders', 'LLMLoader', 16247046016, 'done'),
      mkPastItem('qwen_2.5_vl_7b.safetensors', 'text_encoders', 'LLMLoader', 16725762048, 'failed', {
        downloaded: 12845056, progress: 0.0007,
        message: '远端返回 502 Bad Gateway，连接被重置（已重试 2 次）',
        error: '远端返回 502 Bad Gateway，连接被重置（已重试 2 次）',
      }),
      mkPastItem('hunyuan_video_vae.safetensors', 'vae', 'VAELoader', 335304388, 'unresolved', {
        downloaded: 0, progress: 0, message: '未找到可信来源，需人工指定',
      }),
    ],
  },
  {
    task_id: 't_2c58', created_at: '2026-09-24T21:05:33Z', workflow_name: '基础文生图.json',
    state: 'cancelled',
    log: [
      '[21:05:33] 已创建下载任务，来源：模型社区',
      '[21:06:58] 任务被用户取消',
    ],
    items: [
      mkPastItem('t5xxl_fp8_e4m3fn.safetensors', 'text_encoders', 'CLIPLoader', 4893932416, 'done'),
      mkPastItem('flux1-dev.safetensors', 'diffusion_models', 'UNETLoader', 17051837952, 'downloading', {
        downloaded: 4096000000, progress: 0.24, message: '已下载 3.81 GB', speed_bps: 0,
      }),
      mkPastItem('clip_l.safetensors', 'text_encoders', 'CLIPLoader', 246144512, 'verifying', {
        downloaded: 246144512, progress: 1, message: '正在校验 sha256…', speed_bps: 0,
      }),
      mkPastItem('ae.safetensors', 'vae/VAE', 'VAELoader', 335304388, 'pending', {
        downloaded: 0, progress: 0, speed_bps: 0,
      }),
    ],
  },
];

function seedMockHistory() {
  MOCK_PAST.forEach((rec) => {
    if (mockTasks.has(rec.task_id)) return;
    const task = {
      task_id: rec.task_id, state: rec.state, items: rec.items, log: rec.log,
      created_at: rec.created_at, workflow_name: rec.workflow_name, _timer: null,
    };
    mockTasks.set(rec.task_id, task);
    const row = mockHistory.find((h) => h.task_id === rec.task_id);
    if (row) {
      row.total = task.items.length;
      row.done = task.items.filter((i) => i.state === 'done' || i.state === 'skipped').length;
      row.bytes = task.items.reduce((a, b) => a + b.total, 0);
    }
  });
}

const MOCK_VERIFY = {
  ok: [
    { path: 'checkpoints/4nz-illusustrious-Realistic-XL.safetensors', status: 'ok', size: 6463910342, detail: 'sha256 校验通过' },
    { path: 'loras/majicMIX_realistic_v7.safetensors', status: 'ok', size: 246415296, detail: 'sha256 校验通过' },
    { path: 'vae/VAE/ae.safetensors', status: 'ok', size: 335304388, detail: 'sha256 校验通过' },
    { path: 'text_encoders/clip_l.safetensors', status: 'no_checksum', size: 246144512, detail: '远端未提供 sha256，已通过文件头与大小校验' },
  ],
  bad: [
    { path: 'upscale_models/4x-UltraSharp.paf', status: 'not_a_model', size: 67231, detail: '文件头不是模型格式，疑似反代返回的 HTML 错误页' },
    { path: 'loras/DetailTweaker-Local-Lora.safetensors', status: 'truncated', size: 12845056, detail: '文件尾缺失，实际应为 331,911,720 字节' },
    { path: 'checkpoints/anything-v3.safetensors', status: 'sha_mismatch', size: 2139095040, detail: 'sha256 不匹配，文件已损坏' },
  ],
};

function mockVerify(payload) {
  if (payload && payload.category) {
    const cat = String(payload.category).replace(/\/$/, '');
    const all = MOCK_VERIFY.ok.concat(MOCK_VERIFY.bad);
    const hit = all.filter((r) => r.path.indexOf(cat + '/') === 0);
    return { items: hit.length ? hit : [{ path: cat + '/', status: 'missing', size: 0, detail: '该类别下没有可校验的文件' }] };
  }
  return { items: MOCK_VERIFY.ok.concat(MOCK_VERIFY.bad) };
}

/* =========================================================================
   6. 错误 + API 层
   ========================================================================= */
class ApiError extends Error {
  constructor(detail, status) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(url, opts) {
  const options = opts || {};
  let res;
  try {
    res = await fetch(url, options);
  } catch (e) {
    if (e && e.name === 'AbortError') throw e;
    if (location.protocol === 'file:') {
      throw new ApiError('当前是以 file:// 方式打开的页面，无法访问后端。请通过 ComfyUI Model Downloader 服务打开本页。', 0);
    }
    throw new ApiError('无法连接后端服务，请确认 ComfyUI Model Downloader 正在运行。', 0);
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch (e) { data = null; }
  }
  if (!data) throw new ApiError(res.status, '服务端返回非 JSON 响应');
  if (!res.ok) {
    const detail = data && typeof data.detail === 'string' && data.detail
      ? data.detail
      : '服务端返回 ' + res.status + (res.statusText ? ' ' + res.statusText : '');
    throw new ApiError(detail, res.status);
  }
  if (data === null) {
    throw new ApiError('服务端返回了非 JSON 内容，请确认访问的是 ComfyUI Model Downloader 服务。', res.status);
  }
  return data;
}

let lastPlan = null;

const api = {
  config(signal) {
    if (USE_MOCK) return Promise.resolve(clone(MOCK_CONFIG));
    return request('./api/config', { signal: signal, headers: { Accept: 'application/json' } });
  },
  setConfig(payload) {
    if (USE_MOCK) {
      Object.assign(MOCK_CONFIG, {
        comfy_root: payload.comfy_root,
        models_dir: payload.models_dir || payload.comfy_root + '/models',
      });
      return Promise.resolve({ ...MOCK_CONFIG, saved: true, probe: { notes: [] } });
    }
    return request('./api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },
  browse() {
    if (USE_MOCK) return Promise.resolve({ path: MOCK_CONFIG.comfy_root, supported: false });
    return request('./api/config/browse', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
  },
  detect() {
    if (USE_MOCK) return Promise.resolve({ candidates: [MOCK_CONFIG.comfy_root], current: MOCK_CONFIG.comfy_root });
    return request('./api/config/detect', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
  },
  plan(file, signal) {
    if (USE_MOCK) return Promise.resolve(mockPlan(file));
    const fd = new FormData();
    fd.append('file', file, file.name || 'workflow.json');
    return request('./api/plan', { method: 'POST', body: fd, signal: signal });
  },
  override(payload, signal) {
    if (USE_MOCK) {
      const it = lastPlan && lastPlan.items.find((x) => x.id === payload.item_id);
      if (it) {
        const src = payload.url
          ? { kind: 'url', url: payload.url, size: null, sha256: null,
              score: 1, candidates: it.source.candidates || [] }
          : { kind: 'override', repo_id: payload.repo_id, file_path: payload.file_path,
              size: null, sha256: null, score: 1, candidates: it.source.candidates || [] };
        it.source = mkSource(src);
        lastPlan.totals = computeTotals(lastPlan.items);
      }
      return Promise.resolve(clone(lastPlan));
    }
    return request('./api/plan/override', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: signal,
    });
  },
  download(payload, signal) {
    if (USE_MOCK) return Promise.resolve(mockStartDownload(payload));
    return request('./api/download', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: signal,
    });
  },
  progress(taskId, signal) {
    if (USE_MOCK) {
      const t = mockTasks.get(taskId);
      if (!t) return Promise.reject(new ApiError('任务不存在或已过期。', 404));
      return Promise.resolve(mockSnapshot(t));
    }
    return request('./api/progress/' + encodeURIComponent(taskId), { signal: signal });
  },
  history(signal) {
    if (USE_MOCK) return Promise.resolve({ tasks: clone(mockHistory) });
    return request('./api/history', { signal: signal });
  },
  logs(taskId, signal) {
    if (USE_MOCK) {
      const t = mockTasks.get(taskId);
      return Promise.resolve({ lines: t ? t.log.slice(-120) : ['（暂无日志）'] });
    }
    return request('./api/logs?task_id=' + encodeURIComponent(taskId), { signal: signal });
  },
  verify(payload, signal) {
    if (USE_MOCK) return Promise.resolve(mockVerify(payload));
    return request('./api/verify', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: signal,
    });
  },
  cancelTask(taskId) {
    if (USE_MOCK) {
      const t = mockTasks.get(taskId);
      if (t && t._timer) { clearInterval(t._timer); t._timer = null; }
      if (t) t.state = 'cancelled';
      return Promise.resolve();
    }
    return request('./api/task/' + encodeURIComponent(taskId) + '/cancel', {
      method: 'POST', signal: signal,
    });
  },
};

/* =========================================================================
   7. 状态
   ========================================================================= */
const S = {
  view: 'drop',
  config: null,
  plan: null,
  sel: new Set(),
  open: new Set(),
  filter: 'all',
  query: '',
  taskId: null,
  progress: null,
  history: [],
  verify: null,
  verifyScope: '',
  seen: new Map(),
  lastFile: null,
  downloadCount: 0,
};

/* =========================================================================
   8. 判定助手
   ========================================================================= */
function localPresent(it) {
  const s = it && it.local && it.local.status;
  return s === 'exact' || s === 'basename';
}
function isUnresolved(it) {
  if (!it || !it.source) return true;
  const k = it.source.kind;
  return !k || k === 'none';
}
function isDownloadable(it) {
  return !!it && typeof it.id === 'number' && !localPresent(it) && !isUnresolved(it);
}
function itemSize(it) {
  const s = (it && it.source && it.source.size);
  return num(s) !== null ? num(s) : num(it && it.size) || 0;
}
function targetDir(it) {
  if (it && it.target_rel) return String(it.target_rel).split('/').slice(0, -1).join('/');
  return (it && it.category_dir) || '';
}
function targetRel(it) {
  if (it && it.target_rel) return String(it.target_rel);
  const d = targetDir(it);
  return (d ? d + '/' : '') + (it && it.filename ? it.filename : '');
}
function modelDir() {
  if (S.config && S.config.models_dir) return String(S.config.models_dir);
  return (S.plan && S.plan.models_dir) || '';
}
function modelsRoot() {
  return modelDir();
}
function destPath() {
  const root = modelsRoot();
  const p = S.plan;
  const dirs = {};
  (p && p.items ? p.items : []).forEach((it) => {
    const d = targetDir(it);
    if (d && !dirs[d]) dirs[d] = true;
  });
  const keys = Object.keys(dirs);
  return root ? (keys.length === 1 ? root + '/' + keys[0] : root) : '';
}

/* =========================================================================
   9. 视图切换
   ========================================================================= */
const VIEW_IDS = {
  drop: 'viewDrop', plan: 'viewPlan', download: 'viewDownload',
  history: 'viewHistory', verify: 'viewVerify',
};

function showView(name) {
  if (name !== 'download') stopPoll();
  S.view = name;
  document.documentElement.dataset.view = name;
  Object.keys(VIEW_IDS).forEach((k) => {
    const n = document.getElementById(VIEW_IDS[k]);
    if (n) n.hidden = k !== name;
  });
  $$('.nav__btn').forEach((b) => {
    const on = b.dataset.nav === name;
    b.classList.toggle('is-on', on);
    b.setAttribute('aria-current', on ? 'page' : 'false');
  });
  if (name === 'history') loadHistory();
  if (name === 'verify' && !S.verify) renderVerifyEmpty();
  if (name === 'download' && S.taskId && (!S.progress || S.progress.state === 'running')) startPoll(S.taskId);
  window.scrollTo({ top: 0, behavior: 'auto' });
}

function navEnabled() {
  const map = { drop: true, plan: !!S.plan, download: !!S.taskId, history: true, verify: true };
  $$('.nav__btn').forEach((b) => { b.disabled = !map[b.dataset.nav]; });
  const n = $('#navDlN');
  if (n) {
    const total = S.taskId && S.progress ? (S.progress.overall && S.progress.overall.total) || 0 : 0;
    if (total > 0) { n.hidden = false; n.textContent = String(total); } else { n.hidden = true; }
  }
}

/* =========================================================================
   10. 顶部配置区
   ========================================================================= */
function renderConfig() {
  const c = S.config || {};
  const set = (id, v) => { const n = document.getElementById(id); if (!n) return; n.textContent = v; n.title = v; };
  set('cfgVersion', 'v' + (c.version || '—'));
  set('cfgRoot', c.comfy_root || '未配置');
  set('cfgModels', c.models_dir || '未配置');

  const tk = $('#cfgToken');
  if (tk) {
    const ok = !!c.modelscope_token_set;
    tk.textContent = ok ? '魔搭 Token 已配置' : '魔搭 Token 未配置';
    tk.dataset.tone = ok ? 'ok' : 'warn';
  }
  const cc = $('#cfgConc');
  if (cc) {
    cc.textContent = '并发 ' + (num(c.concurrency) || 1);
    cc.dataset.tone = 'muted';
  }

  const cats = Array.isArray(c.categories) ? c.categories : [];
  const box = $('#cfgCats');
  if (box) {
    box.innerHTML = cats.length
      ? cats.map((k) => `<span class="tag">${esc(catLabel(k))}<span class="mono" style="color:var(--fg-3)">&nbsp;${esc(k)}</span></span>`).join('')
      : '<span class="tag">未获取到类别清单</span>';
  }
  const sel = $('#verifyScope');
  if (sel) {
    const keep = sel.value;
    sel.innerHTML = '<option value="">全部模型目录</option>' +
      cats.map((k) => `<option value="${esc(k)}">${esc(catLabel(k))} · ${esc(k)}</option>`).join('');
    if (keep && cats.indexOf(keep) >= 0) sel.value = keep;
  }
}

function setConn(state, text) {
  const n = $('#conn');
  const t = $('#connText');
  if (n) n.dataset.state = state;
  if (t) t.textContent = text;
  if (state === 'err') $('#viewOffline').hidden = false;
}

async function loadConfig() {
  setConn('wait', '正在连接后端');
  try {
    S.config = await api.config();
    renderConfig();
    setConn(USE_MOCK ? 'mock' : 'ok', USE_MOCK ? '模拟数据模式' : '后端已连接');
    const wasOffline = !$('#viewOffline').hidden;
    $('#viewOffline').hidden = true;
    if (wasOffline) showView(S.view);
    navEnabled();
    return true;
  } catch (e) {
    S.config = null;
    renderConfig();
    setConn('err', '后端未连接');
    const d = $('#offlineDetail');
    if (d) d.innerHTML = esc(e.message || '无法读取 ./api/config');
    $$('.nav__btn').forEach((b) => { b.disabled = true; });
    return false;
  }
}

/* =========================================================================
   11. 导入视图
   ========================================================================= */
async function submitWorkflow(file) {
  if (!file) return;
  setBusy(true, '正在解析工作流…');
  try {
    const data = await api.plan(file);
    lastPlan = data;
    S.plan = data;
    S.lastFile = file;
    S.sel = new Set(
      (data.items || []).filter((it) => isDownloadable(it) && it.selected !== false).map((it) => it.id)
    );
    S.open = new Set();
    S.seen = new Map();
    S.filter = 'all';
    S.query = '';
    const se = $('#planSearch');
    if (se) se.value = '';
    $$('.fbtn').forEach((b) => b.classList.toggle('is-on', b.dataset.filter === 'all'));
    renderPlan();
    navEnabled();
    showView('plan');
    const t = data.totals || {};
    say(`计划已生成，共 ${num(t.total) || 0} 个模型，待下载 ${num(t.to_download) || 0} 个，未解析 ${num(t.unresolved) || 0} 个。`);
  } catch (e) {
    toast(e.message || '解析失败', 'bad', 7000);
    setMsg('#dropFile', e.message || '解析失败', 'bad');
  } finally {
    setBusy(false);
  }
}

function setBusy(on, text) {
  const b = $('#btnPastePlan');
  const br = $('#btnPickDir');
  if (b) { b.disabled = on; b.innerHTML = on ? (text ? esc(text) : '处理中…') : icon('search') + '解析并生成计划'; }
  if (br) br.disabled = on;
  const r = $('#btnReparse');
  if (r) {
    r.disabled = on;
    r.innerHTML = on ? (text ? esc(text) : '处理中…') : icon('refresh') + '重新解析';
  }
  const sp = $('#planSpin');
  if (sp) sp.hidden = !on;
  const d = $('#dropZone');
  if (d) d.setAttribute('aria-busy', on ? 'true' : 'false');
}

function setMsg(sel, text, tone) {
  const n = $(sel);
  if (!n) return;
  n.textContent = text || '';
  if (tone) n.dataset.tone = tone; else delete n.dataset.tone;
}

function initDrop() {
  const zone = $('#dropZone');
  const input = $('#fileInput');

  const openPicker = () => input.click();
  if ($('#btnPickDir')) $('#btnPickDir').addEventListener('click', openPicker);

  zone.addEventListener('click', (e) => {
    if (e.target.closest('#btnBrowse')) return;
    openPicker();
  });
  zone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
      e.preventDefault();
      openPicker();
    }
  });
  ['dragenter', 'dragover'].forEach((ev) =>
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('is-over'); })
  );
  ['dragleave', 'drop'].forEach((ev) =>
    zone.addEventListener(ev, (e) => { e.preventDefault(); if (ev === 'dragleave' && zone.contains(e.relatedTarget)) return; zone.classList.remove('is-over'); })
  );
  function _validateJsonFile(f) {
    if (!f) return '未选择文件';
    if (!/\.json$/i.test(f.name)) return '请上传 .json 后缀的 ComfyUI 工作流文件';
    if (f.size > 50 * 1024 * 1024) return '文件超过 50MB 上限';
    return null;
  }

  zone.addEventListener('drop', (e) => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (!f) return;
    const err = _validateJsonFile(f);
    if (err) { setMsg('#dropFile', err, 'bad'); return; }
    setMsg('#dropFile', f.name, 'ok');
    submitWorkflow(f);
  });
  input.addEventListener('change', () => {
    const f = input.files && input.files[0];
    if (!f) return;
    const err = _validateJsonFile(f);
    if (err) { setMsg('#dropFile', err, 'bad'); input.value = ''; return; }
    setMsg('#dropFile', f.name, 'ok');
    submitWorkflow(f);
    input.value = '';
  });

  $('#btnPastePlan').addEventListener('click', () => {
    const raw = $('#pasteText').value.trim();
    if (!raw) { setMsg('#pasteMsg', '请先粘贴工作流 JSON 内容。', 'bad'); return; }
    try { JSON.parse(raw); } catch (err) {
      setMsg('#pasteMsg', 'JSON 解析失败：' + err.message, 'bad');
      return;
    }
    setMsg('#pasteMsg', '');
    const f = new File([raw], '粘贴的工作流.json', { type: 'application/json' });
    submitWorkflow(f);
  });

  $('#btnSample').addEventListener('click', () => {
    $('#pasteText').value = SAMPLE_WORKFLOW;
    setMsg('#pasteMsg', '已填入示例，点击「解析并生成计划」查看效果。', 'ok');
    $('#pasteText').focus();
  });
}

const SAMPLE_WORKFLOW = `{
  "last_node_id": 42,
  "last_link_id": 51,
  "nodes": [
    { "id": 1, "type": "CheckpointLoaderSimple", "inputs": [], "outputs": [],
      "widgets_values": ["4nz-illusustrious-Realistic-XL.safetensors"] },
    { "id": 3, "type": "UNETLoader", "inputs": [], "outputs": [],
      "widgets_values": ["flux1-dev.safetensors"] },
    { "id": 4, "type": "CLIPTextEncode", "inputs": [], "outputs": [],
      "widgets_values": ["EasyNegative, worst quality, lowres"] },
    { "id": 5, "type": "CLIPLoader", "inputs": [], "outputs": [],
      "widgets_values": ["t5xxl_fp8_e4m3fn.safetensors", "default"] },
    { "id": 6, "type": "CLIPVisionLoader", "inputs": [], "outputs": [],
      "widgets_values": ["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"] },
    { "id": 7, "type": "VAELoader", "inputs": [], "outputs": [],
      "widgets_values": ["ae.safetensors"] },
    { "id": 11, "type": "ControlNetLoader", "inputs": [], "outputs": [],
      "widgets_values": ["flux1-dev-controlnet-canny.safetensors"] },
    { "id": 18, "type": "LoraLoader", "inputs": [], "outputs": [],
      "widgets_values": ["majicMIX_realistic_v7.safetensors", 0.8, 0.3] },
    { "id": 22, "type": "LoraLoaderModelOnly", "inputs": [], "outputs": [],
      "widgets_values": ["DetailTweaker-Local-Lora.safetensors", 1.0] },
    { "id": 27, "type": "DiffusionSelectorCustom", "inputs": [], "outputs": [],
      "widgets_values": ["PuLora_Flux_560_v111.safetensors", 0.9] },
    { "id": 30, "type": "UpscaleModelLoader", "inputs": [], "outputs": [],
      "widgets_values": ["4x-UltraSharp.paf"] }
  ],
  "links": []
}`;

/* =========================================================================
   12. 计划视图
   ========================================================================= */
function renderPlan() {
  const p = S.plan;
  if (!p) return;
  const items = p.items || [];
  const t = p.totals || computeTotals(items);
  const parse = p.parse || {};

  $('#planName').textContent = p.workflow_name || '未命名工作流';
  $('#planName').title = p.workflow_name || '';

  const fmtMap = { ui: '工作流界面格式', api: 'API 格式' };
  const meta = [
    (fmtMap[parse.format] || esc(parse.format) || '未知格式'),
    '任务 <b>' + esc(p.job_id || '—') + '</b>',
    '节点 <b>' + (num(parse.nodes_scanned) || 0) + '</b>',
    '子图 <b>' + (num(parse.subgraphs) || 0) + '</b>',
    '已识别 <b>' + (num(parse.models_resolved) || 0) + '</b>',
    '未识别 <b>' + (num(parse.models_unresolved) || 0) + '</b>',
  ];
  const cats = p.by_category || (parse && parse.by_category) || {};
  const catChips = Object.keys(cats).map((k) => `<span class="tag">${esc(catLabel(k))} <b class="mono" style="font-weight:500">${esc(cats[k])}</b></span>`);
  $('#planMeta').innerHTML = meta.map((m) => `<span>${m}</span>`).join('<span class="fmeta__dot">·</span>') +
    (catChips.length ? '<span class="fmeta__dot">·</span>' + catChips.join('') : '');

  const notes = Array.isArray(parse.notes) ? parse.notes.filter(Boolean) : [];
  const nbox = $('#planNotes');
  if (notes.length) {
    nbox.hidden = false;
    nbox.innerHTML = notes.map((n) => `<span>${icon('info')}<span>${esc(n)}</span></span>`).join('');
  } else {
    nbox.hidden = true;
    nbox.innerHTML = '';
  }

  renderMeter(t);
  renderStats(t);
  renderPlanRows();
  syncSelectionBar();
}

function renderMeter(t) {
  const box = $('#planMeter');
  const segs = [
    { n: num(t.present) || 0, tone: 'ok', label: '已存在' },
    { n: num(t.to_download) || 0, tone: 'ac', label: '待下载' },
    { n: num(t.corrupt) || 0, tone: 'bad', label: '损坏' },
    { n: num(t.unresolved) || 0, tone: 'vio', label: '未解析' },
  ].filter((s) => s.n > 0);
  const total = segs.reduce((a, b) => a + b.n, 0);
  if (!segs.length) {
    box.innerHTML = '<span class="meter__seg" style="flex:1 1 auto" data-tone="mute"></span>';
    box.setAttribute('aria-label', '没有模型需要处理');
    return;
  }
  box.innerHTML = segs.map((s) =>
    `<span class="meter__seg" data-tone="${s.tone}" style="flex:${s.n} 1 0" title="${esc(s.label)} ${s.n}"></span>`
  ).join('');
  box.setAttribute('aria-label', '共 ' + total + ' 个模型：' + segs.map((s) => s.label + ' ' + s.n).join('，'));
}

function renderStats(t) {
  const cells = [
    { n: num(t.total) || 0, l: '识别到的模型', tone: '' },
    { n: num(t.present) || 0, l: '本地已存在', tone: 'ok' },
    { n: num(t.to_download) || 0, l: '待下载', tone: 'ac' },
    { n: num(t.unresolved) || 0, l: '未解析来源', tone: 'vio' },
    { n: num(t.corrupt) || 0, l: '本地损坏', tone: 'bad' },
    { n: fmtBytes(num(t.bytes_to_download) || 0), l: '需下载流量', tone: '' },
  ];
  $('#planStats').innerHTML = cells.map((c) =>
    `<div class="tcell"${c.tone ? ` data-tone="${c.tone}"` : ''}>` +
    `<span class="tcell__n">${esc(c.n)}</span><span class="tcell__l">${esc(c.l)}</span></div>`
  ).join('');
}

function matchFilter(it) {
  if (S.filter === 'todo') return !localPresent(it) && !isUnresolved(it);
  if (S.filter === 'present') return localPresent(it);
  if (S.filter === 'bad') return !!(it.local && it.local.status === 'corrupt');
  if (S.filter === 'unresolved') return isUnresolved(it);
  return true;
}

function matchQuery(it) {
  if (!S.query) return true;
  const q = S.query.toLowerCase();
  const hay = [
    it.filename, it.category, it.class_type, it.input_name,
    it.source && it.source.repo_id, it.source && it.source.file_path,
  ].filter(Boolean).join(' ').toLowerCase();
  return hay.indexOf(q) >= 0;
}

function renderPlanRows() {
  const items = (S.plan && S.plan.items) || [];
  const list = items.filter((it) => matchFilter(it) && matchQuery(it));
  const box = $('#planRows');
  box.innerHTML = list.map((it) => planRowHtml(it)).join('');
  $('#planEmpty').hidden = list.length > 0;
  $('#planEmptyD').textContent = items.length
    ? '共 ' + items.length + ' 个模型，当前筛选与搜索条件下没有匹配项。'
    : '工作流中没有识别到任何模型引用。';
  updateFilterCounts(items);
  hydrateIcons(box);
}

function updateFilterCounts(items) {
  const counts = {
    all: items.length,
    todo: items.filter((it) => !localPresent(it) && !isUnresolved(it)).length,
    present: items.filter(localPresent).length,
    bad: items.filter((it) => it.local && it.local.status === 'corrupt').length,
    unresolved: items.filter(isUnresolved).length,
  };
  $$('.fbtn').forEach((b) => {
    const k = b.dataset.filter;
    b.innerHTML = esc(b.dataset.label || FILTER_LABELS[k] || k) + `<span class="fbtn__n">${counts[k] || 0}</span>`;
  });
}

const FILTER_LABELS = { all: '全部', todo: '待下载', present: '已存在', bad: '损坏', unresolved: '未解析' };

function planRowHtml(it) {
  const present = localPresent(it);
  const unresolved = !present && isUnresolved(it);
  const can = isDownloadable(it);
  const checked = can && S.sel.has(it.id);
  const isOpen = S.open.has(it.id);
  const name = it.filename || '(未命名)';

  const stateChips =
    chip(LOCAL_STATUS, (it.local && it.local.status) || 'missing', 'chip--mini') +
    chip(SOURCE_KIND, (it.source && it.source.kind) || 'none', 'chip--mini');

  const src = it.source || {};
  const href = repoHref(src);
  const confLabel = src.confidence_label || (unresolved ? '无' : '低');
  const conf = CONFIDENCE[confLabel] || CONFIDENCE['无'];
  const cands = Array.isArray(src.candidates) ? src.candidates : [];

  const sourceCell = unresolved
    ? manualSourceHtml(it)
    : `<span class="repoline">` +
        (href
          ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer" title="${esc(href)}">${esc(src.repo_id)}</a>`
          : `<span class="repoline__nohref">${esc(src.repo_id || '—')}</span>`) +
        `<span class="chip chip--mini" data-tone="${conf.tone}">${icon(conf.icon)}<span class="chip__t">${esc(confLabel)}</span></span>` +
      `</span>` +
      `<span class="fmeta"><span class="mono" title="${esc(src.file_path)}">${esc(src.file_path || '—')}</span>` +
      `<span class="fmeta__dot">·</span>` + chip(SOURCE_KIND, src.kind || 'none', 'chip--mini') +
      (cands.length ? `<span class="fmeta__dot">·</span><button type="button" class="lnk" data-act="toggle">备选 ${cands.length} 个</button>` : '') +
      `</span>`;

  const sizeCell = unresolved
    ? `<span class="sizenum sizenum--pending">—</span><span class="sizesub">来源待定</span>`
    : `<span class="sizenum">${esc(fmtBytes(itemSize(it)))}</span><span class="sizesub">${esc(catLabel(it.category))}</span>`;

  return (
    `<div class="row${unresolved ? ' row--unresolved' : ''}" data-id="${esc(it.id)}" data-sel="${checked ? 1 : 0}">` +
      `<div class="row__main">` +
        `<span class="cell cell-select">` +
          `<label class="chk"><input type="checkbox" data-act="sel"${checked ? ' checked' : ''}${can ? '' : ' disabled'}>` +
          `<span class="chk__box"></span></label>` +
        `</span>` +
        `<span class="cell cell-state">${stateChips}</span>` +
        `<span class="cell cell-file">` +
          `<span class="fname" title="${esc(name)}">${esc(name)}</span>` +
          `<span class="fmeta">` +
            `<span class="mono">models/${esc(targetDir(it) || '?')}/</span>` +
            `<span class="fmeta__dot">·</span>` +
            `<span title="${esc((it.class_type || '') + ' · ' + (it.input_name || ''))}">${esc(it.class_type || '未知节点')}${it.input_name ? ' · ' + esc(it.input_name) : ''}</span>` +
            (it.node_id ? `<span class="fmeta__dot">·</span><span class="mono">#${esc(it.node_id)}</span>` : '') +
          `</span>` +
        `</span>` +
        `<span class="cell cell-source">${sourceCell}</span>` +
        `<span class="cell cell-size" data-label="大小">${sizeCell}</span>` +
        `<span class="cell cell-act">` +
          `<button type="button" class="btn btn--ghost btn--icon btn--sm${isOpen ? ' chip--rot' : ''}" data-act="toggle" aria-expanded="${isOpen}"` +
          ` aria-label="展开 ${esc(name)} 的详情">${icon('chev')}</button>` +
        `</span>` +
      `</div>` +
      `<div class="row__detail"${isOpen ? '' : ' hidden'}>${detailHtml(it)}</div>` +
    `</div>`
  );
}

function manualSourceHtml(it) {
  const cands = (it.source && it.source.candidates) || [];
  const chips = cands.map((c, i) =>
    `<button type="button" class="mr__chip" data-act="cand" data-i="${i}"` +
    ` title="${esc(c.file_path || '')}">${esc(c.repo_id)}<span class="mr__chip__score">${num(c.score) ? Number(c.score).toFixed(2) : ''}</span></button>`
  ).join('');
  return (
    `<form class="mr" data-act="override" oninput="(this.querySelector('.mr__err')||{}).hidden=true">` +
      `<p class="mr__note">${icon('info')}<span>没有找到可信的来源：贴一个 HTTPS 直连 URL 即可（覆盖 HF / CivitAI 镜像、私有仓库等场景）。huggingface.co 域名会自动走国内镜像；若仍下载失败，可到 <a href="https://hf-mirror.com" target="_blank" rel="noopener noreferrer">https://hf-mirror.com</a> 手动搜索模型并复制下载链接。</span></p>` +
      `<label class="field mr__url"><span class="field__lb">直连 URL（可覆盖 HF/CivitAI/私有仓库）</span>` +
      `<input class="inp inp--sm mono" name="url" placeholder="https://hf-mirror.com/.../resolve/main/x.safetensors" spellcheck="false" autocomplete="off">` +
      `<p class="field__hint">下载失败可到 <a href="https://hf-mirror.com" target="_blank" rel="noopener noreferrer">https://hf-mirror.com</a> 手动搜索模型获取下载 URL</p>` +
      `</label>` +
      `<button type="submit" class="btn btn--accent btn--sm mr__submit">${icon('refresh')}确认并重算</button>` +
      (chips ? `<div class="mr__cands"><span class="field__lb mr__cands__lb">候选来源</span>${chips}</div>` : '') +
      `<p class="mr__err" hidden></p>` +
    `</form>`
  );
}

function detailHtml(it) {
  const src = it.source || {};
  const loc = it.local || {};
  const cands = Array.isArray(src.candidates) ? src.candidates : [];
  const rows = [
    kv('目标路径', targetRel(it)),
    kv('类别', catLabel(it.category) + (it.category ? ' · ' + it.category : '')),
    kv('来源节点', '#' + (it.node_id || '?') + ' ' + (it.class_type || '') + (it.input_name ? ' · ' + it.input_name : '')),
    kv('匹配方式', (SOURCE_KIND[src.kind] || { t: src.kind || '—' }).t + (num(src.score) ? ' · score ' + Number(src.score).toFixed(3) : '')),
  ];
  if (src.sha256) rows.push(kv('sha256', src.sha256));
  if (src.revision) rows.push(kv('revision', src.revision));
  rows.push(kv('本地状态', (LOCAL_STATUS[loc.status] || { t: loc.status || '—' }).t + (loc.size ? ' · ' + fmtBytes(loc.size) : '')));
  if (loc.path) rows.push(kv('本地路径', loc.path));
  if (loc.note) rows.push(kv('备注', loc.note));

  let candsHtml = '';
  if (cands.length) {
    candsHtml = '<div class="cands">' + cands.map((c) => {
      const h = repoHref({ repo_id: c.repo_id, repo_url: c.repo_url });
      const inner =
        `<span class="cand__id">${esc(c.repo_id)}</span>` +
        `<span class="cand__p" title="${esc(c.file_path || '')}">${esc(c.file_path || '')}</span>` +
        (c.size ? `<span class="cand__p">${esc(fmtBytes(c.size))}</span>` : '') +
        `<span class="cand__s">${num(c.score) ? Number(c.score).toFixed(2) : '—'}</span>`;
      return h
        ? `<a class="cand" href="${esc(h)}" target="_blank" rel="noopener noreferrer" title="${esc(h)}">${inner}</a>`
        : `<span class="cand" style="cursor:default">${inner}</span>`;
    }).join('') + '</div>';
  }
  return `<div class="detail__grid">${rows.join('')}</div>${candsHtml}`;
}

function syncSelectionBar() {
  const items = (S.plan && S.plan.items) || [];
  const picked = items.filter((it) => S.sel.has(it.id) && isDownloadable(it));
  const bytes = picked.reduce((a, b) => a + itemSize(b), 0);
  $('#selCount').textContent = String(picked.length);
  $('#selBytes').textContent = fmtBytes(bytes);
  const start = $('#btnStart');
  const unres = items.filter(isUnresolved).length;
  start.disabled = picked.length === 0;
  start.innerHTML = picked.length
    ? icon('download') + '开始下载 ' + picked.length + ' 项'
    : icon('download') + '开始下载';
  if (unres > 0) {
    start.title = '还有 ' + unres + ' 个模型未解析来源，需要先手工指定才能下载。';
  } else {
    start.title = '';
  }
}

function toggleDetail(id) {
  const box = document.querySelector(`.row[data-id="${id}"]`);
  if (!box) return;
  const det = box.querySelector('.row__detail');
  if (!det) return;
  const willOpen = det.hidden;
  det.hidden = !willOpen;
  if (willOpen) S.open.add(id); else S.open.delete(id);
  const btn = box.querySelector('.cell-act [data-act="toggle"]');
  if (btn) {
    btn.setAttribute('aria-expanded', String(willOpen));
    btn.classList.toggle('chip--rot', willOpen);
  }
}

async function submitOverride(form) {
  const row = form.closest('.row');
  const id = Number(row && row.dataset.id);
  const url = (form.elements.url.value || '').trim();
  const err = form.querySelector('.mr__err');
  const showErr = (m) => { if (err) { err.textContent = m; err.hidden = false; } };
  if (err) err.hidden = true;

  if (!S.plan || !S.plan.job_id) { showErr('缺少任务 ID，请重新解析工作流。'); return; }
  if (!url) { showErr('请填写直连 URL。'); return; }
  if (!/^https?:\/\//i.test(url)) { showErr('URL 必须以 http:// 或 https:// 开头。'); return; }

  const payload = { job_id: S.plan.job_id, item_id: id, url };
  const label = url;

  const btn = form.querySelector('button[type="submit"]');
  if (btn) btn.disabled = true;
  try {
    const data = await api.override(payload);
    lastPlan = data;
    S.plan = data;
    S.sel.add(id);
    renderPlan();
    navEnabled();
    say('已为 ' + label + ' 指定来源并重算计划。');
    toast('来源已更新，该模型已加入下载列表。', 'ok');
  } catch (e) {
    showErr(e.message || '重算失败');
  } finally {
    const b2 = document.querySelector(`.row[data-id="${id}"] form button[type="submit"]`);
    if (b2) b2.disabled = false;
  }
}

function initPlan() {
  $('#btnBack').addEventListener('click', () => showView('drop'));
  $('#btnBack2').addEventListener('click', () => showView('drop'));
  $('#btnReparse').addEventListener('click', () => {
    if (S.lastFile) submitWorkflow(S.lastFile);
    else showView('drop');
  });

  $('#planRows').addEventListener('change', (e) => {
    const box = e.target.closest('[data-act="sel"]');
    if (!box) return;
    const id = Number(box.closest('.row').dataset.id);
    if (box.checked) S.sel.add(id); else S.sel.delete(id);
    box.closest('.row').dataset.sel = box.checked ? '1' : '0';
    syncSelectionBar();
  });

  $('#planRows').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn || btn.tagName === 'INPUT') return;
    const row = btn.closest('.row');
    const id = Number(row.dataset.id);
    if (btn.dataset.act === 'toggle') { toggleDetail(id); return; }
    if (btn.dataset.act === 'cand') {
      const it = S.plan.items.find((x) => x.id === id);
      const c = (it.source.candidates || [])[Number(btn.dataset.i)];
      if (!c) return;
      const form = row.querySelector('form[data-act="override"]');
      if (!form) return;
      form.elements.repo_id.value = c.repo_id || '';
      form.elements.file_path.value = c.file_path || '';
      form.querySelector('button[type="submit"]').focus();
      return;
    }
  });

  $('#planRows').addEventListener('submit', (e) => {
    const form = e.target.closest('form[data-act="override"]');
    if (!form) return;
    e.preventDefault();
    submitOverride(form);
  });

  $$('.fbtn').forEach((b) => b.addEventListener('click', () => {
    S.filter = b.dataset.filter;
    $$('.fbtn').forEach((x) => x.classList.toggle('is-on', x === b));
    renderPlanRows();
  }));

  let qTimer = null;
  $('#planSearch').addEventListener('input', (e) => {
    const v = e.target.value.trim();
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { S.query = v; renderPlanRows(); }, 140);
  });

  $('#btnAll').addEventListener('click', () => {
    (S.plan.items || []).forEach((it) => { if (isDownloadable(it)) S.sel.add(it.id); });
    renderPlanRows(); syncSelectionBar();
  });
  $('#btnNone').addEventListener('click', () => {
    S.sel.clear();
    renderPlanRows(); syncSelectionBar();
  });
  $('#btnInvert').addEventListener('click', () => {
    (S.plan.items || []).forEach((it) => {
      if (!isDownloadable(it)) return;
      if (S.sel.has(it.id)) S.sel.delete(it.id); else S.sel.add(it.id);
    });
    renderPlanRows(); syncSelectionBar();
  });

  $('#btnStart').addEventListener('click', startDownload);
}

async function startDownload() {
  if (!S.plan) return;
  const btn = $('#btnStart');
  if (btn.disabled) return;
  if (S.taskId && S.progress && S.progress.state === 'running') {
    toast('已有任务在运行：' + S.taskId, 'warn');
    return;
  }
  const ids = Array.from(S.sel).filter((id) =>
    S.plan.items.some((it) => it.id === id && isDownloadable(it))
  );
  if (!ids.length) { toast('请至少勾选一个待下载的模型。', 'warn'); return; }
  btn.disabled = true;
  try {
    const r = await api.download({ job_id: S.plan.job_id, item_ids: ids });
    S.taskId = (r && r.task_id) || null;
    if (!S.taskId) throw new ApiError('服务端未返回 task_id。', 0);
    S.progress = null;
    S.seen = new Map();
    $('#dlLog').textContent = '';
    $('#dlDone').hidden = true;
    $('#dlEmpty').hidden = true;
    navEnabled();
    showView('download');
    say('下载已开始，共 ' + ids.length + ' 个文件。');
    startPoll(S.taskId);
  } catch (e) {
    toast(e.message || '启动下载失败', 'bad', 7000);
  } finally {
    btn.disabled = false;
  }
}

/* =========================================================================
   13. 下载视图 + 轮询
   ========================================================================= */
let pollOn = false;
let pollCtl = null;
let pollTimer = null;
let pollFailCount = 0;

function stopPoll() {
  pollOn = false;
  if (pollCtl) { try { pollCtl.abort(); } catch (e) { /* 已中断 */ } pollCtl = null; }
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  pollFailCount = 0;
}

async function startPoll(taskId) {
  stopPoll();
  if (!taskId) return;
  pollOn = true;
  const ctl = new AbortController();
  pollCtl = ctl;
  while (pollOn) {
    let snap;
    try {
      snap = await api.progress(taskId, ctl.signal);
      pollFailCount = 0;
    } catch (e) {
      if (!pollOn || (e && e.name === 'AbortError')) return;
      pollFailCount++;
      if (pollFailCount >= 5) {
        stopPoll();
        toast('进度连接失败已停止：' + (e.message || '未知错误'), 'bad', 9000);
        say('进度连接失败 5 次，已停止轮询');
        return;
      }
      const delay = Math.min(8000, 500 * Math.pow(2, pollFailCount - 1));
      await new Promise((r) => { pollTimer = setTimeout(r, delay); });
      pollTimer = null;
      continue;
    }
if (!pollOn) return;
    applyProgress(snap);
    if (snap.state !== 'running') break;
    await new Promise((r) => { pollTimer = setTimeout(r, 1000); });
    pollTimer = null;
  }
  announceFinal();
}
function applyProgress(snap) {
  S.progress = snap;
  const o = snap.overall || {};
  const total = num(o.total) || 0;
  const done = num(o.done) || 0;
  const bytes = num(o.bytes) || 0;
  const totalBytes = num(o.total_bytes) || 0;
  const ratio = totalBytes > 0 ? clamp01(bytes / totalBytes) : (total ? done / total : 0);

  const pct = ratio * 100;
  $('#dlPct').textContent = pct >= 99.95 ? '100%' : pct.toFixed(1) + '%';
  const fill = $('#dlFill');
  fill.style.width = (ratio * 100).toFixed(2) + '%';
  fill.parentElement.dataset.state = snap.state === 'done' ? 'done' : snap.state === 'failed' ? 'failed' : '';
  const track = $('#dlTrack');
  track.setAttribute('aria-valuenow', String(Math.round(pct)));

  $('#dlMeta').textContent = `${fmtBytes(bytes)} / ${fmtBytes(totalBytes)} · ${done} / ${total} 个完成`;

  const btn = $('#btnCancel');
  const back = $('#btnDlBack');
  if (snap.state === 'running') {
    btn.hidden = false; btn.disabled = false;
    back.hidden = true;
  } else {
    btn.hidden = true;
    back.hidden = false;
  }

  renderDlRows(snap);
  announceStates(snap);

  if (snap.state !== 'running') {
    $('#dlDone').hidden = false;
    renderTally(snap);
    loadLogs(S.taskId, true);
  } else {
    loadLogs(S.taskId, false);
  }
}

function announceStates(snap) {
  (snap.items || []).forEach((it) => {
    const m = DL_STATE[it.state] || DL_STATE.pending;
    if (S.seen.get(it.id) === it.state) return;
    S.seen.set(it.id, it.state);
    if (it.state === 'done' || it.state === 'failed' || it.state === 'skipped') {
      say(`${it.state === 'failed' ? '失败' : it.state === 'skipped' ? '跳过' : '完成'}：${basename(it.filename || '')}`);
    }
  });
}

function announceFinal() {
  const p = S.progress;
  if (!p) return;
  const items = p.items || [];
  const ok = items.filter((i) => i.state === 'done' || i.state === 'skipped').length;
  const bad = items.filter((i) => i.state === 'failed').length;
  const label = TASK_STATE[p.state] || { t: p.state };
  say(`任务${label.t}：成功 ${ok} 个，失败 ${bad} 个。`);
}

function renderDlRows(snap) {
  const items = snap.items || [];
  const cancelled = snap.state === 'cancelled';
  const planById = {};
  ((S.plan && S.plan.items) || []).forEach((it) => { planById[it.id] = it; });
  const box = $('#dlRows');

  box.innerHTML = items.map((it) => {
    const meta = planById[it.id] || {};
    const name = meta.filename || it.filename || '文件 ' + it.id;
    const isOpen = S.open.has('dl-' + it.id);
    const wasKilled = cancelled && ['pending', 'downloading', 'verifying'].indexOf(it.state) >= 0;
    const m = wasKilled
      ? DL_CANCELLED
      : (DL_STATE[it.state] || DL_STATE.pending);
    const prog = clamp01(it.progress);
    const total = num(it.total) || 0;
    const got = num(it.downloaded) || 0;
    const st = wasKilled ? 'cancelled' : (it.state === 'downloading' ? '' : it.state);
    const msgTone = it.error ? 'bad' : (wasKilled ? 'mute' : '');
    const dir = targetDir(meta) || it.category_dir || '';
    const cls = meta.class_type || it.class_type || '—';

    return (
      `<div class="row${it.state === 'failed' ? ' row--failed' : ''}" data-id="${esc(it.id)}">` +
        `<div class="row__main">` +
          `<span class="cell cell-state">${chipSpec(m, 'chip--mini')}</span>` +
          `<span class="cell cell-file">` +
            `<span class="fname" title="${esc(name)}">${esc(name)}</span>` +
            `<span class="fmeta"><span class="mono">models/${esc(dir || '?')}/</span>` +
            `<span class="fmeta__dot">·</span><span>${esc(cls)}</span></span>` +
          `</span>` +
          `<span class="cell cell-prog" data-label="进度">` +
            `<span class="progrow">` +
              `<span class="track" data-state="${esc(st)}" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(prog * 100)}" aria-label="${esc(name)} 进度">` +
              `<span class="track__fill" style="width:${(prog * 100).toFixed(2)}%"></span></span>` +
              `<span class="progrow__pct">${fmtPct(prog)}</span>` +
            `</span>` +
            `<span class="progmsg" data-tone="${msgTone}" title="${esc(it.error || it.message || '')}">${esc(it.error || it.message || m.t)}</span>` +
          `</span>` +
          `<span class="cell cell-spd" data-label="速度">` +
            `<span class="sizenum">${it.state === 'downloading' && !wasKilled && num(it.speed_bps) > 0 ? esc(fmtSpeed(it.speed_bps)) : '—'}</span>` +
            `<span class="sizesub">${esc(fmtBytes(got))} / ${esc(fmtBytes(total))}</span>` +
          `</span>` +
          `<span class="cell cell-act">` +
            `<button type="button" class="btn btn--ghost btn--icon btn--sm" data-act="dltoggle" aria-expanded="${isOpen}" aria-label="展开 ${esc(name)} 的详情">${icon('chev')}</button>` +
          `</span>` +
        `</div>` +
        `<div class="row__detail"${isOpen ? '' : ' hidden'}>` +
          `<div class="detail__grid">` +
            kv('目标路径', targetRel(meta)) +
            kv('状态', m.t) +
            kv('已下载', fmtBytes(got) + ' / ' + fmtBytes(total)) +
            kv('错误', it.error || '无') +
          `</div></div>` +
      `</div>`
    );
  }).join('');

  const any = items.length > 0;
  $('#dlEmpty').hidden = any;
  $('#dlHead').hidden = !any;
  hydrateIcons(box);
}

function renderTally(snap) {
  const items = snap.items || [];
  const unsettled = items.filter((i) => i.state === 'downloading' || i.state === 'verifying' || i.state === 'pending');
  const cells = [
    { n: items.filter((i) => i.state === 'done').length, l: '下载成功', tone: 'ok' },
    { n: items.filter((i) => i.state === 'skipped').length, l: '本地已跳过', tone: 'ok' },
    { n: items.filter((i) => i.state === 'failed').length, l: '失败', tone: 'bad' },
    { n: items.filter((i) => i.state === 'unresolved').length, l: '未解析', tone: 'vio' },
    snap.state === 'cancelled'
      ? { n: unsettled.length, l: '已取消', tone: 'mute' }
      : { n: unsettled.length, l: '未完成', tone: 'warn' },
  ];
  $('#dlTally').innerHTML = cells.map((c) =>
    `<div class="tcell"${c.tone ? ` data-tone="${c.tone}"` : ''}>` +
    `<span class="tcell__n">${c.n}</span><span class="tcell__l">${esc(c.l)}</span></div>`
  ).join('');

  const d = destPath();
  const dn = $('#dlDest');
  dn.textContent = d || (modelsRoot() || '未配置模型目录');
  dn.title = d || '';
}

let lastLogLen = -1;

async function loadLogs(taskId, force) {
  if (!taskId) return;
  try {
    const r = await api.logs(taskId);
    const lines = Array.isArray(r && r.lines) ? r.lines : [];
    if (force) lastLogLen = -1;
    if (lines.length === lastLogLen) return;
    lastLogLen = lines.length;
    const box = $('#dlLog');
    const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;
    box.textContent = lines.join('\n');
    if (atBottom || force) box.scrollTop = box.scrollHeight;
    $('#dlLogN').textContent = lines.length + ' 行';
  } catch (e) {
    /* 日志是附加信息，取不到不打断主流程 */
  }
}

function initDownload() {
  $('#btnCancel').addEventListener('click', onCancel);
  $('#btnDlBack').addEventListener('click', () => showView('plan'));
  $('#dlRows').addEventListener('click', (e) => {
    const b = e.target.closest('[data-act="dltoggle"]');
    if (!b) return;
    const row = b.closest('.row');
    const key = 'dl-' + row.dataset.id;
    const det = row.querySelector('.row__detail');
    const willOpen = det.hidden;
    det.hidden = !willOpen;
    if (willOpen) S.open.add(key); else S.open.delete(key);
    b.setAttribute('aria-expanded', String(willOpen));
    b.style.transform = willOpen ? 'rotate(180deg)' : '';
  });
  $('#btnCopyPath').addEventListener('click', async () => {
    const p = $('#dlDest').textContent || '';
    if (!p || p === '未配置模型目录') { toast('没有可复制的目录。', 'warn'); return; }
    toast((await copyText(p)) ? '目录路径已复制。' : '复制失败，请手动选中路径。', 'ac');
  });
}

async function onCancel() {
  if (!S.taskId) return;
  stopPoll();
  const btn = $('#btnCancel');
  btn.disabled = true;
  try {
    await api.cancelTask(S.taskId);
  } catch (e) {
    /* 服务端未提供取消接口，客户端中止即可 */
  }
  if (S.progress) {
    S.progress.state = 'cancelled';
    (S.progress.items || []).forEach((it) => {
      if (['pending', 'downloading', 'verifying'].indexOf(it.state) >= 0) {
        it.speed_bps = 0;
        it.message = '已由用户取消';
        it.error = null;
      }
    });
  }
  btn.disabled = false;
  applyProgress(S.progress || { state: 'cancelled', overall: {}, items: [] });
  $('#dlDone').hidden = false;
  renderTally(S.progress);
  say('下载已取消。');
  toast('已取消。服务端若未实现取消接口，任务可能仍会在后台结束。', 'warn', 8000);
}

/* =========================================================================
   14. 历史
   ========================================================================= */
async function loadHistory() {
  try {
    const r = await api.history();
    S.history = Array.isArray(r && r.tasks) ? r.tasks : [];
    renderHistory();
  } catch (e) {
    toast(e.message || '无法读取历史记录', 'bad');
    setMsg('#historyMsg', '刷新失败：' + (e.message || '未知错误'), 'bad');
    if (!S.history.length) {
      S.history = [];
      renderHistory();
    }
  }
}

function renderHistory() {
  const list = S.history;
  const box = $('#historyRows');
  const total = list.length;
  const doneB = list.filter((t) => t.state === 'done').length;
  $('#historySum').textContent = total
    ? `共 ${total} 条记录，其中 ${doneB} 条已完成。点击任意一行可重新查看该任务的进度明细。`
    : '';
  $('#historyEmpty').hidden = total > 0;

  box.innerHTML = list.map((t) => {
    const d = num(t.done) || 0, n = num(t.total) || 0;
    return (
      `<div class="row" data-task="${esc(t.task_id)}" style="cursor:pointer">` +
        `<div class="row__main">` +
          `<span class="cell cell--name"><span class="desc__t" title="${esc(t.task_id)}">${esc(t.task_id)}</span></span>` +
          `<span class="cell cell--desc"><span class="fname" title="${esc(t.workflow_name || '')}">${esc(t.workflow_name || '—')}</span></span>` +
          `<span class="cell"><span class="time">${esc(fmtTime(t.created_at))}</span>` +
            `<span class="sizesub">${esc(fmtDelta(t.created_at))}</span></span>` +
          `<span class="cell cell--mid">${chip(TASK_STATE, t.state || 'pending', 'chip--mini')}</span>` +
          `<span class="cell cell--mid"><span class="time">${d} / ${n}</span></span>` +
          `<span class="cell cell--mid"><span class="time">${esc(fmtBytes(num(t.bytes) || 0))}</span></span>` +
        `</div>` +
      `</div>`
    );
  }).join('');

  hydrateIcons(box);
}

function initHistory() {
  $('#btnHistoryRefresh').addEventListener('click', loadHistory);
  $('#historyRows').addEventListener('click', (e) => {
    const row = e.target.closest('[data-task]');
    if (!row) return;
    const id = row.dataset.task;
    S.taskId = id;
    S.progress = null;
    S.seen = new Map();
    S.open = new Set();
    $('#dlLog').textContent = '';
    $('#dlDone').hidden = true;
    $('#dlEmpty').hidden = false;
    navEnabled();
    showView('download');
    say('正在载入任务 ' + id + ' 的进度。');
    startPoll(id);
  });
}

/* =========================================================================
   15. 校验
   ========================================================================= */
function renderVerifyEmpty() {
  $('#verifyEmpty').hidden = false;
  $('#verifyRows').innerHTML = '';
  $('#verifySummary').hidden = true;
}

async function runVerify() {
  const scope = $('#verifyScope').value || '';
  const btn = $('#btnVerifyAll');
  btn.disabled = true;
  btn.innerHTML = '校验中…';
  try {
    const r = await api.verify(scope ? { category: scope } : { all: true });
    S.verify = Array.isArray(r && r.items) ? r.items : [];
    renderVerify();
    const bad = S.verify.filter((x) => !isVerifyOk(x)).length;
    say(`校验完成，共 ${S.verify.length} 个文件，其中 ${bad} 个有问题。`);
  } catch (e) {
    toast(e.message || '校验失败', 'bad', 7000);
  } finally {
    btn.disabled = false;
    btn.innerHTML = icon('shield') + '开始校验';
  }
}

function isVerifyOk(x) {
  const s = (x && x.status) || '';
  return s === 'ok' || s === 'no_checksum';
}

function renderVerify() {
  const list = S.verify || [];
  if (!list.length) { renderVerifyEmpty(); return; }
  const bad = list.filter((x) => !isVerifyOk(x));
  const good = list.length - bad.length;
  const bytes = list.reduce((a, b) => a + (num(b.size) || 0), 0);

  const sb = $('#verifySummary');
  sb.hidden = false;
  sb.className = 'notes ' + (bad.length ? '' : 'notes--ok');
  sb.innerHTML =
    `<span>${icon(bad.length ? 'alert' : 'ok-circle')}<span>` +
    (bad.length
      ? `扫描 ${list.length} 个文件，${good} 个正常，<b style="color:var(--bad)">${bad.length} 个需要重新下载</b>。`
      : `扫描 ${list.length} 个文件，全部正常。`) +
    ` 合计 ${esc(fmtBytes(bytes))}。</span></span>`;

  $('#verifyEmpty').hidden = true;
  $('#verifyRows').innerHTML = list.map((x) => {
    const s = x.status || 'missing';
    const ok = isVerifyOk(x);
    const p = String(x.path || '');
    return (
      `<div class="row${ok ? '' : ' row--failed'}" data-path="${esc(p)}">` +
        `<div class="row__main">` +
          `<span class="cell cell--name"><span class="desc__t" title="${esc(p)}">${esc(basename(p))}</span>` +
            `<span class="sizesub" title="${esc(p)}">${esc(p)}</span></span>` +
          `<span class="cell cell--mid">${chip(VERIFY_STATUS, s, 'chip--mini')}</span>` +
          `<span class="cell cell--mid"><span class="time">${esc(x.size ? fmtBytes(x.size) : '—')}</span></span>` +
          `<span class="cell cell--desc"><span class="desc" title="${esc(x.detail || '')}">${esc(x.detail || '—')}</span></span>` +
          `<span class="cell cell--act">` +
            (ok ? '' : `<button type="button" class="btn btn--ghost btn--sm" data-act="refetch">重新下载</button>`) +
          `</span>` +
        `</div>` +
      `</div>`
    );
  }).join('');
  hydrateIcons($('#verifyRows'));
}

function initVerify() {
  $('#btnVerifyAll').addEventListener('click', runVerify);
  $('#verifyRows').addEventListener('click', (e) => {
    const b = e.target.closest('[data-act="refetch"]');
    if (!b) return;
    const p = b.closest('.row').dataset.path || '';
    const name = basename(p);
    const items = (S.plan && S.plan.items) || [];
    const hit = items.find((it) => it.filename === name);
    if (hit) {
      S.sel = new Set([hit.id]);
      S.filter = 'all';
      S.query = '';
      $('#planSearch').value = '';
      $$('.fbtn').forEach((x) => x.classList.toggle('is-on', x.dataset.filter === 'all'));
      renderPlanRows();
      syncSelectionBar();
      navEnabled();
      showView('plan');
      say('已在计划中定位到 ' + name + '，可直接重新下载。');
      return;
    }
    copyText(name).then((ok) => {
      toast(ok
        ? '已复制文件名「' + name + '」。请上传包含该模型的工作流重新生成下载计划。'
        : '当前计划中没有这个模型。请上传包含「' + name + '」的工作流重新生成下载计划。',
        'warn', 8000);
    });
  });
}

/* =========================================================================
   16. 启动
   ========================================================================= */
function initNav() {
  $$('.nav__btn').forEach((b) => b.addEventListener('click', () => {
    if (b.disabled) return;
    showView(b.dataset.nav);
  }));
}

function renderProbe(p) {
  let box = $('#setProbe');
  if (!box) {
    box = document.createElement('div');
    box.id = 'setProbe';
    box.className = 'probe';
    const anchor = $('#detectBox');
    (anchor ? anchor.parentNode : $('#setConc').parentNode).insertBefore(box, anchor);
  }
  if (!p) { box.innerHTML = ''; return; }
  const notes = (p.notes || []).map((n) => '<span class="probe__notes">' + esc(n) + '</span>').join('');
  box.innerHTML =
    '<span><span class="probe__k">本地模型文件 </span><span class="probe__v">' + esc(num(p.model_file_count) || 0) + ' 个</span></span>' +
    '<span><span class="probe__k">目录结构 </span><span class="probe__v">' + (p.looks_like_comfyui ? '像 ComfyUI' : '未见 main.py / comfy/') + '</span></span>' +
    notes;
}

async function openSettings() {
  const dlg = $('#dlgSettings');
  if (!dlg) return;
  const c = S.config || {};
  $('#setRoot').value = c.comfy_root || '';
  $('#setModels').value = c.models_dir || '';
  $('#setConc').value = c.concurrency || 3;
  $('#detectBox').hidden = true;
  renderProbe(null);
  setMsg('#setMsg', '', null);
  hydrateIcons(dlg);
  dlg.showModal();
  const br = $('#btnPickDir');
  if (br) {
    br.disabled = USE_MOCK;
    br.title = USE_MOCK ? '模拟数据模式下不可用' : '';
  }
  const hint = $('#setRootHint');
  if (hint && USE_MOCK) hint.textContent = '模拟数据模式下不能浏览本机目录，请手动填写路径。';
}

function closeSettings() {
  const dlg = $('#dlgSettings');
  if (dlg && dlg.open) dlg.close();
}

async function saveSettings() {
  const raw = $('#setRoot').value.trim();
  if (!raw) { setMsg('#setMsg', '请填写 ComfyUI 根目录。', 'bad'); return; }
  const payload = { comfy_root: raw, persist: true };
  const m = $('#setModels').value.trim();
  if (m) payload.models_dir = m;
  const n = parseInt($('#setConc').value, 10);
  if (Number.isFinite(n)) payload.concurrency = n;

  const btn = $('#btnSettingsSave');
  btn.disabled = true;
  setMsg('#setMsg', '正在保存…', 'ac');
  try {
    const r = await api.setConfig(payload);
    S.config = Object.assign(S.config || {}, r);
    renderConfig();
    renderProbe(r.probe);
    toast('目录已生效。', 'ok');
    say('目录已生效：' + payload.comfy_root);
    const notes = (r.probe && r.probe.notes) || [];
    if (r.probe && r.probe.looks_like_comfyui) {
      setMsg('#setMsg', notes.length
        ? '已保存并生效。' + notes.join('；')
        : '已保存并生效。', 'ok');
    } else {
      setMsg('#setMsg', '已保存，但该目录不像 ComfyUI（未见 main.py 与 comfy/），查重可能不准。'
        + (notes.length ? ' ' + notes.join('；') : ''), 'warn');
    }
  } catch (e) {
    setMsg('#setMsg', e.message || '保存失败。', 'bad');
  } finally {
    btn.disabled = false;
  }
}

async function browseFolder() {
  setMsg('#setMsg', '等待选择文件夹…', 'ac');
  try {
    const r = await api.browse();
    if (!r || !r.path) {
      setMsg('#setMsg', r && r.supported === false ? '当前系统不支持原生目录选择，请手动填写路径。' : '已取消。', r && r.supported === false ? 'warn' : null);
      return;
    }
    $('#setRoot').value = r.path;
    if (!$('#setModels').value.trim()) $('#setModels').value = r.models_dir || r.path + '/models';
    S.config = Object.assign(S.config || {}, r);
    renderConfig();
    renderProbe(r.probe);
    setMsg('#setMsg', '已选择，保存后生效。', 'ok');
  } catch (e) {
    setMsg('#setMsg', e.message || '选择失败。', 'bad');
  }
}

async function detectFolders() {
  const box = $('#detectBox');
  const list = $('#detectList');
  setMsg('#setMsg', '正在探测…', 'ac');
  try {
    const r = await api.detect();
    const cur = (r && r.current) || '';
    const items = (r && r.candidates) || [];
    if (!items.length) {
      list.innerHTML = '<p class="field__hint">没有在主目录、桌面、下载里找到 ComfyUI 目录，请手动填写路径。</p>';
    } else {
      list.innerHTML = items.map((p) =>
        '<button type="button" class="detect__item" data-p="' + esc(p) + '"' + (p === cur ? ' data-cur="1"' : '') + '>' + esc(p) + '</button>'
      ).join('');
    }
    box.hidden = false;
    setMsg('#setMsg', items.length ? '找到 ' + items.length + ' 个候选目录。' : '', items.length ? 'ok' : 'warn');
  } catch (e) {
    setMsg('#setMsg', e.message || '探测失败。', 'bad');
  }
}

function initSettings() {
  const dlg = $('#dlgSettings');
  if (!dlg) return;
  $('#btnSettings').addEventListener('click', openSettings);
  $('#btnSettingsClose').addEventListener('click', closeSettings);
  $('#btnSettingsCancel').addEventListener('click', closeSettings);
  $('#btnSettingsSave').addEventListener('click', saveSettings);
  $('#btnPickDir').addEventListener('click', browseFolder);
  $('#btnDetect').addEventListener('click', detectFolders);
  $('#formSettings').addEventListener('submit', (e) => { e.preventDefault(); saveSettings(); });
  $('#detectList').addEventListener('click', (e) => {
    const b = e.target.closest('.detect__item');
    if (!b) return;
    const p = b.getAttribute('data-p');
    $('#setRoot').value = p;
    if (!$('#setModels').value.trim()) $('#setModels').value = p + '/models';
    setMsg('#setMsg', '已填入，保存后生效。', 'ok');
  });
  dlg.addEventListener('click', (e) => { if (e.target === dlg) closeSettings(); });
  dlg.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeSettings(); });
}

// —— 前台心跳 ——
// 浏览器前台（页面）每 5s 向 /ws/heartbeat 发一次 ping；关掉窗口/标签时
// server 端不再收到心跳，launcher 判定前台已关闭后自动退出后台服务。
let _hbWs = null;
let _hbTimer = null;
let _hbRetry = null;
let _hbStop = false;
let _hbFailCount = 0;       // 重连退避计数器：每次 onclose 失败指数翻倍（CRIT-2）

function startHeartbeat() {
  if (USE_MOCK || _hbWs || _hbStop) return;
  const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
  let ws;
  try { ws = new WebSocket(proto + location.host + '/ws/heartbeat'); }
  catch (_) { return; }                       // 静默：连不上不打扰 UI
  _hbWs = ws;
  ws.onopen = () => {
    _hbTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 5000);
  };
  ws.onclose = () => {
    _hbWs = null;
    clearInterval(_hbTimer);
    _hbTimer = null;
    if (_hbRetry) clearTimeout(_hbRetry);
    if (!_hbStop && document.readyState !== 'unloading') {
      const delay = Math.min(30000, 1000 * Math.pow(2, _hbFailCount));
      _hbFailCount += 1;
      _hbRetry = setTimeout(startHeartbeat, delay);
    }
  };
  ws.onerror = () => { /* 静默，由 onclose 接管重连 */ };
}

function stopHeartbeat() {
  _hbStop = true;
  clearInterval(_hbTimer);
  _hbTimer = null;
  clearTimeout(_hbRetry);
  _hbRetry = null;
  if (_hbWs) {
    try { if (_hbWs.readyState === WebSocket.OPEN) _hbWs.send('bye'); } catch (_) {}
    try { _hbWs.close(); } catch (_) {}
    _hbWs = null;
  }
}

function initGlobal() {
  $('#btnRecheck').addEventListener('click', async () => {
    const ok = await loadConfig();
    if (ok) { toast('配置已刷新。', 'ok'); say('配置已刷新。'); }
  });
  $('#btnRetry').addEventListener('click', loadConfig);
  $('#btnRetryOpen').addEventListener('click', async () => {
    const ok = await loadConfig();
    if (ok) showView('drop');
  });
  function notifyShutdown() {
  try { navigator.sendBeacon('/api/shutdown', ''); } catch (_) {}
}

window.addEventListener('pagehide', notifyShutdown);
  window.addEventListener('beforeunload', () => { stopPoll(); stopHeartbeat(); notifyShutdown(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (S.view === 'download' && S.taskId && (!S.progress || S.progress.state === 'running')) startPoll(S.taskId);
  });
}

async function boot() {
  hydrateIcons(document);
  if (USE_MOCK) seedMockHistory();
  initNav();
  initGlobal();
  initDrop();
  initPlan();
  initDownload();
  initHistory();
  initVerify();
  initSettings();
  navEnabled();
  showView('drop');
  const ok = await loadConfig();
  if (ok) {
    say('ComfyUI Model Downloader 已就绪' + (USE_MOCK ? '，当前为模拟数据模式。' : '，后端已连接。'));
    startHeartbeat();
  }
  if (!ok) $('#viewOffline').hidden = false;
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
