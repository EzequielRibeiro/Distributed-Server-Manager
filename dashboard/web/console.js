/*
==================================================
 DSM Dashboard Enterprise
 Console Web
==================================================
*/

async function executeCommand() {
    const command = document.getElementById("console-command").value;

    if (!command) return;

    const output = document.getElementById("console-output");
    output.value += "\n\n$ " + command;

    const response = await fetch("/api/console", {
        method: "POST",
        headers: {
            "X-Capivara-Auth-Area": "controller",
            "Accept": "application/json",
            "Content-Type": "application/json"
        },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({command})
    });

    if (response.status === 401) {
        location.replace("/login.html");
        return;
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        output.value += "\nERRO | ERROR: " + (data.error || data.message || `HTTP ${response.status}`);
    } else if (data.output) {
        output.value += "\n" + data.output;
    }

    output.scrollTop = output.scrollHeight;
}

document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("btn-console-execute");
    if (btn) btn.addEventListener("click", executeCommand);
});
