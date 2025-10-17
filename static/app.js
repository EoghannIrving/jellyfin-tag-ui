function val(id){ return document.getElementById(id).value.trim(); }
function setHtml(id, html){ document.getElementById(id).innerHTML = html; }
function splitTags(s){
  if(!s) return [];
  return [...new Set(s.split(/[;,]/).map(t=>t.trim()).filter(Boolean))];
}
function api(path, body){
  return fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {})
  }).then(r => {
    if(!r.ok) throw new Error(r.status + " " + r.statusText);
    return r.json();
  });
}
function optionList(arr, valueKey, textKey){
  return arr.map(o => `<option value="${o[valueKey]}">${o[textKey] || o[valueKey]}</option>`).join("");
}

const btnUsers = document.getElementById("btnUsers");
const btnLibs = document.getElementById("btnLibs");
const userSelect = document.getElementById("userId");
const librarySelect = document.getElementById("libraryId");
const sortSelect = document.getElementById("sortOption");
const userStatusEl = document.getElementById("userStatus");
const libraryStatusEl = document.getElementById("libraryStatus");
const searchState = {
  startIndex: 0,
  limit: 100,
  total: 0,
  queryKey: "",
  itemsById: new Map(),
  selectedIds: new Set(),
  selectedDetails: new Map(),
};

const paginationControls = {
  prev: document.getElementById("btnPrevPage"),
  next: document.getElementById("btnNextPage"),
  summary: document.getElementById("pageSummary"),
};

function checkbox(item){
  const checked = searchState.selectedIds.has(item.Id) ? " checked" : "";
  const safeId = escapeHtml(item.Id);
  const safeName = escapeHtml(item.Name || "");
  const safeType = escapeHtml(item.Type || "");
  return `<input type="checkbox" class="sel" data-id="${safeId}" data-name="${safeName}" data-type="${safeType}"${checked}>`;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch] || ch);
}

function setStatus(el, text){
  if(!el){ return; }
  el.textContent = text || "";
}

function pluralize(count, singular, plural){
  if(count === 1){ return singular; }
  if(plural){ return plural; }
  if(singular.endsWith("y")){
    return `${singular.slice(0, -1)}ies`;
  }
  return `${singular}s`;
}

function setButtonLoading(button, isLoading, loadingText){
  if(!button){ return; }
  if(isLoading){
    if(!button.dataset.originalText){
      button.dataset.originalText = button.textContent;
    }
    button.disabled = true;
    if(loadingText){
      button.textContent = loadingText;
    }
    button.setAttribute("aria-busy", "true");
  } else {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    if(button.dataset.originalText){
      button.textContent = button.dataset.originalText;
      delete button.dataset.originalText;
    }
  }
}

function setSelectPlaceholder(selectEl, text){
  if(!selectEl){ return; }
  const safeText = escapeHtml(text || "");
  selectEl.innerHTML = `<option value="" disabled selected>${safeText}</option>`;
  selectEl.value = "";
}

function getResultRowCheckboxes(){
  return Array.from(document.querySelectorAll("input.sel"));
}

const tagStates = new Map();
let allTags = [];
const tagSearchInput = document.getElementById("tagSearch");
const tagActionSummaryEl = document.getElementById("tagActionSummary");
const clearTagSelectionsButton = document.getElementById("btnClearTagSelections");
const selectedItemsListEl = document.getElementById("selectedItemsList");
const selectedItemsPanelEl = document.getElementById("selectedItemsPanel");

function compareByNameAsc(a, b){
  const options = {sensitivity: "base"};
  const sortA = (a.SortName || a.Name || "").trim();
  const sortB = (b.SortName || b.Name || "").trim();
  const primary = sortA.localeCompare(sortB, undefined, options);
  if(primary !== 0){
    return primary;
  }
  const displayA = (a.Name || "").trim();
  const displayB = (b.Name || "").trim();
  const secondary = displayA.localeCompare(displayB, undefined, options);
  if(secondary !== 0){
    return secondary;
  }
  return (a.Id || "").localeCompare(b.Id || "");
}

function getReleaseTimestamp(item){
  if(!item || typeof item !== "object"){ return null; }
  if(item.PremiereDate){
    const parsed = Date.parse(item.PremiereDate);
    if(!Number.isNaN(parsed)){ return parsed; }
  }
  const year = item.ProductionYear;
  if(year !== undefined && year !== null && year !== ""){
    const parsedYear = Number(year);
    if(Number.isFinite(parsedYear)){
      return Date.UTC(parsedYear, 0, 1);
    }
  }
  return null;
}

function compareByDateDesc(a, b){
  const valueA = getReleaseTimestamp(a);
  const valueB = getReleaseTimestamp(b);
  const normalizedA = valueA === null ? Number.NEGATIVE_INFINITY : valueA;
  const normalizedB = valueB === null ? Number.NEGATIVE_INFINITY : valueB;
  if(normalizedA !== normalizedB){
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

function getSelectedSortOptionKey(){
  if(!sortSelect){ return DEFAULT_SORT_OPTION; }
  const value = sortSelect.value;
  if(value && SORT_OPTIONS[value]){
    return value;
  }
  return DEFAULT_SORT_OPTION;
}

function getSortOptionConfig(key){
  return SORT_OPTIONS[key] || SORT_OPTIONS[DEFAULT_SORT_OPTION];
}

function applyClientSort(items, sortKey){
  if(!Array.isArray(items)){
    return [];
  }
  const key = sortKey && SORT_OPTIONS[sortKey] ? sortKey : DEFAULT_SORT_OPTION;
  const comparator = SORT_OPTIONS[key].clientComparator;
  if(typeof comparator !== "function"){
    return [...items];
  }
  return [...items].sort(comparator);
}

function formatReleaseLabel(item){
  const timestamp = getReleaseTimestamp(item);
  if(timestamp !== null){
    const date = new Date(timestamp);
    if(!Number.isNaN(date.getTime())){
      return date.toLocaleDateString(undefined, {year: "numeric", month: "short", day: "numeric"});
    }
  }
  if(item && item.ProductionYear){
    return String(item.ProductionYear);
  }
  return "";
}

if(selectedItemsListEl){
  selectedItemsListEl.setAttribute("aria-live", "polite");
}

const TAG_STATE_CONFIG = {
  "": {
    className: "",
    ariaPressed: "false",
    icon: "•",
    label: (tag) => `No change for tag ${tag}`,
  },
  add: {
    className: "tag-add",
    ariaPressed: "true",
    icon: "+",
    label: (tag) => `Will add tag ${tag}`,
  },
  remove: {
    className: "tag-remove",
    ariaPressed: "mixed",
    icon: "–",
    label: (tag) => `Will remove tag ${tag}`,
  },
};

function getTagActionCounts(){
  let add = 0;
  let remove = 0;
  tagStates.forEach((state) => {
    if(state === "add"){ add += 1; }
    if(state === "remove"){ remove += 1; }
  });
  return {add, remove};
}

function updateTagActionSummary(){
  if(!tagActionSummaryEl){ return; }
  const {add, remove} = getTagActionCounts();
  if(add === 0 && remove === 0){
    tagActionSummaryEl.textContent = "No tag changes selected";
    return;
  }
  const parts = [];
  parts.push(`${add} to add`);
  parts.push(`${remove} to remove`);
  tagActionSummaryEl.textContent = parts.join(" · ");
}

function applyTagState(button, state) {
  const config = TAG_STATE_CONFIG[state] || TAG_STATE_CONFIG[""];
  const tag = button.dataset.tag || "";
  button.dataset.state = state;
  button.classList.remove("tag-add", "tag-remove");
  if (config.className) {
    button.classList.add(config.className);
  }
  button.setAttribute("aria-pressed", config.ariaPressed);
  button.setAttribute("aria-label", config.label(tag));
  const iconEl = button.querySelector(".tag-icon");
  if (iconEl) {
    iconEl.textContent = config.icon;
  }
  const textEl = button.querySelector(".tag-text");
  if (textEl) {
    textEl.textContent = tag;
  }
}

function currentTagSearchQuery(){
  return tagSearchInput ? tagSearchInput.value : "";
}

function filterTagsByQuery(tags, query){
  const q = (query || "").trim().toLowerCase();
  if(!q){
    return [...tags];
  }
  return tags.filter(tag => tag.toLowerCase().includes(q));
}

function renderTagButtons(tags){
  if(!tags.length){
    const hasQuery = currentTagSearchQuery().trim().length > 0;
    setHtml("tagList", hasQuery ? '<div class="tag-empty">No tags match your search.</div>' : "");
    updateTagActionSummary();
    return;
  }
  const html = tags.map(tag => {
    const state = tagStates.get(tag) || "";
    const config = TAG_STATE_CONFIG[state] || TAG_STATE_CONFIG[""];
    const safeTag = escapeHtml(tag);
    const ariaLabel = escapeHtml(config.label(tag));
    const stateClass = config.className ? ` ${config.className}` : "";
    return `
      <button type="button" class="tag${stateClass}" data-tag="${safeTag}" data-state="${state}" aria-pressed="${config.ariaPressed}" aria-label="${ariaLabel}">
        <span class="tag-icon" aria-hidden="true">${config.icon}</span>
        <span class="tag-text">${safeTag}</span>
      </button>
    `;
  }).join(" ");
  setHtml("tagList", html);
  document.querySelectorAll("#tagList .tag").forEach((button) => {
    applyTagState(button, button.dataset.state || "");
  });
  updateTagActionSummary();
}

function buildSearchBody(startIndex){
  const typesInput = val("types");
  const parsedTypes = splitTags(typesInput);
  const types = parsedTypes.length > 0 ? parsedTypes : null;
  const sortKey = getSelectedSortOptionKey();
  const sortConfig = getSortOptionConfig(sortKey);
  return {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId").value,
    libraryId: document.getElementById("libraryId").value,
    types,
    includeTags: val("includeTags"),
    excludeTags: val("excludeTags"),
    excludeCollections: document.getElementById("excludeCollections").checked,
    startIndex,
    limit: searchState.limit,
    sortBy: sortConfig.sortBy,
    sortOrder: sortConfig.sortOrder,
    sortOption: sortKey,
  };
}

function buildSearchQueryKey(body){
  const types = Array.isArray(body.types) && body.types.length > 0 ? body.types : null;
  return JSON.stringify({
    base: body.base,
    userId: body.userId,
    libraryId: body.libraryId,
    types,
    includeTags: body.includeTags,
    excludeTags: body.excludeTags,
    excludeCollections: body.excludeCollections,
    sortBy: body.sortBy,
    sortOrder: body.sortOrder,
  });
}

function getSortedSelectedItems(){
  return Array.from(searchState.selectedDetails.values()).sort((a, b) => {
    const nameA = (a.name || "").toLocaleLowerCase();
    const nameB = (b.name || "").toLocaleLowerCase();
    if(nameA === nameB){
      return (a.id || "").localeCompare(b.id || "");
    }
    return nameA.localeCompare(nameB);
  });
}

function renderSelectedItemsList(){
  if(!selectedItemsListEl){ return; }
  const selectedItems = getSortedSelectedItems();
  if(selectedItems.length === 0){
    selectedItemsListEl.innerHTML = '<li class="selected-items-empty">No items selected.</li>';
    return;
  }
  const html = selectedItems.map((item) => {
    const safeId = escapeHtml(item.id || "");
    const safeName = escapeHtml(item.name || "(no name)");
    const safeType = escapeHtml(item.type || "Unknown");
    return `
      <li class="selected-item" data-id="${safeId}">
        <div class="selected-item-info">
          <span class="selected-item-name">${safeName}</span>
          <span class="selected-item-type">${safeType}</span>
        </div>
        <button type="button" class="selected-item-remove" data-id="${safeId}">Remove</button>
      </li>
    `;
  }).join("");
  selectedItemsListEl.innerHTML = html;
}

function updateSelectionSummary(){
  const selected = searchState.selectedIds.size;
  const label = selected === 0
    ? "No items selected"
    : `${selected} item${selected === 1 ? "" : "s"} selected`;
  setHtml("selectionSummary", label);
  renderSelectedItemsList();
}

function updateSelectAllState(selAll, rowCheckboxes){
  if(!selAll){ return; }
  const total = rowCheckboxes.length;
  const checkedCount = rowCheckboxes.filter(cb => cb.checked).length;
  if(total === 0){
    selAll.checked = false;
    selAll.indeterminate = false;
    selAll.disabled = true;
    return;
  }
  selAll.disabled = false;
  if(checkedCount === 0){
    selAll.checked = false;
    selAll.indeterminate = false;
  } else if(checkedCount === total){
    selAll.checked = true;
    selAll.indeterminate = false;
  } else {
    selAll.checked = false;
    selAll.indeterminate = true;
  }
}

function applySelectionFromCheckbox(cb){
  if(!cb){ return; }
  const id = cb.dataset.id;
  if(!id){ return; }
  if(cb.checked){
    searchState.selectedIds.add(id);
    searchState.selectedDetails.set(id, {
      id,
      name: cb.dataset.name || "",
      type: cb.dataset.type || "",
    });
  } else {
    searchState.selectedIds.delete(id);
    searchState.selectedDetails.delete(id);
  }
  updateSelectionSummary();
}

function renderResults(items){
  if(!items.length){
    setHtml("results", '<div class="results-empty">No items found.</div>');
    const selAll = document.getElementById("selAll");
    if(selAll){
      updateSelectAllState(selAll, []);
    }
    updateSelectionSummary();
    return;
  }
  const rows = items.map(it => {
    const safeType = escapeHtml(it.Type || "");
    const safeName = escapeHtml(it.Name || "");
    const safePath = escapeHtml(it.Path || "");
    const safeTags = escapeHtml((it.Tags || []).join("; "));
    const releaseLabel = escapeHtml(formatReleaseLabel(it));
    return `
    <tr>
      <td>${checkbox(it)}</td>
      <td>${safeType}</td>
      <td>${safeName}</td>
      <td>${releaseLabel}</td>
      <td>${safePath}</td>
      <td>${safeTags}</td>
    </tr>
  `;
  }).join("");
  const table = `
    <table>
      <thead><tr><th><input type="checkbox" id="selAll"></th><th>Type</th><th>Name</th><th>Release</th><th>Path</th><th>Tags</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  setHtml("results", table);

  const selAll = document.getElementById("selAll");
  const rowCheckboxes = getResultRowCheckboxes();

  rowCheckboxes.forEach(cb => {
    if(cb.checked){
      const id = cb.dataset.id;
      if(id){
        searchState.selectedIds.add(id);
        searchState.selectedDetails.set(id, {
          id,
          name: cb.dataset.name || "",
          type: cb.dataset.type || "",
        });
      }
    }
    cb.addEventListener("change", () => {
      applySelectionFromCheckbox(cb);
      updateSelectAllState(selAll, rowCheckboxes);
    });
  });

  if(selAll){
    selAll.addEventListener("change", () => {
      selAll.indeterminate = false;
      rowCheckboxes.forEach(cb => {
        cb.checked = selAll.checked;
        applySelectionFromCheckbox(cb);
      });
      updateSelectAllState(selAll, rowCheckboxes);
    });
    updateSelectAllState(selAll, rowCheckboxes);
  }

  updateSelectionSummary();
}

function updatePaginationControls(returned, filteredTotal){
  const {prev, next, summary} = paginationControls;
  if(prev){
    const hasPrev = filteredTotal > 0 && searchState.startIndex > 0;
    prev.disabled = !hasPrev;
  }
  if(next){
    const nextStart = searchState.startIndex + searchState.limit;
    next.disabled = !(filteredTotal > 0 && nextStart < filteredTotal);
  }
  if(summary){
    if(filteredTotal === 0){
      summary.textContent = searchState.queryKey ? "No items found" : "";
    } else {
      const start = Math.min(filteredTotal, searchState.startIndex + 1);
      let end = returned ? Math.min(filteredTotal, searchState.startIndex + returned) : Math.min(filteredTotal, searchState.startIndex + searchState.limit);
      if(end < start){
        end = start;
      }
      summary.textContent = `${start}-${end} of ${filteredTotal}`;
    }
  }
}

if(btnUsers){
  btnUsers.addEventListener("click", async ()=>{
    if(!userSelect){ return; }
    setButtonLoading(btnUsers, true, "Loading...");
    setStatus(userStatusEl, "Loading users…");
    setSelectPlaceholder(userSelect, "Loading users…");
    userSelect.disabled = true;
    try {
      const data = await api("/api/users", {base: val("base"), apiKey: val("apiKey")});
      if(Array.isArray(data) && data.length){
        const opts = `<option value="" disabled selected>Select a user</option>${optionList(data, "Id", "Name")}`;
        userSelect.innerHTML = opts;
        userSelect.disabled = false;
        setStatus(userStatusEl, `${data.length} ${pluralize(data.length, "user")} loaded`);
        if(librarySelect){
          setSelectPlaceholder(librarySelect, "Select a user first");
          librarySelect.disabled = true;
        }
        setStatus(libraryStatusEl, "Choose a user to load libraries.");
      } else {
        setSelectPlaceholder(userSelect, "No users found");
        userSelect.disabled = true;
        setStatus(userStatusEl, "No users found");
        if(librarySelect){
          setSelectPlaceholder(librarySelect, "Load libraries first");
          librarySelect.disabled = true;
        }
        setStatus(libraryStatusEl, "No users available; cannot load libraries.");
      }
    } catch (e) {
      setSelectPlaceholder(userSelect, "Load users first");
      userSelect.disabled = true;
      setStatus(userStatusEl, `Error loading users: ${e.message}`);
      if(librarySelect){
        setSelectPlaceholder(librarySelect, "Load libraries first");
        librarySelect.disabled = true;
      }
      setStatus(libraryStatusEl, "Load users before libraries.");
    } finally {
      setButtonLoading(btnUsers, false);
    }
  });
}

if(userSelect){
  userSelect.addEventListener("change", () => {
    if(!librarySelect){ return; }
    if(!userSelect.value){
      setSelectPlaceholder(librarySelect, "Select a user first");
      librarySelect.disabled = true;
      setStatus(libraryStatusEl, "Choose a user to load libraries.");
      return;
    }
    setSelectPlaceholder(librarySelect, "Load libraries first");
    librarySelect.disabled = true;
    setStatus(libraryStatusEl, "Click Load Libraries to fetch options.");
  });
}

if(btnLibs){
  btnLibs.addEventListener("click", async ()=>{
    if(!librarySelect || !userSelect){ return; }
    const userId = userSelect.value;
    if(!userId){
      setStatus(libraryStatusEl, "Select a user first.");
      userSelect.focus();
      return;
    }
    setButtonLoading(btnLibs, true, "Loading...");
    setStatus(libraryStatusEl, "Loading libraries…");
    setSelectPlaceholder(librarySelect, "Loading libraries…");
    librarySelect.disabled = true;
    try {
      const data = await api("/api/libraries", {base: val("base"), apiKey: val("apiKey"), userId});
      if(Array.isArray(data) && data.length){
        const opts = data.map(x => ({value: x.ItemId, text: `${x.Name} (${x.CollectionType||"?"})`}))
                        .map(o => `<option value="${o.value}">${o.text}</option>`).join("");
        librarySelect.innerHTML = `<option value="" disabled selected>Select a library</option>${opts}`;
        librarySelect.disabled = false;
        setStatus(libraryStatusEl, `${data.length} ${pluralize(data.length, "library")} loaded`);
      } else {
        setSelectPlaceholder(librarySelect, "No libraries found");
        librarySelect.disabled = true;
        setStatus(libraryStatusEl, "No libraries found for this user.");
      }
    } catch (e) {
      setSelectPlaceholder(librarySelect, "Load libraries first");
      librarySelect.disabled = true;
      setStatus(libraryStatusEl, `Error loading libraries: ${e.message}`);
    } finally {
      setButtonLoading(btnLibs, false);
    }
  });
}

document.getElementById("btnTags").addEventListener("click", async ()=>{
  const body = {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId").value,
    libraryId: document.getElementById("libraryId").value,
    types: splitTags(val("types"))
  };
  setHtml("tagList", "Loading tags...");
  try {
    const data = await api("/api/tags", body);
    allTags = data.tags || [];
    const available = new Set(allTags);
    let removed = false;
    Array.from(tagStates.keys()).forEach(tag => {
      if(!available.has(tag)){
        tagStates.delete(tag);
        removed = true;
      }
    });
    if(removed){
      updateTagActionSummary();
    }
    renderTagButtons(filterTagsByQuery(allTags, currentTagSearchQuery()));
  } catch (e) {
    allTags = [];
    tagStates.clear();
    setHtml("tagList", `Error loading tags: ${e.message}`);
    updateTagActionSummary();
  }
});

function setTagInputs(addTags, removeTags) {
  const joiner = "; ";
  document.getElementById("applyAdd").value = addTags.join(joiner);
  document.getElementById("applyRemove").value = removeTags.join(joiner);
}

document.getElementById("tagList").addEventListener("click", (event) => {
  const target = event.target.closest(".tag");
  if (!target || !target.dataset.tag) {
    return;
  }

  const tag = target.dataset.tag;
  const addInput = document.getElementById("applyAdd");
  const removeInput = document.getElementById("applyRemove");
  const addTags = splitTags(addInput.value);
  const removeTags = splitTags(removeInput.value);

  const currentState = target.dataset.state || "";

  const nextState =
    currentState === "add" ? "remove" : currentState === "remove" ? "" : "add";

  if (currentState === "add") {
    const idx = addTags.indexOf(tag);
    if (idx !== -1) {
      addTags.splice(idx, 1);
    }
  }

  if (currentState === "remove") {
    const idx = removeTags.indexOf(tag);
    if (idx !== -1) {
      removeTags.splice(idx, 1);
    }
  }

  if (nextState === "add") {
    if (!addTags.includes(tag)) {
      addTags.push(tag);
    }
    const removeIdx = removeTags.indexOf(tag);
    if (removeIdx !== -1) {
      removeTags.splice(removeIdx, 1);
    }
  } else if (nextState === "remove") {
    if (!removeTags.includes(tag)) {
      removeTags.push(tag);
    }
    const addIdx = addTags.indexOf(tag);
    if (addIdx !== -1) {
      addTags.splice(addIdx, 1);
    }
  }

  if (nextState) {
    tagStates.set(tag, nextState);
  } else {
    tagStates.delete(tag);
  }

  applyTagState(target, nextState);

  setTagInputs(addTags, removeTags);
  updateTagActionSummary();
});

if(clearTagSelectionsButton){
  clearTagSelectionsButton.addEventListener("click", () => {
    tagStates.clear();
    setTagInputs([], []);
    renderTagButtons(filterTagsByQuery(allTags, currentTagSearchQuery()));
    updateTagActionSummary();
  });
}

if(selectedItemsPanelEl){
  selectedItemsPanelEl.addEventListener("click", (event) => {
    const removeButton = event.target.closest(".selected-item-remove");
    if(!removeButton){ return; }
    const id = removeButton.dataset.id;
    if(!id){ return; }
    const checkbox = getResultRowCheckboxes().find((cb) => cb.dataset.id === id);
    if(checkbox){
      checkbox.checked = false;
      applySelectionFromCheckbox(checkbox);
      const selAll = document.getElementById("selAll");
      if(selAll){
        updateSelectAllState(selAll, getResultRowCheckboxes());
      }
    } else {
      searchState.selectedIds.delete(id);
      searchState.selectedDetails.delete(id);
      updateSelectionSummary();
    }
  });
}

if(tagSearchInput){
  tagSearchInput.addEventListener("input", ()=>{
    if(!allTags.length){ return; }
    renderTagButtons(filterTagsByQuery(allTags, tagSearchInput.value));
  });
}

async function search({startIndex, reset = false} = {}){
  const previousStartIndex = searchState.startIndex;
  const previousQueryKey = searchState.queryKey;
  const previousTotal = searchState.total;
  const targetStart = typeof startIndex === "number"
    ? Math.max(0, startIndex)
    : (reset ? 0 : searchState.startIndex);
  const body = buildSearchBody(targetStart);
  const queryKey = buildSearchQueryKey(body);
  const isNewQuery = reset || queryKey !== searchState.queryKey;

  if(isNewQuery){
    searchState.selectedIds.clear();
    searchState.selectedDetails.clear();
    searchState.itemsById.clear();
    searchState.total = 0;
    updateSelectionSummary();
  }

  setHtml("resultSummary", "Loading results...");
  setHtml("results", '<div class="results-loading">Loading...</div>');
  if(paginationControls.prev){ paginationControls.prev.disabled = true; }
  if(paginationControls.next){ paginationControls.next.disabled = true; }
  if(paginationControls.summary){ paginationControls.summary.textContent = ""; }

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

    items.forEach(item => {
      searchState.itemsById.set(item.Id, item);
      if(searchState.selectedIds.has(item.Id) && !searchState.selectedDetails.has(item.Id)){
        searchState.selectedDetails.set(item.Id, {
          id: item.Id,
          name: item.Name || "",
          type: item.Type || "",
        });
      }
    });

    renderResults(items);

    if(filteredTotal === 0){
      setHtml("resultSummary", "No items found");
    } else {
      const startNumber = Math.min(filteredTotal, searchState.startIndex + 1);
      let endNumber = returned ? Math.min(filteredTotal, searchState.startIndex + returned) : Math.min(filteredTotal, searchState.startIndex + searchState.limit);
      if(endNumber < startNumber){
        endNumber = startNumber;
      }
      const summaryText = `Showing items ${startNumber}–${endNumber} of ${filteredTotal}`;
      setHtml("resultSummary", summaryText);
    }

    updatePaginationControls(returned, filteredTotal);
  } catch (e) {
    searchState.startIndex = previousStartIndex;
    searchState.queryKey = previousQueryKey;
    searchState.total = previousTotal;
    console.error(e);
    setHtml("resultSummary", `Error loading items: ${escapeHtml(e.message)}`);
    setHtml("results", '<div class="results-empty">Unable to load results.</div>');
    updatePaginationControls(0, searchState.total);
  }
}

document.getElementById("btnSearch").addEventListener("click", ()=>search({startIndex: 0, reset: true}));

if(paginationControls.prev){
  paginationControls.prev.addEventListener("click", () => {
    if(searchState.startIndex <= 0){
      return;
    }
    const newStart = Math.max(0, searchState.startIndex - searchState.limit);
    search({startIndex: newStart});
  });
}

if(paginationControls.next){
  paginationControls.next.addEventListener("click", () => {
    const newStart = searchState.startIndex + searchState.limit;
    if(searchState.total > 0 && newStart < searchState.total){
      search({startIndex: newStart});
    }
  });
}

updateSelectionSummary();
updatePaginationControls(0, 0);
updateTagActionSummary();

document.getElementById("btnExport").addEventListener("click", async ()=>{
  const body = {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId").value,
    libraryId: document.getElementById("libraryId").value,
    types: splitTags(val("types")),
    excludeCollections: document.getElementById("excludeCollections").checked
  };
  const sortKey = getSelectedSortOptionKey();
  const sortConfig = getSortOptionConfig(sortKey);
  body.sortBy = sortConfig.sortBy;
  body.sortOrder = sortConfig.sortOrder;
  const res = await fetch("/api/export", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  if(!res.ok){ alert("Export failed"); return; }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "tags_export.csv";
  document.body.appendChild(a); a.click(); a.remove();
  window.URL.revokeObjectURL(url);
});

document.getElementById("btnApply").addEventListener("click", async ()=>{
  const adds = splitTags(document.getElementById("applyAdd").value);
  const rems = splitTags(document.getElementById("applyRemove").value);
  const selectedIds = Array.from(searchState.selectedIds);
  if(selectedIds.length === 0){ alert("No items selected"); return; }

  const selectedDetails = selectedIds.map(id => {
    const stored = searchState.selectedDetails.get(id) || searchState.itemsById.get(id) || {};
    const name = stored.name ?? stored.Name ?? "";
    const type = stored.type ?? stored.Type ?? "";
    return { id, name, type };
  });
  const detailLookup = new Map(selectedDetails.map(item => [item.id, item]));

  const body = {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId").value,
    changes: selectedDetails.map(item => ({id: item.id, add: adds, remove: rems}))
  };
  const applyButton = document.getElementById("btnApply");
  applyButton.disabled = true;
  setHtml("applyStatus", "Applying...");
  try{
    const data = await api("/api/apply", body);
    const updates = data.updated || [];
    const successes = updates.filter(u => !(u.errors || []).length).length;
    const failures = updates.length - successes;
    const summaryParts = [];
    if(successes){ summaryParts.push(`${successes} successful`); }
    if(failures){ summaryParts.push(`${failures} failed`); }
    const summaryText = summaryParts.length ? summaryParts.join(", ") : "No changes applied";
    const detailItems = updates.map(update => {
      const errors = update.errors || [];
      const added = update.added || [];
      const removed = update.removed || [];
      const meta = detailLookup.get(update.id) || {name: "", type: ""};
      const hasName = meta.name && meta.name !== update.id;
      const itemLabel = hasName
        ? `${escapeHtml(meta.name)} (${escapeHtml(update.id)})`
        : escapeHtml(update.id);
      const changeDescriptions = [];
      if(added.length){ changeDescriptions.push(`added: ${escapeHtml(added.join(", "))}`); }
      if(removed.length){ changeDescriptions.push(`removed: ${escapeHtml(removed.join(", "))}`); }
      const changeDetail = changeDescriptions.length ? `<div>${changeDescriptions.join("; ")}</div>` : "";
      const errorDetail = errors.length ? `<ul>${errors.map(err => `<li>${escapeHtml(err)}</li>`).join("")}</ul>` : "";
      const typeLabel = meta.type ? ` <span class="apply-type">[${escapeHtml(meta.type)}]</span>` : "";
      const statusIcon = errors.length ? "❌" : "✅";
      return [
        `<li class="${errors.length ? "apply-error" : "apply-success"}">`,
        `${statusIcon} <strong>${itemLabel}</strong>${typeLabel}`,
        changeDetail,
        errorDetail,
        "</li>",
      ].join("");
    }).join("");
    const detailsHtml = detailItems ? `<ul class="apply-results">${detailItems}</ul>` : "";
    setHtml("applyStatus", `<div>${escapeHtml(summaryText)}</div>${detailsHtml}`);
    await search({startIndex: 0, reset: true});
  }catch(e){
    setHtml("applyStatus", "Error: " + escapeHtml(e.message));
  }finally{
    applyButton.disabled = false;
  }
});
