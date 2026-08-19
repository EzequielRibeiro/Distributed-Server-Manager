(function(){
  "use strict";
  const $=id=>document.getElementById(id),auth=()=>sessionStorage.getItem("dsm_auth")||"",identity=Object.fromEntries(new URLSearchParams(location.search));let summary={},filePath=".",availableContent=[],installedContent=[],selectedRuntime=null;
  const instancePath=()=>`/opt/dsm/instances/${identity.server}/${identity.game}/${identity.instance}`;
  async function request(path,options={}){const headers={Authorization:`Basic ${auth()}`,Accept:"application/json"};if(options.body)headers["Content-Type"]="application/json";const response=await fetch(path,{...options,headers});if(response.status===401){sessionStorage.removeItem("dsm_auth");location.href="/login.html";throw new Error("Sessão encerrada")}const contentType=response.headers.get("content-type")||"";const data=contentType.includes("application/json")?await response.json():await response.blob();if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data}
  function message(text){const node=$("customer-message");node.textContent=text;node.classList.add("show");clearTimeout(message.timer);message.timer=setTimeout(()=>node.classList.remove("show"),3500)}
  function query(extra={}){return new URLSearchParams({...identity,...extra}).toString()}
  function online(){const state=String(summary.server_state?.status?.state||summary.server_state?.status||"offline").toLowerCase();return state.includes("online")||state.includes("running")}
  function stateLabel(value) {
    const state =
      String(value || "offline")
        .toLowerCase();

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

    return labels[state] || value || "Desconhecido";
  }

  function stateVisualClass(value) {
    const state =
      String(value || "offline")
        .toLowerCase();

    if (
      state === "online" ||
      state === "running"
    ) {
      return "online";
    }

    if (
      [
        "queued",
        "provisioning",
        "pending_steam_auth",
        "pending_install",
        "installing",
        "failed",
        "error",
      ].includes(state)
    ) {
      return "warning";
    }

    return "offline";
  }
  function renderProvision(provision) {
    const status = String(
      provision?.status || ""
    ).toLowerCase();

    const pending = [
      "queued",
      "provisioning",
      "pending_steam_auth",
    ].includes(status);

    const failed =
      status === "failed";

    const completed =
      String(
        provision?.stage || ""
      ).toLowerCase() === "completed"
      && Number(provision?.progress) >= 100;

    const visible =
      pending || failed || completed;

    const box =
      $("provision-progress");

    /*
     * O painel permanece visível durante o provisionamento
     * e também após uma falha.
     *
     * Como os dados vêm do provision.json, a mensagem
     * continua visível depois de F5, logout/login etc.
     */
    box.hidden = !visible;

    /*
     * Nenhum controle da instância deve estar disponível
     * enquanto a instalação estiver pendente ou falhar.
     */
    if (failed || pending) {
      $("instance-start").disabled = true;
      $("instance-stop").disabled = true;
      $("instance-restart").disabled = true;
    } else {
      $("instance-start").disabled =
        online();

      $("instance-stop").disabled =
        !online();

      $("instance-restart").disabled =
        !online();
    }

    if (!visible) {
      return;
    }

    const value = Math.max(
      0,
      Math.min(
        100,
        Number(provision.progress) || 0
      )
    );

    $("provision-value").textContent =
      `${value}%`;

    $("provision-bar").style.width =
      `${value}%`;

    $("provision-failed-actions").hidden =
      true;

    /*
     * Falha persistente
     */
    if (failed || status === "pending_steam_auth") {
      $("provision-label").textContent =
        status === "pending_steam_auth"
          ? "Autenticação Steam necessária"
          : "Falha na instalação";

      $("provision-detail").textContent =
        provision.message ||
        (status === "pending_steam_auth"
          ? "O administrador deve autenticar a Steam. Depois, tente novamente."
          : "Não foi possível instalar o jogo. O administrador foi notificado.");

      box.classList.add(
        "provision-failed"
      );

      $("provision-failed-actions").hidden =
        false;

      return;
    }

    box.classList.remove(
      "provision-failed"
    );

    /*
     * Provisionamento concluído.
     *
     * O resultado permanece visível para deixar claro
     * ao cliente que a instalação terminou com sucesso.
     */
    if (completed) {
      $("provision-label").textContent =
        "Instalação concluída";

      $("provision-detail").textContent =
        provision.message ||
        "O servidor está pronto para iniciar.";

      return;
    }

    /*
     * Steam requer intervenção administrativa.
     */
    if (
      status === "pending_steam_auth"
    ) {
      $("provision-label").textContent =
        "Autenticação Steam necessária";
    } else if (
      status === "queued"
    ) {
      $("provision-label").textContent =
        "Instalação aguardando o Agent";
    } else {
      $("provision-label").textContent =
        `Instalação: ${
          provision.stage ||
          "em andamento"
        }`;
    }

    $("provision-detail").textContent =
      provision.message ||
      "Aguarde a preparação do ambiente.";
  }
  async function loadSummary(){summary=await request(`/api/runtime?${query()}`);const metadata=summary.instance_metadata||{};const state=summary.server_state?.status?.state||summary.server_state?.status||"offline";$("instance-title").textContent=metadata.display_name||identity.instance;$("instance-game").textContent=String(identity.game||"").toUpperCase();$("instance-state").textContent=stateLabel(state);$("instance-state").className=`state ${stateVisualClass(state)}`;renderProvision(summary.provision||{});const events=(summary.events||[]).filter(event=>["warning","error","critical"].includes(String(event.severity||event.level).toLowerCase()));const overview=$("instance-overview");overview.replaceChildren();const details=document.createElement("p");details.textContent=`Agente: ${metadata.agent_id||identity.server} · Identificador: ${identity.instance}`;overview.append(details);if(events.length){const list=document.createElement("ul");list.className="alert-list";events.slice(0,5).forEach(event=>{const li=document.createElement("li");li.textContent=event.message||event.title||"A instância requer atenção";list.append(li)});overview.append(list)}else{const healthy=document.createElement("p");healthy.textContent="Nenhum alerta ativo para esta instância.";overview.append(healthy)}}
  async function control(action){if(action!=="start"&&!confirm(`${action==="restart"?"Reiniciar":"Parar"} esta instância?`))return;togglePower(true);try{await request(`/api/instance/${action}`,{method:"POST",body:JSON.stringify(identity)});message(`Operação ${action} concluída.`);await loadSummary()}finally{togglePower(false)}}
  function togglePower(value){["instance-start","instance-restart","instance-stop"].forEach(id=>$(id).disabled=value)}
  async function loadLogs(){try{const data=await request(`/api/instance/logs?${query({limit:"300"})}`);$("log-connection").textContent="conectado";$("log-connection").className="state online";const terminal=$("instance-terminal"),atBottom=terminal.scrollHeight-terminal.scrollTop-terminal.clientHeight<30;terminal.textContent=(data.logs||[]).join("\n")||"Nenhum registro disponível.";if($("log-autoscroll").checked&&atBottom)terminal.scrollTop=terminal.scrollHeight}catch{$("log-connection").textContent="reconectando";$("log-connection").className="state warning"}}
  async function loadConfigs(){const data=await request(`/api/instance/config?instance=${encodeURIComponent(instancePath())}`),select=$("config-file");select.replaceChildren(...(data.files||[]).map(file=>new Option(file,file)));if(data.files?.length)await loadConfig()}
  async function loadConfig(){const data=await request(`/api/instance/config?${new URLSearchParams({instance:instancePath(),file:$("config-file").value})}`);$("config-editor").value=data.content||""}
  async function saveConfig(){await request("/api/instance/config",{method:"POST",body:JSON.stringify({instance:instancePath(),file:$("config-file").value,content:$("config-editor").value})});message("Configuração salva.")}
  async function loadFiles() {
    const data = await request(
      `/api/instance/files?${query({ path: filePath })}`
    );

    const body = $("file-list");
    const pathNode = $("file-path");

    pathNode.textContent =
      filePath === "."
        ? "/"
        : `/${filePath}`;

    body.replaceChildren();

    if (filePath !== ".") {
      const row = document.createElement("tr");

      const name = document.createElement("td");
      const size = document.createElement("td");
      const date = document.createElement("td");
      const actions = document.createElement("td");

      const back = document.createElement("a");

      back.href = "#";
      back.className = "file-directory-link";
      back.textContent = "⬅ .. Voltar";

      back.addEventListener("click", event => {
        event.preventDefault();
        parentDirectory();
      });

      name.append(back);
      size.textContent = "—";

      row.append(name, size, date, actions);
      body.append(row);
    }

    (data.entries || []).forEach(entry => {
      const row = document.createElement("tr");

      const name = document.createElement("td");
      const size = document.createElement("td");
      const date = document.createElement("td");
      const actions = document.createElement("td");

      if (entry.directory) {
        const folderLink = document.createElement("a");

        folderLink.href = "#";
        folderLink.className = "file-directory-link";
        folderLink.textContent = `📁 ${entry.name}`;

        folderLink.addEventListener("click", event => {
          event.preventDefault();
          openDirectory(entry.name);
        });

        name.append(folderLink);
        size.textContent = "—";
      } else {
        size.textContent = `${entry.size} B`;

        if (entry.editable) {
          const fileLink = document.createElement("a");

          fileLink.href = "#";
          fileLink.className = "file-directory-link";
          fileLink.textContent = `📄 ${entry.name}`;

          fileLink.addEventListener("click", event => {
            event.preventDefault();

            openTextFile(entry.name).catch(
              error => message(error.message)
            );
          });

          name.append(fileLink);

          const edit = document.createElement("button");

          edit.type = "button";
          edit.className = "button";
          edit.textContent = "Editar";

          edit.addEventListener("click", () => {
            openTextFile(entry.name).catch(
              error => message(error.message)
            );
          });

          actions.append(edit);
        } else {
          name.textContent = `📄 ${entry.name}`;
        }

        const download = document.createElement("button");

        download.type = "button";
        download.className = "button";
        download.textContent = "Baixar";

        download.addEventListener("click", () => {
          downloadFile(entry.name).catch(
            error => message(error.message)
          );
        });

        actions.append(download);
      }

      date.textContent =
        new Date(entry.modified_at * 1000).toLocaleString();

      const remove = document.createElement("button");

      remove.type = "button";
      remove.className = "button danger";
      remove.textContent = "Excluir";

      remove.addEventListener("click", () => {
        deleteFile(entry.name).catch(
          error => message(error.message)
        );
      });

      actions.append(remove);

      row.append(name, size, date, actions);
      body.append(row);
    });

    if (!(data.entries || []).length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");

      cell.colSpan = 4;
      cell.textContent = "Esta pasta está vazia.";

      row.append(cell);
      body.append(row);
    }

    $("file-up").disabled = filePath === ".";
  }

  function minecraftSearchContext() {
    const runtime = selectedRuntime || {};

    const version =
      runtime.version?.value ||
      runtime.version?.version ||
      runtime.minecraft_version ||
      "";

    let loader =
      runtime.loader ||
      runtime.variant ||
      "";

    loader = String(loader).toLowerCase();

    /*
     * Paper/Purpur/Spigot/Bukkit utilizam plugins.
     * Fabric/Forge/NeoForge utilizam mods.
     */
    if (
      ["paper", "purpur", "spigot", "bukkit"].includes(loader)
    ) {
      $("content-search-type").value = "plugin";
    } else if (
      ["fabric", "forge", "neoforge", "quilt"].includes(loader)
    ) {
      $("content-search-type").value = "mod";
    }

    return {
      version,
      loader,
    };
  }

  async function searchContent() {
    const searchInput = $("content-search-query");
    const status = $("content-search-status");
    const results = $("content-search-results");

    const q = searchInput.value.trim();

    if (!q) {
      message("Informe o nome de um mod ou plugin.");
      searchInput.focus();
      return;
    }

    const context = minecraftSearchContext();

    const params = new URLSearchParams({
      q,
      game: identity.game,
      version: context.version,
      loader: context.loader,
      type: $("content-search-type").value,
      limit: "20",
    });

    status.textContent = "Pesquisando no Modrinth…";
    results.replaceChildren();

    try {
      const data = await request(
        `/api/catalog/search?${params}`
      );

      renderSearchResults(
        data.entries || []
      );

      const count =
        Number(data.total_hits) || 0;

      status.textContent =
        count
          ? `${count} resultado(s) encontrado(s).`
          : "Nenhum conteúdo compatível encontrado.";

    } catch (error) {
      status.textContent =
        "Não foi possível consultar o Modrinth.";

      throw error;
    }
  }

  function renderSearchResults(entries) {
    const container =
      $("content-search-results");

    container.replaceChildren();

    entries.forEach(entry => {
      const card =
        document.createElement("article");

      card.className =
        "server-card content-search-card";

      const header =
        document.createElement("div");

      const title =
        document.createElement("strong");

      const description =
        document.createElement("small");

      const metadata =
        document.createElement("small");

      const actions =
        document.createElement("div");

      const install =
        document.createElement("button");

      title.textContent =
        entry.name ||
        entry.slug ||
        entry.id;

      description.textContent =
        entry.description ||
        "Sem descrição.";

      metadata.textContent = [
        entry.project_type,
        entry.author
          ? `por ${entry.author}`
          : null,
        Number.isFinite(entry.downloads)
          ? `${entry.downloads.toLocaleString()} downloads`
          : null,
      ]
        .filter(Boolean)
        .join(" · ");

      install.type = "button";
      install.className = "button";
      install.textContent = "Selecionar";

      install.addEventListener(
        "click",
        () => {
          selectExternalContent(entry);
        }
      );

      header.append(
        title,
        description,
        metadata,
      );

      actions.append(
        install,
      );

      card.append(
        header,
        actions,
      );

      container.append(
        card,
      );
    });

    if (!entries.length) {
      const empty =
        document.createElement("p");

      empty.textContent =
        "Nenhum mod ou plugin compatível foi encontrado.";

      container.append(
        empty,
      );
    }
  }

  function selectExternalContent(entry) {
    /*
     * Nesta etapa ainda NÃO fazemos download.
     *
     * Primeiro guardamos a escolha.
     * Na próxima etapa resolveremos:
     *
     * projeto
     *    ↓
     * versão compatível
     *    ↓
     * arquivo
     *    ↓
     * hash
     *    ↓
     * instalação
     */

    const existing =
      availableContent.find(
        item =>
          item.id === entry.id &&
          item.provider === "modrinth"
      );

    if (!existing) {
      availableContent.push({
        ...entry,
        provider: "modrinth",
        external: true,
      });
    }

    message(
      `${entry.name || entry.slug} selecionado.`
    );
  }

  function openDirectory(name) {
    if (
      !name ||
      name === "." ||
      name === ".." ||
      name.includes("/") ||
      name.includes("\\")
    ) {
      message("Nome de pasta inválido.");
      return;
    }

    closeTextFile();

    filePath =
      filePath === "."
        ? name
        : `${filePath}/${name}`;

    loadFiles().catch(
      error => message(error.message)
    );
  }

  function parentDirectory() {
    if (filePath === ".") {
      return;
    }

    closeTextFile();

    const parts = filePath.split("/");
    parts.pop();

    filePath = parts.join("/") || ".";

    loadFiles().catch(
      error => message(error.message)
    );
  }

  function instanceRelativeFile(name) {
    return filePath === "."
      ? name
      : `${filePath}/${name}`;
  }

  async function openTextFile(name) {
    const path = instanceRelativeFile(name);

    const data = await request(
      `/api/instance/file/text?${query({ path })}`
    );

    $("file-editor-path").textContent = `/${path}`;
    $("file-editor").value = data.content || "";
    $("file-editor").dataset.path = path;
    $("file-editor-panel").hidden = false;

    $("file-editor").focus();
  }

  async function saveTextFile() {
    const editor = $("file-editor");
    const path = editor.dataset.path;
    const content = editor.value;

    if (!path) {
      throw new Error("Nenhum arquivo está aberto.");
    }

    const size = new Blob([content]).size;

    const result = await request(
      "/api/instance/file/text",
      {
        method: "POST",
        body: JSON.stringify({
          ...identity,
          path,
          content,
        }),
      }
    );

    editor.dataset.size = String(size);
    message("Arquivo salvo com sucesso.");

    await loadFiles();

    return result;
  }

  function closeTextFile() {
    $("file-editor-panel").hidden = true;
    $("file-editor-path").textContent = "";
    $("file-editor").value = "";
    delete $("file-editor").dataset.path;
  }
  async function downloadFile(name){const path=filePath==="."?name:`${filePath}/${name}`,blob=await request(`/api/instance/file?${query({path})}`),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download=name;link.click();URL.revokeObjectURL(url)}
  async function deleteFile(name){if(!confirm(`Excluir ${name} permanentemente?`))return;const path=filePath==="."?name:`${filePath}/${name}`;await request("/api/instance/file/delete",{method:"POST",body:JSON.stringify({...identity,path})});message("Arquivo excluído.");await loadFiles()}
  async function uploadFile(){const file=$("file-upload").files[0];if(!file)return;const bytes=new Uint8Array(await file.arrayBuffer());let binary="";bytes.forEach(byte=>binary+=String.fromCharCode(byte));await request("/api/instance/file/upload",{method:"POST",body:JSON.stringify({...identity,path:filePath,name:file.name,content:btoa(binary)})});message("Arquivo enviado.");await loadFiles()}
  async function createDirectory() {
    const name = prompt(
      "Nome da nova pasta:"
    );

    if (name === null) {
      return;
    }

    const directoryName = name.trim();

    if (!directoryName) {
      message(
        "Informe o nome da pasta."
      );
      return;
    }

    if (
      directoryName === "." ||
      directoryName === ".." ||
      directoryName.includes("/") ||
      directoryName.includes("\\")
    ) {
      message(
        "Nome de pasta inválido."
      );
      return;
    }

    await request(
      "/api/instance/directory/create",
      {
        method: "POST",
        body: JSON.stringify({
          ...identity,
          path: filePath,
          name: directoryName,
        }),
      }
    );

    message(
      `Pasta "${directoryName}" criada.`
    );

    await loadFiles();
  }

  async function searchFiles() {
    const field = $("file-search");
    const term = field.value.trim();

    if (!term) {
      $("file-search-info").hidden = true;

      await loadFiles();

      return;
    }

    const data = await request(
      `/api/instance/files/search?${query({
        q: term,
        limit: "200"
      })}`
    );

    renderFileSearchResults(
      data.results || [],
      term
    );
  }

  function renderFileSearchResults(
    results,
    term
  ) {
    const body = $("file-list");
    const info = $("file-search-info");

    body.replaceChildren();

    info.hidden = false;
    info.textContent =
      `${results.length} resultado(s) para "${term}"`;

    $("file-path").textContent =
      "Resultados da busca";

    results.forEach(entry => {
      const row = document.createElement("tr");

      const name = document.createElement("td");
      const size = document.createElement("td");
      const date = document.createElement("td");
      const actions = document.createElement("td");

      if (entry.directory) {
        const link = document.createElement("a");

        link.href = "#";
        link.className = "file-directory-link";
        link.textContent =
          `📁 ${entry.path}`;

        link.addEventListener(
          "click",
          event => {
            event.preventDefault();

            filePath = entry.path;

            $("file-search").value = "";
            $("file-search-info").hidden = true;

            closeTextFile();

            loadFiles().catch(
              error => message(error.message)
            );
          }
        );

        name.append(link);
        size.textContent = "—";

      } else {
        if (entry.editable) {
          const link = document.createElement("a");

          link.href = "#";
          link.className = "file-directory-link";
          link.textContent =
            `📄 ${entry.path}`;

          link.addEventListener(
            "click",
            event => {
              event.preventDefault();

              openTextFileByPath(
                entry.path
              ).catch(
                error => message(error.message)
              );
            }
          );

          name.append(link);

        } else {
          name.textContent =
            `📄 ${entry.path}`;
        }

        size.textContent =
          `${entry.size || 0} B`;

        if (entry.editable) {
          const edit =
            document.createElement("button");

          edit.type = "button";
          edit.className = "button";
          edit.textContent = "Editar";

          edit.addEventListener(
            "click",
            () => {
              openTextFileByPath(
                entry.path
              ).catch(
                error => message(error.message)
              );
            }
          );

          actions.append(edit);
        }

        const download =
          document.createElement("button");

        download.type = "button";
        download.className = "button";
        download.textContent = "Baixar";

        download.addEventListener(
          "click",
          () => {
            downloadFileByPath(
              entry.path,
              entry.name
            ).catch(
              error => message(error.message)
            );
          }
        );

        actions.append(download);
      }

      date.textContent =
        new Date(
          entry.modified_at * 1000
        ).toLocaleString();

      row.append(
        name,
        size,
        date,
        actions
      );

      body.append(row);
    });

    if (!results.length) {
      const row =
        document.createElement("tr");

      const cell =
        document.createElement("td");

      cell.colSpan = 4;
      cell.textContent =
        "Nenhum arquivo ou pasta encontrado.";

      row.append(cell);
      body.append(row);
    }
  }

  async function openTextFileByPath(path) {
    const data = await request(
      `/api/instance/file/text?${query({
        path
      })}`
    );

    $("file-editor-path").textContent =
      `/${path}`;

    $("file-editor").value =
      data.content || "";

    $("file-editor").dataset.path =
      path;

    $("file-editor-panel").hidden =
      false;

    $("file-editor").focus();
  }

  async function downloadFileByPath(
    path,
    filename
  ) {
    const blob = await request(
      `/api/instance/file?${query({
        path
      })}`
    );

    const url =
      URL.createObjectURL(blob);

    const link =
      document.createElement("a");

    link.href = url;
    link.download =
      filename || path.split("/").pop();

    document.body.append(link);
    link.click();
    link.remove();

    URL.revokeObjectURL(url);
  }

  async function loadContent(){
    const game = encodeURIComponent(identity.game);
    const instance = encodeURIComponent(instancePath());

    const [runtimeData, contentData, installedData] = await Promise.all([
      request(`/api/catalog/runtimes?game=${game}`),
      request(`/api/catalog/content?game=${game}`),
      request(`/api/catalog/installed?instance=${instance}`),
    ]);

    const runtimes = Array.isArray(runtimeData)
      ? runtimeData
      : (runtimeData.runtimes || []);

    const instanceRuntime = summary.runtime_definition || {};

    selectedRuntime =
      runtimes.find(runtime => runtime.id === instanceRuntime.id) ||
      runtimes.find(runtime => runtime.variant && runtime.variant === instanceRuntime.variant) ||
      null;

    const rawContent = Array.isArray(contentData)
      ? contentData
      : (
          contentData.content ||
          contentData.entries ||
          []
        );

    availableContent = rawContent.filter(entry => {
      if (!selectedRuntime) {
        return false;
      }

      const runtimeId = selectedRuntime.id || "";

      const loader =
        selectedRuntime.loader ||
        selectedRuntime.variant ||
        "";

      const compatibleRuntimes =
        entry.runtime_ids ||
        entry.runtimes ||
        [];

      const compatibleLoaders =
        entry.loaders ||
        entry.compatible_loaders ||
        [];

      if (
        compatibleRuntimes.length &&
        compatibleRuntimes.includes(runtimeId)
      ) {
        return true;
      }

      if (
        compatibleLoaders.length &&
        compatibleLoaders.includes(loader)
      ) {
        return true;
      }

      return (
        entry.runtime_id === runtimeId ||
        entry.loader === loader ||
        entry.variant === loader
      );
    });

    installedContent = Array.isArray(installedData)
      ? installedData
      : (installedData.entries || installedData.content || []);

    renderContent();
  }
  function renderContent(){const available=$("content-available"),installed=$("content-installed");available.replaceChildren();installed.replaceChildren();availableContent.forEach(entry=>{const label=document.createElement("label");label.className="server-card";const input=document.createElement("input"),title=document.createElement("strong"),detail=document.createElement("small");input.type="checkbox";input.value=entry.id;input.addEventListener("change",()=>$("content-install").disabled=!available.querySelector("input:checked"));title.textContent=entry.name||entry.id;detail.textContent=[entry.content_type,entry.version,entry.provider].filter(Boolean).join(" · ");label.append(input,title,detail);available.append(label)});installedContent.forEach(entry=>{const row=document.createElement("div"),text=document.createElement("span"),remove=document.createElement("button"),id=entry.id||entry.content_id;text.textContent=`${entry.name||id} ${entry.version||""}`;remove.className="button danger";remove.textContent="Remover";remove.addEventListener("click",()=>removeContent(id).catch(error=>message(error.message)));row.className="file-toolbar";row.append(text,remove);installed.append(row)});if(!available.children.length)available.textContent="Nenhum conteúdo disponível.";if(!installed.children.length)installed.textContent="Nenhum conteúdo adicional instalado."}
  function contentRequest(){if(!selectedRuntime)throw new Error("Nenhum ambiente de execução disponível para este jogo.");const requirements=selectedRuntime.requirements||{};return{schema_version:2,runtime:{id:selectedRuntime.id,game:selectedRuntime.game||identity.game,version:selectedRuntime.version?.value||selectedRuntime.version?.version||"current",edition:selectedRuntime.edition||null,loader:selectedRuntime.loader||null,loader_version:selectedRuntime.loader_version||null},environment:{os:(requirements.os||[])[0]||null,architecture:(requirements.architectures||[])[0]||null,java:selectedRuntime.process?.engine==="java"?(requirements.java?.min||null):null},content:[...$("content-available").querySelectorAll("input:checked")].map(input=>input.value),installed_content:installedContent.map(entry=>entry.id||entry.content_id).filter(Boolean)}}
  async function installContent(){await request("/api/catalog/install",{method:"POST",body:JSON.stringify({instance:instancePath(),request:contentRequest()})});message("Conteúdo instalado.");await loadContent()}
  async function removeContent(contentId){if(!confirm(`Remover ${contentId} desta instância?`))return;await request("/api/catalog/remove",{method:"POST",body:JSON.stringify({instance:instancePath(),content_id:contentId})});message("Conteúdo removido.");await loadContent()}
  async function verifyContent(){await request("/api/catalog/verify",{method:"POST",body:JSON.stringify({instance:instancePath()})});message("Integridade do conteúdo verificada.")}
  async function loadBackups(){const data=await request(`/api/instance/backups?${query()}`),list=$("backup-list");list.replaceChildren();(data.backups||[]).forEach(backup=>{const row=document.createElement("div");row.className="file-toolbar";const text=document.createElement("span"),actions=document.createElement("span"),restore=document.createElement("button"),remove=document.createElement("button");text.textContent=`${backup.name} · ${backup.size} B · ${new Date(backup.created_at*1000).toLocaleString()}`;restore.className="button";restore.textContent="Restaurar";restore.addEventListener("click",()=>backupAction("restore",backup.name));remove.className="button danger";remove.textContent="Excluir";remove.addEventListener("click",()=>backupAction("delete",backup.name));actions.append(restore,remove);row.append(text,actions);list.append(row)});if(!list.children.length)list.textContent="Nenhum backup disponível."}
  async function backupAction(action,name){if(!confirm(`${action==="restore"?"Restaurar":"Excluir"} o backup ${name}?`))return;await request(`/api/instance/backup/${action}`,{method:"POST",body:JSON.stringify({...identity,name})});message(action==="restore"?"Backup restaurado.":"Backup excluído.");await loadBackups();if(action==="restore")await loadSummary()}
  async function createBackup(){await request("/api/instance/backup/create",{method:"POST",body:JSON.stringify(identity)});message("Backup criado.");await loadBackups()}
  function setDeleteProgress(value,label){const progress=$("delete-progress");progress.hidden=false;$("delete-progress-label").textContent=label;$("delete-progress-value").textContent=`${value}%`;$("delete-progress-bar").style.width=`${value}%`}
  function setDeletionBusy(busy){$("instance-delete").disabled=busy||$("delete-confirm").value!==identity.instance;$("delete-confirm").disabled=busy;$("delete-backup").disabled=busy;$("instance-delete").textContent=busy?"Exclusão em andamento…":"Excluir permanentemente"}
  async function deleteInstance(){const finalBackup=$("delete-backup").checked;let progress=0,timer=null;setDeletionBusy(true);if(finalBackup){setDeleteProgress(5,"Preparando backup final…");timer=setInterval(()=>{progress=Math.min(82,progress+7);setDeleteProgress(Math.max(5,progress),"Criando backup final antes da exclusão…")},700)}else setDeleteProgress(20,"Removendo a instância…");try{await request("/api/instance/delete",{method:"POST",body:JSON.stringify({...identity,confirmation:identity.instance,final_backup:finalBackup})});if(timer)clearInterval(timer);setDeleteProgress(100,"Instância excluída com sucesso.");message("Instância excluída. Retornando ao dashboard…");setTimeout(()=>location.href="/customer.html",500)}catch(error){if(timer)clearInterval(timer);$("delete-progress").hidden=true;message(`Não foi possível excluir a instância: ${error.message}`);setDeletionBusy(false)}}
  async function retryProvision() {
    const button =
      $("provision-retry");

    if (
      !confirm(
        "Tentar instalar novamente este servidor?"
      )
    ) {
      return;
    }

    button.disabled = true;

    const originalText =
      button.textContent;

    button.textContent =
      "Reiniciando instalação…";

    try {
      const result = await request(
        "/api/instance/provision/retry",
        {
          method: "POST",
          body: JSON.stringify(
            identity
          ),
        }
      );

      message(
        "Nova tentativa de instalação iniciada."
      );

      await loadSummary();

      return result;

    } finally {
      button.disabled = false;

      button.textContent =
        originalText;
    }
  }
  document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{document.querySelectorAll("[data-view]").forEach(item=>item.classList.toggle("active",item===button));document.querySelectorAll(".view").forEach(view=>view.classList.toggle("active",view.id===`view-${button.dataset.view}`));if(button.dataset.view==="files")loadFiles().catch(error=>message(error.message));if(button.dataset.view==="content")loadContent().catch(error=>message(error.message));if(button.dataset.view==="backups")loadBackups().catch(error=>message(error.message))}));
  $("instance-start").addEventListener("click",()=>control("start").catch(error=>message(error.message)));$("instance-restart").addEventListener("click",()=>control("restart").catch(error=>message(error.message)));$("instance-stop").addEventListener("click",()=>control("stop").catch(error=>message(error.message)));$("config-file").addEventListener("change",()=>loadConfig().catch(error=>message(error.message)));$("config-save").addEventListener("click",()=>saveConfig().catch(error=>message(error.message)));$("file-upload").addEventListener("change",()=>uploadFile().catch(error=>message(error.message)));$("file-create-directory").addEventListener("click",()=>createDirectory().catch(error=>message(error.message)));$("file-search-button").addEventListener("click",()=>searchFiles().catch(error=>message(error.message)));$("file-search").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();searchFiles().catch(error=>message(error.message))}});$("file-search").addEventListener("search",()=>{if(!$("file-search").value){$("file-search-info").hidden=true;loadFiles().catch(error=>message(error.message))}});$("file-up").addEventListener("click",parentDirectory);$("file-editor-save").addEventListener("click",()=>saveTextFile().catch(error=>message(error.message)));$("file-editor-close").addEventListener("click",closeTextFile);$("content-install").addEventListener("click",()=>installContent().catch(error=>message(error.message)));$("content-verify").addEventListener("click",()=>verifyContent().catch(error=>message(error.message)));$("backup-create").addEventListener("click",()=>createBackup().catch(error=>message(error.message)));$("delete-confirm-label").textContent=identity.instance||"";$("delete-confirm").addEventListener("input",()=>{if(!$("delete-confirm").disabled)$("instance-delete").disabled=$("delete-confirm").value!==identity.instance});$("customer-logout").addEventListener("click",()=>{sessionStorage.removeItem("dsm_auth");location.href="/login.html"});
  $("content-search-button").addEventListener(
    "click",
    () =>
      searchContent().catch(
        error => message(error.message)
      )
  );

  $("content-search-query").addEventListener(
    "keydown",
    event => {
      if (event.key === "Enter") {
        event.preventDefault();

        searchContent().catch(
          error => message(error.message)
        );
      }
    }
  );

  $("provision-retry").addEventListener(
    "click",
    () => retryProvision().catch(
      error => message(
        `Não foi possível reiniciar a instalação: ${error.message}`
      )
    )
  );

  /*
   * Polling adaptativo do estado da instância.
   *
   * Durante o provisionamento consultamos o estado
   * a cada 2 segundos. Em estado estável, a cada
   * 10 segundos.
   */
  async function scheduleSummaryRefresh() {
    let delay = 10000;

    try {
      await loadSummary();

      const status = String(
        summary?.provision?.status || ""
      ).toLowerCase();

      if (
        [
          "queued",
          "provisioning",
          "pending_steam_auth",
        ].includes(status)
      ) {
        delay = 2000;
      }
    } catch {
      /*
       * Uma falha temporária não interrompe o polling.
       */
    }

    window.setTimeout(
      scheduleSummaryRefresh,
      delay
    );
  }

  if (
    !auth()
    || !identity.server
    || !identity.game
    || !identity.instance
  ) {
    location.href =
      auth()
        ? "/customer.html"
        : "/login.html";
  } else {
    /*
     * scheduleSummaryRefresh() já executa loadSummary()
     * imediatamente. Portanto, evitamos uma segunda
     * chamada simultânea durante a inicialização.
     */
    loadConfigs().catch(
      error => message(error.message)
    );

    loadLogs();

    window.setInterval(
      loadLogs,
      2000
    );

    scheduleSummaryRefresh();
  }

})();
