#!/usr/bin/env python3
"""Administrative YARA-X security composition layer."""
from __future__ import annotations

import server_part20 as integration
from yarax_security_http import install_yarax_security_http

legacy = integration.legacy
_controller_authenticate = integration.integration.integration.integration._controller_authenticate
install_yarax_security_http(legacy, _controller_authenticate)


def run():
    integration.run()


if __name__ == "__main__":
    run()
