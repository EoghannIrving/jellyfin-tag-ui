import { api } from "./api.js";
import {
  applySelectionFromCheckbox,
  closeInlineTagEditor,
  updateInlineTagSummary,
  updateSelectAllState,
  updateSelectionSummary,
} from "./selection.js";
import { validateServerConfig } from "./storage.js";
import { searchState } from "./state.js";
import {
  escapeHtml,
  normalizeTagList,
  optionList,
  pluralize,
  setButtonLoading,
  setHtml,
  setSelectPlaceholder,
  setStatus,
  splitTags,
  val,
} from "./utils.js";

const btnUsers = document.getElementById("btnUsers");
const btnLibs = document.getElementById("btnLibs");
const btnSearch = document.getElementById("btnSearch");
const userSelect = document.getElementById("userId");
const librarySelect = document.getElementById("libraryId");
const sortSelect = document.getElementById("sortOption");
const userStatusEl = document.getElementById("userStatus");
const libraryStatusEl = document.getElementById("libraryStatus");
const paginationControls = {
  prev: document.getElementById("btnPrevPage"),
  next: document.getElementById("btnNextPage"),
  summary: document.getElementById("pageSummary"),
};

function compareByNameAsc(a, b) {
  const options = { sensitivity: "base" };
  const sortA = (a.SortName || a.Name || "").trim();
  const sortB = (b.SortName || b.Name || "").trim();
  const primary = sortA.localeCompare(sortB, undefined, options);
  if (primary !== 0) {
    return primary;
  }
  const displayA = (a.Name || "").trim();
  const displayB = (b.Name || "").trim();
  const secondary = displayA.localeCompare(displayB, undefined, options);
  if (secondary !== 0) {
    return secondary;
  }
  return (a.Id || "").localeCompare(b.Id || "");
}

function getReleaseTimestamp(item) {
  if (!item || typeof item !== "object") {
    return null;
  }
  if (item.PremiereDate) {
    const parsed = Date.parse(item.PremiereDate);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  const year = item.ProductionYear;
  if (year !== undefined && year !== null && year !== "") {
    const parsedYear = Number(year);
    if (Number.isFinite(parsedYear)) {
      return Date.UTC(parsedYear, 0, 1);
    }
  }
  return null;
}

function compareByDateDesc(a, b) {
  const valueA = getReleaseTimestamp(a);
  const valueB = getReleaseTimestamp(b);
  const normalizedA = valueA === null ? Number.NEGATIVE_INFINITY : valueA;
  const normalizedB = valueB === null ? Number.NEGATIVE_INFINITY : valueB;
  if (normalizedA !== normalizedB) {
    return normalizedB - normalizedA;
  }
  return compareByNameAsc(a, b);
}

const DEFAULT_SORT_OPTION = "name-asc";
const SORT_OPTIONS = {
  "name-asc": {
    sortBy: "SortName",
    sortOrder: "Ascending",
    clientComparator: compareByNameAsc,
  },
  "date-desc": {
    sortBy: "PremiereDate",
    sortOrder: "Descending",
    clientComparator: compareByDateDesc,
  },
};

export function getSelectedSortOptionKey() {
  if (!sortSelect) {
    return DEFAULT_SORT_OPTION;
  }
  const value = sortSelect.value;
  if (value && SORT_OPTIONS[value]) {
    return value;
  }
  return DEFAULT_SORT_OPTION;
}

export function getSortOptionConfig(key) {
  return SORT_OPTIONS[key] || SORT_OPTIONS[DEFAULT_SORT_OPTION];
}

function applyClientSort(items, sortKey) {
  if (!Array.isArray(items)) {
    return [];
  }
  const key = sortKey && SORT_OPTIONS[sortKey] ? sortKey : DEFAULT_SORT_OPTION;
  const comparator = SORT_OPTIONS[key].clientComparator;
  if (typeof comparator !== "function") {
    return [...items];
  }
  return [...items].sort(comparator);
}

function formatReleaseLabel(item) {
  const timestamp = getReleaseTimestamp(item);
  if (timestamp !== null) {
    const date = new Date(timestamp);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    }
  }
  if (item && item.ProductionYear) {
    return String(item.ProductionYear);
  }
  return "";
}

function buildDetailKey(itemId, index) {
  const rawValue = itemId || `item-${index}`;
  return rawValue.replace(/[^A-Za-z0-9_-]/g, "-");
}

function checkbox(item) {
  const checked = searchState.selectedIds.has(item.Id) ? " checked" : "";
  const safeId = escapeHtml(item.Id);
  const safeName = escapeHtml(item.Name || "");
  const safeType = escapeHtml(item.Type || "");
  return `<input type="checkbox" class="sel" data-id="${safeId}" data-name="${safeName}" data-type="${safeType}"${checked}>`;
}

function renderResults(items) {
  closeInlineTagEditor({ focusTrigger: false });
  if (!items.length) {
    setHtml("results", '<div class="results-empty">No items found.</div>');
    const selAll = document.getElementById("selAll");
    if (selAll) {
      updateSelectAllState(selAll, []);
    }
    updateSelectionSummary();
    return;
  }
  const rows = items
    .map((item, index) => {
      const safeId = escapeHtml(item.Id || "");
      const isSelected = searchState.selectedIds.has(item.Id);
      const detailKey = buildDetailKey(item.Id, index);
      const detailRowId = `result-details-${detailKey}`;
      const detailButton = `
        <button
          type="button"
          class="result-details-toggle"
          data-target-id="${detailRowId}"
          aria-controls="${detailRowId}"
          aria-expanded="false"
        >
          Details
        </button>
      `;
      const rowClasses = ["result-row"];
      if (isSelected) {
        rowClasses.push("is-selected");
      }
      const attributes = [];
      if (rowClasses.length) {
        attributes.push(`class="${rowClasses.join(" ")}"`);
      }
      if (safeId) {
        attributes.push(`data-id="${safeId}"`);
      }
      const attrString = attributes.length ? ` ${attributes.join(" ")}` : "";
      const safeType = escapeHtml(item.Type || "");
      const typeLabel = safeType ? `<span class="type-badge">${safeType}</span>` : '<span class="type-badge type-badge-empty">Unknown</span>';
      const safeName = escapeHtml(item.Name || "");
      const safePath = escapeHtml(item.Path || "");
      const normalizedTags = normalizeTagList(item.Tags || []);
      const tagsHtml = normalizedTags.length
        ? normalizedTags.map((tag) => `<span class="tag-badge">${escapeHtml(tag)}</span>`).join("")
        : '<span class="inline-tag-summary-text inline-tag-empty">No tags</span>';
      const editLabelBase = item.Name || item.Id || "item";
      const safeEditLabel = escapeHtml(`Edit tags for ${editLabelBase}`);
      const releaseLabel = escapeHtml(formatReleaseLabel(item));
      const releaseBadge = releaseLabel
        ? `<span class="meta-badge">${releaseLabel}</span>`
        : '<span class="meta-badge meta-badge-empty">TBD</span>';
      const genreList = Array.isArray(item.Genres) ? item.Genres.filter(Boolean) : [];
      const genreHtml = genreList.length
        ? `<span class="result-details-value">${genreList.map((genre) => escapeHtml(genre)).join(", ")}</span>`
        : "";
      const tagListText = normalizedTags.length
        ? `<span class="result-details-value">${normalizedTags.map((tag) => escapeHtml(tag)).join(", ")}</span>`
        : "";
      const detailSegments = [];
      if (releaseLabel) {
        detailSegments.push(`
          <div class="result-details-item">
            <span class="result-details-label">Release</span>
            <span class="result-details-value">${releaseLabel}</span>
          </div>
        `);
      }
      if (genreHtml) {
        detailSegments.push(`
          <div class="result-details-item">
            <span class="result-details-label">Genres</span>
            ${genreHtml}
          </div>
        `);
      }
      if (tagListText) {
        detailSegments.push(`
          <div class="result-details-item">
            <span class="result-details-label">Tags</span>
            ${tagListText}
          </div>
        `);
      }
      if (safePath) {
        detailSegments.push(`
          <div class="result-details-item">
            <span class="result-details-label">Path</span>
            <span class="result-details-value">${safePath}</span>
          </div>
        `);
      }
      const overviewText = item.Overview ? escapeHtml(item.Overview) : "";
      const overviewHtml = overviewText
        ? `<p class="result-details-overview">${overviewText}</p>`
        : "";
      const detailBody = `
        <tr
          class="result-details-row"
          id="${detailRowId}"
          data-details-for="${safeId}"
          aria-hidden="true"
        >
          <td colspan="6">
            <div class="result-details">
              ${detailSegments.join("")}
              ${overviewHtml}
              ${!detailSegments.length && !overviewHtml ? '<p class="result-details-empty">No extra info available.</p>' : ""}
            </div>
          </td>
        </tr>
      `;
      return `
    <tr${attrString}>
      <td class="result-field result-field--checkbox">
        <span class="sr-only">Select</span>
        ${checkbox(item)}
      </td>
      <td class="result-field result-field--type">
        <div class="result-field-label">Type</div>
        ${typeLabel}
      </td>
      <td class="result-field result-field--name">
        <div class="result-field-name-header">
          <div class="result-field-label">Name</div>
          ${detailButton}
        </div>
        <div class="result-field-value">${safeName}</div>
      </td>
      <td class="result-field result-field--release">
        <div class="result-field-label">Release</div>
        ${releaseBadge}
      </td>
      <td class="result-field result-field--path">
        <div class="result-field-label">Path</div>
        <div class="result-field-value">${safePath}</div>
      </td>
      <td class="result-field result-field--tags result-tags">
        <div class="inline-tag-control" data-id="${safeId}">
          <div class="inline-tag-summary" aria-live="polite">${tagsHtml}</div>
          <button type="button" class="inline-tag-edit" data-id="${safeId}" aria-label="${safeEditLabel}" aria-haspopup="dialog" aria-expanded="false">Edit</button>
        </div>
      </td>
    </tr>
    ${detailBody}
  `;
    })
    .join("");
  const table = `
    <div class="results-table-controls">
      <label>
        <input type="checkbox" id="selAll" />
        Select all visible
      </label>
    </div>
    <table>
      <tbody>${rows}</tbody>
    </table>
  `;
  setHtml("results", table);
  setupDetailToggles();

  const selAll = document.getElementById("selAll");
  const rowCheckboxes = Array.from(document.querySelectorAll("input.sel"));

  rowCheckboxes.forEach((cb) => {
    const row = cb.closest("tr");
    if (row) {
      row.classList.toggle("is-selected", cb.checked);
    }
    if (cb.checked) {
      const id = cb.dataset.id;
      if (id) {
        searchState.selectedIds.add(id);
        const item = searchState.itemsById.get(id) || items.find((candidate) => candidate.Id === id);
        const tags = item ? normalizeTagList(item.Tags || []) : [];
        searchState.selectedDetails.set(id, {
          id,
          name: cb.dataset.name || "",
          type: cb.dataset.type || "",
          tags,
        });
      }
    }
    if (row) {
      const id = cb.dataset.id;
      if (id) {
        const item = searchState.itemsById.get(id) || items.find((candidate) => candidate.Id === id);
        if (item) {
          try {
            row.dataset.item = JSON.stringify(item);
          } catch (error) {
            row.dataset.item = "";
          }
          const control = row.querySelector(".inline-tag-control");
          if (control) {
            updateInlineTagSummary(control, item.Tags || []);
          }
        }
      }
    }
    cb.addEventListener("change", () => {
      applySelectionFromCheckbox(cb);
      updateSelectAllState(selAll, rowCheckboxes);
    });
  });

  if (selAll) {
    selAll.addEventListener("change", () => {
      selAll.indeterminate = false;
      rowCheckboxes.forEach((cb) => {
        cb.checked = selAll.checked;
        applySelectionFromCheckbox(cb);
      });
      updateSelectAllState(selAll, rowCheckboxes);
    });
    updateSelectAllState(selAll, rowCheckboxes);
  }

  updateSelectionSummary();
}

function setupDetailToggles() {
  const toggles = document.querySelectorAll(".result-details-toggle");
  toggles.forEach((toggle) => {
    const targetId = toggle.dataset.targetId;
    const targetRow = targetId ? document.getElementById(targetId) : null;
    if (!targetRow) {
      return;
    }
    targetRow.classList.remove("is-visible");
    targetRow.setAttribute("aria-hidden", "true");
    toggle.setAttribute("aria-expanded", "false");
    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      const nextState = !expanded;
      toggle.setAttribute("aria-expanded", String(nextState));
      targetRow.classList.toggle("is-visible", nextState);
      targetRow.setAttribute("aria-hidden", String(!nextState));
    });
  });
}

function updatePaginationControls(returned, filteredTotal) {
  const { prev, next, summary } = paginationControls;
  if (prev) {
    const hasPrev = filteredTotal > 0 && searchState.startIndex > 0;
    prev.disabled = !hasPrev;
  }
  if (next) {
    const nextStart = searchState.startIndex + searchState.limit;
    next.disabled = !(filteredTotal > 0 && nextStart < filteredTotal);
  }
  if (summary) {
    if (filteredTotal === 0) {
      summary.textContent = searchState.queryKey ? "No items found" : "";
    } else {
      const start = Math.min(filteredTotal, searchState.startIndex + 1);
      let end = returned
        ? Math.min(filteredTotal, searchState.startIndex + returned)
        : Math.min(filteredTotal, searchState.startIndex + searchState.limit);
      if (end < start) {
        end = start;
      }
      summary.textContent = `${start}-${end} of ${filteredTotal}`;
    }
  }
}

export function readSearchFilters() {
  const typesInput = val("types");
  const parsedTypes = splitTags(typesInput);
  const types = parsedTypes.length > 0 ? parsedTypes : null;
  const titleQueryValue = val("titleQuery");
  const titleQuery = titleQueryValue ? titleQueryValue : null;
  const includeTagsValue = val("includeTags");
  const excludeTagsValue = val("excludeTags");
  const excludeCollectionsEl = document.getElementById("excludeCollections");
  const excludeCollections = excludeCollectionsEl ? !!excludeCollectionsEl.checked : false;
  return {
    types,
    titleQuery,
    includeTags: includeTagsValue,
    excludeTags: excludeTagsValue,
    excludeCollections,
  };
}

function buildSearchBody(startIndex) {
  const filters = readSearchFilters();
  const sortKey = getSelectedSortOptionKey();
  const sortConfig = getSortOptionConfig(sortKey);
  return {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId")?.value,
    libraryId: document.getElementById("libraryId")?.value,
    types: filters.types,
    titleQuery: filters.titleQuery,
    includeTags: filters.includeTags,
    excludeTags: filters.excludeTags,
    excludeCollections: filters.excludeCollections,
    startIndex,
    limit: searchState.limit,
    sortBy: sortConfig.sortBy,
    sortOrder: sortConfig.sortOrder,
    sortOption: sortKey,
  };
}

function buildSearchQueryKey(body) {
  const types = Array.isArray(body.types) && body.types.length > 0 ? body.types : null;
  const titleQuery = typeof body.titleQuery === "string" && body.titleQuery.trim() ? body.titleQuery.trim() : null;
  return JSON.stringify({
    base: body.base,
    userId: body.userId,
    libraryId: body.libraryId,
    types,
    titleQuery,
    includeTags: body.includeTags,
    excludeTags: body.excludeTags,
    excludeCollections: body.excludeCollections,
    sortBy: body.sortBy,
    sortOrder: body.sortOrder,
  });
}

export async function search({ startIndex, reset = false } = {}) {
  const validationMessage = validateServerConfig();
  if (validationMessage) {
    setHtml("resultSummary", escapeHtml(validationMessage));
    return;
  }
  const previousStartIndex = searchState.startIndex;
  const previousQueryKey = searchState.queryKey;
  const previousTotal = searchState.total;
  const targetStart = typeof startIndex === "number" ? Math.max(0, startIndex) : reset ? 0 : searchState.startIndex;
  const body = buildSearchBody(targetStart);
  const queryKey = buildSearchQueryKey(body);
  const isNewQuery = reset || queryKey !== searchState.queryKey;

  if (isNewQuery) {
    searchState.selectedIds.clear();
    searchState.selectedDetails.clear();
    searchState.itemsById.clear();
    searchState.total = 0;
    updateSelectionSummary();
  }

  setHtml("resultSummary", "Loading results...");
  setHtml("results", '<div class="results-loading">Loading...</div>');
  if (paginationControls.prev) {
    paginationControls.prev.disabled = true;
  }
  if (paginationControls.next) {
    paginationControls.next.disabled = true;
  }
  if (paginationControls.summary) {
    paginationControls.summary.textContent = "";
  }

  try {
    const data = await api("/api/items", body);
    const sortKey = body.sortOption || getSelectedSortOptionKey();
    let items = data.Items || [];
    items = applyClientSort(items, sortKey);
    const returned = items.length;
    const filteredTotal = data.TotalMatchCount ?? data.TotalRecordCount ?? returned;

    searchState.startIndex = targetStart;
    searchState.total = filteredTotal;
    searchState.queryKey = queryKey;

    items.forEach((item) => {
      searchState.itemsById.set(item.Id, item);
      if (searchState.selectedIds.has(item.Id) && !searchState.selectedDetails.has(item.Id)) {
        searchState.selectedDetails.set(item.Id, {
          id: item.Id,
          name: item.Name || "",
          type: item.Type || "",
        });
      }
    });

    renderResults(items);

    if (filteredTotal === 0) {
      setHtml("resultSummary", "No items found");
    } else {
      const startNumber = Math.min(filteredTotal, searchState.startIndex + 1);
      let endNumber = returned
        ? Math.min(filteredTotal, searchState.startIndex + returned)
        : Math.min(filteredTotal, searchState.startIndex + searchState.limit);
      if (endNumber < startNumber) {
        endNumber = startNumber;
      }
      const summaryText = `Showing items ${startNumber}–${endNumber} of ${filteredTotal}`;
      setHtml("resultSummary", summaryText);
    }

    updatePaginationControls(returned, filteredTotal);
  } catch (error) {
    searchState.startIndex = previousStartIndex;
    searchState.queryKey = previousQueryKey;
    searchState.total = previousTotal;
    console.error(error);
    setHtml("resultSummary", `Error loading items: ${escapeHtml(error.message)}`);
    setHtml("results", '<div class="results-empty">Unable to load results.</div>');
    updatePaginationControls(0, searchState.total);
  }
}

async function loadUsers() {
  if (!userSelect) {
    return;
  }
  const validationMessage = validateServerConfig();
  if (validationMessage) {
    setStatus(userStatusEl, validationMessage);
    return;
  }
  setStatus(userStatusEl, "");
  setButtonLoading(btnUsers, true, "Loading...");
  setStatus(userStatusEl, "Loading users…");
  setSelectPlaceholder(userSelect, "Loading users…");
  userSelect.disabled = true;
  try {
    const data = await api("/api/users", { base: val("base"), apiKey: val("apiKey") });
    if (Array.isArray(data) && data.length) {
      const opts = `<option value="" disabled selected>Select a user</option>${optionList(data, "Id", "Name")}`;
      userSelect.innerHTML = opts;
      userSelect.disabled = false;
      setStatus(userStatusEl, `${data.length} ${pluralize(data.length, "user")} loaded`);
      if (librarySelect) {
        setSelectPlaceholder(librarySelect, "Select a user first");
        librarySelect.disabled = true;
      }
      setStatus(libraryStatusEl, "Choose a user to load libraries.");
    } else {
      setSelectPlaceholder(userSelect, "No users found");
      userSelect.disabled = true;
      setStatus(userStatusEl, "No users found");
      if (librarySelect) {
        setSelectPlaceholder(librarySelect, "Load libraries first");
        librarySelect.disabled = true;
      }
      setStatus(libraryStatusEl, "No users available; cannot load libraries.");
    }
  } catch (error) {
    setSelectPlaceholder(userSelect, "Load users first");
    userSelect.disabled = true;
    setStatus(userStatusEl, `Error loading users: ${error.message}`);
    if (librarySelect) {
      setSelectPlaceholder(librarySelect, "Load libraries first");
      librarySelect.disabled = true;
    }
    setStatus(libraryStatusEl, "Load users before libraries.");
  } finally {
    setButtonLoading(btnUsers, false);
  }
}

async function loadLibraries() {
  if (!librarySelect || !userSelect) {
    return;
  }
  const validationMessage = validateServerConfig();
  if (validationMessage) {
    setStatus(libraryStatusEl, validationMessage);
    return;
  }
  const userId = userSelect.value;
  if (!userId) {
    setStatus(libraryStatusEl, "Select a user first.");
    userSelect.focus();
    return;
  }
  setStatus(libraryStatusEl, "");
  setButtonLoading(btnLibs, true, "Loading...");
  setStatus(libraryStatusEl, "Loading libraries…");
  setSelectPlaceholder(librarySelect, "Loading libraries…");
  librarySelect.disabled = true;
  try {
    const data = await api("/api/libraries", { base: val("base"), apiKey: val("apiKey"), userId });
    if (Array.isArray(data) && data.length) {
      const opts = data
        .map((entry) => ({ value: entry.ItemId, text: `${entry.Name} (${entry.CollectionType || "?"})` }))
        .map((option) => `<option value="${option.value}">${option.text}</option>`)
        .join("");
      librarySelect.innerHTML = `<option value="" disabled selected>Select a library</option>${opts}`;
      librarySelect.disabled = false;
      setStatus(libraryStatusEl, `${data.length} ${pluralize(data.length, "library")} loaded`);
    } else {
      setSelectPlaceholder(librarySelect, "No libraries found");
      librarySelect.disabled = true;
      setStatus(libraryStatusEl, "No libraries found for this user.");
    }
  } catch (error) {
    setSelectPlaceholder(librarySelect, "Load libraries first");
    librarySelect.disabled = true;
    setStatus(libraryStatusEl, `Error loading libraries: ${error.message}`);
  } finally {
    setButtonLoading(btnLibs, false);
  }
}

function handleUserChange() {
  if (!librarySelect || !userSelect) {
    return;
  }
  if (!userSelect.value) {
    setSelectPlaceholder(librarySelect, "Select a user first");
    librarySelect.disabled = true;
    setStatus(libraryStatusEl, "Choose a user to load libraries.");
    return;
  }
  setSelectPlaceholder(librarySelect, "Load libraries first");
  librarySelect.disabled = true;
  setStatus(libraryStatusEl, "Click Load Libraries to fetch options.");
}

export function initializeSearch() {
  if (userSelect) {
    userSelect.addEventListener("change", handleUserChange);
  }
  if (btnUsers) {
    btnUsers.addEventListener("click", loadUsers);
  }
  if (btnLibs) {
    btnLibs.addEventListener("click", loadLibraries);
  }
  if (btnSearch) {
    btnSearch.addEventListener("click", () => {
      const validationMessage = validateServerConfig();
      if (validationMessage) {
        setHtml("resultSummary", escapeHtml(validationMessage));
        return;
      }
      search({ startIndex: 0, reset: true });
    });
  }
  if (paginationControls.prev) {
    paginationControls.prev.addEventListener("click", () => {
      if (searchState.startIndex <= 0) {
        return;
      }
      const newStart = Math.max(0, searchState.startIndex - searchState.limit);
      search({ startIndex: newStart });
    });
  }
  if (paginationControls.next) {
    paginationControls.next.addEventListener("click", () => {
      const newStart = searchState.startIndex + searchState.limit;
      if (searchState.total > 0 && newStart < searchState.total) {
        search({ startIndex: newStart });
      }
    });
  }
  updatePaginationControls(0, 0);
  updateSelectionSummary();
}
