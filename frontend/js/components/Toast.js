/**
 * Toast.js — Transient notification system for forensic feedback.
 *
 * Provides non-blocking feedback for async actions (export, hash verification, report generation).
 * Strict CSP compliant: no inline event handlers, no inline styles.
 */

const TOAST_MAX_COUNT = 3;
const TOAST_AUTO_DISMISS_MS = 4000;

function getOrCreateToastContainer() {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    container.setAttribute('aria-label', 'Notifications');
    container.setAttribute('role', 'region');
    document.body.appendChild(container);
  }
  return container;
}

function showToast(message, kind = 'info', options = {}) {
  const container = getOrCreateToastContainer();

  // Enforce max 3 stacked toasts — remove oldest if exceeding limit
  const currentToasts = container.querySelectorAll('.toast:not(.toast-dismissing)');
  if (currentToasts.length >= TOAST_MAX_COUNT) {
    for (let i = 0; i <= currentToasts.length - TOAST_MAX_COUNT; i++) {
      dismissToast(currentToasts[i]);
    }
  }

  const normalizedKind = ['success', 'info', 'warn', 'error'].includes(kind) ? kind : 'info';
  const toast = document.createElement('div');
  toast.className = `toast toast-${normalizedKind}`;
  toast.setAttribute('role', normalizedKind === 'error' ? 'alert' : 'status');
  toast.setAttribute('aria-live', normalizedKind === 'error' ? 'assertive' : 'polite');

  let iconName = 'info';
  if (normalizedKind === 'success') iconName = 'check-circle';
  else if (normalizedKind === 'warn') iconName = 'alert';
  else if (normalizedKind === 'error') iconName = 'x-circle';

  const iconEl = document.createElement('div');
  iconEl.className = 'toast-icon';
  iconEl.innerHTML = icon(iconName);

  const bodyEl = document.createElement('div');
  bodyEl.className = 'toast-body';

  if (options.title) {
    const titleEl = document.createElement('div');
    titleEl.className = 'toast-title';
    titleEl.textContent = options.title;
    bodyEl.appendChild(titleEl);
  }

  const msgEl = document.createElement('div');
  msgEl.className = 'toast-msg';
  if (options.html) {
    msgEl.innerHTML = message;
  } else {
    msgEl.textContent = message;
  }
  bodyEl.appendChild(msgEl);

  if (options.action && options.action.label) {
    const actionWrap = document.createElement('div');
    actionWrap.className = 'toast-action';
    if (options.action.href) {
      const a = document.createElement('a');
      a.className = 'btn btn-secondary btn-sm';
      a.href = options.action.href;
      if (options.action.download) a.setAttribute('download', options.action.download);
      a.textContent = options.action.label;
      actionWrap.appendChild(a);
    } else if (typeof options.action.onClick === 'function') {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-secondary btn-sm';
      btn.textContent = options.action.label;
      btn.addEventListener('click', () => {
        options.action.onClick();
        dismissToast(toast);
      });
      actionWrap.appendChild(btn);
    }
    bodyEl.appendChild(actionWrap);
  }

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'toast-close';
  closeBtn.setAttribute('aria-label', 'Dismiss notification');
  closeBtn.innerHTML = icon('x');
  closeBtn.addEventListener('click', () => dismissToast(toast));

  toast.appendChild(iconEl);
  toast.appendChild(bodyEl);
  toast.appendChild(closeBtn);

  // Auto-dismiss with hover pause
  let remainingMs = typeof options.duration === 'number' ? options.duration : TOAST_AUTO_DISMISS_MS;
  let timerId = null;
  let startTimestamp = Date.now();

  const startTimer = () => {
    if (remainingMs <= 0) return;
    startTimestamp = Date.now();
    timerId = setTimeout(() => {
      dismissToast(toast);
    }, remainingMs);
  };

  const pauseTimer = () => {
    if (timerId) {
      clearTimeout(timerId);
      timerId = null;
      remainingMs -= (Date.now() - startTimestamp);
      if (remainingMs < 500) remainingMs = 500;
    }
  };

  toast.addEventListener('mouseenter', pauseTimer);
  toast.addEventListener('mouseleave', startTimer);

  container.appendChild(toast);
  startTimer();

  return toast;
}

function dismissToast(toast) {
  if (!toast || toast.classList.contains('toast-dismissing')) return;
  toast.classList.add('toast-dismissing');
  setTimeout(() => {
    if (toast.parentNode) {
      toast.parentNode.removeChild(toast);
    }
  }, 250);
}
