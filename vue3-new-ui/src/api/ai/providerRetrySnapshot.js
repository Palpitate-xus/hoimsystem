export function providerSnapshotKeys(value, fields) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const hasAttempts = Object.prototype.hasOwnProperty.call(value, 'max_attempts');
  if (hasAttempts && (!Number.isSafeInteger(value.max_attempts) || value.max_attempts < 1 || value.max_attempts > 3)) return false;
  const expected = hasAttempts ? [...fields, 'max_attempts'] : fields;
  const actual = Object.keys(value);
  return actual.length === expected.length && actual.every(field => expected.includes(field));
}
