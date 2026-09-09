(()=>{
"use strict";

const params=new URLSearchParams(location.search);
if(params.get("auth_area")!=="controller")return;

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

document.addEventListener("DOMContentLoaded",()=>{
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
