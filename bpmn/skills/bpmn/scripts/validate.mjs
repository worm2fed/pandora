#!/usr/bin/env node
/**
 * validate.mjs — validate a .bpmn file before showing it to anyone.
 *
 * Usage: node validate.mjs <file.bpmn>
 *
 * Two passes:
 *   1. bpmn-moddle parse — schema errors, duplicate ids, unresolved references
 *   2. bpmnlint (bpmnlint:recommended) — best-practice rules: dead ends,
 *      unlabeled gateways/events, implicit splits, superfluous gateways, …
 *
 * Exit code 0 = clean (warnings allowed), 1 = errors found, 2 = usage/parse failure.
 * Output is one finding per line: LEVEL  [elementId]  message  (rule)
 */

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { BpmnModdle } from 'bpmn-moddle';
import bpmnlint from 'bpmnlint';
import NodeResolver from 'bpmnlint/lib/resolver/node-resolver.js';

const require = createRequire(import.meta.url);
const { Linter } = bpmnlint;

const file = process.argv[2];
if (!file) {
  console.error('usage: node validate.mjs <file.bpmn>');
  process.exit(2);
}

const xml = readFileSync(file, 'utf8');
const moddle = new BpmnModdle();

let rootElement;
let parseWarnings = [];
try {
  ({ rootElement, warnings: parseWarnings } = await moddle.fromXML(xml));
} catch (err) {
  console.error(`PARSE ERROR: ${err.message}`);
  for (const w of err.warnings || []) console.error(`  ${w.message}`);
  process.exit(2);
}

let errorCount = 0;
let warnCount = 0;

for (const w of parseWarnings) {
  console.log(`warn   [parse]  ${w.message}`);
  warnCount++;
}

const linter = new Linter({
  config: { extends: 'bpmnlint:recommended' },
  resolver: new NodeResolver({ require }),
});

const results = await linter.lint(rootElement);

for (const [rule, findings] of Object.entries(results)) {
  for (const f of findings) {
    const level = f.category === 'error' ? 'ERROR' : 'warn ';
    console.log(`${level}  [${f.id || '-'}]  ${f.message}  (${rule})`);
    if (f.category === 'error') errorCount++;
    else warnCount++;
  }
}

if (errorCount === 0 && warnCount === 0) {
  console.log('clean: no findings');
}
console.log(`\n${errorCount} error(s), ${warnCount} warning(s)`);
process.exit(errorCount > 0 ? 1 : 0);
