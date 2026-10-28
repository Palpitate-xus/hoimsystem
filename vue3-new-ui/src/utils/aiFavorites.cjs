const PREFIX = "hoim-ai-favorites:v1:";

function favoriteStorageKey(username, roles) {
  if (typeof username !== "string" || !username || !Array.isArray(roles) || !roles.length) return null;
  return PREFIX + encodeURIComponent(JSON.stringify([username, [...new Set(roles)].sort()]));
}

function normalizeFavorites(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter(key => typeof key === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(key)))].slice(0, 80);
}

function readFavorites(storage, key) {
  if (!storage || !key) return [];
  try { return normalizeFavorites(JSON.parse(storage.getItem(key))); } catch { return []; }
}

function writeFavorites(storage, key, keys) {
  if (!storage || !key) return false;
  try { storage.setItem(key, JSON.stringify(normalizeFavorites(keys))); return true; } catch { return false; }
}

module.exports = { favoriteStorageKey, normalizeFavorites, readFavorites, writeFavorites };
