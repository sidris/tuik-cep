"""TÜİK Cep — Telegram kanalına özet mesajı + tek sayfalık PDF gönderir.

Ortam değişkenleri:
  TELEGRAM_BOT_TOKEN   @BotFather'dan alınan bot anahtarı (GitHub secret)
  TELEGRAM_CHAT_ID     (isteğe bağlı) kanal/grup kimliği. Boşsa bot'un eklendiği kanal
                       getUpdates ile otomatik bulunur ve data/state.json'a kaydedilir.
"""
from __future__ import annotations

import datetime as dt
import html
import io
import os
import re
from pathlib import Path
from typing import Any

import requests

API = "https://api.telegram.org/bot{token}/{method}"
TR_TZ = dt.timezone(dt.timedelta(hours=3))

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
    str(Path(__file__).parent / "fonts"),
]


def _log(*a: Any) -> None:
    print(dt.datetime.now(TR_TZ).strftime("%H:%M:%S"), "[telegram]", *a, flush=True)


def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _call(method: str, **kw) -> dict:
    r = requests.post(API.format(token=_token(), method=method), timeout=30, **kw)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"{method}: {j.get('description')}")
    return j["result"]


# ---------------------------------------------------------------- sohbet kimliği

def resolve_chat_id(state: dict) -> str | None:
    """Önce ortam değişkeni, sonra state, en son getUpdates ile keşif."""
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or str(state.get("telegram_chat_id") or "")
    if cid:
        return cid
    try:
        updates = _call("getUpdates", json={"allowed_updates": ["my_chat_member", "channel_post", "message"]})
    except Exception as e:  # noqa: BLE001
        _log("getUpdates hatası:", e)
        return None
    chats: list[dict] = []
    for u in updates:
        for key in ("my_chat_member", "channel_post", "message"):
            ch = (u.get(key) or {}).get("chat")
            if ch:
                chats.append(ch)
    # Kanal > grup > özel sohbet önceliği; en son görüleni al
    for kind in ("channel", "supergroup", "group", "private"):
        found = [c for c in chats if c.get("type") == kind]
        if found:
            c = found[-1]
            state["telegram_chat_id"] = str(c["id"])
            _log(f"sohbet bulundu: {c.get('title') or c.get('username') or c['id']} ({kind})")
            return str(c["id"])
    _log("bot henüz bir kanala/gruba eklenmemiş (getUpdates boş)")
    return None


# ---------------------------------------------------------------- mesaj

def _e(s: Any) -> str:
    return html.escape(str(s or ""), quote=False)


def format_message(item: dict) -> str:
    ai = item.get("ai") or {}
    lines = [f"<b>TÜİK • {_e(item['title'])} — {_e(item['period'])}</b>"]
    if item.get("headline"):
        lines.append(f"<i>{_e(item['headline'])}</i>")
    if ai.get("ozet"):
        lines += ["", _e(ai["ozet"])]
    if ai.get("one_cikanlar"):
        lines.append("")
        lines += [f"• {_e(b)}" for b in ai["one_cikanlar"]]
    if ai.get("rakamlar"):
        lines += ["", "<b>Temel rakamlar</b>"]
        for f in ai["rakamlar"]:
            ch = f" ({_e(f['degisim'])})" if f.get("degisim") else ""
            lines.append(f"{_e(f['etiket'])}: <b>{_e(f['deger'])}</b>{ch}")
    if ai.get("dogrulanamayan"):
        lines += ["", "⚠ Özetteki bazı rakamlar bülten metninde birebir bulunamadı."]
    tail = [f'<a href="{_e(item["url"])}">TÜİK bülteni</a>']
    if item.get("next_release"):
        tail.append(f"Sonraki yayım: {_e(item['next_release'])}")
    lines += ["", " · ".join(tail)]
    if ai:
        lines.append(f"<i>Özet yapay zekâ ({_e(ai.get('model') or 'Gemini')}) ile hazırlanmıştır.</i>")
    text = "\n".join(lines)
    return text[:4000]


# ---------------------------------------------------------------- PDF

def _fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for d in FONT_DIRS:
        reg, bold = Path(d) / "DejaVuSans.ttf", Path(d) / "DejaVuSans-Bold.ttf"
        if reg.exists() and bold.exists():
            if "TC" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("TC", str(reg)))
                pdfmetrics.registerFont(TTFont("TC-B", str(bold)))
            return "TC", "TC-B"
    _log("DejaVu fontu bulunamadı; Türkçe karakterler bozuk görünebilir")
    return "Helvetica", "Helvetica-Bold"


def _fmt_date(iso: str | None) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", iso or "")
    return f"{m[3]}.{m[2]}.{m[1]} {m[4]}:{m[5]}" if m else (iso or "")


def build_pdf(item: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    reg, bold = _fonts()
    RED, INK, MUTED, LINE = colors.HexColor("#C8102E"), colors.HexColor("#16181D"), colors.HexColor("#6B6F78"), colors.HexColor("#E4E2DD")
    st = lambda name, **kw: ParagraphStyle(name, fontName=kw.pop("font", reg), textColor=kw.pop("color", INK), **kw)  # noqa: E731
    s_brand = st("brand", font=bold, fontSize=9, color=RED, leading=12)
    s_kick = st("kick", font=bold, fontSize=8.5, color=RED, leading=11, spaceBefore=4)
    s_h1 = st("h1", font=bold, fontSize=18, leading=23, spaceBefore=2, spaceAfter=10)
    s_head = st("head", font=bold, fontSize=11.5, leading=16)
    s_h2 = st("h2", font=bold, fontSize=8.5, color=MUTED, leading=11, spaceBefore=14, spaceAfter=4)
    s_body = st("body", fontSize=10.5, leading=15.5)
    s_small = st("small", fontSize=8, color=MUTED, leading=11)
    s_cell = st("cell", fontSize=10, leading=13)
    s_num = st("num", font=bold, fontSize=10, leading=13, alignment=2)
    s_chg = st("chg", fontSize=9.5, color=MUTED, leading=13, alignment=2)
    e = _e
    ai = item.get("ai") or {}

    story: list = []
    now = dt.datetime.now(TR_TZ).strftime("%d.%m.%Y %H:%M")
    brand = Table([[Paragraph("TÜİK BÜLTEN ÖZETİ", s_brand), Paragraph(now, st("r", fontSize=8, color=MUTED, alignment=2))]],
                  colWidths=["70%", "30%"])
    brand.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 1.5, RED), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [brand, Spacer(1, 10)]
    kicker = e(item.get("period", "")).upper() + (f" · {_fmt_date(item.get('date'))}" if item.get("date") else "")
    story += [Paragraph(kicker, s_kick), Paragraph(e(item["title"]), s_h1)]

    if item.get("headline"):
        hb = Table([[Paragraph("TÜİK manşeti", s_small)], [Paragraph(e(item["headline"]), s_head)]], colWidths=["100%"])
        hb.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, -1), 2.5, RED), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story += [hb, Spacer(1, 4)]

    if ai:
        story += [Paragraph("ÖZET", s_h2), Paragraph(e(ai.get("ozet")), s_body)]
        if ai.get("one_cikanlar"):
            story.append(Paragraph("ÖNE ÇIKANLAR", s_h2))
            story.append(ListFlowable([ListItem(Paragraph(e(b), s_body), leftIndent=12, value="•") for b in ai["one_cikanlar"]],
                                      bulletType="bullet", start="•", leftIndent=12, bulletColor=RED))
        if ai.get("rakamlar"):
            story.append(Paragraph("TEMEL RAKAMLAR", s_h2))
            rows = [[Paragraph(e(f["etiket"]), s_cell), Paragraph(e(f["deger"]), s_num), Paragraph(e(f.get("degisim")), s_chg)]
                    for f in ai["rakamlar"]]
            t = Table(rows, colWidths=["50%", "18%", "32%"])
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
            story.append(t)
        if ai.get("dogrulanamayan"):
            story.append(Paragraph("Not: Özetteki bazı rakamlar bülten metninde birebir bulunamadı; kesin değerler için TÜİK bültenine bakınız.",
                                   st("w", fontSize=9, color=colors.HexColor("#9A5B00"), leading=12, spaceBefore=8)))
    else:
        story.append(Paragraph("Bu bülten için özet bulunmuyor.", s_body))

    story.append(Spacer(1, 14))
    if item.get("next_release"):
        story.append(Paragraph(f"<font name='{bold}'>Sonraki yayım:</font> {e(item['next_release'])}", s_body))
    story.append(Paragraph(f"<font name='{bold}'>Kaynak:</font> <link href='{e(item['url'])}' color='#C8102E'>{e(item['url'])}</link>", s_body))
    story.append(Spacer(1, 16))
    foot = Table([[Paragraph(
        f"Bu özet, TÜİK haber bülteni metninden yapay zekâ ({e(ai.get('model') or 'Gemini')}) ile otomatik olarak hazırlanmıştır. "
        "Rakamlar bülten metniyle otomatik karşılaştırılmıştır; resmî ve kesin veriler için yukarıdaki TÜİK bültenine başvurunuz.", s_small)]],
        colWidths=["100%"])
    foot.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.5, LINE), ("TOPPADDING", (0, 0), (-1, -1), 6),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(foot)

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                      title=f"{item['title']} — {item['period']}", author="TÜİK Cep").build(story)
    return buf.getvalue()


def pdf_filename(item: dict) -> str:
    tr = str.maketrans("çğıİöşüÇĞÖŞÜ", "cgiIosuCGOSU")
    base = f"TUIK_{item['title']}_{item['period']}".translate(tr)
    return re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")[:90] + ".pdf"


# ---------------------------------------------------------------- gönder

def send_item(item: dict, state: dict) -> bool:
    if not _token():
        _log("TELEGRAM_BOT_TOKEN yok, atlanıyor")
        return False
    chat = resolve_chat_id(state)
    if not chat:
        return False
    try:
        _call("sendMessage", json={"chat_id": chat, "text": format_message(item), "parse_mode": "HTML",
                                   "link_preview_options": {"is_disabled": True}})
        pdf = build_pdf(item)
        _call("sendDocument", data={"chat_id": chat, "caption": f"{item['title']} — {item['period']} (PDF)"},
              files={"document": (pdf_filename(item), pdf, "application/pdf")})
        _log("gönderildi:", item["title"])
        return True
    except Exception as ex:  # noqa: BLE001
        _log("gönderim hatası:", ex)
        return False
