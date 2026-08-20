from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BRAND = colors.HexColor("#2a78d6")
STYLES = getSampleStyleSheet()


def _doc(buf):
    return SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm
    )


def _table(data, col_widths=None):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c3c2b7")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f9f9f7")]),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e1e0d9")),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def _header(title, subtitle):
    elements = [
        Paragraph("BICON TRANS", STYLES["Title"]),
        Paragraph(title, STYLES["Heading2"]),
        Paragraph(subtitle, STYLES["Normal"]),
        Spacer(1, 0.5 * cm),
    ]
    return elements


def _money(v):
    return f"{v:,.0f}"


def build_summary_pdf(rows, totals, start, end):
    buf = BytesIO()
    doc = _doc(buf)
    data = [["GARI", "MAKUSANYO", "MATUMIZI", "BAKI"]]
    for r in rows:
        data.append([r["car"], _money(r["collected"]), _money(r["consumed"]), _money(r["net"])])
    data.append(
        ["JUMLA KUU", _money(totals["grand_collected"]), _money(totals["grand_consumed"]), _money(totals["grand_net"])]
    )
    elements = _header("Muhtasari wa Makusanyo na Matumizi", f"{start.isoformat()} hadi {end.isoformat()}")
    elements.append(_table(data))
    doc.build(elements)
    buf.seek(0)
    return buf


def build_collections_pdf(rows, total, start, end):
    buf = BytesIO()
    doc = _doc(buf)
    data = [["TAREHE", "TRANS NO", "GARI", "KIASI", "MAELEZO"]]
    for r in rows:
        data.append([r["date"].isoformat(), r["trans_no"], r["car"], _money(r["amount"]), r["note"]])
    data.append(["", "", "", _money(total), "JUMLA"])
    elements = _header("Ripoti ya Makusanyo", f"{start.isoformat()} hadi {end.isoformat()}")
    elements.append(_table(data, col_widths=[3 * cm, 3 * cm, 2.5 * cm, 3 * cm, None]))
    doc.build(elements)
    buf.seek(0)
    return buf


def build_consumption_pdf(rows, total, start, end):
    buf = BytesIO()
    doc = _doc(buf)
    data = [["TAREHE", "GARI", "AINA", "KIASI", "MAELEZO"]]
    for r in rows:
        data.append([r["date"].isoformat(), r["car"], r["category"], _money(r["amount"]), r["description"]])
    data.append(["", "", "", _money(total), "JUMLA"])
    elements = _header("Ripoti ya Matumizi", f"{start.isoformat()} hadi {end.isoformat()}")
    elements.append(_table(data, col_widths=[3 * cm, 2.5 * cm, 3.5 * cm, 3 * cm, None]))
    doc.build(elements)
    buf.seek(0)
    return buf
