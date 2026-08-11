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
// These labels are direct, compact transcriptions of the primary shortcut
// references. Native runs establish the clean-profile, real-input baseline;
// the reference resolves browser-chrome behavior that intentionally leaves a
// focused textarea's DOM state unchanged (for example, opening Find).
const documentedOutcomes = {
  'firefox-windows': {
    'ctrl→a': 'select all',
    'ctrl→b': 'bookmarks sidebar',
    'ctrl→c': 'copy',
    'ctrl→d': 'bookmark page',
    'ctrl→e': 'focus search/address bar',
    'ctrl→f': 'find on page',
    'ctrl→g': 'find next',
    'ctrl→h': 'history sidebar',
    'ctrl→i': 'page info',
    'ctrl→j': 'downloads',
    'ctrl→k': 'focus search/address bar',
    'ctrl→l': 'select address bar',
    'ctrl→m': 'mute/unmute audio',
    'ctrl→n': 'new window',
    'ctrl→o': 'open file',
    'ctrl→p': 'print page',
    'ctrl→q': 'quit Firefox',
    'ctrl→r': 'reload page',
    'ctrl→s': 'save page',
    'ctrl→t': 'new tab',
    'ctrl→u': 'view page source',
    'ctrl→v': 'paste',
    'ctrl→w': 'close tab',
    'ctrl→x': 'cut',
    'ctrl→y': 'redo',
    'ctrl→z': 'undo',
    'ctrl→0': 'zoom reset',
    'ctrl→1': 'switch to tab 1',
    'ctrl→2': 'switch to tab 2',
    'ctrl→3': 'switch to tab 3',
    'ctrl→4': 'switch to tab 4',
    'ctrl→5': 'switch to tab 5',
    'ctrl→6': 'switch to tab 6',
    'ctrl→7': 'switch to tab 7',
    'ctrl→8': 'switch to tab 8',
    'ctrl→9': 'switch to last tab',
    'ctrl→-': 'zoom out',
    'ctrl→=': 'zoom in',
    'ctrl→[': 'back',
    'ctrl→]': 'forward',
  },
  'safari-macos': {
    'meta→h': { label: 'hide Safari', source: 'MAC-KEYBOARD' },
    'meta→l': 'select address bar',
    'meta→n': { label: 'new window', source: 'MAC-KEYBOARD' },
    'meta→o': { label: 'open file', source: 'MAC-KEYBOARD' },
    'meta→p': 'print page',
    'meta→q': { label: 'quit Safari', source: 'MAC-KEYBOARD' },
    'meta→t': { label: 'new tab', source: 'MAC-KEYBOARD' },
    'meta→w': 'close tab',
    'meta→x': { label: 'cut', source: 'MAC-KEYBOARD' },
    'meta→z': { label: 'undo', source: 'MAC-KEYBOARD' },
    'meta→1': 'switch to tab 1',
    'meta→2': 'switch to tab 2',
    'meta→3': 'switch to tab 3',
    'meta→4': 'switch to tab 4',
    'meta→5': 'switch to tab 5',
    'meta→6': 'switch to tab 6',
    'meta→7': 'switch to tab 7',
    'meta→8': 'switch to tab 8',
    'meta→9': 'switch to last tab',
    'meta→-': 'zoom out',
    'meta→=': 'zoom in',
    'meta→[': 'back',
    'meta→]': 'forward',
    'meta→,': 'Safari settings',
    'meta→`': { label: 'switch Safari window', source: 'MAC-KEYBOARD' },
  }
};

// Windows-logo-key chords are owned by Windows before a browser can process
// them.  We intentionally do not inject the session-changing ones (for
// example, Win+L) in the runner; instead their precise default behavior comes
// from Microsoft's Windows-key shortcut reference.  Entries absent from this
// register remain unresolved rather than being misrepresented as no-ops.
const windowsShellOutcomes = {
  'meta→a': 'open Action Center',
  'meta→b': 'focus first notification-area icon',
  'meta→c': 'open Copilot',
  'meta→d': 'show/hide desktop',
  'meta→e': 'open File Explorer',
  'meta→f': 'open Feedback Hub',
  'meta→g': 'open Game Bar',
  'meta→h': 'open voice dictation',
  'meta→i': 'open Settings',
  'meta→j': 'open Recall (supported PCs)',
  'meta→k': 'open Cast',
  'meta→l': 'lock computer',
  'meta→m': 'minimize all windows',
  'meta→n': 'open notification center and calendar',
  'meta→o': 'lock device orientation',
  'meta→p': 'open project settings',
  'meta→q': 'open Search',
  'meta→r': 'open Run dialog',
  'meta→s': 'open Search',
  'meta→t': 'cycle taskbar apps',
  'meta→u': 'open Accessibility settings',
  'meta→v': 'open clipboard history',
  'meta→w': 'open Widgets',
  'meta→x': 'open Quick Link menu',
  'meta→y': 'switch Mixed Reality/desktop input',
  'meta→z': 'open snap layouts',
  'meta→0': 'open/switch taskbar app 0',
  'meta→1': 'open/switch taskbar app 1',
  'meta→2': 'open/switch taskbar app 2',
  'meta→3': 'open/switch taskbar app 3',
  'meta→4': 'open/switch taskbar app 4',
  'meta→5': 'open/switch taskbar app 5',
  'meta→6': 'open/switch taskbar app 6',
  'meta→7': 'open/switch taskbar app 7',
  'meta→8': 'open/switch taskbar app 8',
  'meta→9': 'open/switch taskbar app 9',
  'meta→-': 'zoom out in Magnifier',
  'meta→=': 'zoom in with Magnifier',
  'meta→;': 'open emoji panel',
  'meta→,': 'peek at desktop',
  'meta→.': 'open emoji panel',
  'meta→/': 'start IME reconversion'
};

function documentedOutcome(target, combo) {
  if (target.endsWith('-windows') && combo.startsWith('meta→')) {
    const label = windowsShellOutcomes[combo];
    return label ? { label, source: 'WIN-KEYBOARD' } : undefined;
  }
  return documentedOutcomes[target]?.[combo];
}

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
    return 'OS-level behavior';
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
    const documented = documentedOutcome(column.target, combo);
    const documentedLabel = typeof documented === 'string' ? documented : documented?.label;
    const hasAllRecords = records.every((record) => record);
    if (!hasAllRecords && !documentedLabel) {
      missing.push(`${combo}/${column.target}`);
      continue;
    }
    const existing = cells[index + 2].trim();
    const source = documented?.source ?? (hasAllRecords && records.every((record) => record.result.kind === 'os-level') ? 'WIN-KEYBOARD' : column.source);
    // Preserve the table's original inline-code/emphasis treatment. New
    // observed values take the same inline-code form as legacy action labels.
    const staleNoEffect = documentedLabel && /^`no effect \(input\)`(?:<!-- source: [A-Z0-9-]+ -->)?$/.test(existing);
    const staleWindowsShell = /^`Windows shell`(?:<!-- source: [A-Z0-9-]+ -->)?$/.test(existing);
    const content = existing === '_unknown_' || staleNoEffect || staleWindowsShell
      ? `\`${documentedLabel ?? observedLabel(records)}\``
      : existing;
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
