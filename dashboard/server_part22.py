#!/usr/bin/env python3
"""DB1-DB6 Database Intelligence composition layer."""
from __future__ import annotations

import server_part21 as integration
from database_intelligence_http import install_database_intelligence_http

legacy = integration.legacy
_controller_authenticate = integration._controller_authenticate
install_database_intelligence_http(legacy, _controller_authenticate)


def run():
    integration.run()


if __name__ == "__main__":
    run()
