(function () {
  "use strict";

  const $ = id => document.getElementById(id);

  async function request(path) {
    const response = await fetch(path, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    });

    if (response.status === 401) {
      location.replace("/customer-login.html");
      throw new Error("Sessão encerrada.");
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.message || data.error || `HTTP ${response.status}`);
    }
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

  async function load() {
    try {
      const session = await request("/api/customer/auth/session");
      if (session.authenticated !== true || session.role !== "customer") {
        location.replace("/customer-login.html");
        return;
      }

      const data = await request("/api/customer/profile");
      const profile = data.profile || {};
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

      const access = $("customer-account-access");
      access.replaceChildren(
        row("E-mail da conta", profile.account_email),
        row("E-mail verificado", profile.email_verified_at ? "Sim" : "Não")
      );

      const actions = document.createElement("div");
      actions.className = "integration-actions";
      const edit = document.createElement("a");
      edit.className = "button";
      edit.href = "/customer.html#profile";
      edit.textContent = data.editable ? "Editar dados cadastrais" : "Ver perfil";
      actions.append(edit);
      access.append(actions);
    } catch (error) {
      $("customer-account-details").innerHTML = `<div class="integration-notice">${error.message}</div>`;
    }
  }

  load();
})();
