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
function checkbox(id){ return `<input type="checkbox" class="sel" data-id="${id}">`; }

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
    setHtml(
      "tagList",
      data.tags
        .map(
          (t) =>
            `<button type="button" class="tag" data-tag="${t}"><span>${t}</span></button>`
        )
        .join(" ")
    );
  } catch (e) {
    setHtml("tagList", `Error loading tags: ${e.message}`);
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

  target.dataset.state = nextState;
  target.classList.remove("tag-add", "tag-remove");
  if (nextState === "add") {
    target.classList.add("tag-add");
  } else if (nextState === "remove") {
    target.classList.add("tag-remove");
  }

  setTagInputs(addTags, removeTags);
});

async function search(pageStart=0){
  const types = splitTags(val("types"));
  const body = {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId").value,
    libraryId: document.getElementById("libraryId").value,
    types: types,
    includeTags: val("includeTags"),
    excludeTags: val("excludeTags"),
    excludeCollections: document.getElementById("excludeCollections").checked,
    startIndex: pageStart,
    limit: 500
  };
  const data = await api("/api/items", body);
  const returned = data.Items.length;
  const total = data.TotalRecordCount ?? returned;
  setHtml("resultSummary", `Showing ${returned} of ${total} items`);

  const rows = data.Items.map(it => `
    <tr>
      <td>${checkbox(it.Id)}</td>
      <td>${it.Type}</td>
      <td>${it.Name}</td>
      <td>${(it.Path||"")}</td>
      <td>${(it.Tags||[]).join("; ")}</td>
    </tr>
  `).join("");
  const table = `
    <table>
      <thead><tr><th><input type="checkbox" id="selAll"></th><th>Type</th><th>Name</th><th>Path</th><th>Tags</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  setHtml("results", table);

  const updateSelectionSummary = ()=>{
    const selected = document.querySelectorAll("input.sel:checked").length;
    const label = selected === 0 ? "No items selected" : `${selected} item${selected === 1 ? "" : "s"} selected`;
    setHtml("selectionSummary", label);
  };

  const selAll = document.getElementById("selAll");
  const rowCheckboxes = Array.from(document.querySelectorAll("input.sel"));

  selAll.addEventListener("change", ()=>{
    rowCheckboxes.forEach(cb => cb.checked = selAll.checked);
    updateSelectionSummary();
  });

  rowCheckboxes.forEach(cb => cb.addEventListener("change", ()=>{
    if(!cb.checked){
      selAll.checked = false;
    } else if(rowCheckboxes.every(c => c.checked)){
      selAll.checked = true;
    }
    updateSelectionSummary();
  }));

  updateSelectionSummary();
}

document.getElementById("btnSearch").addEventListener("click", ()=>search(0));

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
  const selected = Array.from(document.querySelectorAll("input.sel:checked")).map(cb => cb.dataset.id);
  if(selected.length === 0){ alert("No items selected"); return; }
  const body = {
    base: val("base"),
    apiKey: val("apiKey"),
    userId: document.getElementById("userId").value,
    changes: selected.map(id => ({id: id, add: adds, remove: rems}))
  };
  setHtml("applyStatus", "Applying...");
  try{
    const data = await api("/api/apply", body);
    const errs = data.updated.flatMap(u => u.errors || []);
    setHtml("applyStatus", errs.length ? ("Done with errors: " + errs.length) : "Done");
    await search(0);
  }catch(e){
    setHtml("applyStatus", "Error: " + e.message);
  }
});
