#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
mkdir -p src
printf '{\n  "name": "greet-cli",\n  "version": "0.1.0",\n  "bin": { "greet": "src/index.js" }\n}\n' > package.json
cat > src/index.js <<'JS'
#!/usr/bin/env node
const name = process.argv[2] || "world";
console.log(`Hello, ${name}!`);
JS
c 2025-03-03 "feat: greet cli"
cat > README.md <<'MD'
# greet-cli

A tiny command-line greeter.

## Instalation

    npm install -g .

## Usage

    greet friend
MD
c 2025-03-05 "docs: add README"
printf '{\n  "name": "greet-cli",\n  "version": "0.2.0",\n  "bin": { "greet": "src/index.js" }\n}\n' > package.json
c 2025-03-12 "chore: release 0.2.0"
cat > src/index.js <<'JS'
#!/usr/bin/env node
const name = (process.argv[2] || "world").trim();
console.log(`Hello, ${name}!`);
JS
c 2025-04-02 "fix: trim the name argument"
printf '\n## License\n\nMIT\n' >> README.md
c 2025-04-09 "docs: add license section"
