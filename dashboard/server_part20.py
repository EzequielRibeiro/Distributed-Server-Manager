#!/usr/bin/env python3
"""Scheduled maintenance customer surface composition layer."""
from __future__ import annotations
import server_part19 as integration
from customer_maintenance_http import install_customer_maintenance_http
from customer_dayz_http import install_customer_dayz_http

legacy=integration.legacy
_customer_authenticate=integration.integration.integration._customer_authenticate
install_customer_maintenance_http(legacy,_customer_authenticate)
install_customer_dayz_http(legacy,_customer_authenticate)
legacy.STATIC_FILES.update({
 "/customer-maintenance.js":legacy.WEB_DIR/"customer-maintenance.js",
 "/customer-dayz.js":legacy.WEB_DIR/"customer-dayz.js",
 "/customer-content-update-policy.js":legacy.WEB_DIR/"customer-content-update-policy.js",
})

def run():integration.run()
if __name__=="__main__":run()
