const views = document.querySelectorAll('.workspace-view');
const navItems = document.querySelectorAll('.nav-item[data-view]');
const sidebar = document.querySelector('.sidebar');
const inspector = document.querySelector('.inspector');
const overlay = document.querySelector('.overlay');
const toast = document.querySelector('.toast');
const welcomeScreen = document.querySelector('#welcome-screen');
let latestSnapshot = null;
let transactionFilter = 'ALL';
let eventFilter = 'ALL';
let selectedExecutionStage = null;
let runtimeState = 'BOOTING';
let runtimeRefreshInFlight = false;
let runtimeFailureCount = 0;
let lastInspectorTrigger = null;
const mobileMenu = document.querySelector('.mobile-menu');
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const dismissWelcome = (message) => { welcomeScreen.classList.add('hidden'); if (message) showToast(message); };
document.querySelector('#new-workspace').addEventListener('click', () => dismissWelcome('Đã mở workspace hiện hành.'));
document.querySelector('#open-story-button').addEventListener('click', () => document.querySelector('#story-picker').click());
document.querySelector('#story-picker').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const button = document.querySelector('#open-story-button');
  button.disabled = true;
  try {
    const response = await fetch('/api/v1/stories/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/zip', 'X-Story-Filename': encodeURIComponent(file.name) },
      body: file,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || payload.code || 'Không thể nhập story.zip.');
    dismissWelcome(`Đã nhập ${file.name} · ${payload.result.package_stage}`);
    refreshRuntime();
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    event.target.value = '';
  }
});

function openView(id) {
  const target = document.getElementById(id);
  if (!target) return;
  views.forEach((view) => {
    const active = view.id === id;
    view.classList.toggle('active', active);
    view.setAttribute('aria-hidden', String(!active));
  });
  navItems.forEach((item) => {
    const active = item.dataset.view === id;
    item.classList.toggle('active', active);
    if (active) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  });
  sidebar.classList.remove('open');
  mobileMenu.setAttribute('aria-expanded', 'false');
  overlay.classList.remove('open');
  history.replaceState(null, '', `#${id}`);
  target.setAttribute('tabindex', '-1');
  target.focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: reduceMotion.matches ? 'auto' : 'smooth' });
}

function showToast(message) {
  toast.querySelector('p').textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 2600);
}

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) element.textContent = value;
}

function setSavedState(label, tone) {
  const saved = document.querySelector('.saved');
  if (!saved) return;
  const dot = document.createElement('i');
  dot.className = `status-dot ${tone}`;
  saved.replaceChildren(dot, document.createTextNode(label));
}

function setRuntimeState(state, detail = '') {
  runtimeState = state;
  document.body.classList.remove('runtime-booting', 'runtime-offline', 'runtime-empty', 'runtime-live');
  document.body.classList.add(`runtime-${state.toLowerCase()}`);
  const banner = document.querySelector('#runtime-banner');
  const stageRail = document.querySelector('.stage-rail');
  const dashboard = document.querySelector('.dashboard-grid');
  const storyAction = document.querySelector('[data-action="delete-story"]');
  const packageActions = document.querySelectorAll('[data-action="package"]');
  const hasLiveData = state === 'LIVE';

  if (stageRail) stageRail.hidden = !hasLiveData;
  if (dashboard) dashboard.hidden = !hasLiveData;
  if (storyAction) storyAction.hidden = !hasLiveData;
  packageActions.forEach((button) => { button.disabled = !hasLiveData; });
  if (state === 'BOOTING') {
    banner.hidden = false;
    banner.className = 'runtime-banner';
    banner.replaceChildren(document.createTextNode('Đang kết nối runtime Python và đọc workspace cục bộ…'));
    setSavedState('Đang kiểm tra runtime', 'unknown');
    return;
  }
  if (state === 'OFFLINE') {
    banner.hidden = false;
    banner.className = 'runtime-banner error runtime-banner-action';
    const copy = document.createElement('span');
    copy.textContent = detail || 'Không kết nối được runtime Python. Dữ liệu workspace chưa được tải.';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'secondary-button runtime-retry';
    retry.textContent = 'Thử kết nối lại';
    retry.addEventListener('click', refreshRuntime);
    banner.replaceChildren(copy, retry);
    setText('.breadcrumb strong', 'Runtime chưa kết nối');
    setText('.episode-code', 'OFFLINE');
    setText('.eyebrow span:not(.episode-code)', 'CHƯA XÁC MINH WORKSPACE');
    setText('.page-heading h1', 'Không thể đọc workspace');
    setText('.page-heading p', 'Khởi động Studio bằng open_app.bat, sau đó thử kết nối lại.');
    setSavedState('Runtime ngoại tuyến', 'offline');
    document.querySelectorAll('.nav-count, .warning-count, .live-count').forEach((item) => { item.textContent = '0'; });
    return;
  }
  if (state === 'EMPTY') {
    banner.hidden = false;
    banner.className = 'runtime-banner';
    banner.replaceChildren(document.createTextNode(detail));
    setSavedState('Workspace cục bộ đã sẵn sàng', 'online');
    return;
  }
  banner.hidden = false;
  banner.className = 'runtime-banner';
  banner.replaceChildren(document.createTextNode(detail));
  setSavedState('Đã đồng bộ cục bộ', 'online');
}

function applySnapshot(snapshot) {
  latestSnapshot = snapshot;
  if (snapshot.mode === 'EMPTY') {
    setRuntimeState('EMPTY', `Workspace ${snapshot.workspace} chưa có workflow. Hãy chạy Stage 1 để bắt đầu.`);
    setText('.breadcrumb strong', 'Workspace mới');
    document.querySelector('.breadcrumb strong').removeAttribute('data-workflow-id');
    setText('.episode-code', 'WORKSPACE MỚI');
    setText('.eyebrow span:not(.episode-code)', 'CHƯA CÓ STORY');
    setText('.page-heading h1', 'Workspace rỗng');
    setText('.page-heading p', 'Chưa có story · Hãy tạo story đầu tiên để bắt đầu.');
    document.querySelectorAll('.nav-count, .warning-count, .live-count').forEach((item) => { item.textContent = '0'; });
    setText('.warning-count', '0');
    setText('.live-count', '0');
    document.querySelector('[data-action="delete-story"]').hidden = true;
    setText('#stage-detail-title', 'Chưa có workflow');
    setText('#stage-detail-status', 'Chưa bắt đầu');
    setText('#live-committed', '0');
    setText('#live-total', '/ 0 tài sản');
    setText('#live-percent', 'Chưa có dữ liệu');
    document.querySelector('#live-progress').style.width = '0%';
    applyJobs(snapshot.jobs || []);
    renderExecutionDashboard(snapshot, null, snapshot.jobs?.[0] || null);
    return;
  }
  setRuntimeState('LIVE', `Đang đọc trực tiếp workflow ${snapshot.workflow.id.slice(0, 8)}… từ SQLite · ${snapshot.workspace}`);
  setText('.breadcrumb strong', snapshot.workflow.id.slice(0, 12));
  document.querySelector('.breadcrumb strong').dataset.workflowId = snapshot.workflow.id;
  const story = snapshot.story;
  if (story) {
    const episode = String(story.episode).padStart(2, '0');
    setText('.episode-code', `TẬP ${episode}`);
    setText('.eyebrow span:not(.episode-code)', story.series);
    setText('.page-heading h1', story.title);
  } else {
    setText('.episode-code', 'CHƯA CÓ TẬP');
    setText('.eyebrow span:not(.episode-code)', 'CHƯA CÓ STORY ĐÃ XUẤT BẢN');
    setText('.page-heading h1', 'Story chưa có metadata');
  }
  setText('.page-heading p', `${snapshot.workflow.profile} · ${snapshot.workflow.route} · ${snapshot.workflow.status}`);

  const current = [...snapshot.stages].reverse().find((stage) => stage.status !== 'PASS') || snapshot.stages.at(-1);
  if (current) {
    const { committed, total } = current.progress;
    const percent = total ? Math.round((committed / total) * 100) : 0;
    setText('.production-card h2', `${current.stage} · ${current.status}`);
    setText('#live-committed', String(committed));
    setText('#live-total', `/ ${total} tài sản`);
    setText('#live-percent', `${percent}% hoàn tất`);
    document.querySelector('#live-progress').style.width = `${percent}%`;
    const activeTransaction = current.transactions.find((item) => item.status === 'IN_PROGRESS') || current.transactions.find((item) => item.status === 'FAILED_RETRYABLE') || current.transactions.at(-1);
    if (activeTransaction) {
      setText('.job-copy small', activeTransaction.status.replaceAll('_', ' '));
      setText('.job-copy h3', activeTransaction.basename);
      setText('.job-copy p', `${activeTransaction.orientation} · ${activeTransaction.latest_call?.model_identity || 'Runtime local'}`);
    }
    const waiting = current.transactions.filter((item) => ['PENDING', 'FAILED_RETRYABLE'].includes(item.status));
    setText('.queue-row strong', waiting[0]?.basename || 'Không còn tài sản đang chờ');
    setText('.queue-count', waiting.length ? `${waiting.length} mục đang chờ` : 'Hàng đợi trống');
  }

  const stageElements = document.querySelectorAll('.stage');
  stageElements.forEach((element, index) => {
    const pipeline = snapshot.pipeline_stages || snapshot.stages;
    const stage = pipeline.find((item) => item.stage === `STAGE${index + 1}`);
    element.classList.toggle('complete', stage?.status === 'PASS');
    element.classList.toggle('active', current?.stage === stage?.stage);
    const number = element.querySelector('.stage-number');
    number.textContent = stage?.status === 'PASS' ? '✓' : String(index + 1).padStart(2, '0');
    element.querySelector('em').textContent = stage ? stage.status.replaceAll('_', ' ') : 'Chưa bắt đầu';
  });

  const summary = snapshot.gate_summary;
  setText('.validation-score strong', `${summary.pass} gate đã đạt`);
  setText('.validation-score p', summary.fail || summary.not_verified ? `${summary.fail + summary.not_verified} mục cần xử lý.` : 'Không có gate hiện hành bị chặn.');
  setText('.score-ring span', `${summary.pass}/${summary.total}`);
  const metrics = document.querySelectorAll('.metric strong');
  if (metrics.length === 4) {
    metrics[0].textContent = summary.total;
    metrics[1].textContent = summary.fail;
    metrics[2].textContent = summary.not_verified;
    metrics[3].textContent = snapshot.stages.reduce((sum, stage) => sum + stage.progress.committed, 0);
  }
  setText('.warning-count', String(summary.fail + summary.not_verified));
  renderEvents(snapshot.events);
  renderGates(snapshot.gates.filter((gate) => gate.status !== 'PASS'));
  renderStageDetail(current, snapshot.gates);
  applyJobs(snapshot.jobs || []);
  const executionStage = snapshot.stages.find((stage) => stage.stage === selectedExecutionStage) || current;
  renderExecutionDashboard(snapshot, executionStage, snapshot.jobs?.find((job) => job.stage_id === executionStage?.id) || snapshot.jobs?.[0] || null);
}

function renderStageDetail(stage, gates) {
  const list = document.querySelector('#transaction-list');
  if (!stage) {
    setText('#stage-detail-title', 'Chưa có workflow');
    setText('#stage-detail-percent', '0%');
    setText('#stage-detail-count', '0 / 0 tài sản');
    setText('#stage-detail-updated', 'Chưa có dữ liệu');
    setText('#stage-detail-current', '—');
    setText('#stage-detail-pending', '0');
    setText('#stage-detail-failed', '0');
    setText('#stage-detail-gates', '—');
    document.querySelector('#stage-detail-progress').style.width = '0%';
    const pill = document.querySelector('#stage-detail-status');
    pill.className = 'status-pill';
    pill.replaceChildren(document.createElement('i'), document.createTextNode(' Chưa bắt đầu'));
    if (list) {
      const empty = document.createElement('p');
      empty.className = 'empty-inline';
      empty.textContent = 'Chưa có transaction.';
      list.replaceChildren(empty);
    }
    return;
  }
  const committed = Number(stage.progress?.committed || 0);
  const total = Number(stage.progress?.total || 0);
  const percent = total ? Math.min(100, Math.round((committed / total) * 100)) : 0;
  const status = String(stage.status || 'PENDING');
  setText('#stage-detail-title', `${stage.stage} · ${status.replaceAll('_', ' ')}`);
  setText('#stage-detail-percent', `${percent}%`);
  setText('#stage-detail-count', `${committed} / ${total} tài sản`);
  setText('#stage-detail-updated', stage.updated_at ? `Cập nhật ${new Date(stage.updated_at).toLocaleString('vi-VN')}` : 'Chưa có dữ liệu');
  document.querySelector('#stage-detail-progress').style.width = `${percent}%`;
  const pill = document.querySelector('#stage-detail-status');
  pill.className = `status-pill ${status === 'PASS' ? 'passed' : status === 'RUNNING' ? 'running' : ''}`;
  pill.innerHTML = `<i></i> ${status.replaceAll('_', ' ')}`;
  const transactions = stage.transactions || [];
  const waiting = transactions.filter((item) => ['PENDING', 'FAILED_RETRYABLE'].includes(item.status));
  const failed = transactions.filter((item) => ['FAILED', 'FAILED_RETRYABLE'].includes(item.status));
  const active = transactions.find((item) => item.status === 'IN_PROGRESS');
  setText('#stage-detail-current', active?.basename || '—');
  setText('#stage-detail-pending', String(waiting.length));
  setText('#stage-detail-failed', String(failed.length));
  const stageGates = gates.filter((gate) => gate.stage_id === stage.id);
  setText('#stage-detail-gates', stageGates.length ? `${stageGates.filter((gate) => gate.status === 'PASS').length}/${stageGates.length} PASS` : 'Chưa có');
  if (!list) return;
  list.replaceChildren(...transactions.map((item) => {
    const row = document.createElement('div'); row.className = 'transaction-row';
    const name = document.createElement('div'); const strong = document.createElement('strong'); strong.textContent = item.basename; const small = document.createElement('small'); small.textContent = item.orientation; name.append(strong, small);
    const call = document.createElement('span'); call.textContent = item.latest_call ? `${item.latest_call.attempt_index ? `Attempt ${item.latest_call.attempt_index}` : 'Call'} · ${item.latest_call.duration_ms || 0} ms` : 'Chưa gọi';
    const badge = document.createElement('span'); badge.className = `transaction-status ${item.status === 'PASS' || item.status === 'COMMITTED' ? 'pass' : item.status.includes('FAIL') ? 'fail' : item.status === 'IN_PROGRESS' ? 'running' : ''}`; badge.textContent = item.status.replaceAll('_', ' ');
    const artifact = document.createElement('small'); artifact.textContent = item.committed_artifact ? `SHA ${item.committed_artifact.sha256.slice(0, 10)}…` : 'Chưa commit'; row.append(name, call, badge, artifact); return row;
  }));
}

const stageObjectives = {
  STAGE1: 'Tạo nội dung, kiểm định cấu trúc và đóng gói story cùng character references.',
  STAGE2: 'Tạo Visual Bible landscape, kiểm định ảnh và hoàn tất semantic review.',
  STAGE3: 'Tạo portrait có khóa identity/continuity và đóng gói artifact kế thừa.',
  STAGE4: 'Lập timeline, dựng video/audio/subtitle và kiểm định package cuối.',
};

function formatDuration(milliseconds) {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return '—';
  const total = Math.floor(milliseconds / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours ? `${hours}g ${String(minutes).padStart(2, '0')}p` : `${minutes}p ${String(seconds).padStart(2, '0')}s`;
}

function transactionCategory(item) {
  if (item.status === 'COMMITTED') return 'COMMITTED';
  if (item.status.includes('FAIL') || item.latest_call?.status === 'FAILED') return 'FAILED';
  if (item.status === 'IN_PROGRESS' || item.latest_call?.status === 'RUNNING') return 'ACTIVE';
  return 'PENDING';
}

function eventCategory(event) {
  const type = event.event_type;
  const status = String(event.payload?.status || '');
  if (type.includes('FAIL') || status.includes('FAIL')) return 'ERROR';
  if (type.includes('STARTED') && Number(event.payload?.attempt_index || 1) > 1) return 'RETRY';
  if (type.includes('PASS') || type.includes('COMMITTED') || status === 'FINISHED') return 'SUCCESS';
  return 'PROCESS';
}

function stageSubstep(stage, transaction) {
  if (!stage) return 'Chưa bắt đầu';
  if (!transaction) return stage.status.replaceAll('_', ' ');
  const name = transaction.basename;
  if (stage.stage === 'STAGE1' && name.startsWith('segment-')) {
    const parts = name.replace('.json', '').split('-');
    return `${parts[1]?.toUpperCase() || 'ZONE'} · mục ${parts[2] || '—'} · đoạn ${parts[3] || '—'}`;
  }
  if (stage.stage === 'STAGE2') return `Landscape · ${name}`;
  if (stage.stage === 'STAGE3') return `Portrait · ${name}`;
  if (stage.stage === 'STAGE4') return `Video pipeline · ${name}`;
  return name;
}

function renderExecutionDashboard(snapshot, stage, job) {
  const transactions = stage?.transactions || [];
  const active = transactions.find((item) => item.status === 'IN_PROGRESS' || item.latest_call?.status === 'RUNNING')
    || transactions.find((item) => item.status === 'FAILED_RETRYABLE')
    || transactions.at(-1);
  const committed = Number(stage?.progress?.committed || 0);
  const total = Number(stage?.progress?.total || 0);
  const percent = total ? Math.min(100, Math.round((committed / total) * 100)) : 0;
  const status = job?.status || stage?.status || snapshot.workflow?.status || 'IDLE';
  setText('#execution-stage-label', stage ? `${stage.stage} · ${snapshot.workflow?.profile || ''}` : 'CHƯA CÓ STAGE');
  setText('#execution-title', job?.title || (stage ? `${stage.stage} · ${status.replaceAll('_', ' ')}` : 'Không có workflow đang hoạt động'));
  setText('#execution-objective', stageObjectives[stage?.stage] || 'Tạo Stage 1 để bắt đầu pipeline cục bộ.');
  const pill = document.querySelector('#execution-status');
  pill.className = `status-pill ${['PASS', 'COMPLETED'].includes(status) ? 'passed' : ['RUNNING', 'QUEUED', 'GENERATING'].includes(status) ? 'running' : status === 'FAILED' || status === 'FAIL' ? 'failed' : ''}`;
  pill.innerHTML = `<i></i> ${status.replaceAll('_', ' ')}`;
  setText('#execution-percent', `${percent}%`);
  document.querySelector('#execution-progress').style.width = `${percent}%`;
  setText('#execution-count', `${committed} / ${total} transaction đã commit`);
  setText('#execution-current', active?.basename || '—');
  setText('#execution-substep', stageSubstep(stage, active));
  const latestCall = active?.latest_call;
  const attemptTotal = active?.calls?.length || (latestCall ? latestCall.attempt_index : 0);
  setText('#execution-attempt', latestCall ? `${latestCall.attempt_index} / ${attemptTotal}` : '—');
  setText('#execution-call-status', latestCall ? `${latestCall.status}${latestCall.failure_code ? ` · ${latestCall.failure_code}` : ''}` : 'Không có generation call');
  const startedAt = latestCall?.started_at || stage?.created_at || snapshot.workflow?.created_at;
  const finishedAt = latestCall?.finished_at || (['PASS', 'FAILED', 'CANCELLED'].includes(status) ? stage?.updated_at : null);
  const elapsed = startedAt ? new Date(finishedAt || Date.now()) - new Date(startedAt) : NaN;
  setText('#execution-elapsed', formatDuration(elapsed));
  setText('#execution-timestamps', startedAt ? `Bắt đầu ${new Date(startedAt).toLocaleString('vi-VN')}` : 'Chưa có dữ liệu');
  setText('#execution-runtime', latestCall?.model_identity?.split(/[\\/]/).at(-1) || job?.execution_mode || 'Local');
  setText('#execution-adapter', latestCall?.adapter_version ? `Adapter ${latestCall.adapter_version}` : 'Offline');
  setCopyIdentifier('#execution-workflow-id', job?.workflow_id || snapshot.workflow?.id);
  setCopyIdentifier('#execution-stage-id', job?.stage_id || stage?.id);
  setCopyIdentifier('#execution-job-id', job?.id);
  renderExecutionTransactions(transactions, snapshot.gates || []);
  renderExecutionEvents(snapshot.events || []);
  const result = document.querySelector('#execution-result');
  result.hidden = !['PASS', 'COMPLETED', 'FAILED', 'CANCELLED'].includes(status);
  if (result.hidden) {
    setText('#execution-result-title', 'Chưa có kết quả Stage');
    setText('#execution-result-summary', 'Stage chưa kết thúc.');
    setText('#result-committed', '0/0');
    setText('#result-gates', '0/0');
    setText('#result-retries', '0');
    setText('#result-package', '—');
  } else {
    const stageGates = (snapshot.gates || []).filter((gate) => gate.stage_id === stage?.id);
    const retries = transactions.reduce((sum, item) => sum + Math.max(0, (item.calls?.length || 0) - 1), 0);
    setText('#execution-result-title', ['PASS', 'COMPLETED'].includes(status) ? `${stage?.stage || 'Stage'} hoàn tất` : `${stage?.stage || 'Stage'} ${status}`);
    setText('#execution-result-summary', job?.error_code ? `${job.error_code} — ${job.error_message || 'Không có thông tin bổ sung.'}` : `${committed}/${total} transaction đã commit; mọi kết quả lấy trực tiếp từ runtime.`);
    setText('#result-committed', `${committed}/${total}`);
    setText('#result-gates', `${stageGates.filter((gate) => gate.status === 'PASS').length}/${stageGates.length}`);
    setText('#result-retries', String(retries));
    setText('#result-package', job?.package_digest ? `${job.package_digest.slice(0, 10)}…` : '—');
  }
}

function setCopyIdentifier(selector, value) {
  const button = document.querySelector(selector);
  if (!button) return;
  button.dataset.copy = value || '';
  button.textContent = value ? `${value.slice(0, 12)}…` : '—';
  button.title = value || 'Không có dữ liệu';
}

function renderExecutionTransactions(transactions, gates) {
  const container = document.querySelector('#execution-transactions');
  const visible = transactions.filter((item) => transactionFilter === 'ALL' || transactionCategory(item) === transactionFilter);
  if (!visible.length) {
    const empty = document.createElement('p'); empty.className = 'empty-inline'; empty.textContent = 'Không có transaction phù hợp.'; container.replaceChildren(empty); return;
  }
  container.replaceChildren(...visible.map((item) => {
    const row = document.createElement('button'); row.className = 'execution-transaction-row';
    const name = document.createElement('span'); const strong = document.createElement('strong'); strong.textContent = item.basename; const small = document.createElement('small'); small.textContent = item.orientation; name.append(strong, small);
    const status = document.createElement('span'); status.className = `transaction-status ${transactionCategory(item).toLowerCase()}`; status.textContent = item.status.replaceAll('_', ' ');
    const attempt = document.createElement('span'); attempt.textContent = item.latest_call ? `${item.latest_call.attempt_index}/${item.calls?.length || item.latest_call.attempt_index}` : '—';
    const duration = document.createElement('span'); duration.textContent = formatDuration(Number(item.latest_call?.duration_ms));
    const output = document.createElement('span'); output.textContent = item.committed_artifact ? `${item.committed_artifact.media_type} · ${item.committed_artifact.byte_size} B` : item.latest_call?.failure_code || 'Chưa có artifact';
    row.append(name, status, attempt, duration, output);
    const itemGates = gates.filter((gate) => gate.artifact_sha256 === item.committed_artifact?.sha256);
    row.dataset.asset = item.basename;
    row.dataset.status = `${item.status}${item.latest_call?.failure_code ? ` · ${item.latest_call.failure_code}` : ''}`;
    row.dataset.detail = transactionDetail(item, itemGates);
    row.dataset.stage = latestSnapshot?.stages?.find((stage) => stage.transactions?.some((transaction) => transaction.id === item.id))?.stage || '—';
    row.dataset.transaction = item.id;
    row.dataset.call = item.latest_call?.id || '—';
    row.dataset.detector = itemGates.map((gate) => gate.detector_class).join(', ') || '—';
    row.addEventListener('click', () => openInspector(row));
    return row;
  }));
}

function transactionDetail(item, gates) {
  const lines = item.calls?.map((call) => `Attempt ${call.attempt_index}: ${call.status}${call.failure_code ? ` · ${call.failure_code}` : ''}${call.termination_reason ? ` — ${call.termination_reason}` : ''}`) || [];
  if (item.committed_artifact) lines.push(`Artifact: ${item.committed_artifact.sha256} · ${item.committed_artifact.byte_size} bytes`);
  if (gates.length) lines.push(`Gate: ${gates.map((gate) => `${gate.gate_id}=${gate.status}`).join(', ')}`);
  return lines.join('\n') || 'Transaction chưa có generation call.';
}

function renderExecutionEvents(events) {
  const container = document.querySelector('#execution-events');
  const visible = events.filter((event) => eventFilter === 'ALL' || eventCategory(event) === eventFilter);
  if (!visible.length) {
    const empty = document.createElement('li'); empty.className = 'empty-inline'; empty.textContent = 'Không có sự kiện phù hợp.'; container.replaceChildren(empty); return;
  }
  container.replaceChildren(...visible.map((event) => {
    const item = document.createElement('li'); const category = eventCategory(event); item.className = `execution-event ${category.toLowerCase()}`;
    const marker = document.createElement('i'); marker.textContent = category === 'SUCCESS' ? '✓' : category === 'ERROR' ? '!' : category === 'RETRY' ? '↻' : '•';
    const content = document.createElement('div'); const title = document.createElement('strong'); title.textContent = event.event_type.replaceAll('_', ' '); const detail = document.createElement('small'); detail.textContent = Object.entries(event.payload || {}).map(([key, value]) => `${key}: ${String(value)}`).join(' · ') || 'Workflow event'; content.append(title, detail);
    const time = document.createElement('time'); time.textContent = new Date(event.created_at).toLocaleTimeString('vi-VN'); item.append(marker, content, time); return item;
  }));
}

let lastCompletedJob = null;
let latestRuntimeJob = null;
function applyJobs(jobs) {
  const active = jobs.filter((job) => ['QUEUED', 'RUNNING'].includes(job.status));
  setText('.live-count', String(active.length));
  const latest = jobs[0];
  latestRuntimeJob = latest || null;
  const retry = document.querySelector('#retry-stage2');
  retry.hidden = !(latest?.kind === 'STAGE2_CREATE' && latest?.status === 'FAILED');
  document.querySelector('#review-stage2').hidden = latest?.status !== 'WAITING_SEMANTIC_REVIEW';
  document.querySelector('#cancel-job').hidden = !['QUEUED', 'QUEUED_VLM_REVIEW', 'RUNNING', 'CANCELLING'].includes(latest?.status);
  const failureDetail = latest?.status === 'FAILED'
    ? ` · ${latest.error_code || 'UNKNOWN_ERROR'}${latest.error_message ? ` — ${latest.error_message}` : ''}`
    : '';
  setText('#queue-summary', latest ? `${latest.title} · ${latest.status}${failureDetail}` : 'Không có tác vụ đang chạy.');
  if (latest?.status === 'PASS' && lastCompletedJob !== latest.id) {
    lastCompletedJob = latest.id;
    setText('.page-heading h1', latest.title);
    showToast(`${latest.kind === 'STAGE2_CREATE' ? 'Stage 2' : 'Stage 1'} đã hoàn tất: ${latest.title}`);
  }
  if (latest) {
    setText('.production-card .status-pill', latest.status.replaceAll('_', ' '));
    setText('.package-file strong', latest.package_path ? latest.package_path.split(/[\\/]/).at(-1) : 'Chưa có package');
    setText('.package-file p', latest.package_digest ? `${latest.package_digest.slice(0, 12)}… · đã xác minh` : 'Đang chờ runtime');
    const packageDigest = document.querySelector('.package-meta dd');
    if (packageDigest && latest.package_digest) packageDigest.textContent = `${latest.package_digest.slice(0, 12)}…`;
    if (latest.kind === 'STAGE2_CREATE') {
      setText('#stage2-summary', `${latest.execution_mode} · ${latest.committed_count}/${latest.required_count} · ${latest.status}`);
      setText('.package-card h2', 'Stage 02 Package');
    }
  }
}

function renderEvents(events) {
  const list = document.querySelector('.activity-list');
  if (!list) return;
  if (!events.length) {
    const empty = document.createElement('li');
    empty.className = 'empty-inline';
    empty.textContent = 'Chưa có sự kiện runtime.';
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...events.slice(0, 4).map((event) => {
    const item = document.createElement('li');
    const successful = event.event_type.includes('PASS') || event.event_type.includes('COMMITTED');
    const mark = document.createElement('span');
    mark.className = `activity-mark ${successful ? 'pass' : 'process'}`;
    mark.textContent = successful ? '✓' : '↻';
    const copy = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = event.event_type.replaceAll('_', ' ');
    const detail = document.createElement('p');
    detail.textContent = event.stage_id ? `Stage ${event.stage_id.slice(0, 8)}…` : 'Workflow';
    copy.append(title, detail);
    const time = document.createElement('time');
    time.textContent = new Date(event.created_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
    item.append(mark, copy, time);
    return item;
  }));
}

function renderGates(gates) {
  const table = document.querySelector('.validation-table');
  const overview = document.querySelector('.validation-card');
  overview.querySelectorAll('.issue-row,.empty-inline').forEach((row) => row.remove());
  if (!gates.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-inline';
    empty.textContent = '✓ Tất cả gate hiện hành đều đạt.';
    overview.append(empty);
  }
  if (!table) return;
  table.querySelectorAll('.table-row:not(.table-head),.empty-inline').forEach((row) => row.remove());
  if (!gates.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-inline';
    empty.textContent = 'Chưa có gate cần xử lý.';
    table.append(empty);
    return;
  }
  gates.forEach((gate) => {
    const row = document.createElement('button');
    row.className = 'table-row';
    row.setAttribute('role', 'row');
    row.dataset.asset = gate.artifact_role;
    row.dataset.status = `${gate.status} · ${gate.detector_class}`;
    row.dataset.detail = JSON.stringify(gate.evidence);
    row.dataset.stage = gate.stage_id;
    row.dataset.transaction = '—';
    row.dataset.call = '—';
    row.dataset.detector = gate.detector_class;
    const asset = document.createElement('span');
    const swatch = document.createElement('i');
    swatch.className = 'asset-swatch violet';
    const role = document.createElement('b');
    role.textContent = gate.artifact_role;
    const digest = document.createElement('small');
    digest.textContent = `${gate.artifact_sha256.slice(0, 12)}…`;
    asset.append(swatch, role, digest);
    const gateName = document.createElement('span');
    gateName.textContent = gate.gate_id;
    const result = document.createElement('span');
    const badge = document.createElement('em');
    badge.className = 'badge fail';
    badge.textContent = gate.status;
    result.append(badge);
    const detector = document.createElement('span');
    detector.textContent = gate.detector_class;
    const arrow = document.createElement('span');
    arrow.textContent = '›';
    row.append(asset, gateName, result, detector, arrow);
    row.addEventListener('click', () => openInspector(row));
    table.append(row);
  });
}

async function refreshRuntime() {
  if (runtimeRefreshInFlight) return;
  runtimeRefreshInFlight = true;
  try {
    const response = await fetch('/api/v1/studio', { headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    runtimeFailureCount = 0;
    applySnapshot(await response.json());
  } catch (error) {
    runtimeFailureCount += 1;
    latestSnapshot = null;
    setRuntimeState('OFFLINE');
    renderStageDetail(null, []);
    renderExecutionDashboard({ workflow: null, events: [], gates: [], stages: [] }, null, null);
  } finally {
    runtimeRefreshInFlight = false;
  }
}

async function refreshReleaseReadiness() {
  const target = document.querySelector('#release-readiness');
  if (!target) return;
  try {
    const response = await fetch('/api/v1/release', { cache: 'no-store' });
    const result = await response.json();
    target.textContent = result.status === 'PASS'
      ? `✓ Đủ điều kiện xuất bản · SHA-256 ${result.stage4_output_sha256.slice(0, 16)}…`
      : `⚠ Chưa đủ điều kiện · ${result.blockers.join(', ')}`;
  } catch { target.textContent = 'Không đọc được trạng thái xuất bản.'; }
}

async function refreshDiagnostics() {
  const target = document.querySelector('#diagnostics-summary');
  if (!target) return;
  try {
    const response = await fetch('/api/v1/diagnostics', { cache: 'no-store' });
    const result = await response.json();
    const deps = result.dependencies;
    target.textContent = `${result.status === 'PASS' ? '✓' : '⚠'} SQLite ${result.sqlite.integrity} · ${result.jobs.total} jobs · FFmpeg ${deps.ffmpeg ? 'sẵn sàng' : 'thiếu'} · trống ${Math.round(result.disk.free_bytes / 1073741824)} GB`;
  } catch { target.textContent = 'Không đọc được diagnostics runtime.'; }
}

function openInspector(trigger) {
  lastInspectorTrigger = trigger;
  document.querySelector('#inspector-title').textContent = trigger.dataset.asset;
  document.querySelector('#inspector-status').textContent = trigger.dataset.status;
  document.querySelector('#inspector-detail').textContent = trigger.dataset.detail;
  document.querySelector('#inspector-stage').textContent = trigger.dataset.stage || '—';
  document.querySelector('#inspector-transaction').textContent = trigger.dataset.transaction || '—';
  document.querySelector('#inspector-call').textContent = trigger.dataset.call || '—';
  document.querySelector('#inspector-detector').textContent = trigger.dataset.detector || '—';
  inspector.classList.add('open');
  inspector.setAttribute('aria-hidden', 'false');
  overlay.classList.add('open');
  inspector.querySelector('.close-inspector').focus();
}

function closeInspector() {
  const wasOpen = inspector.classList.contains('open');
  inspector.classList.remove('open');
  inspector.setAttribute('aria-hidden', 'true');
  overlay.classList.remove('open');
  if (wasOpen && lastInspectorTrigger?.isConnected) lastInspectorTrigger.focus();
}

navItems.forEach((item) => item.addEventListener('click', () => openView(item.dataset.view)));
document.querySelectorAll('[data-view-target]').forEach((item) => item.addEventListener('click', () => openView(item.dataset.viewTarget)));
document.querySelectorAll('.stage[data-stage]').forEach((button) => button.addEventListener('click', () => {
  selectedExecutionStage = `STAGE${button.dataset.stage}`;
  openView('queue');
  const stage = latestSnapshot?.stages?.find((item) => item.stage === selectedExecutionStage);
  renderExecutionDashboard(latestSnapshot || { events: [], gates: [] }, stage, latestSnapshot?.jobs?.find((job) => job.stage_id === stage?.id) || null);
}));
document.querySelectorAll('[data-asset]').forEach((item) => item.addEventListener('click', () => openInspector(item)));
document.querySelectorAll('.close-inspector').forEach((item) => item.addEventListener('click', closeInspector));
overlay.addEventListener('click', () => {
  closeInspector();
  sidebar.classList.remove('open');
  mobileMenu.setAttribute('aria-expanded', 'false');
});
mobileMenu.addEventListener('click', () => {
  const open = !sidebar.classList.contains('open');
  sidebar.classList.toggle('open', open);
  overlay.classList.toggle('open', open);
  mobileMenu.setAttribute('aria-expanded', String(open));
  if (open) sidebar.querySelector('.nav-item')?.focus();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    if (inspector.classList.contains('open')) closeInspector();
    else if (sidebar.classList.contains('open')) {
      sidebar.classList.remove('open');
      overlay.classList.remove('open');
      mobileMenu.setAttribute('aria-expanded', 'false');
      mobileMenu.focus();
    }
  }
  if (event.key === 'Tab' && inspector.classList.contains('open')) {
    const focusable = [...inspector.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});

document.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', () => {
  if (button.dataset.action === 'delete-story') {
    const workflowId = document.querySelector('.breadcrumb strong')?.dataset.workflowId;
    if (!workflowId || workflowId === '—') return showToast('Chưa có story hiện hành.');
    if (!window.confirm('Xóa story hiện hành và toàn bộ dữ liệu của story này?')) return;
    fetch('/api/v1/story/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workflow_id: workflowId, confirm: true }) })
      .then(async (response) => { const payload = await response.json(); if (!response.ok) throw new Error(payload.message || 'Không thể xóa story.'); showToast('Đã xóa story hiện hành.'); window.location.reload(); })
      .catch((error) => showToast(error.message));
    return;
  }
  if (button.dataset.action === 'delete-workspace') {
    const confirmed = window.confirm('Xóa workspace hiện hành và toàn bộ dữ liệu bên trong? Hành động này không thể hoàn tác.');
    if (!confirmed) return;
    fetch('/api/v1/workspace/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: true }),
    }).then(async (response) => {
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Không thể xóa workspace.');
      showToast('Đã xóa workspace hiện hành.');
      document.body.innerHTML = '<main class="deleted-workspace"><h1>Workspace đã được xóa</h1><p>Server local đã dừng. Bạn có thể đóng cửa sổ này.</p></main>';
    }).catch((error) => showToast(error.message));
    return;
  }
  if (button.dataset.action === 'create-story') {
    resetStage1Dialog();
    document.querySelector('#story-dialog').showModal();
    return;
  }
  if (button.dataset.action === 'create-stage2') {
    document.querySelector('#stage2-dialog').showModal();
    return;
  }
  if (button.dataset.action === 'create-stage3') {
    fetch('/api/v1/stage3', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ execution_mode: 'VLM_LOCAL' }) })
      .then(async (response) => { const result = await response.json(); if (!response.ok) throw new Error(result.message || result.code); showToast('Stage 3 Portrait đã vào hàng đợi.'); openView('queue'); refreshRuntime(); })
      .catch((error) => showToast(error.message));
    return;
  }
  if (button.dataset.action === 'create-stage4') {
    fetch('/api/v1/stage4', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(async (response) => { const result = await response.json(); if (!response.ok) throw new Error(result.message || result.code); showToast('Stage 4 Video đã vào hàng đợi FFmpeg local.'); openView('queue'); refreshRuntime(); })
      .catch((error) => showToast(error.message));
    return;
  }
  if (button.dataset.action === 'backup') {
    fetch('/api/v1/backup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'STATE_ONLY' }) })
      .then(async (response) => { const result = await response.json(); if (!response.ok) throw new Error(result.message || result.code); showToast(`Backup đã tạo · ${result.result.sha256.slice(0, 16)}…`); })
      .catch((error) => showToast(error.message));
    return;
  }
  if (button.dataset.action === 'retry-stage2') {
    if (!latestRuntimeJob) return;
    fetch(`/api/v1/jobs/${latestRuntimeJob.id}/retry`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || result.code);
        showToast('Đã tiếp tục Stage 2 bằng transaction hiện có.');
        refreshRuntime();
      })
      .catch((error) => showToast(error.message));
    return;
  }
  if (button.dataset.action === 'cancel-job') {
    if (!latestRuntimeJob) return;
    fetch(`/api/v1/jobs/${latestRuntimeJob.id}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(async (response) => { const result = await response.json(); if (!response.ok) throw new Error(result.message || result.code); showToast('Đã gửi yêu cầu hủy an toàn.'); refreshRuntime(); })
      .catch((error) => showToast(error.message));
    return;
  }
  if (button.dataset.action === 'review-stage2') {
    openSemanticReview();
    return;
  }
  if (button.dataset.action === 'retry') {
    const transactionId = document.querySelector('#inspector-transaction').textContent;
    if (!transactionId || transactionId === '—') return showToast('Không xác định được transaction cần tạo lại.');
    button.disabled = true;
    fetch(`/api/v1/transactions/${encodeURIComponent(transactionId)}/retry`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
    }).then(async (response) => {
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || result.code || 'Không thể tạo lại tài sản.');
      closeInspector();
      showToast('Đã đưa tài sản vào hàng đợi tạo lại.');
      refreshRuntime();
    }).catch((error) => showToast(error.message)).finally(() => { button.disabled = false; });
    return;
  }
  const messages = {
    package: 'Đã mở bản kiểm kê Stage 01 package.',
    resume: 'Workflow Stage 02 đang tiếp tục.',
    recheck: 'Đã đưa 2 tài sản vào hàng đợi kiểm tra.',
    retry: 'Đã tạo một lần thử mới, giữ nguyên lịch sử cũ.',
    pause: 'Hàng đợi sẽ dừng sau tác vụ hiện tại.'
  };
  showToast(messages[button.dataset.action]);
}));

const storyDialog = document.querySelector('#story-dialog');
const storyForm = document.querySelector('#story-form');
const durationProfiles = {
  YOUTH_SAFE: { KIDS_3_6: [8, 12, 10], KIDS_7_10: [12, 18, 15], PRETEEN_11_14: [18, 28, 23], TEEN_15_18: [24, 36, 30] },
  ADULT_STANDARD: { AUTO: [25, 38, 32], default: [25, 38, 32] },
  SERIAL_DETECTIVE: { START_SERIES: [35, 50, 42], CONTINUE_SERIES: [30, 45, 36], FINALIZE_SERIES: [40, 58, 48] }
};
const profilePresets = {
  YOUTH_SAFE: ['Ngôi Nhà Của Những Cảm Xúc Nhỏ', 'Tiệm Vá Những Lời Hứa', 'Đội Sửa Chữa Sau Giờ Học', 'Chuyến Tàu Của Những Câu Hỏi Hay', 'Câu Lạc Bộ Manh Mối Tử Tế', 'Trạm Khoa Học Bên Dòng Sông', 'Phòng Tin Tức Của Lớp 6A', 'Hồ Sơ Sau Giờ Tan Học', 'Dự Án Ngày Mai Của Chúng Ta', 'Ranh Giới Của Những Người Bạn Tốt'],
  ADULT_STANDARD: ['Trọng Sinh Báo Thù Hào Môn', 'Xuyên Không Thành Người Thừa Kế Bị Gạt Khỏi Di Chúc', 'Ngôi Nhà Có Ba Phiên Bản Ký Ức', 'Bữa Cơm Có Chiếc Ghế Bỏ Trống', 'Bản Hợp Đồng Không Thể Ký Bằng Im Lặng', 'Báo Cáo Không Ai Muốn Ký', 'Ban Công Có Ánh Đèn Bật Muộn', 'Bí Mật Trong Khu Chung Cư Mất Điện', 'Bắt Đầu Lại Ở Nửa Sau Cuộc Đời', 'Lớp Học Tối Của Những Người Bắt Đầu Lại'],
  SERIAL_DETECTIVE: ['Tòa Soạn Và Những Nguồn Tin Biến Mất', 'Tuyến Phà Không Xuất Hiện Trên Lịch', 'Bệnh Viện Và Những Danh Tính Không Khớp', 'Phiên Tòa Của Nhân Chứng Thứ Mười Ba', 'Phòng Tranh Của Những Tác Phẩm Đổi Chủ', 'Khu Phố Chỉ Xuất Hiện Trên Bản Đồ Cũ', 'Kho Chứng Cứ Không Có Trong Sổ Sách', 'Đài Phát Thanh Của Những Bản Tin Cũ', 'Khu Nghỉ Dưỡng Chỉ Mở Bảy Ngày Mỗi Năm', 'Vườn Thực Vật Có Những Mùa Nở Sai Lịch']
};
let confirmingDuration = false;
function resetStage1Dialog() {
  storyForm.reset();
  confirmingDuration = false;
  document.querySelector('#story-setup-step').hidden = false;
  document.querySelector('#duration-step').hidden = true;
  document.querySelector('#back-story-step').hidden = true;
  document.querySelector('#story-submit').innerHTML = 'Tiếp tục <span>→</span>';
  document.querySelector('#dialog-message').hidden = true;
  storyForm.content_source.value = 'preset';
  storyForm.querySelectorAll('.source-tabs button').forEach((item) => item.classList.toggle('active', item.dataset.source === 'preset'));
  storyForm.querySelectorAll('.source-panel').forEach((panel) => { panel.hidden = panel.dataset.panel !== 'preset'; });
  showProfileOptions();
}
document.querySelectorAll('.dialog-close').forEach((button) => button.addEventListener('click', () => storyDialog.close()));
const selectedProfile = () => storyForm.querySelector('input[name="profile"]:checked')?.value;
const renderPresetOptions = (profile) => {
  const select = storyForm.preset;
  const presets = profilePresets[profile] || [];
  select.replaceChildren(new Option(profile ? 'Chọn một preset…' : 'Chọn profile nội dung trước…', ''));
  presets.forEach((title, index) => select.add(new Option(`${String(index + 1).padStart(2, '0')} · ${title}`, `${String(index + 1).padStart(2, '0')} · ${title}`)));
  select.disabled = presets.length === 0;
};
const selectedDuration = () => {
  const profile = selectedProfile();
  if (profile === 'YOUTH_SAFE') return durationProfiles.YOUTH_SAFE[storyForm.age_profile.value];
  if (profile === 'SERIAL_DETECTIVE') return durationProfiles.SERIAL_DETECTIVE[storyForm.episode_mode.value];
  return durationProfiles.ADULT_STANDARD[storyForm.adult_family.value] || durationProfiles.ADULT_STANDARD.default;
};
const showProfileOptions = () => {
  const profile = selectedProfile();
  document.querySelector('#youth-options').hidden = profile !== 'YOUTH_SAFE';
  document.querySelector('#adult-options').hidden = profile !== 'ADULT_STANDARD';
  document.querySelector('#serial-options').hidden = profile !== 'SERIAL_DETECTIVE';
  renderPresetOptions(profile);
};
storyForm.querySelectorAll('input[name="profile"]').forEach((input) => input.addEventListener('change', showProfileOptions));
storyForm.querySelectorAll('.source-tabs button').forEach((button) => button.addEventListener('click', () => {
  storyForm.content_source.value = button.dataset.source;
  storyForm.querySelectorAll('.source-tabs button').forEach((item) => item.classList.toggle('active', item === button));
  storyForm.querySelectorAll('.source-panel').forEach((panel) => { panel.hidden = panel.dataset.panel !== button.dataset.source; });
}));
const validContentSource = () => {
  const source = storyForm.content_source.value;
  if (source === 'random') return true;
  const fields = { preset: storyForm.preset, topic: storyForm.story_topic, brief: storyForm.content_brief, idea: storyForm.plot_idea };
  return Boolean(fields[source]?.value.trim());
};
const showDurationConfirmation = () => {
  const profile = selectedProfile();
  if (!profile) return 'Hãy chọn một profile nội dung.';
  if (!validContentSource()) return 'Hãy chọn hoặc nhập một nguồn nội dung.';
  if (profile === 'SERIAL_DETECTIVE' && storyForm.episode_mode.value !== 'START_SERIES') return 'Tiếp tục/kết series chưa được Stage 1 hỗ trợ; chỉ có thể bắt đầu series mới.';
  if (profile === 'SERIAL_DETECTIVE' && Number(storyForm.episode.value) !== 1) return 'Series mới phải bắt đầu từ episode 1.';
  const [minimum, maximum, target] = selectedDuration();
  const descriptor = profile === 'YOUTH_SAFE' ? `nhóm tuổi ${storyForm.age_profile.options[storyForm.age_profile.selectedIndex].text}` : profile === 'SERIAL_DETECTIVE' ? storyForm.episode_mode.options[storyForm.episode_mode.selectedIndex].text.toLowerCase() : 'nhóm truyện người lớn';
  setText('#duration-title', `Thời lượng cho ${descriptor}`);
  setText('#duration-copy', `Prompt gợi ý khoảng ${target} phút, trong khoảng ${minimum}–${maximum} phút. Đây là thời lượng đọc ước tính, chưa gồm nhạc và khoảng nghỉ bổ sung.`);
  setText('#duration-recommendation', `Khoảng ${target} phút`);
  storyForm.duration_minutes.min = minimum; storyForm.duration_minutes.max = maximum; storyForm.duration_minutes.value = target;
  document.querySelector('#story-setup-step').hidden = true; document.querySelector('#duration-step').hidden = false;
  document.querySelector('#back-story-step').hidden = false; document.querySelector('#story-submit').innerHTML = 'Tạo Stage 01 <span>→</span>';
  confirmingDuration = true;
  return null;
};
document.querySelector('#back-story-step').addEventListener('click', () => { document.querySelector('#story-setup-step').hidden = false; document.querySelector('#duration-step').hidden = true; document.querySelector('#back-story-step').hidden = true; document.querySelector('#story-submit').innerHTML = 'Tiếp tục <span>→</span>'; confirmingDuration = false; });
storyForm.querySelectorAll('input[name="duration_choice"]').forEach((input) => input.addEventListener('change', () => { document.querySelector('.custom-duration').hidden = storyForm.duration_choice.value !== 'custom'; }));
storyForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = storyForm.querySelector('[type="submit"]');
  const message = document.querySelector('#dialog-message');
  if (!confirmingDuration) { const problem = showDurationConfirmation(); if (problem) { message.hidden = false; message.classList.remove('success'); message.textContent = problem; } return; }
  submit.disabled = true;
  message.hidden = true;
  const data = new FormData(storyForm);
  const [minimum, maximum, target] = selectedDuration();
  const duration = data.get('duration_choice') === 'custom' ? Number(data.get('duration_minutes')) : target;
  if (!Number.isInteger(duration) || duration < minimum || duration > maximum) { message.hidden = false; message.textContent = `Thời lượng phải nằm trong khoảng ${minimum}–${maximum} phút.`; submit.disabled = false; return; }
  const sourceText = data.get('content_source') === 'preset' ? data.get('preset') : data.get(data.get('content_source') === 'topic' ? 'story_topic' : data.get('content_source') === 'brief' ? 'content_brief' : 'plot_idea');
  const seeded = String(data.get('seed') || '').trim();
  const seed = seeded ? Number(seeded) : Math.floor(Math.random() * 2147483648);
  const suggestedTitle = data.get('content_source') === 'preset'
    ? String(sourceText).replace(/^\d+ · /, '')
    : data.get('content_source') === 'random' ? `Truyện ngẫu hứng ${seed}` : String(sourceText).trim();
  const title = String(data.get('title') || '').trim() || suggestedTitle.slice(0, 120);
  const sourceLabels = { preset: 'Serial preset', topic: 'Chủ đề', brief: 'Tóm tắt nội dung', idea: 'Ý tưởng cốt truyện', random: 'Yêu cầu random' };
  const profileDetail = data.get('profile') === 'YOUTH_SAFE' ? `Nhóm tuổi: ${data.get('age_profile')}.` : data.get('profile') === 'ADULT_STANDARD' ? `Nhóm truyện: ${data.get('adult_family')}.` : 'Bắt đầu series mới.';
  const creativeInput = `${sourceLabels[data.get('content_source')]}: ${data.get('content_source') === 'random' ? 'Tạo premise mới trong profile đã chọn.' : String(sourceText).trim()} ${profileDetail}`;
  const payload = {
    title, series: String(data.get('series') || '').trim() || null,
    episode: Number(data.get('episode')), episode_mode: data.get('profile') === 'SERIAL_DETECTIVE' ? data.get('episode_mode') : null,
    profile: data.get('profile'), language: data.get('language'), duration_minutes: duration,
    seed, creative_input: creativeInput
  };
  try {
    const response = await fetch('/api/v1/workflows', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || result.code);
    message.hidden = false;
    message.classList.add('success');
    message.textContent = 'Đã đưa Stage 1 vào hàng đợi. Bạn có thể theo dõi tại mục Hàng đợi.';
    window.setTimeout(() => { storyDialog.close(); openView('queue'); refreshRuntime(); }, 900);
  } catch (error) {
    message.hidden = false;
    message.classList.remove('success');
    message.textContent = error.message;
  } finally { submit.disabled = false; }
});

const stage2Dialog = document.querySelector('#stage2-dialog');
const stage2Form = document.querySelector('#stage2-form');
document.querySelectorAll('.stage2-dialog-close').forEach((button) => button.addEventListener('click', () => stage2Dialog.close()));
stage2Form.execution_mode.addEventListener('change', () => {
  setText('#stage2-mode-hint', stage2Form.execution_mode.value === 'COMFYUI'
    ? 'Dùng ComfyUI tại 127.0.0.1:8188; package sẽ chờ semantic review sau khi tạo ảnh.'
    : 'Tạo đủ 10 ảnh và dùng semantic fixture chỉ dành cho kiểm thử.');
});
stage2Form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = stage2Form.querySelector('[type="submit"]');
  const message = document.querySelector('#stage2-dialog-message');
  submit.disabled = true;
  message.hidden = true;
  const data = new FormData(stage2Form);
  const payload = { execution_mode: data.get('execution_mode') };
  const source = String(data.get('source_package') || '').trim();
  if (source) payload.source_package = source;
  try {
    const response = await fetch('/api/v1/stage2', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || result.code);
    message.hidden = false;
    message.classList.add('success');
    message.textContent = 'Stage 2 đã vào hàng đợi một-tác-vụ-nặng.';
    window.setTimeout(() => { stage2Dialog.close(); openView('queue'); refreshRuntime(); }, 900);
  } catch (error) {
    message.hidden = false;
    message.classList.remove('success');
    message.textContent = error.message;
  } finally { submit.disabled = false; }
});

const reviewDialog = document.querySelector('#review-dialog');
const reviewForm = document.querySelector('#review-form');
document.querySelectorAll('.review-dialog-close').forEach((button) => button.addEventListener('click', () => reviewDialog.close()));
async function openSemanticReview() {
  if (!latestRuntimeJob) return;
  try {
    const response = await fetch(`/api/v1/jobs/${latestRuntimeJob.id}/semantic-review`, { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || result.code);
    const container = document.querySelector('#review-assets');
    container.replaceChildren(...result.result.assets.map((asset) => {
      const row = document.createElement('label'); row.className = 'review-item'; row.dataset.basename = asset.basename;
      const name = document.createElement('span'); const strong = document.createElement('strong'); strong.textContent = asset.basename;
      const digest = document.createElement('small'); digest.textContent = asset.image_sha256; name.append(strong, digest);
      const status = document.createElement('select'); status.innerHTML = '<option value="PASS">PASS</option><option value="FAIL">FAIL</option>';
      const findings = document.createElement('textarea'); findings.required = true; findings.maxLength = 500; findings.placeholder = 'Mô tả chi tiết quan sát trực tiếp trên ảnh…';
      row.append(name, status, findings); return row;
    }));
    reviewDialog.showModal();
  } catch (error) { showToast(error.message); }
}
reviewForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const assessments = [...document.querySelectorAll('.review-item')].map((row) => ({
    basename: row.dataset.basename, status: row.querySelector('select').value,
    observable_findings: [row.querySelector('textarea').value.trim()]
  }));
  const message = document.querySelector('#review-dialog-message');
  try {
    const response = await fetch(`/api/v1/jobs/${latestRuntimeJob.id}/semantic-review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ assessments }) });
    const result = await response.json(); if (!response.ok) throw new Error(result.message || result.code);
    message.hidden = false; message.classList.add('success'); message.textContent = result.result.status === 'PASS' ? 'Semantic PASS; Stage 2 package đã được tạo.' : 'Assessment đã lưu nhưng aggregate gate vẫn bị chặn.';
    await refreshRuntime();
  } catch (error) { message.hidden = false; message.classList.remove('success'); message.textContent = error.message; }
});
document.querySelector('#run-vlm-review').addEventListener('click', async () => {
  const message = document.querySelector('#review-dialog-message');
  try {
    const response = await fetch(`/api/v1/jobs/${latestRuntimeJob.id}/vlm-review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const result = await response.json(); if (!response.ok) throw new Error(result.message || result.code);
    message.hidden = false; message.classList.add('success'); message.textContent = 'Đã đưa Qwen2.5-VL local vào hàng đợi GPU độc quyền.';
    window.setTimeout(() => { reviewDialog.close(); openView('queue'); refreshRuntime(); }, 900);
  } catch (error) { message.hidden = false; message.classList.remove('success'); message.textContent = error.message; }
});

document.querySelectorAll('.copy-button').forEach((button) => button.addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(button.dataset.copy); showToast('Đã sao chép SHA-256.'); }
  catch { showToast('SHA-256: ' + button.dataset.copy); }
}));

document.querySelectorAll('.copy-inline').forEach((button) => button.addEventListener('click', async () => {
  if (!button.dataset.copy) return;
  try { await navigator.clipboard.writeText(button.dataset.copy); showToast('Đã sao chép định danh.'); }
  catch { showToast(button.dataset.copy); }
}));

document.querySelectorAll('[data-transaction-filter]').forEach((button) => button.addEventListener('click', () => {
  transactionFilter = button.dataset.transactionFilter;
  button.parentElement.querySelectorAll('button').forEach((item) => item.classList.toggle('active', item === button));
  const stage = latestSnapshot?.stages?.find((item) => item.stage === selectedExecutionStage) || (latestSnapshot?.stages ? [...latestSnapshot.stages].reverse().find((item) => item.status !== 'PASS') || latestSnapshot.stages.at(-1) : null);
  renderExecutionTransactions(stage?.transactions || [], latestSnapshot?.gates || []);
}));

document.querySelectorAll('[data-event-filter]').forEach((button) => button.addEventListener('click', () => {
  eventFilter = button.dataset.eventFilter;
  button.parentElement.querySelectorAll('button').forEach((item) => item.classList.toggle('active', item === button));
  renderExecutionEvents(latestSnapshot?.events || []);
}));

document.querySelector('#copy-diagnostics').addEventListener('click', async () => {
  if (!latestSnapshot) return;
  const report = JSON.stringify({
    workflow: latestSnapshot.workflow,
    jobs: latestSnapshot.jobs,
    stages: latestSnapshot.stages,
    gates: latestSnapshot.gates,
    events: latestSnapshot.events,
  }, null, 2);
  try { await navigator.clipboard.writeText(report); showToast('Đã sao chép chẩn đoán runtime.'); }
  catch { showToast('Trình duyệt không cho phép sao chép tự động.'); }
});

document.querySelectorAll('.segmented button').forEach((button) => button.addEventListener('click', () => {
  button.parentElement.querySelectorAll('button').forEach((item) => item.classList.remove('active'));
  button.classList.add('active');
}));

const search = document.querySelector('.search-box input');
if (search) search.addEventListener('input', () => {
  const query = search.value.toLowerCase();
  document.querySelectorAll('.validation-table .table-row:not(.table-head)').forEach((row) => {
    row.style.display = row.textContent.toLowerCase().includes(query) ? 'grid' : 'none';
  });
});

function registerAgentTools() {
  const context = document.modelContext;
  if (!context?.registerTool) return;
  const tools = [
    {
      name: 'open_studio_view',
      title: 'Mở khu vực Studio',
      description: 'Điều hướng giao diện Audio Story Studio tới một khu vực làm việc có sẵn.',
      inputSchema: {
        type: 'object',
        properties: { view: { type: 'string', enum: ['overview', 'story', 'characters', 'visual', 'timeline', 'queue', 'validation', 'export', 'activity'] } },
        required: ['view'], additionalProperties: false
      },
      annotations: { readOnlyHint: true, untrustedContentHint: false },
      execute(input) { openView(input.view); return { view: input.view, opened: true }; }
    },
    {
      name: 'create_stage1_workflow',
      title: 'Tạo Stage 1',
      description: 'Tạo và đưa một Audio Story Stage 1 deterministic vào hàng đợi runtime local.',
      inputSchema: {
        type: 'object',
        properties: {
          title: { type: 'string', minLength: 1, maxLength: 120 },
          series: { type: 'string', minLength: 1, maxLength: 120 },
          episode: { type: 'integer', minimum: 1, maximum: 9999 },
          episode_mode: { type: 'string', enum: ['START_SERIES'] },
          creative_input: { type: 'string', maxLength: 2000 },
          profile: { type: 'string', enum: ['YOUTH_SAFE', 'ADULT_STANDARD', 'SERIAL_DETECTIVE'] },
          language: { type: 'string', enum: ['vi', 'en'] },
          duration_minutes: { type: 'integer' }, seed: { type: 'integer', minimum: 0, maximum: 2147483647 }
        },
        required: ['title', 'profile', 'language', 'duration_minutes', 'seed'], additionalProperties: false
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      async execute(input) {
        const response = await fetch('/api/v1/workflows', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input)
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || result.code);
        openView('queue');
        await refreshRuntime();
        return { job_id: result.result.id, status: result.result.status };
      }
    },
    {
      name: 'create_stage2_workflow',
      title: 'Tạo Stage 2',
      description: 'Tạo 10 landscape assets từ Stage 1 package bằng mock deterministic hoặc ComfyUI local.',
      inputSchema: {
        type: 'object',
        properties: {
          execution_mode: { type: 'string', enum: ['COMFYUI'] },
          source_package: { type: 'string' }
        },
        required: ['execution_mode'], additionalProperties: false
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      async execute(input) {
        const response = await fetch('/api/v1/stage2', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input)
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || result.code);
        openView('queue');
        await refreshRuntime();
        return { job_id: result.result.id, status: result.result.status };
      }
    }
  ];
  tools.forEach((tool) => {
    try { void Promise.resolve(context.registerTool(tool)).catch(() => {}); } catch { /* Unsupported preview context. */ }
  });
}

registerAgentTools();
const initialView = window.location.hash.slice(1);
openView(document.getElementById(initialView)?.classList.contains('workspace-view') ? initialView : 'overview');
setRuntimeState('BOOTING');
refreshRuntime();
refreshReleaseReadiness();
refreshDiagnostics();
window.setInterval(() => {
  if (document.hidden || runtimeState === 'OFFLINE') return;
  refreshRuntime();
  refreshReleaseReadiness();
  refreshDiagnostics();
}, 5000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && runtimeState !== 'OFFLINE') refreshRuntime();
});
