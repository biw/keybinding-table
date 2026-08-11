#!/usr/bin/env node

/**
 * Review and transcribe a completed manual workflow run. This program is
 * deliberately not called by GitHub Actions: it makes a local, reviewable
 * README/evidence change only after all artifacts have been downloaded.
 */
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import process from 'node:process';

const root = resolve(import.meta.dirname, '..');
const targetColumns = [
  { target: 'firefox-macos', source: 'FF-KEYBOARD' },
  { target: 'chromium-macos', source: 'CHROME-KEYBOARD' },
  { target: 'safari-macos', source: 'SAFARI-KEYBOARD' },
  { target: 'firefox-windows', source: 'FF-KEYBOARD' },
  { target: 'chrome-windows', source: 'CHROME-KEYBOARD' },
  { target: 'edge-windows', source: 'EDGE-KEYBOARD' }
];

function usage() {
  console.error('usage: transcribe-evidence.mjs [--allow-partial] [--existing evidence/observations.json] [--render-existing] --artifact <run URL> observation.json [...]');
  process.exit(2);
}

let currentArtifact;
let existingPath;
let renderExisting = false;
const inputs = [];
const allowPartial = process.argv.includes('--allow-partial');
for (let index = 2; index < process.argv.length; index += 1) {
  if (process.argv[index] === '--allow-partial') continue;
  if (process.argv[index] === '--render-existing') {
    renderExisting = true;
    continue;
  }
  if (process.argv[index] === '--existing') {
    existingPath = process.argv[index + 1];
    if (!existingPath) usage();
    index += 1;
    continue;
  }
  if (process.argv[index] === '--artifact') {
    currentArtifact = process.argv[index + 1];
    if (!currentArtifact) usage();
    index += 1;
    continue;
  }
  if (!currentArtifact) usage();
  inputs.push({ path: process.argv[index], artifact: currentArtifact });
}
if (!inputs.length && !renderExisting) usage();

const documents = await Promise.all(inputs.map(async ({ path, artifact }) => ({
  artifact,
  document: JSON.parse(await readFile(path, 'utf8'))
})));
const existingDocument = existingPath ? JSON.parse(await readFile(existingPath, 'utf8')) : null;
const incomingObservations = documents.flatMap(({ document, artifact }) => (document.observations ?? []).map((observation) => ({
  ...observation,
  artifact: `${artifact} (${observation.artifact})`
})));
const observationKey = (observation) => [observation.combo, observation.target, observation.state].join('|');
const incomingKeys = new Set();
for (const observation of incomingObservations) {
  const key = observationKey(observation);
  if (incomingKeys.has(key)) throw new Error(`Duplicate incoming observation: ${key}`);
  incomingKeys.add(key);
}
// A later isolated run may deliberately supersede a previous measurement of
// the same case (for example, after adding a new OS-state probe). Keep the
// new versioned record and leave unrelated historical observations intact.
const observations = [
  ...(existingDocument?.observations ?? []).filter((observation) => !incomingKeys.has(observationKey(observation))),
  ...incomingObservations
];
if (!observations.length) throw new Error('No observations were supplied.');
const failures = observations.filter((observation) => observation.result?.kind === 'injector-failure');
if (failures.length) throw new Error(`Refusing to transcribe ${failures.length} injector failures.`);

const byKey = new Map();
for (const observation of observations) {
  const key = observationKey(observation);
  if (byKey.has(key)) throw new Error(`Duplicate observation: ${key}`);
  byKey.set(key, observation);
}

const readmePath = resolve(root, 'README.md');
const evidencePath = resolve(root, 'evidence/observations.json');
const readme = await readFile(readmePath, 'utf8');

function rowCombo(line) {
  const match = line.match(/^\|\s+\*\*(?:`([^`]+)`|``\s*([^`]+)`\s*``)\*\*/);
  return match ? (match[1] ?? `${match[2]}\``) : null;
}

function eventDelivered(record) {
  return record.result?.after?.events?.some((event) => event.isTrusted && event.type === 'keydown') ?? false;
}

function quoted(value) {
  return `“${value.replaceAll('\n', '↵')}”`;
}

function textDelta(before, after) {
  let prefix = 0;
  while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) prefix += 1;
  let beforeEnd = before.length;
  let afterEnd = after.length;
  while (beforeEnd > prefix && afterEnd > prefix && before[beforeEnd - 1] === after[afterEnd - 1]) {
    beforeEnd -= 1;
    afterEnd -= 1;
  }
  return { start: prefix, removed: before.slice(prefix, beforeEnd), inserted: after.slice(prefix, afterEnd) };
}

function observedLabel(records) {
  if (records.every((record) => record.result.kind === 'os-level')) {
    return 'Windows shell';
  }
  const changedRecord = records.find((record) => record.result.kind === 'observed');
  if (!changedRecord) {
    return records.some(eventDelivered)
      ? 'no effect (input)'
      : 'no effect (input)';
  }
  const before = changedRecord.result.before;
  const after = changedRecord.result.after;
  if (!after) {
    if (changedRecord.result.modal) return changedRecord.result.modal;
    return changedRecord.result.error?.includes('timed out')
      ? 'opens browser/OS UI; textarea postcondition timed out'
      : 'tested page closed or was replaced after native input';
  }
  if (before.value !== after.value) {
    const delta = textDelta(before.value, after.value);
    if (!delta.removed) return `inserts ${quoted(delta.inserted)} at textarea offset ${delta.start}`;
    if (!delta.inserted) return `deletes ${quoted(delta.removed)} at textarea offset ${delta.start}`;
    return `replaces ${quoted(delta.removed)} with ${quoted(delta.inserted)} at textarea offset ${delta.start}`;
  }
  if (before.selectionStart !== after.selectionStart || before.selectionEnd !== after.selectionEnd) {
    if (after.selectionStart === 0 && after.selectionEnd === after.value.length) return 'select all (input)';
    if (after.selectionStart === after.selectionEnd) return `caret → ${after.selectionStart}`;
    return `select ${after.selectionStart}–${after.selectionEnd}`;
  }
  if (before.activeElement !== after.activeElement) return `moves focus from textarea to ${after.activeElement ?? 'browser UI'}`;
  if (before.appState?.isHidden !== after.appState?.isHidden && after.appState?.isHidden) return 'hide Safari';
  if (before.url !== after.url) return 'navigates away from the harness page';
  if (before.windowHandles !== after.windowHandles) return 'window/tab changed';
  return 'browser UI changed';
}

function cite(text, source) {
  return `${text.replace(/\s*(?:〔[A-Z0-9-]+〕|<!-- source: [A-Z0-9-]+ -->)/g, '')}<!-- source: ${source} -->`;
}

function alignTable(lines) {
  const begin = lines.findIndex((line) => line.startsWith('| Key Combo'));
  let end = begin + 2;
  while (end < lines.length && lines[end].startsWith('|')) end += 1;
  const rows = lines.slice(begin, end).map((line) => line.split('|').slice(1, -1).map((cell) => cell.trim()));
  const widths = rows[0].map((_, column) => Math.max(...rows.map((row) => row[column].length)));
  const table = rows.map((row, rowIndex) => `| ${row.map((cell, column) => (
    rowIndex === 1 ? '-'.repeat(widths[column]) : cell.padEnd(widths[column])
  )).join(' | ')} |`);
  lines.splice(begin, end - begin, ...table);
  return lines;
}

const lines = readme.split('\n');
const missing = [];
const rewritten = lines.map((line) => {
  const combo = rowCombo(line);
  if (!combo) return line;
  const cells = line.split('|');
  if (cells.length !== 9) throw new Error(`Unexpected table row shape for ${combo}`);
  for (let index = 0; index < targetColumns.length; index += 1) {
    const column = targetColumns[index];
    const records = ['textarea-caret', 'textarea-selection'].map((state) => byKey.get([combo, column.target, state].join('|')));
    if (records.some((record) => !record)) {
      missing.push(`${combo}/${column.target}`);
      continue;
    }
    const existing = cells[index + 2].trim();
    const source = records.every((record) => record.result.kind === 'os-level') ? 'WIN-KEYBOARD' : column.source;
    // Preserve the table's original inline-code/emphasis treatment. New
    // observed values take the same inline-code form as legacy action labels.
    const content = existing === '_unknown_' ? `\`${observedLabel(records)}\`` : existing;
    cells[index + 2] = ` ${cite(content, source)} `;
  }
  return cells.join('|');
});
if (missing.length && !allowPartial) {
  throw new Error(`Missing both-state evidence for ${missing.slice(0, 10).join(', ')}${missing.length > 10 ? '…' : ''}`);
}

const targetOrder = new Map(targetColumns.map((column, index) => [column.target, index]));
observations.sort((left, right) => [left.combo, targetOrder.get(left.target), left.state].join('|').localeCompare([right.combo, targetOrder.get(right.target), right.state].join('|')));
// Preserve the established Markdown layout rather than reformatting the table.
await writeFile(readmePath, `${rewritten.join('\n').replace(/\n+$/, '')}\n`, 'utf8');
await writeFile(evidencePath, `${JSON.stringify({
  schemaVersion: 1,
  metadata: {
    workflowRuns: [...new Set([...(existingDocument?.metadata?.workflowRuns ?? []), ...documents.map(({ artifact }) => artifact)])],
    completeMatrix: missing.length === 0,
    inputLayout: 'U.S.',
    cleanProfile: true,
    transcribedAt: new Date().toISOString()
  },
  observations
}, null, 2)}\n`, 'utf8');
console.log(`Transcribed ${observations.length} observations into README.md and evidence/observations.json.`);
