(function () {
  "use strict";

  const API = "/api/customer/profile";
  let profile = null;
  let editable = false;

  function text(value) { return String(value ?? ""); }
  function esc(value) {
    return text(value).replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[ch]);
  }
  function message(value) {
    const node = document.getElementById("customer-message");
    if (!node) return;
    node.textContent = value;
    node.classList.add("show");
    window.clearTimeout(message.timer);
    message.timer = window.setTimeout(() => node.classList.remove("show"), 5000);
  }
  function ensurePanel() {
    let panel = document.getElementById("customer-profile-panel");
    if (panel) return panel;
    panel = document.createElement("section");
    panel.id = "customer-profile-panel";
    panel.className = "customer-section";
    panel.hidden = true;
    panel.innerHTML = `
      <article class="instance-panel">
        <div class="section-heading"><div><p class="customer-label">MINHA CONTA</p><h2>Perfil</h2><p>Dados cadastrais do Customer. Alteração de e-mail possui fluxo seguro separado.</p></div><button id="customer-profile-close" class="button" type="button">Fechar</button></div>
        <form id="customer-profile-form">
          <div class="runtime-selection-summary">
            <label>Nome<input id="customer-profile-name" autocomplete="name"></label>
            <label>Razão social / nome legal<input id="customer-profile-legal-name"></label>
            <label>Telefone<input id="customer-profile-phone" autocomplete="tel"></label>
            <label>Tipo de documento<select id="customer-profile-document-type"><option value="">Não informado</option><option value="cpf">CPF</option><option value="cnpj">CNPJ</option><option value="other">Outro</option></select></label>
            <label>Documento<input id="customer-profile-document-number"></label>
            <div><span>E-mail da conta</span><strong id="customer-profile-email">—</strong><small>Somente leitura. A troca exige confirmação no novo endereço.</small><button class="button" type="button" data-customer-email-change>Alterar e-mail</button></div>
            <div><span>Código do cliente</span><strong id="customer-profile-code">—</strong></div>
          </div>
          <div class="runtime-create-actions"><button id="customer-profile-save" class="button" type="submit">Salvar alterações</button></div>
        </form>
      </article>`;
    document.querySelector(".customer-main")?.appendChild(panel);
    panel.querySelector("#customer-profile-close")?.addEventListener("click", () => panel.hidden = true);
    panel.querySelector("#customer-profile-form")?.addEventListener("submit", save);
    return panel;
  }
  function render() {
    const panel = ensurePanel();
    const p = profile || {};
    panel.querySelector("#customer-profile-name").value = text(p.name);
    panel.querySelector("#customer-profile-legal-name").value = text(p.legal_name);
    panel.querySelector("#customer-profile-phone").value = text(p.phone);
    panel.querySelector("#customer-profile-document-type").value = text(p.document_type);
    panel.querySelector("#customer-profile-document-number").value = text(p.document_number);
    panel.querySelector("#customer-profile-email").textContent = text(p.account_email || "Não informado");
    panel.querySelector("#customer-profile-code").textContent = text(p.customer_code || "—");
    panel.querySelectorAll("input,select").forEach(node => { node.disabled = !editable; });
    panel.querySelector("#customer-profile-save").hidden = !editable;
  }
  async function load() {
    const response = await fetch(API, {headers: {"Accept":"application/json"}});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message || "Não foi possível carregar o perfil.");
    profile = body.profile || {};
    editable = body.editable === true;
    render();
  }
  async function open() {
    const panel = ensurePanel();
    panel.hidden = false;
    panel.scrollIntoView({behavior:"smooth", block:"start"});
    try { await load(); } catch (error) { message(error.message); }
  }
  async function save(event) {
    event.preventDefault();
    if (!editable) return;
    const panel = ensurePanel();
    const changes = {
      name: panel.querySelector("#customer-profile-name").value,
      legal_name: panel.querySelector("#customer-profile-legal-name").value,
      phone: panel.querySelector("#customer-profile-phone").value,
      document_type: panel.querySelector("#customer-profile-document-type").value,
      document_number: panel.querySelector("#customer-profile-document-number").value,
    };
    const response = await fetch(API, {method:"POST", headers:{"Content-Type":"application/json","Accept":"application/json"}, body:JSON.stringify({changes})});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) { message(body.message || "Não foi possível atualizar o perfil."); return; }
    profile = body.profile || profile;
    render();
    message(body.updated ? "Perfil atualizado." : "Nenhuma alteração necessária.");
  }

  document.addEventListener("click", event => {
    const trigger = event.target.closest("[data-customer-profile]");
    if (!trigger) return;
    event.preventDefault();
    open();
  });
  document.addEventListener("customer-email-changed", () => { if (!ensurePanel().hidden) load().catch(() => {}); });
})();
