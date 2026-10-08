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
  
  // Try to find current logged-in username to pre-fill investigator
  const currentHeaderUser = document.getElementById('header-username')?.textContent?.replace(/^[\u{1F464}\s]+|[▼\s]+$/gu, '') || '';

  root.innerHTML = `
    <div class="page-header">
      <div class="page-title">Register New Case</div>
      <div class="page-subtitle">Enter chain-of-custody and legal reference metadata before loading evidence disk images.</div>
    </div>

    <div class="card max-w-card">
      <form id="new-case-form" novalidate>
        <!-- Primary Identification -->
        <div class="form-row-2col">
          <div class="form-group">
            <label for="input-case-number">Case Number / Reference ID <span class="text-error">*</span></label>
            <input type="text" id="input-case-number" class="form-control"
              placeholder="e.g. FIR-2026-892" required autocomplete="off" maxlength="64" />
            <div id="err-case-number" class="field-error hidden"></div>
          </div>
          <div class="form-group">
            <label for="input-case-title">Case Title / Description</label>
            <input type="text" id="input-case-title" class="form-control"
              placeholder="e.g. Commercial Burglary - Sector 4 CCTV" maxlength="255" />
          </div>
        </div>

        <!-- Investigator & Agency -->
        <div class="form-row-2col">
          <div class="form-group">
            <label for="input-investigator">Lead Examiner / Investigator <span class="text-error">*</span></label>
            <input type="text" id="input-investigator" class="form-control"
              placeholder="e.g. Officer A. Sharma" required maxlength="128" value="${escapeHtml(currentHeaderUser)}" />
            <div id="err-investigator" class="field-error hidden"></div>
          </div>
          <div class="form-group">
            <label for="input-agency">Agency / Police Unit <span class="text-dim text-xs">(optional)</span></label>
            <input type="text" id="input-agency" class="form-control"
              placeholder="e.g. Cyber Crime Division, State Police" maxlength="255" />
            <div id="err-agency" class="field-error hidden"></div>
          </div>
        </div>

        <!-- FIR & Priority -->
        <div class="form-row-2col">
          <div class="form-group">
            <label for="input-fir-number">FIR / Crime Reference No.</label>
            <input type="text" id="input-fir-number" class="form-control"
              placeholder="e.g. 142/2026 PS Connaught Place" maxlength="128" />
          </div>
          <div class="form-group">
            <label for="input-priority">Investigation Priority</label>
            <select id="input-priority" class="form-control">
              <option value="LOW">Low</option>
              <option value="MEDIUM" selected>Medium</option>
              <option value="HIGH">High</option>
              <option value="CRITICAL">Critical (Urgent / Active Crime)</option>
            </select>
          </div>
        </div>

        <!-- Seizure Details -->
        <div class="form-row-2col">
          <div class="form-group">
            <label for="input-seizure-officer">Seizure Officer (as on Panchnama)</label>
            <input type="text" id="input-seizure-officer" class="form-control"
              placeholder="e.g. Sub-Inspector V. Rao" maxlength="128" />
          </div>
          <div class="form-group">
            <label for="input-incident-date">Incident / Seizure Date</label>
            <input type="date" id="input-incident-date" class="form-control" />
          </div>
        </div>

        <div class="form-row-2col">
          <div class="form-group">
            <label for="input-seizure-location">Seizure Location / Scene</label>
            <input type="text" id="input-seizure-location" class="form-control"
              placeholder="e.g. Building A-12, Main Server Room" maxlength="255" />
          </div>
          <div class="form-group">
            <label for="input-target-device">Target DVR / NVR Hardware</label>
            <input type="text" id="input-target-device" class="form-control"
              placeholder="e.g. Hikvision DS-7208HQHI / Dahua DH-XVR5108" maxlength="128" />
          </div>
        </div>

        <div class="form-group">
          <label for="input-notes">Forensic Examination Notes &amp; Scope</label>
          <textarea id="input-notes" class="form-control" rows="3"
            placeholder="Optional: specific cameras of interest, time ranges required, write-blocker details…"></textarea>
        </div>

        <!-- inline error — hidden by default -->
        <div id="case-error" class="error-inline hidden mb-12">
          <span>${icon('alert')}</span>
          <span id="case-error-msg"></span>
        </div>

        <div class="d-flex justify-end gap-md mt-24">
          <button type="button" class="btn btn-secondary" ${navAttrs('dashboard')}>${icon('arrow-left')} Cancel</button>
          <button type="submit" id="btn-submit-case" class="btn btn-primary">Create case &amp; continue ${icon('arrow-right')}</button>
        </div>
      </form>
    </div>
  `;

  // If header username wasn't loaded yet, try async fetch
  if (!currentHeaderUser) {
    API.authStatus().then(st => {
      const invInput = document.getElementById('input-investigator');
      if (invInput && !invInput.value && st && st.username) {
        invInput.value = st.username;
      }
    }).catch(() => {});
  }

  const form      = document.getElementById('new-case-form');
  const submitBtn = document.getElementById('btn-submit-case');
  const errEl     = document.getElementById('case-error');
  const errMsg    = document.getElementById('case-error-msg');

  /** Show a per-field error message. */
  function _fieldError(id, msg) {
    const el = document.getElementById(id);
    if (el) { el.textContent = msg; el.classList.remove('hidden'); }
  }
  /** Clear a per-field error. */
  function _fieldClear(id) {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.classList.add('hidden'); }
  }
  /** Clear all per-field errors. */
  function _clearAll() {
    ['err-case-number', 'err-investigator', 'err-agency'].forEach(_fieldClear);
    errEl.classList.add('hidden');
  }

  form.onsubmit = async (e) => {
    e.preventDefault();
    _clearAll();

    const caseNumber      = document.getElementById('input-case-number').value.trim();
    const caseTitle       = document.getElementById('input-case-title').value.trim();
    const investigator    = document.getElementById('input-investigator').value.trim();
    const agency          = document.getElementById('input-agency').value.trim();
    const firNumber       = document.getElementById('input-fir-number').value.trim();
    const priority        = document.getElementById('input-priority').value;
    const seizureOfficer  = document.getElementById('input-seizure-officer').value.trim();
    const incidentDate    = document.getElementById('input-incident-date').value;
    const seizureLocation = document.getElementById('input-seizure-location').value.trim();
    const targetDevice    = document.getElementById('input-target-device').value.trim();
    const notes           = document.getElementById('input-notes').value.trim();

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

    if (hasError) return;

    // Disable button + show spinner
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="btn-spinner"></span> Creating…';

    const data = {
      case_number:      caseNumber,
      case_title:       caseTitle || null,
      examiner:         investigator,
      agency:           agency || null,
      fir_number:       firNumber || null,
      incident_date:    incidentDate || null,
      seizure_officer:  seizureOfficer || null,
      seizure_location: seizureLocation || null,
      priority:         priority || 'MEDIUM',
      status:           'ACTIVE',
      target_device:    targetDevice || null,
      notes:            notes || null,
    };

    try {
      const created = await API.createCase(data);
      if (typeof Toast !== 'undefined' && Toast.success) {
        Toast.success(`Case created successfully: ${caseNumber}`);
      }
      navigateTo('case-detail', { caseId: created.case_id });
    } catch (err) {
      // Show verbatim server error (includes HTTP 409 duplicate message)
      errMsg.textContent = err.message;
      errEl.classList.remove('hidden');
      if (typeof Toast !== 'undefined' && Toast.error) {
        Toast.error(err.message || 'Failed to create case');
      }
      submitBtn.disabled = false;
      submitBtn.innerHTML = 'Create case &amp; continue ' + icon('arrow-right');
    }
  };
}
