"""Standard deck template. Every deck uses these exact colours, fonts and layout.
Change the look ONLY here. Pure Python (reportlab): no browser or server needed."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping

FONTS = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("LS", str(FONTS / "LiberationSans-Regular.ttf")))
pdfmetrics.registerFont(TTFont("LS-B", str(FONTS / "LiberationSans-Bold.ttf")))
for b, i, f in [(0, 0, "LS"), (1, 0, "LS-B"), (0, 1, "LS"), (1, 1, "LS-B")]:
    addMapping("LS", b, i, f)

W, H = 960, 540
NAVY, TEAL, AMBER = HexColor("#0F2A43"), HexColor("#1B998B"), HexColor("#F4A259")
INK, GREY, LIGHT = HexColor("#1D2733"), HexColor("#5B6B7A"), HexColor("#F3F6F9")
SIG = "Knowledge sharing by Kunal Sinha"


def _st(size, color=INK, bold=False, lead=None):
    return ParagraphStyle("s", fontName="LS-B" if bold else "LS", fontSize=size,
                          leading=lead or size * 1.3, textColor=color)


def _para(c, text, x, ytop, w, style):
    p = Paragraph(text, style)
    _, h = p.wrap(w, 2000)
    p.drawOn(c, x, ytop - h)
    return h


def _esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _frame(c, n, total, kicker, title):
    c.setFillColor(white); c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(NAVY); c.rect(0, H - 92, W, 92, fill=1, stroke=0)
    c.setFillColor(TEAL); c.rect(0, H - 96, W, 4, fill=1, stroke=0)
    c.setFillColor(AMBER); c.setFont("LS-B", 11); c.drawString(48, H - 34, kicker.upper()[:70])
    size = 27
    while size > 18 and pdfmetrics.stringWidth(title, "LS-B", size) > W - 96:
        size -= 1
    c.setFillColor(white); c.setFont("LS-B", size); c.drawString(48, H - 68, title)
    c.setFillColor(GREY); c.setFont("LS", 10)
    c.drawString(48, 22, SIG); c.drawRightString(W - 48, 22, f"{n} / {total}")
    c.setStrokeColor(HexColor("#D5DDE5")); c.line(48, 38, W - 48, 38)


def _bullets(c, items, x, ytop, w, max_h, note):
    """Largest font (17 -> 12pt) that fits the available height."""
    avail = max_h - (58 if note else 0)
    for size in (17, 16, 15, 14, 13, 12):
        total = 0
        for it in items:
            p = Paragraph(_esc(it), _st(size)); total += p.wrap(w - 20, 2000)[1] + size * 0.75
        if total <= avail or size == 12:
            break
    y = ytop
    for it in items:
        c.setFillColor(TEAL); c.circle(x + 5, y - size * 0.55, 4, fill=1, stroke=0)
        h = _para(c, _esc(it), x + 20, y, w - 20, _st(size))
        y -= h + size * 0.75
    return y


def build_pdf(deck, sources, out_path, date_label):
    slides = (deck.get("slides") or [])[:8]
    total = len(slides) + 2
    c = canvas.Canvas(str(out_path), pagesize=(W, H), pageCompression=1, initialFontName="LS")
    c.setTitle(deck.get("topic", "Lean update")); c.setAuthor("Kunal Sinha")
    # 1. cover
    c.setFillColor(NAVY); c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(TEAL); c.rect(0, 0, 18, H, fill=1, stroke=0)
    c.setFillColor(AMBER); c.setFont("LS-B", 13)
    c.drawString(70, 440, "LEAN  |  PROCESS EXCELLENCE  |  OPERATIONAL EXCELLENCE")
    _para(c, _esc(deck.get("topic", "")), 70, 410, 820, _st(42, white, True, 52))
    _para(c, _esc(deck.get("subtitle", "")), 70, 250, 760, _st(18, HexColor("#C9D6E2")))
    c.setStrokeColor(AMBER); c.setLineWidth(2); c.line(70, 150, 300, 150)
    c.setFillColor(white); c.setFont("LS-B", 20); c.drawString(70, 118, SIG)
    c.setFillColor(HexColor("#9FB3C6")); c.setFont("LS", 12); c.drawString(70, 92, date_label)
    c.showPage()
    # 2..n-1 content
    for i, s in enumerate(slides):
        _frame(c, i + 2, total, s.get("kicker", ""), s.get("title", ""))
        note = (s.get("note") or "").strip()
        items = [b for b in (s.get("bullets") or [])[:5]]
        end = _bullets(c, items, 48, H - 125, W - 96, H - 125 - 60, note)
        if note:
            c.setFillColor(LIGHT); c.roundRect(48, 52, W - 96, 40, 4, fill=1, stroke=0)
            c.setFillColor(AMBER); c.rect(48, 52, 5, 40, fill=1, stroke=0)
            _para(c, _esc(note), 64, 86, W - 130, _st(12.5, HexColor("#3A4A5A")))
        c.showPage()
    # last: sources + signature band
    _frame(c, total, total, "References", "Sources")
    y = H - 125
    for sr in (sources or [])[:10]:
        y -= _para(c, "• " + _esc(sr.get("title", "")), 48, y, W - 96, _st(12, HexColor("#3A4A5A"))) + 6
    c.setFillColor(NAVY); c.rect(0, 60, W, 56, fill=1, stroke=0)
    c.setFillColor(white); c.setFont("LS-B", 21); c.drawCentredString(W / 2, 80, SIG)
    c.showPage()
    c.save()
    return out_path
