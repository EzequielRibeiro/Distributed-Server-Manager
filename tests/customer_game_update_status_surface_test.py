"""Customer game update status must remain read-only and permission-gated."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CustomerGameUpdateStatusSurfaceTest(unittest.TestCase):
    def test_customer_endpoint_checks_instance_permission(self):
        source = (ROOT / 'dashboard/customer_content_http.py').read_text()
        self.assertIn('policy_api(user,instance_id);return send(self,200,instance_update_policy_view(instance_id,backend=backend()))', source)
        self.assertIn('api.workspace.require(user,instance_id,permission)', source)

    def test_api_exposes_existing_instance_state_without_mutation(self):
        source = (ROOT / 'dashboard/server_update_api.py').read_text()
        start = source.index('def instance_update_policy_view(')
        end = source.index('\ndef configure_server_update(', start)
        body = source[start:end]
        self.assertIn("'game_update':public_state", body)
        self.assertIn("'last_checked_at'", body)
        self.assertNotIn("'game_update':snapshot.get('state')", body)
        self.assertIn('repo.snapshot(iid)', body)
        self.assertNotIn('queue_check(', body)
        self.assertNotIn('queue_update(', body)

    def test_customer_ui_separates_game_from_managed_content(self):
        source = (ROOT / 'dashboard/web/customer-content-update-policy.js').read_text()
        self.assertIn('function renderGameUpdate(view)', source)
        self.assertIn('view.game_update', source)
        self.assertIn('m4-game-update-status', source)
        self.assertIn('body.insertBefore(game,installed)', source)
        self.assertIn('body.append(global,game,status)', source)
        self.assertIn('textContent', source)
        self.assertNotIn('innerHTML', source)


if __name__ == '__main__':
    unittest.main()
