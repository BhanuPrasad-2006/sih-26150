/**
 * Modal dialog helper.
 * Uses the updated design-system button / error-banner classes.
 */
function showModal(title, bodyHtml, buttons = []) {
  const root = document.getElementById('modal-root');
  root.innerHTML = `
    <div class="modal-overlay">
      <div class="modal-content">
        <div class="card-title" style="margin-bottom:14px;">
          <span style="font-size:16px;">${title}</span>
          <button id="modal-close-btn"
            style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:20px; line-height:1; padding:0; flex-shrink:0;"
            aria-label="Close modal">✕</button>
        </div>
        <div class="modal-body" style="margin-bottom:20px; font-size:14px; line-height:1.6;">
          ${bodyHtml}
        </div>
        ${buttons.length > 0 ? `
          <div class="modal-footer" style="display:flex; justify-content:flex-end; gap:10px; flex-wrap:wrap;">
            ${buttons.map((b, i) => `<button id="modal-btn-${i}" class="btn ${b.class || 'btn-secondary'}">${b.label}</button>`).join('')}
          </div>` : ''}
      </div>
    </div>
  `;

  document.getElementById('modal-close-btn').onclick = closeModal;

  // Close on overlay click
  root.querySelector('.modal-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });

  buttons.forEach((b, i) => {
    document.getElementById(`modal-btn-${i}`).onclick = () => {
      b.onClick();
      // Only auto-close if not the primary action button (let async handlers control flow)
      if (b.autoClose !== false) closeModal();
    };
  });
}

function closeModal() {
  document.getElementById('modal-root').innerHTML = '';
}
