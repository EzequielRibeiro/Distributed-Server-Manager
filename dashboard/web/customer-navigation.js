(function () {
  "use strict";

  const ITEMS = [
    ["/customer.html", "▣", "Meus servidores", "Instâncias contratadas"],
    ["/customer-backups.html", "↺", "Backups", "Backups de todos os servidores"],
    ["/customer-integrations.html", "◇", "Integrações", "Discord e serviços externos"],
    ["/customer-members.html", "◎", "Equipe e acessos", "Usuários, convites e permissões"],
    ["/customer.html#profile", "◌", "Dados cadastrais", "Cadastro e informações da conta", "profile"],
    ["/customer-change-password.html", "⌁", "Conta e segurança", "Senha e segurança de acesso"],
  ];

  function activePath() {
    return location.pathname || "/customer.html";
  }

  function link([href, mark, title, subtitle, action]) {
    const anchor = document.createElement("a");
    anchor.className = "catalog-game customer-nav-link";
    anchor.href = href;
    anchor.dataset.customerNav = title;
    if (activePath() === href.split("#")[0] && !href.includes("#")) {
      anchor.classList.add("active");
      anchor.setAttribute("aria-current", "page");
    }
    if (action === "profile") {
      anchor.setAttribute("data-customer-profile", "");
    }
    anchor.innerHTML = `<span class="game-mark">${mark}</span><span><strong>${title}</strong><small>${subtitle}</small></span>`;
    return anchor;
  }

  function install() {
    const sidebar = document.querySelector(".customer-sidebar");
    if (!sidebar) return;

    let area = sidebar.querySelector("nav[aria-label='Área do cliente']");
    if (!area) {
      const label = document.createElement("p");
      label.className = "customer-label";
      label.textContent = "Cliente";
      area = document.createElement("nav");
      area.className = "customer-catalog";
      area.setAttribute("aria-label", "Área do cliente");
      const brand = sidebar.querySelector(".customer-brand");
      (brand || sidebar.firstChild)?.after(label, area);
    }
    area.replaceChildren(...ITEMS.map(link));

    const logout = sidebar.querySelector("#customer-logout");
    if (logout && !logout.dataset.navigationBound) {
      logout.dataset.navigationBound = "1";
      logout.addEventListener("click", () => {
        sessionStorage.removeItem("dsm_auth");
        location.href = "/login.html";
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }
})();
