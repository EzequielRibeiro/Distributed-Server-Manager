(function () {
  "use strict";
  function load(src) {
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    document.head.appendChild(script);
  }
  // Customer pages served through legacy HTML composition do not pass through
  // DashboardHandler.send_file, so bootstrap the same credential-free cookie
  // session bridge explicitly before any legacy Customer module runs.
  load("/browser-session-bridge.js?v=1");
  load("/customer-navigation.js?v=1");
  load("/customer-core.js?v=2");
})();