(()=>{"use strict";const $=id=>document.getElementById(id),q=new URLSearchParams(location.search),iid=q.get("instance")||q.get("instance_id")||"";let overview=null,permissions=new Set(),filePath=".",filePathAccess="read_only";const api="/api/customer/instance/workspace";
function customerHeaders(body=false){const headers={Accept:"application/json","X-Capivara-Auth-Area":"customer"};if(body)headers["Content-Type"]="application/json";return headers}
async function request(path,options={}){const headers={...customerHeaders(!!options.body),...(options.headers||{})};const r=await fetch(path,{...options,headers,credentials:"same-origin",cache:options.cache||"no-store"});if(r.status===401){location.href="/customer-login.html";throw new Error("Sessão encerrada")};const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.message||data.error||`HTTP ${r.status}`);return data}
function toast(text){const n=$("toast");n.textContent=text;n.classList.add("show");clearTimeout(toast.t);toast.t=setTimeout(()=>n.classList.remove("show"),3500)}function fmtBytes(v){const n=Number(v||0);if(!n)return "0 B";const u=["B","KB","MB","GB","TB"],i=Math.min(u.length-1,Math.floor(Math.log(n)/Math.log(1024)));return `${(n/1024**i).toLocaleString("pt-BR",{maximumFractionDigits:1})} ${u[i]}`}
let consolePollTimer=null;
function stopConsolePolling(){
    if(consolePollTimer!==null){
        clearInterval(consolePollTimer);
        consolePollTimer=null;
    }
}
function startConsolePolling(){
    stopConsolePolling();
    loadConsole().catch(()=>{});
    consolePollTimer=setInterval(()=>{
        if(document.visibilityState==="visible"){
            loadConsole().catch(()=>{});
        }
    },3000);
}
function can(p){return permissions.has(p)}
function setView(name){
    document.querySelectorAll("[data-view]").forEach(b=>b.classList.toggle("active",b.dataset.view===name));
    document.querySelectorAll(".view").forEach(v=>v.classList.toggle("active",v.id===`view-${name}`));
    if(name==="console")startConsolePolling();
    else stopConsolePolling();
    if(name==="startup")loadStartup();
    if(name==="files")loadFiles().catch(e=>toast(e.message));
    if(name==="backups")loadBackups();
    if(name==="team")loadTeam();
    if(name==="upgrade")loadUpgrade();
}
function telemetryNumber(value){
    if(value===null||value===undefined||value==="")return null;
    const n=Number(value);
    return Number.isFinite(n)?n:null;
}

function telemetryTime(value){
    const d=new Date(value);
    if(Number.isNaN(d.getTime()))return "";
    return d.toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"});
}

function telemetryStats(values){
    const nums=values.filter(v=>Number.isFinite(v));
    if(!nums.length)return null;
    return {
        current:nums[nums.length-1],
        average:nums.reduce((a,b)=>a+b,0)/nums.length,
        peak:Math.max(...nums),
    };
}

function drawTelemetry(canvas,series,options={}){
    const dpr=window.devicePixelRatio||1;
    const cssWidth=Math.max(1,canvas.clientWidth);
    const cssHeight=Math.max(1,canvas.clientHeight);

    canvas.width=Math.round(cssWidth*dpr);
    canvas.height=Math.round(cssHeight*dpr);

    const ctx=canvas.getContext("2d");
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,cssWidth,cssHeight);

    const left=48,right=12,top=32,bottom=26;
    const plotWidth=Math.max(1,cssWidth-left-right);
    const plotHeight=Math.max(1,cssHeight-top-bottom);

    const allValues=series.flatMap(item=>
        item.values.filter(v=>Number.isFinite(v))
    );

    if(!allValues.length){
        ctx.fillStyle="#8d9aaf";
        ctx.font="12px sans-serif";
        ctx.textAlign="center";
        ctx.textBaseline="middle";
        ctx.fillText(
            options.emptyLabel||"Sem telemetria disponível",
            cssWidth/2,
            cssHeight/2
        );
        return;
    }

    let min=options.min??0;
    let max=options.max;

    if(max===undefined||max===null){
        max=Math.max(...allValues);
        max=max<=0?1:max*1.08;
    }

    if(max<=min)max=min+1;

    ctx.font="10px sans-serif";
    ctx.lineWidth=1;

    for(let i=0;i<=4;i++){
        const ratio=i/4;
        const y=top+plotHeight*ratio;
        const value=max-(max-min)*ratio;

        ctx.strokeStyle="#263246";
        ctx.beginPath();
        ctx.moveTo(left,y);
        ctx.lineTo(cssWidth-right,y);
        ctx.stroke();

        ctx.fillStyle="#8d9aaf";
        ctx.textAlign="right";
        ctx.textBaseline="middle";
        ctx.fillText(
            options.formatAxis?options.formatAxis(value):value.toFixed(0),
            left-6,
            y
        );
    }

    const pointCount=Math.max(...series.map(x=>x.values.length));

    series.forEach((item,index)=>{
        ctx.strokeStyle=item.color||["#6f9cff","#39d06f","#f59e42"][index%3];
        ctx.lineWidth=1.7;
        ctx.beginPath();

        let drawing=false;

        item.values.forEach((value,i)=>{
            if(!Number.isFinite(value)){
                drawing=false;
                return;
            }

            const x=left+(i/Math.max(1,pointCount-1))*plotWidth;
            const y=top+plotHeight-
                ((value-min)/(max-min))*plotHeight;

            if(!drawing){
                ctx.moveTo(x,y);
                drawing=true;
            }else{
                ctx.lineTo(x,y);
            }
        });

        ctx.stroke();
    });

    if(Number.isFinite(options.reference)){
        const value=options.reference;
        if(value>=min&&value<=max){
            const y=top+plotHeight-
                ((value-min)/(max-min))*plotHeight;

            ctx.save();
            ctx.setLineDash([5,4]);
            ctx.strokeStyle="#8d9aaf";
            ctx.beginPath();
            ctx.moveTo(left,y);
            ctx.lineTo(cssWidth-right,y);
            ctx.stroke();
            ctx.restore();
        }
    }

    if(options.summary){
        ctx.fillStyle="#eef3fb";
        ctx.font="11px sans-serif";
        ctx.textAlign="right";
        ctx.textBaseline="top";
        ctx.fillText(options.summary,cssWidth-right,5);
    }

    if(options.times?.length){
        ctx.fillStyle="#8d9aaf";
        ctx.font="10px sans-serif";
        ctx.textBaseline="bottom";

        ctx.textAlign="left";
        ctx.fillText(
            telemetryTime(options.times[0]),
            left,
            cssHeight-2
        );

        ctx.textAlign="right";
        ctx.fillText(
            telemetryTime(options.times[options.times.length-1]),
            cssWidth-right,
            cssHeight-2
        );
    }

    if(series.length>1){
        let x=left;
        series.forEach(item=>{
            ctx.fillStyle=item.color||"#eef3fb";
            ctx.fillRect(x,7,8,2);

            ctx.fillStyle="#8d9aaf";
            ctx.font="10px sans-serif";
            ctx.textAlign="left";
            ctx.textBaseline="middle";
            ctx.fillText(item.label,x+12,8);

            x+=ctx.measureText(item.label).width+34;
        });
    }
}

function networkRates(samples,key){
    return samples.map((sample,index)=>{
        if(index===0)return null;

        const current=telemetryNumber(sample[key]);
        const previous=telemetryNumber(samples[index-1][key]);

        if(current===null||previous===null||current<previous)return null;

        const now=new Date(sample.sampled_at).getTime();
        const before=new Date(samples[index-1].sampled_at).getTime();
        const seconds=(now-before)/1000;

        if(!Number.isFinite(seconds)||seconds<=0)return null;

        return (current-previous)/seconds;
    });
}

async function loadTelemetry(){
    const d=await request(
        `${api}/telemetry?instance_id=${encodeURIComponent(iid)}&limit=120`
    );

    /*
     * Repository returns newest first. Charts must run oldest -> newest.
     */
    const samples=[...(d.samples||[])].sort(
        (a,b)=>new Date(a.sampled_at).getTime()-new Date(b.sampled_at).getTime()
    );
    const times=samples.map(x=>x.sampled_at);

    const cpuRaw=samples.map(x=>telemetryNumber(x.cpu_percent));
    const cpuLimit=telemetryNumber(overview?.policy?.cpu_limit_cores);

    const cpu=samples.map(x=>{
        const raw=telemetryNumber(x.cpu_percent);
        if(raw===null)return null;
        return cpuLimit&&cpuLimit>0?raw/cpuLimit:raw;
    });

    const cpuStats=telemetryStats(cpu);
    const cpuRawStats=telemetryStats(cpuRaw);

    drawTelemetry(
        $("cpu-chart"),
        [{label:"CPU",values:cpu,color:"#6f9cff"}],
        {
            min:0,
            max:100,
            times,
            formatAxis:v=>`${Math.round(v)}%`,
            summary:cpuStats
                ? cpuLimit&&cpuRawStats
                    ? `Atual ${cpuStats.current.toFixed(1)}% · ${(cpuRawStats.current/100).toFixed(2)} / ${cpuLimit} cores · Pico ${cpuStats.peak.toFixed(1)}%`
                    : `Atual ${cpuStats.current.toFixed(1)}% · Média ${cpuStats.average.toFixed(1)}% · Pico ${cpuStats.peak.toFixed(1)}%`
                : null,
            emptyLabel:"Sem telemetria de CPU",
        }
    );

    const memoryBytes=samples.map(x=>telemetryNumber(x.memory_bytes));
    const memoryLimitBytes=telemetryNumber(
        overview?.policy?.memory_limit_bytes
    );

    const memory=samples.map(x=>{
        const bytes=telemetryNumber(x.memory_bytes);
        if(bytes===null)return null;
        if(memoryLimitBytes&&memoryLimitBytes>0){
            return bytes/memoryLimitBytes*100;
        }
        return null;
    });

    const memoryStats=telemetryStats(memory);
    const memoryBytesStats=telemetryStats(memoryBytes);

    drawTelemetry(
        $("memory-chart"),
        [{label:"Memória",values:memory,color:"#6f9cff"}],
        {
            min:0,
            max:100,
            times,
            formatAxis:v=>`${Math.round(v)}%`,
            summary:memoryStats&&memoryBytesStats&&memoryLimitBytes
                ? `Atual ${(memoryBytesStats.current/1024/1024/1024).toFixed(2)} / ${(memoryLimitBytes/1024/1024/1024).toFixed(2)} GiB · ${memoryStats.current.toFixed(1)}% · Pico ${memoryStats.peak.toFixed(1)}%`
                : null,
            emptyLabel:"Sem telemetria de memória",
        }
    );

    const rx=networkRates(samples,"network_rx_bytes");
    const tx=networkRates(samples,"network_tx_bytes");
    const networkValues=[...rx,...tx].filter(Number.isFinite);
    const latestRx=[...rx].reverse().find(Number.isFinite);
    const latestTx=[...tx].reverse().find(Number.isFinite);

    drawTelemetry(
        $("network-chart"),
        [
            {label:"RX",values:rx,color:"#39d06f"},
            {label:"TX",values:tx,color:"#6f9cff"},
        ],
        {
            min:0,
            times,
            formatAxis:v=>`${fmtBytes(v)}/s`,
            summary:networkValues.length
                ? `RX ${fmtBytes(latestRx||0)}/s · TX ${fmtBytes(latestTx||0)}/s`
                : null,
            emptyLabel:"Telemetria de rede não disponível",
        }
    );
}

async function retryProvision(){const button=$("provision-retry");if(!button)throw new Error("A ação de retry não está disponível nesta página.");if(!confirm("Tentar instalar novamente este servidor?"))return;button.disabled=true;const originalText=button.textContent;button.textContent="Reiniciando instalação…";try{const result=await request("/api/instance/provision/retry",{method:"POST",body:JSON.stringify({instance_id:iid})});toast("Nova tentativa de instalação iniciada.");await loadOverview();return result}finally{button.disabled=false;button.textContent=originalText}}
async function loadOverview(){overview=await request(`${api}?instance_id=${encodeURIComponent(iid)}`);permissions=new Set(overview.permissions||[]);const inst=overview.instance||{},t=overview.telemetry||{},loc=overview.location||{},storage=overview.storage||{};$("title").textContent=inst.name||iid;$("game").textContent=String(inst.game_id||"").toUpperCase();$("state").textContent=inst.status||"desconhecido";$("state").className=`state ${["running","online"].includes(String(inst.status).toLowerCase())?"ok":""}`;$("health").textContent=t.health||"—";$("players").textContent=`${t.players_online??0} / ${t.players_max??overview.policy?.player_limit??"—"}`;$("latency").textContent=t.latency_ms!=null?`${Number(t.latency_ms).toFixed(0)} ms`:"—";$("location").textContent=[loc.city,loc.region_name,loc.country_code||loc.region_country_code].filter(Boolean).join(" · ")||"—";$("ports").replaceChildren(...(overview.ports||[]).map(p=>{const d=document.createElement("div");d.className="row";d.innerHTML=`<span>${p.name||p.protocol}</span><strong>${p.port}/${p.protocol||"udp"}</strong>`;return d}));$("storage-label").textContent=`${fmtBytes(storage.used_bytes)} / ${fmtBytes(storage.limit_bytes)}`;$("storage-bar").style.width=`${Math.min(100,Number(storage.percent||0))}%`;const pr=overview.provision;$("provision").classList.toggle("hidden",!pr);const retryActions=$("provision-failed-actions");if(retryActions)retryActions.classList.add("hidden");if(pr){const provisionStatus=String(pr.status||"").toLowerCase();const progress=Math.min(100,Number(pr.progress||0));$("provision-text").textContent=`${pr.message||pr.stage||"Instalando"} · ${progress}%`;$("provision-bar").style.width=`${progress}%`;const retryable=provisionStatus==="failed"||provisionStatus==="pending_steam_auth";$("provision").classList.toggle("error",retryable);if(retryActions&&retryable&&can("instance.provision.retry"))retryActions.classList.remove("hidden")};$("console-command-wrap").classList.toggle("hidden",!can("console.execute"));$("content-tab").classList.toggle("hidden",!(overview.content_sections||[]).length);$("team-tab").classList.toggle("hidden",!can("team.read"));$("upgrade-tab").classList.toggle("hidden",!can("contract.read"));const runtimeState=String(inst.status||"").toLowerCase();
const running=["running","online"].includes(runtimeState);
const stopped=["stopped","offline","inactive"].includes(runtimeState);
const transitioning=["starting","stopping","restarting","pending"].includes(runtimeState);
const locked=!!pr||transitioning;

$("start").disabled=!can("instance.start")||locked||running;
$("stop").disabled=!can("instance.stop")||locked||stopped;
$("restart").disabled=!can("instance.restart")||locked||!running;renderContent();await loadTelemetry()}
function setLifecycleBusy(action,busy){
    const labels={start:"Start",stop:"Stop",restart:"Restart"};
    const busyLabels={start:"Iniciando…",stop:"Parando…",restart:"Reiniciando…"};
    for(const name of ["start","stop","restart"]){
        const button=$(name);
        if(!button)continue;
        button.disabled=busy||!can(`instance.${name}`);
        button.classList.toggle("busy",busy&&name===action);
        button.textContent=busy&&name===action?busyLabels[name]:labels[name];
    }
}

async function control(action){
    if(!can(`instance.${action}`)&&action!=="restart")return;
    setLifecycleBusy(action,true);
    try{
        await request(`/api/instance/${action}`,{
            method:"POST",
            body:JSON.stringify({
                server:q.get("server"),
                game:q.get("game"),
                instance:iid
            })
        });
        toast(`${action==="start"?"Inicialização":action==="stop"?"Parada":"Reinicialização"} concluída.`);
        await loadOverview();
    }catch(error){
        toast(error.message||`Falha ao executar ${action}.`);
        throw error;
    }finally{
        setLifecycleBusy(action,false);
    }
}
window.addEventListener("beforeunload",stopConsolePolling);
async function loadConsole(){if(!can("console.read")){$("console-output").textContent="Você não possui permissão para visualizar o console.";return}const d=await request(`${api}/console?instance_id=${encodeURIComponent(iid)}&limit=400`);$("console-output").textContent=(d.lines||[]).map(x=>x.line||"").join("\n")||"Nenhuma saída disponível.";$("console-output").scrollTop=$("console-output").scrollHeight}
async function sendConsole(){if(!can("console.execute"))return;const input=$("console-command"),cmd=input.value.trim();if(!cmd)return;await request(`${api}/console`,{method:"POST",body:JSON.stringify({instance_id:iid,command:cmd})});input.value="";toast("Comando enviado ao servidor de jogo.");setTimeout(loadConsole,1000)}
async function loadStartup(){if(!can("startup.read"))return;const d=await request(`${api}/startup?instance_id=${encodeURIComponent(iid)}`),box=$("startup-fields");box.replaceChildren();Object.entries(d.declaration||{}).forEach(([key,spec])=>{const label=document.createElement("label");label.textContent=key;let input;if(spec.type==="select"){input=document.createElement("select");(spec.allowed||[]).forEach(v=>input.append(new Option(v,v)))}else if(spec.type==="boolean"){input=document.createElement("select");input.append(new Option("Sim","true"),new Option("Não","false"))}else{input=document.createElement("input");input.type=spec.type==="integer"?"number":"text"}input.dataset.key=key;input.value=String((d.values||{})[key]??"");input.disabled=!can("startup.write");label.append(input);box.append(label)});$("startup-save").disabled=!can("startup.write")}
async function saveStartup(){const values={};document.querySelectorAll("#startup-fields [data-key]").forEach(n=>{let v=n.value;if(v==="true"||v==="false")v=v==="true";else if(n.type==="number")v=Number(v);values[n.dataset.key]=v});await request(`${api}/startup`,{method:"PATCH",body:JSON.stringify({instance_id:iid,values})});toast("Parâmetros de inicialização salvos.")}
async function fileCommand(action,path=filePath,target_path=null,payload={}){const d=await request(`${api}/files`,{method:"POST",body:JSON.stringify({instance_id:iid,action,path,target_path,payload})});for(let i=0;i<30;i++){await new Promise(r=>setTimeout(r,400));const s=await request(`${api}/files/status?instance_id=${encodeURIComponent(iid)}&command_id=${encodeURIComponent(d.command_id)}`);if(["completed","failed"].includes(s.status)){if(s.status==="failed")throw new Error(s.last_error||"Falha na operação de arquivo");return s.result||s}}throw new Error("Operação ainda está em processamento")}
async function loadFiles(){
    if(!can("files.read"))return;

    const result=await fileCommand("list",filePath);
    const entries=result.entries||result.files||[];

    filePathAccess=String(result.access||"read_only");
    $("file-path").textContent=filePath;

    const accessBadge=$("file-access-badge");
    if(accessBadge){
        const readOnly=filePathAccess!=="read_write";
        accessBadge.textContent=readOnly?"Somente leitura":"Leitura e escrita";
        accessBadge.classList.toggle("readonly",readOnly);
        accessBadge.classList.remove("hidden");
    }

    const currentWritable=filePathAccess==="read_write";
    $("file-mkdir").disabled=!currentWritable||!can("files.upload");
    $("file-upload").disabled=!currentWritable||!can("files.upload");

    const body=$("file-body");
    body.replaceChildren();

    entries.forEach(item=>{
        const tr=document.createElement("tr");
        const name=document.createElement("td");
        const size=document.createElement("td");
        const actions=document.createElement("td");

        name.textContent=item.name;
        size.textContent=item.directory?"—":fmtBytes(item.size);

        const open=document.createElement("button");
        open.className="btn";
        open.textContent=item.directory?"Abrir":"Visualizar";

        open.onclick=async()=>{
            const p=filePath==="."?item.name:`${filePath}/${item.name}`;

            if(item.directory){
                filePath=p;
                loadFiles().catch(e=>toast(e.message));
                return;
            }

            if(can("files.read")){
                const r=await fileCommand("read_text",p);
                $("file-editor-path").textContent=p;
                $("file-editor").value=r.content||"";

                const writable=item.access==="read_write";
                $("file-editor").readOnly=!writable;
                $("file-editor-save").classList.toggle(
                    "hidden",
                    !writable||!can("files.edit")
                );
                $("file-editor-wrap").classList.remove("hidden");
            }
        };

        actions.append(open);

        if(item.access==="read_write"&&can("files.delete")){
            const del=document.createElement("button");
            del.className="btn danger";
            del.textContent="Excluir";

            del.onclick=async()=>{
                if(confirm(`Excluir ${item.name}?`)){
                    await fileCommand(
                        "delete",
                        filePath==="."?item.name:`${filePath}/${item.name}`
                    );
                    loadFiles().catch(e=>toast(e.message));
                }
            };

            actions.append(del);
        }

        tr.append(name,size,actions);
        body.append(tr);
    });

    const usage=await fileCommand("usage",".");
    const used=Number(usage.usage_bytes??usage.used_bytes??0);
    const limit=Number(
        usage.limit_bytes??
        overview?.storage?.limit_bytes??
        0
    );

    $("files-storage-label").textContent=
        `${fmtBytes(used)} / ${limit?fmtBytes(limit):"Sem limite definido"}`;

    const pct=Number(
        usage.percent??
        (limit>0?(used/limit*100):0)
    );

    $("files-storage-bar").style.width=
        `${Math.min(100,Math.max(0,pct))}%`;


}
async function saveFile(){if($("file-editor").readOnly){toast("Esta área é somente leitura.");return}await fileCommand("write_text",$("file-editor-path").textContent,null,{content:$("file-editor").value});toast("Arquivo salvo.");$("file-editor-wrap").classList.add("hidden")}
async function mkdir(){if(filePathAccess!=="read_write"){toast("Esta área é somente leitura.");return}const name=prompt("Nome do novo diretório:");if(!name)return;const clean=name.trim();if(!clean)return;const path=filePath==="."?clean:`${filePath}/${clean}`;await fileCommand("mkdir",path);toast("Pasta criada.");loadFiles().catch(e=>toast(e.message))}
async function upload(){if(filePathAccess!=="read_write"){toast("Esta área é somente leitura.");$("file-upload").value="";return}const f=$("file-upload").files[0];if(!f)return;const b64=await new Promise((res,rej)=>{const r=new FileReader;r.onload=()=>res(String(r.result).split(",")[1]);r.onerror=rej;r.readAsDataURL(f)});await fileCommand("upload",filePath==="."?f.name:`${filePath}/${f.name}`,null,{content_base64:b64});toast("Upload concluído.");loadFiles()}
function renderContent(){const box=$("content-body");if(!box)return;box.replaceChildren();const sections=overview?.content_sections||[];if(!sections.length){box.textContent="Este contrato não permite mods, plugins ou Workshop.";return}sections.forEach(s=>{const d=document.createElement("div");d.className="card";d.innerHTML=`<h3>${s[0].toUpperCase()+s.slice(1)}</h3><p class=muted>Disponível conforme o runtime e o contrato desta instância.</p>`;box.append(d)})}
async function loadBackups(){if(!can("backup.read"))return;const [jobs,policy]=await Promise.all([request(`${api}/backups?instance_id=${encodeURIComponent(iid)}`),request(`${api}/backup-policy?instance_id=${encodeURIComponent(iid)}`)]);$("backup-time").value=policy.schedule_time||"04:00";$("backup-zone").value=policy.schedule_timezone||"UTC";$("backup-enabled").checked=policy.enabled!==false;$("backup-save").disabled=!can("backup.create");$("backup-create").disabled=!can("backup.create");const list=$("backup-list");list.replaceChildren();const completed=(jobs.jobs||[]).filter(x=>x.action==="create"&&x.status==="completed").slice(0,1);if(!completed.length){list.textContent="Nenhum backup operacional disponível.";return}completed.forEach(job=>{const d=document.createElement("div");d.className="row";const meta=document.createElement("span");meta.textContent=`${job.backup_id||"backup"} · ${fmtBytes(job.size_bytes)}`;const actions=document.createElement("span");if(can("backup.restore")){const b=document.createElement("button");b.className="btn";b.textContent="Restaurar";b.onclick=()=>backupAction("restore",job.backup_id);actions.append(b)}if(can("backup.delete")){const b=document.createElement("button");b.className="btn danger";b.textContent="Excluir";b.onclick=()=>backupAction("delete",job.backup_id);actions.append(b)}d.append(meta,actions);list.append(d)})}
async function backupAction(action,backup_id=null){await request(`${api}/backups`,{method:"POST",body:JSON.stringify({instance_id:iid,action,backup_id})});toast(`Backup: ${action} solicitado.`);setTimeout(loadBackups,1000)}async function saveBackupPolicy(){await request(`${api}/backup-policy`,{method:"PATCH",body:JSON.stringify({instance_id:iid,enabled:$("backup-enabled").checked,schedule_time:$("backup-time").value,schedule_timezone:$("backup-zone").value})});toast("Agenda de backup atualizada.")}
const permissionLabels={"instance.view":"Visualizar servidor","instance.start":"Start","instance.stop":"Stop","instance.restart":"Restart","instance.delete":"Excluir servidor","console.read":"Visualizar console","console.execute":"Enviar comandos no console","files.read":"Visualizar arquivos","files.download":"Download de arquivos","files.upload":"Enviar/criar arquivos","files.edit":"Editar arquivos","files.delete":"Excluir arquivos","files.move":"Mover/renomear arquivos","files.extract":"Descompactar arquivos","backup.read":"Visualizar backups","backup.create":"Criar backup","backup.download":"Baixar backup","backup.restore":"Restaurar backup","backup.delete":"Excluir backup","startup.read":"Visualizar inicialização","startup.write":"Alterar inicialização","content.read":"Visualizar conteúdo","content.install":"Instalar mods/plugins","content.remove":"Remover mods/plugins","team.read":"Visualizar equipe","team.manage":"Administrar equipe","contract.read":"Visualizar plano","contract.upgrade":"Solicitar upgrade"};
function permissionForm(container,grants={}){container.replaceChildren();Object.keys(permissionLabels).forEach(p=>{const l=document.createElement("label"),c=document.createElement("input");c.type="checkbox";c.dataset.permission=p;c.checked=!!grants[p];l.append(c,document.createTextNode(permissionLabels[p]));container.append(l)})}
async function loadTeam(){if(!can("team.read"))return;const d=await request(`/api/customer/instance/workspace/team?instance_id=${encodeURIComponent(iid)}`),list=$("team-list");list.replaceChildren();(d.members||[]).forEach(m=>{const row=document.createElement("div");row.className="row";const t=document.createElement("span");t.textContent=`${m.email||m.username} · ${m.account_role}`;const edit=document.createElement("button");edit.className="btn";edit.textContent="Permissões";edit.onclick=()=>openGrants(m);row.append(t,edit);list.append(row)});$("team-invite-card").classList.toggle("hidden",!can("team.manage"))}
function selectedGrants(){const r={};document.querySelectorAll("#permission-grid [data-permission]").forEach(c=>r[c.dataset.permission]=c.checked);return r}function openGrants(member){$("team-user").value=member.username;$("team-email").value=member.email||"";permissionForm($("permission-grid"),member.grants||{});$("team-modal").classList.remove("hidden")}
async function inviteTeam(){await request("/api/customer/instance/workspace/team/invite",{method:"POST",body:JSON.stringify({instance_id:iid,email:$("invite-email").value,grants:selectedGrants()})});toast("Usuário adicionado à equipe.");$("team-modal").classList.add("hidden");loadTeam()}async function saveGrants(){await request("/api/customer/instance/workspace/team/grants",{method:"PATCH",body:JSON.stringify({instance_id:iid,username:$("team-user").value,grants:selectedGrants()})});toast("Permissões atualizadas.");$("team-modal").classList.add("hidden");loadTeam()}async function removeTeam(){if(!confirm("Remover o acesso deste usuário à instância? A conta dele será preservada."))return;await request("/api/customer/instance/workspace/team/remove",{method:"POST",body:JSON.stringify({instance_id:iid,username:$("team-user").value})});$("team-modal").classList.add("hidden");toast("Acesso removido; identidade preservada.");loadTeam()}
async function loadUpgrade(){if(!can("contract.read"))return;const d=await request(`${api}/upgrade-options?instance_id=${encodeURIComponent(iid)}`),box=$("upgrade-list");box.replaceChildren();(d.profiles||[]).forEach(p=>{const c=document.createElement("div");c.className=`card upgrade-card ${p.current?"current":""}`;c.innerHTML=`<h3>${p.name||p.id}</h3><p>${p.cpu_cores||"—"} CPU · ${Number(p.memory_mb||0)/1024} GB RAM · ${Number(p.storage_mb||0)/1024} GB storage</p>`;if(p.upgrade&&can("contract.upgrade")){const b=document.createElement("button");b.className="btn primary";b.textContent="Selecionar upgrade";b.onclick=async()=>{await request(`${api}/upgrade`,{method:"POST",body:JSON.stringify({instance_id:iid,profile_id:p.id})});toast("Solicitação enviada ao Billing.")};c.append(b)}box.append(c)})}
async function logout(){try{await fetch("/api/customer/auth/logout",{method:"POST",headers:customerHeaders(false),credentials:"same-origin",cache:"no-store"})}finally{location.href="/customer-login.html"}}
function wire(){document.querySelectorAll("[data-view]").forEach(b=>b.onclick=()=>setView(b.dataset.view));$("start").onclick=()=>control("start");$("stop").onclick=()=>control("stop");$("restart").onclick=()=>control("restart");$("console-send").onclick=sendConsole;$("console-command").onkeydown=e=>{if(e.key==="Enter")sendConsole()};$("startup-save").onclick=saveStartup;$("file-up").onclick=()=>{if(filePath!=="."){const a=filePath.split("/");a.pop();filePath=a.join("/")||".";loadFiles()}};$("file-mkdir").onclick=mkdir;$("file-upload").onchange=upload;$("file-editor-save").onclick=saveFile;$("file-editor-close").onclick=()=>$("file-editor-wrap").classList.add("hidden");$("backup-create").onclick=()=>backupAction("create");$("backup-save").onclick=saveBackupPolicy;$("invite-open").onclick=()=>{$("team-user").value="";$("team-email").value="";permissionForm($("permission-grid"),{});$("team-modal").classList.remove("hidden")};$("team-save").onclick=()=>$("team-user").value?saveGrants():inviteTeam();$("team-remove").onclick=removeTeam;$("team-close").onclick=()=>$("team-modal").classList.add("hidden");$("logout").onclick=logout;const retry=$("provision-retry");if(retry)retry.onclick=()=>retryProvision().catch(e=>toast(`Não foi possível reiniciar a instalação: ${e.message}`))}
if(!iid){document.body.textContent="Instância não informada.";return}wire();loadOverview().catch(e=>toast(e.message));setInterval(()=>{if(document.visibilityState==="visible")loadOverview().catch(()=>{})},15000)})();