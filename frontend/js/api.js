/**
 * api.js — API client for communication with FastAPI backend.
 *
 * Every fetch call checks res.ok and throws a descriptive Error that includes
 * the HTTP status code, the URL, and the server's error message so the UI can
 * show exactly which request failed and why.
 */

const API = {
  /** Throw a descriptive error when the server returns a non-2xx status. */
  async _checkOk(res, url) {
    if (res.ok) return res;
    let serverMsg = '';
    try {
      const body = await res.json();
      serverMsg = body.detail || body.message || JSON.stringify(body);
    } catch (_) {
      try { serverMsg = await res.text(); } catch (_) { serverMsg = '(no body)'; }
    }
    throw new Error(`HTTP ${res.status} from ${url} — ${serverMsg}`);
  },

  async listCases() {
    const url = '/api/cases';
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  async getCase(id) {
    const url = `/api/cases/${id}`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  async createCase(data) {
    const url = '/api/cases';
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        case_number: data.case_number,
        examiner: data.examiner || data.investigator_name,
        notes: data.notes
      })
    });
    await this._checkOk(res, url);
    return res.json();
  },

  async addEvidence(caseId, filePath, label) {
    const url = `/api/cases/${caseId}/evidence`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath, label })
    });
    await this._checkOk(res, url);
    return res.json();
  },

  async startScan(caseId) {
    const url = `/api/cases/${caseId}/scan`;
    const res = await fetch(url, { method: 'POST' });
    await this._checkOk(res, url);
    return res.json();
  },

  listenScanProgress(caseId, onProgress, onComplete, onError) {
    const source = new EventSource(`/api/cases/${caseId}/status`);
    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'ping') return;
      if (data.type === 'done') {
        source.close();
        onComplete(data);
        return;
      }
      onProgress(data);
      if (data.phase === 'DONE') {
        source.close();
        onComplete(data);
      } else if (data.phase === 'ERROR') {
        source.close();
        onError(data.message);
      }
    };
    source.onerror = (err) => {
      source.close();
      onError('Connection to scan stream failed');
    };
  },

  async getSegments(caseId) {
    const url = `/api/cases/${caseId}/segments`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  async exportSegment(caseId, segmentId) {
    const url = `/api/cases/${caseId}/export/${segmentId}`;
    const res = await fetch(url, { method: 'POST' });
    await this._checkOk(res, url);
    return res.json();
  },

  async verifyEvidenceIntegrity(caseId) {
    const url = `/api/cases/${caseId}/verify`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  async generateReport(caseId) {
    const url = `/api/cases/${caseId}/report`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.blob();
  },

  async getAuditLog(caseId) {
    const url = `/api/cases/${caseId}/audit`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  }
};
