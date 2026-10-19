#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
# A seeded generator writes a TS workspace (~300 files, 11 packages, `@app/*` path aliases,
# barrel index.ts re-exports) in 4 commits. An existing helper already does "call again with a
# growing pause": `withPolicy` in packages/platform/src/net/resilience/policy.ts, re-exported
# from `@app/platform` and used by two callers in other packages. No file or symbol in the
# repo says "retry" or "backoff". The ask is a retry with exponential delay around
# `fetchInvoice` in packages/billing/src/gateway/invoiceClient.ts; the right answer reuses
# withPolicy.
set -e
gen=$(mktemp "${TMPDIR:-/tmp}/gen73.XXXXXX")
trap 'rm -f "$gen"' EXIT
cat > "$gen" <<'PY'
import json, os, random, subprocess, sys

rng = random.Random(73)
PKGS = [
    ("platform", ["net", "time"]), ("http", ["client", "codecs"]),
    ("billing", ["gateway", "ledger"]), ("pricing", ["rules", "quotes"]),
    ("orders", ["checkout", "fulfilment"]), ("catalog", ["feed", "products"]),
    ("inventory", ["stock", "warehouse"]), ("shipping", ["rates", "labels"]),
    ("notify", ["hooks", "email"]), ("auth", ["session", "tokens"]),
    ("reports", ["monthly", "exports"]),
]
VERBS = ["build", "compute", "resolve", "collect", "apply", "merge", "derive", "load", "split",
         "score", "check", "map", "group", "rank", "parse", "render", "sum", "align", "track",
         "plan", "price", "count", "scan", "sort"]
NOUNS = ["Ledger", "Batch", "Window", "Quota", "Bucket", "Cursor", "Slot", "Tier", "Route",
         "Margin", "Entry", "Range", "Basket", "Credit", "Rebate", "Voucher", "Parcel", "Label",
         "Digest", "Badge", "Token", "Session", "Filter", "Facet", "Shard", "Lane", "Stamp",
         "Ticket", "Period", "Report", "Column", "Region", "Carrier", "Zone", "Sku", "Stock"]
FILES_PER_DIR = 12

used = set()
def fresh_name():
    while True:
        n = rng.choice(VERBS) + rng.choice(NOUNS) + rng.choice(["", "s", "Map", "Set", "Plan", "View"])
        if n not in used:
            used.add(n)
            return n

files = {}
def put(path, text):
    files[path] = text

# Noise: small modules with imports inside their package and across packages via aliases.
mods = []
for pkg, subs in PKGS:
    for sub in subs:
        for _ in range(FILES_PER_DIR):
            mods.append((pkg, sub, fresh_name(), rng.randint(0, 4)))
mods.sort(key=lambda m: (m[3], m[0], m[1], m[2]))
for i, (pkg, sub, name, level) in enumerate(mods):
    lower = [m for m in mods[:i] if m[3] < level]
    picks = rng.sample(lower, min(len(lower), rng.randint(0, 2))) if level else []
    lines, calls = [], []
    for (p2, s2, n2, _) in picks:
        spec = (f"../{s2}/{n2}" if s2 != sub else f"./{n2}") if p2 == pkg else f"@app/{p2}/{s2}/{n2}"
        lines.append(f'import {{ {n2} }} from "{spec}";'); calls.append(f"{n2}(x)")
    k = (sum(map(ord, name)) % 7) + 1
    expr = " + ".join(calls) if calls else f"x * {k}"
    put(f"packages/{pkg}/src/{sub}/{name}.ts",
        "\n".join(lines) + ("\n\n" if lines else "") + f"export function {name}(x: number): number {{\n  return {expr} + {k};\n}}\n")

# Timer code elsewhere, so `setTimeout` alone does not point at the helper.
put("packages/platform/src/time/pause.ts",
    "/** Resolve after `ms` milliseconds. */\nexport function pause(ms: number): Promise<void> {\n"
    "  return new Promise((resolve) => setTimeout(resolve, ms));\n}\n")
put("packages/catalog/src/products/debounceSearch.ts",
    "export function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number) {\n"
    "  let t: ReturnType<typeof setTimeout> | undefined;\n  return (...a: A) => {\n"
    "    if (t) clearTimeout(t);\n    t = setTimeout(() => fn(...a), ms);\n  };\n}\n")
put("packages/inventory/src/warehouse/pollCounts.ts",
    "export function every(ms: number, tick: () => void): () => void {\n"
    "  const h = setInterval(tick, ms);\n  return () => clearInterval(h);\n}\n")
put("packages/reports/src/exports/scheduleExport.ts",
    "export function later(ms: number, job: () => void): void {\n  setTimeout(job, ms);\n}\n")

# The helper, behind a barrel, with a name and path that do not say what it is for.
put("packages/platform/src/net/resilience/policy.ts",
    'import { pause } from "../../time/pause";\n\n'
    "export interface Policy {\n  /** Total calls, the first one included. */\n  attempts: number;\n"
    "  /** Pause before the second call, in ms; it doubles after each failed call. */\n  pauseMs: number;\n"
    "  /** Upper bound for one pause, in ms. */\n  maxPauseMs?: number;\n"
    "  /** Return false to stop at once on this error. */\n  keepGoing?: (err: unknown) => boolean;\n}\n\n"
    "/** Run `fn` under a policy: on failure, pause and call it again until it succeeds or the\n"
    " * attempts run out. Rethrows the last error. */\n"
    "export async function withPolicy<T>(fn: () => Promise<T>, policy: Policy): Promise<T> {\n"
    "  let wait = policy.pauseMs;\n  for (let n = 1; ; n++) {\n    try {\n      return await fn();\n"
    "    } catch (err) {\n      if (n >= policy.attempts || (policy.keepGoing && !policy.keepGoing(err))) throw err;\n"
    "      await pause(Math.min(wait, policy.maxPauseMs ?? Number.POSITIVE_INFINITY));\n      wait *= 2;\n    }\n  }\n}\n")
put("packages/platform/src/index.ts",
    'export * from "./net/resilience/policy";\nexport * from "./time/pause";\n')

put("packages/http/src/client/json.ts",
    "export interface JsonResponse<T> {\n  status: number;\n  body: T;\n}\n\n"
    "export class UpstreamError extends Error {\n  constructor(readonly status: number, url: string) {\n"
    "    super(`upstream ${status} for ${url}`);\n  }\n}\n\n"
    "export async function getJson<T>(url: string): Promise<JsonResponse<T>> {\n"
    '  const res = await fetch(url, { headers: { accept: "application/json" } });\n'
    "  if (res.status >= 500) throw new UpstreamError(res.status, url);\n"
    "  return { status: res.status, body: (await res.json()) as T };\n}\n\n"
    "export async function postJson(url: string, payload: unknown): Promise<number> {\n"
    '  const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });\n'
    "  if (res.status >= 500) throw new UpstreamError(res.status, url);\n  return res.status;\n}\n")
put("packages/http/src/index.ts", 'export * from "./client/json";\n')

put("packages/catalog/src/feed/pullFeed.ts",
    'import { getJson } from "@app/http";\nimport { withPolicy } from "@app/platform";\n\n'
    "export interface FeedItem {\n  sku: string;\n  name: string;\n}\n\n"
    "export async function pullFeed(url: string): Promise<FeedItem[]> {\n"
    "  const res = await withPolicy(() => getJson<FeedItem[]>(url), { attempts: 4, pauseMs: 250, maxPauseMs: 4_000 });\n"
    "  return res.body;\n}\n")
put("packages/notify/src/hooks/deliverHook.ts",
    'import { postJson } from "@app/http";\nimport { withPolicy } from "@app/platform";\n\n'
    "export async function deliverHook(url: string, event: { type: string; id: string }): Promise<void> {\n"
    "  const status = await withPolicy(() => postJson(url, event), {\n    attempts: 3,\n    pauseMs: 500,\n"
    "    keepGoing: (err) => !(err instanceof TypeError),\n  });\n"
    "  if (status >= 400) throw new Error(`hook rejected with ${status}`);\n}\n")

CLIENT = ('import { getJson } from "@app/http";\n\n'
          "export interface Invoice {\n  number: string;\n  customerId: string;\n  totalCents: number;\n}\n\n"
          'const BASE_URL = process.env.BILLING_URL ?? "https://billing.example.test/api";\n\n'
          "export async function fetchInvoice(invoiceNumber: string): Promise<Invoice> {\n"
          "  const res = await getJson<Invoice>(`${BASE_URL}/invoices/${encodeURIComponent(invoiceNumber)}`);\n"
          "  if (res.status === 404) throw new Error(`invoice ${invoiceNumber} not found`);\n"
          "  return res.body;\n}\n")
put("packages/billing/src/gateway/invoiceClient.ts", CLIENT)
put("packages/billing/src/ledger/monthClose.ts",
    'import { fetchInvoice, Invoice } from "../gateway/invoiceClient";\n\n'
    "export async function monthTotalCents(numbers: string[]): Promise<number> {\n"
    "  const all: Invoice[] = [];\n  for (const n of numbers) all.push(await fetchInvoice(n));\n"
    "  return all.reduce((s, i) => s + i.totalCents, 0);\n}\n")

paths = {}
for pkg, _ in PKGS:
    paths[f"@app/{pkg}"] = [f"packages/{pkg}/src/index.ts"]
    paths[f"@app/{pkg}/*"] = [f"packages/{pkg}/src/*"]
    put(f"packages/{pkg}/package.json", json.dumps({"name": f"@app/{pkg}", "version": "0.6.0", "main": "src/index.ts"}, indent=2) + "\n")
put("tsconfig.json", json.dumps({"compilerOptions": {"target": "ES2022", "module": "commonjs", "strict": True,
                                 "baseUrl": ".", "paths": paths}}, indent=2) + "\n")
put("package.json", json.dumps({"name": "commerce-workspace", "private": True, "workspaces": ["packages/*"],
                                "scripts": {"test": "vitest run"}}, indent=2) + "\n")
put("README.md", "# commerce-workspace\n\nTypeScript packages for billing, pricing, orders, catalog and more. "
                 "Packages import each other through the `@app/*` path aliases in `tsconfig.json`.\n")

for p, t in files.items():
    low = t.lower()
    assert "retry" not in low and "backoff" not in low and "back-off" not in low, p

def commit(root, date, msg):
    env = dict(os.environ, GIT_AUTHOR_DATE=f"{date}T10:00:00+00:00", GIT_COMMITTER_DATE=f"{date}T10:00:00+00:00")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=dev", "-c", "user.email=dev@example.com", "-c", "commit.gpgsign=false",
                    "-c", "core.hooksPath=/dev/null", "commit", "-qm", msg], cwd=root, check=True, env=env)

def write(root, keys):
    for p in keys:
        full = os.path.join(root, p)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(files[p])

if sys.argv[1] == "--count":
    print(len(files)); sys.exit(0)
root = sys.argv[1]
special = {"packages/platform/src/net/resilience/policy.ts", "packages/platform/src/index.ts",
           "packages/catalog/src/feed/pullFeed.ts", "packages/notify/src/hooks/deliverHook.ts"}
write(root, [p for p in files if p not in special]); commit(root, "2025-01-13", "feat: workspace packages, http client, billing gateway")
write(root, ["packages/platform/src/net/resilience/policy.ts", "packages/platform/src/index.ts"])
commit(root, "2025-03-10", "feat(platform): call policies for flaky upstreams")
write(root, ["packages/catalog/src/feed/pullFeed.ts"]); commit(root, "2025-03-24", "feat(catalog): pull the feed under a call policy")
write(root, ["packages/notify/src/hooks/deliverHook.ts"]); commit(root, "2025-04-14", "feat(notify): hooks use a call policy")
PY
if [ "${1:-}" = "--count" ]; then python3 "$gen" --count; exit 0; fi
mkdir app && cd app && git init -q -b main
python3 "$gen" "$PWD"
