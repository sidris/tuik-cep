import { useState } from 'react';
import { Text, View } from 'react-native';
import Svg, { Circle, Line, Polyline, Rect } from 'react-native-svg';

export type ChartData = {
  title: string;
  type: 'line' | 'bar';
  labels: string[];
  series: { label: string; data: (number | null)[] }[];
};

type Colors = { text: string; muted: string; line: string; accent: string; card: string };

const H = 150;
const PAD = { top: 10, right: 8, bottom: 4, left: 8 };

const fmt = (v: number) => v.toLocaleString('tr-TR', { maximumFractionDigits: 2 });

export function MiniChart({ chart, c }: { chart: ChartData; c: Colors }) {
  const [w, setW] = useState(0);
  const palette = [c.accent, '#3B7BC4', c.muted];
  const all = chart.series.flatMap((s) => s.data).filter((v): v is number => v != null);
  if (all.length < 2) return null;
  let min = Math.min(...all);
  let max = Math.max(...all);
  if (chart.type === 'bar') { min = Math.min(0, min); max = Math.max(0, max); }
  if (min === max) { min -= 1; max += 1; }
  const n = chart.labels.length;
  const iw = Math.max(0, w - PAD.left - PAD.right);
  const ih = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (n <= 1 ? iw / 2 : (i * iw) / (n - 1));
  const y = (v: number) => PAD.top + ih - ((v - min) / (max - min)) * ih;

  const main = chart.series[0];
  const lastIdx = (() => { for (let i = main.data.length - 1; i >= 0; i--) if (main.data[i] != null) return i; return -1; })();
  const last = lastIdx >= 0 ? (main.data[lastIdx] as number) : null;

  return (
    <View>
      {!!chart.title && <Text style={{ color: c.muted, fontSize: 12, marginBottom: 6 }}>{chart.title}</Text>}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 2 }}>
        <Text style={{ color: c.muted, fontSize: 11, fontVariant: ['tabular-nums'] }}>en yüksek {fmt(Math.max(...all))}</Text>
        {last != null && <Text style={{ color: c.accent, fontSize: 13, fontWeight: '700', fontVariant: ['tabular-nums'] }}>son: {fmt(last)}</Text>}
      </View>
      <View onLayout={(e) => setW(e.nativeEvent.layout.width)} style={{ height: H }}>
        {w > 0 && (
          <Svg width={w} height={H}>
            {chart.type === 'bar' && min < 0 && (
              <Line x1={PAD.left} x2={w - PAD.right} y1={y(0)} y2={y(0)} stroke={c.line} strokeWidth={1} />
            )}
            {chart.type === 'bar'
              ? (() => {
                  const bw = Math.max(2, (iw / n) * 0.6);
                  return main.data.map((v, i) =>
                    v == null ? null : (
                      <Rect
                        key={i}
                        x={x(i) - bw / 2}
                        y={Math.min(y(v), y(0))}
                        width={bw}
                        height={Math.max(1, Math.abs(y(v) - y(0)))}
                        rx={1.5}
                        fill={i === lastIdx ? c.accent : c.muted}
                        opacity={i === lastIdx ? 1 : 0.45}
                      />
                    ),
                  );
                })()
              : chart.series.map((s, si) => {
                  const pts = s.data.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(' ');
                  return (
                    <Polyline key={si} points={pts} fill="none" stroke={palette[si % palette.length]}
                      strokeWidth={si === 0 ? 2.5 : 1.75} strokeLinejoin="round" strokeLinecap="round" />
                  );
                })}
            {chart.type === 'line' && last != null && (
              <Circle cx={x(lastIdx)} cy={y(last)} r={4} fill={c.accent} stroke={c.card} strokeWidth={2} />
            )}
          </Svg>
        )}
      </View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
        <Text style={{ color: c.muted, fontSize: 11 }}>{chart.labels[0]}</Text>
        <Text style={{ color: c.muted, fontSize: 11 }}>en düşük {fmt(Math.min(...all))}</Text>
        <Text style={{ color: c.muted, fontSize: 11 }}>{chart.labels[n - 1]}</Text>
      </View>
      {chart.series.length > 1 && chart.type === 'line' && (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 8 }}>
          {chart.series.map((s, si) => (
            <View key={si} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <View style={{ width: 12, height: 3, borderRadius: 2, backgroundColor: palette[si % palette.length] }} />
              <Text style={{ color: c.text, fontSize: 12 }}>{s.label}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}
