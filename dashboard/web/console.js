/*
==================================================
 DSM Dashboard Enterprise
 Console Web
==================================================
*/

function getAuth() {
    return sessionStorage.getItem("dsm_auth");
}

async function executeCommand() {
    const command = document.getElementById("console-command").value;

    if (!command) {
        return;
    }

    const output = document.getElementById("console-output");
    output.value += "\n\n$ " + command;

    const response = await fetch("/api/console", {
        method: "POST",
        headers: {
            "Authorization": "Basic " + getAuth(),
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            command: command
        })
    });

    const data = await response.json();

    if (data.output) {
        output.value += "\n" + data.output;
    }

    if (data.error) {
        output.value += "\nERRO | ERROR: " + data.error;
    }

    output.scrollTop = output.scrollHeight;
}

document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("btn-console-execute");
    if (btn) {
        btn.addEventListener("click", executeCommand);
    }
});
