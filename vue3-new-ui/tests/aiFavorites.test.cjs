const test = require('node:test');
const assert = require('node:assert/strict');
const { favoriteStorageKey, readFavorites, writeFavorites } = require('../src/utils/aiFavorites.cjs');

function storage() {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test('favorites persist for one account and are separate across accounts and role changes', () => {
  const store = storage(), key = favoriteStorageKey('doctor1', ['doctor']);
  assert(writeFavorites(store, key, ['patient_summary', 'outpatient_note']));
  assert.deepEqual(readFavorites(store, key), ['patient_summary', 'outpatient_note']);
  assert.deepEqual(readFavorites(store, favoriteStorageKey('doctor2', ['doctor'])), []);
  assert.deepEqual(readFavorites(store, favoriteStorageKey('doctor1', ['patient'])), []);
  assert.equal(favoriteStorageKey('super', ['super_admin', 'admin']), favoriteStorageKey('super', ['admin', 'super_admin', 'admin']));
});

test('invalid stored values do not become task selections', () => {
  const store = storage(), key = favoriteStorageKey('doctor1', ['doctor']);
  for (const value of ['broken JSON', '{"patient_id":123}', 'null', 'true']) {
    store.setItem(key, value);
    assert.deepEqual(readFavorites(store, key), []);
  }
  store.setItem(key, JSON.stringify(['patient_summary', 'patient_summary', 123, {}, '../admin', '<script>', '']));
  assert.deepEqual(readFavorites(store, key), ['patient_summary']);
});

test('an unavailable browser store and an anonymous session are handled without exceptions', () => {
  const blocked = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('quota'); } };
  assert.deepEqual(readFavorites(blocked, 'key'), []);
  assert.equal(writeFavorites(blocked, 'key', ['patient_summary']), false);
  assert.equal(favoriteStorageKey('', ['doctor']), null);
  assert.equal(favoriteStorageKey('doctor1', []), null);
  assert.equal(writeFavorites(storage(), null, ['patient_summary']), false);
});
