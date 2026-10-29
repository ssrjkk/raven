import test from 'node:test';
import assert from 'node:assert/strict';
import { safeExternalUrl } from '../src/popup/popup-security.js';

test('extension popup links accept only absolute http(s) URLs', () => {
  assert.equal(safeExternalUrl('https://example.com/a'), 'https://example.com/a');
  assert.equal(safeExternalUrl('http://127.0.0.1:18888/'), 'http://127.0.0.1:18888/');
  assert.equal(safeExternalUrl('javascript:alert(1)'), '');
  assert.equal(safeExternalUrl('/relative'), '');
  assert.equal(safeExternalUrl('chrome-extension://evil'), '');
});
