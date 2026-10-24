const app = document.querySelector('#app');
const toastRegion = document.querySelector('#toast-region');
const backgroundJobRegion = document.querySelector('#background-job-region');
const uiSessionKey = 'ai-story-ui-state-v3';
function loadUiSession() {
  try { return JSON.parse(sessionStorage.getItem(uiSessionKey) || '{}'); }
  catch { return {}; }
}
const savedUiSession = loadUiSession();
const state = {
  runs: [], config: null, settings: null, settingsDirty: false, models: null, currentRun: null, jobTimer: null,
  jobs: [],
  jobsUi: { query: '', status: 'ALL', resource: 'ALL', period: 'ALL', sort: 'NEWEST', page: 1, pageSize: 10 },
  validationUi: savedUiSession.validationUi || { status: 'open', stage: 'all', severity: 'all' },
  runTabs: savedUiSession.runTabs || {},
  scrollPositions: savedUiSession.scrollPositions || {}, currentRouteKey: null,
};

function saveUiSession() {
  try {
    sessionStorage.setItem(uiSessionKey, JSON.stringify({
      validationUi: state.validationUi,
      runTabs: state.runTabs,
      scrollPositions: state.scrollPositions,
    }));
  } catch { /* Session persistence is an enhancement; navigation must still work without it. */ }
}

const profileLabels = {
  YOUTH_SAFE: 'Truyện thiếu nhi',
  ADULT_STANDARD: 'Truyện người lớn',
  SERIAL_DETECTIVE: 'Series trinh thám',
};
const stageLabels = {
  STAGE1: 'Nội dung & nhân vật',
  STAGE2: 'Hình ảnh ngang',
  STAGE3: 'Hình ảnh dọc',
  STAGE4: 'Prompt video',
};
const statusLabels = {
  INITIALIZED: 'Đã khởi tạo',
  RUNNING: 'Đang xử lý',
  QUEUED: 'Đang chờ',
  SUCCEEDED: 'Đã tạo đầu ra',
  COMPLETED_WITH_WARNINGS: 'Hoàn tất — cần sửa',
  FAILED: 'Xử lý thất bại',
  CANCELLED: 'Đã hủy',
  NEEDS_ATTENTION: 'Cần xử lý',
};
const validationLabels = {
  PASS: 'Đã xác minh — đạt',
  FAIL: 'Đã xác minh — không đạt',
  NOT_VERIFIED: 'Chưa thể xác minh',
  ASSESSED_PASS: 'AI đánh giá — đạt',
  ASSESSED_FAIL: 'AI đánh giá — chưa đạt',
};

const gateLabels = {
  AGE_PROFILE_GATE: 'Câu chữ phù hợp độ tuổi',
  BRIEF_ADHERENCE_GATE: 'Bám sát nội dung brief',
  BRIEF_POLICY_GATE: 'Brief phù hợp chính sách',
  CHARACTER_REFERENCE_SET_GATE: 'Bộ ảnh tham chiếu nhân vật đầy đủ',
  DIALOGUE_STRUCTURE_GATE: 'Lời thoại rõ người nói',
  EDITORIAL_INTEGRITY_GATE: 'Mạch truyện và cảm xúc nhất quán',
  INTRA_ZONE_REPETITION_GATE: 'Không lặp câu trong cùng đoạn',
  LANGUAGE_INTEGRITY_GATE: 'Ngôn ngữ nhất quán',
  NARRATIVE_COHERENCE_GATE: 'Diễn biến bám sát dàn ý',
  NARRATIVE_INVARIANT_GATE: 'Không vi phạm ràng buộc cốt truyện',
  NARRATIVE_VOICE_GATE: 'Ngôi kể và xưng hô nhất quán',
  'PRE-SERIALIZE-SCRIPT-ENUM-VALIDATION-01': 'Cấu trúc kịch bản hợp lệ',
  PROFILE_GATE: 'Đúng hồ sơ nội dung',
  PROFILE_SAFETY_GATE: 'An toàn theo nhóm người đọc',
  PROSE_HYGIENE_GATE: 'Câu văn hoàn chỉnh và sạch lỗi',
  SCENE_STATE_CONTINUITY_GATE: 'Liên tục giữa các cảnh',
  SEMANTIC_REPETITION_GATE: 'Không lặp ý giữa các đoạn',
  SENTENCE_COMPLETENESS_GATE: 'Câu không bị dang dở',
  STORY_CONTRACT_GATE: 'Đáp ứng yêu cầu bắt buộc',
  STORY_QUALITY_GATE: 'Chất lượng biên tập',
  WORD_DURATION_GATE: 'Độ dài và thời lượng',
  YOUTH_CONTEXT_SAFETY_GATE: 'Hành động của trẻ có bối cảnh an toàn',
  ZONE_BUDGET_GATE: 'Dung lượng các phần cân đối',
  'RESEARCH:BLOCKER:BRIEF_COVERAGE': 'Thiếu kết quả bắt buộc của brief',
};

function validationTitle(record) {
  const id = String(record?.id || 'Kiểm tra chưa đặt tên');
  const shortId = id.split(':').pop();
  return gateLabels[id] || gateLabels[shortId] || shortId.replace(/^STAGE\d+[:-]?/, '').replace(/_GATE$/, '').replaceAll('_', ' ').toLocaleLowerCase('vi').replace(/^./, value => value.toLocaleUpperCase('vi'));
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatDate(value) {
  if (!value) return 'Chưa cập nhật';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function formatElapsed(startedAt, completedAt = null) {
  if (!startedAt) return 'Đang chờ bắt đầu';
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 'Chưa xác định';
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  if (seconds < 60) return `${seconds} giây`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes} phút ${remainingSeconds} giây`;
  return `${Math.floor(minutes / 60)} giờ ${minutes % 60} phút`;
}

function jobStageLabel(job) {
  const match = String(job.operation || '').match(/STAGE(\d)/);
  return match ? (stageLabels[`STAGE${match[1]}`] || `Stage ${match[1]}`) : 'Workflow';
}

function jobOperationLabel(job) {
  const match = String(job.operation || '').match(/STAGE(\d)/);
  if (!match) return job.operation || 'Workflow';
  const action = String(job.operation || '').includes('REPAIR') ? 'Repair' : String(job.operation || '').includes('CREATE') ? 'Tạo' : 'Xử lý';
  return `${action} ${stageLabels[`STAGE${match[1]}`] || `Stage ${match[1]}`}`;
}

function jobProgressKind(job) {
  if (job.state === 'FAILED') return 'danger';
  if (job.state === 'SUCCEEDED') return 'success';
  if (job.state === 'CANCELLED') return 'warning';
  return 'brand';
}

function jobProviderLabel(providerMode) {
  return ({
    deterministic: 'Deterministic',
    hybrid: 'Hybrid',
    text_local: 'Text local',
    local: 'Local production',
  })[providerMode] || providerMode || 'Mặc định';
}

function jobModelLabel(job) {
  const selection = job.request_payload?.model_selection;
  if (!selection || typeof selection !== 'object' || !Object.keys(selection).length) {
    return job.request_payload?.provider_mode === 'deterministic' ? 'Không dùng model AI' : 'Theo cấu hình hiện tại';
  }
  return Object.entries(selection).map(([role, model]) => `${role}: ${typeof model === 'string' ? model : model?.name || model?.id || 'custom'}`).join(' · ');
}

function stage1ModelSelection(wizard) {
  const rolesByMode = {
    deterministic: [],
    hybrid: ['story'],
    text_local: ['story', 'safety'],
    local: ['story', 'character_image', 'safety'],
  };
  const roles = rolesByMode[wizard.provider_mode] || [];
  return Object.fromEntries(
    roles.map(role => [role, wizard[`model_${role}`]]).filter(([, value]) => value),
  );
}

function jobStaleMessage(job) {
  if (job.state !== 'RUNNING' || !job.updated_at) return '';
  const seconds = Math.floor((Date.now() - new Date(job.updated_at).getTime()) / 1000);
  if (!Number.isFinite(seconds) || seconds < 60) return '';
  return `Chưa có cập nhật mới trong ${Math.floor(seconds / 60)} phút. Tác vụ có thể vẫn đang xử lý bước nặng.`;
}

function jobPhaseLabel(phase) {
  return ({
    QUEUED: 'Đang chờ tài nguyên',
    WAITING_FOR_GPU: 'Đang chờ GPU',
    STARTING: 'Khởi tạo',
    WORKSPACE: 'Chuẩn bị workspace',
    GENERATING: 'Tạo nội dung',
    STAGE2: 'Khởi tạo hình ảnh ngang',
    STAGE2_ASSETS: 'Tạo hình ảnh ngang',
    STAGE3: 'Tạo hình ảnh dọc',
    STAGE4: 'Tạo prompt video',
    PACKAGING: 'Đóng gói kết quả',
    COMPLETED: 'Hoàn tất',
    FAILED: 'Thất bại',
    CANCELLED: 'Đã hủy',
  })[phase] || phase || 'Đang xử lý';
}

function renderJobSteps(job) {
  const percent = Number(job.progress_percent || 0);
  const steps = [
    ['Khởi tạo', 5],
    ['Chuẩn bị', 10],
    ['Xử lý chính', 20],
    ['Đóng gói', 95],
  ];
  return steps.map(([label, threshold], index) => {
    const nextThreshold = steps[index + 1]?.[1] ?? 101;
    const kind = percent >= nextThreshold || job.state === 'SUCCEEDED' ? 'done' : percent >= threshold ? 'active' : 'pending';
    return `<li class="job-step ${kind}"><span aria-hidden="true">${kind === 'done' ? '✓' : index + 1}</span><small>${label}</small></li>`;
  }).join('');
}

function updateJobModal(modal, job) {
  const percent = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
  modal.querySelector('#job-description').textContent = job.progress_message || 'Đang xử lý';
  modal.querySelector('#job-percent').textContent = `${percent}%`;
  modal.querySelector('#job-progress-bar').style.width = `${percent}%`;
  modal.querySelector('#job-progress-bar').parentElement.setAttribute('aria-valuenow', String(percent));
  modal.querySelector('#job-state').textContent = statusLabels[job.state] || job.state;
  modal.querySelector('#job-phase').textContent = jobPhaseLabel(job.progress_phase);
  modal.querySelector('#job-stage').textContent = jobStageLabel(job);
  modal.querySelector('#job-resource').textContent = job.resource_class || 'CPU';
  modal.querySelector('#job-attempt').textContent = `Lần ${job.attempt || 1}`;
  modal.querySelector('#job-elapsed').textContent = formatElapsed(job.started_at, job.completed_at);
  modal.querySelector('#job-updated').textContent = formatDate(job.updated_at);
  modal.querySelector('#job-run-id').textContent = job.run_id || 'Sẽ tạo sau khi khởi động';
  modal.querySelector('#job-provider').textContent = jobProviderLabel(job.request_payload?.provider_mode);
  modal.querySelector('#job-models').textContent = jobModelLabel(job);
  modal.querySelector('#job-steps').innerHTML = renderJobSteps(job);
  const staleMessage = jobStaleMessage(job);
  const staleNotice = modal.querySelector('#job-stale-notice');
  staleNotice.textContent = staleMessage;
  staleNotice.hidden = !staleMessage;
}

function statusBadge(status) {
  const kind = status === 'FAILED' || status === 'NEEDS_ATTENTION' || status === 'COMPLETED_WITH_WARNINGS' ? 'danger' : status === 'RUNNING' || status === 'QUEUED' || status === 'INITIALIZED' || status === 'CANCELLED' ? 'warning' : 'success';
  return `<span class="badge badge-${kind}">${escapeHtml(statusLabels[status] || status || 'Chưa rõ')}</span>`;
}

const findingLabels = {
  MISSING_REQUIRED_OUTCOME: 'Thiếu kết quả bắt buộc đã nêu trong brief',
  CROSS_ZONE_SEMANTIC_REPETITION: 'Câu bị lặp ý với một scene khác',
  MISSING_SENTENCE_BOUNDARY: 'Câu chưa kết thúc đầy đủ',
  DANGLING_CLAUSE_END: 'Mệnh đề bị bỏ dở',
  SUSPICIOUS_FINAL_FRAGMENT: 'Đoạn kết có dấu hiệu là câu cụt',
  UNCLOSED_QUOTE: 'Lời thoại chưa đóng ngoặc kép',
  UNEXPECTED_UNICODE_SCRIPT: 'Có ký tự không thuộc ngôn ngữ yêu cầu',
  UNEXPECTED_LANGUAGE_TOKENS: 'Có từ thuộc ngôn ngữ khác',
  NARRATIVE_INVARIANT_VIOLATION: 'Diễn biến vi phạm ràng buộc của brief',
  EDITORIAL_DIMENSION_BELOW_MINIMUM: 'Một tiêu chí biên tập dưới ngưỡng',
  EDITORIAL_SCORE_BELOW_THRESHOLD: 'Tổng điểm biên tập dưới ngưỡng',
  SUBJECT_ONLY_FRAGMENT: 'Câu chỉ có chủ ngữ, chưa có hành động',
  NARRATIVE_PERSON_SHIFT: 'Ngôi kể thay đổi trong cùng một đoạn',
  CHARACTER_GENDER_ADDRESS_MISMATCH: 'Cách xưng hô không khớp nhân vật',
  SCENE_ENTRY_STATE_MISMATCH: 'Trạng thái đầu scene không nối với scene trước',
  PREMATURE_SCENE_OUTCOME: 'Kết quả của scene xuất hiện quá sớm',
  SCENE_ACTOR_MISSING: 'Scene thiếu nhân vật đã khóa trong kế hoạch',
  SCENE_BEAT_EVIDENCE_INSUFFICIENT: 'Scene chưa thể hiện đủ hành động, địa điểm hoặc đạo cụ',
  SCENE_BOUNDARY_MISSING: 'Scene kết thúc khi câu chưa hoàn chỉnh',
  SCENE_ENVIRONMENT_MISSING: 'Scene chưa có môi trường cụ thể',
  SCENE_SENTENCE_TOO_LONG: 'Scene có câu quá dài so với nhóm tuổi',
  UNSUPERVISED_MINOR_HIGH_RISK_ACTIVITY: 'Trẻ thực hiện hành động nguy hiểm không có giám sát',
  CHARACTER_PERSON_COUNT_MISMATCH: 'Ảnh không có đúng một nhân vật',
  CHARACTER_AGE_BAND_MISMATCH: 'Tuổi biểu hiện trong ảnh không khớp hồ sơ',
  CHARACTER_PRESENTATION_MISMATCH: 'Presentation trong ảnh không khớp hồ sơ',
  CHARACTER_FRAMING_MISMATCH: 'Ảnh không phải character reference độc lập',
  CHARACTER_VISUAL_ATTRIBUTE_MISMATCH: 'Đặc điểm nhận dạng trong ảnh không khớp khóa',
  CHARACTER_SEMANTIC_NOT_ASSESSED: 'Ảnh chưa được kiểm định semantic',
};

function findingSummary(finding) {
  if (!finding || typeof finding !== 'object') return String(finding || 'Không có mô tả chi tiết');
  const label = findingLabels[finding.error] || finding.error || 'Lỗi kiểm định';
  const locator = finding.locator || finding.source_locator;
  return `${label}${locator ? ` — ${locator}` : ''}`;
}

function validationBadge(status) {
  const kind = status === 'PASS' || status === 'ASSESSED_PASS' ? 'success' : status === 'NOT_VERIFIED' ? 'warning' : 'danger';
  return `<span class="badge badge-${kind}">${escapeHtml(validationLabels[status] || status)}</span>`;
}

function toast(message, error = false) {
  const element = document.createElement('div');
  element.className = `toast${error ? ' error' : ''}`;
  element.textContent = message;
  toastRegion.append(element);
  window.setTimeout(() => element.remove(), 4500);
}

function activateDialog(backdrop, close) {
  const dialog = backdrop.querySelector('[role="dialog"]');
  const previousFocus = document.activeElement;
  const focusable = () => [...dialog.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])')];
  const onKeydown = event => {
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key !== 'Tab') return;
    const items = focusable();
    if (!items.length) return;
    const first = items[0]; const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  dialog.addEventListener('keydown', onKeydown);
  (focusable()[0] || dialog).focus();
  return () => { dialog.removeEventListener('keydown', onKeydown); backdrop.remove(); previousFocus?.focus?.(); };
}

function showBackgroundJob(job) {
  backgroundJobRegion.innerHTML = `<a class="background-job" href="#/jobs"><span class="status-dot"></span><span><strong>${escapeHtml(jobOperationLabel(job))}</strong><small>${escapeHtml(job.progress_message || 'Đang xử lý')} · ${Number(job.progress_percent || 0)}%</small></span><span aria-hidden="true">↗</span></a>`;
}

function clearBackgroundJob() { backgroundJobRegion.innerHTML = ''; }

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...(options.headers || {}) } });
  const contentType = response.headers.get('content-type') || '';
  const value = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(value?.error || value || `HTTP ${response.status}`);
  return value;
}

function uxViewport() {
  return window.innerWidth <= 420 ? 'narrow' : window.innerWidth <= 960 ? 'compact' : 'wide';
}

function trackUx(event, fields = {}) {
  const payload = JSON.stringify({ event, viewport: uxViewport(), ...fields });
  fetch('/api/ux-events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: payload, keepalive: true }).catch(() => {});
}

function setLoading(label = 'Đang tải dữ liệu…') {
  app.innerHTML = `<div class="loading"><div><div class="spinner"></div><div>${escapeHtml(label)}</div></div></div>`;
}

function setError(error) {
  app.innerHTML = `<div class="page-head"><div><div class="kicker">Có lỗi</div><h1>Không thể hiển thị trang</h1></div></div><div class="error-panel"><strong>Đã xảy ra lỗi</strong>${escapeHtml(error.message || error)}</div>`;
}

async function loadBase() {
  const [runs, config, settings, models] = await Promise.all([api('/api/runs'), api('/api/config'), api('/api/settings'), api('/api/models')]);
  state.runs = runs.runs;
  state.config = config;
  state.settings = settings;
  state.models = models;
  applyAppearance(settings);
}

const roleLabels = { story: 'Model viết truyện', safety: 'Model kiểm duyệt', character_image: 'Model ảnh nhân vật', landscape: 'Model ảnh ngang', portrait: 'Model ảnh dọc', tts: 'Giọng đọc TTS' };
const roleKinds = { story: 'text', safety: 'text', character_image: 'image', landscape: 'image', portrait: 'image', tts: 'voice' };
function modelField(role, selected = '') {
  const models = (state.models?.models || []).filter(model => model.kind === roleKinds[role] && model.status === 'READY' && model.selectable !== false);
  const active = selected || state.models?.active?.[role] || '';
  return `<div class="field"><label for="model-${role}">${roleLabels[role]}</label><select class="input" id="model-${role}" name="model_${role}"><option value="">Mặc định theo provider</option>${models.map(model => `<option value="${escapeHtml(model.id)}" ${active === model.id ? 'selected' : ''}>${escapeHtml(model.name)} · ${escapeHtml(model.quantization || model.kind)}</option>`).join('')}</select></div>`;
}
function presetField(selected = 'balanced') {
  const presets = state.config?.quality_presets || {};
  return `<div class="field"><label for="quality-preset">Preset chất lượng</label><select class="input" id="quality-preset" name="quality_preset">${Object.entries(presets).map(([id, value]) => `<option value="${escapeHtml(id)}" ${selected === id ? 'selected' : ''}>${escapeHtml(value.label)}</option>`).join('')}</select><small>Nhanh giảm lượt thử/bước ảnh; Chất lượng cao tăng retry và diffusion steps.</small></div>`;
}

function routeInfo() {
  const raw = location.hash.slice(1) || '/';
  const [path, queryString] = raw.split('?');
  return { path, query: new URLSearchParams(queryString || '') };
}

function updateNavigation(route) {
  document.querySelectorAll('[data-route]').forEach(link => {
    const active = route === 'dashboard' ? link.dataset.route === 'dashboard' : link.dataset.route === route;
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  });
}

async function renderRoute() {
  if (state.jobTimer) { clearTimeout(state.jobTimer); state.jobTimer = null; }
  if (state.currentRouteKey) {
    state.scrollPositions[state.currentRouteKey] = window.scrollY;
    saveUiSession();
  }
  const route = routeInfo();
  const routeKey = `${route.path}?${route.query.toString()}`;
  state.currentRouteKey = routeKey;
  setLoading();
  try {
    if (!state.config) await loadBase();
    if (route.path === '/' || route.path === '/stories') {
      updateNavigation(route.path === '/' ? 'dashboard' : 'stories');
      renderDashboard(route.path === '/stories');
    } else if (route.path === '/new') {
      updateNavigation('dashboard');
      renderWizard();
    } else if (route.path === '/jobs') {
      updateNavigation('jobs');
      await renderJobs();
    } else if (route.path.startsWith('/runs/')) {
      updateNavigation('stories');
      const runId = decodeURIComponent(route.path.split('/')[2] || '');
      state.currentRun = await api(`/api/runs/${encodeURIComponent(runId)}`);
      renderRun(state.currentRun);
    } else if (route.path === '/validation') {
      updateNavigation('validation');
      const runId = route.query.get('run') || state.runs.find(item => item.output_package)?.run_id;
      if (runId) state.currentRun = await api(`/api/runs/${encodeURIComponent(runId)}`);
      renderValidation(state.currentRun);
    } else if (route.path === '/inspector') {
      updateNavigation('inspector');
      renderInspector();
    } else if (route.path === '/models') {
      updateNavigation('models');
      await renderModels();
    } else if (route.path === '/settings') {
      updateNavigation('settings');
      await renderSettings();
    } else {
      location.hash = '#/';
      return;
    }
    app.focus({ preventScroll: true });
    requestAnimationFrame(() => window.scrollTo({ top: state.scrollPositions[routeKey] || 0, behavior: 'instant' }));
  } catch (error) {
    setError(error);
  }
}

function applyAppearance(settings) {
  document.documentElement.style.colorScheme = settings?.theme === 'system' ? 'light dark' : (settings?.theme || 'light dark');
  const fontStacks = {
    system: 'Inter, "Segoe UI", system-ui, sans-serif',
    humanist: '"Trebuchet MS", "Segoe UI", sans-serif',
    serif: 'Georgia, "Times New Roman", serif',
    mono: '"Cascadia Code", "SFMono-Regular", Consolas, monospace',
  };
  document.documentElement.style.setProperty('--font-ui', fontStacks[settings?.ui_font] || fontStacks.system);
  document.documentElement.classList.toggle('reduced-motion', Boolean(settings?.reduced_motion));
}

async function renderSettings() {
  const settings = state.settings || {};
  const history = await api('/api/settings/history');
  const defaultSettings = { profile: 'YOUTH_SAFE', language: 'vi', provider_mode: 'deterministic', quality_preset: 'balanced', duration_youth: 10, duration_adult: 15, duration_serial: 20, render_tts: false, auto_advance: false, aspect_ratio: 'LANDSCAPE_16_9', theme: 'system', ui_font: 'system', reduced_motion: false, job_refresh_seconds: 3 };
  const check = (value) => value ? 'checked' : '';
  app.innerHTML = `<div class="page-head"><div><div class="kicker">Workspace</div><h1>Cài đặt</h1><p>Quản lý mặc định dự án, runtime và trải nghiệm làm việc.</p></div><div class="actions"><button class="button" id="import-settings" type="button">↑ Nhập</button><button class="button" id="export-settings" type="button">↓ Xuất</button><input id="settings-file" type="file" accept="application/json,.json" hidden></div></div>
    <div class="settings-shell"><nav class="settings-nav" aria-label="Nhóm cài đặt">${[['project','✦','Mặc định dự án'],['models','⬡','Model & provider'],['quality','◇','Chất lượng'],['appearance','◐','Giao diện'],['backup','↺','Sao lưu']].map((item, index) => `<button type="button" data-settings-tab="${item[0]}" aria-pressed="${index === 0}"><span>${item[1]}</span>${item[2]}</button>`).join('')}</nav>
    <form class="settings-layout" id="settings-form">
      <div data-settings-panel="project"><section class="card card-padding settings-section"><div class="settings-section-head"><span class="settings-icon">✦</span><div><h2>Dự án mới</h2><p>Các giá trị được điền sẵn khi mở wizard tạo truyện.</p></div></div>
        <div class="grid grid-two"><div class="field"><label>Loại nội dung</label><select class="input" name="profile">${Object.entries(profileLabels).map(([id, label]) => `<option value="${id}" ${settings.profile === id ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('')}</select></div><div class="field"><label>Ngôn ngữ</label><select class="input" name="language"><option value="vi" ${settings.language === 'vi' ? 'selected' : ''}>Tiếng Việt</option><option value="en" ${settings.language === 'en' ? 'selected' : ''}>English</option></select></div></div>
        <h3>Thời lượng mục tiêu</h3><div class="grid grid-three"><div class="field"><label>Thiếu nhi</label><input class="input" name="duration_youth" type="number" min="5" max="20" value="${settings.duration_youth}"><small>5–20 phút</small></div><div class="field"><label>Người lớn</label><input class="input" name="duration_adult" type="number" min="10" max="30" value="${settings.duration_adult}"><small>10–30 phút</small></div><div class="field"><label>Series trinh thám</label><input class="input" name="duration_serial" type="number" min="15" max="35" value="${settings.duration_serial}"><small>15–35 phút</small></div></div>
        <div class="grid grid-two"><div class="field"><label>Tỷ lệ khung hình cuối</label><select class="input" name="aspect_ratio"><option value="LANDSCAPE_16_9" ${settings.aspect_ratio === 'LANDSCAPE_16_9' ? 'selected' : ''}>Ngang 16:9</option><option value="PORTRAIT_9_16" ${settings.aspect_ratio === 'PORTRAIT_9_16' ? 'selected' : ''}>Dọc 9:16</option></select></div></div>
        <label class="setting-toggle"><input type="checkbox" name="render_tts" ${check(settings.render_tts)}><span><strong>Tạo giọng đọc TTS</strong><small>Yêu cầu model giọng đọc sẵn sàng ở Stage 4.</small></span></label><label class="setting-toggle"><input type="checkbox" name="auto_advance" ${check(settings.auto_advance)}><span><strong>Tự động chuyển stage</strong><small>Chỉ tiếp tục khi package hợp lệ; dừng ngay khi một stage thất bại.</small></span></label>
      </section></div>
      <div data-settings-panel="models" hidden><section class="card card-padding settings-section"><div class="settings-section-head"><span class="settings-icon">⬡</span><div><h2>Model & provider</h2><p>Chọn tuyến xử lý và model mặc định theo từng vai trò.</p></div></div><div class="field"><label>Provider mode</label><select class="input" name="provider_mode"><option value="deterministic" ${settings.provider_mode === 'deterministic' ? 'selected' : ''}>Deterministic</option><option value="hybrid" ${settings.provider_mode === 'hybrid' ? 'selected' : ''}>Hybrid</option><option value="text_local" ${settings.provider_mode === 'text_local' ? 'selected' : ''}>Text local</option><option value="local" ${settings.provider_mode === 'local' ? 'selected' : ''}>Local production</option></select></div><div class="grid grid-two">${Object.keys(roleLabels).map(role => modelField(role, state.models?.active?.[role])).join('')}</div><div class="health-panel" id="health-result"><span class="muted">Chạy kiểm tra để xác minh cấu hình hiện tại.</span><button class="button" id="check-settings" type="button">Kiểm tra cấu hình</button></div></section></div>
      <div data-settings-panel="quality" hidden><section class="card card-padding settings-section"><div class="settings-section-head"><span class="settings-icon">◇</span><div><h2>Chất lượng & hiệu năng</h2><p>Preset điều phối retry, temperature và số bước tạo ảnh.</p></div></div>${presetField(settings.quality_preset || 'balanced')}<div class="preset-comparison">${Object.entries(state.config?.quality_presets || {}).map(([id, preset]) => `<article><strong>${escapeHtml(preset.label)}</strong><span>${preset.retry_attempts} lần thử</span><span>${preset.image_steps} bước ảnh</span><span>Temperature ${preset.parameters?.temperature}</span></article>`).join('')}</div></section></div>
      <div data-settings-panel="appearance" hidden><section class="card card-padding settings-section"><div class="settings-section-head"><span class="settings-icon">◐</span><div><h2>Giao diện</h2><p>Điều chỉnh hiển thị và tần suất cập nhật.</p></div></div><div class="grid grid-two"><div class="field"><label>Theme</label><select class="input" name="theme"><option value="system" ${settings.theme === 'system' ? 'selected' : ''}>Theo hệ thống</option><option value="light" ${settings.theme === 'light' ? 'selected' : ''}>Sáng</option><option value="dark" ${settings.theme === 'dark' ? 'selected' : ''}>Tối</option></select></div><div class="field"><label>Font giao diện</label><select class="input font-picker" name="ui_font"><option value="system" ${settings.ui_font === 'system' ? 'selected' : ''}>Mặc định hệ thống</option><option value="humanist" ${settings.ui_font === 'humanist' ? 'selected' : ''}>Humanist — dễ đọc</option><option value="serif" ${settings.ui_font === 'serif' ? 'selected' : ''}>Serif — biên tập</option><option value="mono" ${settings.ui_font === 'mono' ? 'selected' : ''}>Monospace — kỹ thuật</option></select><small>Sử dụng font có sẵn trên máy, không cần kết nối mạng.</small></div><div class="field"><label>Tự động cập nhật tác vụ</label><select class="input" name="job_refresh_seconds">${[2,3,5,10].map(value => `<option value="${value}" ${Number(settings.job_refresh_seconds) === value ? 'selected' : ''}>${value} giây</option>`).join('')}</select></div></div><div class="font-preview" id="font-preview"><span>Truyện của bạn bắt đầu từ một ý tưởng.</span><small>Aa Bb Cc · 0123456789 · Tiếng Việt</small></div><label class="setting-toggle"><input type="checkbox" name="reduced_motion" ${check(settings.reduced_motion)}><span><strong>Giảm chuyển động</strong><small>Hạn chế animation và transition trong giao diện.</small></span></label></section></div>
      <div data-settings-panel="backup" hidden><section class="card card-padding settings-section"><div class="settings-section-head"><span class="settings-icon">↺</span><div><h2>Sao lưu & lịch sử</h2><p>Xuất cấu hình hoặc khôi phục một phiên bản gần đây.</p></div></div><div class="settings-history">${history.entries.length ? history.entries.map((entry, index) => `<div class="history-row"><div><strong>${escapeHtml(formatDate(entry.saved_at))}</strong><small>${escapeHtml(profileLabels[entry.settings?.profile] || entry.settings?.profile)} · ${escapeHtml(entry.settings?.provider_mode)}</small></div><button class="button button-small" type="button" data-restore-index="${index}">Khôi phục</button></div>`).join('') : '<p class="muted">Chưa có phiên bản trước.</p>'}</div></section></div>
      <div class="settings-actions"><span class="muted small" id="settings-status" role="status">Thay đổi chỉ áp dụng cho dự án tạo mới.</span><div class="actions"><button class="button" id="reset-settings" type="button">Khôi phục mặc định</button><button class="button button-primary" type="submit">Lưu thay đổi</button></div></div>
    </form></div>`;
  const form = document.querySelector('#settings-form');
  state.settingsDirty = false;
  form.addEventListener('input', () => { state.settingsDirty = true; document.querySelector('#settings-status').textContent = 'Có thay đổi chưa lưu.'; });
  form.querySelector('[name="ui_font"]').addEventListener('change', event => { const previewSettings = {...state.settings, ui_font: event.target.value}; const fontStacks = { system: 'Inter, "Segoe UI", system-ui, sans-serif', humanist: '"Trebuchet MS", "Segoe UI", sans-serif', serif: 'Georgia, "Times New Roman", serif', mono: '"Cascadia Code", "SFMono-Regular", Consolas, monospace' }; document.querySelector('#font-preview').style.fontFamily = fontStacks[previewSettings.ui_font]; });
  document.querySelectorAll('[data-settings-tab]').forEach(button => button.addEventListener('click', () => { document.querySelectorAll('[data-settings-tab]').forEach(item => item.setAttribute('aria-pressed', String(item === button))); document.querySelectorAll('[data-settings-panel]').forEach(panel => { panel.hidden = panel.dataset.settingsPanel !== button.dataset.settingsTab; }); }));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      const payload = Object.fromEntries(new FormData(form));
      const selectedModels = Object.fromEntries(Object.keys(roleLabels).map(role => [role, payload[`model_${role}`]]));
      Object.keys(roleLabels).forEach(role => delete payload[`model_${role}`]);
      ['duration_youth','duration_adult','duration_serial','job_refresh_seconds'].forEach(key => payload[key] = Number(payload[key]));
      ['render_tts','auto_advance','reduced_motion'].forEach(key => payload[key] = new FormData(form).has(key));
      state.settings = await api('/api/settings', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
      for (const role of Object.keys(roleLabels)) { const modelId = selectedModels[role]; if (modelId && modelId !== state.models?.active?.[role]) await api(`/api/models/${encodeURIComponent(modelId)}/activate`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({role}) }); }
      state.models = await api('/api/models');
      state.settingsDirty = false; applyAppearance(state.settings);
      document.querySelector('#settings-status').textContent = 'Đã lưu. Dự án mới sẽ dùng các giá trị này.';
      toast('Đã lưu cài đặt dự án.');
    } catch (error) { toast(error.message, true); }
    finally { submit.disabled = false; }
  });
  document.querySelector('#reset-settings').addEventListener('click', async () => {
    state.settings = await api('/api/settings', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(defaultSettings) });
    toast('Đã khôi phục cài đặt mặc định.');
    renderSettings();
  });
  document.querySelector('#check-settings').addEventListener('click', async () => { const result = await api('/api/settings/health', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}); document.querySelector('#health-result').innerHTML = `<span class="badge badge-${result.ready ? 'success' : 'warning'}">${result.ready ? 'Sẵn sàng' : 'Cần cấu hình'}</span><span class="small">${result.checks.length ? result.checks.map(item => `${roleLabels[item.role]}: ${item.status}`).join(' · ') : 'Không cần model AI cho chế độ hiện tại.'}</span>`; });
  document.querySelector('#export-settings').addEventListener('click', () => { const blob = new Blob([JSON.stringify(state.settings, null, 2)], {type:'application/json'}); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'ai-story-settings.json'; link.click(); URL.revokeObjectURL(link.href); });
  const fileInput = document.querySelector('#settings-file'); document.querySelector('#import-settings').addEventListener('click', () => fileInput.click()); fileInput.addEventListener('change', async () => { try { const imported = JSON.parse(await fileInput.files[0].text()); state.settings = await api('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(imported)}); applyAppearance(state.settings); toast('Đã nhập cấu hình.'); renderSettings(); } catch (error) { toast(`Không thể nhập: ${error.message}`, true); } });
  document.querySelectorAll('[data-restore-index]').forEach(button => button.addEventListener('click', async () => { const entry = history.entries[Number(button.dataset.restoreIndex)]; state.settings = await api('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(entry.settings)}); applyAppearance(state.settings); toast('Đã khôi phục phiên bản cài đặt.'); renderSettings(); }));
}

async function renderModels() {
  const inventory = await api('/api/models');
  const models = inventory.models || [];
  app.innerHTML = `<div class="page-head"><div><div class="kicker">Runtime local</div><h1>Quản lý model</h1><p>Đăng ký, kiểm tra và chọn model cho từng vai trò. Gỡ đăng ký không xóa weights.</p></div><button class="button button-primary" id="add-model">＋ Đăng ký model</button></div>
    <section class="card card-padding"><div class="card-head"><div><h2>Catalog</h2><p>${models.length} model đã đăng ký trong workspace.</p></div></div>
    ${models.length ? `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Model</th><th>Loại</th><th>Vòng đời</th><th>Trạng thái</th><th>Vai trò / công dụng</th><th></th></tr></thead><tbody>${models.map(model => `<tr><td><strong>${escapeHtml(model.name)}</strong><div class="muted small">${escapeHtml(model.path || model.model_id)}</div></td><td>${escapeHtml(model.kind)}</td><td>${escapeHtml(model.lifecycle || 'production')}</td><td><span class="badge badge-${model.status === 'READY' ? 'success' : 'danger'}">${escapeHtml(model.status)}</span></td><td>${escapeHtml((model.active_roles || []).join(', ') || model.usage || 'Chưa chọn')}</td><td><div class="actions">${model.selectable ? `<button class="button" data-activate-model="${escapeHtml(model.id)}" data-kind="${escapeHtml(model.kind)}">Chọn</button>` : ''}<button class="button button-ghost" data-remove-model="${escapeHtml(model.id)}">Gỡ</button></div></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty-state"><div><span class="empty-icon">⬡</span><h2>Chưa có model</h2><p>Đăng ký file GGUF, ONNX hoặc model Hugging Face để quản lý tập trung.</p></div></div>'}</section>`;
  document.querySelector('#add-model').addEventListener('click', showAddModel);
  document.querySelectorAll('[data-remove-model]').forEach(button => button.addEventListener('click', async () => { try { await api(`/api/models/${encodeURIComponent(button.dataset.removeModel)}/remove`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' }); toast('Đã gỡ model khỏi catalog; weights được giữ nguyên.'); await renderModels(); } catch (error) { toast(error.message, true); } }));
  document.querySelectorAll('[data-activate-model]').forEach(button => button.addEventListener('click', async () => { const choices = button.dataset.kind === 'text' ? ['story','safety'] : button.dataset.kind === 'image' ? ['character_image','landscape','portrait'] : button.dataset.kind === 'voice' ? ['tts'] : []; const role = window.prompt(`Vai trò (${choices.join(', ')}):`, choices[0] || ''); if (!role) return; try { await api(`/api/models/${encodeURIComponent(button.dataset.activateModel)}/activate`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({role}) }); await renderModels(); } catch (error) { toast(error.message, true); } }));
}

function showAddModel() {
  const modal = document.createElement('div'); modal.className = 'modal-backdrop';
  modal.innerHTML = `<div class="modal"><h2>Đăng ký model local</h2><p>Dùng đường dẫn tuyệt đối tới file/thư mục trên máy, hoặc Model ID từ Hugging Face.</p><form id="model-form"><div class="field"><label>ID</label><input class="input" name="id" required pattern="[a-z0-9._-]+"></div><div class="field"><label>Tên hiển thị</label><input class="input" name="name" required></div><div class="field"><label>Loại</label><select class="input" name="kind"><option value="text">Text / GGUF</option><option value="image">Image</option><option value="vision">Vision / encoder</option><option value="voice">Voice / ONNX</option><option value="upscaler">Upscaler</option><option value="preprocessor">Preprocessor</option><option value="adapter">Adapter</option><option value="controlnet">ControlNet</option></select></div><div class="field"><label>Đường dẫn file hoặc thư mục</label><input class="input" name="path" placeholder="D:\\models\\model"></div><div class="field"><label>Hoặc Hugging Face Model ID</label><input class="input" name="model_id" placeholder="organization/model"></div><div class="field"><label>Quantization</label><input class="input" name="quantization" placeholder="Q4_K_M"></div><div class="field"><label>Vòng đời</label><select class="input" name="lifecycle"><option value="production">Production</option><option value="system">System</option><option value="experimental">Experimental</option><option value="legacy">Legacy</option></select></div><div class="field"><label>Công dụng</label><input class="input" name="usage" placeholder="Semantic QA, upscale, identity..."></div><div class="form-actions"><button class="button" type="button" data-close>Hủy</button><button class="button button-primary">Đăng ký</button></div></form></div>`;
  document.body.append(modal); modal.querySelector('[data-close]').addEventListener('click', () => modal.remove());
  modal.querySelector('#model-form').addEventListener('submit', async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); try { await api('/api/models', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}); modal.remove(); toast('Đã đăng ký model.'); await renderModels(); } catch (error) { toast(error.message, true); } });
}

function workflowGroups(runs) {
  const byDigest = new Map(runs.filter(run => run.package?.package_digest_sha256).map(run => [run.package.package_digest_sha256, run]));
  const groups = new Map();
  for (const run of runs) {
    let root = run; let parent = run.package?.parent_package_digest_sha256; const seen = new Set();
    while (parent && byDigest.has(parent) && !seen.has(parent)) { seen.add(parent); root = byDigest.get(parent); parent = root.package?.parent_package_digest_sha256; }
    const key = root.run_id || `${run.profile}:${run.title}`;
    const group = groups.get(key) || { root, runs: [] };
    group.runs.push(run); groups.set(key, group);
  }
  return [...groups.values()].map(group => {
    group.runs.sort((left, right) => Number(String(right.stage || '').replace('STAGE', '')) - Number(String(left.stage || '').replace('STAGE', '')) || new Date(right.updated_at) - new Date(left.updated_at));
    return { ...group, latest: group.runs[0] };
  }).sort((left, right) => new Date(right.latest.updated_at) - new Date(left.latest.updated_at));
}

function dashboardRows(groups) {
  return groups.map((group, index) => { const run = group.latest; return `
    <tr>
      <td><div class="story-cell"><span class="story-cover" style="filter:hue-rotate(${index * 47}deg)"></span><div><div class="story-name">${escapeHtml(run.title)}</div><div class="muted small">${group.runs.length} lần chạy · ${escapeHtml(formatDate(run.updated_at))}</div></div></div></td>
      <td>${escapeHtml(profileLabels[run.profile] || run.profile)}</td>
      <td>${escapeHtml(stageLabels[run.stage] || run.stage || 'Chưa bắt đầu')}</td>
      <td>${statusBadge(run.status)}</td>
      <td><a class="button" href="#/runs/${encodeURIComponent(run.run_id)}" aria-label="Mở workflow ${escapeHtml(run.title)}">Mở workflow</a></td>
    </tr>`; }).join('');
}

function renderDashboard(allStories = false) {
  const runs = state.runs;
  const groups = workflowGroups(runs);
  if (!runs.length) {
    app.innerHTML = `
      <div class="page-head"><div><div class="kicker">Workspace</div><h1>${allStories ? 'Truyện' : 'Chào bạn'}</h1><p>Workflow tạo gói truyện bốn giai đoạn.</p></div></div>
      <section class="card empty-state"><div><span class="empty-icon">✦</span><h2>Chưa có truyện nào</h2><p>Bắt đầu từ một brief. Hệ thống sẽ tạo nội dung, hình ảnh và prompt video theo workflow có kiểm định.</p><a class="button button-primary" href="#/new">Tạo truyện đầu tiên</a></div></section>`;
    return;
  }
  const attention = runs.filter(item => ['FAILED', 'NEEDS_ATTENTION'].includes(item.status)).slice(0, 3);
  app.innerHTML = `
    <div class="page-head"><div><div class="kicker">Workspace</div><h1>${allStories ? 'Tất cả truyện' : 'Chào buổi sáng'}</h1><p>${allStories ? `${groups.length} workflow · ${runs.length} lần chạy trong workspace local.` : `${attention.length} workflow đang cần bạn kiểm tra.`}</p></div><div class="actions"><a class="button" href="#/inspector">◇ Kiểm tra gói</a><a class="button button-primary" href="#/new">＋ Tạo truyện mới</a></div></div>
    ${!allStories && attention.length ? `<section class="card attention"><div class="attention-head"><div><strong>Cần xử lý</strong><span class="muted small">Giải quyết lỗi trước khi tiếp tục workflow.</span></div><span class="badge badge-danger">${attention.length} vấn đề</span></div>${attention.map(run => `<div class="list-row"><span class="row-icon">!</span><div><div class="row-title">${escapeHtml(run.title)}</div><div class="muted small">${escapeHtml(statusLabels[run.status])} • ${escapeHtml(stageLabels[run.stage] || 'Chưa xác định stage')}</div></div><a class="button" href="#/runs/${encodeURIComponent(run.run_id)}">Xem lần chạy</a></div>`).join('')}</section>` : ''}
    <section class="card card-padding section-space"><div class="card-head"><div><h2>${allStories ? 'Danh sách workflow' : 'Truyện gần đây'}</h2><p>Mỗi truyện hiển thị lần chạy mới nhất trong cùng lineage package.</p></div><button class="button button-ghost" type="button" id="reload-runs">↻ Làm mới</button></div><div class="data-table-wrap"><table class="data-table"><thead><tr><th>Truyện</th><th>Loại nội dung</th><th>Stage hiện tại</th><th>Trạng thái</th><th></th></tr></thead><tbody>${dashboardRows(groups)}</tbody></table></div></section>`;
  document.querySelector('#reload-runs')?.addEventListener('click', refreshRuns);
  if (runs.some(item => item.status === 'RUNNING')) {
    state.jobTimer = window.setTimeout(refreshRuns, Number(state.settings?.job_refresh_seconds || 3) * 1000);
  }
}

function showDeleteRun(runId, title) {
  const modal = document.createElement('div');
  modal.className = 'modal-backdrop';
  modal.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="delete-run-title"><h2 id="delete-run-title">Xóa truyện?</h2><p>“${escapeHtml(title)}”, toàn bộ nội dung, hình ảnh, gói đầu ra và các tác vụ liên quan sẽ bị xóa vĩnh viễn.</p><div class="form-actions"><button class="button" type="button" data-close>Hủy</button><button class="button button-danger" type="button" data-confirm-delete>Xóa truyện</button></div></div>`;
  document.body.append(modal);
  const close = () => modal.remove();
  modal.querySelector('[data-close]').addEventListener('click', close);
  modal.addEventListener('click', event => { if (event.target === modal) close(); });
  const confirm = modal.querySelector('[data-confirm-delete]');
  confirm.addEventListener('click', async () => {
    confirm.disabled = true;
    try {
      const result = await api(`/api/runs/${encodeURIComponent(runId)}`, { method: 'DELETE' });
      state.runs = state.runs.filter(run => run.run_id !== runId);
      state.jobs = state.jobs.filter(job => job.run_id !== runId);
      if (state.currentRun?.run_id === runId) state.currentRun = null;
      close();
      toast(`Đã xóa truyện và ${Number(result.deleted_jobs || 0)} tác vụ liên quan.`);
      if (routeInfo().path.startsWith('/runs/')) location.hash = '#/stories';
      else renderDashboard(routeInfo().path === '/stories');
    } catch (error) {
      toast(error.message, true);
      confirm.disabled = false;
    }
  });
  confirm.focus();
}

async function refreshRuns() {
  try {
    state.runs = (await api('/api/runs')).runs;
    renderRoute();
  } catch (error) { toast(error.message, true); }
}

function renderWizard() {
  const defaults = state.settings || {};
  const durationDefaults = { YOUTH_SAFE: defaults.duration_youth, ADULT_STANDARD: defaults.duration_adult, SERIAL_DETECTIVE: defaults.duration_serial };
  const wizard = { step: 1, profile: defaults.profile || 'YOUTH_SAFE', language: defaults.language || 'vi', minutes: durationDefaults[defaults.profile] || defaults.duration_youth, provider_mode: defaults.provider_mode || 'deterministic', quality_preset: defaults.quality_preset || 'balanced', seen_brief_ids: new Set() };
  const durations = state.config.durations;
  app.innerHTML = `
    <div class="page-head"><div><div class="kicker">Workflow mới</div><h1>Tạo truyện</h1><p>Thiết lập đầu vào cho Nội dung & nhân vật.</p></div><a class="button button-ghost" href="#/">Đóng</a></div>
    <div class="stepper" id="wizard-steps">${['Loại nội dung', 'Brief', 'Cấu hình', 'Kiểm tra'].map((label, index) => `<div class="step${index === 0 ? ' active' : ''}" data-step="${index + 1}"><span class="step-number">${index + 1}</span>${label}</div>`).join('')}</div>
    <form class="form-layout" id="story-form" novalidate>
      <div id="wizard-panel"></div>
      <div class="form-actions"><button class="button" id="wizard-prev" type="button" disabled>Quay lại</button><button class="button button-primary" id="wizard-next" type="button">Tiếp tục</button></div>
    </form>`;
  const form = document.querySelector('#story-form');
  const panel = document.querySelector('#wizard-panel');
  const next = document.querySelector('#wizard-next');
  const prev = document.querySelector('#wizard-prev');

  function durationFor(profile, mode = null) {
    return durations.find(item => item.profile === profile && item.episode_mode === mode) || durations.find(item => item.profile === profile);
  }
  function snapshot() {
    const data = new FormData(form);
    for (const [key, value] of data.entries()) wizard[key] = value;
  }
  function paint() {
    document.querySelectorAll('#wizard-steps .step').forEach(item => {
      const step = Number(item.dataset.step);
      item.classList.toggle('active', step === wizard.step);
      item.classList.toggle('done', step < wizard.step);
    });
    prev.disabled = wizard.step === 1;
    next.textContent = wizard.step === 4 ? 'Tạo nội dung' : 'Tiếp tục';
    if (wizard.step === 1) {
      panel.innerHTML = `<h2>Chọn loại nội dung</h2><p class="muted">Loại nội dung quyết định quy tắc an toàn và thời lượng đề xuất.</p><div class="choice-grid">${[
        ['YOUTH_SAFE', '✦', 'Truyện thiếu nhi', 'Đối tượng 7–10 tuổi, có kiểm tra an toàn nội dung.'],
        ['ADULT_STANDARD', '◐', 'Truyện người lớn', 'Nội dung 18+, giọng kể và chủ đề trưởng thành.'],
        ['SERIAL_DETECTIVE', '⌕', 'Series trinh thám', 'Nhiều tập với continuity được quản lý xuyên suốt.'],
      ].map(item => `<button class="choice${wizard.profile === item[0] ? ' selected' : ''}" type="button" data-profile="${item[0]}"><span class="radio-indicator"></span><span class="choice-icon">${item[1]}</span><strong>${item[2]}</strong><span>${item[3]}</span></button>`).join('')}</div>`;
      panel.querySelectorAll('[data-profile]').forEach(button => button.addEventListener('click', () => { wizard.profile = button.dataset.profile; wizard.minutes = durationDefaults[wizard.profile]; paint(); }));
    } else if (wizard.step === 2) {
      const serial = wizard.profile === 'SERIAL_DETECTIVE';
      const mode = serial ? (wizard.episode_mode || 'START_SERIES') : null;
      const duration = durationFor(wizard.profile, mode);
      panel.innerHTML = `<h2>Nội dung và thời lượng</h2><p class="muted">Cung cấp ý tưởng đủ rõ để hệ thống xây dựng câu chuyện.</p>
        <div class="field"><div class="field-label-row"><label for="brief">Brief</label><button class="button button-ghost button-small" id="random-brief" type="button">✦ Gợi ý Brief</button></div><textarea class="input" id="brief" name="brief" required>${escapeHtml(wizard.brief || '')}</textarea><small>Mô tả chủ đề, nhân vật hoặc xung đột trung tâm. Bạn có thể chọn một gợi ý rồi chỉnh sửa.</small><div id="brief-suggestions" aria-live="polite"></div></div>
        ${serial ? `<div class="field"><label for="episode-mode">Chế độ tập</label><select class="input" id="episode-mode" name="episode_mode"><option value="START_SERIES">Bắt đầu series</option><option value="CONTINUE_SERIES" disabled>Tiếp tục series — cần chọn anchor</option><option value="FINALIZE_SERIES" disabled>Kết thúc series — cần chọn anchor</option></select></div><div class="field"><label for="series-title">Tên series</label><input class="input" id="series-title" name="series_title" value="${escapeHtml(wizard.series_title || '')}" required></div>` : ''}
        <div class="grid grid-two"><div class="field"><label for="language">Ngôn ngữ</label><select class="input" id="language" name="language"><option value="vi" ${wizard.language === 'vi' ? 'selected' : ''}>Tiếng Việt</option><option value="en" ${wizard.language === 'en' ? 'selected' : ''}>English</option></select></div><div class="field"><label for="minutes">Thời lượng mục tiêu</label><input class="input" id="minutes" name="minutes" type="number" min="${duration.length_min}" max="${duration.length_max}" value="${escapeHtml(wizard.minutes || duration.length_target)}" required><small>Khoảng hợp lệ: ${duration.length_min}–${duration.length_max} phút.</small></div></div>
        <label class="checkbox"><input type="checkbox" name="confirmed" value="yes" ${wizard.confirmed === 'yes' ? 'checked' : ''}> Tôi xác nhận thời lượng mục tiêu.</label><div class="field-error" id="wizard-error" role="alert"></div>`;
      panel.querySelector('#random-brief').addEventListener('click', async event => {
        const button = event.currentTarget;
        const language = panel.querySelector('#language').value || 'vi';
        button.disabled = true;
        button.textContent = 'Đang tìm ý tưởng…';
        try {
          const excluded = [...wizard.seen_brief_ids].join(',');
          const result = await api(`/api/briefs/random?profile=${encodeURIComponent(wizard.profile)}&language=${encodeURIComponent(language)}&count=3&exclude=${encodeURIComponent(excluded)}`);
          const items = Array.isArray(result.suggestion_items) ? result.suggestion_items : (result.suggestions || [result.brief]).map((brief, index) => ({id: `legacy-${index}-${brief}`, brief}));
          items.forEach(item => wizard.seen_brief_ids.add(item.id));
          const suggestionPanel = panel.querySelector('#brief-suggestions');
          suggestionPanel.innerHTML = `<section class="brief-suggestions"><div class="brief-suggestions-head"><strong>Chọn một ý tưởng</strong><span>${items.length} gợi ý mới</span></div>${items.map((item, index) => `<button class="brief-suggestion" type="button" data-suggestion-index="${index}"><span>${index + 1}</span><span>${escapeHtml(item.brief)}</span></button>`).join('')}</section>`;
          suggestionPanel.querySelectorAll('[data-suggestion-index]').forEach(option => option.addEventListener('click', () => {
            const brief = items[Number(option.dataset.suggestionIndex)].brief;
            const textarea = panel.querySelector('#brief');
            textarea.value = brief;
            wizard.brief = brief;
            suggestionPanel.innerHTML = '';
            textarea.focus();
            textarea.setSelectionRange(textarea.value.length, textarea.value.length);
          }));
        } catch (error) { toast(error.message, true); }
        finally { button.disabled = false; button.textContent = '✦ Gợi ý Brief'; }
      });
    } else if (wizard.step === 3) {
      panel.innerHTML = `<h2>Cấu hình đầu ra</h2><p class="muted">Hệ thống sẽ dùng cấu hình mặc định của dự án. Chỉ mở phần nâng cao khi bạn cần thay đổi cách tạo đầu ra.</p>
        <section class="card card-padding"><dl class="detail-list" style="margin:0"><dt>Chất lượng</dt><dd>${escapeHtml(({fast:'Nhanh',balanced:'Cân bằng',quality:'Chất lượng cao'})[wizard.quality_preset] || wizard.quality_preset)}</dd><dt>Chế độ ảnh</dt><dd>ZONE</dd><dt>Nơi lưu</dt><dd>Workspace local</dd></dl></section>
        <details class="advanced-options"><summary>Tùy chọn nâng cao</summary><div class="advanced-options-body"><div class="field"><label for="provider-mode">Provider</label><select class="input" id="provider-mode" name="provider_mode">
          <option value="deterministic" ${wizard.provider_mode === 'deterministic' ? 'selected' : ''}>Deterministic — kiểm thử nhanh</option>
          <option value="hybrid" ${wizard.provider_mode === 'hybrid' ? 'selected' : ''}>Hybrid — LLM local, ảnh deterministic</option>
          <option value="text_local" ${wizard.provider_mode === 'text_local' ? 'selected' : ''}>Text local — story + safety local, ảnh deterministic</option>
          <option value="local" ${wizard.provider_mode === 'local' ? 'selected' : ''}>Local production — LLM + Diffusers + QA</option>
        </select><small>Local production cần llama.cpp, model Diffusers, IP-Adapter, CLIP và Tesseract.</small></div>
        ${presetField(wizard.quality_preset)}
        <div id="stage-models">${wizard.provider_mode === 'deterministic' ? '<p class="muted small">Chế độ deterministic không dùng model AI.</p>' : `${modelField('story', wizard.model_story)}${wizard.provider_mode === 'local' ? modelField('character_image', wizard.model_character_image) : ''}${['local','text_local'].includes(wizard.provider_mode) ? modelField('safety', wizard.model_safety) : ''}`}</div>
        </div></details>`;
      panel.querySelector('#provider-mode').addEventListener('change', event => { snapshot(); wizard.provider_mode = event.target.value; paint(); });
    } else {
      panel.innerHTML = `<h2>Kiểm tra trước khi tạo</h2><p class="muted">Xác nhận thông tin trước khi khởi chạy.</p><section class="card card-padding"><dl class="detail-list" style="margin:0"><dt>Loại nội dung</dt><dd>${escapeHtml(profileLabels[wizard.profile])}</dd><dt>Brief</dt><dd>${escapeHtml(wizard.brief)}</dd><dt>Ngôn ngữ</dt><dd>${wizard.language === 'en' ? 'English' : 'Tiếng Việt'}</dd><dt>Thời lượng</dt><dd>${escapeHtml(wizard.minutes)} phút • đã xác nhận</dd><dt>Provider</dt><dd>${escapeHtml(wizard.provider_mode)}</dd>${wizard.profile === 'SERIAL_DETECTIVE' ? `<dt>Series</dt><dd>${escapeHtml(wizard.series_title)}</dd>` : ''}</dl></section>`;
    }
  }
  prev.addEventListener('click', () => { snapshot(); wizard.step = Math.max(1, wizard.step - 1); paint(); });
  next.addEventListener('click', async () => {
    snapshot();
    if (wizard.step === 2) {
      const error = panel.querySelector('#wizard-error');
      const duration = durationFor(wizard.profile, wizard.profile === 'SERIAL_DETECTIVE' ? 'START_SERIES' : null);
      if (!String(wizard.brief || '').trim()) { error.textContent = 'Vui lòng nhập brief.'; return; }
      if (wizard.profile === 'SERIAL_DETECTIVE' && !String(wizard.series_title || '').trim()) { error.textContent = 'Vui lòng nhập tên series.'; return; }
      if (Number(wizard.minutes) < duration.length_min || Number(wizard.minutes) > duration.length_max) { error.textContent = `Thời lượng phải từ ${duration.length_min} đến ${duration.length_max} phút.`; return; }
      if (wizard.confirmed !== 'yes') { error.textContent = 'Bạn cần xác nhận thời lượng.'; return; }
    }
    if (wizard.step < 4) { wizard.step += 1; paint(); return; }
    next.disabled = true;
    try {
      const model_selection = stage1ModelSelection(wizard);
      const job = await api('/api/jobs/stage1', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile: wizard.profile, brief: wizard.brief, language: wizard.language || 'vi', minutes: Number(wizard.minutes), episode_mode: wizard.profile === 'SERIAL_DETECTIVE' ? 'START_SERIES' : null, series_title: wizard.series_title || null, provider_mode: wizard.provider_mode || 'deterministic', quality_preset: wizard.quality_preset || 'balanced', auto_advance: Boolean(defaults.auto_advance), render_tts: Boolean(defaults.render_tts), aspect_ratio: defaults.aspect_ratio || 'LANDSCAPE_16_9', model_selection, idempotency_key: crypto.randomUUID() }) });
      showJob(job);
    } catch (error) { toast(error.message, true); next.disabled = false; }
  });
  paint();
}

function showJob(job) {
  document.querySelector('.modal-backdrop')?.remove();
  const modal = document.createElement('div');
  modal.className = 'modal-backdrop';
  modal.innerHTML = `<section class="modal job-modal" role="dialog" aria-modal="true" aria-labelledby="job-title" aria-describedby="job-description">
    <div class="job-modal-head"><div><div class="kicker">${escapeHtml(jobStageLabel(job))}</div><h2 id="job-title">Đang xử lý workflow</h2></div><div class="spinner" aria-hidden="true"></div></div>
    <div class="job-current" aria-live="polite"><p id="job-description">${escapeHtml(job.progress_message || 'Đang chờ cập nhật')}</p><strong id="job-percent">${Number(job.progress_percent || 0)}%</strong></div>
    <div class="job-progress" role="progressbar" aria-label="Tiến độ workflow" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Number(job.progress_percent || 0)}"><span id="job-progress-bar" style="width:${Number(job.progress_percent || 0)}%"></span></div>
    <ol class="job-steps" id="job-steps" aria-label="Các mốc xử lý"></ol>
    <div class="job-stale-notice" id="job-stale-notice" role="status" hidden></div>
    <dl class="job-detail-grid"><div><dt>Bước hiện tại</dt><dd id="job-phase"></dd></div><div><dt>Stage</dt><dd id="job-stage"></dd></div><div><dt>Tài nguyên</dt><dd id="job-resource"></dd></div><div><dt>Lần chạy</dt><dd id="job-attempt"></dd></div><div><dt>Thời gian đã chạy</dt><dd id="job-elapsed"></dd></div><div><dt>Cập nhật lúc</dt><dd id="job-updated"></dd></div></dl>
    <details class="job-technical"><summary>Chi tiết kỹ thuật</summary><dl><dt>Provider</dt><dd id="job-provider"></dd><dt>Model</dt><dd id="job-models"></dd><dt>Job ID</dt><dd>${escapeHtml(job.job_id)}</dd><dt>Run ID</dt><dd id="job-run-id"></dd></dl></details>
    <div class="job-actions"><div class="badge badge-warning" id="job-state">${escapeHtml(statusLabels[job.state] || job.state)}</div><div class="actions"><button class="button" id="job-background" type="button">Đóng và tiếp tục chạy</button><button class="button button-ghost" id="job-cancel" type="button">Hủy tác vụ</button></div></div>
  </section>`;
  document.body.append(modal);
  let dismiss = () => {};
  const moveToBackground = () => { showBackgroundJob(job); dismiss(); };
  dismiss = activateDialog(modal, moveToBackground);
  updateJobModal(modal, job);
  modal.querySelector('#job-background').addEventListener('click', moveToBackground);
  modal.querySelector('#job-cancel').addEventListener('click', async event => {
    event.currentTarget.disabled = true;
    try { await api(`/api/jobs/${encodeURIComponent(job.job_id)}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); }
    catch (error) { toast(error.message, true); event.currentTarget.disabled = false; }
  });
  pollJob(job.job_id, modal);
}

async function pollJob(jobId, modal) {
  try {
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (!modal?.isConnected) { showBackgroundJob(job); pollJobInBackground(jobId); return; }
    updateJobModal(modal, job);
    if (job.state === 'SUCCEEDED') {
      modal.remove();
      state.runs = (await api('/api/runs')).runs;
      toast('Workflow đã tạo đầu ra thành công.');
      location.hash = `#/runs/${encodeURIComponent(job.run_id)}`;
      return;
    }
    if (job.state === 'FAILED' || job.state === 'CANCELLED') {
      modal.querySelector('.spinner')?.remove();
      modal.querySelector('#job-title').textContent = job.state === 'CANCELLED' ? 'Workflow đã hủy' : 'Workflow thất bại';
      modal.querySelector('#job-description').textContent = job.error || job.progress_message || 'Không có chi tiết lỗi.';
      modal.querySelector('#job-state').className = `badge badge-${job.state === 'FAILED' ? 'danger' : 'warning'}`;
      modal.querySelector('#job-cancel')?.remove();
      const actions = modal.querySelector('.job-actions');
      if (job.retryable) { const retry = document.createElement('button'); retry.className = 'button button-primary'; retry.textContent = 'Thử lại'; retry.addEventListener('click', async () => { retry.disabled = true; try { const next = await api(`/api/jobs/${encodeURIComponent(job.job_id)}/retry`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); modal.remove(); showJob(next); } catch (error) { toast(error.message, true); retry.disabled = false; } }); actions.append(retry); }
      const close = document.createElement('button'); close.className = 'button'; close.textContent = 'Đóng'; close.addEventListener('click', () => modal.remove()); actions.append(close);
      return;
    }
    state.jobTimer = setTimeout(() => pollJob(jobId, modal), 800);
  } catch (error) {
    modal.remove(); toast(error.message, true);
  }
}

async function pollJobInBackground(jobId) {
  try {
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (job.state === 'SUCCEEDED') {
      clearBackgroundJob();
      state.runs = (await api('/api/runs')).runs;
      toast('Workflow đã hoàn tất. Mở Tác vụ hoặc Truyện để xem kết quả.');
      return;
    }
    if (job.state === 'FAILED' || job.state === 'CANCELLED') {
      clearBackgroundJob(); toast(job.error || statusLabels[job.state], job.state === 'FAILED'); return;
    }
    showBackgroundJob(job);
    state.jobTimer = setTimeout(() => pollJobInBackground(jobId), 800);
  } catch (error) { clearBackgroundJob(); toast(error.message, true); }
}

function jobSummaryCard(label, value, status, kind) {
  const active = state.jobsUi.status === status;
  return `<button class="job-stat job-stat-${kind}" type="button" data-job-summary="${status}" aria-pressed="${active}"><span>${escapeHtml(label)}</span><strong>${value}</strong></button>`;
}

function filteredJobs() {
  const ui = state.jobsUi;
  const query = ui.query.trim().toLocaleLowerCase('vi');
  const now = Date.now();
  const periodMs = { DAY: 86400000, WEEK: 604800000, MONTH: 2592000000 }[ui.period];
  const jobs = state.jobs.filter(job => {
    const haystack = `${jobOperationLabel(job)} ${job.operation || ''} ${job.job_id || ''} ${job.run_id || ''}`.toLocaleLowerCase('vi');
    if (query && !haystack.includes(query)) return false;
    if (ui.status !== 'ALL' && job.state !== ui.status) return false;
    if (ui.resource !== 'ALL' && job.resource_class !== ui.resource) return false;
    if (periodMs && now - new Date(job.created_at).getTime() > periodMs) return false;
    return true;
  });
  return jobs.sort((left, right) => {
    if (ui.sort === 'OLDEST') return new Date(left.created_at) - new Date(right.created_at);
    if (ui.sort === 'PROGRESS') return Number(right.progress_percent || 0) - Number(left.progress_percent || 0);
    return new Date(right.created_at) - new Date(left.created_at);
  });
}

function renderJobsView() {
  const jobs = filteredJobs();
  const ui = state.jobsUi;
  const totalPages = Math.max(1, Math.ceil(jobs.length / ui.pageSize));
  ui.page = Math.min(ui.page, totalPages);
  const start = (ui.page - 1) * ui.pageSize;
  const pageJobs = jobs.slice(start, start + ui.pageSize);
  const counts = state.jobs.reduce((result, job) => { result[job.state] = (result[job.state] || 0) + 1; return result; }, {});
  const runningCount = counts.RUNNING || 0;
  const hasFilters = ui.query || ui.status !== 'ALL' || ui.resource !== 'ALL' || ui.period !== 'ALL';
  const updatedAt = new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date());
  app.innerHTML = `<div class="page-head"><div><div class="kicker">Vận hành</div><h1>Tác vụ</h1><p>Theo dõi hàng đợi, tiến độ và xử lý nhanh các workflow cần chú ý.</p></div><div class="jobs-refresh"><span class="muted small">Cập nhật lúc ${updatedAt}</span><button class="button" id="reload-jobs" type="button">↻ Làm mới</button></div></div>
    <section class="job-summary" aria-label="Tổng quan tác vụ">
      ${jobSummaryCard('Đang chạy', runningCount, 'RUNNING', 'brand')}
      ${jobSummaryCard('Đang chờ', counts.QUEUED || 0, 'QUEUED', 'warning')}
      ${jobSummaryCard('Hoàn thành', counts.SUCCEEDED || 0, 'SUCCEEDED', 'success')}
      ${jobSummaryCard('Thất bại', counts.FAILED || 0, 'FAILED', 'danger')}
    </section>
    <section class="card jobs-panel">
      <div class="jobs-toolbar">
        <label class="jobs-search"><span class="sr-only">Tìm tác vụ</span><span aria-hidden="true">⌕</span><input class="input" id="job-search" value="${escapeHtml(ui.query)}" placeholder="Tìm tên tác vụ, Job ID hoặc Run ID…"></label>
        <label><span class="sr-only">Trạng thái</span><select class="input" id="job-status"><option value="ALL">Mọi trạng thái</option>${Object.entries({QUEUED:'Đang chờ',RUNNING:'Đang xử lý',SUCCEEDED:'Hoàn thành',FAILED:'Thất bại',CANCELLED:'Đã hủy'}).map(([value,label]) => `<option value="${value}" ${ui.status === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
        <label><span class="sr-only">Tài nguyên</span><select class="input" id="job-resource"><option value="ALL">CPU và GPU</option><option value="CPU" ${ui.resource === 'CPU' ? 'selected' : ''}>CPU</option><option value="GPU" ${ui.resource === 'GPU' ? 'selected' : ''}>GPU</option></select></label>
        <label><span class="sr-only">Thời gian</span><select class="input" id="job-period"><option value="ALL">Mọi thời gian</option><option value="DAY" ${ui.period === 'DAY' ? 'selected' : ''}>24 giờ qua</option><option value="WEEK" ${ui.period === 'WEEK' ? 'selected' : ''}>7 ngày qua</option><option value="MONTH" ${ui.period === 'MONTH' ? 'selected' : ''}>30 ngày qua</option></select></label>
        <label><span class="sr-only">Sắp xếp</span><select class="input" id="job-sort"><option value="NEWEST" ${ui.sort === 'NEWEST' ? 'selected' : ''}>Mới nhất</option><option value="OLDEST" ${ui.sort === 'OLDEST' ? 'selected' : ''}>Cũ nhất</option><option value="PROGRESS" ${ui.sort === 'PROGRESS' ? 'selected' : ''}>Tiến độ cao nhất</option></select></label>
        ${hasFilters ? '<button class="button button-ghost" id="clear-job-filters" type="button">Xóa bộ lọc</button>' : ''}
      </div>
      <div class="jobs-results"><strong>${jobs.length} tác vụ</strong><span class="muted small">${state.jobs.some(job => ['QUEUED','RUNNING'].includes(job.state)) ? '● Tự động cập nhật' : 'Lịch sử workspace local'}</span></div>
      <div class="data-table-wrap"><table class="data-table jobs-table"><thead><tr><th>Tác vụ</th><th>Trạng thái</th><th>Tiến độ</th><th>Tài nguyên</th><th>Bắt đầu</th><th>Thời lượng</th><th>Hành động</th></tr></thead><tbody>${pageJobs.map(job => {
        const percent = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
        const error = job.state === 'FAILED' && job.error ? `<div class="job-error" title="${escapeHtml(job.error)}">${escapeHtml(job.error)}</div>` : '';
        return `<tr class="job-row job-row-${String(job.state || '').toLowerCase()}"><td><strong>${escapeHtml(jobOperationLabel(job))}</strong><div class="muted small job-id"><span>${escapeHtml(job.job_id)}</span> · Lần chạy ${job.attempt || 1}</div>${error}</td><td>${statusBadge(job.state)}</td><td><div class="compact-progress progress-${jobProgressKind(job)}" role="progressbar" aria-label="Tiến độ" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span style="width:${percent}%"></span></div><div class="muted small">${escapeHtml(jobPhaseLabel(job.progress_phase))} · ${percent}%</div></td><td><span class="resource-pill">${escapeHtml(job.resource_class || 'CPU')}</span></td><td><span title="${escapeHtml(formatDate(job.started_at || job.created_at))}">${escapeHtml(formatDate(job.started_at || job.created_at))}</span></td><td>${escapeHtml(formatElapsed(job.started_at, job.completed_at))}</td><td><div class="actions job-actions-cell">${job.retryable && ['FAILED','CANCELLED'].includes(job.state) ? `<button class="button button-small" data-retry-job="${escapeHtml(job.job_id)}" type="button">↻ Thử lại</button>` : ''}${['QUEUED','RUNNING'].includes(job.state) ? `<button class="button button-ghost button-small" data-cancel-job="${escapeHtml(job.job_id)}" type="button">Hủy</button>` : ''}${job.run_id ? `<a class="button button-small" href="#/runs/${encodeURIComponent(job.run_id)}">Chi tiết →</a>` : '<span class="muted small">Chưa có kết quả</span>'}</div></td></tr>`;
      }).join('') || `<tr><td colspan="7"><div class="jobs-empty"><strong>${hasFilters ? 'Không tìm thấy tác vụ phù hợp' : 'Chưa có tác vụ'}</strong><span class="muted">${hasFilters ? 'Hãy thử thay đổi hoặc xóa bộ lọc.' : 'Tác vụ mới sẽ xuất hiện tại đây.'}</span>${hasFilters ? '<button class="button" id="empty-clear-job-filters" type="button">Xóa bộ lọc</button>' : ''}</div></td></tr>`}</tbody></table></div>
      ${jobs.length ? `<div class="jobs-pagination"><span class="muted small">Hiển thị ${start + 1}–${Math.min(start + ui.pageSize, jobs.length)} trong ${jobs.length}</span><div class="actions"><button class="button button-small" id="jobs-prev" ${ui.page === 1 ? 'disabled' : ''}>← Trước</button><span class="small">Trang ${ui.page}/${totalPages}</span><button class="button button-small" id="jobs-next" ${ui.page === totalPages ? 'disabled' : ''}>Sau →</button></div></div>` : ''}
    </section>`;

  document.querySelector('#reload-jobs').addEventListener('click', renderJobs);
  document.querySelector('#job-search').addEventListener('input', event => { ui.query = event.target.value; ui.page = 1; renderJobsView(); document.querySelector('#job-search').focus(); document.querySelector('#job-search').setSelectionRange(ui.query.length, ui.query.length); });
  [['job-status','status'],['job-resource','resource'],['job-period','period'],['job-sort','sort']].forEach(([id,key]) => document.querySelector(`#${id}`).addEventListener('change', event => { ui[key] = event.target.value; ui.page = 1; renderJobsView(); }));
  const clearFilters = () => { state.jobsUi = { ...state.jobsUi, query: '', status: 'ALL', resource: 'ALL', period: 'ALL', page: 1 }; renderJobsView(); };
  document.querySelector('#clear-job-filters')?.addEventListener('click', clearFilters);
  document.querySelector('#empty-clear-job-filters')?.addEventListener('click', clearFilters);
  document.querySelectorAll('[data-job-summary]').forEach(button => button.addEventListener('click', () => { ui.status = ui.status === button.dataset.jobSummary ? 'ALL' : button.dataset.jobSummary; ui.page = 1; renderJobsView(); }));
  document.querySelector('#jobs-prev')?.addEventListener('click', () => { ui.page -= 1; renderJobsView(); });
  document.querySelector('#jobs-next')?.addEventListener('click', () => { ui.page += 1; renderJobsView(); });
  document.querySelectorAll('[data-cancel-job]').forEach(button => button.addEventListener('click', async () => { button.disabled = true; try { await api(`/api/jobs/${encodeURIComponent(button.dataset.cancelJob)}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast('Đã gửi yêu cầu hủy tác vụ.'); await renderJobs(); } catch (error) { toast(error.message, true); button.disabled = false; } }));
  document.querySelectorAll('[data-retry-job]').forEach(button => button.addEventListener('click', async () => { button.disabled = true; try { const job = await api(`/api/jobs/${encodeURIComponent(button.dataset.retryJob)}/retry`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast('Đã tạo lần chạy mới.'); showJob(job); } catch (error) { toast(error.message, true); button.disabled = false; } }));
}

async function renderJobs() {
  if (state.jobTimer) { clearTimeout(state.jobTimer); state.jobTimer = null; }
  state.jobs = (await api('/api/jobs')).jobs;
  renderJobsView();
  if (state.jobs.some(job => ['QUEUED','RUNNING'].includes(job.state))) state.jobTimer = window.setTimeout(renderJobs, Number(state.settings?.job_refresh_seconds || 3) * 1000);
}

function artifactGroup(artifacts, prefix) {
  return artifacts.filter(item => item.path.startsWith(prefix));
}

function storyText(script) {
  return (script || []).map(item => {
    if (typeof item === 'string') return item;
    return item.text || item.content || JSON.stringify(item);
  }).join('\n\n');
}

function characterPreview(run) {
  const characters = run.story?.characters || [];
  const imageArtifacts = new Set(
    (run.artifacts || []).filter(item => item.kind === 'image').map(item => item.path),
  );
  const cards = characters.map(character => {
    const referencePath = character.reference_asset?.reference_image;
    const fallbackPath = character.character_id ? `characters/${character.character_id}.png` : '';
    const imagePath = [referencePath, fallbackPath].find(path => path && imageArtifacts.has(path));
    const ageMin = character.canonical_age_min;
    const ageMax = character.canonical_age_max;
    const age = ageMin == null ? '' : ageMin === ageMax ? `${ageMin} tuổi` : `${ageMin}–${ageMax} tuổi`;
    const details = [character.role, age].filter(Boolean).map(escapeHtml).join(' · ');
    const image = imagePath
      ? `<img class="character-image" src="/api/runs/${encodeURIComponent(run.run_id)}/artifact?path=${encodeURIComponent(imagePath)}" alt="Ảnh nhân vật ${escapeHtml(character.name || character.character_id || '')}" loading="lazy">`
      : '<div class="character-image character-image-placeholder" aria-label="Chưa có ảnh nhân vật">◇</div>';
    return `<figure class="character-card">${image}<figcaption><strong>${escapeHtml(character.name || character.character_id || 'Nhân vật')}</strong>${details ? `<span>${details}</span>` : ''}</figcaption></figure>`;
  }).join('');
  if (!cards) return '';
  return `<section class="character-preview" aria-labelledby="character-preview-title"><div class="character-preview-head"><h3 id="character-preview-title">Nhân vật</h3><span>${characters.length} nhân vật</span></div><div class="character-grid">${cards}</div></section>`;
}

function renderRun(run) {
  try {
    const pendingReturn = JSON.parse(sessionStorage.getItem('ai-story-validation-return') || 'null');
    if (pendingReturn?.started_at && Date.now() - pendingReturn.started_at < 5 * 60 * 1000) {
      trackUx('WORKSPACE_RETURNED', { stage: run.stage || 'UNKNOWN', elapsed_ms: Math.max(0, Date.now() - pendingReturn.started_at) });
    }
    sessionStorage.removeItem('ai-story-validation-return');
  } catch { sessionStorage.removeItem('ai-story-validation-return'); }
  const stageNumber = Number(String(run.stage || 'STAGE1').replace('STAGE', '')) || 1;
  const validation = run.validation?.records || [];
  const failed = validation.filter(item => !['PASS', 'ASSESSED_PASS'].includes(item.status));
  const hasOpenErrors = Number(run.validation?.blocking_count || 0) > 0;
  const nextStage = stageNumber < 4 ? stageNumber + 1 : null;
  const qualityBlocked = failed.length > 0 || run.package?.content_quality_status !== 'PASS';
  const isFixture = run.package?.artifact_class === 'TEST_FIXTURE';
  const releaseReady = !qualityBlocked && !isFixture;
  const refinement = run.validation?.refinement;
  const refinementResolved = refinement && Number(refinement.open_defect_count || 0) === 0;
  const refinementStatus = refinementResolved ? 'REPAIRED' : refinement?.refinement_status;
  const refinementSummary = refinement && Number(refinement.initial_defect_count || 0) > 0
    ? `<div class="validation-banner"${refinementResolved ? ' style="background:var(--success-soft);color:var(--success)"' : ''}><strong>Repair: ${escapeHtml(refinementStatus)}</strong><span>Đã đóng ${Number(refinement.closed_defect_count || 0)}/${Number(refinement.initial_defect_count || 0)} lỗi; còn ${Number(refinement.open_defect_count || 0)} lỗi mở.</span></div>`
    : '';
  const telemetry = run.telemetry_reconciliation;
  const telemetryWarning = telemetry?.status === 'FAIL'
    ? `<div class="validation-banner"><strong>Telemetry lệch chuẩn</strong><span>Độ lệch ${Number(telemetry.deviation_percent || 0).toFixed(2)}%, vượt ngưỡng ${Number(telemetry.maximum_deviation_percent || 5).toFixed(2)}%.</span></div>`
    : '';
  const imageEvidence = run.package_quality_report?.image_evidence || {};
  const imageAssessments = [
    ...(imageEvidence.landscape_assessments || []),
    ...(imageEvidence.portrait_assessments || []),
  ];
  const qaLayers = imageAssessments.flatMap(item => item.qa_layers || []);
  const qaLayerSummary = Object.entries(qaLayers.reduce((summary, layer) => {
    const key = layer.layer || 'UNKNOWN';
    summary[key] = summary[key] || { total: 0, failed: 0 };
    summary[key].total += 1;
    if (['FAIL', 'ASSESSED_FAIL'].includes(layer.status)) summary[key].failed += 1;
    return summary;
  }, {}));
  const repairAttempts = imageAssessments.reduce((total, item) => total + (item.repair_history || []).length, 0);
  const assistedImages = imageAssessments.filter(item => item.assist_provenance?.workflow === 'MANUAL_OPTIONAL_NO_API').length;
  const learnedUpscales = imageAssessments.filter(item => item.upscale_postprocess?.mode === 'LATENT_X2_PLUS_RESIDUAL').length;
  const visualQualitySummary = imageAssessments.length ? `<div class="validation-banner" style="background:var(--surface-subtle)"><strong>QA hình ảnh đa tầng</strong><span>${imageAssessments.length} assessment · ${repairAttempts} repair attempt · ${learnedUpscales} learned upscale · ${assistedImages} Web Assist</span><ul>${qaLayerSummary.map(([name,value]) => `<li><strong>${escapeHtml(name)}</strong>: ${value.total - value.failed}/${value.total} đạt</li>`).join('')}</ul></div>` : '';
  const releaseChecks = run.release_evaluation?.checks || [];
  const failedReleaseChecks = releaseChecks.filter(item => item.status !== 'PASS');
  const releaseGateSummary = releaseChecks.length ? `<div class="validation-banner" style="background:var(--surface-subtle)"><strong>Release gates: ${escapeHtml(run.release_evaluation.readiness)}</strong><span>${releaseChecks.length - failedReleaseChecks.length}/${releaseChecks.length} gate đạt trong snapshot phát triển.</span>${failedReleaseChecks.length ? `<ul>${failedReleaseChecks.slice(0, 6).map(item => `<li><strong>${escapeHtml(item.id)}</strong>: FAIL</li>`).join('')}</ul>` : ''}</div>` : '';
  const canAdvance = Boolean(nextStage && run.status === 'SUCCEEDED' && run.package?.allowed_next_stage && run.quality_decision?.advancement_status === 'ALLOWED' && !hasOpenErrors && !qualityBlocked);
  const advancementBlocked = Boolean(nextStage && (hasOpenErrors || qualityBlocked));
  const blockingFindings = failed.flatMap(item => (item.findings || []).map(finding => ({ gate: validationTitle(item), finding }))).slice(0, 5);
  const activeTab = state.runTabs[run.run_id] || 'result';
  app.innerHTML = `
    <div class="page-head"><div><div class="kicker">${escapeHtml(profileLabels[run.profile] || run.profile)}</div><h1>${escapeHtml(run.title)}</h1><div class="actions" style="margin-top:9px">${statusBadge(run.status)}<span class="badge ${releaseReady ? 'badge-success' : 'badge-warning'}">${releaseReady ? 'Sẵn sàng phát hành' : 'Chưa khuyến nghị phát hành'}</span><span class="muted small">${escapeHtml(run.run_id)}</span></div></div><div class="actions">${run.output_package ? `<a class="button" href="/api/runs/${encodeURIComponent(run.run_id)}/package">↓ Tải package${releaseReady ? '' : ' kèm cảnh báo'}</a>` : ''}<button class="button button-danger" type="button" id="delete-current-run">Xóa truyện</button></div></div>
    <div class="stage-bar" role="list" aria-label="Các stage">${[1,2,3,4].map(number => `<div class="stage-button" role="listitem" aria-current="${number === stageNumber ? 'step' : 'false'}" aria-disabled="${number > stageNumber || !canAdvance}"><span class="stage-index">0${number}</span><strong>${stageLabels[`STAGE${number}`]}</strong><small>${number < stageNumber ? 'Đã hoàn thành' : number === stageNumber ? statusLabels[run.status] : number === stageNumber + 1 && canAdvance ? 'Sẵn sàng' : number === stageNumber + 1 && advancementBlocked ? 'Bị chặn bởi kiểm định' : 'Chưa chạy'}</small></div>`).join('')}</div>
    <div class="grid grid-two"><section class="card card-padding"><div class="card-head"><div><h2>${escapeHtml(stageLabels[run.stage] || 'Kết quả')}</h2><p>${run.artifacts.length} artifact trong workspace.</p></div></div><div class="tab-bar" role="tablist" aria-label="Nội dung workspace"><button class="tab-button" id="run-tab-result" type="button" role="tab" aria-controls="run-panel" aria-selected="${activeTab === 'result'}" tabindex="${activeTab === 'result' ? '0' : '-1'}" data-run-tab="result">Kết quả</button><button class="tab-button" id="run-tab-artifacts" type="button" role="tab" aria-controls="run-panel" aria-selected="${activeTab === 'artifacts'}" tabindex="${activeTab === 'artifacts' ? '0' : '-1'}" data-run-tab="artifacts">Tệp đầu ra</button><button class="tab-button" id="run-tab-technical" type="button" role="tab" aria-controls="run-panel" aria-selected="${activeTab === 'technical'}" tabindex="${activeTab === 'technical' ? '0' : '-1'}" data-run-tab="technical">Kỹ thuật</button></div><div id="run-panel" role="tabpanel" aria-live="polite"></div></section>
      <aside class="card card-padding"><div class="card-head"><div><h2>Kiểm định nội dung</h2><p>${validation.length} kiểm tra được ghi nhận.</p></div>${hasOpenErrors ? `<span class="badge badge-danger">Có lỗi chặn</span>` : releaseReady ? '<span class="badge badge-success">Đủ điều kiện phát hành</span>' : '<span class="badge badge-warning">Chưa sẵn sàng phát hành</span>'}</div>${isFixture ? '<div class="validation-banner"><strong>Artefact kiểm thử</strong><span>Chỉ dùng để kiểm thử; chưa đủ điều kiện phát hành production.</span></div>' : ''}${telemetryWarning}${visualQualitySummary}${releaseGateSummary}${hasOpenErrors ? `<div class="validation-banner"><strong>Cần xử lý trước khi chạy stage tiếp theo</strong><span>Có ${failed.length} kiểm tra chưa đạt hoặc chưa xác minh. Hãy mở kiểm định để xem bằng chứng và hành động đề xuất.</span>${blockingFindings.length ? `<ul>${blockingFindings.map(item => `<li><strong>${escapeHtml(item.gate)}</strong>: ${escapeHtml(findingSummary(item.finding))}</li>`).join('')}</ul>` : ''}</div>` : canAdvance ? '<div class="validation-banner" style="background:var(--success-soft);color:var(--success)"><strong>Có thể chạy stage tiếp theo</strong><span>Không có lỗi kiểm định đang mở. Trạng thái phát hành được đánh giá riêng.</span></div>' : '<div class="validation-banner" style="background:var(--success-soft);color:var(--success)"><strong>Không có lỗi kiểm định đang mở</strong><span>Kiểm tra điều kiện phát hành trước khi tải package cuối.</span></div>'}${refinementSummary}<div class="validation-list">${validation.slice(0, 5).map(item => `<div class="validation-row"><span class="validation-icon ${item.status === 'PASS' ? 'success' : item.status === 'NOT_VERIFIED' ? 'warning' : ''}">${item.status === 'PASS' ? '✓' : '!'}</span><div><div class="row-title">${escapeHtml(validationTitle(item))}</div><div class="muted small">${escapeHtml(validationLabels[item.status] || item.status)}${item.status !== 'PASS' && item.findings?.length ? ` · ${escapeHtml(findingSummary(item.findings[0]))}` : ''}</div></div></div>`).join('') || '<p class="muted small">Stage này không cung cấp gate record chi tiết.</p>'}</div><a class="button button-block" href="#/validation?run=${encodeURIComponent(run.run_id)}">Mở kiểm định</a>${hasOpenErrors && stageNumber === 1 ? '<button class="button button-primary button-block" id="repair-open-errors" type="button" style="margin-top:8px">Repair lỗi mở</button>' : ''}${canAdvance ? `<button class="button button-primary button-block" id="run-next-stage" type="button" style="margin-top:8px">Chạy ${stageLabels[`STAGE${nextStage}`]}</button>` : ''}</aside></div>
    <div class="activity">${run.events.slice(0, 5).map(event => `<span>${escapeHtml(formatDate(event.timestamp))} · ${escapeHtml(event.event)}</span>`).join('')}</div>`;
  const panel = document.querySelector('#run-panel');
  function paintTab(tab) {
    state.runTabs[run.run_id] = tab;
    saveUiSession();
    document.querySelectorAll('[data-run-tab]').forEach(button => {
      const selected = button.dataset.runTab === tab;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    panel.setAttribute('aria-labelledby', `run-tab-${tab}`);
    if (tab === 'result') {
      const imagePrefix = { STAGE1: 'characters/', STAGE2: 'landscape/', STAGE3: 'portrait/' }[run.stage];
      const images = run.artifacts.filter(item => item.kind === 'image' && imagePrefix && item.path.startsWith(imagePrefix));
      if (run.stage === 'STAGE1' && run.story) {
        const fullStory = storyText(run.story.script);
        const excerpt = storyText((run.story.script || []).slice(0, 2));
        panel.innerHTML = `${characterPreview(run)}<section class="story-preview"><div class="story-preview-head"><div><h3>Nội dung truyện</h3><p>Hiển thị phần mở đầu để bạn kiểm tra nhanh.</p></div><span>${Number(run.story.script_item_count || run.story.script?.length || 0)} phần</span></div><div class="story-content story-excerpt">${escapeHtml(excerpt)}</div><details><summary>Đọc toàn bộ truyện</summary><div class="story-content">${escapeHtml(fullStory)}</div></details></section>`;
      }
      else if (images.length) panel.innerHTML = `<div class="gallery">${images.slice(0, 12).map(item => `<figure class="asset"><img class="asset-image" src="/api/runs/${encodeURIComponent(run.run_id)}/artifact?path=${encodeURIComponent(item.path)}" alt="${escapeHtml(item.path)}" loading="lazy"><figcaption><span>${escapeHtml(item.path.split('/').pop())}</span><span>${formatBytes(item.size_bytes)}</span></figcaption></figure>`).join('')}</div>`;
      else if (run.stage === 'STAGE4') panel.innerHTML = `<div class="empty-state" style="min-height:220px"><div><span class="empty-icon">▷</span><h2>Prompt video đã sẵn sàng</h2><p>Mở tab Tệp đầu ra để xem <code>video_prompts.json</code> hoặc tải package sản xuất video.</p></div></div>`;
      else panel.innerHTML = '<p class="muted">Chưa có preview cho stage này.</p>';
    } else if (tab === 'artifacts') {
      panel.innerHTML = `<ul class="file-tree">${run.artifacts.map(item => `<li><strong>${escapeHtml(item.path)}</strong> <span>— ${formatBytes(item.size_bytes)}</span></li>`).join('')}</ul>`;
    } else {
      panel.innerHTML = `<dl class="detail-list"><dt>Run ID</dt><dd>${escapeHtml(run.run_id)}</dd><dt>Thực thi</dt><dd>${escapeHtml(run.quality_decision?.workflow_status || run.package?.execution_status || run.status)}</dd><dt>Kỹ thuật</dt><dd>${escapeHtml(run.quality_decision?.technical_status || run.package?.integrity_status || 'Không rõ')}</dd><dt>An toàn</dt><dd>${escapeHtml(run.quality_decision?.safety_status || 'Không rõ')}</dd><dt>Biên tập</dt><dd>${escapeHtml(run.quality_decision?.editorial_status || run.package?.content_quality_status || 'Chưa đánh giá')}</dd><dt>Quyền chuyển stage</dt><dd>${escapeHtml(run.quality_decision?.advancement_status || (run.package?.allowed_next_stage ? 'ALLOWED' : 'BLOCKED'))}</dd><dt>Loại artefact</dt><dd>${escapeHtml(run.package?.artifact_class || 'Không rõ')}</dd><dt>Profile</dt><dd>${escapeHtml(run.profile)}</dd><dt>Stage</dt><dd>${escapeHtml(run.stage)}</dd><dt>Provider mode</dt><dd>${escapeHtml(run.package?.provider_mode || 'Không rõ')}</dd><dt>Telemetry</dt><dd>${escapeHtml(telemetry?.status || 'Không có')}</dd><dt>Độ lệch telemetry</dt><dd>${telemetry ? `${Number(telemetry.deviation_percent || 0).toFixed(2)}% / ${Number(telemetry.maximum_deviation_percent || 5).toFixed(2)}%` : 'Không có'}</dd><dt>Wall-clock job</dt><dd>${telemetry ? `${Number(telemetry.job_wall_clock_ms || 0).toFixed(1)} ms` : 'Không có'}</dd><dt>Wall-clock manifest</dt><dd>${telemetry ? `${Number(telemetry.reported_wall_clock_ms || 0).toFixed(1)} ms` : 'Không có'}</dd><dt>Last event</dt><dd>${escapeHtml(run.last_event)}</dd><dt>Package digest</dt><dd>${escapeHtml(run.package?.package_digest_sha256 || 'Chưa có')}</dd><dt>Parent digest</dt><dd>${escapeHtml(run.package?.parent_package_digest_sha256 || 'Không có')}</dd></dl>`;
    }
  }
  document.querySelectorAll('[data-run-tab]').forEach(button => button.addEventListener('click', () => paintTab(button.dataset.runTab)));
  document.querySelector('.tab-bar').addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [...document.querySelectorAll('[data-run-tab]')];
    const current = tabs.indexOf(document.activeElement);
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    event.preventDefault();
    tabs[target].focus();
    paintTab(tabs[target].dataset.runTab);
  });
  document.querySelector('#delete-current-run')?.addEventListener('click', () => showDeleteRun(run.run_id, run.title));
  paintTab(activeTab);
  document.querySelector('#run-next-stage')?.addEventListener('click', () => submitNextStage(run, nextStage));
  document.querySelector('#repair-open-errors')?.addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = 'Đang khởi tạo repair…';
    try {
      const job = await api(`/api/runs/${encodeURIComponent(run.run_id)}/repair`, {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}',
      });
      showJob(job);
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
      button.textContent = 'Repair lỗi mở';
    }
  });
}

async function submitNextStage(run, stage) {
  const role = {2:'landscape', 3:'portrait', 4:'tts'}[stage];
  const openWarnings = (run.validation?.records || []).filter(item => item.resolution_status === 'OPEN' || !['PASS','ASSESSED_PASS'].includes(item.status));
  const modal = document.createElement('div'); modal.className = 'modal-backdrop';
  const warningNotice = openWarnings.length ? `<div class="validation-banner warning-banner"><strong>Không thể khởi chạy</strong><span>Package còn ${openWarnings.length} lỗi mở. Hãy sửa và kiểm định lại trước khi chạy stage tiếp theo.</span><a href="#/validation?run=${encodeURIComponent(run.run_id)}">Xem chi tiết kiểm định</a></div>` : '<div class="validation-banner success-banner"><strong>Không có cảnh báo mở</strong><span>Package đầu vào đã vượt qua các kiểm tra được ghi nhận.</span></div>';
  modal.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="stage-dialog-title" tabindex="-1"><h2 id="stage-dialog-title">Cấu hình ${escapeHtml(stageLabels[`STAGE${stage}`])}</h2><p>Các lựa chọn này chỉ áp dụng cho giai đoạn đang chạy.</p>${warningNotice}<form id="stage-model-form">${stage < 4 ? presetField(run.package?.quality_preset || state.settings?.quality_preset || 'balanced') : ''}${modelField(role)}${stage === 4 ? `<label class="checkbox"><input type="checkbox" name="visual_review_approved" value="yes"> Tôi đã duyệt cover, cao trào và cặp ảnh ngang/dọc mẫu.</label><small class="muted">Không bắt buộc để chạy; nếu bỏ chọn, review được ghi PENDING.</small><label class="checkbox"><input type="checkbox" name="render_tts" value="yes" ${state.settings?.render_tts ? 'checked' : ''}> Render audio bằng Piper</label>` : ''}<div class="form-actions"><button class="button" type="button" data-close>Hủy</button><button class="button button-primary" ${openWarnings.length ? 'disabled' : ''}>Khởi chạy</button></div></form></div>`;
  document.body.append(modal);
  let dismissStageDialog = () => {};
  dismissStageDialog = activateDialog(modal, () => dismissStageDialog());
  modal.querySelector('[data-close]').addEventListener('click', dismissStageDialog);
  modal.querySelector('form').addEventListener('submit', async event => {
    event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const selected = data[`model_${role}`];
      const inheritedMode = run.package?.provider_mode || 'deterministic';
      const payload = { input_run_id: run.run_id, confirm_large_plan: true, provider_mode: selected && stage < 4 ? 'local' : inheritedMode, quality_preset: data.quality_preset || state.settings?.quality_preset || 'balanced', model_selection: selected ? {[role]: selected} : {}, render_tts: data.render_tts === 'yes', aspect_ratio: state.settings?.aspect_ratio || 'LANDSCAPE_16_9', auto_advance: Boolean(state.settings?.auto_advance), visual_review_approved: data.visual_review_approved === 'yes', idempotency_key: crypto.randomUUID() };
      const job = await api(`/api/jobs/stage${stage}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      modal.remove(); showJob(job);
    } catch (error) { toast(error.message, true); }
  });
}

function renderValidation(run) {
  if (!run) {
    app.innerHTML = `<div class="page-head"><div><div class="kicker">Kiểm định</div><h1>Không có dữ liệu kiểm định</h1><p>Tạo hoặc mở một workflow để xem kết quả.</p></div></div><section class="card empty-state"><div><span class="empty-icon">✓</span><h2>Chưa có package</h2><p>Validation record sẽ xuất hiện sau khi pipeline tạo đầu ra.</p><a class="button button-primary" href="#/new">Tạo truyện</a></div></section>`;
    return;
  }
  const validationOpenedAt = performance.now();
  trackUx('VALIDATION_VIEWED', { stage: run.stage || 'UNKNOWN' });
  const records = run.validation?.records || [];
  const severityPriority = { PUBLISH_BLOCKER: 0, QUALITY_BLOCKER: 1 };
  const statusPriority = { FAIL: 0, NOT_VERIFIED: 1, ASSESSED_FAIL: 2, ASSESSED_PASS: 3, PASS: 4 };
  const prioritizedRecords = [...records].sort((left, right) => {
    const leftOpen = left.resolution_status === 'OPEN' || !['PASS', 'ASSESSED_PASS'].includes(left.status);
    const rightOpen = right.resolution_status === 'OPEN' || !['PASS', 'ASSESSED_PASS'].includes(right.status);
    if (leftOpen !== rightOpen) return leftOpen ? -1 : 1;
    const severityDelta = (severityPriority[left.severity] ?? 2) - (severityPriority[right.severity] ?? 2);
    if (severityDelta) return severityDelta;
    return (statusPriority[left.status] ?? 5) - (statusPriority[right.status] ?? 5);
  });
  const failed = records.filter(item => ['FAIL', 'NOT_VERIFIED', 'ASSESSED_FAIL'].includes(item.status));
  const passed = records.filter(item => ['PASS', 'ASSESSED_PASS'].includes(item.status));
  const ledger = run.validation?.ledger || {};
  const openCount = Math.max(Number(ledger.summary?.open_warning_count || 0), failed.length);
  const requirementCoverage = run.validation?.requirement_coverage || { items: [], satisfied_count: 0, total_count: 0 };
  const requirementPanel = requirementCoverage.total_count ? `<section class="card card-padding"><div class="card-head"><div><h2>Yêu cầu của brief</h2><p>Đã chứng minh ${Number(requirementCoverage.satisfied_count)}/${Number(requirementCoverage.total_count)} requirement trong outline và script.</p></div><span class="badge ${requirementCoverage.satisfied_count === requirementCoverage.total_count ? 'badge-success' : 'badge-danger'}">${requirementCoverage.satisfied_count === requirementCoverage.total_count ? 'Đủ bằng chứng' : 'Còn thiếu'}</span></div><div class="validation-list">${requirementCoverage.items.map(item => `<div class="validation-row"><span class="validation-icon ${item.status === 'SATISFIED' ? 'success' : ''}">${item.status === 'SATISFIED' ? '✓' : '!'}</span><div><div class="row-title">${escapeHtml(item.requirement_id)}</div><div class="muted small">${escapeHtml(item.kind || 'REQUIREMENT')} · ${escapeHtml(item.status)}${item.outline_zones?.length ? ` · outline: ${escapeHtml(item.outline_zones.join(', '))}` : ''}${item.script_locators?.length ? ` · script: ${escapeHtml(item.script_locators.join(', '))}` : ''}</div></div></div>`).join('')}</div></section>` : '';
  app.innerHTML = `<div class="page-head"><div><div class="kicker">${escapeHtml(run.title)}</div><h1>Trung tâm kiểm định · ${escapeHtml(stageLabels[run.stage] || '')}</h1><p>Tổng hợp kiểm định xuyên stage; lỗi mở sẽ chặn các stage sản xuất tiếp theo.</p></div><a class="button" href="#/runs/${encodeURIComponent(run.run_id)}">← Về workspace</a></div>
    <div class="summary-grid summary-grid-four"><div class="card stat"><strong style="color:var(--danger)">${openCount}</strong><span class="muted small">Cảnh báo đang mở</span></div><div class="card stat"><strong style="color:var(--warning)">${records.filter(item => item.status === 'NOT_VERIFIED').length}</strong><span class="muted small">Chưa xác minh</span></div><div class="card stat"><strong style="color:var(--success)">${passed.length}</strong><span class="muted small">Đã đạt</span></div><div class="card stat"><strong class="recommendation ${openCount ? 'warning-text' : 'success-text'}">${openCount ? 'Chưa nên phát hành' : 'Sẵn sàng'}</strong><span class="muted small">Khuyến nghị phát hành</span></div></div>
    ${requirementPanel}
    <div class="filter-bar ledger-filters"><label>Trạng thái<select class="input" id="filter-status"><option value="all">Tất cả</option><option value="open">Đang mở</option><option value="resolved">Đã xử lý</option></select></label><label>Giai đoạn<select class="input" id="filter-stage"><option value="all">Tất cả</option>${[1,2,3,4].map(number => `<option value="STAGE${number}">${stageLabels[`STAGE${number}`]}</option>`).join('')}</select></label><label>Mức ảnh hưởng<select class="input" id="filter-severity"><option value="all">Tất cả</option>${[...new Set(records.map(item => item.severity).filter(Boolean))].map(value => `<option value="${escapeHtml(value)}">${value === 'PUBLISH_BLOCKER' ? 'Chặn phát hành' : value === 'QUALITY_BLOCKER' ? 'Chặn chất lượng' : escapeHtml(value)}</option>`).join('')}</select></label><span class="muted small" id="filter-count"></span></div>
    <div class="grid grid-two"><section class="card card-padding" id="validation-list"></section><aside class="card card-padding" id="validation-detail"><p class="muted">Chọn một kiểm tra để xem chi tiết.</p></aside></div>`;
  const list = document.querySelector('#validation-list');
  const detail = document.querySelector('#validation-detail');
  if (openCount === 0 && state.validationUi.status === 'open') {
    state.validationUi.status = 'all';
    saveUiSession();
  }
  document.querySelector('#filter-status').value = state.validationUi.status;
  document.querySelector('#filter-stage').value = state.validationUi.stage;
  document.querySelector('#filter-severity').value = state.validationUi.severity;
  function paintList() {
    const status = document.querySelector('#filter-status').value;
    const stage = document.querySelector('#filter-stage').value;
    const severity = document.querySelector('#filter-severity').value;
    const filtered = prioritizedRecords.filter(item => (status === 'all' || (status === 'open' ? item.resolution_status === 'OPEN' || !['PASS','ASSESSED_PASS'].includes(item.status) : item.resolution_status === 'RESOLVED' || ['PASS','ASSESSED_PASS'].includes(item.status))) && (stage === 'all' || item.stage === stage) && (severity === 'all' || item.severity === severity));
    document.querySelector('#filter-count').textContent = `${filtered.length}/${records.length} kiểm tra`;
    const listHeading = status === 'open' ? 'Việc cần xử lý' : status === 'resolved' ? 'Kiểm tra đã xử lý' : 'Tất cả kiểm tra';
    list.innerHTML = `<div class="validation-section-head"><div><h2>${listHeading}</h2><p>${status === 'open' ? 'Ưu tiên theo mức ảnh hưởng và trạng thái.' : 'Chọn một kiểm tra để xem bằng chứng.'}</p></div><strong>${filtered.length}</strong></div>${filtered.length ? filtered.map(item => `<button type="button" class="check-row" data-record-index="${records.indexOf(item)}" style="width:100%;border-left:0;border-right:0;border-bottom:0;background:transparent;color:inherit;text-align:left;cursor:pointer"><span class="validation-icon ${['PASS','ASSESSED_PASS'].includes(item.status) ? 'success' : item.status === 'NOT_VERIFIED' ? 'warning' : ''}">${['PASS','ASSESSED_PASS'].includes(item.status) ? '✓' : '!'}</span><span><span class="row-title" style="display:block">${escapeHtml(validationTitle(item))}</span><span class="muted small">${escapeHtml(stageLabels[item.stage] || item.stage || 'Không rõ giai đoạn')}</span></span>${validationBadge(item.status)}</button>`).join('') : '<p class="muted">Không có kiểm tra phù hợp bộ lọc.</p>'}`;
    list.querySelectorAll('[data-record-index]').forEach(button => button.addEventListener('click', () => {
      const item = records[Number(button.dataset.recordIndex)];
      paintDetail(item);
      if (item.resolution_status === 'OPEN' || !['PASS','ASSESSED_PASS'].includes(item.status)) {
        trackUx('BLOCKER_OPENED', {
          stage: item.stage || 'UNKNOWN',
          severity: ['PUBLISH_BLOCKER', 'QUALITY_BLOCKER'].includes(item.severity) ? item.severity : 'OTHER',
          elapsed_ms: Math.max(0, Math.round(performance.now() - validationOpenedAt)),
        });
      }
    }));
    if (filtered[0]) paintDetail(filtered[0]);
    else detail.innerHTML = '<p class="muted">Không có kiểm tra phù hợp bộ lọc.</p>';
  }
  function paintDetail(item) {
    const suggestions = item.recommendations || [];
    const open = item.resolution_status === 'OPEN' || !['PASS','ASSESSED_PASS'].includes(item.status);
    detail.innerHTML = `<div class="card-head"><div><h2>${escapeHtml(validationTitle(item))}</h2><p>${escapeHtml(stageLabels[item.stage] || item.stage || 'Không rõ giai đoạn')}</p></div>${validationBadge(item.status)}</div><div class="validation-banner" style="background:${['PASS','ASSESSED_PASS'].includes(item.status) ? 'var(--success-soft)' : 'var(--warning-soft)'};color:${['PASS','ASSESSED_PASS'].includes(item.status) ? 'var(--success)' : 'var(--warning)'}"><strong>${escapeHtml(validationLabels[item.status] || item.status)}</strong><span>${['PASS','ASSESSED_PASS'].includes(item.status) ? 'Kiểm tra này đã đạt.' : 'Cần xử lý trước khi chạy giai đoạn tiếp theo.'}</span></div>${item.findings?.length ? `<h3>Vấn đề cụ thể</h3><ul>${item.findings.map(value => `<li>${escapeHtml(findingSummary(value))}</li>`).join('')}</ul>` : ''}${suggestions.length ? `<h3>Gợi ý sửa ưu tiên</h3><ul>${suggestions.map(value => `<li>${escapeHtml(value)}</li>`).join('')}</ul>` : ''}${open ? `<div class="actions" style="margin-top:16px"><a class="button button-primary" data-blocker-cta href="#/runs/${encodeURIComponent(run.run_id)}">${item.stage === run.stage ? 'Mở workspace để xử lý' : `Về ${escapeHtml(stageLabels[item.stage] || item.stage)}`}</a></div>` : ''}<details class="job-technical" style="margin-top:16px"><summary>Chi tiết kỹ thuật</summary><dl class="detail-list"><dt>Gate ID</dt><dd>${escapeHtml(item.id)}</dd><dt>Resolution</dt><dd>${escapeHtml(item.resolution_status || 'OPEN')}</dd><dt>Release impact</dt><dd>${escapeHtml(item.release_impact || 'NOT_RECOMMENDED')}</dd><dt>Severity</dt><dd>${escapeHtml(item.severity)}</dd><dt>Evidence</dt><dd>${escapeHtml((item.locators || []).join(', ') || 'Không có')}</dd></dl></details>`;
    detail.querySelector('[data-blocker-cta]')?.addEventListener('click', () => {
      trackUx('BLOCKER_CTA_SELECTED', { stage: item.stage || 'UNKNOWN' });
      sessionStorage.setItem('ai-story-validation-return', JSON.stringify({ started_at: Date.now() }));
    });
  }
  document.querySelectorAll('.ledger-filters select').forEach(select => select.addEventListener('change', () => {
    state.validationUi = { status: document.querySelector('#filter-status').value, stage: document.querySelector('#filter-stage').value, severity: document.querySelector('#filter-severity').value };
    saveUiSession();
    trackUx('VALIDATION_FILTER_CHANGED', {
      status_filter: state.validationUi.status,
      stage_filter: state.validationUi.stage,
      severity_filter: ['all', 'PUBLISH_BLOCKER', 'QUALITY_BLOCKER'].includes(state.validationUi.severity) ? state.validationUi.severity : 'OTHER',
    });
    paintList();
  }));
  paintList();
}

function renderInspector() {
  app.innerHTML = `<div class="page-head"><div><div class="kicker">Công cụ</div><h1>Kiểm tra gói</h1><p>Xác minh integrity và khả năng dùng làm đầu vào.</p></div></div><section class="dropzone" id="dropzone"><div><span class="drop-icon">◇</span><h2>Thả file story.zip vào đây</h2><p>Package không bị thay đổi trong quá trình kiểm tra.</p><input type="file" id="package-file" accept=".zip,application/zip" hidden><button class="button button-primary" type="button" id="choose-package">Chọn gói từ máy tính</button></div></section><div id="inspector-result"></div>`;
  const input = document.querySelector('#package-file');
  const dropzone = document.querySelector('#dropzone');
  document.querySelector('#choose-package').addEventListener('click', () => input.click());
  input.addEventListener('change', () => input.files[0] && inspectFile(input.files[0]));
  ['dragenter', 'dragover'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.remove('dragover'); }));
  dropzone.addEventListener('drop', event => { const file = event.dataTransfer.files[0]; if (file) inspectFile(file); });
}

async function inspectFile(file) {
  const result = document.querySelector('#inspector-result');
  result.innerHTML = '<div class="loading"><div><div class="spinner"></div>Đang xác minh package…</div></div>';
  try {
    const value = await api('/api/packages/inspect', { method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file });
    document.querySelector('#dropzone').hidden = true;
    const validation = value.manifest.validation || {};
    const blocked = validation.content_quality_status !== 'PASS';
    const fixture = validation.artifact_class === 'TEST_FIXTURE';
    result.innerHTML = `<div class="grid grid-two"><section class="card card-padding"><div class="card-head"><div><h2>Cấu trúc gói</h2><p>${value.files.length} tệp canonical.</p></div><span class="badge badge-success">Integrity đạt</span></div><ul class="file-tree">${value.files.map(item => `<li><strong>${escapeHtml(item.path)}</strong> — ${formatBytes(item.size_bytes)}</li>`).join('')}</ul></section><aside class="card card-padding"><div class="card-head"><div><h2>${blocked ? 'Package có cảnh báo' : 'Trạng thái package'}</h2><p>Toàn vẹn, chất lượng và phát hành được đánh giá riêng.</p></div><span class="badge ${blocked ? 'badge-warning' : 'badge-success'}">${blocked ? 'Tiếp tục có cảnh báo' : 'Đạt'}</span></div>${fixture ? '<div class="validation-banner warning-banner"><strong>Artefact kiểm thử</strong><span>Có thể làm đầu vào stage tiếp theo; không được xem là production-ready.</span></div>' : ''}<dl class="detail-list"><dt>Thực thi</dt><dd>${escapeHtml(validation.execution_status || 'Không rõ')}</dd><dt>Toàn vẹn</dt><dd>${escapeHtml(validation.integrity_status || validation.status || 'Không rõ')}</dd><dt>Chất lượng nội dung</dt><dd>${escapeHtml(validation.content_quality_status || 'Chưa đánh giá')}</dd><dt>Cảnh báo mở</dt><dd>${Number(validation.open_warning_count || 0)}</dd><dt>Khuyến nghị phát hành</dt><dd>${blocked || fixture ? 'NOT_RECOMMENDED' : 'READY'}</dd><dt>Loại artefact</dt><dd>${escapeHtml(validation.artifact_class || 'Không rõ')}</dd><dt>Stage</dt><dd>${escapeHtml(stageLabels[value.manifest.package_stage] || value.manifest.package_stage)}</dd><dt>Profile</dt><dd>${escapeHtml(profileLabels[value.manifest.active_profile] || value.manifest.active_profile)}</dd><dt>Stage tiếp theo</dt><dd>${escapeHtml(stageLabels[value.manifest.allowed_next_stage] || value.manifest.allowed_next_stage || 'Đã đến stage cuối')}</dd></dl><button class="button button-block" id="inspect-another" type="button" style="margin-top:18px">Kiểm tra package khác</button></aside></div>`;
    document.querySelector('#inspect-another').addEventListener('click', renderInspector);
  } catch (error) {
    result.innerHTML = `<div class="error-panel section-space"><strong>Package không hợp lệ</strong>${escapeHtml(error.message)}</div>`;
  }
}

document.querySelector('#refresh-button').addEventListener('click', refreshRuns);
window.addEventListener('hashchange', renderRoute);
window.addEventListener('beforeunload', event => {
  if (state.currentRouteKey) state.scrollPositions[state.currentRouteKey] = window.scrollY;
  saveUiSession();
  if (state.settingsDirty) event.preventDefault();
});
document.addEventListener('click', event => { const link = event.target.closest('a[href^="#/"]'); if (link && state.settingsDirty && !window.confirm('Bạn có thay đổi cài đặt chưa lưu. Rời trang và bỏ thay đổi?')) event.preventDefault(); });
window.addEventListener('DOMContentLoaded', renderRoute);
