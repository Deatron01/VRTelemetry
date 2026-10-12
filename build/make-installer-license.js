// Builds the text the Windows installer shows on its licence page, so nobody
// can install the app without being shown the research-use-only disclaimer.
// Generated from LICENSE + DISCLAIMER.md at package time (never edited by
// hand, never committed) so it cannot drift from the documents in the repo.
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const read = (name) => fs.readFileSync(path.join(root, name), 'utf8').replace(/\r\n/g, '\n');

const text = [
  'IMPORTANT - READ BEFORE INSTALLING',
  '',
  'VRTelemetry is a research data-acquisition tool for non-clinical research.',
  'It is NOT a medical device, it does not diagnose, monitor or treat any',
  'condition, and nothing it outputs is medical advice.',
  '',
  '='.repeat(72),
  '',
  read('DISCLAIMER.md'),
  '',
  '='.repeat(72),
  '',
  read('LICENSE'),
].join('\n');

// UTF-8 with BOM and CRLF: the form NSIS's licence page reads reliably on
// Windows, including the non-ASCII characters in the author's name.
fs.writeFileSync(path.join(__dirname, 'installer-license.txt'), '﻿' + text.replace(/\n/g, '\r\n'));
console.log('build/installer-license.txt written');
