# TÜİK Cep

TÜİK haber bültenleri yayımlandığında telefona bildirim gönderen ve Gemini ile özet çıkaran kişisel uygulama.

```
GitHub Actions (hafta içi 09:35–10:30 arası 15 sn'de bir, diğer saatlerde ~10 dk'da bir)
   └─ watcher/tuik_watcher.py
        1. veriportali.tuik.gov.tr/api/tr/press/latest  → yeni bülten var mı?
        2. /api/tr/press/{id}                           → bülten metni + tablolar
        3. Gemini                                       → özet, öne çıkanlar, temel rakamlar
        4. Rakam doğrulama                              → metinde olmayan rakamları ele
        5. Expo Push → Firebase → telefon
        6. data/feed.json'a yaz, commit et              → uygulama buradan okur
```

## Klasörler

| Klasör | İçerik |
|---|---|
| `watcher/` | Python izleyici, `watchlist.json` (hangi bültenler), testler |
| `.github/workflows/tuik-watch.yml` | Zamanlama |
| `data/` | `feed.json` (son 150 bülten + özetler), `state.json` (görülenler). Bot günceller. |
| `app/` | Expo (React Native) Android uygulaması |

## Kurulum (bir kerelik)

### 1) Gemini anahtarı
https://aistudio.google.com/apikey → **Create API key** → kopyala.

### 2) GitHub
1. Repo: https://github.com/sidris/tuik-cep (Public: Actions dakikası sınırsız ve ücretsiz; kodda gizli bilgi yok, anahtarlar Secrets'ta durur).
2. Yerelde çalışmak için: `git clone https://github.com/sidris/tuik-cep.git`
3. Repo → **Settings → Secrets and variables → Actions → New repository secret**
   - `GEMINI_API_KEY` = 1. adımdaki anahtar
4. Repo → **Settings → Actions → General → Workflow permissions → Read and write permissions** → Save.
5. **Actions** sekmesi → "TÜİK izleyici" → **Run workflow** (mode: `once`).
   İlk çalıştırma geçmiş bültenleri bildirim göndermeden "görüldü" sayar ve son 5 bülteni özetleyip `data/feed.json`'a yazar.
   Log'da `feed'e eklendi` satırlarını görürsen TÜİK ve Gemini bağlantısı çalışıyor demektir.

### 3) Firebase (Android push için zorunlu)
1. https://console.firebase.google.com → **Create project** → `tuik-cep` (Analytics kapalı olabilir).
2. Proje ana sayfası → **Android** simgesi → package name: `com.sefa.tuikcep` → Register.
3. `google-services.json` dosyasını indir → `app/` klasörüne koy. (Repo'ya girmez, `.gitignore`'da.)
4. ⚙ **Project settings → Service accounts → Generate new private key** → JSON'u indir.
   Bu dosyayı repo klasörüne KOYMA; İndirilenler'de kalsın, 5. adımda EAS'a yükleyeceğiz.

### 4) Expo / APK
Gerekli: Node.js 20+ ve ücretsiz bir https://expo.dev hesabı.
```powershell
cd app
npm install
npx eas-cli@latest login
npx eas-cli@latest init            # app.json'a projectId ekler
```
`app/app.json` içindeki `githubRepo` zaten `sidris/tuik-cep` olarak ayarlı.

FCM anahtarını yükle:
```powershell
npx eas-cli@latest credentials
#  Android → (profil sorarsa) preview → Google Service Account
#  → Manage your Google Service Account Key for Push Notifications (FCM V1)
#  → Set up a Google Service Account Key for Push Notifications (FCM V1) → Upload → 3.4'teki JSON
```
APK'yı derle (Expo'nun bulutunda, ~10-15 dk):
```powershell
npx eas-cli@latest build -p android --profile preview
```
Bitince çıkan bağlantıyı / QR'ı telefonda aç → APK'yı indir → kur ("bilinmeyen kaynaklara izin ver" diyebilir).

### 5) Telefonu bağla
1. Uygulamayı aç → bildirim iznine **İzin ver**.
2. **Ayarlar** → **Token'ı kopyala** (`ExponentPushToken[...]`).
3. GitHub → Settings → Secrets → Actions → `EXPO_PUSH_TOKENS` = kopyaladığın token.
4. Actions → Run workflow → mode: `test-push` → telefona son bülten bildirimi gelmeli.

## Günlük kullanım
- Hiçbir şey yapmana gerek yok. Bülten çıkınca bildirim gelir; dokununca özet açılır, "TÜİK'te aç" ile asıl bülten.
- Hangi bültenler: `watcher/watchlist.json` → `anahtar_kelimeler`. Hepsi için `"hepsi": true`.
- Model: varsayılan `gemini-3.8-flash`, olmazsa `gemini-3.5-flash-lite`. Değiştirmek için repo → Settings → Variables → `GEMINI_MODEL`.
- Belirli bir bülteni yeniden test et: Run workflow → `test-push`, `press_id` = 58290 gibi.

## Sınırlamalar
- GitHub zamanlanmış işleri garanti saatinde başlatmaz; yoğun pencere dışında gecikme 10–20 dakikayı bulabilir.
  09:35–10:30 penceresinde iş zaten çalıştığı için 10:00 bültenleri genelde 15–30 sn içinde yakalanır.
- 60 gün boyunca repo'da hiç commit olmazsa GitHub zamanlanmış işleri durdurur. Bot bülten geldikçe commit attığı için normalde sorun olmaz.
- AI özeti yanlış olabilir. Rakamlar metinle otomatik karşılaştırılır, uyuşmayan varsa uygulamada uyarı çıkar. Kesin rakam için TÜİK metnine bak.

## Geliştirme
```powershell
pip install -r watcher/requirements.txt pytest
python -m pytest watcher/tests
python watcher/tuik_watcher.py summarize --id 58290   # GEMINI_API_KEY ortam değişkeni gerekir
```
