import { api } from "./api.js";
import { validateServerConfig } from "./storage.js";
import { escapeHtml, normalizeTagList, setHtml, splitTags, val } from "./utils.js";

const btnTags = document.getElementById("btnTags");
const tagListEl = document.getElementById("tagList");
const tagSearchInput = document.getElementById("tagSearch");
const tagActionSummaryEl = document.getElementById("tagActionSummary");
const chipFields = {
  add: {
    input: document.getElementById("applyAdd"),
    list: document.getElementById("applyAddChips"),
  },
  remove: {
    input: document.getElementById("applyRemove"),
    list: document.getElementById("applyRemoveChips"),
  },
};

const tagStates = new Map();
let allTags = [];
let pendingRetryTimer = null;

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

function getTagActionCounts() {
  let add = 0;
  let remove = 0;
  tagStates.forEach((state) => {
    if (state === "add") {
      add += 1;
    }
    if (state === "remove") {
      remove += 1;
    }
  });
  return { add, remove };
}

export function updateTagActionSummary() {
  if (!tagActionSummaryEl) {
    return;
  }
  const { add, remove } = getTagActionCounts();
  if (add === 0 && remove === 0) {
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

function findTagButtonByTag(tag) {
  if (!tagListEl) {
    return null;
  }
  const buttons = tagListEl.querySelectorAll(".tag");
  for (const button of buttons) {
    if ((button.dataset.tag || "") === tag) {
      return button;
    }
  }
  return null;
}

function currentTagSearchQuery() {
  return tagSearchInput ? tagSearchInput.value : "";
}

export function filterTagsByQuery(tags, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) {
    return [...tags];
  }
  return tags.filter((tag) => tag.toLowerCase().includes(q));
}

export function renderTagButtons(tags) {
  if (!tagListEl) {
    return;
  }
  if (!tags.length) {
    const hasQuery = currentTagSearchQuery().trim().length > 0;
    setHtml("tagList", hasQuery ? '<div class="tag-empty">No tags match your search.</div>' : "");
    updateTagActionSummary();
    return;
  }
  const html = tags
    .map((tag) => {
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
    })
    .join(" ");
  tagListEl.innerHTML = html;
  tagListEl.querySelectorAll(".tag").forEach((button) => {
    applyTagState(button, button.dataset.state || "");
  });
  updateTagActionSummary();
}

export function setTagState(tag, state) {
  if (!tag) {
    return;
  }
  if (state) {
    tagStates.set(tag, state);
  } else {
    tagStates.delete(tag);
  }
  const button = findTagButtonByTag(tag);
  if (button) {
    applyTagState(button, state || "");
  }
  updateTagActionSummary();
}

function resetStatesForUnavailableTags(available) {
  let removed = false;
  Array.from(tagStates.keys()).forEach((tag) => {
    if (!available.has(tag)) {
      tagStates.delete(tag);
      removed = true;
    }
  });
  if (removed) {
    updateTagActionSummary();
  }
}

function renderChipField(type, tags) {
  const field = chipFields[type];
  if (!field || !field.list) {
    return;
  }
  const listEl = field.list;
  listEl.innerHTML = "";
  const normalized = normalizeTagList(tags);
  if (!normalized.length) {
    const empty = document.createElement("div");
    empty.className = "chip-empty";
    empty.textContent = "No tags selected";
    empty.setAttribute("aria-hidden", "true");
    listEl.appendChild(empty);
    return;
  }
  const fragment = document.createDocumentFragment();
  normalized.forEach((tag) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.dataset.tag = tag;
    chip.dataset.type = type;
    chip.setAttribute("role", "listitem");

    const label = document.createElement("span");
    label.className = "chip-label";
    label.textContent = tag;

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "chip-remove";
    removeButton.dataset.tag = tag;
    removeButton.dataset.type = type;
    removeButton.setAttribute("aria-label", `Remove ${tag}`);
    removeButton.innerHTML = "<span aria-hidden=\"true\">×</span>";

    chip.appendChild(label);
    chip.appendChild(removeButton);
    fragment.appendChild(chip);
  });
  listEl.appendChild(fragment);
}

function updateChipField(type, tags) {
  const field = chipFields[type];
  if (!field || !field.input) {
    return;
  }
  const normalized = normalizeTagList(tags);
  field.input.value = normalized.join("; ");
  renderChipField(type, normalized);
}

export function setTagInputs(addTags, removeTags) {
  updateChipField("add", addTags);
  updateChipField("remove", removeTags);
}

export function getChipTags(type) {
  const field = chipFields[type];
  if (!field || !field.input) {
    return [];
  }
  return normalizeTagList(splitTags(field.input.value));
}

function clearTagPendingNotice() {
  if (!tagListEl) {
    return;
  }
  const notice = tagListEl.querySelector(".tag-pending-notice");
  if (notice) {
    notice.remove();
  }
  const button = tagListEl.querySelector(".tag-pending-retry");
  if (button) {
    button.remove();
  }
  if (pendingRetryTimer) {
    clearTimeout(pendingRetryTimer);
    pendingRetryTimer = null;
  }
}

function showTagPendingNotice(message) {
  if (!tagListEl) {
    return;
  }
  setHtml("tagList", "");
  const notice = document.createElement("div");
  notice.className = "tag-pending-notice";
  notice.textContent = message || "Gathering tags, please try again shortly.";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "tag-pending-retry";
  button.textContent = "Retry now";
  button.addEventListener("click", () => {
    button.disabled = true;
    button.textContent = "Retrying…";
    setTimeout(() => {
      button.disabled = false;
      button.textContent = "Retry now";
      loadTags();
    }, 3000);
  });
  tagListEl.appendChild(notice);
  tagListEl.appendChild(button);
  if (!pendingRetryTimer) {
    pendingRetryTimer = setTimeout(() => {
      pendingRetryTimer = null;
      loadTags();
    }, 4000);
  }
}

async function loadTags() {
  const validationMessage = validateServerConfig();
  if (validationMessage) {
    setHtml("tagList", escapeHtml(validationMessage));
    return;
  }
  const body = {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId")?.value,
    libraryId: document.getElementById("libraryId")?.value,
    types: splitTags(val("types")),
  };
  setHtml("tagList", "Loading tags...");
  try {
    const data = await api("/api/tags", body);
    if (data.status === "pending") {
      showTagPendingNotice(data.message);
      return;
    }
    allTags = Array.isArray(data.tags) ? data.tags : [];
    if (!allTags.length) {
      setHtml("tagList", "No tags found.");
      return;
    }
    clearTagPendingNotice();
    const available = new Set(allTags);
    resetStatesForUnavailableTags(available);
    const existingNotice = tagListEl?.querySelector(".tag-refresh-notice");
    if (existingNotice) {
      existingNotice.remove();
    }
    renderTagButtons(filterTagsByQuery(allTags, currentTagSearchQuery()));
    if (data.loading && tagListEl) {
      const refreshNotice = document.createElement("div");
      refreshNotice.className = "tag-refresh-notice";
      refreshNotice.textContent = "Tags are being refreshed in the background.";
      tagListEl.prepend(refreshNotice);
    }
  } catch (error) {
    allTags = [];
    tagStates.clear();
    setHtml("tagList", `Error loading tags: ${error.message}`);
    updateTagActionSummary();
  }
}

function handleTagListClick(event) {
  const target = event.target.closest(".tag");
  if (!target || !target.dataset.tag) {
    return;
  }
  const tag = target.dataset.tag;
  const addTags = getChipTags("add");
  const removeTags = getChipTags("remove");
  const currentState = target.dataset.state || "";
  const nextState = currentState === "add" ? "remove" : currentState === "remove" ? "" : "add";
  if (currentState === "add") {
    const index = addTags.indexOf(tag);
    if (index !== -1) {
      addTags.splice(index, 1);
    }
  }
  if (currentState === "remove") {
    const index = removeTags.indexOf(tag);
    if (index !== -1) {
      removeTags.splice(index, 1);
    }
  }
  if (nextState === "add") {
    if (!addTags.includes(tag)) {
      addTags.push(tag);
    }
    const removeIndex = removeTags.indexOf(tag);
    if (removeIndex !== -1) {
      removeTags.splice(removeIndex, 1);
    }
  } else if (nextState === "remove") {
    if (!removeTags.includes(tag)) {
      removeTags.push(tag);
    }
    const addIndex = addTags.indexOf(tag);
    if (addIndex !== -1) {
      addTags.splice(addIndex, 1);
    }
  }
  setTagState(tag, nextState);
  setTagInputs(addTags, removeTags);
}

function handleTagSearchInput() {
  if (!allTags.length) {
    return;
  }
  renderTagButtons(filterTagsByQuery(allTags, tagSearchInput.value));
}

export function initializeTagPanel() {
  updateTagActionSummary();
  if (btnTags) {
    btnTags.addEventListener("click", loadTags);
  }
  if (tagListEl) {
    tagListEl.addEventListener("click", handleTagListClick);
  }
  if (tagSearchInput) {
    tagSearchInput.addEventListener("input", handleTagSearchInput);
  }
  Object.entries(chipFields).forEach(([type, field]) => {
    if (!field || !field.list) {
      return;
    }
    field.list.addEventListener("click", (event) => {
      const removeButton = event.target.closest(".chip-remove");
      if (!removeButton) {
        return;
      }
      const tag = removeButton.dataset.tag;
      if (!tag) {
        return;
      }
      const current = {
        add: getChipTags("add"),
        remove: getChipTags("remove"),
      };
      current[type] = current[type].filter((existing) => existing !== tag);
      setTagInputs(current.add, current.remove);
      const currentState = tagStates.get(tag) || "";
      if (currentState === type) {
        setTagState(tag, "");
      }
    });
  });
  setTagInputs(getChipTags("add"), getChipTags("remove"));
}
