import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import { File, Paths } from 'expo-file-system';

export type PdfItem = {
  id: number;
  title: string;
  period: string;
  date: string | null;
  url: string;
  headline: string;
  next_release: string | null;
  ai: {
    baslik: string;
    ozet: string;
    one_cikanlar: string[];
    rakamlar: { etiket: string; deger: string; degisim: string }[];
    dogrulanamayan?: string[];
    model?: string;
  } | null;
};

const esc = (s: string | null | undefined) =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

function fmtDate(iso: string | null): string {
  if (!iso) return '';
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : iso;
}

function fileName(it: PdfItem): string {
  const map: Record<string, string> = { ç: 'c', ğ: 'g', ı: 'i', İ: 'I', ö: 'o', ş: 's', ü: 'u', Ç: 'C', Ğ: 'G', Ö: 'O', Ş: 'S', Ü: 'U' };
  const base = `TUIK_${it.title}_${it.period}`
    .replace(/[çğıİöşüÇĞÖŞÜ]/g, (ch) => map[ch] ?? ch)
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 90);
  return `${base}.pdf`;
}

export function buildHtml(it: PdfItem): string {
  const ai = it.ai;
  const now = new Date();
  const created = `${String(now.getDate()).padStart(2, '0')}.${String(now.getMonth() + 1).padStart(2, '0')}.${now.getFullYear()} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  const bullets = (ai?.one_cikanlar ?? []).map((b) => `<li>${esc(b)}</li>`).join('');
  const rows = (ai?.rakamlar ?? [])
    .map((f) => `<tr><td>${esc(f.etiket)}</td><td class="num">${esc(f.deger)}</td><td class="num muted">${esc(f.degisim)}</td></tr>`)
    .join('');
  const warn = (ai?.dogrulanamayan?.length ?? 0) > 0
    ? `<p class="warn">Not: Özetteki bazı rakamlar bülten metninde birebir bulunamadı; kesin değerler için TÜİK bültenine bakınız.</p>`
    : '';

  return `<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8" />
<style>
  @page { size: A4; margin: 0; }
  * { box-sizing: border-box; }
  body { font-family: 'Roboto', 'Helvetica Neue', Arial, sans-serif; color: #16181D; font-size: 11pt; line-height: 1.5; margin: 0; }
  .page { padding: 48px 44px; }
  .brand { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 2px solid #C8102E; padding-bottom: 6px; margin-bottom: 18px; }
  .brand b { color: #C8102E; font-size: 10pt; letter-spacing: .5px; }
  .brand span { color: #6B6F78; font-size: 9pt; }
  .kicker { color: #C8102E; font-size: 9pt; font-weight: 700; text-transform: uppercase; letter-spacing: .4px; }
  h1 { font-size: 19pt; line-height: 1.25; margin: 4px 0 14px; }
  .headline { border-left: 3px solid #C8102E; padding: 4px 0 4px 12px; margin: 0 0 18px; }
  .headline small { display: block; color: #6B6F78; font-size: 8.5pt; font-weight: 600; margin-bottom: 2px; }
  .headline p { margin: 0; font-weight: 600; font-size: 12pt; }
  h2 { font-size: 9pt; color: #6B6F78; text-transform: uppercase; letter-spacing: .5px; margin: 20px 0 6px; }
  p { margin: 0 0 8px; }
  ul { margin: 6px 0 0; padding-left: 18px; }
  li { margin-bottom: 4px; }
  table { width: 100%; border-collapse: collapse; margin-top: 4px; }
  td { padding: 6px 4px; border-bottom: 1px solid #E4E2DD; vertical-align: top; }
  td.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; font-weight: 700; }
  td.muted { color: #6B6F78; font-weight: 400; }
  .warn { color: #9A5B00; font-size: 9.5pt; margin-top: 10px; }
  .meta { margin-top: 20px; font-size: 10pt; }
  .meta a { color: #C8102E; word-break: break-all; }
  .foot { margin-top: 26px; padding-top: 8px; border-top: 1px solid #E4E2DD; color: #6B6F78; font-size: 8.5pt; }
</style></head><body><div class="page">
  <div class="brand"><b>TÜİK BÜLTEN ÖZETİ</b><span>${esc(created)}</span></div>
  <div class="kicker">${esc(it.period)}${it.date ? ' · ' + esc(fmtDate(it.date)) : ''}</div>
  <h1>${esc(it.title)}</h1>
  ${it.headline ? `<div class="headline"><small>TÜİK manşeti</small><p>${esc(it.headline)}</p></div>` : ''}
  ${ai ? `
    <h2>Özet</h2><p>${esc(ai.ozet)}</p>
    ${bullets ? `<h2>Öne çıkanlar</h2><ul>${bullets}</ul>` : ''}
    ${rows ? `<h2>Temel rakamlar</h2><table>${rows}</table>` : ''}
    ${warn}` : `<p>Bu bülten için özet bulunmuyor.</p>`}
  <div class="meta">
    ${it.next_release ? `<p><b>Sonraki yayım:</b> ${esc(it.next_release)}</p>` : ''}
    <p><b>Kaynak:</b> <a href="${esc(it.url)}">${esc(it.url)}</a></p>
  </div>
  <div class="foot">Bu özet, TÜİK haber bülteni metninden yapay zekâ (${esc(ai?.model ?? 'Gemini')}) ile otomatik olarak hazırlanmıştır. Rakamlar bülten metniyle otomatik karşılaştırılmıştır; resmî ve kesin veriler için yukarıdaki TÜİK bültenine başvurunuz.</div>
</div></body></html>`;
}

export async function sharePdf(it: PdfItem): Promise<void> {
  const { uri } = await Print.printToFileAsync({ html: buildHtml(it), width: 595, height: 842 });
  let shareUri = uri;
  try {
    const dest = new File(Paths.cache, fileName(it));
    if (dest.exists) dest.delete();
    new File(uri).move(dest);
    shareUri = dest.uri;
  } catch {
    // yeniden adlandırma başarısız olursa rastgele adlı dosyayla devam
  }
  if (!(await Sharing.isAvailableAsync())) throw new Error('Bu cihazda paylaşım kullanılamıyor.');
  await Sharing.shareAsync(shareUri, { mimeType: 'application/pdf', dialogTitle: `${it.title} — ${it.period}`, UTI: 'com.adobe.pdf' });
}
