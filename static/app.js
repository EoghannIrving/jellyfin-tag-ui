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
const searchState = {
  startIndex: 0,
  limit: 500,
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

const tagStates = new Map();
let allTags = [];
const tagSearchInput = document.getElementById("tagSearch");
const tagActionSummaryEl = document.getElementById("tagActionSummary");

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
  const types = splitTags(val("types"));
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
  };
}

function buildSearchQueryKey(body){
  return JSON.stringify({
    base: body.base,
    userId: body.userId,
    libraryId: body.libraryId,
    types: body.types,
    includeTags: body.includeTags,
    excludeTags: body.excludeTags,
    excludeCollections: body.excludeCollections,
  });
}

function updateSelectionSummary(){
  const selected = searchState.selectedIds.size;
  const label = selected === 0
    ? "No items selected"
    : `${selected} item${selected === 1 ? "" : "s"} selected`;
  setHtml("selectionSummary", label);
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
    return `
    <tr>
      <td>${checkbox(it)}</td>
      <td>${safeType}</td>
      <td>${safeName}</td>
      <td>${safePath}</td>
      <td>${safeTags}</td>
    </tr>
  `;
  }).join("");
  const table = `
    <table>
      <thead><tr><th><input type="checkbox" id="selAll"></th><th>Type</th><th>Name</th><th>Path</th><th>Tags</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  setHtml("results", table);

  const selAll = document.getElementById("selAll");
  const rowCheckboxes = Array.from(document.querySelectorAll("input.sel"));

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

function updatePaginationControls(returned, total){
  const {prev, next, summary} = paginationControls;
  if(prev){
    const hasPrev = total > 0 && searchState.startIndex > 0;
    prev.disabled = !hasPrev;
  }
  if(next){
    const nextStart = searchState.startIndex + searchState.limit;
    next.disabled = !(total > 0 && nextStart < total);
  }
  if(summary){
    if(total === 0){
      summary.textContent = searchState.queryKey ? "No items found" : "";
    } else {
      const start = Math.min(total, searchState.startIndex + 1);
      let end = returned ? Math.min(total, searchState.startIndex + returned) : Math.min(total, searchState.startIndex + searchState.limit);
      if(end < start){
        end = start;
      }
      summary.textContent = `${start}-${end} of ${total}`;
    }
  }
}

document.getElementById("btnUsers").addEventListener("click", async ()=>{
  const data = await api("/api/users", {base: val("base"), apiKey: val("apiKey")});
  const opts = optionList(data, "Id", "Name");
  setHtml("userId", opts);
});

document.getElementById("btnLibs").addEventListener("click", async ()=>{
  const data = await api("/api/libraries", {base: val("base"), apiKey: val("apiKey")});
  const opts = data.map(x => ({value: x.ItemId, text: `${x.Name} (${x.CollectionType||"?"})`}))
                   .map(o => `<option value="${o.value}">${o.text}</option>`).join("");
  setHtml("libraryId", opts);
});

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
    const items = data.Items || [];
    const returned = items.length;
    const total = data.TotalRecordCount ?? returned;

    searchState.startIndex = targetStart;
    searchState.total = total;
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

    if(total === 0){
      setHtml("resultSummary", "No items found");
    } else {
      const startNumber = Math.min(total, searchState.startIndex + 1);
      let endNumber = returned ? Math.min(total, searchState.startIndex + returned) : Math.min(total, searchState.startIndex + searchState.limit);
      if(endNumber < startNumber){
        endNumber = startNumber;
      }
      const summaryText = `Showing items ${startNumber}–${endNumber} of ${total}`;
      setHtml("resultSummary", summaryText);
    }

    updatePaginationControls(returned, total);
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
