(() => {
    "use strict";

    function mount() {
        const Explorer = window.CapivaraInfrastructureExplorer;
        const Details = window.CapivaraInfrastructureDetails;
        if (!Explorer || document.getElementById("capivara-infrastructure-shell")) return;

        const shell = document.createElement("aside");
        shell.id = "capivara-infrastructure-shell";
        shell.className = "capivara-infrastructure-shell";
        shell.hidden = true;
        shell.innerHTML = `
            <div class="infra-shell-header">
                <div>
                    <strong>Infrastructure</strong>
                    <span>Region · Datacenter · Agent</span>
                </div>
                <button type="button" class="infra-shell-close" aria-label="Fechar infraestrutura">×</button>
            </div>
            <div class="infrastructure-explorer" data-infrastructure-explorer></div>
            <div class="infrastructure-details" data-infrastructure-details></div>
        `;
        document.body.appendChild(shell);

        const trigger = document.createElement("button");
        trigger.type = "button";
        trigger.id = "capivara-infrastructure-trigger";
        trigger.className = "capivara-infrastructure-trigger";
        trigger.textContent = "Infrastructure";
        trigger.title = "Abrir Infrastructure Explorer";
        document.body.appendChild(trigger);

        const explorer = shell.querySelector("[data-infrastructure-explorer]");
        const details = shell.querySelector("[data-infrastructure-details]");
        const close = shell.querySelector(".infra-shell-close");

        if (Details) {
            Details.mount(details);
        }

        function open() {
            shell.hidden = false;
            trigger.setAttribute("aria-expanded", "true");
            if (!shell.dataset.loaded) {
                shell.dataset.loaded = "true";
                Explorer.load(explorer, { activeOnly: false });
            }
        }

        function hide() {
            shell.hidden = true;
            trigger.setAttribute("aria-expanded", "false");
        }

        trigger.setAttribute("aria-controls", shell.id);
        trigger.setAttribute("aria-expanded", "false");
        trigger.addEventListener("click", () => shell.hidden ? open() : hide());
        close.addEventListener("click", hide);
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !shell.hidden) hide();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mount, { once: true });
    } else {
        mount();
    }
})();