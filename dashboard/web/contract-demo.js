(function () {
  "use strict";

  const requestedGame = new URLSearchParams(location.search).get("game") || "";
  const customerHeaders = () => ({Accept: "application/json", "X-Capivara-Auth-Area": "customer"});

  const gameNames = {
    minecraft: "Minecraft",
    dayz: "DayZ",
    rust: "Rust",
    arma3: "Arma 3",
    mindustry: "Mindustry",
  };

  function normalize(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, "");
  }

  function gameLabel(game) {
    return gameNames[String(game || "").toLowerCase()] || String(game || "Jogo");
  }

  function formatGb(memoryMb) {
    const value = Number(memoryMb);
    if (!Number.isFinite(value) || value <= 0) return "—";
    return `${(value / 1024).toLocaleString("pt-BR", {maximumFractionDigits: 2})} GB`;
  }

  async function request(path) {
    const response = await fetch(path, {
      headers: customerHeaders(),
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

  function resolveGame(catalogData) {
    const entries = Array.isArray(catalogData)
      ? catalogData
      : (catalogData.runtimes || catalogData.entries || []);

    const games = [...new Set(entries.map(item => item.game || item.game_id || item.id).filter(Boolean))];
    const target = normalize(requestedGame);
    return games.find(game => normalize(game) === target || normalize(gameLabel(game)) === target) || requestedGame.trim().toLowerCase();
  }

  function profileCard(profile, contracted) {
    const article = document.createElement("article");
    article.className = "server-card contract";

    const label = document.createElement("span");
    label.className = "game";
    label.textContent = contracted ? "PERFIL CONTRATADO" : "PERFIL DO CATÁLOGO";

    const title = document.createElement("h3");
    title.textContent = profile.name || profile.display_name || profile.id || "Perfil";

    const description = document.createElement("p");
    description.textContent = profile.description || "Perfil de recursos disponível para este jogo.";

    const box = document.createElement("div");
    box.className = "contract-profile";

    const specifications = document.createElement("dl");
    [
      ["CPU", Number(profile.cpu_cores) > 0 ? `${profile.cpu_cores} núcleos` : "—"],
      ["Memória", formatGb(profile.memory_mb)],
      ["Armazenamento", formatGb(profile.storage_mb)],
    ].forEach(([name, value]) => {
      const item = document.createElement("div");
      const term = document.createElement("dt");
      const detail = document.createElement("dd");
      term.textContent = name;
      detail.textContent = value;
      item.append(term, detail);
      specifications.append(item);
    });
    box.append(specifications);

    const actions = document.createElement("div");
    actions.className = "server-actions";
    const action = document.createElement("a");
    action.className = "button";
    action.href = "/customer.html";
    action.textContent = contracted ? "Já contratado · Ir para Meus servidores" : "Voltar para Meus servidores";
    actions.append(action);

    article.append(label, title, description, box, actions);
    return article;
  }

  async function load() {
    const title = document.getElementById("demo-game");
    const container = document.getElementById("demo-profiles");

    try {
      await request("/api/customer/auth/session");
      const catalogData = await request("/api/catalog/runtimes");
      const game = resolveGame(catalogData);
      title.textContent = `Servidor ${gameLabel(game)}`;

      const [profileData, contractData] = await Promise.all([
        request(`/api/catalog/resource-profiles?game=${encodeURIComponent(game)}`),
        request("/api/customer/contracts"),
      ]);

      const profiles = Array.isArray(profileData.profiles) ? profileData.profiles : [];
      const contracts = Array.isArray(contractData.contracts) ? contractData.contracts : [];
      const activeProfiles = new Set(
        contracts
          .filter(item => item.status === "active" && String(item.game_id || "").toLowerCase() === String(game).toLowerCase())
          .map(item => item.resource_profile_id)
          .filter(Boolean)
      );

      container.replaceChildren();
      if (!profiles.length) {
        const empty = document.createElement("p");
        empty.textContent = "Nenhum perfil de recursos está cadastrado no catálogo para este jogo.";
        container.append(empty);
        return;
      }

      profiles.forEach(profile => {
        container.append(profileCard(profile, activeProfiles.has(profile.id)));
      });
    } catch (error) {
      container.replaceChildren();
      const message = document.createElement("p");
      message.textContent = error.message || "Não foi possível carregar os perfis do jogo.";
      container.append(message);
    }
  }

  load();
})();
