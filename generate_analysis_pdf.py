"""Generate trading analysis PDF from session conversation."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from datetime import date

OUTPUT = "Trading_Analysis_22Jun2026.pdf"

# ── colour palette ────────────────────────────────────────────────────────────
DARK       = colors.HexColor("#1a1a2e")
ACCENT     = colors.HexColor("#185FA5")
GREEN      = colors.HexColor("#0F6E56")
GREEN_LITE = colors.HexColor("#E1F5EE")
RED        = colors.HexColor("#A32D2D")
RED_LITE   = colors.HexColor("#FCEBEB")
AMBER      = colors.HexColor("#854F0B")
AMBER_LITE = colors.HexColor("#FAEEDA")
BLUE_LITE  = colors.HexColor("#E6F1FB")
GREY       = colors.HexColor("#F1EFE8")
GREY_MID   = colors.HexColor("#888780")
BORDER     = colors.HexColor("#D3D1C7")

# ── styles ────────────────────────────────────────────────────────────────────
def build_styles():
    s = getSampleStyleSheet()
    base = dict(fontName="Helvetica", leading=14)

    def ps(name, **kw):
        return ParagraphStyle(name, **{**base, **kw})

    return dict(
        cover_title  = ps("cover_title",  fontSize=26, fontName="Helvetica-Bold",
                          textColor=DARK, alignment=TA_CENTER, leading=32),
        cover_sub    = ps("cover_sub",    fontSize=13, textColor=GREY_MID,
                          alignment=TA_CENTER, spaceAfter=6),
        cover_date   = ps("cover_date",   fontSize=11, textColor=GREY_MID,
                          alignment=TA_CENTER, spaceAfter=4),

        section_hdr  = ps("section_hdr",  fontSize=16, fontName="Helvetica-Bold",
                          textColor=ACCENT, spaceBefore=14, spaceAfter=4),
        sub_hdr      = ps("sub_hdr",      fontSize=13, fontName="Helvetica-Bold",
                          textColor=DARK, spaceBefore=10, spaceAfter=4),
        mini_hdr     = ps("mini_hdr",     fontSize=11, fontName="Helvetica-Bold",
                          textColor=DARK, spaceBefore=6, spaceAfter=3),

        body         = ps("body",         fontSize=10, textColor=colors.black,
                          spaceAfter=4, leading=15),
        body_sm      = ps("body_sm",      fontSize=9,  textColor=colors.HexColor("#3a3a3a"),
                          spaceAfter=3, leading=13),
        bullet       = ps("bullet",       fontSize=10, textColor=colors.black,
                          leftIndent=14, spaceAfter=3, leading=14,
                          bulletIndent=4, bulletText="•"),
        note         = ps("note",         fontSize=9,  textColor=GREY_MID,
                          alignment=TA_CENTER, spaceAfter=2),

        verdict_g    = ps("verdict_g",    fontSize=11, fontName="Helvetica-Bold",
                          textColor=GREEN, spaceAfter=3),
        verdict_r    = ps("verdict_r",    fontSize=11, fontName="Helvetica-Bold",
                          textColor=RED, spaceAfter=3),
        verdict_a    = ps("verdict_a",    fontSize=11, fontName="Helvetica-Bold",
                          textColor=AMBER, spaceAfter=3),
    )

def hr(doc):
    return HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=6, spaceBefore=4)

def spacer(h=6):
    return Spacer(1, h)

def section_divider(styles, title):
    return [
        spacer(8),
        Paragraph(title, styles["section_hdr"]),
        HRFlowable(width="100%", thickness=1.5, color=ACCENT, spaceAfter=8),
    ]

# ── metric card table ─────────────────────────────────────────────────────────
def metric_row(data, colcount=4):
    """data = list of (label, value, sub) tuples"""
    cells, styles_cmds = [], []
    for i, (lbl, val, sub) in enumerate(data):
        cell = Paragraph(
            f'<font size="8" color="#888780">{lbl}</font><br/>'
            f'<font size="13"><b>{val}</b></font>'
            + (f'<br/><font size="8" color="#888780">{sub}</font>' if sub else ""),
            ParagraphStyle("mc", fontName="Helvetica", leading=16)
        )
        cells.append(cell)

    while len(cells) % colcount:
        cells.append("")

    rows = [cells[i:i+colcount] for i in range(0, len(cells), colcount)]
    w = 170 / colcount
    t = Table(rows, colWidths=[w*mm]*colcount, rowHeights=18*mm)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), GREY),
        ("BOX",        (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID",  (0,0), (-1,-1), 0.5, BORDER),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",(0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("ROUNDEDCORNERS", [4]),
    ]))
    return t

# ── levels table ──────────────────────────────────────────────────────────────
def levels_table(rows_data):
    """rows_data = list of (side, label, value) where side in R/S/N"""
    colour_map = {"R": (RED_LITE, RED), "S": (GREEN_LITE, GREEN), "N": (GREY, DARK)}
    rows = []
    for side, label, value in rows_data:
        bg, fg = colour_map.get(side, (GREY, DARK))
        rows.append([
            Paragraph(label, ParagraphStyle("lbl", fontName="Helvetica", fontSize=9,
                                             textColor=colors.HexColor("#444441"))),
            Paragraph(f'<font color="#{fg.hexval()[2:]}" ><b>{value}</b></font>',
                      ParagraphStyle("val", fontName="Helvetica", fontSize=9,
                                     alignment=TA_RIGHT)),
        ])
    t = Table(rows, colWidths=[105*mm, 55*mm])
    style_cmds = [
        ("BOX",    (0,0), (-1,-1), 0.5, BORDER),
        ("LINEBELOW",(0,0),(-1,-2), 0.5, BORDER),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),8),
        ("RIGHTPADDING",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]
    for i, (side, _, _) in enumerate(rows_data):
        bg = colour_map.get(side, (GREY, DARK))[0]
        style_cmds.append(("BACKGROUND", (0,i), (-1,i), bg))
    t.setStyle(TableStyle(style_cmds))
    return t

# ── coloured 3-column insight box ─────────────────────────────────────────────
def insight_table(cols, styles):
    """cols = list of (title, colour, items_list)"""
    bg_map = {"green": GREEN_LITE, "amber": AMBER_LITE, "red": RED_LITE}
    fg_map = {"green": GREEN,      "amber": AMBER,      "red": RED}
    cells = []
    for title, colour, items in cols:
        bg = bg_map.get(colour, GREY)
        fg = fg_map.get(colour, DARK)
        txt = (f'<font color="#{fg.hexval()[2:]}"><b>{title}</b></font><br/>'
               + "<br/>".join(f"• {i}" for i in items))
        cells.append(Paragraph(txt, ParagraphStyle(
            "ins", fontName="Helvetica", fontSize=9, leading=14,
            leftIndent=0, spaceAfter=0)))
    t = Table([cells], colWidths=[55*mm]*3)
    style_cmds = [
        ("BOX",      (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID",(0,0), (-1,-1), 0.5, BORDER),
        ("VALIGN",   (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",(0,0),(-1,-1),8),
        ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),8),
        ("RIGHTPADDING",(0,0),(-1,-1),8),
    ]
    for i, (_, colour, _) in enumerate(cols):
        bg = bg_map.get(colour, GREY)
        style_cmds.append(("BACKGROUND", (i,0), (i,0), bg))
    t.setStyle(TableStyle(style_cmds))
    return t

# ── generic data table ────────────────────────────────────────────────────────
def data_table(headers, rows, col_widths=None):
    all_rows = [headers] + rows
    if col_widths is None:
        w = 170 / len(headers)
        col_widths = [w*mm] * len(headers)
    t = Table(all_rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  ACCENT),
        ("TEXTCOLOR",     (0,0), (-1,0),  colors.white),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0),  9),
        ("BACKGROUND",    (0,1), (-1,-1), colors.white),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, GREY]),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,1), (-1,-1), 9),
        ("GRID",          (0,0), (-1,-1), 0.5, BORDER),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ]))
    return t

# ── trade setup box ───────────────────────────────────────────────────────────
def trade_setup_table(rows):
    """rows = list of (param, value, note)"""
    colour_row = {
        "Entry zone":  (BLUE_LITE, ACCENT),
        "Stop loss":   (RED_LITE,  RED),
        "Target 1":    (GREEN_LITE, GREEN),
        "Target 2":    (GREEN_LITE, GREEN),
        "R:R":         (GREY, DARK),
        "Risk":        (AMBER_LITE, AMBER),
        "Stance":      (AMBER_LITE, AMBER),
    }
    tbl_rows = []
    style_cmds = [
        ("BOX",    (0,0),(-1,-1), 0.5, BORDER),
        ("LINEBELOW",(0,0),(-1,-2), 0.5, BORDER),
        ("VALIGN", (0,0),(-1,-1), "MIDDLE"),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),8),
        ("RIGHTPADDING",(0,0),(-1,-1),8),
    ]
    for i, (param, value, note) in enumerate(rows):
        bg, fg = colour_row.get(param, (GREY, DARK))
        tbl_rows.append([
            Paragraph(f"<b>{param}</b>", ParagraphStyle(
                "tp", fontName="Helvetica-Bold", fontSize=9,
                textColor=colors.HexColor("#3a3a3a"))),
            Paragraph(f'<font color="#{fg.hexval()[2:]}"><b>{value}</b></font>',
                      ParagraphStyle("tv", fontName="Helvetica-Bold", fontSize=10)),
            Paragraph(note, ParagraphStyle("tn", fontName="Helvetica", fontSize=8,
                                            textColor=GREY_MID)),
        ])
        style_cmds.append(("BACKGROUND", (0,i),(-1,i), bg))

    t = Table(tbl_rows, colWidths=[45*mm, 60*mm, 65*mm])
    t.setStyle(TableStyle(style_cmds))
    return t

# ─────────────────────────────────────────────────────────────────────────────
# CONTENT BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def build_cover(styles):
    elems = []
    elems.append(spacer(40))
    elems.append(Paragraph("Trading Analysis Report", styles["cover_title"]))
    elems.append(spacer(8))
    elems.append(Paragraph("Intraday &amp; Positional Setups — Indian Equities", styles["cover_sub"]))
    elems.append(spacer(4))
    elems.append(Paragraph("Generated: 22 June 2026 | Source: OpenAlgo MCP", styles["cover_date"]))
    elems.append(spacer(20))

    toc_data = [
        ["#", "Section", "Instrument", "Type"],
        ["1", "NIFTY 50 Index",         "NSE_INDEX",    "Intraday"],
        ["2", "Dixon Technologies",      "NSE: DIXON",   "Positional"],
        ["3", "HCL Technologies",        "NSE: HCLTECH", "Positional"],
    ]
    t = data_table(toc_data[0], toc_data[1:], [10*mm, 65*mm, 50*mm, 35*mm])
    elems.append(t)
    elems.append(spacer(16))
    elems.append(Paragraph(
        "Disclaimer: This report is for educational purposes only and does not constitute "
        "investment advice. All prices as of the morning session, 22 June 2026. "
        "Trading in equities and derivatives carries significant risk.",
        styles["note"]
    ))
    return elems


def build_nifty(styles):
    elems = []
    elems += section_divider(styles, "1. NIFTY 50 — Intraday Analysis")

    # Metrics
    elems.append(Paragraph("Market Snapshot", styles["sub_hdr"]))
    elems.append(metric_row([
        ("LTP",       "24,123.7", "+0.46%"),
        ("Day Open",  "24,106.6", "Gap +93.5 pts"),
        ("Day High",  "24,137.4", ""),
        ("Day Low",   "24,073.15",""),
        ("Prev Close","24,013.1", ""),
        ("Day Range", "64.2 pts", "Early session"),
    ], colcount=3))
    elems.append(spacer(10))

    # Context
    elems.append(Paragraph("Market Context", styles["sub_hdr"]))
    elems.append(Paragraph(
        "NIFTY 50 opened with a strong gap-up of 93.5 pts (+0.39%) against the previous close "
        "of 24,013. The index hit a session high of 24,137 within the first candle. Only two "
        "5-minute candles were available at the time of analysis (09:15–09:20 IST). "
        "The 20-day SMA stands at approximately 23,632, and the index is trading 491 pts above it, "
        "confirming the broader intermediate uptrend from the 30-day low of 23,070 (Jun 8).",
        styles["body"]
    ))
    elems.append(spacer(6))

    # Levels
    elems.append(Paragraph("Key Levels", styles["sub_hdr"]))
    elems.append(levels_table([
        ("R", "R3 · Jun 18 all-time recent high",      "24,189"),
        ("R", "R2 · Today's session high",              "24,137"),
        ("R", "R1 · Jun 19 intraday high area",         "24,047"),
        ("N", "CMP (Last Traded Price)",                "24,123.7"),
        ("S", "S1 · Today's session low",              "24,073"),
        ("S", "S2 · Prev close / gap fill level",      "24,013"),
        ("S", "S3 · Jun 19 intraday low",              "23,902"),
        ("S", "20-day SMA",                             "23,632"),
    ]))
    elems.append(spacer(10))

    # Technicals
    elems.append(Paragraph("Technical Signals", styles["sub_hdr"]))
    elems.append(insight_table([
        ("Bullish cues", "green", [
            "Gap-up open +93.5 pts",
            "Opened above prev close",
            "Above 20-day SMA (+491 pts)",
            "10-day uptrend from Jun 8 intact",
            "Higher-low structure in place",
        ]),
        ("Caution zones", "amber", [
            "Near Jun 18 high (24,189)",
            "Narrow range so far (64 pts)",
            "Only 2 candles available",
            "Gap-fill risk if momentum fades",
            "Broad market direction key",
        ]),
        ("Invalidation", "red", [
            "Break below 24,013 flips bias",
            "Jun 19 sell candle still fresh",
            "Volume confirmation needed",
            "Watch 24,189 as hard resistance",
        ]),
    ], styles))
    elems.append(spacer(10))

    # Bias
    elems.append(Paragraph("Intraday Bias", styles["sub_hdr"]))
    elems.append(Paragraph(
        "<b>Bias: Cautiously Bullish.</b> The gap-up open above a prior distribution area "
        "(23,900–24,013) is constructive. However, the index is within striking distance of the "
        "Jun 18 high of 24,189, which is a major supply zone. A breakout above 24,189 with "
        "expanding volume would be a strong bullish signal for continuation towards 24,400+. "
        "Failure there and a close below 24,013 would signal a gap-fill and shift bias bearish "
        "for the session.",
        styles["body"]
    ))

    # 20-day price trail
    elems.append(spacer(6))
    elems.append(Paragraph("20-Day Price Trail (Closing Prices)", styles["sub_hdr"]))
    trail = [
        ["Date", "Close", "Date", "Close", "Date", "Close"],
        ["22-May", "23,719", "04-Jun", "23,417", "15-Jun", "23,854"],
        ["25-May", "24,032", "05-Jun", "23,367", "16-Jun", "23,989"],
        ["26-May", "23,914", "08-Jun", "23,123", "17-Jun", "24,086"],
        ["27-May", "23,907", "09-Jun", "23,242", "18-Jun", "24,168"],
        ["29-May", "23,548", "10-Jun", "23,215", "19-Jun", "24,013"],
        ["01-Jun", "23,383", "11-Jun", "23,162", "22-Jun*", "24,121"],
        ["02-Jun", "23,484", "12-Jun", "23,623", "20-day SMA", "23,632"],
    ]
    t = data_table(trail[0], trail[1:],
                   [28*mm, 22*mm, 28*mm, 22*mm, 28*mm, 22*mm])
    elems.append(t)
    elems.append(Paragraph("* Partial session data", styles["note"]))
    return elems


def build_dixon(styles):
    elems = []
    elems += section_divider(styles, "2. Dixon Technologies (DIXON) — Positional Analysis")

    elems.append(Paragraph("Stock Snapshot", styles["sub_hdr"]))
    elems.append(metric_row([
        ("LTP",        "12,336",  "-1.4%"),
        ("Swing High", "12,930",  "Jun 18, 2026"),
        ("6M Low",     "9,630",   "Mar 9, 2026"),
        ("20-day SMA", "11,797",  "Price above"),
        ("RSI (14)",   "~62",     "Bullish zone"),
        ("Rally",      "+34%",    "From Mar low"),
    ], colcount=3))
    elems.append(spacer(10))

    elems.append(Paragraph("Price Story — 6 Months", styles["sub_hdr"]))
    phases = [
        ["Phase", "Period", "Price Range", "Description"],
        ["1 — Crash",       "Dec 2025 – Mar 2026",
         "14,566 → 9,630",
         "Dec 10 earnings shock triggered severe selling. Multiple failed bounces. -34% peak-to-trough."],
        ["2 — Base build",  "Mar – Apr 2026",
         "9,630 – 11,400",
         "Mar 10 reversal (+11%, 2.03M vol) marked the low. Choppy 9,600–11,400 range for 2 months."],
        ["3 — Recovery",    "May 13 – Jun 18, 2026",
         "10,100 → 12,930",
         "May 13 reversal (2.69M vol) triggered momentum. Jun 15-17 breakout above 12,000 on high volume."],
        ["4 — Pullback",    "Jun 18 – Jun 22, 2026",
         "12,930 → 12,336",
         "3-day healthy pullback (-4.6%) from swing high. Current low-volume correction is constructive."],
    ]
    t = data_table(phases[0], phases[1:],
                   [28*mm, 35*mm, 28*mm, 79*mm])
    elems.append(t)
    elems.append(spacer(10))

    elems.append(Paragraph("Key Levels", styles["sub_hdr"]))
    elems.append(levels_table([
        ("R", "R3 · Dec 2025 distribution zone",               "13,500+"),
        ("R", "R2 · Jun 18 swing high (30-day high)",          "12,930"),
        ("R", "R1 · Today's session high",                     "12,650"),
        ("N", "CMP (Last Traded Price)",                       "12,336"),
        ("S", "S1 · Today's low / Jun 19 close zone",         "12,262"),
        ("S", "S2 · 20-day SMA / Jun 15 breakout close",      "11,800–11,957"),
        ("S", "S3 · Breakout-retest zone (May–Jun base)",     "11,400–11,600"),
        ("S", "S4 · Major structural floor",                   "10,800–11,100"),
    ]))
    elems.append(spacer(10))

    elems.append(Paragraph("Positional Trade Setup", styles["sub_hdr"]))
    elems.append(trade_setup_table([
        ("Entry zone",  "12,000 – 12,300",    "Current zone or slight further pullback"),
        ("Stop loss",   "Below 11,600",        "Close basis — below Jun 9–12 consolidation"),
        ("Target 1",    "12,900",              "+4.6% from entry midpoint (12,150) — swing high"),
        ("Target 2",    "13,700",              "+11.1% — Dec 2025 distribution zone"),
        ("Risk",        "~550 pts (~4.5%)",    "From entry midpoint 12,150 to SL 11,600"),
        ("R:R",         "1:1.4 / 1:2.8",      "To Target 1 / Target 2 respectively"),
    ]))
    elems.append(spacer(10))

    elems.append(Paragraph("Technical Signals", styles["sub_hdr"]))
    elems.append(insight_table([
        ("Bullish signals", "green", [
            "+34% recovery from Mar 9 low intact",
            "Above 20-day SMA (price +539 pts)",
            "RSI ~62 — bullish momentum zone",
            "Jun 15–17 rally on high volume (1.7M)",
            "Higher-lows structure in place",
            "May 13 reversal candle held (2.69M vol)",
        ]),
        ("Neutral / watch", "amber", [
            "3-day pullback from 12,930",
            "Today gap-up open but fading",
            "Current volume ~503K below avg",
            "Dec 2025 highs (14,500+) far off",
            "Broader market direction key",
        ]),
        ("Risk factors", "red", [
            "Break below 11,600 = trend fail",
            "Multiple failed recoveries Jan–Mar",
            "High beta — intraday swings 5–8%",
            "Still -15% from Dec 2025 highs",
            "Earnings-related downside risk",
        ]),
    ], styles))
    elems.append(spacer(10))

    elems.append(Paragraph("Volume Analysis — Key Events", styles["sub_hdr"]))
    vol_tbl = [
        ["Date", "Volume", "Close", "Move", "Signal"],
        ["Dec 10, 2025",  "974K",    "12,351",  "-8.6%",  "Crash day — earnings shock"],
        ["Dec 29-30",     "1.3M ea", "11,767",  "-2.4%",  "Heavy institutional selling"],
        ["Mar 10, 2026",  "2.03M",   "10,908",  "+11%",   "Monster reversal — low confirmed"],
        ["May 13, 2026",  "2.69M",   "11,124",  "+9.7%",  "Second reversal — trend change"],
        ["Jun 16, 2026",  "1.09M",   "12,235",  "+2.4%",  "Breakout continuation"],
        ["Jun 17, 2026",  "1.69M",   "12,833",  "+4.9%",  "Strong institutional buying"],
    ]
    t = data_table(vol_tbl[0], vol_tbl[1:],
                   [28*mm, 20*mm, 20*mm, 18*mm, 84*mm])
    elems.append(t)
    elems.append(spacer(8))

    elems.append(Paragraph("Summary Verdict", styles["verdict_g"]))
    elems.append(Paragraph(
        "<b>Bullish — Dip-buy opportunity.</b> Dixon is in a clear intermediate uptrend from "
        "the Mar 9 low of 9,630. The current 3-day pullback from 12,930 (–4.6%) is "
        "low-volume and constructive. The 20-day SMA at 11,797 and the Jun 15 breakout zone "
        "(11,957) provide a strong demand area. Initiating a positional long in the 12,000–12,300 "
        "zone with a stop below 11,600 offers a favourable 1:1.4 to 1:2.8 risk-reward ratio. "
        "Watch for a volume-backed close above 12,930 as confirmation for the next leg to 13,500+.",
        styles["body"]
    ))
    return elems


def build_hcltech(styles):
    elems = []
    elems += section_divider(styles, "3. HCL Technologies (HCLTECH) — Positional Analysis")

    elems.append(Paragraph("Stock Snapshot", styles["sub_hdr"]))
    elems.append(metric_row([
        ("LTP",        "1,130.5",  "-0.1%"),
        ("6M High",    "1,729",    "Jan 28, 2026"),
        ("6M Low",     "1,089",    "Jun 11, 2026"),
        ("From High",  "-34.6%",   "5-month decline"),
        ("RSI (14)",   "~25",      "Deeply oversold"),
        ("vs 20-SMA",  "-26 pts",  "SMA = 1,157"),
    ], colcount=3))
    elems.append(spacer(10))

    elems.append(Paragraph("Price Story — 6 Months", styles["sub_hdr"]))
    phases = [
        ["Phase", "Period", "Price Range", "Description"],
        ["1 — Late peak",      "Dec 2025 – Jan 2026",
         "1,630 → 1,729",
         "Ranged 1,630–1,730. Hit 6M high of 1,729 on Jan 28. Looked range-bound but distributing."],
        ["2 — First leg down", "Feb 2026",
         "1,729 → 1,322",
         "Feb 4 results shock (-6%). Feb 12–13 crash on 7M+ vol. Feb 24 capitulation on 10M vol (close 1,339)."],
        ["3 — Dead-cat range", "Mar – Apr 21, 2026",
         "1,297 – 1,475",
         "Choppy stabilization for 7 weeks. Looked like a base but was just consolidation before the next fall."],
        ["4 — Earnings crash", "Apr 22, 2026",
         "1,441 → 1,285",
         "33.1M volume in a single day (-10.8%). Worst single-day sell event. New low regime started."],
        ["5 — Drift to lows",  "May 12 – Jun 11, 2026",
         "1,194 → 1,089",
         "Gradual bleed to 6M low of 1,089. May 29 high-vol up-close (12.4M) was only bright spot."],
        ["6 — Failed bounce",  "Jun 16 – Jun 22, 2026",
         "1,089 → 1,130",
         "Jun 16 bought on 8.3M vol (+3.6%) — promising. Jun 19 sold back on 10M vol (-2.6%). Now near lows."],
    ]
    t = data_table(phases[0], phases[1:],
                   [28*mm, 32*mm, 26*mm, 84*mm])
    elems.append(t)
    elems.append(spacer(10))

    elems.append(Paragraph("Key Institutional Volume Events", styles["sub_hdr"]))
    vol_tbl = [
        ["Date", "Volume", "Close", "Move", "Event / Signal"],
        ["Feb 24, 2026",  "10.0M",  "1,339",  "-6.1%",  "Capitulation — first major flush"],
        ["Apr 22, 2026",  "33.1M",  "1,285",  "-10.8%", "Earnings crash — defining event. Institutions fled."],
        ["Apr 24, 2026",  "10.9M",  "1,203",  "-6.2%",  "Follow-through selling after earnings"],
        ["May 29, 2026",  "12.4M",  "1,184",  "+1.6%",  "Accumulation signal? High-vol up-close near lows"],
        ["Jun 16, 2026",  "8.3M",   "1,159",  "+3.6%",  "Bounce attempt — buying came in"],
        ["Jun 19, 2026",  "10.0M",  "1,131",  "-2.6%",  "Bounce killed — sellers back in force"],
    ]
    t = data_table(vol_tbl[0], vol_tbl[1:],
                   [25*mm, 18*mm, 18*mm, 17*mm, 92*mm])
    elems.append(t)
    elems.append(spacer(10))

    elems.append(Paragraph("Key Levels", styles["sub_hdr"]))
    elems.append(levels_table([
        ("R", "R4 · Jan 28, 2026 cycle peak",                  "1,729"),
        ("R", "R3 · Jun 2 swing high / Apr 2026 zone",        "1,257"),
        ("R", "R2 · 20-day SMA (price below = bearish)",      "1,157"),
        ("R", "R1 · Jun 16–17 resistance zone",               "1,160–1,174"),
        ("N", "CMP (Last Traded Price)",                       "1,130.5"),
        ("S", "S1 · Today's session low",                     "1,127"),
        ("S", "S2 · Jun 11 multi-month low — key floor",      "1,089"),
        ("S", "S3 · Psychological / next support",            "1,000–1,050"),
    ]))
    elems.append(spacer(10))

    elems.append(Paragraph("Trade Setup Options", styles["sub_hdr"]))
    elems.append(trade_setup_table([
        ("Stance",      "AVOID fresh longs",        "Primary trend is down. Do not fight the tape."),
        ("Entry zone",  "1,090 – 1,130",            "Tactical oversold bounce only (not positional)"),
        ("Stop loss",   "Below 1,085",              "Below Jun 11 multi-month low"),
        ("Target 1",    "1,200 – 1,250",            "+6–11% — quick tactical bounce target"),
        ("Risk",        "~40–45 pts (~3.5%)",       "From entry midpoint to stop"),
        ("R:R",         "1:1.5 – 1:1.7 max",        "Poor R:R for a downtrend stock — use small size"),
    ]))
    elems.append(spacer(6))
    elems.append(Paragraph(
        "Reversal confirmation trigger: Buy only on a close ABOVE 1,260 on volume >5M. "
        "This would break the lower-highs pattern and confirm a trend change. "
        "Target 1,350–1,400 on a confirmed reversal trade.",
        styles["body_sm"]
    ))
    elems.append(spacer(10))

    elems.append(Paragraph("Technical Signals", styles["sub_hdr"]))
    elems.append(insight_table([
        ("Potential positives", "green", [
            "RSI ~25 = deeply oversold",
            "Jun 11 low (1,089) holding so far",
            "May 29 high-vol up-close (12.4M)",
            "Possible double-bottom forming",
            "IT sector relative defensiveness",
        ]),
        ("Concerns", "amber", [
            "Below 20-day SMA (price –26 pts)",
            "Below 50-day SMA (est. ~1,350)",
            "Jun 16 bounce fully reversed",
            "Jun 19 heavy selling on 10M vol",
            "No confirmed base formed yet",
        ]),
        ("Red flags", "red", [
            "Apr 22 earnings crash (33M vol)",
            "-34.6% from Jan 28 peak",
            "Every rally sold into heavily",
            "Lower highs + lower lows intact",
            "Break of 1,089 targets 1,000",
        ]),
    ], styles))
    elems.append(spacer(10))

    elems.append(Paragraph("Summary Verdict", styles["verdict_r"]))
    elems.append(Paragraph(
        "<b>Bearish — Avoid positional longs.</b> HCLTECH is in a confirmed primary downtrend, "
        "down 34.6% from its Jan 2026 peak. The Apr 22 earnings crash on 33M volume was the "
        "defining institutional exit event, and every subsequent bounce has been sold into "
        "with high volume (Jun 16 bounce reversed on Jun 19 at 10M volume). While RSI at ~25 "
        "signals extreme oversold conditions and a tactical bounce is possible near the Jun 11 "
        "low of 1,089, this is NOT a positional long setup. Wait for a confirmed close above "
        "1,260 on strong volume before considering a positional entry. Until then, stay on the "
        "sidelines or use only small size for the tactical bounce.",
        styles["body"]
    ))
    return elems


def build_summary(styles):
    elems = []
    elems += section_divider(styles, "4. Comparative Summary")

    rows = [
        ["Instrument", "CMP", "Trend",     "RSI", "Stance",         "Key Level"],
        ["NIFTY 50",   "24,124","Uptrend",  "~62", "Bullish / Hold", "S: 24,013 | R: 24,189"],
        ["DIXON",      "12,336","Uptrend",  "~62", "BUY dip",        "Entry 12,000–12,300 | SL 11,600"],
        ["HCLTECH",    "1,130", "Downtrend","~25", "AVOID / Watch",  "Wait for close > 1,260"],
    ]
    t = data_table(rows[0], rows[1:],
                   [30*mm, 18*mm, 22*mm, 14*mm, 28*mm, 58*mm])
    elems.append(t)
    elems.append(spacer(10))
    elems.append(Paragraph(
        "All prices and analysis are based on data available during the morning session of "
        "22 June 2026. This document is for educational reference only and does not "
        "constitute financial or investment advice.",
        styles["note"]
    ))
    return elems


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    doc = SimpleDocTemplate(
        OUTPUT,
        pagesize=A4,
        topMargin=18*mm, bottomMargin=18*mm,
        leftMargin=20*mm, rightMargin=20*mm,
        title="Trading Analysis Report — 22 Jun 2026",
        author="OpenAlgo MCP",
        subject="Intraday & Positional Analysis"
    )

    styles = build_styles()
    story = []
    story += build_cover(styles)
    story += build_nifty(styles)
    story += build_dixon(styles)
    story += build_hcltech(styles)
    story += build_summary(styles)

    doc.build(story)
    print(f"PDF saved: {OUTPUT}")

if __name__ == "__main__":
    main()
