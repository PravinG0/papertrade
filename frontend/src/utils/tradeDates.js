// The backend stores naive wall-clock timestamps in Asia/Kolkata. Explicit offsets
// are converted to IST, independent of the browser timezone.
export function istParts(value) {
  if (!value || typeof value !== 'string') return null;
  const shape = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/.exec(value);
  if (!shape) return null;
  const [y, m, d, h, min, sec] = shape.slice(1).map(v => Number(v || 0));
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  if (y < 1 || m < 1 || m > 12 || d < 1 || d > [31, leap ? 29 : 28,31,30,31,30,31,31,30,31,30,31][m-1] || h > 23 || min > 59 || sec > 59) return null;
  const naive = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?$/.exec(value);
  if (naive) return { date: naive[1], time: naive[2].length === 5 ? `${naive[2]}:00` : naive[2] };
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime()) || !/[T ]\d{2}:\d{2}/.test(value)) return null;
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(parsed).map(p => [p.type, p.value]));
  return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}:${parts.second}` };
}
export function dateTimeIST(value) {
  const p = istParts(value);
  return p ? `${p.date.split('-').reverse().join('/')} ${p.time}` : '—';
}
export function dateInRange(value, from, to) {
  if (!from && !to) return true;
  const p = istParts(value);
  return Boolean(p && (!from || p.date >= from) && (!to || p.date <= to));
}
export function todayIST() { return istParts(new Date().toISOString()).date; }
