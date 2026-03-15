"""
Export service for generating PDF and CSV reports from validation results.
"""

import csv
import io
import zipfile
from datetime import datetime

import structlog
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = structlog.get_logger(__name__)

# Status colors for PDF
_STATUS_COLORS = {
    "pass": colors.HexColor("#4caf50"),
    "fail": colors.HexColor("#f44336"),
    "warn": colors.HexColor("#ff9800"),
    "info": colors.HexColor("#2196f3"),
    "error": colors.HexColor("#f44336"),
}


def generate_pdf(report) -> bytes:
    """Generate a PDF report from a completed ReportJob."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=12)
    heading_style = ParagraphStyle("SectionHeading", parent=styles["Heading2"], fontSize=14, spaceAfter=8, spaceBefore=16)
    normal_style = styles["Normal"]

    elements: list = []
    result = report.result or {}
    summary = result.get("summary", {})

    # Title
    elements.append(Paragraph(f"Post-Deployment Validation Report", title_style))
    elements.append(Paragraph(f"Site: {report.site_name}", normal_style))
    elements.append(Paragraph(f"Generated: {report.completed_at or report.created_at}", normal_style))
    elements.append(Spacer(1, 0.5 * cm))

    # Summary
    elements.append(Paragraph("Summary", heading_style))
    summary_data = [
        ["Pass", "Fail", "Warning", "Info"],
        [str(summary.get("pass", 0)), str(summary.get("fail", 0)), str(summary.get("warn", 0)), str(summary.get("info", 0))],
    ]
    summary_table = Table(summary_data, colWidths=[4 * cm] * 4)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 1), (0, 1), _STATUS_COLORS["pass"]),
        ("BACKGROUND", (1, 1), (1, 1), _STATUS_COLORS["fail"]),
        ("BACKGROUND", (2, 1), (2, 1), _STATUS_COLORS["warn"]),
        ("BACKGROUND", (3, 1), (3, 1), _STATUS_COLORS["info"]),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.white),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.5 * cm))

    # Site Information
    site_info = result.get("site_info", {})
    if site_info:
        elements.append(Paragraph("Site Information", heading_style))

        # Name, address, groups
        site_address = site_info.get("site_address", "")
        site_groups = site_info.get("site_groups", [])
        if site_address:
            elements.append(Paragraph(f"<b>Address:</b> {site_address}", normal_style))
        if site_groups:
            elements.append(Paragraph(f"<b>Site Groups:</b> {', '.join(site_groups)}", normal_style))
        if site_address or site_groups:
            elements.append(Spacer(1, 0.2 * cm))

        # Templates
        tmpl_list = site_info.get("templates", [])
        if tmpl_list:
            tmpl_data = [["Template Type", "Template Name"]]
            for t in tmpl_list:
                tmpl_data.append([t.get("type", ""), t.get("name", "")])
            elements.append(_make_table(tmpl_data))
            elements.append(Spacer(1, 0.2 * cm))

        # WLANs
        org_wlans = site_info.get("org_wlans", [])
        site_wlans = site_info.get("site_wlans", [])
        if org_wlans or site_wlans:
            wlan_data = [["SSID", "Source"]]
            for w in org_wlans:
                wlan_data.append([w.get("ssid", ""), "Org (template)"])
            for w in site_wlans:
                wlan_data.append([w.get("ssid", ""), "Site"])
            elements.append(_make_table(wlan_data))
        elements.append(Spacer(1, 0.3 * cm))

    # Template Variables
    tmpl_vars = result.get("template_variables", [])
    if tmpl_vars:
        elements.append(Paragraph("Template Variables", heading_style))
        data = [["Template Type", "Template Name", "Variable", "Status"]]
        for item in tmpl_vars:
            data.append([
                item.get("template_type", ""),
                _truncate(item.get("template_name", ""), 30),
                item.get("variable", ""),
                item.get("status", "").upper(),
            ])
        elements.append(_make_table(data))
        elements.append(Spacer(1, 0.3 * cm))

    # APs
    aps = result.get("aps", [])
    if aps:
        elements.append(Paragraph(f"Access Points ({len(aps)})", heading_style))
        data = [["Name", "Model", "Status", "Firmware", "Eth0 Speed"]]
        for ap in aps:
            checks = {c["check"]: c for c in ap.get("checks", [])}
            data.append([
                ap.get("name", ""),
                ap.get("model", ""),
                checks.get("connection_status", {}).get("value", ""),
                checks.get("firmware_version", {}).get("value", ""),
                checks.get("eth0_port_speed", {}).get("value", ""),
            ])
        elements.append(_make_table(data))
        elements.append(Spacer(1, 0.3 * cm))

    # Switches
    switches = result.get("switches", [])
    if switches:
        elements.append(Paragraph(f"Switches ({len(switches)})", heading_style))
        for sw in switches:
            checks = {c["check"]: c for c in sw.get("checks", [])}
            elements.append(Paragraph(
                f"<b>{sw.get('name', '(unnamed)')}</b> — {sw.get('model', '')} — "
                f"Status: {checks.get('connection_status', {}).get('value', '')} — "
                f"Firmware: {checks.get('firmware_version', {}).get('value', '')}",
                normal_style,
            ))

            # VC members
            vc = sw.get("virtual_chassis")
            if vc and vc.get("members"):
                vc_data = [["Member", "Model", "Firmware", "VC Ports UP", "Status"]]
                for m in vc["members"]:
                    vc_data.append([
                        str(m.get("member_id", "")),
                        m.get("model", ""),
                        m.get("firmware", ""),
                        str(m.get("vc_ports_up", 0)),
                        m.get("status", ""),
                    ])
                elements.append(_make_table(vc_data))

            # Cable tests
            cable_tests = sw.get("cable_tests", [])
            if cable_tests:
                ct_data = [["Port", "Result"]]
                for ct in cable_tests:
                    ct_data.append([ct.get("port", ""), ct.get("status", "").upper()])
                elements.append(_make_table(ct_data))
            elements.append(Spacer(1, 0.3 * cm))

    # Gateways
    gateways = result.get("gateways", [])
    if gateways:
        elements.append(Paragraph(f"Gateways ({len(gateways)})", heading_style))
        data = [["Name", "Model", "Status", "Firmware", "WAN Ports"]]
        for gw in gateways:
            checks = {c["check"]: c for c in gw.get("checks", [])}
            data.append([
                gw.get("name", ""),
                gw.get("model", ""),
                checks.get("connection_status", {}).get("value", ""),
                checks.get("firmware_version", {}).get("value", ""),
                checks.get("wan_port_status", {}).get("value", ""),
            ])
        elements.append(_make_table(data))

    doc.build(elements)
    return buf.getvalue()


def generate_csv_zip(report) -> bytes:
    """Generate a ZIP file containing CSV exports for each section."""
    buf = io.BytesIO()
    result = report.result or {}

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Site information
        site_info = result.get("site_info", {})
        if site_info:
            si_rows: list[dict] = []
            si_rows.append({"category": "site", "type": "name", "name": site_info.get("site_name", ""), "source": ""})
            if site_info.get("site_address"):
                si_rows.append({"category": "site", "type": "address", "name": site_info["site_address"], "source": ""})
            for g in site_info.get("site_groups", []):
                si_rows.append({"category": "site_group", "type": "", "name": g, "source": ""})
            for t in site_info.get("templates", []):
                si_rows.append({"category": "template", "type": t.get("type", ""), "name": t.get("name", ""), "source": ""})
            for w in site_info.get("org_wlans", []):
                si_rows.append({"category": "wlan", "type": "", "name": w.get("ssid", ""), "source": "org"})
            for w in site_info.get("site_wlans", []):
                si_rows.append({"category": "wlan", "type": "", "name": w.get("ssid", ""), "source": "site"})
            if si_rows:
                zf.writestr("site_info.csv", _dict_list_to_csv(si_rows, ["category", "type", "name", "source"]))

        # Template variables
        tmpl_vars = result.get("template_variables", [])
        if tmpl_vars:
            zf.writestr("template_variables.csv", _dict_list_to_csv(
                tmpl_vars, ["template_type", "template_name", "variable", "defined", "status"]
            ))

        # APs
        aps = result.get("aps", [])
        if aps:
            zf.writestr("aps.csv", _devices_to_csv(aps, ["eth0_port_speed", "config_status"]))

        # Switches
        switches = result.get("switches", [])
        if switches:
            zf.writestr("switches.csv", _devices_to_csv(switches, ["config_status"]))
            # Cable tests in a separate CSV
            ct_rows: list[dict] = []
            for sw in switches:
                for ct in sw.get("cable_tests", []):
                    ct_rows.append({
                        "switch_name": sw.get("name", ""),
                        "switch_id": sw.get("device_id", ""),
                        "port": ct.get("port", ""),
                        "status": ct.get("status", ""),
                        "pairs": str(ct.get("pairs", [])),
                    })
            if ct_rows:
                zf.writestr("cable_tests.csv", _dict_list_to_csv(
                    ct_rows, ["switch_name", "switch_id", "port", "status", "pairs"]
                ))

        # Gateways
        gateways = result.get("gateways", [])
        if gateways:
            zf.writestr("gateways.csv", _devices_to_csv(gateways, ["wan_port_status", "config_status"]))

    return buf.getvalue()


# ── Internal helpers ─────────────────────────────────────────────────────


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _make_table(data: list[list]) -> Table:
    """Create a styled reportlab Table."""
    col_count = len(data[0]) if data else 1
    col_width = (A4[0] - 3 * cm) / col_count
    table = Table(data, colWidths=[col_width] * col_count, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def _dict_list_to_csv(rows: list[dict], fields: list[str]) -> str:
    """Convert a list of dicts to a CSV string."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return out.getvalue()


def _devices_to_csv(devices: list[dict], extra_checks: list[str]) -> str:
    """Convert device check results to a CSV string."""
    fields = ["name", "device_id", "mac", "model", "connection_status", "firmware_version"] + extra_checks
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for dev in devices:
        checks = {c["check"]: c.get("value", "") for c in dev.get("checks", [])}
        row = {
            "name": dev.get("name", ""),
            "device_id": dev.get("device_id", ""),
            "mac": dev.get("mac", ""),
            "model": dev.get("model", ""),
        }
        row.update(checks)
        writer.writerow(row)
    return out.getvalue()
