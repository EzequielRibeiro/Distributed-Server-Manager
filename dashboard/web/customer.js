(function() {
  "use strict";

  const $ = id => document.getElementById(id);

  const auth = () =>
    sessionStorage.getItem("dsm_auth") || "";

  const gameNames = {
    minecraft: "Minecraft",
    dayz: "DayZ",
    rust: "Rust",
    arma3: "Arma 3",
    mindustry: "Mindustry",
  };

  let resources = [];
  let contracts = [];
  let catalog = [];

  // =========================================================
  // HTTP
  // =========================================================

  async function request(path, options = {}) {
    const headers = {
      Authorization: `Basic ${auth()}`,
      Accept: "application/json",
    };

    if (options.body) {
      headers["Content-Type"] = "application/json";
    }

    const response = await fetch(
      path, {
        ...options,
        headers,
      }
    );

    if (response.status === 401) {
      sessionStorage.removeItem("dsm_auth");
      location.href = "/login.html";

      throw new Error(
        "Sessão encerrada."
      );
    }

    const data =
      await response
      .json()
      .catch(() => ({}));

    if (!response.ok) {
      throw new Error(
        data.error ||
        `HTTP ${response.status}`
      );
    }

    return data;
  }


  // =========================================================
  // Mensagens
  // =========================================================

  function message(text) {
    const node =
      $("customer-message");

    if (!node) {
      return;
    }

    node.textContent =
      text;

    node.classList.add(
      "show"
    );

    clearTimeout(
      message.timer
    );

    message.timer =
      setTimeout(
        () => {
          node.classList.remove(
            "show"
          );
        },
        3500
      );
  }


  // =========================================================
  // Helpers
  // =========================================================

  function gameLabel(game) {
    return (
      gameNames[game] ||
      game ||
      "Servidor"
    );
  }


  function instanceUrl(item) {
    return (
      "/customer-instance.html?" +
      new URLSearchParams({
        server: item.server,

        game: item.game,

        instance: item.instance,
      })
    );
  }


  function stateLabel(value) {
    const state =
      String(
        value || "unknown"
      ).toLowerCase();

    const labels = {
      online: "Online",
      running: "Online",
      offline: "Offline",
      queued: "Aguardando instalação",
      provisioning: "Preparando instalação",
      pending_steam_auth: "Aguardando autenticação Steam",
      pending_install: "Aguardando instalação",
      installing: "Instalando",
      failed: "Falha na instalação",
      error: "Erro",
    };

    return (
      labels[state] ||
      value ||
      "Desconhecido"
    );
  }


  function stateClass(value) {
    const state =
      String(
        value || "unknown"
      ).toLowerCase();

    if (
      state.includes("online") ||
      state.includes("running")
    ) {
      return "online";
    }

    if (
      state.includes("offline") ||
      state.includes("stop")
    ) {
      return "offline";
    }

    return "warning";
  }


  // =========================================================
  // Runtime da instância
  // =========================================================

  function runtimeDescription(item) {
    const metadata =
      item.metadata || {};

    const runtime =
      metadata.runtime || {};

    const parts = [];

    if (runtime.edition) {
      parts.push(
        runtime.edition
      );
    }

    if (
      runtime.variant ||
      runtime.server_type ||
      runtime.loader
    ) {
      parts.push(
        runtime.variant ||
        runtime.server_type ||
        runtime.loader
      );
    }

    if (runtime.version) {
      parts.push(
        runtime.version
      );
    }

    return parts
      .filter(Boolean)
      .join(" · ");
  }


  // =========================================================
  // Card de instância existente
  // =========================================================

  function instanceCard(item) {
    const article =
      document.createElement(
        "article"
      );

    article.className =
      "server-card";

    const head =
      document.createElement(
        "div"
      );

    head.className =
      "server-card-head";

    const title =
      document.createElement(
        "div"
      );

    const game =
      document.createElement(
        "span"
      );

    game.className =
      "game";

    game.textContent =
      gameLabel(
        item.game
      );

    const name =
      document.createElement(
        "h3"
      );

    name.textContent =
      item.metadata
      ?.display_name ||
      item.instance;

    const runtime =
      document.createElement(
        "small"
      );

    const runtimeText =
      runtimeDescription(
        item
      );

    runtime.textContent =
      runtimeText ?
      runtimeText :
      `Agente: ${
                    item.metadata
                        ?.agent_id
                    || item.server
                }`;

    const state =
      document.createElement(
        "span"
      );

    state.className =
      `state ${
                stateClass(
                    item.status
                )
            }`;

    state.textContent =
      stateLabel(
        item.status
      );

    title.append(
      game,
      name,
      runtime
    );

    head.append(
      title,
      state
    );

    article.append(
      head
    );


    // -----------------------------------------------------
    // Provisionamento
    // -----------------------------------------------------

    if (
      [
        "queued",
        "provisioning",
        "pending_steam_auth",
      ].includes(
        item.provision
        ?.status
      )
    ) {
      const detail =
        document.createElement(
          "p"
        );

      detail.textContent =
        `${
                    item.provision
                        .message
                    || "Preparando instalação…"
                } (${
                    item.provision
                        .progress
                    || 0
                }%)`;

      article.append(
        detail
      );
    }


    // -----------------------------------------------------
    // Alertas
    // -----------------------------------------------------

    const alerts =
      (
        item.events || []
      )
      .filter(
        event => [
          "warning",
          "error",
          "critical",
        ].includes(
          String(
            event.severity ||
            event.level
          )
          .toLowerCase()
        )
      )
      .slice(
        0,
        2
      );

    if (alerts.length) {
      const list =
        document.createElement(
          "ul"
        );

      list.className =
        "alert-list";

      alerts.forEach(
        alert => {
          const li =
            document.createElement(
              "li"
            );

          li.textContent =
            alert.message ||
            alert.title ||
            "A instância requer atenção.";

          list.append(
            li
          );
        }
      );

      article.append(
        list
      );
    }


    // -----------------------------------------------------
    // Ações
    // -----------------------------------------------------

    const actions =
      document.createElement(
        "div"
      );

    actions.className =
      "server-actions";

    const open =
      document.createElement(
        "button"
      );

    open.type =
      "button";

    open.textContent =
      "Administrar instância";

    open.addEventListener(
      "click",
      () => {
        location.href =
          instanceUrl(
            item
          );
      }
    );

    actions.append(
      open
    );

    article.append(
      actions
    );

    return {
      node: article,
      alerts: alerts.length,
    };
  }


  // =========================================================
  // Card de contrato disponível
  // =========================================================

  function contractCard(
    contract,
    slotIndex
  ) {
    const article =
      document.createElement(
        "article"
      );

    article.className =
      "server-card contract";

    article.dataset.contract =
      contract.id;

    article.dataset.slot =
      String(
        slotIndex
      );


    const label =
      document.createElement(
        "span"
      );

    label.className =
      "game";

    label.textContent =
      "CONTRATO ATIVO";


    const title =
      document.createElement(
        "h3"
      );

    title.textContent =
      gameLabel(
        contract.game_id
      );


    const detail =
      document.createElement(
        "p"
      );

    detail.textContent =
      "Você possui uma vaga contratada. Escolha o tipo de servidor antes da criação da instância.";


    const usage =
      document.createElement(
        "small"
      );

    usage.textContent =
      `Em uso: ${
                contract.instances_used
                || 0
            } de ${
                contract.instance_limit
                || 0
            }`;


    const actions =
      document.createElement(
        "div"
      );

    actions.className =
      "server-actions";


    const create =
      document.createElement(
        "button"
      );

    create.type =
      "button";

    create.textContent =
      "Criar servidor agora";


    create.addEventListener(
      "click",
      () => {
        if (
          !window
          .CapivaraRuntimeSelector ||
          typeof window
          .CapivaraRuntimeSelector
          .open !==
          "function"
        ) {
          message(
            "O seletor de tipo de servidor não está disponível."
          );

          return;
        }

        window
          .CapivaraRuntimeSelector
          .open(
            contract
          )
          .catch(
            error => {
              message(
                error.message
              );
            }
          );
      }
    );


    actions.append(
      create
    );

    article.append(
      label,
      title,
      detail,
      usage,
      actions
    );

    return article;
  }


  // =========================================================
  // Renderizar contratos
  // =========================================================

  function renderContracts() {
    const container =
      $("customer-contracts");

    if (!container) {
      return;
    }

    container.replaceChildren();

    let availableSlots =
      0;

    contracts.forEach(
      contract => {
        const limit =
          Number(
            contract
            .instance_limit
          ) || 0;

        const used =
          Number(
            contract
            .instances_used
          ) || 0;

        const free =
          Math.max(
            0,
            limit - used
          );

        if (
          contract.status !==
          "active" ||
          !contract.available ||
          free <= 0
        ) {
          return;
        }

        for (
          let index = 0; index < free; index += 1
        ) {
          container.append(
            contractCard(
              contract,
              index
            )
          );

          availableSlots += 1;
        }
      }
    );


    if (
      !container.children.length
    ) {
      const empty =
        document.createElement(
          "p"
        );

      empty.textContent =
        "Nenhuma vaga contratada disponível para criação.";

      container.append(
        empty
      );
    }


    const summary =
      $("summary-slots");

    if (summary) {
      summary.textContent =
        String(
          availableSlots
        );
    }
  }


  // =========================================================
  // Renderizar instâncias
  // =========================================================

  function renderInstances() {
    const container =
      $("customer-servers");

    if (!container) {
      return;
    }

    container.replaceChildren();

    let alertCount =
      0;

    let onlineCount =
      0;


    resources.forEach(
      item => {
        const rendered =
          instanceCard(
            item
          );

        alertCount +=
          rendered.alerts;

        if (
          stateClass(
            item.status
          ) ===
          "online"
        ) {
          onlineCount += 1;
        }

        container.append(
          rendered.node
        );
      }
    );


    if (
      !container.children.length
    ) {
      const empty =
        document.createElement(
          "p"
        );

      empty.textContent =
        "Nenhuma instância criada.";

      container.append(
        empty
      );
    }


    const summaryInstances =
      $("summary-instances");

    if (summaryInstances) {
      summaryInstances
        .textContent =
        String(
          resources.length
        );
    }


    const summaryOnline =
      $("summary-online");

    if (summaryOnline) {
      summaryOnline
        .textContent =
        String(
          onlineCount
        );
    }


    const summaryAlerts =
      $("summary-alerts");

    if (summaryAlerts) {
      summaryAlerts
        .textContent =
        String(
          alertCount
        );
    }
  }


  // =========================================================
  // Catálogo lateral
  // =========================================================

  function renderCatalog() {
    const nav =
      $("customer-catalog");

    if (!nav) {
      return;
    }

    const games = [
      ...new Set(
        [
          ...catalog.map(
            item =>
            item.game ||
            item.id
          ),

          ...contracts.map(
            item =>
            item.game_id
          ),

          ...resources.map(
            item =>
            item.game
          ),
        ]
        .filter(
          Boolean
        )
      ),
    ].sort();


    nav.replaceChildren();


    games.forEach(
      game => {
        const instances =
          resources.filter(
            item =>
            item.game ===
            game
          );

        const hasContract =
          contracts.some(
            item =>
            item.game_id ===
            game &&
            item.status ===
            "active"
          );


        const button =
          document.createElement(
            "button"
          );

        button.type =
          "button";

        button.className =
          `catalog-game ${
                        hasContract
                            ? ""
                            : "locked"
                    }`;


        const mark =
          document.createElement(
            "span"
          );

        mark.className =
          "game-mark";

        mark.textContent =
          gameLabel(
            game
          )
          .slice(
            0,
            2
          )
          .toUpperCase();


        const text =
          document.createElement(
            "span"
          );

        const strong =
          document.createElement(
            "strong"
          );

        const small =
          document.createElement(
            "small"
          );

        const flag =
          document.createElement(
            "b"
          );


        strong.textContent =
          gameLabel(
            game
          );


        if (
          instances.length
        ) {
          small.textContent =
            `${instances.length} instância(s)`;
        } else if (
          hasContract
        ) {
          small.textContent =
            "Pronto para criar";
        } else {
          small.textContent =
            "Conheça o plano";
        }


        flag.textContent =
          hasContract ?
          "ATIVO" :
          "VER";


        text.append(
          strong,
          small
        );

        button.append(
          mark,
          text,
          flag
        );


        button.addEventListener(
          "click",
          () => {
            if (
              instances.length ===
              1
            ) {
              location.href =
                instanceUrl(
                  instances[0]
                );

              return;
            }


            if (
              !hasContract
            ) {
              location.href =
                `/contract-demo.html?game=${
                                    encodeURIComponent(
                                        game
                                    )
                                }`;

              return;
            }


            const contract =
              contracts.find(
                item =>
                item.game_id ===
                game &&
                item.available
              );

            if (
              contract &&
              window
              .CapivaraRuntimeSelector
            ) {
              window
                .CapivaraRuntimeSelector
                .open(
                  contract
                )
                .catch(
                  error =>
                  message(
                    error.message
                  )
                );

              return;
            }


            $("customer-contracts")
              ?.scrollIntoView({
                behavior: "smooth",
              });
          }
        );


        nav.append(
          button
        );
      }
    );
  }


  // =========================================================
  // Carregar dashboard
  // =========================================================

  async function load() {
    if (!auth()) {
      location.href =
        "/login.html";

      return;
    }


    const [
      user,
      runtimeData,
      contractData,
      catalogData,
    ] =
    await Promise.all(
      [
        request(
          "/api/whoami"
        ),

        request(
          "/api/runtime/list"
        ),

        request(
          "/api/customer/contracts"
        ),

        request(
          "/api/catalog/runtimes"
        ),
      ]
    );


    if (
      ![
        "customer",
        "admin",
        "controller",
      ].includes(
        user.role
      )
    ) {
      location.href =
        "/index.html";

      return;
    }


    resources =
      Array.isArray(
        runtimeData
      ) ?
      runtimeData :
      (
        runtimeData
        .resources ||
        []
      );


    contracts =
      contractData
      .contracts ||
      [];


    catalog =
      Array.isArray(
        catalogData
      ) ?
      catalogData :
      (
        catalogData
        .runtimes ||
        []
      );


    const profile =
      $("customer-profile");

    if (profile) {
      profile.textContent =
        `${user.username} · ${user.role}`;
    }


    // -----------------------------------------------------
    // Carregar detalhes de cada instância
    // -----------------------------------------------------

    const summaries =
      await Promise.all(
        resources.map(
          async item => {
            try {
              const data =
                await request(
                  `/api/runtime?${
                                        new URLSearchParams(
                                            item
                                        )
                                    }`
                );

              return {
                ...item,

                status: data
                  .server_state
                  ?.status
                  ?.state ||
                  item.status,

                events: data.events ||
                  [],

                metadata: data
                  .instance_metadata ||
                  {},

                provision: data.provision ||
                  {},
              };
            } catch (
              error
            ) {
              console.error(
                error
              );

              return item;
            }
          }
        )
      );


    resources =
      summaries;


    renderContracts();
    renderInstances();
    renderCatalog();
  }


  // =========================================================
  // API pública para runtime-selector.js
  // =========================================================

  window.CapivaraCustomer = {
    reload: load,
  };


  // =========================================================
  // Eventos
  // =========================================================

  const refresh =
    $("customer-refresh");

  if (refresh) {
    refresh.addEventListener(
      "click",
      () => {
        load()
          .catch(
            error =>
            message(
              error.message
            )
          );
      }
    );
  }


  const logout =
    $("customer-logout");

  if (logout) {
    logout.addEventListener(
      "click",
      () => {
        sessionStorage.removeItem(
          "dsm_auth"
        );

        location.href =
          "/login.html";
      }
    );
  }


  // =========================================================
  // Inicialização
  // =========================================================

  load()
    .catch(
      error => {
        console.error(
          error
        );

        message(
          error.message
        );
      }
    );

})();