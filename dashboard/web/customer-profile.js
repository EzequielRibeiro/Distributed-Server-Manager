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

  function customerHeaders() {
    return {"Accept":"application/json","X-Capivara-Auth-Area":"customer"};
  }
  async function customerJson(path) {
    const response = await fetch(path, {headers: customerHeaders(), credentials:"same-origin", cache:"no-store"});
    if (!response.ok) return null;
    return response.json().catch(() => null);
  }
  function publicContractCode(resource, metadata, contracts) {
    const candidates = [
      resource?.contract_code,
      resource?.contract_id,
      metadata?.contract_code,
      metadata?.contract_id,
      metadata?.contract?.code,
      metadata?.contract?.id,
    ].map(value => String(value || "").trim()).filter(Boolean);
    for (const candidate of candidates) {
      const match = contracts.find(contract => String(contract.id || contract.contract_code || "") === candidate);
      if (match) return String(match.contract_code || match.id || candidate);
      if (/^[a-z0-9][a-z0-9._-]*-[a-f0-9]{6,}$/i.test(candidate)) return candidate;
    }
    return "";
  }
  function contractBadge(code) {
    const node = document.createElement("small");
    node.className = "customer-contract-code";
    node.textContent = `Contrato: ${code}`;
    node.title = "Código de referência do contrato deste servidor";
    return node;
  }
  async function decorateServerContractCodes() {
    const container = document.getElementById("customer-servers");
    if (!container) return;
    const [runtimeData, contractData] = await Promise.all([
      customerJson("/api/runtime/list"),
      customerJson("/api/customer/contracts"),
    ]);
    const resources = Array.isArray(runtimeData) ? runtimeData : (runtimeData?.resources || []);
    const contracts = contractData?.contracts || [];
    if (!resources.length || !contracts.length) return;
    const enriched = await Promise.all(resources.map(async resource => {
      let metadata = resource.metadata || {};
      const params = new URLSearchParams(resource);
      const summary = await customerJson(`/api/runtime?${params}`);
      if (summary?.instance_metadata) metadata = summary.instance_metadata;
      return {resource, metadata};
    }));
    const apply = () => {
      const cards = [...container.querySelectorAll(".server-card")];
      enriched.forEach(({resource, metadata}, index) => {
        const card = cards[index];
        if (!card || card.querySelector(".customer-contract-code")) return;
        const code = publicContractCode(resource, metadata, contracts);
        if (!code) return;
        const title = card.querySelector(".server-card-head > div") || card;
        title.append(contractBadge(code));
      });
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(container, {childList:true, subtree:true});
    window.setTimeout(() => observer.disconnect(), 10000);
  }
  async function decorateInstanceContractCode() {
    const title = document.getElementById("title");
    if (!title || !location.pathname.endsWith("/customer-instance.html")) return;
    const q = new URLSearchParams(location.search);
    const instanceId = q.get("instance") || q.get("instance_id") || "";
    if (!instanceId) return;
    const [runtimeData, contractData] = await Promise.all([
      customerJson("/api/runtime/list"),
      customerJson("/api/customer/contracts"),
    ]);
    const resources = Array.isArray(runtimeData) ? runtimeData : (runtimeData?.resources || []);
    const contracts = contractData?.contracts || [];
    const resource = resources.find(item => String(item.instance || item.instance_id || "") === instanceId) || {};
    let metadata = resource.metadata || {};
    if (Object.keys(resource).length) {
      const summary = await customerJson(`/api/runtime?${new URLSearchParams(resource)}`);
      if (summary?.instance_metadata) metadata = summary.instance_metadata;
    }
    const code = publicContractCode(resource, metadata, contracts);
    if (!code || document.getElementById("instance-contract-code")) return;
    const node = document.createElement("span");
    node.id = "instance-contract-code";
    node.className = "muted customer-contract-code";
    node.textContent = `Contrato: ${code}`;
    node.title = "Informe este código ao suporte para identificar exatamente o contrato deste servidor";
    title.insertAdjacentElement("afterend", node);
  }

  document.addEventListener("click", event => {
    const trigger = event.target.closest("[data-customer-profile]");
    if (!trigger) return;
    event.preventDefault();
    open();
  });
  document.addEventListener("customer-email-changed", () => { if (!ensurePanel().hidden) load().catch(() => {}); });
  decorateServerContractCodes().catch(() => {});
  decorateInstanceContractCode().catch(() => {});
})();
