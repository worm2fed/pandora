#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
# The repo already has a backoff helper under a name that does not say "retry"
# (src/util/backoff.ts, withBackoff) with two callers. The ask is a retry with
# exponential delay around fetchInvoice; the right answer reuses withBackoff.
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
mkdir -p src/util src/billing src/catalog src/notify test
printf '{\n  "name": "ledger-sync",\n  "version": "0.3.0",\n  "private": true,\n  "scripts": { "test": "vitest run" }\n}\n' > package.json
printf '# ledger-sync\n\nPulls invoices and catalog data from upstream services and sends webhooks.\n' > README.md
cat > src/util/http.ts <<'TS'
export interface HttpResponse<T> {
  status: number;
  body: T;
}

export async function getJson<T>(url: string): Promise<HttpResponse<T>> {
  const res = await fetch(url, { headers: { accept: "application/json" } });
  if (res.status >= 500) {
    throw new Error(`upstream ${res.status} for ${url}`);
  }
  return { status: res.status, body: (await res.json()) as T };
}

export async function postJson(url: string, payload: unknown): Promise<number> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.status >= 500) {
    throw new Error(`upstream ${res.status} for ${url}`);
  }
  return res.status;
}
TS
c 2025-01-13 "feat(util): JSON HTTP helpers"
cat > src/billing/client.ts <<'TS'
import { getJson } from "../util/http";

export interface Invoice {
  number: string;
  customerId: string;
  totalCents: number;
}

const BASE_URL = "https://billing.example.test/api";

export async function fetchInvoice(invoiceNumber: string): Promise<Invoice> {
  const res = await getJson<Invoice>(`${BASE_URL}/invoices/${encodeURIComponent(invoiceNumber)}`);
  if (res.status === 404) {
    throw new Error(`invoice ${invoiceNumber} not found`);
  }
  return res.body;
}
TS
cat > src/billing/report.ts <<'TS'
import { fetchInvoice, Invoice } from "./client";

export async function monthlyTotalCents(numbers: string[]): Promise<number> {
  const invoices: Invoice[] = [];
  for (const n of numbers) {
    invoices.push(await fetchInvoice(n));
  }
  return invoices.reduce((sum, inv) => sum + inv.totalCents, 0);
}
TS
c 2025-02-03 "feat(billing): invoice client and monthly report"
cat > src/util/backoff.ts <<'TS'
export interface BackoffOptions {
  /** Total attempts, the first one included. */
  attempts: number;
  /** Delay before the second attempt, in ms; doubles after each failure. */
  baseDelayMs: number;
  /** Upper bound for one delay, in ms. */
  maxDelayMs?: number;
  /** Return false to give up at once on this error. */
  shouldContinue?: (err: unknown) => boolean;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Run `fn`; on failure, wait and run it again, doubling the wait each time,
 * until it succeeds or the attempts run out. Rethrows the last error.
 */
export async function withBackoff<T>(fn: () => Promise<T>, opts: BackoffOptions): Promise<T> {
  let delay = opts.baseDelayMs;
  for (let attempt = 1; ; attempt++) {
    try {
      return await fn();
    } catch (err) {
      const giveUp = attempt >= opts.attempts || (opts.shouldContinue && !opts.shouldContinue(err));
      if (giveUp) throw err;
      await sleep(Math.min(delay, opts.maxDelayMs ?? Number.POSITIVE_INFINITY));
      delay *= 2;
    }
  }
}
TS
cat > test/backoff.test.ts <<'TS'
import { describe, expect, it } from "vitest";
import { withBackoff } from "../src/util/backoff";

describe("withBackoff", () => {
  it("returns the first success", async () => {
    let calls = 0;
    const v = await withBackoff(async () => {
      calls++;
      if (calls < 3) throw new Error("flaky");
      return 42;
    }, { attempts: 5, baseDelayMs: 1 });
    expect(v).toBe(42);
    expect(calls).toBe(3);
  });

  it("rethrows after the last attempt", async () => {
    await expect(withBackoff(async () => { throw new Error("down"); }, { attempts: 2, baseDelayMs: 1 }))
      .rejects.toThrow("down");
  });
});
TS
c 2025-03-10 "feat(util): exponential backoff helper"
cat > src/catalog/sync.ts <<'TS'
import { getJson } from "../util/http";
import { withBackoff } from "../util/backoff";

export interface CatalogItem {
  sku: string;
  name: string;
}

export async function pullCatalog(feedUrl: string): Promise<CatalogItem[]> {
  const res = await withBackoff(() => getJson<CatalogItem[]>(feedUrl), {
    attempts: 4,
    baseDelayMs: 250,
    maxDelayMs: 4_000,
  });
  return res.body;
}
TS
c 2025-03-24 "feat(catalog): pull the catalog feed with backoff"
cat > src/notify/webhook.ts <<'TS'
import { postJson } from "../util/http";
import { withBackoff } from "../util/backoff";

export async function sendWebhook(url: string, event: { type: string; id: string }): Promise<void> {
  const status = await withBackoff(() => postJson(url, event), {
    attempts: 3,
    baseDelayMs: 500,
    shouldContinue: (err) => !(err instanceof TypeError),
  });
  if (status >= 400) {
    throw new Error(`webhook rejected with ${status}`);
  }
}
TS
c 2025-04-14 "feat(notify): webhooks back off on upstream errors"
sed -i.bak 's/^const BASE_URL = .*/const BASE_URL = process.env.BILLING_URL ?? "https:\/\/billing.example.test\/api";/' src/billing/client.ts && rm -f src/billing/client.ts.bak
c 2025-05-05 "chore(billing): base URL from BILLING_URL"
cat >> src/billing/report.ts <<'TS'

export async function largestInvoice(numbers: string[]): Promise<Invoice | undefined> {
  let best: Invoice | undefined;
  for (const n of numbers) {
    const inv = await fetchInvoice(n);
    if (!best || inv.totalCents > best.totalCents) best = inv;
  }
  return best;
}
TS
c 2025-06-02 "feat(billing): largest invoice in a batch"
