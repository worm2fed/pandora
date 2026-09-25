#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
n=0
t() { for f in "$@"; do n=$((n+1)); grep -v '^// build ' "$f" > "$f.tmp" || true; mv "$f.tmp" "$f"; echo "// build $(echo "$n" | cksum | cut -d' ' -f1)" >> "$f"; done; }
mkdir -p src/util src/billing src/catalog
printf '{\n  "name": "storefront-core",\n  "version": "0.1.0",\n  "private": true\n}\n' > package.json
printf '# storefront-core\n\nPricing, billing and catalog logic.\n' > README.md
cat > src/util/round.ts <<'TS'
export function roundTo(value: number, decimals: number): number {
  const f = 10 ** decimals;
  return Math.round(value * f) / f;
}

export function roundCents(value: number): number {
  return roundTo(value, 2);
}
TS
cat > src/util/slugify.ts <<'TS'
export function slugify(s: string): string {
  return s
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
TS
c 2024-07-08 "feat(util): rounding and slug helpers"
cat > src/util/currency.ts <<'TS'
import { roundCents } from "./round";

export function toCents(amount: number): number {
  return Math.trunc(roundCents(amount) * 100);
}

export function formatMoney(cents: number, currency = "EUR"): string {
  return (cents / 100).toFixed(2) + " " + currency;
}
TS
cat > src/util/percent.ts <<'TS'
import { roundTo } from "./round";

export function applyPercent(amount: number, percent: number): number {
  return roundTo((amount * percent) / 100, 2);
}
TS
c 2024-07-22 "feat(util): currency and percent helpers"
cat > src/catalog/product.ts <<'TS'
import { slugify } from "../util/slugify";

export interface Product {
  id: string;
  slug: string;
  name: string;
  priceCents: number;
}

export function makeProduct(id: string, name: string, price: number): Product {
  return { id, slug: slugify(name), name, priceCents: Math.round(price * 100) };
}
TS
cat > src/catalog/search.ts <<'TS'
import { Product } from "./product";
import { slugify } from "../util/slugify";

export function search(products: Product[], query: string): Product[] {
  const q = slugify(query);
  return products.filter((p) => p.slug.includes(q));
}
TS
c 2024-08-12 "feat(catalog): products and search"
cat > src/billing/lineItem.ts <<'TS'
import { toCents } from "../util/currency";

export interface LineItem {
  sku: string;
  unitPrice: number;
  qty: number;
}

export function lineTotalCents(item: LineItem): number {
  return toCents(item.unitPrice) * item.qty;
}
TS
cat > src/billing/tax.ts <<'TS'
import { applyPercent } from "../util/percent";

export const DEFAULT_VAT = 20;

export function taxFor(net: number, rate = DEFAULT_VAT): number {
  return applyPercent(net, rate);
}
TS
cat > src/billing/invoice.ts <<'TS'
import { LineItem, lineTotalCents } from "./lineItem";
import { taxFor } from "./tax";

export interface Invoice {
  number: string;
  items: LineItem[];
}

export function invoiceTotals(inv: Invoice) {
  const netCents = inv.items.reduce((sum, i) => sum + lineTotalCents(i), 0);
  const taxCents = Math.round(taxFor(netCents / 100) * 100);
  return { netCents, taxCents, grossCents: netCents + taxCents };
}
TS
c 2024-09-09 "feat(billing): invoices with line items and VAT"
cat > src/billing/refundPolicy.ts <<'TS'
export const REFUND_WINDOW_DAYS = 30;

export function isRefundable(orderedAt: Date, now: Date): boolean {
  const days = Math.round((now.getTime() - orderedAt.getTime()) / 86_400_000);
  return days <= REFUND_WINDOW_DAYS;
}
TS
c 2024-09-30 "feat(billing): refund policy"
cat > src/billing/pdfSummary.ts <<'TS'
import { Invoice, invoiceTotals } from "./invoice";

export function summaryLines(inv: Invoice): string[] {
  const t = invoiceTotals(inv);
  return [
    "Invoice " + inv.number,
    "Net: " + (t.netCents / 100).toFixed(2),
    "VAT: " + (t.taxCents / 100).toFixed(2),
    "Total: " + (t.grossCents / 100).toFixed(2),
  ];
}
TS
c 2024-10-21 "feat(billing): PDF summary lines"
t src/catalog/search.ts; c 2024-11-04 "feat(catalog): prefix search"
t src/billing/tax.ts; c 2024-11-18 "fix(billing): reduced VAT rate for books"
t src/util/slugify.ts; c 2024-12-02 "fix(util): slugify collapses repeated dashes"
t src/billing/refundPolicy.ts; c 2024-12-16 "feat(billing): holiday refund extension"
t src/util/currency.ts; c 2024-12-30 "chore(util): currency code constants"
t src/catalog/product.ts; c 2025-01-13 "feat(catalog): product names up to 120 chars"
t src/billing/invoice.ts; c 2025-01-27 "feat(billing): invoice numbers per year"
t src/util/currency.ts; c 2025-02-10 "feat(util): formatMoney accepts a currency"
t src/billing/pdfSummary.ts; c 2025-03-03 "chore(billing): align PDF summary labels"
t src/catalog/search.ts src/catalog/product.ts; c 2025-03-24 "feat(catalog): search by product id"
t src/billing/lineItem.ts; c 2025-04-14 "fix(billing): zero-quantity lines"
t src/util/percent.ts; c 2025-05-05 "chore(util): document percent helpers"
t src/billing/refundPolicy.ts; c 2025-05-26 "fix(billing): refund window counted in UTC days"
t src/catalog/product.ts; c 2025-06-16 "chore(catalog): tidy product factory"
t src/billing/invoice.ts src/billing/pdfSummary.ts; c 2025-07-07 "feat(billing): credit notes reuse invoice totals"
t src/util/slugify.ts; c 2025-07-28 "chore(util): slugify tests moved"
t src/catalog/product.ts; c 2025-08-04 "feat(catalog): product badges"
t src/billing/tax.ts; c 2025-08-18 "feat(billing): VAT rate per country"
t src/catalog/search.ts; c 2025-09-01 "fix(catalog): search ignores accents"
cat > src/util/round.ts <<'TS'
export function roundTo(value: number, decimals: number): number {
  const f = 10 ** decimals;
  return (Math.sign(value) * Math.round(Math.abs(value) * f)) / f;
}

export function roundCents(value: number): number {
  return roundTo(value, 2);
}
TS
c 2025-09-15 "refactor(util): round half away from zero in roundTo"
