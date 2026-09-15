(function () {
  "use strict";

  const API = "/api/infrastructure";
  let role = "";
  let regions = [];

  function byId(id) {
    return document.getElementById(id);
  }

  function optionalValue(id) {
    const value = String(byId(id)?.value || "").trim();
    return value || null;
  }

  function numberValue(id) {
    const value = optionalValue(id);
    return value === null ? null : Number(value);
  }

  async function request(path, body) {
    const response = await fetch(`${API}${path}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Capivara-Auth-Area": "controller",
      },
      credentials: "same-origin",
      cache: "no-store",
      body: JSON.stringify(body),
    });
    if (response.status === 401) {
      window.location.replace("/login.html");
      throw new Error("Sessão encerrada.");
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
    return payload;
  }

  function showAdminControls() {
    document.querySelectorAll("[data-location-admin]").forEach(node => {
      node.hidden = role !== "admin";
    });
  }

  function resetRegionForm(item = null) {
    const form = byId("infra-region-form");
    if (!form) return;
    form.reset();
    const editing = Boolean(item);
    byId("infra-region-id").disabled = editing;
    byId("infra-region-id").value = item?.id || "";
    byId("infra-region-name").value = item?.name || "";
    byId("infra-region-country-code").value = item?.country_code || "";
    byId("infra-region-continent-code").value = item?.continent_code || "";
    byId("infra-region-latitude").value = item?.latitude ?? "";
    byId("infra-region-longitude").value = item?.longitude ?? "";
    byId("infra-region-status").value = item?.status || "active";
    const title = byId("infra-region-editor-title");
    if (title) title.textContent = editing ? `Editar Region: ${item.name || item.id}` : "Nova Region";
    const feedback = byId("infra-region-feedback");
    if (feedback) feedback.textContent = "";
  }

  function rebuildRegionOptions(selected = "") {
    const select = byId("infra-datacenter-region-id");
    if (!select) return;
    select.replaceChildren(new Option("Selecione uma Region", ""));
    regions.forEach(region => {
      select.appendChild(new Option(`${region.name || region.id} (${region.id})`, String(region.id)));
    });
    if ([...select.options].some(option => option.value === selected)) select.value = selected;
  }

  function resetDatacenterForm(item = null) {
    const form = byId("infra-datacenter-form");
    if (!form) return;
    form.reset();
    const editing = Boolean(item);
    byId("infra-datacenter-id").disabled = editing;
    byId("infra-datacenter-id").value = item?.id || "";
    rebuildRegionOptions(String(item?.region_id || ""));
    byId("infra-datacenter-name").value = item?.name || "";
    byId("infra-datacenter-provider").value = item?.provider || "";
    byId("infra-datacenter-country-code").value = item?.country_code || "";
    byId("infra-datacenter-country-name").value = item?.country_name || "";
    byId("infra-datacenter-state-code").value = item?.state_code || "";
    byId("infra-datacenter-state-name").value = item?.state_name || "";
    byId("infra-datacenter-city").value = item?.city || "";
    byId("infra-datacenter-latitude").value = item?.latitude ?? "";
    byId("infra-datacenter-longitude").value = item?.longitude ?? "";
    byId("infra-datacenter-status").value = item?.status || "active";
    const title = byId("infra-datacenter-editor-title");
    if (title) title.textContent = editing ? `Editar Datacenter: ${item.name || item.id}` : "Novo Datacenter";
    const feedback = byId("infra-datacenter-feedback");
    if (feedback) feedback.textContent = "";
  }

  function openEditor(id) {
    const editor = byId(id);
    if (!editor || role !== "admin") return;
    editor.hidden = false;
    editor.scrollIntoView?.({behavior: "smooth", block: "start"});
  }

  function editButton(label, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "cap-btn cap-btn-secondary cap-infra-edit";
    button.textContent = label;
    button.addEventListener("click", handler);
    return button;
  }

  async function submitRegion(event) {
    event.preventDefault();
    const id = String(byId("infra-region-id")?.value || "").trim();
    const feedback = byId("infra-region-feedback");
    try {
      if (!id) throw new Error("ID da Region é obrigatório.");
      feedback.textContent = "Salvando…";
      await request("/regions", {
        id,
        name: String(byId("infra-region-name")?.value || "").trim(),
        country_code: optionalValue("infra-region-country-code")?.toUpperCase() || null,
        continent_code: optionalValue("infra-region-continent-code")?.toUpperCase() || null,
        latitude: numberValue("infra-region-latitude"),
        longitude: numberValue("infra-region-longitude"),
        status: byId("infra-region-status")?.value || "active",
      });
      feedback.textContent = "Region salva.";
      await window.CapivaraInfrastructureReload?.();
    } catch (error) {
      feedback.textContent = error.message;
    }
  }

  async function submitDatacenter(event) {
    event.preventDefault();
    const id = String(byId("infra-datacenter-id")?.value || "").trim();
    const feedback = byId("infra-datacenter-feedback");
    try {
      if (!id) throw new Error("ID do Datacenter é obrigatório.");
      feedback.textContent = "Salvando…";
      await request("/datacenters", {
        id,
        region_id: String(byId("infra-datacenter-region-id")?.value || "").trim(),
        name: String(byId("infra-datacenter-name")?.value || "").trim(),
        provider: optionalValue("infra-datacenter-provider"),
        country_code: optionalValue("infra-datacenter-country-code")?.toUpperCase() || null,
        country_name: optionalValue("infra-datacenter-country-name"),
        state_code: optionalValue("infra-datacenter-state-code")?.toUpperCase() || null,
        state_name: optionalValue("infra-datacenter-state-name"),
        city: optionalValue("infra-datacenter-city"),
        latitude: numberValue("infra-datacenter-latitude"),
        longitude: numberValue("infra-datacenter-longitude"),
        status: byId("infra-datacenter-status")?.value || "active",
      });
      feedback.textContent = "Datacenter salvo.";
      await window.CapivaraInfrastructureReload?.();
    } catch (error) {
      feedback.textContent = error.message;
    }
  }

  function bindForms() {
    byId("infra-region-new")?.addEventListener("click", () => {
      resetRegionForm();
      openEditor("infra-region-editor");
    });
    byId("infra-datacenter-new")?.addEventListener("click", () => {
      resetDatacenterForm();
      openEditor("infra-datacenter-editor");
    });
    byId("infra-region-form")?.addEventListener("submit", submitRegion);
    byId("infra-datacenter-form")?.addEventListener("submit", submitDatacenter);
    byId("infra-region-cancel")?.addEventListener("click", () => { byId("infra-region-editor").hidden = true; });
    byId("infra-datacenter-cancel")?.addEventListener("click", () => { byId("infra-datacenter-editor").hidden = true; });
  }

  window.CapivaraLocationAdmin = Object.freeze({
    setUser(user) {
      role = String(user?.role || "").toLowerCase();
      showAdminControls();
    },
    setTopology(nextRegions) {
      regions = Array.isArray(nextRegions) ? nextRegions.slice() : [];
      rebuildRegionOptions(byId("infra-datacenter-region-id")?.value || "");
    },
    decorateRegionCard(node, item) {
      if (role !== "admin") return;
      node.appendChild(editButton("Editar", () => {
        resetRegionForm(item);
        openEditor("infra-region-editor");
      }));
    },
    decorateDatacenterCard(node, item) {
      if (role !== "admin") return;
      node.appendChild(editButton("Editar", () => {
        resetDatacenterForm(item);
        openEditor("infra-datacenter-editor");
      }));
    },
  });

  document.addEventListener("DOMContentLoaded", bindForms);
})();
