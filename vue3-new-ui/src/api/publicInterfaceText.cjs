/* Shared immutable string values; the production loader stores their exact JSON as inert data. */
const pool = require('./publicInterfaceTextPool.json');
module.exports = function publicInterfaceText(index) {
  if (!Number.isSafeInteger(index) || index < 0 || index >= pool.values.length || typeof pool.values[index] !== 'string') throw new Error('Invalid public interface text index');
  return pool.values[index];
};
