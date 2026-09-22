/**
 * NewCaseScreen.js — Register new forensic case.
 *
 * Client-side validation rules (mirroring the Pydantic validators on the backend):
 *   case_number : 1–64 chars, only [A-Za-z0-9_\-/] — same regex as server.
 *   examiner    : 2–128 chars, required.
 *   agency      : required (stored in notes alongside free-text notes).
 *
 * On duplicate case number the server returns HTTP 409 and the message is shown inline.
 */

const _CASE_NUMBER_RE = /^[\w\-/]{1,64}$/;

function renderNewCaseScreen() {
  const root = document.getElementById('content-root');
  root.innerHTML = `
    <div class="page-header">
      <div class="page-title">Register New Case</div>
      <div class="page-subtitle">Enter chain-of-custody metadata before loading evidence disk images.</div>
    </div>

    <div class="card" style="max-width: 660px;">
      <form id="new-case-form" novalidate>
        <div class="form-group">
          <label for="input-case-number">Case Number / Reference ID <span style="color:var(--status-error);">*</span></label>
          <input type="text" id="input-case-number" class="form-control"
            placeholder="e.g. FIR-2026-892" required autocomplete="off" maxlength="64" />
          <div id="err-case-number" class="field-error" style="display:none;"></div>
        </div>
        <div class="form-group">
          <label for="input-investigator">Investigator Name <span style="color:var(--status-error);">*</span></label>
          <input type="text" id="input-investigator" class="form-control"
            placeholder="e.g. Officer A. Sharma" required maxlength="128" />
          <div id="err-investigator" class="field-error" style="display:none;"></div>
        </div>
        <div class="form-group">
          <label for="input-agency">Agency / Organization <span style="color:var(--status-error);">*</span></label>
          <input type="text" id="input-agency" class="form-control"
            placeholder="e.g. Cyber Crime Unit, State Police" required />
          <div id="err-agency" class="field-error" style="display:none;"></div>
        </div>
        <div class="form-group">
          <label for="input-notes">Notes / Case Summary</label>
          <textarea id="input-notes" class="form-control" rows="4"
            placeholder="Optional: seizure location, recorder model, special handling notes…"></textarea>
        </div>

        <!-- inline error — hidden by default -->
        <div id="case-error" style="display:none;" class="error-inline">
          <span>⚠️</span>
          <span id="case-error-msg"></span>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px;">
          <button type="button" class="btn btn-secondary" onclick="navigateTo('dashboard')">← Cancel</button>
          <button type="submit" id="btn-submit-case" class="btn btn-primary">Create Case &amp; Add Evidence ➔</button>
        </div>
      </form>
    </div>
  `;

  const form      = document.getElementById('new-case-form');
  const submitBtn = document.getElementById('btn-submit-case');
  const errEl     = document.getElementById('case-error');
  const errMsg    = document.getElementById('case-error-msg');

  /** Show a per-field error message. */
  function _fieldError(id, msg) {
    const el = document.getElementById(id);
    if (el) { el.textContent = msg; el.style.display = 'block'; }
  }
  /** Clear a per-field error. */
  function _fieldClear(id) {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.style.display = 'none'; }
  }
  /** Clear all per-field errors. */
  function _clearAll() {
    ['err-case-number', 'err-investigator', 'err-agency'].forEach(_fieldClear);
    errEl.style.display = 'none';
  }

  form.onsubmit = async (e) => {
    e.preventDefault();
    _clearAll();

    const caseNumber   = document.getElementById('input-case-number').value.trim();
    const investigator = document.getElementById('input-investigator').value.trim();
    const agency       = document.getElementById('input-agency').value.trim();
    const notes        = document.getElementById('input-notes').value.trim();

    let hasError = false;

    // ── Case number validation ──────────────────────────────────────────────
    if (!caseNumber) {
      _fieldError('err-case-number', 'Case number is required.');
      hasError = true;
    } else if (!_CASE_NUMBER_RE.test(caseNumber)) {
      _fieldError(
        'err-case-number',
        'Case number must be 1–64 characters and may only contain letters, digits, dashes (-), slashes (/), and underscores (_).'
      );
      hasError = true;
    }

    // ── Examiner validation ─────────────────────────────────────────────────
    if (!investigator) {
      _fieldError('err-investigator', 'Investigator name is required.');
      hasError = true;
    } else if (investigator.length < 2) {
      _fieldError('err-investigator', 'Investigator name must be at least 2 characters.');
      hasError = true;
    } else if (investigator.length > 128) {
      _fieldError('err-investigator', 'Investigator name must be 128 characters or fewer.');
      hasError = true;
    }

    // ── Agency validation ───────────────────────────────────────────────────
    if (!agency) {
      _fieldError('err-agency', 'Agency / Organization is required.');
      hasError = true;
    }

    if (hasError) return;

    // Disable button + show spinner
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="btn-spinner"></span> Creating…';

    // Combine agency and notes into the notes field
    const combinedNotes = agency + (notes ? `\n\n${notes}` : '');
    const data = {
      case_number: caseNumber,
      examiner:    investigator,
      notes:       combinedNotes,
    };

    try {
      const created = await API.createCase(data);
      navigateTo('case-detail', { caseId: created.case_id });
    } catch (err) {
      // Show verbatim server error (includes HTTP 409 duplicate message)
      errMsg.textContent = err.message;
      errEl.style.display = 'flex';
      submitBtn.disabled = false;
      submitBtn.innerHTML = 'Create Case &amp; Add Evidence ➔';
    }
  };
}
