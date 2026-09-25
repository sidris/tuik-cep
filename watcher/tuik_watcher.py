#!/usr/bin/env python3
"""TÜİK Cep — TÜİK haber bültenlerini izler, Gemini ile özetler, telefona push gönderir.

Kullanım:
  python watcher/tuik_watcher.py once                      # tek kontrol
  python watcher/tuik_watcher.py burst --until-utc 07:30   # belirtilen saate kadar sık kontrol
  python watcher/tuik_watcher.py test-push                 # feed'deki son bülteni tekrar bildirim olarak gönder
  python watcher/tuik_watcher.py summarize --id 58177      # tek bülteni özetle, ekrana yaz (push yok)

Ortam değişkenleri:
  GEMINI_API_KEY            Gemini anahtarı (yoksa AI özeti atlanır, TÜİK manşeti gönderilir)
  GEMINI_MODEL              varsayılan: gemini-3.8-flash
  GEMINI_FALLBACK_MODEL     varsayılan: gemini-3.5-flash-lite
  EXPO_PUSH_TOKENS          virgülle ayrılmış ExponentPushToken[...] listesi
  GIT_COMMIT=1              data/ değişince commit + push yap (GitHub Actions'ta)
  DRY_RUN=1                 push gönderme, dosya yazma
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE_PATH = DATA / "state.json"
FEED_PATH = DATA / "feed.json"
WATCHLIST_PATH = ROOT / "watcher" / "watchlist.json"

BASE = "https://veriportali.tuik.gov.tr"
LATEST_URL = f"{BASE}/api/tr/press/latest"
PRESS_URL = f"{BASE}/api/tr/press/{{id}}"
PUBLIC_URL = f"{BASE}/tr/press/{{id}}"

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

FEED_MAX = 150
SEEN_MAX = 1000
MAX_PENDING_ATTEMPTS = 6
TR_TZ = dt.timezone(dt.timedelta(hours=3))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (TUIK-Cep kisisel bildirim; +https://github.com)",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE}/tr",
})


def log(*a: Any) -> None:
    print(dt.datetime.now(TR_TZ).strftime("%H:%M:%S"), *a, flush=True)


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "evet"}


# ---------------------------------------------------------------- TÜİK API

def get_json(url: str, attempts: int = 4) -> dict:
    """TÜİK API bazen ilk istekte 404 'Sayfa bulunamadı' döndürüyor; birkaç kez dene."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            r = SESSION.get(url, timeout=20)
            if r.status_code == 200:
                j = r.json()
                if j.get("isError"):
                    raise RuntimeError(f"TÜİK hata: {j.get('message')}")
                return j
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.0 + i * 1.5)
    raise RuntimeError(f"{url} alınamadı: {last}")


def press_id_from_url(url: str) -> int | None:
    m = re.fullmatch(r"/tr/press/(\d+)", url or "")
    return int(m.group(1)) if m else None


def fetch_latest() -> list[dict]:
    items = get_json(LATEST_URL)["data"]
    out = []
    for it in items:
        pid = press_id_from_url(it.get("url", ""))
        if it.get("typeId") == 1 and pid:
            out.append({
                "id": pid,
                "title": it.get("name", "").strip(),
                "period": it.get("period", "").strip(),
                "date": it.get("date"),
            })
    return out


def fetch_press(pid: int) -> dict:
    return get_json(PRESS_URL.format(id=pid))["data"]


# ---------------------------------------------------------------- metin işleme

def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def html_to_text(content: str) -> str:
    soup = BeautifulSoup(content or "", "lxml")
    for g in soup.select(".grafik"):
        g.decompose()
    for table in soup.find_all("table"):
        lines = []
        for tr in table.find_all("tr"):
            cells = [" ".join(c.get_text(" ", strip=True).split()) for c in tr.find_all(["th", "td"])]
            if any(cells):
                lines.append(" | ".join(cells))
        table.replace_with(NavigableString("\n[TABLO]\n" + "\n".join(lines) + "\n[/TABLO]\n"))
    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))
    text = html.unescape(soup.get_text())
    lines = [" ".join(l.split()) for l in text.splitlines()]
    lines = [l for l in lines if not re.fullmatch(r"_{5,}", l)]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_headline(content: str, title: str, period: str) -> str:
    """TÜİK bültenlerinde 2. kalın satır genelde ana bulgu cümlesidir."""
    soup = BeautifulSoup(content or "", "lxml")
    t_low, p_low = tr_lower(title), tr_lower(period)
    for s in soup.find_all(["strong", "b"]):
        txt = " ".join(s.get_text(" ", strip=True).split())
        low = tr_lower(txt)
        if len(txt) < 12:
            continue
        if p_low and p_low in low and low.startswith(t_low[:15]) and len(txt) <= len(title) + len(period) + 6:
            continue  # "Başlık, Dönem" satırı
        if s.find_parent("table"):
            continue
        return txt
    return ""


def extract_next_release(text: str) -> str | None:
    m = re.search(r"bir sonraki haber bülteninin yayımlanma tarihi\s*:\s*([^\n]+)", text, re.I)
    return m.group(1).strip() if m else None


NUM_RE = re.compile(r"[-−–+]?\d+(?:[.,]\d+)*")


def canon_num(tok: str) -> str:
    return re.sub(r"\D", "", tok).lstrip("0") or "0"


def numbers_in(text: str) -> set[str]:
    return {canon_num(t) for t in NUM_RE.findall(text or "")}


# ---------------------------------------------------------------- Gemini

PROMPT = """Sen Türkiye ekonomisini izleyen bir analist için TÜİK haber bültenlerini özetleyen bir asistansın.
Aşağıdaki TÜİK bülteni metnine DAYANARAK kısa bir Türkçe özet hazırla.

Kurallar:
- YALNIZCA verilen metindeki bilgileri kullan. Metinde olmayan rakam, yorum, tahmin veya neden ekleme.
- Rakamları metinde yazdığı gibi, virgüllü Türkçe biçimde aynen aktar (ör. %31,51). Yuvarlama yapma.
- "Önceki bülten" bölümü verilmişse, yalnızca oradaki rakamlarla kıyas yap; yoksa kıyası metnin kendisinden yap.
- Kısa, net, haber ajansı dili kullan.

Şu JSON nesnesini döndür:
{{
  "baslik": "bildirim satırı, en fazla 110 karakter, en önemli rakamı içersin",
  "ozet": "2-4 cümlelik özet",
  "one_cikanlar": ["en fazla 4 kısa madde"],
  "rakamlar": [{{"etiket": "kısa ad", "deger": "metindeki değer", "degisim": "varsa değişim, yoksa boş"}}]
}}
"rakamlar" en fazla 6 öğe olsun.

=== BÜLTEN: {title} — {period} ===
{text}
{prev}"""


def gemini_summarize(title: str, period: str, text: str, prev_text: str | None) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        log("GEMINI_API_KEY yok, AI özeti atlanıyor")
        return None
    prev = f"\n=== ÖNCEKİ BÜLTEN (kıyas için, kısaltılmış) ===\n{prev_text[:2500]}" if prev_text else ""
    prompt = PROMPT.format(title=title, period=period, text=text[:28000], prev=prev)
    models = [os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash",
              os.environ.get("GEMINI_FALLBACK_MODEL") or "gemini-3.5-flash-lite"]
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    for model in models:
        for attempt in range(2):
            try:
                r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=45,
                                  headers={"x-goog-api-key": key})
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
                parts = r.json()["candidates"][0]["content"]["parts"]
                raw = "".join(p.get("text", "") for p in parts)
                raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
                data = json.loads(raw)
                data["model"] = model
                return data
            except Exception as e:  # noqa: BLE001
                log(f"Gemini ({model}) hata: {e}")
                time.sleep(2)
    return None


def verify_ai(ai: dict, source_text: str) -> dict:
    """AI'ın yazdığı rakamları kaynak metinle karşılaştır; metinde geçmeyenleri ele / işaretle."""
    src = numbers_in(source_text)
    clean_figs = []
    for f in ai.get("rakamlar") or []:
        if not isinstance(f, dict):
            continue
        toks = numbers_in(f"{f.get('deger', '')} {f.get('degisim', '')}")
        if toks and toks <= src:
            clean_figs.append({k: str(f.get(k, "") or "") for k in ("etiket", "deger", "degisim")})
    ai["rakamlar"] = clean_figs[:6]
    ai["one_cikanlar"] = [str(x) for x in (ai.get("one_cikanlar") or [])][:4]
    for k in ("baslik", "ozet"):
        ai[k] = str(ai.get(k) or "").strip()
    free_text = " ".join([ai["baslik"], ai["ozet"], *ai["one_cikanlar"]])
    unverified = sorted(numbers_in(free_text) - src)
    ai["dogrulanamayan"] = unverified
    return ai


# ---------------------------------------------------------------- push

def send_push(title: str, body: str, data: dict) -> None:
    tokens = [t.strip() for t in os.environ.get("EXPO_PUSH_TOKENS", "").split(",") if t.strip()]
    if not tokens:
        log("EXPO_PUSH_TOKENS yok, push atlanıyor")
        return
    if env_flag("DRY_RUN"):
        log(f"[DRY_RUN] push: {title} — {body}")
        return
    msgs = [{
        "to": t, "title": title, "body": body[:230], "data": data,
        "sound": "default", "priority": "high", "channelId": "tuik",
    } for t in tokens]
    try:
        r = requests.post(EXPO_PUSH_URL, json=msgs, timeout=20,
                          headers={"Accept": "application/json", "Content-Type": "application/json"})
        log("push yanıtı:", r.status_code, r.text[:400])
    except Exception as e:  # noqa: BLE001
        log("push hatası:", e)


# ---------------------------------------------------------------- durum / feed

def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: Path, obj: Any) -> None:
    if env_flag("DRY_RUN"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_watchlist() -> dict:
    return load_json(WATCHLIST_PATH, {"hepsi": True, "anahtar_kelimeler": [], "haric": []})


def is_watched(title: str, wl: dict) -> bool:
    low = tr_lower(title)
    if any(tr_lower(x) in low for x in wl.get("haric", [])):
        return False
    if wl.get("hepsi"):
        return True
    return any(tr_lower(k) in low for k in wl.get("anahtar_kelimeler", []))


def git_commit(message: str) -> None:
    if not env_flag("GIT_COMMIT") or env_flag("DRY_RUN"):
        return
    def run(*cmd: str) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    run("git", "add", "data")
    if run("git", "diff", "--cached", "--quiet").returncode == 0:
        return
    run("git", "commit", "-m", message)
    for _ in range(3):
        run("git", "pull", "--rebase", "-X", "theirs")
        p = run("git", "push")
        if p.returncode == 0:
            log("git push tamam")
            return
        time.sleep(3)
    log("git push başarısız:", p.stderr[-300:])


# ---------------------------------------------------------------- ana akış

def build_item(meta: dict, with_ai: bool = True) -> dict:
    pid = meta["id"]
    press = fetch_press(pid)
    title = press.get("title") or meta.get("title", "")
    period = press.get("period") or meta.get("period", "")
    content = press.get("content", "")
    text = html_to_text(content)
    headline = extract_headline(content, title, period)

    prev_text = None
    prev = (press.get("previousPresses") or [])
    if with_ai and prev:
        ppid = press_id_from_url(prev[0].get("url", ""))
        if ppid:
            try:
                prev_text = html_to_text(fetch_press(ppid).get("content", ""))
            except Exception as e:  # noqa: BLE001
                log("önceki bülten alınamadı:", e)

    ai = gemini_summarize(title, period, text, prev_text) if with_ai else None
    if ai:
        ai = verify_ai(ai, text + "\n" + (prev_text or ""))

    return {
        "id": pid,
        "title": title,
        "period": period,
        "date": press.get("date") or meta.get("date"),
        "url": PUBLIC_URL.format(id=pid),
        "headline": headline,
        "next_release": extract_next_release(text),
        "ai": ai,
        "detected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def notify(item: dict) -> None:
    short = item["title"]
    title = f"TÜİK • {short} — {item['period']}"
    ai = item.get("ai") or {}
    body = ai.get("baslik") or item.get("headline") or "Yeni bülten yayımlandı"
    send_push(title, body, {"id": item["id"], "url": item["url"]})


def upsert_feed(feed: list[dict], item: dict) -> list[dict]:
    feed = [x for x in feed if x["id"] != item["id"]]
    feed.insert(0, item)
    feed.sort(key=lambda x: (x.get("date") or "", x["id"]), reverse=True)
    return feed[:FEED_MAX]


def check_once(backfill: int = 5) -> int:
    """Bir kez kontrol et. Yeni (izlenen) bülten sayısını döndürür."""
    state = load_json(STATE_PATH, {"seen": [], "pending": {}})
    feed = load_json(FEED_PATH, [])
    wl = load_watchlist()
    latest = fetch_latest()
    seen = set(state.get("seen", []))
    pending: dict[str, int] = state.get("pending", {})

    # İlk çalıştırma: geçmişi bildirim olarak yağdırma; yalnızca son birkaçını sessizce feed'e koy.
    if not seen:
        log(f"ilk çalıştırma: {len(latest)} bülten görüldü olarak işaretleniyor")
        state["seen"] = [x["id"] for x in latest]
        state["initialized_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        for meta in [m for m in latest if is_watched(m["title"], wl)][:backfill]:
            try:
                feed = upsert_feed(feed, build_item(meta))
                log("feed'e eklendi:", meta["title"])
            except Exception as e:  # noqa: BLE001
                log("backfill hatası:", meta["id"], e)
        save_json(STATE_PATH, state)
        save_json(FEED_PATH, feed)
        git_commit("TÜİK Cep: ilk kurulum")
        return 0

    new = [m for m in latest if m["id"] not in seen]
    count = 0
    for meta in new:
        if not is_watched(meta["title"], wl):
            seen.add(meta["id"])
            log("izlenmiyor, atlandı:", meta["title"])
            continue
        log("YENİ:", meta["title"], meta["period"])
        try:
            item = build_item(meta)
        except Exception as e:  # noqa: BLE001
            n = pending.get(str(meta["id"]), 0) + 1
            pending[str(meta["id"])] = n
            log(f"bülten alınamadı ({n}/{MAX_PENDING_ATTEMPTS}):", e)
            if n < MAX_PENDING_ATTEMPTS:
                continue
            item = {"id": meta["id"], "title": meta["title"], "period": meta["period"], "date": meta["date"],
                    "url": PUBLIC_URL.format(id=meta["id"]), "headline": "", "next_release": None, "ai": None,
                    "detected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        notify(item)
        feed = upsert_feed(feed, item)
        seen.add(meta["id"])
        pending.pop(str(meta["id"]), None)
        count += 1

    if new:
        state["seen"] = sorted(seen, reverse=True)[:SEEN_MAX]
        state["pending"] = pending
        save_json(STATE_PATH, state)
        save_json(FEED_PATH, feed)
        titles = ", ".join(m["title"] for m in new)[:150]
        git_commit(f"TÜİK Cep: {titles}")
    return count


def burst(until_utc: str, interval: int) -> None:
    hh, mm = map(int, until_utc.split(":"))
    now = dt.datetime.now(dt.timezone.utc)
    end = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if end <= now:
        log("bitiş saati geçmiş; tek kontrol yapılıyor")
        end = now
    log(f"yoğun izleme {end:%H:%M} UTC'ye kadar, {interval} sn aralıkla")
    while True:
        try:
            check_once()
        except Exception as e:  # noqa: BLE001
            log("kontrol hatası:", e)
        if dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=interval) > end:
            break
        time.sleep(interval)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    b = sub.add_parser("burst")
    b.add_argument("--until-utc", required=True)
    b.add_argument("--interval", type=int, default=15)
    tp = sub.add_parser("test-push")
    tp.add_argument("--id", type=int)
    s = sub.add_parser("summarize")
    s.add_argument("--id", type=int, required=True)
    args = ap.parse_args()

    if args.cmd == "once":
        check_once()
    elif args.cmd == "burst":
        burst(args.until_utc, args.interval)
    elif args.cmd == "summarize":
        print(json.dumps(build_item({"id": args.id}), ensure_ascii=False, indent=2))
    elif args.cmd == "test-push":
        feed = load_json(FEED_PATH, [])
        if args.id:
            item = build_item({"id": args.id})
            feed = upsert_feed(feed, item)
            save_json(FEED_PATH, feed)
            git_commit(f"TÜİK Cep: test {item['title']}")
        elif feed:
            item = feed[0]
        else:
            sys.exit("feed boş; --id ile bir bülten numarası ver")
        notify(item)


if __name__ == "__main__":
    main()
