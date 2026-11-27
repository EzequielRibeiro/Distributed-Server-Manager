import contextlib
import hashlib
import io
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "dashboard"), str(ROOT / "installer")]
import controller_tls_lifecycle as rotation
import tls_runtime


class Health(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()
        self.wfile.write(b'{"status":"healthy"}')


class ControllerTlsLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir="/run" if os.geteuid() == 0 else None)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.work = Path(cls.temporary.name)
        cls.work.chmod(0o755)
        cls.ca = cls.work / "ca.pem"
        cls.ca_key = cls.work / "ca.key"
        cls.openssl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                    "-nodes", "-days", "60", "-subj", "/CN=DSM test CA",
                    "-keyout", cls.ca_key, "-out", cls.ca)
        cls.first = cls.issue("one", "controller.test", days=30)
        cls.second = cls.issue("two", "controller.test", days=45)
        cls.wrong_hostname = cls.issue("wrong", "another.test", days=45)
        cls.expired = cls.issue("expired", "controller.test", days=0)

    @classmethod
    def openssl(cls, *args):
        subprocess.run(["openssl", *args], capture_output=True, check=True, cwd=cls.work)

    @classmethod
    def issue(cls, label, hostname, *, days):
        cert, key = cls.work / f"{label}.pem", cls.work / f"{label}.key"
        ext = cls.work / f"{label}.ext"
        ext.write_text(f"subjectAltName=DNS:{hostname}\nextendedKeyUsage=serverAuth\n")
        cls.openssl("req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                    "-nodes", "-subj", f"/CN={hostname}", "-keyout", key, "-out", "request.csr")
        cls.openssl("x509", "-req", "-in", "request.csr", "-CA", cls.ca, "-CAkey", cls.ca_key,
                    "-CAcreateserial", "-days", str(days), "-extfile", ext, "-out", cert)
        return cert, key

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(dir=self.work))
        self.addCleanup(shutil.rmtree, self.directory)
        self.directory.chmod(0o755)
        self.native = self.directory / "tls"
        runtime = patch.object(tls_runtime, "NATIVE_TLS", self.native)
        runtime.start()
        self.addCleanup(runtime.stop)
        mode = patch.dict(os.environ, {"DSM_TLS_CERT_MODE": "existing"})
        mode.start()
        self.addCleanup(mode.stop)
        self.config = dict(hostname="controller.test", port=8443, ca_file=str(self.ca),
                           service_user="nobody", service_group="nogroup")
        self.select(self.first)
        if os.geteuid() != 0:
            # Exercise the same artifacts and sockets locally. CI also runs
            # as root to check source ownership, chown and the real DSM uid.
            for patcher in (
                patch.object(rotation, "trusted", side_effect=lambda path, **_: Path(path)),
                patch.object(rotation.os, "chown"),
                patch.object(rotation.os, "fchown"),
                patch.object(rotation.Lifecycle, "prepare", self.prepare_unprivileged),
                patch.object(rotation, "run", side_effect=self.run_unprivileged),
            ):
                patcher.start()
                self.addCleanup(patcher.stop)

    @staticmethod
    def prepare_unprivileged(lifecycle):
        lifecycle.versions.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def run_unprivileged(args, code, *, timeout=15, account=None):
        completed = subprocess.run(args, timeout=timeout, capture_output=True)
        if completed.returncode:
            raise rotation.RotationError(code)

    def select(self, pair):
        self.config.update(source_cert=str(pair[0]), source_key=str(pair[1]))

    def start_dashboard(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Health)
        self.addCleanup(self.server.server_close)
        self.config["port"] = self.server.server_port
        tls_runtime.configure_tls(self.server, scheme="https",
                                  cert_file=str(self.native / rotation.CERT),
                                  key_file=str(self.native / rotation.KEY))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(self.server.shutdown)

    def bootstrap(self):
        lifecycle = rotation.Lifecycle(self.config, self.native)
        lifecycle.prepare()
        lifecycle.refresh(bootstrap=True)
        self.start_dashboard()
        lifecycle.port = self.config["port"]
        self.serves(self.first)
        return lifecycle

    def serves(self, pair):
        rotation.probe("controller.test", "127.0.0.1", self.server.server_port,
                       str(self.ca), rotation.leaf_der(pair[0].read_bytes()))

    def test_external_renewal_activates_exact_leaf_and_preserves_processes(self):
        lifecycle = self.bootstrap()
        games = [subprocess.Popen(["sleep", "60"]) for _ in range(2)]
        for game in games:
            self.addCleanup(game.wait, 5)
            self.addCleanup(game.terminate)
        previous = lifecycle.current()
        self.select(self.second)
        lifecycle.refresh()
        self.serves(self.second)
        self.assertNotEqual(lifecycle.current(), previous)
        self.assertTrue(lifecycle.pair(previous)[1].exists())
        self.assertEqual(lifecycle.pair(lifecycle.current())[1].stat().st_mode & 0o777, 0o640)
        self.assertFalse(lifecycle.pending.exists())
        self.assertTrue(all(game.poll() is None for game in games))
        lifecycle.refresh()
        self.assertTrue(lifecycle.pair(previous)[1].exists())

    def test_unattended_certbot_contract_publishes_renewed_lineage(self):
        lifecycle = self.bootstrap()
        archive = self.directory / "archive" / "controller.test"
        archive.mkdir(parents=True)
        lineage = self.directory / "live" / "controller.test"
        lineage.mkdir(parents=True)
        self.config["certbot_lineage"] = "controller.test"
        original_run = rotation.run

        def renew(args, code, **kwargs):
            if args[0] != "/usr/bin/certbot":
                return original_run(args, code, **kwargs)
            self.assertIn("--non-interactive", args)
            self.assertIn("--no-directory-hooks", args)
            for name, artifact in zip(("fullchain.pem", "privkey.pem"), self.second):
                shutil.copy(artifact, archive / name)
                (lineage / name).symlink_to(Path("../../archive/controller.test") / name)

        with patch.object(rotation, "CERTBOT_LIVE", lineage.parent), patch.object(rotation, "run", side_effect=renew):
            lifecycle.refresh()
        self.serves(self.second)

    def test_wrong_hostname_wrong_key_expired_and_untrusted_chain_leave_old_pair(self):
        lifecycle = self.bootstrap()
        old = lifecycle.current()
        for pair, code in (
            ((self.second[0], self.first[1]), "dashboard_cannot_load_pair"),
            (self.wrong_hostname, "certificate_hostname_chain_or_validity_failed"),
            (self.expired, "certificate_hostname_chain_or_validity_failed"),
        ):
            with self.subTest(code=code, certificate=pair[0].name):
                self.select(pair)
                with self.assertRaisesRegex(rotation.RotationError, code):
                    lifecycle.refresh()
                self.assertEqual(lifecycle.current(), old)
                self.serves(self.first)
        self.select(self.second)
        with patch.object(lifecycle, "ca", None):
            with self.assertRaisesRegex(rotation.RotationError, "certificate_hostname_chain"):
                lifecycle.refresh()
        self.serves(self.first)

    @unittest.skipUnless(os.geteuid() == 0, "requires real root and Dashboard uid")
    def test_source_permissions_and_dashboard_read_access(self):
        lifecycle = self.bootstrap()
        cert, key = self.directory / "candidate.pem", self.directory / "candidate.key"
        shutil.copy(self.second[0], cert)
        shutil.copy(self.second[1], key)
        key.chmod(0o644)
        self.select((cert, key))
        with self.assertRaisesRegex(rotation.RotationError, "unsafe_source"):
            lifecycle.refresh()
        key.chmod(0o600)
        original_fchmod = os.fchmod
        with patch.object(os, "fchmod", side_effect=lambda fd, mode: original_fchmod(fd, 0o600)):
            with self.assertRaisesRegex(rotation.RotationError, "dashboard_cannot_load_pair"):
                lifecycle.refresh()
        self.serves(self.first)

    def test_failed_readiness_rolls_back_and_rejected_leaf_is_not_retried(self):
        lifecycle = self.bootstrap()
        previous = lifecycle.current()
        self.select(self.second)
        candidate_der = rotation.leaf_der(self.second[0].read_bytes())
        original_ready = lifecycle.ready

        def readiness(leaf):
            if leaf == candidate_der:
                self.serves(self.second)
                raise rotation.RotationError("simulated_unhealthy_dashboard")
            original_ready(leaf)

        with patch.object(lifecycle, "ready", side_effect=readiness):
            with self.assertRaisesRegex(rotation.RotationError, "candidate_activation_failed"):
                lifecycle.refresh()
        self.assertEqual(lifecycle.current(), previous)
        self.serves(self.first)
        with self.assertRaisesRegex(rotation.RotationError, "previously_rejected"):
            lifecycle.refresh()

    def test_interrupted_transaction_restores_prior_pair_before_provider(self):
        lifecycle = self.bootstrap()
        previous = lifecycle.current()
        cert, key = (item.read_bytes() for item in self.second)
        version = hashlib.sha256(cert + b"\0" + key).hexdigest()
        lifecycle.stage(version, cert, key)
        rotation.atomic_state(lifecycle.pending, [previous, version])
        lifecycle.point(version)
        self.config["certbot_lineage"] = "controller.test"
        original_run = rotation.run

        def execute(args, code, **kwargs):
            if args[0] == "/usr/bin/certbot":
                self.serves(self.first)
                self.assertEqual(args[-2:], ["--cert-name", "controller.test"])
                raise rotation.RotationError(code)
            original_run(args, code, **kwargs)

        with patch.object(rotation, "run", side_effect=execute):
            with self.assertRaisesRegex(rotation.RotationError, "certbot_renewal_failed"):
                lifecycle.refresh()
        self.assertEqual(lifecycle.current(), previous)
        self.assertFalse(lifecycle.pending.exists())

    def test_expiry_alerts_at_each_threshold_and_deduplicated(self):
        lifecycle = rotation.Lifecycle(self.config, self.native)
        lifecycle.prepare()
        lifecycle.refresh(bootstrap=True)
        expiry = ssl.cert_time_to_seconds(subprocess.check_output(
            ["openssl", "x509", "-in", str(self.first[0]), "-enddate", "-noout"],
            text=True,
        ).strip().removeprefix("notAfter="))
        for days in (30, 15, 7, 1, 0):
            with patch.object(time, "time", return_value=expiry - days * 86400):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    lifecycle.expiry()
                    lifecycle.expiry()
                self.assertEqual(output.getvalue().count(f"days_threshold={days}\n"), 1)

    def test_invalid_startup_pair_never_constructs_listener(self):
        with patch.object(tls_runtime, "_transport", return_value=("https", "127.0.0.1", 8443, None, None)):
            from unittest.mock import Mock
            legacy = Mock()
            with self.assertRaises(SystemExit) as failed:
                tls_runtime.run_dashboard(legacy)
            self.assertEqual(failed.exception.code, 78)
            legacy.DashboardServer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
