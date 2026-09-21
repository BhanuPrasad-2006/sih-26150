/**
 * NewCaseScreen.js — Register new forensic case.
 * Agency field is blank by default (no pre-filled organisation name).
 * On duplicate case number the server returns HTTP 409 and the message is shown.
 */
function renderNewCaseScreen() {
  const root = document.getElementById('content-root');
  root.innerHTML = `
    <div style="margin-bottom: 24px;">
      <h2 style="font-size: 24px; font-weight: 700;">Register New Case</h2>
      <p style="color: var(--text-muted); font-size: 14px;">Enter chain of custody metadata before loading evidence disk images.</p>
    </div>

    <div class="card" style="max-width: 650px;">
      <form id="new-case-form">
        <div class="form-group">
          <label>Case Number / Reference ID *</label>
          <input type="text" id="input-case-number" class="form-control" placeholder="e.g. FIR-2026-892" required />
        </div>
        <div class="form-group">
          <label>Investigator Name *</label>
          <input type="text" id="input-investigator" class="form-control" placeholder="e.g. Officer A. Sharma" required />
        </div>
        <div class="form-group">
          <label>Agency / Organization *</label>
          <input type="text" id="input-agency" class="form-control" placeholder="e.g. Cyber Crime Unit, State Police" required />
        </div>
        <div class="form-group">
          <label>Notes / Case Summary</label>
          <textarea id="input-notes" class="form-control" rows="4" placeholder="Optional notes regarding seizure location, recorder model, etc."></textarea>
        </div>
        <div id="case-error" style="display:none; color:var(--accent-rose); font-size:13px; margin-bottom:12px;"></div>
        <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px;">
          <button type="button" class="btn btn-secondary" onclick="navigateTo('dashboard')">Cancel</button>
          <button type="submit" class="btn btn-primary">Create Case &amp; Add Evidence ➔</button>
        </div>
      </form>
    </div>
  `;

  document.getElementById('new-case-form').onsubmit = async (e) => {
    e.preventDefault();
    const errEl = document.getElementById('case-error');
    errEl.style.display = 'none';

    const data = {
      case_number: document.getElementById('input-case-number').value.trim(),
      examiner: document.getElementById('input-investigator').value.trim(),
      notes: document.getElementById('input-notes').value.trim()
    };
    try {
      const created = await API.createCase(data);
      navigateTo('case-detail', { caseId: created.case_id });
    } catch (err) {
      // Show inline error (includes HTTP 409 duplicate message from server)
      errEl.textContent = err.message;
      errEl.style.display = 'block';
    }
  };

}
