(function () {
  "use strict";

  const AREA_HEADER = "X-Capivara-Auth-Area";
  const nativeFetch = window.fetch.bind(window);

  if (!window.__capivaraCustomerFetchBoundary) {
    window.__capivaraCustomerFetchBoundary = true;
    window.fetch = function (input, init) {
      const options = {...(init || {})};
      const headers = new Headers(options.headers || {});
      headers.set(AREA_HEADER, "customer");
      options.headers = headers;
      if (!options.credentials) options.credentials = "same-origin";
      return nativeFetch(input, options);
    };
  }

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

    sidebar.style.overflowY = "auto";

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

    let logout = sidebar.querySelector("#customer-logout");
    if (!logout) {
      logout = document.createElement("button");
      logout.id = "customer-logout";
      logout.className = "customer-logout";
      logout.type = "button";
      logout.textContent = "Sair";
      sidebar.appendChild(logout);
    }

    logout.hidden = false;
    logout.style.display = "block";
    logout.style.position = "sticky";
    logout.style.bottom = "0";
    logout.style.zIndex = "5";
    logout.style.marginTop = "20px";
    logout.style.background = "#091b18";

    if (!logout.dataset.navigationBound) {
      logout.dataset.navigationBound = "1";
      logout.addEventListener("click", async (event) => {
        event.preventDefault();
        try {
          await fetch("/api/customer/auth/logout", {
            method: "POST",
            credentials: "same-origin",
            headers: {Accept: "application/json", [AREA_HEADER]: "customer"},
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