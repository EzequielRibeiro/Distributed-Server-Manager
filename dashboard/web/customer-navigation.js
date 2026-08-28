(function () {
  "use strict";

  const ITEMS = [
    ["/customer.html", "▣", "Meus servidores", "Instâncias contratadas"],
    ["/customer-backups.html", "↺", "Backups", "Backups de todos os servidores"],
    ["/customer-integrations.html", "◇", "Integrações", "Discord e serviços externos"],
    ["/customer-members.html", "◎", "Equipe e acessos", "Usuários, convites e permissões"],
    ["/customer-account.html", "◌", "Minha conta", "Cadastro e informações da conta"],
  ];

  function activePath() {
    return location.pathname || "/customer.html";
  }

  function link([href, mark, title, subtitle]) {
    const anchor = document.createElement("a");
    anchor.className = "catalog-game customer-nav-link";
    anchor.href = href;
    anchor.dataset.customerNav = title;
    if (activePath() === href) {
      anchor.classList.add("active");
      anchor.setAttribute("aria-current", "page");
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
      logout.addEventListener("click", async (event) => {
        event.preventDefault();
        try {
          await fetch("/api/customer/auth/logout", {
            method: "POST",
            credentials: "same-origin",
            headers: {Accept: "application/json"},
            cache: "no-store",
          });
        } finally {
          location.replace("/customer-login.html");
        }
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }
})();
