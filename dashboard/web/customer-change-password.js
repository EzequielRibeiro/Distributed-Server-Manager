(function () {
  "use strict";

  const $ = id => document.getElementById(id);
  const form = $("customer-change-password-form");
  const message = $("customer-change-password-message");

  async function customerSession() {
    const response = await fetch("/api/customer/auth/session", {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    const data = await response.json().catch(() => ({}));
    return data?.authenticated && data?.role === "customer" ? data : null;
  }

  async function initialize() {
    const session = await customerSession().catch(() => null);

    if (!session) {
      location.replace("/customer-login.html");
      return;
    }

    if (!session.must_change_password) {
      location.replace("/customer.html");
      return;
    }

    form.addEventListener("submit", async event => {
      event.preventDefault();

      const password = $("customer-new-password").value;
      const confirmation = $("customer-new-password-confirmation").value;

      if (password !== confirmation) {
        message.textContent = "A confirmação da senha não corresponde.";
        return;
      }

      try {
        const response = await fetch(
          "/api/customer/password/change-temporary",
          {
            method: "POST",
            headers: {
              Accept: "application/json",
              "Content-Type": "application/json",
            },
            credentials: "same-origin",
            body: JSON.stringify({
              password,
              password_confirmation: confirmation,
            }),
          }
        );

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
          throw new Error(
            data.error ||
            data.message ||
            `HTTP ${response.status}`
          );
        }

        message.textContent =
          "Senha alterada. Entre novamente com sua nova senha.";

        await fetch("/api/customer/auth/logout", {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
          cache: "no-store",
        }).catch(() => {});

        location.replace("/customer-login.html");
      } catch (error) {
        message.textContent = error.message;
      }
    });
  }

  initialize();
})();
