(() => {
  "use strict";

  const SELECTOR = "select[data-capivara-timezone]";

  function detectedTimezone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch (_) {
      return "UTC";
    }
  }

  function isBrowserTimezone(timezone) {
    const value = String(timezone || "").trim();
    if (!value) return false;
    try {
      new Intl.DateTimeFormat("pt-BR", { timeZone: value }).format(new Date());
      return true;
    } catch (_) {
      return false;
    }
  }

  function offsetLabel(timezone, instant = new Date()) {
    const value = String(timezone || "UTC").trim() || "UTC";
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: value,
        timeZoneName: "longOffset",
        hour: "2-digit",
      }).formatToParts(instant);
      const raw = parts.find(part => part.type === "timeZoneName")?.value || "GMT";
      if (/^(GMT|UTC)$/i.test(raw)) return "UTC+00:00";
      const match = raw.match(/(?:GMT|UTC)([+-])(\d{1,2})(?::?(\d{2}))?/i);
      if (match) {
        const sign = match[1] === "-" ? "−" : "+";
        return `UTC${sign}${String(match[2]).padStart(2, "0")}:${String(match[3] || "00").padStart(2, "0")}`;
      }
    } catch (_) {
      // Fall through to a neutral label. Existing server-side IANA aliases
      // still need to remain selectable even when the browser cannot format them.
    }
    return value === "UTC" ? "UTC+00:00" : "UTC";
  }

  function locationLabel(timezone) {
    const value = String(timezone || "UTC").trim() || "UTC";
    if (value === "UTC" || value === "Etc/UTC") return "UTC";
    const parts = value.split("/");
    return (parts[parts.length - 1] || value).replaceAll("_", " ");
  }

  function label(timezone, instant = new Date()) {
    const value = String(timezone || "UTC").trim() || "UTC";
    const location = locationLabel(value);
    const offset = offsetLabel(value, instant);
    return value === "UTC" ? `UTC (${offset})` : `${location} (${offset}) · ${value}`;
  }

  function supportedTimezones() {
    let values = [];
    try {
      if (typeof Intl.supportedValuesOf === "function") {
        values = Intl.supportedValuesOf("timeZone") || [];
      }
    } catch (_) {
      values = [];
    }
    const detected = detectedTimezone();
    return [...new Set(["UTC", detected, ...values].filter(Boolean))];
  }

  function addOption(select, timezone) {
    const value = String(timezone || "").trim();
    if (!value) return null;
    let option = [...select.options].find(item => item.value === value);
    if (option) return option;
    option = document.createElement("option");
    option.value = value;
    option.textContent = label(value);
    select.append(option);
    return option;
  }

  function installValueCompatibility(select) {
    if (select.dataset.capivaraTimezoneValueHook === "1") return;
    const descriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
    if (!descriptor?.get || !descriptor?.set) return;
    Object.defineProperty(select, "value", {
      configurable: true,
      enumerable: true,
      get() {
        return descriptor.get.call(this);
      },
      set(next) {
        const value = String(next ?? "").trim();
        if (value) addOption(this, value);
        descriptor.set.call(this, value);
      },
    });
    select.dataset.capivaraTimezoneValueHook = "1";
  }

  function enhance(select) {
    if (!(select instanceof HTMLSelectElement) || select.dataset.capivaraTimezoneReady === "1") return;
    const initial = String(select.value || select.dataset.value || "UTC").trim() || "UTC";
    const detected = detectedTimezone();
    select.replaceChildren();

    const zones = supportedTimezones();
    const priority = new Set(["UTC", detected]);
    const ordered = [
      ...zones.filter(zone => priority.has(zone)),
      ...zones.filter(zone => !priority.has(zone)).sort((a, b) => label(a).localeCompare(label(b), "pt-BR")),
    ];
    ordered.forEach(zone => addOption(select, zone));
    addOption(select, initial);
    installValueCompatibility(select);
    select.value = initial;
    select.dataset.capivaraTimezoneReady = "1";

    if (select.dataset.capivaraTimezoneDetect === "false") return;
    const helper = document.createElement("div");
    helper.className = "timezone-helper";
    const note = document.createElement("small");
    note.className = "muted";
    note.textContent = `Fuso deste dispositivo: ${label(detected)}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn";
    button.textContent = "Usar fuso deste dispositivo";
    button.addEventListener("click", () => {
      select.value = detected;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    helper.append(note, button);
    select.insertAdjacentElement("afterend", helper);
  }

  function init(root = document) {
    root.querySelectorAll(SELECTOR).forEach(enhance);
  }

  window.CapivaraScheduleTimezone = {
    detectedTimezone,
    enhance,
    init,
    isBrowserTimezone,
    label,
    offsetLabel,
  };

  init();
})();
