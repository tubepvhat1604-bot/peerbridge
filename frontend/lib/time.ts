export const APP_TIMEZONE = "Asia/Ho_Chi_Minh";
function parse(value: string) {
 if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(value + "T00:00:00+07:00");
 const normalized = value.replace(" ", "T");
 return new Date(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : normalized + "Z");
}
function parts(value: string, timezone = APP_TIMEZONE) {
 const d = parse(value); if (Number.isNaN(d.getTime())) return null;
 return Object.fromEntries(new Intl.DateTimeFormat("en-GB", {timeZone:timezone,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(d).map(p=>[p.type,p.value]));
}
export function formatDate(value: string, timezone = APP_TIMEZONE) { const p=parts(value,timezone); return p ? `${p.day}/${p.month}/${p.year}` : "Chưa đặt ngày"; }
export function formatClock(value: string, timezone = APP_TIMEZONE) { const p=parts(value,timezone); return p ? `${p.hour}:${p.minute}` : "Chưa đặt giờ"; }
export function formatDateTime(value: string | null, timezone = APP_TIMEZONE) { return value ? `${formatDate(value,timezone)} · ${formatClock(value,timezone)}` : "Chưa đặt giờ"; }
export function toDateTimeInput(value: string | null) { const p=value ? parts(value) : null; return p ? `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}` : ""; }
export function localInputToISO(value: string) { return new Date(value + ":00+07:00").toISOString(); }
