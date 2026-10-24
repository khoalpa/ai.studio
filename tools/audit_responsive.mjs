const endpoint = process.argv[2] || 'http://127.0.0.1:9223';
const targetUrl = process.argv[3] || 'http://127.0.0.1:8770/#/validation';
const widths = (process.argv[4] || '390,768,1280').split(',').map(Number);

const targets = await fetch(`${endpoint}/json`).then(response => response.json());
const target = targets.find(item => item.type === 'page' && item.url === 'about:blank')
  || targets.find(item => item.type === 'page' && item.url.startsWith('http'));
if (!target) throw new Error('Không tìm thấy tab trình duyệt để kiểm tra.');

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});

let sequence = 0;
const pending = new Map();
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message)); else resolve(message.result);
});
function send(method, params = {}) {
  const id = ++sequence;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

const results = [];
await send('Network.setCacheDisabled', { cacheDisabled: true });
for (const width of widths) {
  const height = width <= 390 ? 844 : width <= 768 ? 1024 : 900;
  await send('Emulation.setDeviceMetricsOverride', {
    width, height, deviceScaleFactor: 1, mobile: width <= 390,
  });
  const navigationUrl = `${targetUrl}${targetUrl.includes('?') ? '&' : '?'}audit_width=${width}`;
  await send('Page.navigate', { url: navigationUrl });
  await new Promise(resolve => setTimeout(resolve, 1200));
  const evaluation = await send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const root = document.documentElement;
      const heading = document.querySelector('.page-head h1');
      const action = document.querySelector('.page-head .button');
      const visible = element => element && getComputedStyle(element).visibility !== 'hidden' && getComputedStyle(element).display !== 'none';
      const withinViewport = element => {
        if (!visible(element)) return false;
        const rect = element.getBoundingClientRect();
        return rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0;
      };
      return {
        width: innerWidth,
        height: innerHeight,
        scrollWidth: root.scrollWidth,
        noHorizontalOverflow: root.scrollWidth <= innerWidth,
        headingWithinViewport: withinViewport(heading),
        actionWithinViewport: withinViewport(action),
        compactNavigation: matchMedia('(max-width: 680px)').matches,
        narrowLayout: matchMedia('(max-width: 420px)').matches,
        summaryColumns: getComputedStyle(document.querySelector('.summary-grid-four')).gridTemplateColumns.split(' ').length,
        filterStatus: document.querySelector('#filter-status')?.value,
        visibleRecords: document.querySelectorAll('[data-record-index]').length,
        sessionStatePersisted: Boolean(sessionStorage.getItem('ai-story-ui-state-v3')),
      };
    })()`,
  });
  results.push(evaluation.result.value);
}

socket.close();
console.log(JSON.stringify(results, null, 2));
if (results.some(result => !result.noHorizontalOverflow || !result.headingWithinViewport || !result.actionWithinViewport || result.filterStatus !== 'open')) {
  process.exitCode = 1;
}
