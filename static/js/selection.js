import { api } from "./api.js";
import { validateServerConfig } from "./storage.js";
import { searchState } from "./state.js";
import { escapeHtml, normalizeTagList, splitTags, val } from "./utils.js";

const resultsContainer = document.getElementById("results");
const inlineTagEditorTemplate = document.getElementById("inlineTagEditorTemplate");
const selectedItemsListEl = document.getElementById("selectedItemsList");
const selectedItemsPanelEl = document.getElementById("selectedItemsPanel");
const clearSelectionButton = document.getElementById("btnClearSelection");
const selectionSummaryEl = document.getElementById("selectionSummary");

let inlineEditorState = null;

function createInlineTagEditorForm() {
  if (inlineTagEditorTemplate && inlineTagEditorTemplate.content) {
    const clone = inlineTagEditorTemplate.content.firstElementChild?.cloneNode(true);
    if (clone) {
      return clone;
    }
  }
  const form = document.createElement("form");
  form.className = "inline-tag-editor-form";
  const field = document.createElement("div");
  field.className = "inline-tag-editor-field";
  const label = document.createElement("label");
  label.className = "inline-tag-editor-label sr-only";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "inline-tag-input";
  const hint = document.createElement("div");
  hint.className = "inline-tag-help";
  hint.textContent = "Separate tags with commas or semicolons.";
  field.append(label, input, hint);
  form.appendChild(field);
  const actions = document.createElement("div");
  actions.className = "inline-tag-editor-actions";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.className = "inline-tag-save";
  saveButton.textContent = "Save";
  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.className = "inline-tag-cancel";
  cancelButton.textContent = "Cancel";
  actions.append(saveButton, cancelButton);
  form.appendChild(actions);
  const status = document.createElement("div");
  status.className = "inline-tag-editor-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  form.appendChild(status);
  return form;
}

export function updateInlineTagSummary(container, tags) {
  if (!container) {
    return;
  }
  const summary = container.querySelector(".inline-tag-summary-text");
  if (!summary) {
    return;
  }
  const normalized = normalizeTagList(tags);
  if (normalized.length) {
    summary.textContent = normalized.join("; ");
    summary.classList.remove("inline-tag-empty");
  } else {
    summary.textContent = "No tags";
    summary.classList.add("inline-tag-empty");
  }
}

export function closeInlineTagEditor(options = {}) {
  if (!inlineEditorState) {
    return;
  }
  const { container, form, trigger } = inlineEditorState;
  const shouldFocus = !!options.focusTrigger;
  if (container) {
    container.classList.remove("is-editing");
  }
  if (form && container && container.contains(form)) {
    container.removeChild(form);
  }
  if (trigger) {
    trigger.setAttribute("aria-expanded", "false");
    trigger.removeAttribute("aria-controls");
    if (shouldFocus && typeof trigger.focus === "function") {
      trigger.focus();
    }
  }
  inlineEditorState = null;
}

function getRowForItemId(id) {
  if (!id) {
    return null;
  }
  const rows = Array.from(document.querySelectorAll("#results tbody tr"));
  return rows.find((row) => row.dataset.id === id) || null;
}

function openInlineTagEditor(trigger) {
  if (!trigger) {
    return;
  }
  const id = trigger.dataset.id;
  if (!id) {
    return;
  }
  const row = trigger.closest("tr");
  if (!row) {
    return;
  }
  if (inlineEditorState && inlineEditorState.activeId === id) {
    closeInlineTagEditor({ focusTrigger: true });
    return;
  }
  if (inlineEditorState) {
    closeInlineTagEditor({ focusTrigger: false });
  }
  const container = trigger.closest(".inline-tag-control");
  if (!container) {
    return;
  }
  const storedItem = searchState.itemsById.get(id);
  let item = storedItem;
  if (!item) {
    const raw = row.dataset.item;
    if (raw) {
      try {
        item = JSON.parse(raw);
      } catch (error) {
        item = null;
      }
    }
  }
  if (!item) {
    return;
  }
  const originalTags = normalizeTagList(item.Tags || []);
  const form = createInlineTagEditorForm();
  if (!form) {
    return;
  }
  const uniqueSuffix = Math.random().toString(36).slice(2);
  const formId = `inlineTagEditor-${uniqueSuffix}`;
  form.id = formId;
  form.dataset.id = id;
  const input = form.querySelector(".inline-tag-input");
  const label = form.querySelector(".inline-tag-editor-label");
  const hint = form.querySelector(".inline-tag-help");
  const status = form.querySelector(".inline-tag-editor-status");
  const actions = form.querySelector(".inline-tag-editor-actions");
  if (label) {
    label.classList.add("sr-only");
    const labelId = `inlineTagLabel-${uniqueSuffix}`;
    label.id = labelId;
    label.textContent = `Tags for ${item.Name || item.Id}`;
    form.setAttribute("aria-labelledby", labelId);
  }
  if (input) {
    const inputId = `inlineTagInput-${uniqueSuffix}`;
    input.id = inputId;
    input.value = originalTags.join("; ");
    input.setAttribute("aria-describedby", `inlineTagHelp-${uniqueSuffix}`);
    input.setAttribute("autocomplete", "off");
    input.setAttribute("placeholder", "Tag1; Tag2");
  }
  if (hint) {
    hint.id = `inlineTagHelp-${uniqueSuffix}`;
  }
  if (actions) {
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", "Inline tag editor actions");
  }
  if (status) {
    status.textContent = "";
  }
  trigger.setAttribute("aria-expanded", "true");
  trigger.setAttribute("aria-controls", formId);
  container.classList.add("is-editing");
  container.appendChild(form);
  inlineEditorState = {
    activeId: id,
    container,
    form,
    input,
    status,
    trigger,
    originalTags,
    item,
  };
  if (input) {
    window.requestAnimationFrame(() => {
      input.focus();
      input.select();
    });
  }
}

async function submitInlineTagEdit(form) {
  if (!inlineEditorState || inlineEditorState.form !== form) {
    return;
  }
  const validationMessage = validateServerConfig();
  if (validationMessage) {
    if (inlineEditorState.status) {
      inlineEditorState.status.textContent = validationMessage;
    }
    return;
  }
  const { input, originalTags, status, activeId, item, container } = inlineEditorState;
  if (!input) {
    return;
  }
  const updatedTags = normalizeTagList(splitTags(input.value));
  const originalSet = new Set(originalTags);
  const updatedSet = new Set(updatedTags);
  const add = updatedTags.filter((tag) => !originalSet.has(tag));
  const remove = originalTags.filter((tag) => !updatedSet.has(tag));
  if (add.length === 0 && remove.length === 0) {
    updateInlineTagSummary(container, updatedTags);
    item.Tags = updatedTags;
    searchState.itemsById.set(activeId, item);
    if (searchState.selectedDetails.has(activeId)) {
      const detail = searchState.selectedDetails.get(activeId);
      if (detail) {
        detail.tags = updatedTags.slice();
      }
    }
    const row = getRowForItemId(activeId);
    if (row) {
      row.dataset.item = JSON.stringify(item);
    }
    closeInlineTagEditor({ focusTrigger: true });
    return;
  }
  const base = val("base");
  const apiKey = val("apiKey");
  const userSelect = document.getElementById("userId");
  const userIdValue = userSelect ? userSelect.value : "";
  const body = {
    base,
    apiKey,
    userId: userIdValue,
    changes: [{ id: activeId, add, remove }],
  };
  if (status) {
    status.textContent = "Saving tags...";
  }
  form.setAttribute("aria-busy", "true");
  const saveButton = form.querySelector(".inline-tag-save");
  const cancelButton = form.querySelector(".inline-tag-cancel");
  if (saveButton) {
    saveButton.disabled = true;
  }
  if (cancelButton) {
    cancelButton.disabled = true;
  }
  try {
    await api("/api/apply", body);
    item.Tags = updatedTags;
    searchState.itemsById.set(activeId, item);
    if (searchState.selectedDetails.has(activeId)) {
      const detail = searchState.selectedDetails.get(activeId);
      if (detail) {
        detail.tags = updatedTags.slice();
      }
    }
    const row = getRowForItemId(activeId);
    if (row) {
      row.dataset.item = JSON.stringify(item);
    }
    updateInlineTagSummary(container, updatedTags);
    if (status) {
      status.textContent = "Tags updated.";
    }
    closeInlineTagEditor({ focusTrigger: true });
  } catch (error) {
    if (status) {
      status.textContent = `Error updating tags: ${error.message}`;
    }
  } finally {
    form.removeAttribute("aria-busy");
    if (saveButton) {
      saveButton.disabled = false;
    }
    if (cancelButton) {
      cancelButton.disabled = false;
    }
  }
}

function getResultRowCheckboxes() {
  return Array.from(document.querySelectorAll("input.sel"));
}

function getSortedSelectedItems() {
  return Array.from(searchState.selectedDetails.values()).sort((a, b) => {
    const nameA = (a.name || "").toLocaleLowerCase();
    const nameB = (b.name || "").toLocaleLowerCase();
    if (nameA === nameB) {
      return (a.id || "").localeCompare(b.id || "");
    }
    return nameA.localeCompare(nameB);
  });
}

function renderSelectedItemsList() {
  if (!selectedItemsListEl) {
    return;
  }
  const selectedItems = getSortedSelectedItems();
  if (selectedItems.length === 0) {
    selectedItemsListEl.innerHTML = '<li class="selected-items-empty">No items selected.</li>';
    return;
  }
  const html = selectedItems
    .map((item) => {
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
    })
    .join("");
  selectedItemsListEl.innerHTML = html;
}

export function updateSelectionSummary() {
  const selected = searchState.selectedIds.size;
  const label =
    selected === 0 ? "No items selected" : `${selected} item${selected === 1 ? "" : "s"} selected`;
  if (selectionSummaryEl) {
    selectionSummaryEl.textContent = label;
  }
  if (clearSelectionButton) {
    clearSelectionButton.disabled = selected === 0;
  }
  renderSelectedItemsList();
}

export function updateSelectAllState(selAll, rowCheckboxes) {
  if (!selAll) {
    return;
  }
  const total = rowCheckboxes.length;
  const checkedCount = rowCheckboxes.filter((cb) => cb.checked).length;
  if (total === 0) {
    selAll.checked = false;
    selAll.indeterminate = false;
    selAll.disabled = true;
    return;
  }
  selAll.disabled = false;
  if (checkedCount === 0) {
    selAll.checked = false;
    selAll.indeterminate = false;
  } else if (checkedCount === total) {
    selAll.checked = true;
    selAll.indeterminate = false;
  } else {
    selAll.checked = false;
    selAll.indeterminate = true;
  }
}

export function applySelectionFromCheckbox(cb) {
  if (!cb) {
    return;
  }
  const id = cb.dataset.id;
  if (!id) {
    return;
  }
  const row = cb.closest("tr");
  if (cb.checked) {
    searchState.selectedIds.add(id);
    const item = searchState.itemsById.get(id);
    const tags = item ? normalizeTagList(item.Tags || []) : [];
    searchState.selectedDetails.set(id, {
      id,
      name: cb.dataset.name || "",
      type: cb.dataset.type || "",
      tags,
    });
    if (row) {
      row.classList.add("is-selected");
    }
  } else {
    searchState.selectedIds.delete(id);
    searchState.selectedDetails.delete(id);
    if (row) {
      row.classList.remove("is-selected");
    }
  }
  updateSelectionSummary();
}

function handleSelectedItemRemoval(event) {
  const removeButton = event.target.closest(".selected-item-remove");
  if (!removeButton) {
    return;
  }
  const id = removeButton.dataset.id;
  if (!id) {
    return;
  }
  const checkbox = getResultRowCheckboxes().find((cb) => cb.dataset.id === id);
  if (checkbox) {
    checkbox.checked = false;
    applySelectionFromCheckbox(checkbox);
    const selAll = document.getElementById("selAll");
    if (selAll) {
      updateSelectAllState(selAll, getResultRowCheckboxes());
    }
  } else {
    searchState.selectedIds.delete(id);
    searchState.selectedDetails.delete(id);
    updateSelectionSummary();
  }
}

function handleClearSelection() {
  if (!searchState.selectedIds.size) {
    return;
  }
  searchState.selectedIds.clear();
  searchState.selectedDetails.clear();
  const rowCheckboxes = getResultRowCheckboxes();
  rowCheckboxes.forEach((cb) => {
    cb.checked = false;
    const row = cb.closest("tr");
    if (row) {
      row.classList.remove("is-selected");
    }
  });
  const selAll = document.getElementById("selAll");
  if (selAll) {
    updateSelectAllState(selAll, rowCheckboxes);
  }
  updateSelectionSummary();
}

function handleResultsClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) {
    return;
  }
  const editButton = target.closest(".inline-tag-edit");
  if (editButton) {
    event.preventDefault();
    openInlineTagEditor(editButton);
    return;
  }
  const cancelButton = target.closest(".inline-tag-cancel");
  if (cancelButton && inlineEditorState) {
    event.preventDefault();
    closeInlineTagEditor({ focusTrigger: true });
  }
}

function handleResultsSubmit(event) {
  if (event.target.matches(".inline-tag-editor-form")) {
    event.preventDefault();
    submitInlineTagEdit(event.target);
  }
}

function handleResultsKeydown(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (event.key === "Escape" && target && inlineEditorState && inlineEditorState.form?.contains(target)) {
    event.preventDefault();
    closeInlineTagEditor({ focusTrigger: true });
  }
}

export function initializeSelection() {
  if (selectedItemsListEl) {
    selectedItemsListEl.setAttribute("aria-live", "polite");
  }
  if (resultsContainer) {
    resultsContainer.addEventListener("click", handleResultsClick);
    resultsContainer.addEventListener("submit", handleResultsSubmit);
    resultsContainer.addEventListener("keydown", handleResultsKeydown);
  }
  if (selectedItemsPanelEl) {
    selectedItemsPanelEl.addEventListener("click", handleSelectedItemRemoval);
  }
  if (clearSelectionButton) {
    clearSelectionButton.addEventListener("click", handleClearSelection);
  }
  updateSelectionSummary();
}
