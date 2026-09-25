import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  BackHandler,
  FlatList,
  Linking,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  useColorScheme,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import * as Clipboard from 'expo-clipboard';
import AsyncStorage from '@react-native-async-storage/async-storage';

// ---------------------------------------------------------------- tipler

type Figure = { etiket: string; deger: string; degisim: string };
type AI = {
  baslik: string;
  ozet: string;
  one_cikanlar: string[];
  rakamlar: Figure[];
  dogrulanamayan?: string[];
  model?: string;
};
type Item = {
  id: number;
  title: string;
  period: string;
  date: string | null;
  url: string;
  headline: string;
  next_release: string | null;
  ai: AI | null;
  detected_at: string;
};

const DEFAULT_REPO: string = Constants.expoConfig?.extra?.githubRepo ?? '';
const K_FEED = 'feed-cache-v1';
const K_REPO = 'github-repo-v1';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

// ---------------------------------------------------------------- yardımcılar

async function fetchFeed(repo: string): Promise<Item[]> {
  // GitHub API: önbelleksiz, en güncel feed.json. Hata olursa raw adresini dene.
  const api = `https://api.github.com/repos/${repo}/contents/data/feed.json?ref=main&t=${Date.now()}`;
  try {
    const r = await fetch(api, { headers: { Accept: 'application/vnd.github.raw+json' } });
    if (r.ok) return (await r.json()) as Item[];
  } catch {}
  const raw = `https://raw.githubusercontent.com/${repo}/main/data/feed.json?t=${Date.now()}`;
  const r = await fetch(raw);
  if (!r.ok) throw new Error(`Feed alınamadı (HTTP ${r.status})`);
  return (await r.json()) as Item[];
}

async function registerForPush(): Promise<string> {
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('tuik', {
      name: 'TÜİK bültenleri',
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 200, 120, 200],
      lightColor: '#C8102E',
    });
  }
  if (!Device.isDevice) throw new Error('Push bildirimleri yalnızca gerçek cihazda çalışır.');
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== 'granted') status = (await Notifications.requestPermissionsAsync()).status;
  if (status !== 'granted') throw new Error('Bildirim izni verilmedi. Ayarlar > Uygulamalar > TÜİK Cep > Bildirimler.');
  const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  if (!projectId) throw new Error('EAS projectId bulunamadı (eas init çalıştırıldı mı?).');
  return (await Notifications.getExpoPushTokenAsync({ projectId })).data;
}

function fmtDate(iso: string | null): string {
  if (!iso) return '';
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : iso;
}

function shortTitle(t: string): string {
  return t
    .replace('Tüketici Fiyat Endeksi', 'TÜFE')
    .replace('Yurt İçi Üretici Fiyat Endeksi', 'Yİ-ÜFE')
    .replace('Dönemsel Gayrisafi Yurt İçi Hasıla', 'GSYH');
}

// ---------------------------------------------------------------- uygulama

export default function App() {
  const dark = useColorScheme() === 'dark';
  const c = dark ? darkColors : lightColors;
  const s = useMemo(() => makeStyles(c), [c]);

  const [repo, setRepo] = useState<string>(DEFAULT_REPO);
  const [feed, setFeed] = useState<Item[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [screen, setScreen] = useState<'list' | 'detail' | 'settings'>('list');
  const [selected, setSelected] = useState<Item | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [tokenErr, setTokenErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const pendingOpen = useRef<{ id: number; url?: string } | null>(null);

  const load = useCallback(async (r: string = repo) => {
    if (!r) {
      setError('Ayarlar ekranından GitHub reposunu gir (ör. kullanici/tuik-cep).');
      return [] as Item[];
    }
    setLoading(true);
    setError(null);
    try {
      const f = await fetchFeed(r);
      setFeed(f);
      AsyncStorage.setItem(K_FEED, JSON.stringify(f)).catch(() => {});
      return f;
    } catch (e: any) {
      setError(e?.message ?? String(e));
      return [] as Item[];
    } finally {
      setLoading(false);
    }
  }, [repo]);

  const openById = useCallback(async (id: number, url?: string) => {
    let item = feed.find((x) => x.id === id);
    if (!item) item = (await load()).find((x) => x.id === id);
    if (!item) {
      item = { id, title: 'Yeni bülten', period: '', date: null, url: url ?? `https://veriportali.tuik.gov.tr/tr/press/${id}`,
        headline: 'Özet henüz senkronize olmadı; birkaç dakika sonra yenile.', next_release: null, ai: null, detected_at: '' };
    }
    setSelected(item);
    setScreen('detail');
  }, [feed, load]);

  // İlk açılış: önbellek, ayarlar, push kaydı, feed
  useEffect(() => {
    (async () => {
      try {
        const cached = await AsyncStorage.getItem(K_FEED);
        if (cached) setFeed(JSON.parse(cached));
      } catch {}
      let r = DEFAULT_REPO;
      try {
        const saved = await AsyncStorage.getItem(K_REPO);
        if (saved) r = saved;
      } catch {}
      setRepo(r);
      await load(r);
      if (pendingOpen.current) {
        const p = pendingOpen.current;
        pendingOpen.current = null;
        openById(p.id, p.url);
      }
    })();
    registerForPush().then(setToken).catch((e) => setTokenErr(e?.message ?? String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Bildirime dokunulunca ilgili bülteni aç
  const lastResponse = Notifications.useLastNotificationResponse();
  useEffect(() => {
    if (!lastResponse || lastResponse.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) return;
    const data = lastResponse.notification.request.content.data as { id?: number; url?: string };
    if (data?.id) openById(Number(data.id), data.url);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastResponse]);

  // Uygulama açıkken bildirim gelirse listeyi yenile
  useEffect(() => {
    const sub = Notifications.addNotificationReceivedListener(() => {
      setTimeout(() => load(), 4000);
    });
    return () => sub.remove();
  }, [load]);

  // Android geri tuşu
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (screen !== 'list') {
        setScreen('list');
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, [screen]);

  // ------------------------------------------------------------ ekranlar

  const header = (title: string, left?: { label: string; onPress: () => void }, right?: { label: string; onPress: () => void }) => (
    <View style={s.header}>
      <View style={s.headerSide}>
        {left && (
          <Pressable onPress={left.onPress} hitSlop={12}>
            <Text style={s.headerBtn}>{left.label}</Text>
          </Pressable>
        )}
      </View>
      <Text style={s.headerTitle} numberOfLines={1}>{title}</Text>
      <View style={[s.headerSide, { alignItems: 'flex-end' }]}>
        {right && (
          <Pressable onPress={right.onPress} hitSlop={12}>
            <Text style={s.headerBtn}>{right.label}</Text>
          </Pressable>
        )}
      </View>
    </View>
  );

  if (screen === 'settings') {
    return (
      <View style={s.root}>
        <StatusBar style={dark ? 'light' : 'dark'} />
        {header('Ayarlar', { label: '‹ Geri', onPress: () => setScreen('list') })}
        <ScrollView contentContainerStyle={s.pad}>
          <Text style={s.label}>Push token</Text>
          <Text style={s.help}>Bunu GitHub'da repo → Settings → Secrets → Actions → EXPO_PUSH_TOKENS olarak kaydet.</Text>
          <View style={s.card}>
            {token ? <Text selectable style={s.mono}>{token}</Text> : <Text style={s.err}>{tokenErr ?? 'Alınıyor…'}</Text>}
          </View>
          {token && (
            <Pressable style={s.primaryBtn} onPress={async () => { await Clipboard.setStringAsync(token); setCopied(true); setTimeout(() => setCopied(false), 2000); }}>
              <Text style={s.primaryBtnText}>{copied ? 'Kopyalandı ✓' : 'Token\'ı kopyala'}</Text>
            </Pressable>
          )}
          {!token && (
            <Pressable style={s.secondaryBtn} onPress={() => { setTokenErr(null); registerForPush().then(setToken).catch((e) => setTokenErr(e?.message ?? String(e))); }}>
              <Text style={s.secondaryBtnText}>Tekrar dene</Text>
            </Pressable>
          )}

          <Text style={[s.label, { marginTop: 28 }]}>GitHub reposu</Text>
          <Text style={s.help}>Bültenlerin okunduğu repo (kullanici/repo).</Text>
          <TextInput
            style={s.input}
            value={repo}
            onChangeText={setRepo}
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="kullanici/tuik-cep"
            placeholderTextColor={c.muted}
          />
          <Pressable style={s.secondaryBtn} onPress={async () => { await AsyncStorage.setItem(K_REPO, repo.trim()); await load(repo.trim()); setScreen('list'); }}>
            <Text style={s.secondaryBtnText}>Kaydet ve yenile</Text>
          </Pressable>
        </ScrollView>
      </View>
    );
  }

  if (screen === 'detail' && selected) {
    const it = selected;
    const ai = it.ai;
    return (
      <View style={s.root}>
        <StatusBar style={dark ? 'light' : 'dark'} />
        {header(shortTitle(it.title), { label: '‹ Geri', onPress: () => setScreen('list') })}
        <ScrollView contentContainerStyle={s.pad}>
          <Text style={s.kicker}>{it.period}{it.date ? ` · ${fmtDate(it.date)}` : ''}</Text>
          <Text style={s.h1}>{it.title}</Text>
          {!!it.headline && (
            <View style={s.quote}>
              <Text style={s.quoteLabel}>TÜİK manşeti</Text>
              <Text style={s.quoteText}>{it.headline}</Text>
            </View>
          )}

          {ai ? (
            <>
              <Text style={s.section}>AI özeti</Text>
              <Text style={s.body}>{ai.ozet}</Text>
              {ai.one_cikanlar?.length > 0 && (
                <View style={{ marginTop: 12 }}>
                  {ai.one_cikanlar.map((b, i) => (
                    <View key={i} style={s.bulletRow}>
                      <Text style={s.bulletDot}>•</Text>
                      <Text style={[s.body, { flex: 1 }]}>{b}</Text>
                    </View>
                  ))}
                </View>
              )}
              {ai.rakamlar?.length > 0 && (
                <>
                  <Text style={s.section}>Temel rakamlar</Text>
                  <View style={s.card}>
                    {ai.rakamlar.map((f, i) => (
                      <View key={i} style={[s.figRow, i > 0 && s.figDivider]}>
                        <Text style={s.figLabel}>{f.etiket}</Text>
                        <View style={{ alignItems: 'flex-end' }}>
                          <Text style={s.figValue}>{f.deger}</Text>
                          {!!f.degisim && <Text style={s.figChange}>{f.degisim}</Text>}
                        </View>
                      </View>
                    ))}
                  </View>
                </>
              )}
              {(ai.dogrulanamayan?.length ?? 0) > 0 && (
                <Text style={s.warn}>⚠ Özetteki bazı rakamlar bülten metninde birebir bulunamadı; TÜİK metnine bakarak kontrol et.</Text>
              )}
              <Text style={s.meta}>Rakamlar TÜİK metniyle otomatik karşılaştırıldı · {ai.model ?? 'Gemini'}</Text>
            </>
          ) : (
            <Text style={[s.body, { marginTop: 16, color: c.muted }]}>Bu bülten için AI özeti yok.</Text>
          )}

          {!!it.next_release && <Text style={s.next}>Sonraki yayım: {it.next_release}</Text>}

          <Pressable style={[s.primaryBtn, { marginTop: 24 }]} onPress={() => Linking.openURL(it.url)}>
            <Text style={s.primaryBtnText}>TÜİK'te aç</Text>
          </Pressable>
        </ScrollView>
      </View>
    );
  }

  return (
    <View style={s.root}>
      <StatusBar style={dark ? 'light' : 'dark'} />
      {header('TÜİK Cep', undefined, { label: 'Ayarlar', onPress: () => setScreen('settings') })}
      {error && <Text style={[s.err, { paddingHorizontal: 16, paddingTop: 8 }]}>{error}</Text>}
      <FlatList
        data={feed}
        keyExtractor={(x) => String(x.id)}
        contentContainerStyle={{ padding: 16, paddingBottom: 48 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => load()} colors={[c.accent]} />}
        ListEmptyComponent={loading ? <ActivityIndicator style={{ marginTop: 40 }} color={c.accent} /> : (
          <Text style={[s.body, { color: c.muted, textAlign: 'center', marginTop: 40 }]}>Henüz bülten yok. Aşağı çekip yenile.</Text>
        )}
        renderItem={({ item }) => (
          <Pressable style={({ pressed }) => [s.card, s.listCard, pressed && { opacity: 0.7 }]} onPress={() => { setSelected(item); setScreen('detail'); }}>
            <View style={s.rowBetween}>
              <Text style={s.kicker}>{item.period}</Text>
              <Text style={s.kickerMuted}>{fmtDate(item.date)}</Text>
            </View>
            <Text style={s.cardTitle}>{shortTitle(item.title)}</Text>
            <Text style={s.cardBody} numberOfLines={3}>{item.ai?.baslik || item.headline}</Text>
            {item.ai && <Text style={s.badge}>AI özeti</Text>}
          </Pressable>
        )}
      />
    </View>
  );
}

// ---------------------------------------------------------------- stil

const lightColors = { bg: '#F6F5F2', card: '#FFFFFF', text: '#16181D', muted: '#6B6F78', line: '#E4E2DD', accent: '#C8102E', accentSoft: '#FBE9EC', warn: '#9A5B00' };
const darkColors = { bg: '#101114', card: '#1A1C21', text: '#ECEDEF', muted: '#9A9EA8', line: '#2A2D34', accent: '#FF5A6E', accentSoft: '#3A1A20', warn: '#F0B35A' };
type Colors = typeof lightColors;

const makeStyles = (c: Colors) => StyleSheet.create({
  root: { flex: 1, backgroundColor: c.bg, paddingTop: Constants.statusBarHeight },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, height: 52, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.line },
  headerSide: { width: 72 },
  headerTitle: { flex: 1, textAlign: 'center', fontSize: 17, fontWeight: '700', color: c.text },
  headerBtn: { color: c.accent, fontSize: 15, fontWeight: '600' },
  pad: { padding: 16, paddingBottom: 48 },
  card: { backgroundColor: c.card, borderRadius: 14, padding: 14, borderWidth: StyleSheet.hairlineWidth, borderColor: c.line },
  listCard: { marginBottom: 12 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between' },
  kicker: { color: c.accent, fontSize: 12, fontWeight: '700', letterSpacing: 0.3, textTransform: 'uppercase' },
  kickerMuted: { color: c.muted, fontSize: 12 },
  cardTitle: { color: c.text, fontSize: 17, fontWeight: '700', marginTop: 6 },
  cardBody: { color: c.text, fontSize: 15, lineHeight: 21, marginTop: 6, opacity: 0.9 },
  badge: { alignSelf: 'flex-start', marginTop: 10, backgroundColor: c.accentSoft, color: c.accent, fontSize: 11, fontWeight: '700', paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, overflow: 'hidden' },
  h1: { color: c.text, fontSize: 24, fontWeight: '800', marginTop: 6, lineHeight: 30 },
  quote: { marginTop: 16, borderLeftWidth: 3, borderLeftColor: c.accent, paddingLeft: 12, paddingVertical: 4 },
  quoteLabel: { color: c.muted, fontSize: 12, fontWeight: '600', marginBottom: 4 },
  quoteText: { color: c.text, fontSize: 16, lineHeight: 23, fontWeight: '600' },
  section: { color: c.muted, fontSize: 13, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 24, marginBottom: 8 },
  body: { color: c.text, fontSize: 16, lineHeight: 24 },
  bulletRow: { flexDirection: 'row', gap: 8, marginBottom: 6 },
  bulletDot: { color: c.accent, fontSize: 16, lineHeight: 24 },
  figRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 10, gap: 12 },
  figDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line },
  figLabel: { color: c.text, fontSize: 14, flex: 1 },
  figValue: { color: c.text, fontSize: 17, fontWeight: '700', fontVariant: ['tabular-nums'] },
  figChange: { color: c.muted, fontSize: 13, fontVariant: ['tabular-nums'] },
  warn: { color: c.warn, fontSize: 13, marginTop: 14, lineHeight: 19 },
  meta: { color: c.muted, fontSize: 12, marginTop: 14 },
  next: { color: c.text, fontSize: 14, marginTop: 20, fontWeight: '600' },
  label: { color: c.text, fontSize: 15, fontWeight: '700' },
  help: { color: c.muted, fontSize: 13, marginTop: 4, marginBottom: 10, lineHeight: 18 },
  mono: { color: c.text, fontFamily: Platform.OS === 'android' ? 'monospace' : 'Menlo', fontSize: 13 },
  err: { color: c.accent, fontSize: 14 },
  input: { backgroundColor: c.card, borderRadius: 12, borderWidth: 1, borderColor: c.line, paddingHorizontal: 12, paddingVertical: 10, color: c.text, fontSize: 15 },
  primaryBtn: { backgroundColor: c.accent, borderRadius: 12, paddingVertical: 14, alignItems: 'center', marginTop: 12 },
  primaryBtnText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
  secondaryBtn: { borderRadius: 12, paddingVertical: 12, alignItems: 'center', marginTop: 12, borderWidth: 1, borderColor: c.accent },
  secondaryBtnText: { color: c.accent, fontSize: 15, fontWeight: '700' },
});
