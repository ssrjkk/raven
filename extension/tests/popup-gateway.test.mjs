import test from 'node:test';
import assert from 'node:assert/strict';
import { gatewayOriginPatterns, normalizeGatewayEndpoint } from '../src/popup/popup-gateway.js';

test('a typed address becomes the origin the socket will use', () => {
  assert.equal(normalizeGatewayEndpoint('http://localhost:18888/'), 'http://localhost:18888');
  assert.equal(normalizeGatewayEndpoint('192.168.1.20:18888'), 'http://192.168.1.20:18888');
  assert.equal(normalizeGatewayEndpoint('wss://raven.example.com'), 'https://raven.example.com');
  assert.equal(normalizeGatewayEndpoint('https://raven.example.com/ws'), 'https://raven.example.com');
});

test('an address Chrome cannot be asked about is refused, not half-used', () => {
  for (const unusable of ['', '   ', 'not a host', 'file:///c:/gate', 'http://user:pass@host:18888', 'ftp://host/x']) {
    assert.equal(normalizeGatewayEndpoint(unusable), '', unusable);
  }
});

test('the permission request carries the http origin and its socket twin', () => {
  assert.deepEqual(gatewayOriginPatterns('http://127.0.0.1:18888'), [
    'http://127.0.0.1:18888/*',
    'ws://127.0.0.1:18888/*',
  ]);
  assert.deepEqual(gatewayOriginPatterns('https://raven.example.com'), [
    'https://raven.example.com/*',
    'wss://raven.example.com/*',
  ]);
  assert.deepEqual(gatewayOriginPatterns('file:///c:/gate'), []);
});
