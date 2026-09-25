#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
n=0
t() { for f in "$@"; do n=$((n+1)); grep -v '^// build ' "$f" > "$f.tmp" || true; mv "$f.tmp" "$f"; echo "// build $(echo "$n" | cksum | cut -d' ' -f1)" >> "$f"; done; }
v() { printf '{\n  "name": "report-export",\n  "version": "%s",\n  "private": true\n}\n' "$1" > package.json; }
mkdir -p src/reports src/dates src/api
v 1.0.0
printf '# report-export\n\nCSV exports for the reporting page.\n' > README.md
cat > src/reports/csv.ts <<'TS'
export function toCsv(rows: string[][], delimiter = ","): string {
  return rows.map((r) => r.map((cell) => escapeCell(cell, delimiter)).join(delimiter)).join("\n");
}

function escapeCell(cell: string, delimiter: string): string {
  const needsQuotes = cell.includes(delimiter) || cell.includes('"') || cell.includes("\n");
  return needsQuotes ? '"' + cell.replace(/"/g, '""') + '"' : cell;
}
TS
cat > src/reports/columns.ts <<'TS'
export interface Column {
  key: string;
  header: string;
}

export const DEFAULT_COLUMNS: Column[] = [
  { key: "day", header: "Day" },
  { key: "account", header: "Account" },
  { key: "amount", header: "Amount" },
];
TS
cat > src/reports/exportReport.ts <<'TS'
import { toCsv } from "./csv";
import { Column, DEFAULT_COLUMNS } from "./columns";

export interface Row {
  day: Date;
  account: string;
  amount: number;
}

export function exportReport(rows: Row[], columns: Column[] = DEFAULT_COLUMNS): string {
  const header = columns.map((c) => c.header);
  const body = rows.map((r) => columns.map((c) => String((r as any)[c.key])));
  return toCsv([header, ...body]);
}
TS
c 2024-08-05 "feat: report export scaffold"
cat > src/dates/timezone.ts <<'TS'
export const REPORT_TZ = "UTC";

export function toUtcMidnight(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
}
TS
cat > src/dates/format.ts <<'TS'
import { toUtcMidnight } from "./timezone";

export function formatDay(d: Date): string {
  const m = toUtcMidnight(d);
  return m.getUTCFullYear() + "-" + (m.getUTCMonth() + 1) + "-" + m.getUTCDate();
}
TS
c 2024-08-19 "feat(dates): date formatting helpers"
cat > src/dates/monthRange.ts <<'TS'
export interface DateRange {
  start: Date;
  end: Date;
}

export function monthRange(year: number, month: number): DateRange {
  const start = new Date(Date.UTC(year, month, 1));
  const end = new Date(Date.UTC(year, month + 1, 0, 23, 59, 59));
  return { start, end };
}

export function previousMonth(now: Date): DateRange {
  return monthRange(now.getUTCFullYear(), now.getUTCMonth() - 1);
}

export function inRange(d: Date, r: DateRange): boolean {
  return d.getTime() >= r.start.getTime() && d.getTime() <= r.end.getTime();
}
TS
cat > src/reports/query.ts <<'TS'
import { DateRange, monthRange } from "../dates/monthRange";

export interface ReportQuery {
  range: DateRange;
  account?: string;
}

export function queryForMonth(year: number, month: number): ReportQuery {
  return { range: monthRange(year, month) };
}
TS
cat > src/reports/exportReport.ts <<'TS'
import { toCsv } from "./csv";
import { Column, DEFAULT_COLUMNS } from "./columns";
import { formatDay } from "../dates/format";
import { DateRange, inRange } from "../dates/monthRange";

export interface Row {
  day: Date;
  account: string;
  amount: number;
}

export function exportReport(rows: Row[], range: DateRange, columns: Column[] = DEFAULT_COLUMNS): string {
  const header = columns.map((c) => c.header);
  const body = rows
    .filter((r) => inRange(r.day, range))
    .map((r) => columns.map((c) => (c.key === "day" ? formatDay(r.day) : String((r as any)[c.key]))));
  return toCsv([header, ...body]);
}
TS
c 2024-09-02 "feat(dates): month ranges for report filters"
cat > src/api/auth.ts <<'TS'
export interface Session {
  userId: string;
  canExport: boolean;
}

export function requireExport(s: Session | undefined): Session {
  if (!s || !s.canExport) throw new Error("forbidden");
  return s;
}
TS
cat > src/api/reportsRoute.ts <<'TS'
import { requireExport, Session } from "./auth";
import { exportReport, Row } from "../reports/exportReport";
import { queryForMonth } from "../reports/query";

export function handleExport(session: Session | undefined, rows: Row[], year: number, month: number) {
  requireExport(session);
  const q = queryForMonth(year, month);
  return { contentType: "text/csv", body: exportReport(rows, q.range) };
}
TS
c 2024-09-16 "feat(api): reports export route"
t src/reports/csv.ts; c 2024-10-01 "fix(csv): escape embedded quotes"
t src/reports/columns.ts src/reports/exportReport.ts; c 2024-10-14 "feat(reports): configurable columns"
v 2.0.0; c 2024-10-28 "chore: release v2.0.0"
t src/dates/monthRange.ts; c 2024-11-12 "fix(dates): month range skipped from December to January"
t src/reports/exportReport.ts; c 2024-11-25 "feat(reports): add totals row"
t src/api/reportsRoute.ts; c 2024-12-09 "chore(api): tidy export handler"
t src/dates/monthRange.ts; c 2025-01-13 "fix(dates): previous month was wrong in January"
t src/reports/query.ts; c 2025-01-27 "feat(reports): account filter on report query"
t src/reports/csv.ts; c 2025-02-10 "fix(csv): quote cells containing newlines"
t src/reports/csv.ts src/reports/exportReport.ts; c 2025-02-24 "feat(reports): semicolon-delimited export option"
v 2.1.0; c 2025-03-10 "chore: release v2.1.0"
t src/dates/monthRange.ts; c 2025-03-24 "fix(dates): month range end shifted by timezone offset"
t src/dates/format.ts; c 2025-04-07 "feat(dates): locale-aware month names"
t src/api/reportsRoute.ts src/api/auth.ts; c 2025-04-21 "feat(api): rate-limit the export endpoint"
t src/dates/monthRange.ts; c 2025-05-05 "fix(dates): inRange dropped rows in the last second of the month"
t src/reports/exportReport.ts; c 2025-05-19 "feat(reports): streaming export for large reports"
v 2.2.0; c 2025-06-02 "chore: release v2.2.0"
t src/reports/query.ts; c 2025-06-16 "feat(reports): sort report by column"
t src/dates/format.ts; c 2025-06-30 "fix(format): pad single-digit days"
t src/reports/columns.ts; c 2025-07-14 "feat(reports): column presets"
t src/api/auth.ts; c 2025-07-28 "chore(api): rename session fields"
t src/dates/monthRange.ts; c 2025-08-11 "fix(dates): February range in leap years"
t src/reports/columns.ts src/reports/exportReport.ts; c 2025-08-25 "feat(reports): account name column"
v 2.3.0; c 2025-09-02 "chore: release v2.3.0"
cat > src/reports/exportReport.ts <<'TS'
import { toCsv } from "./csv";
import { Column, DEFAULT_COLUMNS } from "./columns";
import { formatDay } from "../dates/format";
import { DateRange, inRange, previousMonth } from "../dates/monthRange";

export interface Row {
  day: Date;
  account: string;
  amount: number;
}

export type Preset = "previous-month" | "custom";

export function rangeForPreset(preset: Preset, now: Date, custom?: DateRange): DateRange {
  if (preset === "previous-month") return previousMonth(now);
  if (!custom) throw new Error("custom range required");
  return custom;
}

export function exportReport(rows: Row[], range: DateRange, columns: Column[] = DEFAULT_COLUMNS): string {
  const header = columns.map((c) => c.header);
  const body = rows
    .filter((r) => inRange(r.day, range))
    .map((r) => columns.map((c) => (c.key === "day" ? formatDay(r.day) : String((r as any)[c.key]))));
  return toCsv([header, ...body]);
}
TS
c 2025-09-15 "feat(reports): 'Previous month' preset in the export dialog"
t src/api/reportsRoute.ts; c 2025-09-22 "feat(api): export filename includes the period"
t src/reports/csv.ts; c 2025-09-29 "fix(csv): no trailing delimiter on empty rows"
cat > src/dates/monthRange.ts <<'TS'
export interface DateRange {
  start: Date;
  end: Date;
}

export function monthRange(year: number, month: number): DateRange {
  const start = new Date(Date.UTC(year, month, 1));
  const end = new Date(Date.UTC(year, month + 1, 1));
  return { start, end };
}

export function previousMonth(now: Date): DateRange {
  return monthRange(now.getUTCFullYear(), now.getUTCMonth() - 1);
}

export function inRange(d: Date, r: DateRange): boolean {
  return d.getTime() >= r.start.getTime() && d.getTime() <= r.end.getTime();
}
TS
c 2025-10-06 "fix(dates): use the start of next month as the range end"
v 2.4.0; c 2025-10-08 "chore: release v2.4.0"
