#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from catalog_resource_profiles_http import (
    catalog_resource_profiles,
    dispatch_catalog_resource_profiles_get,
    dispatch_catalog_resource_profiles_put,
)
from catalog_provisioning_resolver import resolve_catalog_provisioning


class CatalogGameDataArchitectureTest(unittest.TestCase):
    def test_catalog_page_does_not_manage_instances(self):
        html = (ROOT / "dashboard/web/catalog.html").read_text(encoding="utf-8")
        self.assertNotIn('id="catalog-v2-instance"', html)
        self.assertNotIn("Reinstalar instância", html)
        for label in ("Game Data", "Parâmetros", "Configuração", "Recursos", "Agents", "Versões"):
            self.assertIn(label, html)

    def test_game_installation_has_live_progress_and_error_details(self):
        html = (ROOT / "dashboard/web/catalog.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard/web/catalog-page.js").read_text(encoding="utf-8")
        self.assertIn('id="catalog-operation-progress"', html)
        self.assertIn('id="catalog-error-details"', html)
        self.assertIn('id="catalog-steam-auth-help"', html)
        self.assertIn('id="catalog-copy-steam-auth"', html)
        self.assertIn("followJob", script)
        self.assertIn("resumeAgentJob", script)
        self.assertIn("Carregando arquivos do Agent", script)
        self.assertIn("if(byId('catalog-agent').value)loadFiles()", script)
        self.assertIn("Nenhuma nova instalação foi iniciada", script)
        self.assertIn("Object.hasOwn(operationLabels", script)
        self.assertIn("Consultando arquivos", script)
        self.assertIn("fileReadToken", script)
        self.assertIn("Aguardando o Agent enviar o conteúdo", script)
        self.assertIn("request('/api/whoami')", script)
        self.assertNotIn("request('/api/auth/me')", script)
        self.assertIn("Não foi possível confirmar as permissões", script)
        self.assertIn("timeoutMs=180000", script)
        self.assertIn("fileReadBusy", script)
        self.assertIn("fileListBusy", script)
        self.assertIn("Ver detalhes técnicos do erro", html)
        self.assertIn("DSM_STEAM_USER", script)
        self.assertIn("Steam Guard", script)
        self.assertIn("navigator.clipboard.writeText", script)
        self.assertIn("document.execCommand('copy')", script)
        self.assertIn("window.isSecureContext", script)
        self.assertIn("STEAM_ACCOUNT < /dev/tty", script)
        self.assertIn("+quit < /dev/tty", script)
        self.assertNotIn("DSM_STEAM_PASSWORD", script)

    def test_resource_profile_sample_uses_explicit_units(self):
        payload = json.loads((ROOT / "catalog/v2/games/minecraft/resource-profiles.json").read_text(encoding="utf-8"))
        profiles = {item["id"]: item for item in payload["profiles"]}
        self.assertEqual(profiles["standard"]["memory_mb"], 8192)
        self.assertEqual(profiles["standard"]["storage_mb"], 25600)
        self.assertEqual(profiles["large"]["memory_mb"], 16384)
        self.assertEqual(profiles["large"]["storage_mb"], 30720)

    def test_provisioning_without_selection_uses_the_game_default_profile(self):
        _, configuration = resolve_catalog_provisioning(
            environment_id="minecraft.java.vanilla",
            selector="current",
            selection={"environment_id": "minecraft.java.vanilla"},
            configuration={},
            root=ROOT,
        )
        self.assertEqual(configuration["resource_profile_id"], "standard")
        self.assertEqual(configuration["resource_profile"]["name"], "Standard")

    def test_resource_profile_reader_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                catalog_resource_profiles(Path(tmp), "../etc")

    def test_resource_profile_reader_returns_empty_for_undefined_game_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog/v2/games/example").mkdir(parents=True)
            payload = catalog_resource_profiles(root, "example")
            self.assertEqual(payload["profiles"], [])
            self.assertIsNone(payload["default_profile_id"])

    def test_resource_profiles_can_be_saved_and_read_by_customer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog/v2/games/example").mkdir(parents=True)
            profile = {
                "id": "standard", "name": "Standard",
                "description": "Perfil recomendado.", "cpu_cores": 2,
                "memory_mb": 4096, "storage_mb": 20480,
                "swap_mb": 1024, "pids_limit": 512,
            }
            status, saved = dispatch_catalog_resource_profiles_put(
                "/api/catalog/resource-profiles",
                {"game": "example", "profiles": [profile], "default_profile_id": "standard"},
                user={"role": "admin"}, root=root,
            )
            self.assertEqual(status, 200)
            self.assertEqual(saved["profiles"][0]["id"], "standard")
            self.assertEqual(saved["default_profile_id"], "standard")
            self.assertTrue((root / "config/catalog-resource-profiles/example.json").is_file())
            status, loaded = dispatch_catalog_resource_profiles_get(
                "/api/catalog/resource-profiles", "game=example",
                user={"role": "customer"}, root=root,
            )
            self.assertEqual(status, 200)
            self.assertEqual(loaded, saved)

    def test_operator_can_change_only_the_default_resource_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game_dir = root / "catalog/v2/games/example"
            game_dir.mkdir(parents=True)
            profiles = [
                {"id": "small", "name": "Small", "cpu_cores": 1,
                 "memory_mb": 1024, "storage_mb": 1024, "swap_mb": 0, "pids_limit": 128},
                {"id": "large", "name": "Large", "cpu_cores": 2,
                 "memory_mb": 2048, "storage_mb": 2048, "swap_mb": 0, "pids_limit": 256},
            ]
            dispatch_catalog_resource_profiles_put(
                "/api/catalog/resource-profiles",
                {"game": "example", "profiles": profiles, "default_profile_id": "small"},
                user={"role": "admin"}, root=root,
            )
            status, payload = dispatch_catalog_resource_profiles_put(
                "/api/catalog/resource-profiles",
                {"game": "example", "profiles": profiles, "default_profile_id": "large"},
                user={"role": "operator"}, root=root,
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["default_profile_id"], "large")
            changed = [dict(profiles[0], memory_mb=8192), profiles[1]]
            status, payload = dispatch_catalog_resource_profiles_put(
                "/api/catalog/resource-profiles",
                {"game": "example", "profiles": changed, "default_profile_id": "small"},
                user={"role": "operator"}, root=root,
            )
            self.assertEqual(status, 403)
            self.assertEqual(payload["error"], "forbidden")

    def test_dashboard_uses_latest_composition_layer(self):
        service = (ROOT / "systemd/dsm-dashboard.service").read_text(encoding="utf-8")
        self.assertIn("server_part17.py", service)


if __name__ == "__main__":
    unittest.main()
