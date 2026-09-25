import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tuik_watcher as w  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(w, "FEED_PATH", tmp_path / "feed.json")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    pushes = []
    monkeypatch.setattr(w, "send_push", lambda t, b, d: pushes.append((t, b, d)))
    latest = fx("latest.json")
    press = fx("press_58177.json")

    def fake_get(url, attempts=4):
        if url.endswith("/latest"):
            return latest
        return press
    monkeypatch.setattr(w, "get_json", fake_get)
    return latest, pushes


def test_text_and_headline():
    d = fx("press_58177.json")["data"]
    text = w.html_to_text(d["content"])
    assert "Yükleniyor" not in text
    assert "Tüketici güven endeksi | 90,8 | 91,9 | 1,0 | 1,3" in text
    assert w.extract_headline(d["content"], d["title"], d["period"]) == "Tüketici güven endeksi 91,9 oldu"
    assert w.extract_next_release(text) == "22 Ekim 2026"


def test_verify_ai_drops_invented_numbers():
    text = w.html_to_text(fx("press_58177.json")["data"]["content"])
    ai = {"baslik": "Tüketici güveni %1,3 artışla 91,9", "ozet": "Endeks 95,5 oldu.",
          "one_cikanlar": ["x"],
          "rakamlar": [{"etiket": "Endeks", "deger": "91,9", "degisim": "%1,3"},
                       {"etiket": "Uydurma", "deger": "77,7", "degisim": ""}]}
    out = w.verify_ai(ai, text)
    assert [f["etiket"] for f in out["rakamlar"]] == ["Endeks"]
    assert out["dogrulanamayan"] == ["955"]


def test_watchlist():
    wl = w.load_watchlist()
    assert w.is_watched("Tüketici Güven Endeksi", wl)
    assert w.is_watched("Tüketici Fiyat Endeksi", wl)
    assert w.is_watched("İşgücü İstatistikleri", wl)
    assert not w.is_watched("Hayvancılık İstatistikleri", wl)


def test_first_run_seeds_without_push_then_detects_new(env):
    latest, pushes = env
    assert w.check_once(backfill=2) == 0
    assert pushes == []
    feed = json.loads(w.FEED_PATH.read_text(encoding="utf-8"))
    assert len(feed) == 2
    # yeni bülten gelsin
    latest["data"].insert(0, {"name": "Tüketici Güven Endeksi", "period": "Ekim 2026",
                              "url": "/tr/press/59999", "date": "2026-10-22T10:00:00",
                              "type": "Haber Bülteni", "typeId": 1})
    latest["data"].insert(0, {"name": "Hayvancılık İstatistikleri", "period": "x",
                              "url": "/tr/press/59998", "date": "2026-10-22T10:00:00",
                              "type": "Haber Bülteni", "typeId": 1})
    assert w.check_once() == 1
    assert len(pushes) == 1
    title, body, data = pushes[0]
    assert title.startswith("TÜİK • Tüketici Güven Endeksi")
    assert body == "Tüketici güven endeksi 91,9 oldu"  # AI yokken TÜİK manşeti
    assert data["id"] == 59999
    # tekrar çalışınca yeniden bildirim yok
    assert w.check_once() == 0
    assert len(pushes) == 1

# ---------------------------------------------------------------- Telegram / PDF

import telegram_pdf as tg  # noqa: E402

SAMPLE = {
    "id": 58177, "title": "Tüketici Güven Endeksi", "period": "Eylül 2026", "date": "2026-09-22T10:00:00",
    "url": "https://veriportali.tuik.gov.tr/tr/press/58177", "headline": "Tüketici güven endeksi 91,9 oldu",
    "next_release": "22 Ekim 2026",
    "ai": {"baslik": "x", "ozet": "Endeks <91,9> & arttı.", "one_cikanlar": ["a", "b"],
           "rakamlar": [{"etiket": "Endeks", "deger": "91,9", "degisim": "%1,3"}], "dogrulanamayan": [],
           "model": "gemini-3.8-flash"},
}


def test_telegram_message_escapes_html():
    m = tg.format_message(SAMPLE)
    assert m.startswith("<b>TÜİK • Tüketici Güven Endeksi — Eylül 2026</b>")
    assert "&lt;91,9&gt; &amp; arttı." in m
    assert "Endeks: <b>91,9</b> (%1,3)" in m
    assert len(m) <= 4000


def test_pdf_builds_and_filename():
    pdf = tg.build_pdf(SAMPLE)
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000
    assert tg.pdf_filename(SAMPLE) == "TUIK_Tuketici_Guven_Endeksi_Eylul_2026.pdf"


def test_chat_id_discovery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(tg, "_call", lambda method, **kw: [
        {"message": {"chat": {"id": 5, "type": "private"}}},
        {"my_chat_member": {"chat": {"id": -1001, "type": "channel", "title": "TÜİK Cep"}}},
    ])
    state = {}
    assert tg.resolve_chat_id(state) == "-1001"
    assert state["telegram_chat_id"] == "-1001"
