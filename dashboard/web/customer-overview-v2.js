(function(){
  "use strict";

  /*
   * Legacy compatibility asset.
   *
   * The current customer instance page is rendered by customer-instance.js,
   * which owns #instance-overview and the provisioning status panel.  Older
   * server composition layers may still inject this file into
   * customer-instance.html.  It must therefore remain inert so it cannot
   * replace the current overview every 10 seconds and race the adaptive
   * polling performed by customer-instance.js.
   *
   * Keep this file as a no-op until the legacy injection in server_part8 is
   * removed from every supported upgrade path.
   */
})();
