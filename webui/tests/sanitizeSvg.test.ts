import assert from 'node:assert/strict';
import test from 'node:test';

import { sanitizeSvg } from '../src/utils/sanitizeSvg.ts';

test('sanitizeSvg preserves basic svg markup', () => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>contrast</text></svg>';

  assert.equal(sanitizeSvg(svg), svg);
});

test('sanitizeSvg removes active content and event handlers', () => {
  const sanitized = sanitizeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">' +
      '<script>alert(1)</script><foreignObject><div onclick="x()">x</div></foreignObject>' +
      '<text onclick="alert(2)">safe</text></svg>',
  );

  assert.match(sanitized, /<text>safe<\/text>/);
  assert.doesNotMatch(sanitized, /script|foreignObject|onload|onclick/i);
});

test('sanitizeSvg removes unsafe url attributes', () => {
  const sanitized = sanitizeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg">' +
      '<a href="javascript:alert(1)"><text>bad</text></a>' +
      '<use href="#safe" /></svg>',
  );

  assert.doesNotMatch(sanitized, /javascript:/i);
  assert.match(sanitized, /href="#safe"/);
});

test('sanitizeSvg rejects non-svg payloads', () => {
  assert.equal(sanitizeSvg('<img src=x onerror=alert(1)>'), '');
});
