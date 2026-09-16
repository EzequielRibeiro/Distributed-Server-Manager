(()=>{
"use strict";

const params=new URLSearchParams(location.search);
const controllerMode=location.pathname.endsWith("/controller-instance.html")||params.get("auth_area")==="controller";
if(!controllerMode)return;

window.CAPIVARA_INSTANCE_AUTH_AREA="controller";

const nativeFetch=window.fetch.bind(window);
window.fetch=async function(input,init={}){
    const options={...init};
    const sourceHeaders=options.headers||(input instanceof Request?input.headers:undefined);
    const headers=new Headers(sourceHeaders||{});
    headers.set("X-Capivara-Auth-Area","controller");
    options.headers=headers;
    const response=await nativeFetch(input,options);
    if(response.status===401){
        location.replace("/login.html");
        return new Promise(()=>{});
    }
    return response;
};

function timezoneOffset(zone){
    try{
        const parts=new Intl.DateTimeFormat("en-US",{timeZone:zone,timeZoneName:"longOffset",hour:"2-digit"}).formatToParts(new Date());
        const raw=parts.find(part=>part.type==="timeZoneName")?.value||"GMT";
        if(/^(GMT|UTC)$/i.test(raw))return"UTC+00:00";
        const match=raw.match(/(?:GMT|UTC)([+-])(\d{1,2})(?::?(\d{2}))?/i);
        if(match)return`UTC${match[1]==="-"?"−":"+"}${String(match[2]).padStart(2,"0")}:${String(match[3]||"00").padStart(2,"0")}`;
    }catch(_){ }
    return"UTC";
}
function timezoneLabel(zone){
    const value=String(zone||"UTC");
    if(value==="UTC"||value==="Etc/UTC")return`UTC (${timezoneOffset("UTC")})`;
    const city=(value.split("/").pop()||value).replaceAll("_"," ");
    return`${city} (${timezoneOffset(value)}) · ${value}`;
}
function installTimezoneSelector(){
    const input=document.getElementById("backup-zone");
    if(!input||input.tagName==="SELECT")return;
    let detected="UTC";
    try{detected=Intl.DateTimeFormat().resolvedOptions().timeZone||"UTC"}catch(_){ }
    let zones=[];
    try{if(typeof Intl.supportedValuesOf==="function")zones=Intl.supportedValuesOf("timeZone")||[]}catch(_){ }
    const select=document.createElement("select");
    select.id=input.id;select.className=input.className;select.name=input.name;
    const initial=String(input.value||"UTC");
    const ordered=[...new Set(["UTC",detected,initial,...zones].filter(Boolean))];
    ordered.sort((a,b)=>a==="UTC"?-1:b==="UTC"?1:a===detected?-1:b===detected?1:timezoneLabel(a).localeCompare(timezoneLabel(b),"pt-BR"));
    for(const zone of ordered){const option=document.createElement("option");option.value=zone;option.textContent=timezoneLabel(zone);select.append(option)}
    select.value=initial;input.replaceWith(select);
    const helper=document.createElement("div");helper.className="timezone-helper";
    const note=document.createElement("small");note.className="muted";note.textContent=`Fuso deste dispositivo: ${timezoneLabel(detected)}`;
    const button=document.createElement("button");button.type="button";button.className="btn";button.textContent="Usar fuso deste dispositivo";button.onclick=()=>{select.value=detected;select.dispatchEvent(new Event("change",{bubbles:true}))};
    helper.append(note,button);select.insertAdjacentElement("afterend",helper);
}

document.addEventListener("DOMContentLoaded",()=>{
    document.body.classList.add("cap-controller-instance");
    installTimezoneSelector();
    const brand=document.querySelector(".sidebar .brand");
    if(brand)brand.href="/servers.html";

    const back=[...document.querySelectorAll(".sidebar nav a")]
        .find(link=>link.textContent.includes("Meus servidores"));
    if(back){
        back.href="/servers.html";
        back.textContent="← Instâncias";
    }

    const logout=document.getElementById("logout");
    if(logout){
        logout.textContent="Voltar";
        logout.onclick=event=>{
            event.preventDefault();
            event.stopImmediatePropagation();
            location.href="/servers.html";
        };
    }
});
})();
