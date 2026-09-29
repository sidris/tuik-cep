"""TÜİK Cep — bültenlerden grafik serileri ve yayın takvimi çıkarma."""
from __future__ import annotations

import ast
import datetime as dt
import html
import re
from typing import Any

from bs4 import BeautifulSoup

MAX_POINTS = 24
MAX_SERIES = 3
MAX_CHARTS = 2
CHART_TYPES = {"line", "bar", "column", "area", "verticalbar"}

AYLAR = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9, "ekim": 10, "kasım": 11,
    "kasim": 11, "aralık": 12, "aralik": 12,
}


# ---------------------------------------------------------------- grafikler

def _parse_options(raw: str) -> dict | None:
    """TÜİK grafik ayarları tek tırnaklı JS nesnesi; Python literal'ine çevirip oku."""
    s = html.unescape(raw or "").strip()
    if not s.startswith("{"):
        return None
    s = re.sub(r"\bnull\b", "None", s)
    s = re.sub(r"\btrue\b", "True", s)
    s = re.sub(r"\bfalse\b", "False", s)
    try:
        v = ast.literal_eval(s)
    except Exception:  # noqa: BLE001
        return None
    return v if isinstance(v, dict) else None


def _num(x: Any) -> float | None:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return round(float(x), 2)
    if isinstance(x, str):
        try:
            return round(float(x.replace(".", "").replace(",", ".")), 2)
        except ValueError:
            return None
    return None


def extract_charts(content: str) -> list[dict]:
    soup = BeautifulSoup(content or "", "lxml")
    charts: list[dict] = []
    for g in soup.select(".grafik"):
        opt = _parse_options(g.get("data-options", ""))
        if not opt:
            continue
        ctype = str(opt.get("type") or "").lower()
        labels = [str(x) for x in (opt.get("labels") or [])]
        if ctype not in CHART_TYPES or len(labels) < 4:
            continue
        series = []
        for d in opt.get("data") or []:
            if not isinstance(d, dict):
                continue
            vals = [_num(v) for v in (d.get("data") or [])]
            if len(vals) != len(labels) or sum(v is not None for v in vals) < 4:
                continue
            series.append({"label": str(d.get("label") or ""), "data": vals[-MAX_POINTS:]})
            if len(series) >= MAX_SERIES:
                break
        if not series:
            continue
        charts.append({
            "title": str(opt.get("name") or ""),
            "type": "bar" if ctype in {"bar", "column", "verticalbar"} else "line",
            "labels": labels[-MAX_POINTS:],
            "series": series,
        })
        if len(charts) >= MAX_CHARTS:
            break
    return charts


# ---------------------------------------------------------------- takvim

def parse_tr_date(s: str | None) -> str | None:
    """'05 Ekim 2026' -> '2026-10-05'."""
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})", s)
    if not m:
        return None
    ay = AYLAR.get(m.group(2).replace("I", "ı").replace("İ", "i").lower())
    if not ay:
        return None
    try:
        return dt.date(int(m.group(3)), ay, int(m.group(1))).isoformat()
    except ValueError:
        return None


def update_calendar(calendar: list[dict], title: str, next_release: str | None, source_id: int | None,
                    today: dt.date | None = None) -> list[dict]:
    """Bir bültenin sonraki yayım tarihini takvime işle; geçmiş tarihleri temizle."""
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()
    iso = parse_tr_date(next_release)
    cal = [c for c in calendar if c.get("title") != title] if iso else list(calendar)
    if iso:
        cal.append({"title": title, "date": iso, "source_id": source_id})
    cal = [c for c in cal if c.get("date") and c["date"] >= today.isoformat()]
    cal.sort(key=lambda c: (c["date"], c["title"]))
    return cal
