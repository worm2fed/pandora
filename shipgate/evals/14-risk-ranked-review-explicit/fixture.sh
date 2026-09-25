#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
n=0
t() { for f in "$@"; do n=$((n+1)); grep -v '^// build ' "$f" > "$f.tmp" || true; mv "$f.tmp" "$f"; echo "// build $(echo "$n" | cksum | cut -d' ' -f1)" >> "$f"; done; }
mkdir -p src/checkout src/payments src/shared
printf '{\n  "name": "checkout-service",\n  "version": "1.0.0",\n  "private": true\n}\n' > package.json
printf '# checkout-service\n\nCart, promotions and payment capture.\n' > README.md
cat > src/shared/money.ts <<'TS'
export type Cents = number;

export function addCents(a: Cents, b: Cents): Cents {
  return a + b;
}

export function percentOf(amount: Cents, percent: number): Cents {
  return Math.round((amount * percent) / 100);
}
TS
cat > src/shared/logger.ts <<'TS'
export function log(event: string, data: Record<string, unknown> = {}): void {
  console.log(JSON.stringify({ event, ...data }));
}
TS
cat > src/shared/calendar.ts <<'TS'
export interface Window {
  from: Date;
  to: Date;
}

export function startOfDay(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
}

export function addDays(d: Date, days: number): Date {
  return new Date(d.getTime() + days * 86_400_000);
}
TS
c 2024-09-02 "feat(shared): money, logging and calendar helpers"
cat > src/payments/ledger.ts <<'TS'
import { Cents, addCents } from "../shared/money";
import { log } from "../shared/logger";

export type EntryKind = "charge" | "refund" | "fee" | "adjustment";

export interface Entry {
  orderId: string;
  kind: EntryKind;
  amount: Cents;
  at: Date;
}

const entries: Entry[] = [];

export function record(entry: Entry): void {
  if (!Number.isInteger(entry.amount)) throw new Error("amount must be whole cents");
  entries.push(entry);
  log("ledger.record", { orderId: entry.orderId, kind: entry.kind, amount: entry.amount });
}

export function balance(orderId: string): Cents {
  return entries
    .filter((e) => e.orderId === orderId)
    .reduce((sum, e) => addCents(sum, e.kind === "refund" ? -e.amount : e.amount), 0);
}

export function entriesFor(orderId: string): Entry[] {
  return entries.filter((e) => e.orderId === orderId);
}
TS
c 2024-09-16 "feat(payments): double-entry ledger"
cat > src/checkout/promo.ts <<'TS'
import { Cents, percentOf } from "../shared/money";
import { startOfDay } from "../shared/calendar";

export interface Promo {
  code: string;
  percent: number;
  expires: Date;
}

export function discountFor(promo: Promo, subtotal: Cents, now: Date): Cents {
  if (startOfDay(now) > promo.expires) return 0;
  return percentOf(subtotal, promo.percent);
}
TS
cat > src/checkout/cart.ts <<'TS'
import { Cents, addCents } from "../shared/money";
import { Promo, discountFor } from "./promo";

export interface CartLine {
  sku: string;
  price: Cents;
  qty: number;
}

export function subtotal(lines: CartLine[]): Cents {
  return lines.reduce((sum, l) => addCents(sum, l.price * l.qty), 0);
}

export function total(lines: CartLine[], promo: Promo | undefined, now: Date): Cents {
  const sub = subtotal(lines);
  return promo ? sub - discountFor(promo, sub, now) : sub;
}
TS
c 2024-09-30 "feat(checkout): cart totals with promo codes"
cat > src/payments/gateway.ts <<'TS'
import { record } from "./ledger";
import { log } from "../shared/logger";

export interface CaptureRequest {
  orderId: string;
  amount: number;
  idempotencyKey: string;
}

const seen = new Set<string>();

export async function capture(req: CaptureRequest, send: (r: CaptureRequest) => Promise<boolean>): Promise<boolean> {
  if (seen.has(req.idempotencyKey)) return true;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (await send(req)) {
      seen.add(req.idempotencyKey);
      record({ orderId: req.orderId, kind: "charge", amount: req.amount, at: new Date() });
      return true;
    }
    log("gateway.retry", { orderId: req.orderId, attempt });
  }
  return false;
}
TS
c 2024-10-07 "feat(payments): gateway capture with idempotency and retries"
cat > src/checkout/shipping.ts <<'TS'
import { Cents } from "../shared/money";

export function shippingFor(subtotal: Cents, country: string): Cents {
  if (subtotal >= 5000) return 0;
  return country === "domestic" ? 490 : 1290;
}
TS
cat > src/checkout/checkoutFlow.ts <<'TS'
import { CartLine, total } from "./cart";
import { Promo } from "./promo";
import { shippingFor } from "./shipping";
import { capture } from "../payments/gateway";

export async function checkout(orderId: string, lines: CartLine[], promo: Promo | undefined, country: string, send: any) {
  const goods = total(lines, promo, new Date());
  const amount = goods + shippingFor(goods, country);
  return capture({ orderId, amount, idempotencyKey: orderId }, send);
}
TS
c 2024-10-21 "feat(checkout): checkout flow"
cat > src/payments/receipts.ts <<'TS'
import { entriesFor } from "./ledger";
import { startOfDay } from "../shared/calendar";

export function receiptLines(orderId: string): string[] {
  return entriesFor(orderId).map((e) => startOfDay(e.at).toISOString().slice(0, 10) + " " + e.kind + " " + e.amount);
}
TS
c 2024-11-04 "feat(payments): receipts"
t src/payments/ledger.ts; c 2024-11-18 "chore(payments): ledger entry docs"
t src/checkout/cart.ts; c 2024-12-02 "feat(checkout): cart line quantities"
t src/checkout/shipping.ts; c 2024-12-16 "feat(checkout): free shipping threshold"
t src/checkout/promo.ts; c 2025-01-13 "feat(checkout): promo codes are case-insensitive"
t src/payments/gateway.ts; c 2025-01-20 "feat(payments): gateway timeout setting"
t src/shared/calendar.ts; c 2025-02-10 "fix(shared): addDays across DST change"
t src/shared/money.ts; c 2025-02-24 "fix(shared): percentOf rounding for negative amounts"
t src/checkout/checkoutFlow.ts; c 2025-03-10 "feat(checkout): pass country to shipping"
t src/payments/receipts.ts; c 2025-03-24 "feat(payments): receipt dates in ISO format"
t src/checkout/shipping.ts; c 2025-04-07 "fix(checkout): international shipping price"
t src/checkout/checkoutFlow.ts src/checkout/shipping.ts; c 2025-04-28 "feat(checkout): shipping shown before payment"
t src/checkout/promo.ts; c 2025-05-12 "fix(checkout): expired promo still applied on expiry day"
t src/shared/logger.ts; c 2025-05-26 "chore(shared): structured log fields"
t src/shared/calendar.ts; c 2025-06-09 "fix(shared): startOfDay used local time"
t src/checkout/promo.ts; c 2025-07-07 "fix(checkout): promo percent over 100 accepted"
t src/shared/calendar.ts; c 2025-07-21 "feat(shared): calendar windows"
t src/shared/calendar.ts; c 2025-08-04 "fix(shared): window end excluded the last day"
t src/checkout/promo.ts; c 2025-08-18 "fix(checkout): promo discount applied twice with a second code"
t src/checkout/promo.ts; c 2025-09-01 "feat(checkout): stackable promo flag"
t src/checkout/checkoutFlow.ts; c 2025-09-08 "fix(checkout): retry after declined card reused old total"
t src/shared/calendar.ts; c 2025-09-15 "fix(shared): addDays off by one hour at month end"
t src/checkout/promo.ts; c 2025-09-29 "fix(checkout): stackable promos rounded per code"
t src/payments/receipts.ts; c 2025-10-06 "chore(payments): receipt line format"
t src/shared/calendar.ts; c 2025-10-13 "fix(shared): window comparison ignored time zone"
t src/checkout/promo.ts; c 2025-10-27 "fix(checkout): promo expiry compared against server time"
t src/shared/calendar.ts; c 2025-11-03 "fix(shared): startOfDay for dates before 1970"
t src/checkout/promo.ts; c 2025-11-10 "fix(checkout): case-insensitive match broke codes with digits"
python3 - <<'PY'
import re

def edit(path, old, new):
    s = open(path).read()
    assert old in s, (path, old)
    open(path, "w").write(s.replace(old, new, 1))

edit("src/shared/calendar.ts", "export function addDays", "export function isWithin(d: Date, w: Window): boolean {\n  return d >= w.from && d <= w.to;\n}\n\nexport function addDays")
edit("src/checkout/promo.ts", "import { startOfDay } from \"../shared/calendar\";", "import { Window, isWithin, startOfDay } from \"../shared/calendar\";")
edit("src/checkout/promo.ts", "  expires: Date;\n}", "  expires: Date;\n  activeWindow?: Window;\n}")
edit("src/checkout/promo.ts", "  if (startOfDay(now) > promo.expires) return 0;", "  if (startOfDay(now) > promo.expires) return 0;\n  if (promo.activeWindow && !isWithin(now, promo.activeWindow)) return 0;")
edit("src/checkout/cart.ts", "export function total(", "export function discount(lines: CartLine[], promo: Promo | undefined, now: Date): Cents {\n  return promo ? discountFor(promo, subtotal(lines), now) : 0;\n}\n\nexport function total(")
edit("src/checkout/cart.ts", "  const sub = subtotal(lines);\n  return promo ? sub - discountFor(promo, sub, now) : sub;", "  return subtotal(lines) - discount(lines, promo, now);")
edit("src/payments/ledger.ts", "export type EntryKind = \"charge\" | \"refund\" | \"fee\" | \"adjustment\";", "export type EntryKind = \"charge\" | \"refund\" | \"fee\" | \"adjustment\" | \"promo\";")
edit("src/payments/ledger.ts", "  amount: Cents;\n  at: Date;\n}", "  amount: Cents;\n  at: Date;\n  promoCode?: string;\n}")
edit("src/payments/ledger.ts", "e.kind === \"refund\" ? -e.amount", "e.kind === \"refund\" || e.kind === \"promo\" ? -e.amount")
edit("src/payments/ledger.ts", "log(\"ledger.record\", { orderId: entry.orderId, kind: entry.kind, amount: entry.amount });", "log(\"ledger.record\", { orderId: entry.orderId, kind: entry.kind, amount: entry.amount, promoCode: entry.promoCode });")
edit("src/payments/ledger.ts", "export function entriesFor", "export function promoTotal(orderId: string): Cents {\n  return entries\n    .filter((e) => e.orderId === orderId && e.kind === \"promo\")\n    .reduce((sum, e) => addCents(sum, e.amount), 0);\n}\n\nexport function entriesFor")
edit("src/payments/gateway.ts", "  idempotencyKey: string;\n}", "  idempotencyKey: string;\n  promoCode?: string;\n  promoAmount?: number;\n}")
edit("src/payments/gateway.ts", "      record({ orderId: req.orderId, kind: \"charge\", amount: req.amount, at: new Date() });", "      const at = new Date();\n      record({ orderId: req.orderId, kind: \"charge\", amount: req.amount, at });\n      if (req.promoCode && req.promoAmount) {\n        record({ orderId: req.orderId, kind: \"promo\", amount: req.promoAmount, at, promoCode: req.promoCode });\n      }")
PY
c 2025-11-20 "feat(checkout): time-windowed promo codes recorded in the ledger"
