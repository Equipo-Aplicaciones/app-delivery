import assert from 'node:assert/strict';
import { parseAggregator, prepareLookup, prepareSend } from '../src/engine';

function testOrderTrim() {
  const ready = prepareSend({ imageUri: 'file://pedido.jpg', order: '  88  ', aggregator: 'uber' });
  assert.equal(ready.ok, true);
  if (ready.ok) assert.equal(ready.payload.numeroOrden, '88');
}

function testEmptyOrder() {
  const ready = prepareSend({ imageUri: 'file://pedido.jpg', order: '   ', aggregator: 'uber' });
  assert.equal(ready.ok, false);
}

function testMissingPhoto() {
  const ready = prepareSend({ imageUri: null, order: '88', aggregator: 'pedidosya' });
  assert.equal(ready.ok, false);
}

function testPedyaIsNotStored() {
  const parsed = parseAggregator('pedya');
  assert.equal(parsed.ok, false);
  const lookup = prepareLookup({ order: '88', aggregator: 'pedidosya' });
  assert.equal(lookup.ok, true);
  if (lookup.ok) assert.equal(lookup.key.agregador, 'pedidosya');
}

function testLookupDoesNotNeedPhoto() {
  const lookup = prepareLookup({ order: ' 15 ', aggregator: 'uber' });
  assert.equal(lookup.ok, true);
  if (lookup.ok) assert.equal(lookup.key.numeroOrden, '15');
}

testOrderTrim();
testEmptyOrder();
testMissingPhoto();
testPedyaIsNotStored();
testLookupDoesNotNeedPhoto();
console.log('smoke v1 ok');
