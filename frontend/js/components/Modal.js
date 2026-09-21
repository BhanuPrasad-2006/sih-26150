/**
 * Modal dialog helper.
 */
function showModal(title, bodyHtml, buttons = []) {
  const root = document.getElementById('modal-root');
  root.innerHTML = `
    <div class="modal-overlay">
      <div class="modal-content">
        <div class="card-title">
          <span>${title}</span>
          <button id="modal-close-btn" style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:18px;">✕</button>
        </div>
        <div class="modal-body" style="margin-bottom: 20px;">
          ${bodyHtml}
        </div>
        <div class="modal-footer" style="display:flex; justify-content:flex-end; gap:10px;">
          ${buttons.map((b, i) => `<button id="modal-btn-${i}" class="btn ${b.class || 'btn-secondary'}">${b.label}</button>`).join('')}
        </div>
      </div>
    </div>
  `;

  document.getElementById('modal-close-btn').onclick = closeModal;
  buttons.forEach((b, i) => {
    document.getElementById(`modal-btn-${i}`).onclick = () => {
      b.onClick();
      closeModal();
    };
  });
}

function closeModal() {
  document.getElementById('modal-root').innerHTML = '';
}
