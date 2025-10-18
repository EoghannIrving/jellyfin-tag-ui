export const SERVER_CONFIG_ERRORS = {
  missingBoth: "Enter the Jellyfin base URL and API key.",
  missingBase: "Enter the Jellyfin base URL.",
  missingApiKey: "Enter the Jellyfin API key.",
};

export const SERVER_CONFIG_ERROR_MESSAGES = new Set(Object.values(SERVER_CONFIG_ERRORS));

const baseInputEl = document.getElementById("base");
const apiKeyInputEl = document.getElementById("apiKey");
const rememberDetailsCheckbox = document.getElementById("rememberDetails");

const SERVER_CONFIG_STORAGE_KEY = "jellyfinTagUi.serverConfig";

function getServerConfigStorage() {
  try {
    const storage = window.localStorage;
    const testKey = "__jftu_storage_test__";
    storage.setItem(testKey, "1");
    storage.removeItem(testKey);
    return storage;
  } catch (error) {
    return null;
  }
}

const serverConfigStorage = getServerConfigStorage();

function readStoredServerConfig() {
  if (!serverConfigStorage) {
    return null;
  }
  try {
    const raw = serverConfigStorage.getItem(SERVER_CONFIG_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    const base = typeof parsed.base === "string" ? parsed.base : "";
    const apiKey = typeof parsed.apiKey === "string" ? parsed.apiKey : "";
    if (!base && !apiKey) {
      return null;
    }
    return { base, apiKey };
  } catch (error) {
    return null;
  }
}

function writeStoredServerConfig(config) {
  if (!serverConfigStorage) {
    return;
  }
  const base = (config.base || "").trim();
  const apiKey = (config.apiKey || "").trim();
  if (!base && !apiKey) {
    try {
      serverConfigStorage.removeItem(SERVER_CONFIG_STORAGE_KEY);
    } catch (error) {
      // ignore storage errors
    }
    return;
  }
  try {
    serverConfigStorage.setItem(
      SERVER_CONFIG_STORAGE_KEY,
      JSON.stringify({ base, apiKey }),
    );
  } catch (error) {
    // ignore storage errors
  }
}

function clearStoredServerConfig() {
  if (!serverConfigStorage) {
    return;
  }
  try {
    serverConfigStorage.removeItem(SERVER_CONFIG_STORAGE_KEY);
  } catch (error) {
    // ignore storage errors
  }
}

export function getCurrentServerConfigValues() {
  return {
    base: baseInputEl ? baseInputEl.value.trim() : "",
    apiKey: apiKeyInputEl ? apiKeyInputEl.value.trim() : "",
  };
}

export function syncServerConfigStorage() {
  if (!rememberDetailsCheckbox) {
    return;
  }
  if (!serverConfigStorage) {
    return;
  }
  if (!rememberDetailsCheckbox.checked) {
    clearStoredServerConfig();
    return;
  }
  writeStoredServerConfig(getCurrentServerConfigValues());
}

function applyStoredServerConfig() {
  const stored = readStoredServerConfig();
  const hasStoredValues = !!(stored && (stored.base || stored.apiKey));
  if (stored) {
    if (baseInputEl && typeof stored.base === "string") {
      baseInputEl.value = stored.base;
    }
    if (apiKeyInputEl && typeof stored.apiKey === "string") {
      apiKeyInputEl.value = stored.apiKey;
    }
  }
  if (rememberDetailsCheckbox) {
    rememberDetailsCheckbox.checked = hasStoredValues;
  }
}

export function setupServerConfigPersistence() {
  applyStoredServerConfig();
  if (baseInputEl) {
    baseInputEl.addEventListener("input", syncServerConfigStorage);
    baseInputEl.addEventListener("change", syncServerConfigStorage);
  }
  if (apiKeyInputEl) {
    apiKeyInputEl.addEventListener("input", syncServerConfigStorage);
    apiKeyInputEl.addEventListener("change", syncServerConfigStorage);
  }
  if (rememberDetailsCheckbox) {
    rememberDetailsCheckbox.addEventListener("change", syncServerConfigStorage);
  }
  syncServerConfigStorage();
}

export function validateServerConfig() {
  const baseValue = baseInputEl ? baseInputEl.value.trim() : "";
  const apiKeyValue = apiKeyInputEl ? apiKeyInputEl.value.trim() : "";
  const missingBase = !baseValue;
  const missingApiKey = !apiKeyValue;

  if (!missingBase && !missingApiKey) {
    return "";
  }

  if (missingBase && baseInputEl) {
    baseInputEl.focus();
  } else if (missingApiKey && apiKeyInputEl) {
    apiKeyInputEl.focus();
  }

  if (missingBase && missingApiKey) {
    return SERVER_CONFIG_ERRORS.missingBoth;
  }
  if (missingBase) {
    return SERVER_CONFIG_ERRORS.missingBase;
  }
  return SERVER_CONFIG_ERRORS.missingApiKey;
}
