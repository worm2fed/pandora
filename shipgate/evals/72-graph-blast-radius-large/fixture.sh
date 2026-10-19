#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
# A seeded generator writes a TS workspace (~480 files, 13 npm-workspace packages named @app/*,
# barrel index.ts re-exports, a few dynamic requires, a __tests__/ tree) in 5 commits. The
# change at HEAD edits one hub module (packages/money/src/rounding/halfEven.ts) and one
# script that nothing imports. `fixture.sh --expected` prints the ground truth as JSON
# (the graders' file lists come from it) and builds nothing.
set -e
gen=$(mktemp "${TMPDIR:-/tmp}/gen72.XXXXXX")
trap 'rm -f "$gen"' EXIT
cat > "$gen" <<'PY'
import json, os, random, subprocess, sys
from collections import defaultdict, deque

rng = random.Random(72)
PKGS = [
    ("core", ["config", "errors"]), ("money", ["rounding", "format"]),
    ("billing", ["invoice", "ledger"]), ("pricing", ["rules", "quotes"]),
    ("orders", ["checkout", "fulfilment"]), ("catalog", ["products", "media"]),
    ("inventory", ["stock", "warehouse"]), ("shipping", ["rates", "labels"]),
    ("notify", ["email", "hooks"]), ("auth", ["session", "tokens"]),
    ("reports", ["monthly", "exports"]), ("search", ["indexer", "query"]),
    ("tools", ["scripts", "dev"]),
]
VERBS = ["build", "compute", "resolve", "collect", "apply", "merge", "derive", "load", "split",
         "score", "check", "map", "group", "rank", "parse", "render", "sum", "align", "track",
         "plan", "price", "count", "scan", "sort"]
NOUNS = ["Ledger", "Batch", "Window", "Quota", "Bucket", "Cursor", "Slot", "Tier", "Route",
         "Margin", "Entry", "Range", "Basket", "Credit", "Rebate", "Voucher", "Parcel", "Label",
         "Digest", "Badge", "Token", "Session", "Filter", "Facet", "Shard", "Lane", "Stamp",
         "Ticket", "Period", "Report", "Column", "Region", "Carrier", "Zone", "Sku", "Stock"]
FILES_PER_DIR = 16
LEVEL_W = [3, 3, 3, 3, 2, 2]
P_AFFECTED = [0, 0.05, 0.10, 0.12, 0.14, 0.16]

used = set()
def fresh_name():
    while True:
        n = rng.choice(VERBS) + rng.choice(NOUNS) + rng.choice(["", "s", "Map", "Set", "Plan", "View"])
        if n not in used:
            used.add(n)
            return n

class F:
    def __init__(self, pkg, sub, name, level, path=None):
        self.pkg, self.sub, self.name, self.level = pkg, sub, name, level
        self.path = path or f"packages/{pkg}/src/{sub}/{name}.ts"
        self.imports = []  # (target F, kind) kind: rel | alias | barrel | dynamic
        self.affected = False
        self.barrel = False
        self.test = False

files = []
by_pkg = defaultdict(list)
for pkg, subs in PKGS:
    for sub in subs:
        for i in range(FILES_PER_DIR):
            f = F(pkg, sub, fresh_name(), rng.choices(range(6), weights=LEVEL_W)[0])
            files.append(f); by_pkg[pkg].append(f)

# The hub, and two look-alike distractors that stay clean.
hub = by_pkg["money"][0]
used.discard(hub.name); hub.name = "roundHalfEven"; hub.path = "packages/money/src/rounding/halfEven.ts"
hub.level = 0; hub.affected = True
d1 = by_pkg["pricing"][0]; d1.name = "roundingPolicy"; d1.path = "packages/pricing/src/rules/roundingPolicy.ts"; d1.level = 0
d2 = by_pkg["reports"][1]; d2.name = "halfEvenSummary"; d2.path = "packages/reports/src/monthly/halfEvenSummary.ts"; d2.level = 2
DISTRACTORS = {d1.path, d2.path}

barrels = {}
def make_barrels():
    for pkg, _ in PKGS:
        if pkg == "tools":
            continue
        b = F(pkg, "", "index", 1.5, path=f"packages/{pkg}/src/index.ts"); b.barrel = True
        low = [f for f in by_pkg[pkg] if f.level <= 1 and f.path not in DISTRACTORS]
        picks = rng.sample(low, min(3, len(low)))
        if pkg == "money" and hub not in picks:
            picks[0] = hub
        for t in picks:
            b.imports.append((t, "rel"))
        b.affected = any(t.affected for t in picks)
        barrels[pkg] = b

def pool(level, me, affected):
    out = [f for f in files if f.level < level and f.pkg != "tools" and f is not me and f.affected == affected]
    if level >= 2:
        out += [b for p, b in barrels.items() if p != me.pkg and b.affected == affected]
    return out

def kind_for(me, t):
    if t.barrel:
        return "barrel"
    return "rel" if t.pkg == me.pkg else "alias"

ordered = sorted([f for f in files if f is not hub], key=lambda f: (f.level, f.path))
done_barrels = False
for f in ordered:
    if f.level >= 2 and not done_barrels:
        make_barrels(); done_barrels = True
    if f.level == 0:
        continue
    want_aff = f.path not in DISTRACTORS and rng.random() < P_AFFECTED[f.level]
    aff = pool(f.level, f, True) if want_aff else []
    clean = pool(f.level, f, False)
    picks = []
    if aff:
        picks.append(rng.choice(aff)); f.affected = True
    for t in rng.sample(clean, min(len(clean), rng.randint(0 if aff else 1, 2))):
        if t not in picks:
            picks.append(t)
    f.imports = [(t, kind_for(f, t)) for t in picks]
if not done_barrels:
    make_barrels()

# A few affected cross-package edges become dynamic requires.
dyn = 0
for f in sorted(files, key=lambda f: f.path):
    if dyn >= 3:
        break
    for i, (t, k) in enumerate(f.imports):
        if f.level >= 2 and t.affected and k == "alias":
            f.imports[i] = (t, "dynamic"); dyn += 1
            break

# Tests: 40 files; 15 reach the hub, 25 do not.
tests = []
aff_src = sorted([f for f in files if f.affected and f is not hub and f.pkg != "tools"], key=lambda f: f.path)
clean_src = sorted([f for f in files if not f.affected and f.pkg != "tools"], key=lambda f: f.path)
for i in range(40):
    pkg = PKGS[i % 12][0]
    n = fresh_name()
    t = F(pkg, "", n, 9, path=f"__tests__/{pkg}/{n}.test.ts"); t.test = True
    tests.append(t)
reach = rng.sample(range(40), 15)
for i, t in enumerate(tests):
    if i in reach:
        tgt = [rng.choice(aff_src)]
        t.affected = True
    else:
        tgt = rng.sample(clean_src, 2)
    t.imports = [(x, "alias") for x in tgt]

allf = files + list(barrels.values()) + tests

# Ground truth by BFS over reverse edges (the graph is what we wrote, not what we meant).
rev = defaultdict(list)
for f in allf:
    for t, _ in f.imports:
        rev[t.path].append(f)
dist = {hub.path: 0}
q = deque([hub])
while q:
    cur = q.popleft()
    for imp in rev[cur.path]:
        if imp.path not in dist:
            dist[imp.path] = dist[cur.path] + 1; q.append(imp)
assert all((f.path in dist) == f.affected for f in allf if f is not hub), "affected flag drifted from the graph"
assert not (DISTRACTORS & set(dist)), "a distractor became affected"

unrelated = sorted([f for f in by_pkg["tools"] if f.sub == "scripts"], key=lambda f: f.path)[0]
assert unrelated.path not in rev, "the unrelated file has importers"

def spec(me, t, kind):
    if kind == "barrel":
        return f"@app/{t.pkg}"
    if kind in ("alias", "dynamic") or me.test:
        # The module path, not the symbol name: the hub's file is halfEven.ts, its symbol roundHalfEven.
        return f"@app/{t.pkg}/" + t.path[len(f"packages/{t.pkg}/src/"):-3]
    a = os.path.dirname(me.path); b = t.path[:-3]
    r = os.path.relpath(b, a)
    return r if r.startswith(".") else "./" + r

def fn_of(t):
    if t.barrel:
        return t.imports[0][0].name
    return t.name

def body(f):
    lines, calls = [], []
    for t, k in f.imports:
        fn = fn_of(t)
        if k == "dynamic":
            lines.append(f'const {{ {fn} }} = require("{spec(f, t, k)}");')
        else:
            lines.append(f'import {{ {fn} }} from "{spec(f, t, k)}";')
        calls.append(f"{fn}(x)")
    if f.barrel:
        out = []
        for t, _ in f.imports:
            out.append(f'export * from "{spec(f, t, "rel")}";')
        return "\n".join(out) + "\n"
    if f.test:
        lines = ['import { describe, expect, it } from "vitest";'] + lines
        name = os.path.basename(f.path)[:-8]
        checks = "\n".join(f"    expect(Number.isFinite({c.replace('(x)', '(3)')})).toBe(true);" for c in calls)
        return "\n".join(lines) + f'\n\ndescribe("{name}", () => {{\n  it("stays finite", () => {{\n{checks}\n  }});\n}});\n'
    if f is hub:
        return ("export function roundHalfEven(value: number, decimals = 2): number {\n"
                "  const f = 10 ** decimals;\n  const n = value * f;\n  const r = Math.round(n);\n"
                "  const tie = Math.abs(n % 1) === 0.5;\n  return (tie && r % 2 !== 0 ? r - 1 : r) / f;\n}\n")
    if f.path == d1.path:
        return ("// Pricing keeps its own half-up rounding on purpose; see the pricing rules doc.\n"
                "export function roundingPolicy(x: number): number {\n  return Math.round(x * 100) / 100;\n}\n")
    k = (sum(map(ord, f.name)) % 7) + 1
    expr = " + ".join(calls) if calls else f"x * {k}"
    return ("\n".join(lines) + ("\n\n" if lines else "")
            + f"export function {f.name}(x: number): number {{\n  return {expr} + {k};\n}}\n")

def contents():
    out = {}
    for f in allf:
        out[f.path] = body(f)
    out["package.json"] = json.dumps({"name": "commerce-workspace", "private": True,
                                      "workspaces": ["packages/*"], "scripts": {"test": "vitest run"}}, indent=2) + "\n"
    for pkg, _ in PKGS:
        # npm workspaces: each package is named @app/<pkg>; `exports` maps deep imports to src/.
        out[f"packages/{pkg}/package.json"] = json.dumps({"name": f"@app/{pkg}", "version": "0.4.0",
                                                         "main": "src/index.ts",
                                                         "exports": {".": "./src/index.ts", "./*": "./src/*.ts"}},
                                                        indent=2) + "\n"
    out["tsconfig.json"] = json.dumps({"compilerOptions": {"target": "ES2022", "module": "nodenext",
                                       "moduleResolution": "nodenext", "strict": True}}, indent=2) + "\n"
    out["README.md"] = ("# commerce-workspace\n\nA workspace of TypeScript packages: billing, pricing, orders, "
                        "catalog and more. It uses npm workspaces: each package's `package.json` names it "
                        "`@app/<package>` and maps deep imports to `src/` through `exports`. Each package "
                        "re-exports its public modules from `src/index.ts`.\n")
    return out

def expected():
    imp = sorted(p for p in dist if p != hub.path and not p.startswith("__tests__/"))
    tst = sorted(p for p in dist if p.startswith("__tests__/"))
    def first(pred):
        for p in imp:
            if pred(p):
                return p
    byp = {f.path: f for f in allf}
    s_barrel = first(lambda p: any(k == "barrel" and t.pkg == "money" for t, k in byp[p].imports))
    s_dyn = first(lambda p: any(k == "dynamic" for _, k in byp[p].imports))
    s_deep = max(imp, key=lambda p: (dist[p], p))
    s_test = max(tst, key=lambda p: (dist[p], p))
    s_cross = first(lambda p: dist[p] >= 3 and any(k == "barrel" and t.pkg != "money" for t, k in byp[p].imports))
    return {"hub": hub.path, "unrelated": unrelated.path, "importers": imp, "tests": tst,
            "sentinels": [s for s in [s_barrel, s_dyn, s_deep, s_cross, s_test] if s],
            "depth": {p: dist[p] for p in sorted(dist)}, "distractors": sorted(DISTRACTORS),
            "files_total": len(contents())}

def commit(root, date, msg):
    env = dict(os.environ, GIT_AUTHOR_DATE=f"{date}T10:00:00+00:00", GIT_COMMITTER_DATE=f"{date}T10:00:00+00:00")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=dev", "-c", "user.email=dev@example.com", "-c", "commit.gpgsign=false",
                    "-c", "core.hooksPath=/dev/null", "commit", "-qm", msg], cwd=root, check=True, env=env)

def write(root, items):
    for p, text in items.items():
        full = os.path.join(root, p)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(text)

def build(root):
    c = contents()
    first = {p: t for p, t in c.items() if not p.startswith("packages/") or p.split("/")[1] in ("core", "money")}
    first = {p: t for p, t in first.items() if not p.startswith("__tests__/")}
    write(root, first); commit(root, "2025-01-06", "chore: npm workspace layout, core and money")
    write(root, {p: t for p, t in c.items() if p.startswith("packages/") and p not in first})
    commit(root, "2025-02-03", "feat: billing, pricing, orders, catalog and the other packages")
    write(root, {p: t for p, t in c.items() if p.startswith("__tests__/")})
    commit(root, "2025-03-03", "test: package tests")
    touched = sorted(p for p in c if p.startswith("packages/pricing/src/quotes/"))[:4]
    write(root, {p: c[p] + "// quotes: currency per region\n" for p in touched})
    commit(root, "2025-04-07", "feat(pricing): quotes carry a region currency")
    write(root, {hub.path: c[hub.path].replace("const tie = Math.abs(n % 1) === 0.5;",
                                                 "const tie = Math.abs(Math.abs(n % 1) - 0.5) < 1e-9;"),
                 unrelated.path: "// Dev-only seed script; run with ts-node.\n" + c[unrelated.path]})
    commit(root, "2025-05-05", "fix(money): half-even ties tolerate float error; tidy a seed script")

mode = sys.argv[2]
if mode == "expected":
    print(json.dumps(expected(), indent=2))
else:
    build(sys.argv[1])
PY
if [ "${1:-}" = "--expected" ]; then
  python3 "$gen" "" expected
  exit 0
fi
mkdir app && cd app && git init -q -b main
python3 "$gen" "$PWD" build
