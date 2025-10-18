export function val(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : "";
}

export function setHtml(id, html) {
  const el = document.getElementById(id);
  if (el) {
    el.innerHTML = html;
  }
}

export function splitTags(input) {
  if (!input) {
    return [];
  }
  return [...new Set(input.split(/[;,]/).map((tag) => tag.trim()).filter(Boolean))];
}

export function optionList(arr, valueKey, textKey) {
  return arr
    .map((item) => {
      const value = item[valueKey];
      const text = item[textKey] || item[valueKey];
      return `<option value="${value}">${text}</option>`;
    })
    .join("");
}

export function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) =>
    ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch] || ch),
  );
}

export function setStatus(element, text) {
  if (!element) {
    return;
  }
  element.textContent = text || "";
}

export function pluralize(count, singular, plural) {
  if (count === 1) {
    return singular;
  }
  if (plural) {
    return plural;
  }
  if (singular.endsWith("y")) {
    return `${singular.slice(0, -1)}ies`;
  }
  return `${singular}s`;
}

export function setButtonLoading(button, isLoading, loadingText) {
  if (!button) {
    return;
  }
  if (isLoading) {
    if (!button.dataset.originalText) {
      button.dataset.originalText = button.textContent;
    }
    button.disabled = true;
    if (loadingText) {
      button.textContent = loadingText;
    }
    button.setAttribute("aria-busy", "true");
    return;
  }
  button.disabled = false;
  button.removeAttribute("aria-busy");
  if (button.dataset.originalText) {
    button.textContent = button.dataset.originalText;
    delete button.dataset.originalText;
  }
}

export function setSelectPlaceholder(selectEl, text) {
  if (!selectEl) {
    return;
  }
  const safeText = escapeHtml(text || "");
  selectEl.innerHTML = `<option value="" disabled selected>${safeText}</option>`;
  selectEl.value = "";
}

export function normalizeTagList(tags) {
  if (!Array.isArray(tags)) {
    return [];
  }
  const seen = new Set();
  const normalized = [];
  tags.forEach((tag) => {
    const trimmed = (tag || "").trim();
    if (!trimmed || seen.has(trimmed)) {
      return;
    }
    seen.add(trimmed);
    normalized.push(trimmed);
  });
  return normalized;
}
