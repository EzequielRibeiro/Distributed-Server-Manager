(function () {
  "use strict";

  const $ = id => document.getElementById(id);
  const headers = json => ({Accept:"application/json","X-Capivara-Auth-Area":"customer",...(json?{"Content-Type":"application/json"}:{})});
  let profile = {};
  let editable = false;

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {...headers(Boolean(options.body)), ...(options.headers || {})},
      credentials: "same-origin",
      cache: "no-store",
    });
    if (response.status === 401) {
      location.replace("/customer-login.html");
      throw new Error("Sessão encerrada.");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    return data;
  }

  function row(label, value) {
    const node = document.createElement("div");
    node.className = "integration-row";
    const key = document.createElement("span");
    key.className = "integration-muted";
    key.textContent = label;
    const data = document.createElement("strong");
    data.textContent = value || "—";
    node.append(key, data);
    return node;
  }

  function makeButton(label, onClick, secondary = false) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = secondary ? "button customer-account-secondary" : "button";
    node.textContent = label;
    node.addEventListener("click", onClick);
    return node;
  }

  function renderSummary() {
    const details = $("customer-account-details");
    details.replaceChildren(
      row("ID público", profile.customer_code),
      row("Nome", profile.name),
      row("Razão social", profile.legal_name),
      row("Documento", [profile.document_type, profile.document_number].filter(Boolean).join(" ")),
      row("Telefone", profile.phone),
      row("Status do cadastro", profile.registration_status),
      row("Função na conta", profile.account_role)
    );
    if (editable) {
      const actions = document.createElement("div");
      actions.className = "integration-actions customer-account-actions";
      actions.append(makeButton("Editar dados cadastrais", renderEditor));
      details.append(actions);
    }
  }

  function field(label, key, options) {
    const wrapper = document.createElement("label");
    wrapper.textContent = label;
    let control;
    if (options) {
      control = document.createElement("select");
      options.forEach(([value, text]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        control.append(option);
      });
    } else {
      control = document.createElement("input");
    }
    control.dataset.field = key;
    control.value = String(profile[key] || "");
    wrapper.append(control);
    return wrapper;
  }

  function renderEditor() {
    const details = $("customer-account-details");
    const form = document.createElement("form");
    form.className = "integration-form customer-account-form";
    const grid = document.createElement("div");
    grid.className = "customer-account-form-grid";
    grid.append(
      field("Nome", "name"),
      field("Razão social / nome legal", "legal_name"),
      field("Telefone", "phone"),
      field("Tipo de documento", "document_type", [["","Não informado"],["cpf","CPF"],["cnpj","CNPJ"],["other","Outro"]]),
      field("Documento", "document_number")
    );
    const note = document.createElement("p");
    note.className = "integration-muted customer-account-note";
    note.textContent = "E-mail, código do cliente, status e função permanecem somente leitura.";
    const actions = document.createElement("div");
    actions.className = "integration-actions customer-account-actions";
    const cancel = makeButton("Cancelar", renderSummary, true);
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "button";
    save.textContent = "Salvar alterações";
    actions.append(cancel, save);
    form.append(grid, note, actions);
    form.addEventListener("submit", saveProfile);
    details.replaceChildren(form);
  }

  async function saveProfile(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const changes = {};
    form.querySelectorAll("[data-field]").forEach(control => { changes[control.dataset.field] = control.value; });
    try {
      const data = await request("/api/customer/profile", {method:"POST", body:JSON.stringify({changes})});
      profile = data.profile || profile;
      renderSummary();
      const message = $("customer-message");
      if (message) {
        message.textContent = data.updated ? "Dados cadastrais atualizados." : "Nenhuma alteração necessária.";
        message.classList.add("show");
        setTimeout(() => message.classList.remove("show"), 4000);
      }
    } catch (error) {
      form.querySelector(".integration-notice")?.remove();
      const notice = document.createElement("div");
      notice.className = "integration-notice";
      notice.textContent = error.message;
      form.prepend(notice);
    }
  }

  function renderAccess() {
    $("customer-account-access").replaceChildren(
      row("E-mail da conta", profile.account_email),
      row("E-mail verificado", profile.email_verified_at ? "Sim" : "Não")
    );
  }

  async function load() {
    try {
      const session = await request("/api/customer/auth/session");
      if (session.authenticated !== true || session.role !== "customer") {
        location.replace("/customer-login.html");
        return;
      }
      const data = await request("/api/customer/profile");
      profile = data.profile || {};
      editable = data.editable === true;
      renderSummary();
      renderAccess();
    } catch (error) {
      const details = $("customer-account-details");
      details.replaceChildren();
      const notice = document.createElement("div");
      notice.className = "integration-notice";
      notice.textContent = error.message;
      details.append(notice);
    }
  }

  load();
})();
