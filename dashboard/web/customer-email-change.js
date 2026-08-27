(function () {
  "use strict";

  const INITIATE = "/api/customer/email-change/initiate";
  const VERIFY = "/api/customer/email-change/verify";
  const CANCEL = "/api/customer/email-change/cancel";
  let challengeId = "";

  function notify(value) {
    const node = document.getElementById("customer-message");
    if (!node) return;
    node.textContent = String(value || "");
    node.classList.add("show");
  }

  function panel() {
    let node = document.getElementById("customer-email-change-panel");
    if (node) return node;
    node = document.createElement("section");
    node.id = "customer-email-change-panel";
    node.className = "customer-section";
    node.hidden = true;
    node.innerHTML = `
      <article class="instance-panel">
        <div class="section-heading"><div><p class="customer-label">SEGURANÇA DA CONTA</p><h2>Alterar e-mail</h2><p>O novo endereço só será aplicado depois que o código enviado a ele for validado.</p></div><button class="button" type="button" data-email-close>Fechar</button></div>
        <div id="email-change-request">
          <label class="runtime-field">Novo e-mail<input id="email-change-target" type="email" autocomplete="email" required></label>
          <label class="runtime-region-fallback"><input id="email-change-confirm" type="checkbox"><span>Confirmo que estou solicitando a alteração do e-mail desta conta.</span></label>
          <div class="runtime-create-actions"><button class="button" type="button" data-email-initiate>Enviar código de verificação</button></div>
        </div>
        <div id="email-change-verify" hidden>
          <p>Insira o código recebido no novo endereço. O código é de uso único e possui prazo de expiração.</p>
          <label class="runtime-field">Código de verificação<input id="email-change-token" autocomplete="one-time-code" required></label>
          <label class="runtime-region-fallback"><input id="email-change-verify-confirm" type="checkbox"><span>Confirmo a aplicação do novo e-mail após a verificação.</span></label>
          <div class="runtime-create-actions"><button class="button" type="button" data-email-verify>Confirmar novo e-mail</button><button class="button" type="button" data-email-cancel>Cancelar solicitação</button></div>
        </div>
      </article>`;
    document.querySelector(".customer-main")?.appendChild(node);
    return node;
  }

  async function post(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: {"Content-Type":"application/json", "Accept":"application/json"},
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message || "Não foi possível concluir a operação.");
    return body;
  }

  async function initiate() {
    const node = panel();
    const email = node.querySelector("#email-change-target").value.trim();
    const confirmed = node.querySelector("#email-change-confirm").checked;
    try {
      const body = await post(INITIATE, {email, confirmed});
      challengeId = String(body.challenge_id || "");
      node.querySelector("#email-change-request").hidden = true;
      node.querySelector("#email-change-verify").hidden = false;
      notify("Código de verificação enviado ao novo e-mail.");
    } catch (error) { notify(error.message); }
  }

  async function verify() {
    const node = panel();
    const token = node.querySelector("#email-change-token").value.trim();
    const confirmed = node.querySelector("#email-change-verify-confirm").checked;
    try {
      await post(VERIFY, {challenge_id: challengeId, token, confirmed});
      challengeId = "";
      node.hidden = true;
      node.querySelector("#email-change-request").hidden = false;
      node.querySelector("#email-change-verify").hidden = true;
      node.querySelector("#email-change-token").value = "";
      notify("E-mail alterado e verificado com sucesso.");
      document.dispatchEvent(new CustomEvent("customer-email-changed"));
    } catch (error) { notify(error.message); }
  }

  async function cancel() {
    const node = panel();
    if (challengeId) {
      try { await post(CANCEL, {challenge_id: challengeId}); } catch (_) {}
    }
    challengeId = "";
    node.hidden = true;
    node.querySelector("#email-change-request").hidden = false;
    node.querySelector("#email-change-verify").hidden = true;
  }

  document.addEventListener("click", event => {
    if (event.target.closest("[data-customer-email-change]")) {
      event.preventDefault();
      const node = panel(); node.hidden = false; node.scrollIntoView({behavior:"smooth", block:"start"});
    } else if (event.target.closest("[data-email-initiate]")) initiate();
    else if (event.target.closest("[data-email-verify]")) verify();
    else if (event.target.closest("[data-email-cancel]")) cancel();
    else if (event.target.closest("[data-email-close]")) cancel();
  });
})();
