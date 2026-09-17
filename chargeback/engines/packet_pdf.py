"""The counter evidence packet as a PDF.

The same document ``templates/client_packet.html`` puts on screen, rendered from
the same projection ``app._client_packet`` assembles. Two renderings of one
packet: the prose, the assembled documents and the exhibit list cannot drift
apart here, only the typesetting.

Nothing in this module decides what a merchant may see. That is settled in the
projection, so a field that should not reach a merchant cannot reach one by
being referenced here.
"""

import os
from io import BytesIO
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

# The packet's palette, taken from client_packet.html so the page and the file
# read as one document.
INK = colors.HexColor("#2e1f17")
BODY = colors.HexColor("#4b4038")
MUTED = colors.HexColor("#6b584c")
FAINT = colors.HexColor("#9c8578")
BRAND = colors.HexColor("#f4611a")
BRAND_WASH = colors.HexColor("#ffeadd")
RED = colors.HexColor("#c62828")
RULE = colors.HexColor("#e7ded6")
HAIRLINE = colors.HexColor("#f0e8e1")
CARD = colors.HexColor("#fdfbf9")
PRIMARY_WASH = colors.HexColor("#fce4ec")
SECONDARY_WASH = colors.HexColor("#fcf6f1")
FOOT = colors.HexColor("#9c8578")

FOOTER_TEXT = "CONFIDENTIAL DISPUTE REPRESENTMENT EVIDENCE"

# Longest side handed to reportlab. A 10 MB upload can decode to hundreds of
# megapixels; MAX_IMAGE_PIXELS is Pillow's own bomb guard.
MAX_IMAGE_PX = 4000
PILImage.MAX_IMAGE_PIXELS = 64_000_000

# Room for a picture without pushing its caption onto the next page.
MAX_IMAGE_HEIGHT = 165 * mm


def _esc(value):
    """Text safe for reportlab's mini-markup.

    Paragraph parses its input as markup, so an ampersand in a merchant name or
    a "<" in an agent's prose would raise rather than print.
    """
    return escape("" if value is None else str(value))


def _money(value):
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _styles():
    base = getSampleStyleSheet()
    return {
        "masthead": ParagraphStyle("mh", parent=base["Title"], fontSize=16, leading=20,
                                   textColor=INK, alignment=TA_CENTER, spaceAfter=2),
        "mastsub": ParagraphStyle("ms", parent=base["Normal"], fontSize=9.5, leading=13,
                                  textColor=MUTED, alignment=TA_CENTER, spaceAfter=4),
        "prose": ParagraphStyle("pr", parent=base["Normal"], fontSize=9.5, leading=14,
                                textColor=INK, spaceAfter=6),
        "sectitle": ParagraphStyle("st", parent=base["Heading2"], fontSize=12, leading=15,
                                   textColor=INK, spaceBefore=14, spaceAfter=5,
                                   underlineWidth=0.7, underlineOffset=-3),
        "endtitle": ParagraphStyle("et", parent=base["Heading2"], fontSize=12, leading=15,
                                   textColor=RED, spaceBefore=14, spaceAfter=5,
                                   underlineWidth=0.7, underlineOffset=-3),
        "compelling": ParagraphStyle("cp", parent=base["Normal"], fontSize=9.5, leading=13,
                                     textColor=INK, fontName="Helvetica-Bold",
                                     spaceBefore=6, spaceAfter=5),
        "mandate": ParagraphStyle("md", parent=base["Normal"], fontSize=9, leading=12.5,
                                  textColor=BRAND, fontName="Helvetica-BoldOblique",
                                  leftIndent=16, bulletIndent=5, spaceAfter=2),
        "dochead": ParagraphStyle("dh", parent=base["Normal"], fontSize=9.5, leading=12.5,
                                  textColor=INK, fontName="Helvetica-Bold",
                                  spaceBefore=7, spaceAfter=3),
        "docpara": ParagraphStyle("dp", parent=base["Normal"], fontSize=9, leading=12.5,
                                  textColor=BODY, spaceAfter=4),
        "policy": ParagraphStyle("po", parent=base["Normal"], fontSize=7.5, leading=10,
                                 textColor=colors.HexColor("#b45309"),
                                 fontName="Helvetica-Bold", spaceAfter=5),
        "rank": ParagraphStyle("rk", parent=base["Normal"], fontSize=9.5, leading=13,
                               fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=5),
        "item": ParagraphStyle("it", parent=base["Normal"], fontSize=9, leading=12,
                               textColor=INK, fontName="Helvetica-Bold"),
        "caption": ParagraphStyle("ca", parent=base["Normal"], fontSize=8.5, leading=11,
                                  textColor=MUTED, spaceBefore=2, spaceAfter=6),
        "note": ParagraphStyle("nt", parent=base["Normal"], fontSize=8.5, leading=11,
                               textColor=FAINT, fontName="Helvetica-Oblique",
                               spaceAfter=6),
        "cell": ParagraphStyle("ce", parent=base["Normal"], fontSize=8.5, leading=11,
                               textColor=INK),
        "cellk": ParagraphStyle("ck", parent=base["Normal"], fontSize=8.5, leading=11,
                                textColor=MUTED),
        "label": ParagraphStyle("lb", parent=base["Normal"], fontSize=8.5, leading=11,
                                textColor=MUTED, fontName="Helvetica-Bold"),
        # 7.5pt so a 23-digit ARN fits its cell on one line. reportlab splits an
        # unbroken run mid-number rather than overflowing, and an ARN broken
        # across two lines is the one field an issuer has to be able to read.
        "mono": ParagraphStyle("mo", parent=base["Normal"], fontSize=7.5, leading=10.5,
                               fontName="Courier", textColor=INK),
    }


def _page_furniture(doc_title, generated_at):
    """The header strip every page carries. The footer needs the page total, so
    it is drawn by _NumberedCanvas once the whole packet has been laid out."""

    def draw(canvas, pdf):
        canvas.saveState()
        w, h = A4
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(FAINT)
        canvas.drawString(18 * mm, h - 11 * mm, generated_at)
        canvas.drawRightString(w - 18 * mm, h - 11 * mm, doc_title)
        canvas.restoreState()

    return draw


class _NumberedCanvas(Canvas):
    """"Page N of M", where M is only known once everything has been laid out.

    A packet's length depends on how many sections survived, how much the agent
    wrote and how many pictures are attached, so there is no page count to
    assume — it is counted here rather than claimed.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._footer(total)
            super().showPage()
        super().save()

    def _footer(self, total):
        w = A4[0]
        self.saveState()
        self.setFont("Helvetica-Bold", 7)
        self.setFillColor(FOOT)
        self.drawString(18 * mm, 12 * mm, FOOTER_TEXT)
        self.drawRightString(w - 18 * mm, 12 * mm,
                             f"PAGE {self._pageNumber} OF {total}")
        self.restoreState()


def _info_table(rows, st, width):
    """The header grid — two label/value pairs to a row."""
    body = []
    for pair in [rows[i:i + 2] for i in range(0, len(rows), 2)]:
        cells = []
        for label, value in pair:
            cells.append(Paragraph(_esc(label), st["label"]))
            cells.append(Paragraph(_esc(value), st["mono"]))
        while len(cells) < 4:
            cells.append(Paragraph("", st["cell"]))
        body.append(cells)
    table = Table(body, colWidths=[width * 0.21, width * 0.29] * 2)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#fdfbf9")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#fdfbf9")),
    ]))
    return table


def _kv_table(pairs, st, width):
    """A document's own label/value rows."""
    body = [[Paragraph(_esc(k), st["cellk"]), Paragraph(_esc(v), st["cell"])]
            for k, v in pairs]
    table = Table(body, colWidths=[width * 0.34, width * 0.66])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, HAIRLINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _prose(text, st, style="prose"):
    """Agent-written text, one paragraph per line, blank lines dropped.

    Paragraph collapses whitespace, so the page's `white-space: pre-wrap` has to
    be reproduced by splitting rather than by handing over the string whole.
    """
    return [Paragraph(_esc(line.strip()), st[style])
            for line in (text or "").splitlines() if line.strip()]


def _image_flowable(path, frame_width):
    """An attached picture drawn into the packet, or None if it will not draw.

    platypus.Image is lazy for anything that is not a .jpg — Image('broken.png')
    constructs fine and raises inside doc.build(), where there is no per-flowable
    recovery and one bad upload would take the whole download with it. So the
    file is opened, decoded, normalised and measured here, before it is ever
    appended to the story. Whatever does not survive is listed by name instead,
    which is what a non-image attachment gets anyway.
    """
    try:
        if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
            return None
        # verify() is structural only and leaves the image unusable, so the file
        # is opened twice: once to reject garbage, once to read it.
        with PILImage.open(path) as probe:
            probe.verify()
        with PILImage.open(path) as im:
            im.load()
            width, height = im.size
            if not width or not height:
                return None
            # Always convert. CMYK is the reason: reportlab inlines a
            # four-component JPEG raw and writes an inverting Decode array
            # unconditionally, which turns any non-Adobe CMYK photo into a
            # negative. RGB also sidesteps the palette-with-transparency path.
            if im.mode != "RGB":
                im = im.convert("RGB")
            if max(width, height) > MAX_IMAGE_PX:
                im.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX), PILImage.LANCZOS)
                width, height = im.size
            buf = BytesIO()
            im.save(buf, format="PNG", optimize=True)
            buf.seek(0)
    except (OSError, ValueError, SyntaxError, MemoryError,
            PILImage.DecompressionBombError):
        return None

    # Fit the frame in both directions. platypus will not: it only errors when a
    # flowable overflows vertically, so a wide picture runs silently off the
    # right margin instead.
    scale = min(frame_width / float(width), MAX_IMAGE_HEIGHT / float(height), 1.0)
    return Image(buf, width=width * scale, height=height * scale, kind="direct")


def _attachment_flowables(files, st, width):
    """Pictures drawn in, everything else named."""
    out = []
    for f in files:
        caption = Paragraph(
            f'&#128196; {_esc(f.get("name"))} '
            f'<font color="#9c8578">&middot; {_esc(f.get("size_kb"))} KB</font>',
            st["caption"])
        picture = _image_flowable(f.get("path"), width) if f.get("kind") == "image" else None
        if picture is not None:
            out.append(KeepTogether([picture, caption]))
        else:
            out.append(caption)
    return out


def _section_flowables(section, st, width):
    """One evidence section: its title, the agent's intro, what was assembled
    for it and what was attached to it."""
    out = [Paragraph(f'<u>{_esc(section["title"])}:</u>', st["sectitle"])]
    out += _prose(section.get("intro"), st)

    doc = section.get("document")
    if doc:
        out.append(Paragraph(
            f'Compelling Evidence: {{{_esc(doc["title"])}}}', st["compelling"]))
        inner = []
        if doc.get("policy"):
            inner.append(Paragraph("MERCHANT POLICY", st["policy"]))
        for heading, body in doc.get("sections") or []:
            inner.append(Paragraph(_esc(heading), st["dochead"]))
            if body and isinstance(body[0], str):
                inner += [Paragraph(_esc(p), st["docpara"]) for p in body]
            elif body:
                inner.append(_kv_table(body, st, width - 16))
        card = Table([[inner]], colWidths=[width])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CARD),
            ("BOX", (0, 0), (-1, -1), 0.5, RULE),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        out.append(card)

    out += _attachment_flowables(section.get("attachments") or [], st, width)
    return out


def _rank_flowables(names, st, width, primary):
    out = [Paragraph(
        "Primary Evidence (Required)" if primary else "Secondary Evidence (Supporting)",
        ParagraphStyle("r", parent=st["rank"], textColor=RED if primary else MUTED))]
    for name in names:
        row = Table([[Paragraph(_esc(name), st["item"])]], colWidths=[width])
        row.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PRIMARY_WASH if primary else SECONDARY_WASH),
            ("LINEBEFORE", (0, 0), (0, -1), 3, RED if primary else colors.HexColor("#d0bcae")),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        out.append(row)
    return out


def render_packet_pdf(packet, case=None):
    """The counter evidence packet as PDF bytes.

    `packet` is exactly what app._client_packet returns and
    templates/client_packet.html renders, so this adds no facts of its own.
    """
    st = _styles()
    buf = BytesIO()
    title = packet.get("document_title") or "Counter Evidence"
    pdf = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=title, author=(case or {}).get("merchant", "") or "ChargeShield AI",
        subject=f"Chargeback representment evidence - {packet.get('case_id', '')}",
    )
    width = pdf.width

    story = [
        Paragraph(_esc(title), st["masthead"]),
        Paragraph(_esc(packet.get("subtitle")), st["mastsub"]),
        Spacer(1, 10),
        _info_table(packet.get("header") or [], st, width),
        Spacer(1, 12),
    ]
    story += _prose(packet.get("letter_body"), st)

    mandate = packet.get("mandate") or []
    if mandate:
        lines = [Paragraph(
            f"The compelling evidence listed below are provided as per "
            f"{_esc(packet.get('payment_method'))}'s Compelling Evidence Mandate "
            f"Policy Revision:", st["mandate"])]
        for i, line in enumerate(mandate, 1):
            lines.append(Paragraph(_esc(line), st["mandate"], bulletText=f"{i}."))
        panel = Table([[lines]], colWidths=[width])
        panel.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_WASH),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story += [Spacer(1, 6), panel]

    sections = packet.get("sections") or []
    for section in sections:
        story += _section_flowables(section, st, width)
    if not sections:
        story.append(Paragraph(
            "No supporting documents were attached to this dispute.", st["note"]))

    names = packet.get("attachment_names") or []
    if names:
        story.append(Paragraph("<u>Attachments:</u>", st["sectitle"]))
        for i, name in enumerate(names, 1):
            story.append(Paragraph(_esc(name), st["docpara"], bulletText=f"{i}."))

    other = packet.get("other_attachments") or []
    if other:
        story.append(Paragraph("<u>Other Attachments:</u>", st["sectitle"]))
        story += _attachment_flowables(other, st, width)

    primary = packet.get("evidence_primary") or []
    secondary = packet.get("evidence_secondary") or []
    if primary or secondary:
        story.append(PageBreak())
        story.append(Paragraph("<u>Evidence Categorization</u>", st["sectitle"]))
        story.append(Paragraph(
            "Evidence is categorized by the dispute's reason code into primary "
            "(required to win) and secondary (supporting). Listed here is what "
            "this packet carries.", st["note"]))
        if primary:
            story += _rank_flowables(primary, st, width, True)
        if secondary:
            story += _rank_flowables(secondary, st, width, False)

    conclusion = packet.get("conclusion")
    if conclusion:
        story.append(Paragraph("<u>Conclusion:</u>", st["endtitle"]))
        story += _prose(conclusion, st)

    furniture = _page_furniture(title, f"Generated {packet.get('generated_at', '')}")
    pdf.build(story, onFirstPage=furniture, onLaterPages=furniture,
              canvasmaker=_NumberedCanvas)
    return buf.getvalue()
