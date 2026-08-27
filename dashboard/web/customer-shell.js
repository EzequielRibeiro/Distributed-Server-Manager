(function () {
  "use strict";
  function load(src) {
    const script = document.createElement("script");
    script.src = src;
    script.defer = false;
    document.head.appendChild(script);
  }
  load("/customer-navigation.js?v=1");
  load("/customer-core.js?v=2");
})();
