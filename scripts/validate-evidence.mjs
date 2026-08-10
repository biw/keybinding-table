#!/usr/bin/env node

import { readFile } from 'node:fs/promises';
import process from 'node:process';

const allowedTargets = new Set([
  'firefox-macos',
  'chromium-macos',
  'safari-macos',
  'firefox-windows',
  'chrome-windows',
  'edge-windows'
]);
const allowedStates = new Set(['textarea-caret', 'textarea-selection']);
const allowedKinds = new Set([
  'observed',
  'observed-no-effect',
  'os-level',
  'requires-manual-verification',
  'injector-failure'
]);

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index === -1 ? fallback : process.argv[index + 1];
}

function fail(errors) {
  for (const error of errors) console.error(`evidence validation: ${error}`);
  process.exitCode = 1;
}

const readmePath = option('--readme', 'README.md');
const sourcesPath = option('--sources', 'SOURCES.md');
const observationsPath = option('--observations', 'evidence/observations.json');
const rejectInjectorFailures = process.argv.includes('--reject-injector-failures');
const [readme, sources, rawObservations] = await Promise.all([
  readFile(readmePath, 'utf8'),
  readFile(sourcesPath, 'utf8'),
  readFile(observationsPath, 'utf8')
]);

const combos = new Set(
  [...readme.matchAll(/^\|\s+\*\*(?:`([^`]+)`|``\s*([^`]+)`\s*``)\*\*/gm)]
    .map((match) => match[1] ?? `${match[2]}\``)
);
const sourceIds = new Set(
  [...sources.matchAll(/^## ([A-Z0-9-]+)$/gm)].map((match) => match[1])
);
const errors = [];
let document;
try {
  document = JSON.parse(rawObservations);
} catch (error) {
  fail([`${observationsPath} is not valid JSON: ${error.message}`]);
  process.exit();
}

if (document.schemaVersion !== 1) errors.push('schemaVersion must be 1');
if (!Array.isArray(document.observations)) errors.push('observations must be an array');

const seen = new Set();
for (const [index, observation] of (document.observations ?? []).entries()) {
  const prefix = `observation ${index}`;
  if (!combos.has(observation.combo)) errors.push(`${prefix}: unknown combo ${JSON.stringify(observation.combo)}`);
  if (!allowedTargets.has(observation.target)) errors.push(`${prefix}: invalid target ${JSON.stringify(observation.target)}`);
  if (!allowedStates.has(observation.state)) errors.push(`${prefix}: invalid state ${JSON.stringify(observation.state)}`);
  if (!allowedKinds.has(observation.result?.kind)) errors.push(`${prefix}: invalid result kind`);
  if (rejectInjectorFailures && observation.result?.kind === 'injector-failure') {
    errors.push(`${prefix}: injector failure must be resolved before accepting this run`);
  }
  if (typeof observation.result?.summary !== 'string' || !observation.result.summary.trim()) {
    errors.push(`${prefix}: result.summary is required`);
  }
  const environment = observation.environment;
  for (const key of ['browser', 'browserVersion', 'os', 'runnerImage']) {
    if (typeof environment?.[key] !== 'string' || !environment[key].trim()) {
      errors.push(`${prefix}: environment.${key} is required`);
    }
  }
  if (environment?.inputLayout !== 'U.S.') errors.push(`${prefix}: inputLayout must be U.S.`);
  if (environment?.cleanProfile !== true) errors.push(`${prefix}: cleanProfile must be true`);
  if (!Array.isArray(observation.sources) || observation.sources.length === 0) {
    errors.push(`${prefix}: at least one source ID is required`);
  } else {
    for (const source of observation.sources) {
      if (!sourceIds.has(source)) errors.push(`${prefix}: unknown source ID ${source}`);
    }
  }
  if (typeof observation.artifact !== 'string' || !observation.artifact.trim()) {
    errors.push(`${prefix}: artifact is required`);
  }
  if (['observed-no-effect', 'os-level'].includes(observation.result?.kind)) {
    if (!observation.result.before || !observation.result.after) {
      errors.push(`${prefix}: stable observed result requires before and after state`);
    }
  }
  if (observation.result?.kind === 'observed' && (!observation.result.before || (!observation.result.after && !observation.result.error))) {
    errors.push(`${prefix}: changed observed result requires before state and an after state or postcondition error`);
  }
  const key = [observation.combo, observation.target, observation.state].join('|');
  if (seen.has(key)) errors.push(`${prefix}: duplicate combo/target/state record`);
  seen.add(key);
}

if (combos.size === 0) errors.push(`no keybinding rows found in ${readmePath}`);
if (sourceIds.size === 0) errors.push(`no source IDs found in ${sourcesPath}`);
for (const match of readme.matchAll(/〔([A-Z0-9-]+)〕/g)) {
  if (!sourceIds.has(match[1])) errors.push(`README cites unknown source ID ${match[1]}`);
}
// Raw workflow artifacts deliberately contain only the matrix selected for a
// manual run and do not rewrite README. Citation completeness is enforced on
// the merged, reviewed evidence document produced by transcribe-evidence.
if (document.metadata?.workflowRun) {
  for (const line of readme.split('\n')) {
    if (!/^\|\s+\*\*/.test(line)) continue;
    const cells = line.split('|');
    for (const cell of cells.slice(2, -1)) {
      const value = cell.trim();
      if (value && value !== '_unknown_' && !/〔[A-Z0-9-]+〕/.test(value)) {
        errors.push(`completed README cell lacks a source ID: ${value}`);
      }
    }
  }
}
if (errors.length) {
  fail(errors);
} else {
  console.log(`Validated ${document.observations.length} observations against ${combos.size} table rows and ${sourceIds.size} sources.`);
}
