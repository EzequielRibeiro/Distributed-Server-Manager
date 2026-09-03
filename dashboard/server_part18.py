#!/usr/bin/env python3
"""Universal game-server update composition layer."""
from __future__ import annotations
from pathlib import Path
import server_part17 as integration
from server_update_install import install_server_update_http
legacy=integration.legacy
_ROOT=Path(__file__).resolve().parents[1]
install_server_update_http(legacy,integration._controller_authenticate,_ROOT)
def run():integration.run()
if __name__=='__main__':run()
