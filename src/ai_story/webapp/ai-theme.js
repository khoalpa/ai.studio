/* AI Themes 1.0.0 — local preferences; no network or remote fonts. */
(() => {
  'use strict';
  const root = document.documentElement;
  const choices = {theme: ['neutral', 'atelier', 'paper'], mode: ['system', 'light', 'dark'], style: ['minimal', 'soft', 'editorial'], density: ['comfortable', 'compact']};
  const defaults = {theme: root.dataset.theme || 'neutral', mode: root.dataset.mode || 'system', style: root.dataset.style || 'minimal', density: root.dataset.density || 'comfortable'};
  const key = 'ai-themes:1:' + (root.dataset.themeApp || location.pathname);
  const media = matchMedia('(prefers-color-scheme: dark)');
  let state = {...defaults};
  try { const saved = JSON.parse(localStorage.getItem(key)); for (const k in choices) if (choices[k].includes(saved?.[k])) state[k] = saved[k]; } catch (_) { /* Storage may be unavailable. */ }
  function apply(next, save = true) {
    for (const k in choices) if (choices[k].includes(next[k])) state[k] = next[k];
    for (const k in choices) root.dataset[k] = state[k];
    root.dataset.resolvedMode = state.mode === 'system' ? (media.matches ? 'dark' : 'light') : state.mode;
    if (save) { try { localStorage.setItem(key, JSON.stringify(state)); } catch (_) {} }
    document.dispatchEvent(new CustomEvent('ai-theme-change', {detail: {...state}}));
  }
  apply(state, false);
  media.addEventListener('change', () => apply(state, false));
  window.AIThemes = Object.freeze({set: apply, get: () => ({...state}), reset: () => apply(defaults)});
  function mount() {
    if (document.getElementById('ui-theme-dialog')) return;
    const trigger = document.createElement('button');
    trigger.className = 'ui-theme-trigger'; trigger.type = 'button'; trigger.textContent = '◐'; trigger.title = 'Giao diện'; trigger.setAttribute('aria-label', 'Tùy chỉnh giao diện'); trigger.setAttribute('aria-haspopup', 'dialog');
    const dialog = document.createElement('dialog'); dialog.id = 'ui-theme-dialog'; dialog.className = 'ui-theme-dialog'; dialog.setAttribute('aria-labelledby', 'ui-theme-title');
    const heading = document.createElement('h2'); heading.id = 'ui-theme-title'; heading.textContent = 'Giao diện'; dialog.append(heading);
    const labels = {theme: ['Bảng màu', ['Trung tính', 'Atelier', 'Giấy']], mode: ['Chế độ', ['Theo hệ thống', 'Sáng', 'Tối']], style: ['Phong cách', ['Tối giản', 'Mềm mại', 'Biên tập']], density: ['Khoảng cách', ['Thoải mái', 'Gọn']]};
    for (const k in choices) {
      const label = document.createElement('label'); label.textContent = labels[k][0];
      const select = document.createElement('select'); select.dataset.preference = k;
      choices[k].forEach((value, i) => { const opt = document.createElement('option'); opt.value = value; opt.textContent = labels[k][1][i]; select.append(opt); });
      select.value = state[k]; select.addEventListener('change', () => apply({[k]: select.value})); label.append(select); dialog.append(label);
    }
    const actions = document.createElement('div'); actions.className = 'ui-actions';
    const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'ui-button'; reset.textContent = 'Mặc định'; reset.onclick = () => { apply(defaults); dialog.querySelectorAll('select').forEach(s => { s.value = state[s.dataset.preference]; }); };
    const close = document.createElement('button'); close.type = 'button'; close.className = 'ui-button ui-primary'; close.textContent = 'Xong'; close.onclick = () => dialog.close();
    actions.append(reset, close); dialog.append(actions); document.body.append(trigger, dialog);
    trigger.onclick = () => { dialog.querySelectorAll('select').forEach(s => { s.value = state[s.dataset.preference]; }); dialog.showModal(); }; dialog.addEventListener('close', () => trigger.focus());
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true}); else mount();
})();
