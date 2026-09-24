"""
reporting.py — PDF report builder using ReportLab.

Report sections (PRD §5.7):
  1. Cover page
  2. Evidence integrity (hashes before/after, comparison result)
  3. Brand detection result
  4. Camera list and recordings table
  5. Gaps and unrecovered areas
  6. Log events (if any)
  7. Method and limitations (plain language)
  8. Section 63(4) certificate helper — Part A (custodian) + Part B (expert)
     WATERMARKED: "Draft — not legal advice" on every certificate page
  9. Audit log (paginated)

All wording uses "verified" and "strong evidence", never "absolute proof".
"""

from __future__ import annotations

import io
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.models import AuditEntry, Case, Evidence, LogEvent, Segment, SegmentStatus

# ── Colours ───────────────────────────────────────────────────────────────────
_C_DARK   = colors.HexColor("#1a1a2e")
_C_ACCENT = colors.HexColor("#0f3460")
_C_GREEN  = colors.HexColor("#2d6a4f")
_C_AMBER  = colors.HexColor("#b5451b")
_C_RED    = colors.HexColor("#c62828")
_C_GREY   = colors.HexColor("#f5f5f5")
_C_WHITE  = colors.white

_STATUS_COLOURS = {
    SegmentStatus.COMPLETE:  colors.HexColor("#2d6a4f"),
    SegmentStatus.PARTIAL:   colors.HexColor("#e6a817"),
    SegmentStatus.UNCERTAIN: colors.HexColor("#c62828"),
}

TOOL_VERSION = "v1.0.0-dev"
TOOL_NAME    = "SIH26150 DVR/NVR Forensic Tool"


# ── Helper: watermarked canvas callback ──────────────────────────────────────

def _make_watermark_canvas(watermark_text: str, page_numbers: set[int]):
    """
    Returns a canvas callback that draws a diagonal watermark on specified pages.
    """
    def _on_page(canvas, doc):
        pn = doc.page
        if pn in page_numbers:
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 22)
            canvas.setFillColor(colors.HexColor("#cc0000"))
            canvas.setFillAlpha(0.25)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, watermark_text)
            canvas.restoreState()
        _add_page_footer(canvas, doc)

    return _on_page


class _PageMarker(Flowable):
    """
    Zero-size flowable that records the page number it's drawn on into a
    shared set. Used to discover which pages the certificate section lands
    on during a throwaway first pass, so the real build only watermarks
    those pages instead of the whole report.
    """
    def __init__(self, page_set: set[int]) -> None:
        super().__init__()
        self.width = 0
        self.height = 0
        self._page_set = page_set

    def draw(self) -> None:
        self._page_set.add(self.canv.getPageNumber())


def _add_page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(
        2 * cm, 1 * cm,
        f"{TOOL_NAME}  |  {TOOL_VERSION}  |  Page {doc.page}",
    )
    canvas.restoreState()


# ── Style helpers ─────────────────────────────────────────────────────────────

def _styles():
    base = getSampleStyleSheet()
    styles = {
        "h1":    ParagraphStyle("h1",    fontSize=18, textColor=_C_DARK, spaceAfter=10, fontName="Helvetica-Bold"),
        "h2":    ParagraphStyle("h2",    fontSize=13, textColor=_C_ACCENT, spaceAfter=6, spaceBefore=10, fontName="Helvetica-Bold"),
        "h3":    ParagraphStyle("h3",    fontSize=11, textColor=_C_DARK, spaceAfter=4, spaceBefore=6, fontName="Helvetica-Bold"),
        "body":  ParagraphStyle("body",  fontSize=9,  leading=13, spaceAfter=4),
        "mono":  ParagraphStyle("mono",  fontSize=8,  fontName="Courier", leading=10, spaceAfter=2),
        "warn":  ParagraphStyle("warn",  fontSize=9,  textColor=_C_AMBER, leading=13),
        "cert":  ParagraphStyle("cert",  fontSize=9,  leading=14, spaceAfter=6),
        "small": ParagraphStyle("small", fontSize=7,  textColor=colors.grey, leading=10),
        "center":ParagraphStyle("center",fontSize=9,  alignment=TA_CENTER),
    }
    return styles


# ── Table styles ──────────────────────────────────────────────────────────────

_TBL_HDR = TableStyle([
    ("BACKGROUND",  (0, 0), (-1, 0),  _C_ACCENT),
    ("TEXTCOLOR",   (0, 0), (-1, 0),  _C_WHITE),
    ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
    ("FONTSIZE",    (0, 0), (-1, -1), 8),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_C_GREY, _C_WHITE]),
    ("GRID",        (0, 0), (-1, -1), 0.4, colors.lightgrey),
    ("TOPPADDING",  (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING",(0,0), (-1, -1), 3),
    ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ("RIGHTPADDING",(0, 0), (-1, -1), 4),
])


def _accuracy_section(results: list, S) -> list:
    """Report section for ground-truth comparisons; explicit 'not measured' when there are none."""
    out: list = [Paragraph("Accuracy Against Ground Truth", S["h2"])]
    if not results:
        out.append(Paragraph(
            "NOT MEASURED. No ground truth (a known-good video, a recording log, or the original pre-deletion "
            "disk image) was supplied for this case, so no recovery percentage is stated. The tool cannot know "
            "how much footage there should have been.",
            S["body"],
        ))
        out.append(Spacer(1, 0.3 * cm))
        return out
    out.append(Paragraph(
        "Each row was measured against ground truth the examiner supplied for that test. The figures describe that "
        "one segment on that one disk and deletion; they are not a general recovery rate.",
        S["small"],
    ))
    rows = [["Segment", "Frame recall", "Frame precision", "In order", "Byte-identical", "Byte recall (disk)", "Not measured"]]
    for r in results:
        f, b, pl = r.get("frames"), r.get("bytes"), r.get("placement")
        rows.append([
            (r.get("segment_id") or "")[:8],
            f"{f['frame_recall_pct']}%" if f and f.get("frame_recall_pct") is not None else "-",
            f"{f['frame_precision_pct']}%" if f and f.get("frame_precision_pct") is not None else "-",
            f"{f['in_order_pct']}%" if f and f.get("in_order_pct") is not None else "-",
            ("YES" if b["identical"] else "NO") if b else "-",
            f"{pl['byte_recall_pct']}%" if pl and pl.get("byte_recall_pct") is not None else "-",
            textwrap.shorten("; ".join(r.get("not_measured", [])) or "-", 40),
        ])
    out.append(Table(rows, colWidths=[2*cm, 2.2*cm, 2.4*cm, 1.7*cm, 2.3*cm, 2.6*cm, 3.8*cm], style=_TBL_HDR))
    for r in results:
        pl = r.get("placement")
        if pl:
            out.append(Paragraph("Reference for disk placement: " + pl["reference_source"] + ".", S["small"]))
            break
    out.append(Spacer(1, 0.3 * cm))
    return out


# ── Main builder ──────────────────────────────────────────────────────────────

def generate_report(
    output_path: Path,
    case: Case,
    evidence: Evidence,
    segments: list[Segment],
    log_events: list[LogEvent],
    audit_entries: list[AuditEntry],
    chain_ok: bool,
    correlated_events: Optional[list] = None,
    accuracy_results: Optional[list] = None,
) -> None:
    """
    Generate a PDF forensic report at *output_path*.
    Raises on any ReportLab error.

    *correlated_events* is an optional list of correlation.CorrelatedEvent (or
    objects exposing the same .to_dict()) describing segments whose time
    windows overlap across 2+ cameras — see backend/correlation.py. Purely
    a time-proximity clustering, not content analysis.

    *accuracy_results* is the list of stored ground-truth comparisons (backend/accuracy.py). When empty,
    the report states that recovery was NOT measured; it never invents a percentage.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    S = _styles()

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_reference = f"RPT-{case.case_number}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    def _build_elements(cert_pages: set[int]) -> list:
        """
        Build the flowables list. *cert_pages* is populated (as a side effect,
        during doc.build()) with the page numbers the certificate section
        lands on, via the _PageMarker flowables bracketing that section.
        Flowables carry per-build state, so this must be called fresh for
        each doc.build() call rather than reusing one list across builds.
        """
        elements = []

        # ── 1. Cover ──────────────────────────────────────────────────────────
        elements.append(Spacer(1, 2 * cm))
        elements.append(Paragraph(TOOL_NAME, S["h1"]))
        elements.append(Paragraph("Digital Forensic Evidence Report", S["h2"]))
        elements.append(HRFlowable(width="100%", thickness=1, color=_C_ACCENT))
        elements.append(Spacer(1, 0.5 * cm))

        cover_data = [
            ["Report reference", report_reference],
            ["Case number",  case.case_number],
            ["Examiner",     case.examiner],
            ["Report date",  generated_at],
            ["Tool version", f"{TOOL_NAME} {TOOL_VERSION}"],
            ["Case notes",   case.notes or "—"],
        ]
        elements.append(Table(cover_data, colWidths=[5 * cm, 12 * cm], style=_TBL_HDR))
        elements.append(Spacer(1, 0.4 * cm))


        elements.append(PageBreak())

        # ── 2. Evidence integrity ────────────────────────────────────────────
        elements.append(Paragraph("Evidence Integrity", S["h1"]))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=_C_ACCENT))

        ok_text   = "MATCH — strong evidence that the disk image was not modified by this tool."
        fail_text = "MISMATCH — hashes differ. The image may have been modified. Do not rely on this evidence."
        hash_ok   = (
            evidence.sha256_before is not None
            and evidence.sha256_after is not None
            and evidence.sha256_before == evidence.sha256_after
        )
        integrity_data = [
            ["Field",             "Value"],
            ["Source path",       evidence.path],
            ["File size",         f"{evidence.size_bytes:,} bytes" if evidence.size_bytes else "—"],
            ["SHA-256 (before)",  evidence.sha256_before or "—"],
            ["MD5 (before)",      evidence.md5_before or "—"],
            ["SHA-256 (after)",   evidence.sha256_after or "—"],
            ["Hash comparison",   ok_text if hash_ok else fail_text],
            ["Audit chain",       "INTACT" if chain_ok else "BROKEN — see audit log"],
        ]
        elements.append(Table(integrity_data, colWidths=[5 * cm, 12 * cm], style=_TBL_HDR))
        elements.append(Spacer(1, 0.4 * cm))

        # ── 3. Brand detection ───────────────────────────────────────────────
        elements.append(Paragraph("Brand Detection", S["h2"]))
        det_data = [
            ["Field",       "Value"],
            ["Brand",       evidence.brand or "Unknown"],
            ["Version",     evidence.brand_version or "—"],
            ["Confidence",  f"{evidence.confidence:.0%}" if evidence.confidence is not None else "—"],
        ]
        elements.append(Table(det_data, colWidths=[5 * cm, 12 * cm], style=_TBL_HDR))
        elements.append(Spacer(1, 0.4 * cm))

        # ── 4. Recordings table ──────────────────────────────────────────────
        elements.append(Paragraph("Recovered Recordings", S["h1"]))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=_C_ACCENT))

        if not segments:
            elements.append(Paragraph("No recordings found.", S["body"]))
        else:
            seg_rows = [["Camera", "Start", "End", "Frames", "Status", "SHA-256 (first 16)", "Notes"]]
            for seg in segments:
                seg_rows.append([
                    str(seg.camera),
                    seg.start_time.strftime("%Y-%m-%d %H:%M:%S") if seg.start_time else "—",
                    seg.end_time.strftime("%Y-%m-%d %H:%M:%S")   if seg.end_time   else "—",
                    str(seg.frame_count),
                    seg.status.value,
                    seg.sha256[:16] + "…" if seg.sha256 else "—",
                    textwrap.shorten(seg.notes or "", 60),
                ])
            seg_style = TableStyle(list(_TBL_HDR._cmds))
            for i, seg in enumerate(segments, start=1):
                c = _STATUS_COLOURS.get(seg.status, colors.grey)
                seg_style.add("BACKGROUND", (4, i), (4, i), c)
                seg_style.add("TEXTCOLOR",  (4, i), (4, i), _C_WHITE)
            elements.append(Table(seg_rows, colWidths=[1.5*cm, 3.5*cm, 3.5*cm, 1.5*cm, 2.5*cm, 3*cm, 3.5*cm], style=seg_style))

        elements.append(Spacer(1, 0.4 * cm))

        # ── 4b. Cross-camera event correlation ───────────────────────────────
        if correlated_events:
            elements.append(Paragraph("Cross-Camera Event Correlation", S["h2"]))
            elements.append(Paragraph(
                "Segments whose time windows overlap across 2 or more cameras, grouped purely by time "
                "proximity. This is NOT content analysis (no face/object recognition) and does not by "
                "itself establish that the underlying events are related — independent review is required.",
                S["small"],
            ))
            corr_rows = [["Start", "End", "Cameras", "Segments"]]
            for ce in correlated_events:
                d = ce.to_dict() if hasattr(ce, "to_dict") else ce
                start = d.get("start_time")
                end = d.get("end_time")
                corr_rows.append([
                    start[:19] if isinstance(start, str) else (start.strftime("%Y-%m-%d %H:%M:%S") if start else "—"),
                    end[:19] if isinstance(end, str) else (end.strftime("%Y-%m-%d %H:%M:%S") if end else "—"),
                    ", ".join(str(c) for c in d.get("cameras", [])),
                    str(len(d.get("segment_ids", []))),
                ])
            elements.append(Table(corr_rows, colWidths=[4*cm, 4*cm, 4.5*cm, 4.5*cm], style=_TBL_HDR))
            elements.append(Spacer(1, 0.4 * cm))

        # ── 4c. Accuracy against ground truth ────────────────────────────────
        elements.extend(_accuracy_section(accuracy_results or [], S))

        # ── 5. Method and limitations ────────────────────────────────────────
        elements.append(PageBreak())
        elements.append(Paragraph("Method and Limitations", S["h1"]))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=_C_ACCENT))
        method_text = """
This tool reads a raw disk image in read-only mode. It computes SHA-256 and MD5 hashes
of the evidence in a single pass to prevent double-reading. Brand detection checks for
known file-system signatures. Video is recovered by carving: scanning for known frame
markers and validating each candidate against a documented checklist.

Deleted recordings are recovered because deleting normally removes only the index entry,
not the frame data itself. Video that has been overwritten by new recordings cannot be
recovered.

Labels used: COMPLETE (all checks pass, hash verified), PARTIAL (frames found with gaps
or sequence issues), UNCERTAIN (some checks failed or carving is experimental).

No tool can recover overwritten data. Recovery rates depend on how much of the disk has
been overwritten since deletion. Results labelled UNCERTAIN should not be relied upon
without independent verification.

This tool is a prototype and has not been validated by an accredited forensic laboratory.
Recovery accuracy must be established on real recorders before figures are relied upon.
        """.strip()
        for para in method_text.split("\n\n"):
            elements.append(Paragraph(para.replace("\n", " "), S["body"]))
            elements.append(Spacer(1, 0.2 * cm))

        # ── 6. Log events ────────────────────────────────────────────────────
        if log_events:
            elements.append(Paragraph("Extracted Log Events", S["h2"]))
            log_rows = [["Time", "Type", "Detail", "Disk offset"]]
            for ev in log_events:
                log_rows.append([
                    ev.event_timestamp.strftime("%Y-%m-%d %H:%M:%S") if ev.event_timestamp else "—",
                    ev.event_type,
                    textwrap.shorten(ev.detail, 60),
                    str(ev.source_offset) if ev.source_offset is not None else "—",
                ])
            elements.append(Table(log_rows, colWidths=[4*cm, 3*cm, 8*cm, 3*cm], style=_TBL_HDR))
            elements.append(Spacer(1, 0.4 * cm))

        # ── 7. Section 63(4) certificate helper ──────────────────────────────
        # Bracketed by _PageMarker flowables so the real build knows exactly
        # which pages this section lands on and watermarks only those pages.
        elements.append(PageBreak())
        elements.append(_PageMarker(cert_pages))

        elements.append(Paragraph(
            "Section 63(4) Certificate Helper — DRAFT, NOT LEGAL ADVICE",
            S["h1"],
        ))
        elements.append(Paragraph(
            "This section pre-fills technical fields for the Section 63(4) certificate under the "
            "Bharatiya Sakshya Adhiniyam, 2023. Signature blocks are left empty. A qualified "
            "legal expert must review and sign. See Pune Bar Association v. Union of India "
            "(Supreme Court, 22 May 2026).",
            S["warn"],
        ))
        elements.append(Spacer(1, 0.3 * cm))

        elements.append(Paragraph("Part A — Custodian Certificate (technical fields only)", S["h2"]))
        part_a_data = [
            ["Field",                        "Pre-filled value"],
            ["Report reference",             report_reference],
            ["Device description",           f"DVR/NVR disk image, brand: {evidence.brand or 'Unknown'}"],
            ["Hash algorithm",               "SHA-256"],
            ["Hash value of the record",     evidence.sha256_before or "—"],
            ["Tool used",                    f"{TOOL_NAME} {TOOL_VERSION}"],
            ["Image acquired",               evidence.created_at],
            ["Custodian name",               "____________________________ (to be signed)"],
            ["Designation",                  "____________________________ (to be signed)"],
            ["Date",                         "____________________________ (to be signed)"],
        ]
        elements.append(Table(part_a_data, colWidths=[7*cm, 10*cm], style=_TBL_HDR))
        elements.append(Spacer(1, 0.3 * cm))

        elements.append(Paragraph("Part B — Expert Certificate (technical fields only)", S["h2"]))
        part_b_data = [
            ["Field",                        "Pre-filled value"],
            ["Method",                       "Read-only mmap acquisition; SHA-256/MD5 single-pass hash; "
                                             "frame carving by marker search; adaptive gap segmentation."],
            ["Tool validation",              f"Known-answer tests (KAT-01 to KAT-08) described in project documentation."],
            ["Hash check result",            "MATCH" if hash_ok else "MISMATCH"],
            ["Recovery label",               ", ".join(sorted({s.status.value for s in segments})) or "—"],
            ["Expert name",                  "____________________________ (to be signed)"],
            ["Qualifications",               "____________________________ (to be signed)"],
            ["Date",                         "____________________________ (to be signed)"],
        ]
        elements.append(Table(part_b_data, colWidths=[7*cm, 10*cm], style=_TBL_HDR))
        elements.append(Spacer(1, 0.3 * cm))
        elements.append(Paragraph(
            "Draft for review — not legal advice. Copy the exact field layout from the official "
            "Schedule of the Bharatiya Sakshya Adhiniyam, 2023 before use in court.",
            S["small"],
        ))
        # Marks the last page the certificate section's content actually lands on.
        elements.append(_PageMarker(cert_pages))

        # ── 8. Audit log ──────────────────────────────────────────────────────
        elements.append(PageBreak())
        elements.append(Paragraph("Audit Log", S["h1"]))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=_C_ACCENT))
        elements.append(Paragraph(
            "Every action taken by this tool is recorded below with a hash-chained entry. "
            "Modifying any entry breaks all subsequent hashes, making tampering visible.",
            S["body"],
        ))
        elements.append(Spacer(1, 0.3 * cm))

        if audit_entries:
            audit_rows = [["Time", "Action", "Hash (first 16)"]]
            for entry in audit_entries:
                audit_rows.append([
                    entry.created_at[:19],
                    textwrap.shorten(f"{entry.action}: {entry.details}", 70),
                    entry.entry_hash[:16] + "…",
                ])
            elements.append(Table(audit_rows, colWidths=[4.5*cm, 10*cm, 3.5*cm], style=_TBL_HDR))
        else:
            elements.append(Paragraph("No audit entries recorded.", S["body"]))

        return elements

    def _doc(target) -> SimpleDocTemplate:
        return SimpleDocTemplate(
            target,
            pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2*cm,  bottomMargin=2*cm,
            title=f"Forensic Report — Case {case.case_number}",
            author=case.examiner,
            subject="DVR/NVR Digital Forensic Report",
        )

    # ── Pass 1 (throwaway): discover which page numbers the certificate
    # section lands on, so pass 2 only watermarks those pages instead of
    # stamping "DRAFT" across the whole report (cover, hash table, audit log).
    cert_pages: set[int] = set()
    _doc(io.BytesIO()).build(
        _build_elements(cert_pages),
        onFirstPage=_add_page_footer,
        onLaterPages=_add_page_footer,
    )
    watermark_pages = set(range(min(cert_pages), max(cert_pages) + 1)) if cert_pages else set()

    # ── Pass 2 (real): rebuild fresh flowables (ReportLab flowables carry
    # per-build layout state and can't be reused across doc.build() calls)
    # and write the final PDF with the watermark scoped to the cert pages.
    doc = _doc(str(output_path))
    doc.build(
        _build_elements(set()),
        onFirstPage=_make_watermark_canvas("DRAFT — NOT LEGAL ADVICE", watermark_pages),
        onLaterPages=_make_watermark_canvas("DRAFT — NOT LEGAL ADVICE", watermark_pages),
    )
