import { api } from "./api.js";
import { SERVER_CONFIG_ERROR_MESSAGES, validateServerConfig } from "./storage.js";
import { search } from "./search.js";
import { getSelectedSortOptionKey, getSortOptionConfig, readSearchFilters } from "./search.js";
import { getChipTags } from "./tags.js";
import { searchState } from "./state.js";
import { escapeHtml, setHtml, val } from "./utils.js";

const btnExport = document.getElementById("btnExport");
const btnApply = document.getElementById("btnApply");
const applyStatusEl = document.getElementById("applyStatus");
const resultSummaryEl = document.getElementById("resultSummary");

function clearIfServerConfigError(element) {
  if (!element) {
    return;
  }
  const text = (element.textContent || "").trim();
  if (SERVER_CONFIG_ERROR_MESSAGES.has(text)) {
    element.textContent = "";
  }
}

async function handleApplyClick() {
  const validationMessage = validateServerConfig();
  if (validationMessage) {
    setHtml("applyStatus", escapeHtml(validationMessage));
    return;
  }
  clearIfServerConfigError(applyStatusEl);
  const adds = getChipTags("add");
  const rems = getChipTags("remove");
  const selectedIds = Array.from(searchState.selectedIds);
  if (!selectedIds.length) {
    window.alert("No items selected");
    return;
  }
  const selectedDetails = selectedIds.map((id) => {
    const stored = searchState.selectedDetails.get(id) || searchState.itemsById.get(id) || {};
    const name = stored.name ?? stored.Name ?? "";
    const type = stored.type ?? stored.Type ?? "";
    return { id, name, type };
  });
  const detailLookup = new Map(selectedDetails.map((item) => [item.id, item]));
  const body = {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId")?.value,
    changes: selectedDetails.map((item) => ({ id: item.id, add: adds, remove: rems })),
  };
  if (btnApply) {
    btnApply.disabled = true;
  }
  setHtml("applyStatus", "Applying...");
  try {
    const data = await api("/api/apply", body);
    const updates = data.updated || [];
    const successes = updates.filter((update) => !(update.errors || []).length).length;
    const failures = updates.length - successes;
    const summaryParts = [];
    if (successes) {
      summaryParts.push(`${successes} successful`);
    }
    if (failures) {
      summaryParts.push(`${failures} failed`);
    }
    const summaryText = summaryParts.length ? summaryParts.join(", ") : "No changes applied";
    const detailItems = updates
      .map((update) => {
        const errors = update.errors || [];
        const added = update.added || [];
        const removed = update.removed || [];
        const meta = detailLookup.get(update.id) || { name: "", type: "" };
        const hasName = meta.name && meta.name !== update.id;
        const itemLabel = hasName ? `${escapeHtml(meta.name)} (${escapeHtml(update.id)})` : escapeHtml(update.id);
        const changeDescriptions = [];
        if (added.length) {
          changeDescriptions.push(`added: ${escapeHtml(added.join(", "))}`);
        }
        if (removed.length) {
          changeDescriptions.push(`removed: ${escapeHtml(removed.join(", "))}`);
        }
        const changeDetail = changeDescriptions.length ? `<div>${changeDescriptions.join("; ")}</div>` : "";
        const errorDetail = errors.length ? `<ul>${errors.map((err) => `<li>${escapeHtml(err)}</li>`).join("")}</ul>` : "";
        const typeLabel = meta.type ? ` <span class="apply-type">[${escapeHtml(meta.type)}]</span>` : "";
        const statusIcon = errors.length ? "❌" : "✅";
        return [
          `<li class="${errors.length ? "apply-error" : "apply-success"}">`,
          `${statusIcon} <strong>${itemLabel}</strong>${typeLabel}`,
          changeDetail,
          errorDetail,
          "</li>",
        ].join("");
      })
      .join("");
    const detailsHtml = detailItems ? `<ul class="apply-results">${detailItems}</ul>` : "";
    setHtml("applyStatus", `<div>${escapeHtml(summaryText)}</div>${detailsHtml}`);
    await search({ startIndex: 0, reset: true });
  } catch (error) {
    setHtml("applyStatus", `Error: ${escapeHtml(error.message)}`);
  } finally {
    if (btnApply) {
      btnApply.disabled = false;
    }
  }
}

async function handleExportClick() {
  const validationMessage = validateServerConfig();
  if (validationMessage) {
    setHtml("resultSummary", escapeHtml(validationMessage));
    return;
  }
  clearIfServerConfigError(resultSummaryEl);
  const filters = readSearchFilters();
  const body = {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId")?.value,
    libraryId: document.getElementById("libraryId")?.value,
    types: filters.types,
    titleQuery: filters.titleQuery,
    includeTags: filters.includeTags,
    excludeTags: filters.excludeTags,
    excludeCollections: filters.excludeCollections,
  };
  const sortKey = getSelectedSortOptionKey();
  const sortConfig = getSortOptionConfig(sortKey);
  body.sortBy = sortConfig.sortBy;
  body.sortOrder = sortConfig.sortOrder;
  const response = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    window.alert("Export failed");
    return;
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "tags_export.csv";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

export function initializeApply() {
  if (btnApply) {
    btnApply.addEventListener("click", handleApplyClick);
  }
  if (btnExport) {
    btnExport.addEventListener("click", handleExportClick);
  }
}
