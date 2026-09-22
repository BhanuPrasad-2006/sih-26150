/**
 * TimelineScreen.js — Shared UTC timeline for every recovered segment in a case.
 *
 * The API provides timestamp-sorted camera lanes and per-lane uncovered gaps.
 * This screen only presents that data; it never changes recovered segments.
 */

function timelineFormatUtc(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown time';
  return date.toISOString().replace('T', ' ').replace('.000Z', ' UTC');
}

function timelineDuration(seconds) {
  const wholeSeconds = Math.max(0, Math.round(seconds || 0));
  const hours = Math.floor(wholeSeconds / 3600);
  const minutes = Math.floor((wholeSeconds % 3600) / 60);
  const remainder = wholeSeconds % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${remainder}s`;
  return `${remainder}s`;
}

function timelineEscapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[character]));
}

function timelineStatusClass(status) {
  switch ((status || '').toUpperCase()) {
    case 'COMPLETE': return 'timeline-segment--complete';
    case 'PARTIAL': return 'timeline-segment--partial';
    case 'UNCERTAIN': return 'timeline-segment--uncertain';
    default: return 'timeline-segment--unknown';
  }
}

function timelinePercent(value, rangeStart, rangeMs) {
  const point = new Date(value).getTime();
  if (rangeMs <= 0 || Number.isNaN(point)) return 0;
  return Math.max(0, Math.min(100, ((point - rangeStart) / rangeMs) * 100));
}

function timelineTicks(startTime, endTime) {
  const start = new Date(startTime).getTime();
  const end = new Date(endTime).getTime();
  const range = Math.max(0, end - start);
  return Array.from({ length: 5 }, (_, index) => {
    const offset = range * (index / 4);
    return {
      left: index * 25,
      label: timelineFormatUtc(new Date(start + offset).toISOString())
    };
  });
}

function renderTimelineSegment(segment, rangeStart, rangeMs) {
  const left = timelinePercent(segment.start_time, rangeStart, rangeMs);
  const end = timelinePercent(segment.end_time, rangeStart, rangeMs);
  const width = Math.min(100 - left, Math.max(1.25, end - left));
  const status = (segment.status || 'UNCERTAIN').toUpperCase();
  const title = [
    `Camera ${segment.camera}`,
    `${timelineFormatUtc(segment.start_time)} — ${timelineFormatUtc(segment.end_time)}`,
    `${segment.frame_count || 0} frames · ${status}`,
    segment.notes || ''
  ].filter(Boolean).join('\n');

  return `
    <div class="timeline-segment ${timelineStatusClass(status)}"
      style="left:${left}%; width:${width}%;"
      title="${timelineEscapeHtml(title)}">
      <span class="timeline-segment-label">${status}</span>
    </div>`;
}

function renderTimelineGap(gap, rangeStart, rangeMs) {
  const left = timelinePercent(gap.start_time, rangeStart, rangeMs);
  const end = timelinePercent(gap.end_time, rangeStart, rangeMs);
  const width = Math.min(100 - left, Math.max(0.6, end - left));
  const title = `Gap: ${timelineFormatUtc(gap.start_time)} — ${timelineFormatUtc(gap.end_time)} (${timelineDuration(gap.duration_seconds)})`;
  const label = gap.duration_seconds >= 60 ? timelineDuration(gap.duration_seconds) : '';

  return `
    <div class="timeline-gap" style="left:${left}%; width:${width}%;" title="${timelineEscapeHtml(title)}">
      ${label ? `<span class="timeline-gap-label">Gap ${label}</span>` : ''}
    </div>`;
}

function renderTimelineLane(lane, rangeStart, rangeMs) {
  return `
    <section class="timeline-lane" aria-label="Camera ${lane.camera} timeline">
      <div class="timeline-lane-label">
        <strong>Camera ${lane.camera}</strong>
        <span>${lane.segments.length} segment${lane.segments.length === 1 ? '' : 's'}</span>
      </div>
      <div class="timeline-lane-track">
        ${lane.gaps.map(gap => renderTimelineGap(gap, rangeStart, rangeMs)).join('')}
        ${lane.segments.map(segment => renderTimelineSegment(segment, rangeStart, rangeMs)).join('')}
      </div>
    </section>`;
}

async function renderTimelineScreen(params) {
  const { caseId } = params;
  const root = document.getElementById('content-root');

  root.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Building cross-camera timeline…</p>
    </div>`;

  let timeline;
  try {
    timeline = await API.getTimeline(caseId);
  } catch (err) {
    root.innerHTML = `
      <div class="page-header"><div class="page-title">Cross-Camera Timeline</div></div>
      <div class="error-banner">
        <div class="error-banner-icon">⚠️</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Failed to load timeline</div>
          <div class="error-banner-msg">${err.message}</div>
        </div>
      </div>`;
    return;
  }

  const lanes = timeline.lanes || [];
  const segmentCount = lanes.reduce((count, lane) => count + lane.segments.length, 0);
  const gapCount = lanes.reduce((count, lane) => count + lane.gaps.length, 0);

  if (!timeline.start_time || !timeline.end_time || segmentCount === 0) {
    root.innerHTML = `
      <div class="page-header">
        <div class="page-title">Cross-Camera Timeline</div>
        <div class="page-subtitle">A shared UTC view of recovered footage across every camera and evidence image in this case.</div>
      </div>
      <div class="card empty-state">
        <div class="empty-state-icon">🕒</div>
        <div class="empty-state-title">No timestamped segments are available</div>
        <div class="empty-state-subtitle">Run a scan to recover timestamped segments, then return here to compare cameras on one timeline.</div>
        <button class="btn btn-primary" onclick="navigateTo('case-detail', { caseId: '${caseId}' })">Return to Case Overview</button>
      </div>`;
    return;
  }

  const rangeStart = new Date(timeline.start_time).getTime();
  const rangeMs = Math.max(0, new Date(timeline.end_time).getTime() - rangeStart);
  const ticks = timelineTicks(timeline.start_time, timeline.end_time);

  root.innerHTML = `
    <div class="page-header">
      <div class="page-title">Cross-Camera Timeline</div>
      <div class="page-subtitle">All recovered, timestamped segments are aligned in UTC. Striped intervals indicate periods without recovered footage on that camera.</div>
    </div>

    <div class="timeline-summary-grid">
      <div class="timeline-summary-card"><span>Time Range</span><strong>${timelineFormatUtc(timeline.start_time)} — ${timelineFormatUtc(timeline.end_time)}</strong></div>
      <div class="timeline-summary-card"><span>Recovered Segments</span><strong>${segmentCount} across ${lanes.length} camera${lanes.length === 1 ? '' : 's'}</strong></div>
      <div class="timeline-summary-card"><span>Detected Gaps</span><strong>${gapCount} interval${gapCount === 1 ? '' : 's'} · ${timelineDuration(timeline.duration_seconds)}</strong></div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>Shared Timeline</span>
        <div class="status-legend" aria-label="Segment status legend">
          <span class="status-legend-item">Segments:</span>
          <span class="badge badge-complete">COMPLETE</span>
          <span class="badge badge-partial">PARTIAL</span>
          <span class="badge badge-uncertain">UNCERTAIN</span>
          <span class="timeline-gap-key"><i></i> Gap</span>
        </div>
      </div>
      <div class="timeline-scroll">
        <div class="timeline-content">
          <div class="timeline-axis">
            <div class="timeline-axis-label">UTC</div>
            <div class="timeline-axis-track">
              ${ticks.map(tick => `<span class="timeline-tick" style="left:${tick.left}%">${tick.label}</span>`).join('')}
            </div>
          </div>
          ${lanes.map(lane => renderTimelineLane(lane, rangeStart, rangeMs)).join('')}
        </div>
      </div>
    </div>

    ${timeline.unplaced_segments?.length ? `
      <div class="notice-card">
        <h3>⚠️ ${timeline.unplaced_segments.length} segment${timeline.unplaced_segments.length === 1 ? '' : 's'} not positioned</h3>
        <p>These recovered segments lack a valid start/end timestamp and are therefore excluded from the visual timeline. Review them in Recordings before relying on their chronology.</p>
      </div>` : ''}
  `;
}
