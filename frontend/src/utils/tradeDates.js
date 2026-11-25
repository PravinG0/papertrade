// The backend stores naive wall-clock timestamps in Asia/Kolkata. Explicit offsets
// are converted to IST, independent of the browser timezone.
export function istParts(value) {
  if (!value || typeof value !== 'string') return null;
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
