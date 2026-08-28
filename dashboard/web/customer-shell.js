(function () {
  "use strict";

  function load(src) {
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    document.head.appendChild(script);
  }

  // Customer pages use the dedicated Customer cookie session directly.
  // Do not inject the Controller compatibility bridge into this auth domain.
  load("/customer-navigation.js?v=2");
  load("/customer-core.js?v=3");
})();
