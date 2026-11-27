"""Privileged Controller TLS rotation. Installed outside the DSM runtime tree."""
import argparse
from contextlib import ExitStack
import fcntl
import grp
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time


NATIVE = Path("/etc/capivara/tls")
CONFIG = Path("/etc/capivara/controller-tls.json")
CERTBOT_LIVE = Path("/etc/letsencrypt/live")
UPDATE_LOCK = Path("/var/lib/capivara-dsm-928/updater-admission.lock")
CERT = "server.crt"
KEY = "server.key"
DIGEST = re.compile(r"[a-f0-9]{64}")
PEM = re.compile(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S)
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "HOME": "/root"}


class RotationError(Exception):
    pass


def event(priority, code, detail=""):
    # systemd's journal interprets the priority prefix. No subprocess output,
    # PEM data, provider arguments or credential paths reach this interface.
    print(f"<{priority}>controller-tls {code} {detail}".rstrip(), flush=True)


def trusted(path, *, private=False):
    """Accept root-controlled paths, including Certbot's archive symlinks."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise RotationError("absolute_root_controlled_path_required")

    def check(target):
        info = target.lstat()
        if info.st_uid != 0 or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022):
            raise RotationError("unsafe_path_ownership_or_permissions")

    # Resolve one component at a time so intermediate symlink destinations
    # (including those outside the final resolved path) are checked too.
    def resolve(target, remaining=40):
        current = Path("/")
        for part in target.parts[1:]:
            current /= part
            check(current)
            if current.is_symlink():
                if not remaining:
                    raise RotationError("unsafe_symlink_chain")
                link = Path(os.readlink(current))
                destination = link if link.is_absolute() else current.parent / link
                # Resolve even the directories traversed before a "..".
                current = resolve(destination, remaining - 1)
        return current

    resolved = resolve(path)
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode) or (private and info.st_mode & 0o077):
        raise RotationError("unsafe_source_file_type_or_permissions")
    return resolved


def retain_update_admission(locks):
    if not UPDATE_LOCK.exists() and not UPDATE_LOCK.is_symlink():
        return
    descriptor = os.open(UPDATE_LOCK, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    lock = locks.enter_context(os.fdopen(descriptor, "rb"))
    info = os.fstat(lock.fileno())
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size != 0):
        raise RotationError("untrusted_updater_admission_inode")
    fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    current = UPDATE_LOCK.lstat()
    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        raise RotationError("updater_admission_inode_changed")


def run(args, code, *, timeout=15, account=None):
    identity = {}
    if account:
        user, gid = account
        identity = {"user": user.pw_uid, "group": gid,
                    "extra_groups": os.getgrouplist(user.pw_name, gid)}
    try:
        completed = subprocess.run(
            args, check=False, timeout=timeout, env=ENV,
            stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, **identity,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RotationError(code) from None
    if completed.returncode:
        raise RotationError(code)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_file(path, data, mode, gid=0):
    with path.open("xb") as stream:
        os.fchown(stream.fileno(), 0, gid)
        os.fchmod(stream.fileno(), mode)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_state(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def leaf_der(cert):
    match = PEM.search(cert)
    if match is None:
        raise RotationError("invalid_certificate_pem")
    return ssl.PEM_cert_to_DER_cert(match[0].decode("ascii"))


def probe(host, address, port, ca, expected_leaf, timeout=5):
    context = ssl.create_default_context(cafile=ca)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((address, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            if tls.getpeercert(binary_form=True) != expected_leaf:
                raise RotationError("unexpected_served_certificate")
            tls.sendall(f"GET /health HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode("ascii"))
            response = http.client.HTTPResponse(tls)
            response.begin()
            if response.status != 200 or json.loads(response.read(65536)).get("status") != "healthy":
                raise RotationError("dashboard_health_failed")


def verification_name(host):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
            raise RotationError("invalid_public_hostname") from None
        return "-verify_hostname"
    return "-verify_ip"


class Lifecycle:
    def __init__(self, config, root=NATIVE):
        self.config = config
        self.root = root
        self.versions = root / "versions"
        self.active = root / "active"
        self.pending = root / ".pending.json"
        self.rejected = root / ".rejected.json"
        self.alerts = root / ".expiry.json"
        self.host = config["hostname"]
        verification_name(self.host)
        self.address = str(ipaddress.ip_address(config.get("address", "127.0.0.1")))
        self.port = int(config["port"])
        if not 1 <= self.port <= 65535:
            raise RotationError("invalid_dashboard_port")
        user = pwd.getpwnam(config["service_user"])
        self.gid = grp.getgrnam(config["service_group"]).gr_gid
        if user.pw_uid == 0 or self.gid == 0:
            raise RotationError("unprivileged_dashboard_account_required")
        self.account = user, self.gid
        self.ca = str(trusted(config["ca_file"])) if config.get("ca_file") else None

    def prepare(self):
        for directory, mode in ((self.root, 0o750), (self.versions, 0o750)):
            directory.mkdir(mode=mode, exist_ok=True)
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_mode & 0o022:
                raise RotationError("unsafe_tls_directory")
            os.chown(directory, 0, self.gid)
            os.chmod(directory, mode)

    def current(self):
        try:
            target = os.readlink(self.active)
        except FileNotFoundError:
            return None
        version = target.removeprefix("versions/")
        if target != f"versions/{version}" or not DIGEST.fullmatch(version):
            raise RotationError("invalid_active_generation")
        return version

    def point(self, version):
        temporary = self.root / ".next"
        temporary.unlink(missing_ok=True)
        if version is None:
            self.active.unlink(missing_ok=True)
        else:
            temporary.symlink_to(f"versions/{version}")
            os.replace(temporary, self.active)
        sync_dir(self.root)

    def pair(self, version):
        directory = self.versions / version if version else self.root
        return directory / CERT, directory / KEY

    def validate(self, cert, key):
        certificate = cert.read_bytes()
        chain = PEM.findall(certificate)
        if not chain or PEM.sub(b"", certificate).strip():
            raise RotationError("invalid_fullchain_pem")
        # Test the actual service credentials, including traversal and key pairing.
        run(
            ["/usr/bin/python3", "-I", "-c",
             "import ssl,sys; ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(*sys.argv[1:], password=b'')",
             str(cert), str(key)],
            "dashboard_cannot_load_pair", account=self.account,
        )
        with tempfile.TemporaryDirectory() as work:
            leaf = Path(work) / "leaf.pem"
            intermediates = Path(work) / "chain.pem"
            leaf.write_bytes(chain[0] + b"\n")
            intermediates.write_bytes(b"\n".join(chain[1:]))
            args = ["/usr/bin/openssl", "verify", "-purpose", "sslserver",
                    verification_name(self.host), self.host]
            if self.ca:
                args += ["-CAfile", self.ca, "-no-CApath", "-no-CAstore"]
            if len(chain) > 1:
                args += ["-untrusted", str(intermediates)]
            run(args + [str(leaf)], "certificate_hostname_chain_or_validity_failed")
        return leaf_der(certificate)

    def stage(self, version, certificate, key):
        dest = self.versions / version
        if not dest.exists():
            with tempfile.TemporaryDirectory(dir=self.versions) as work:
                source = Path(work) / "pair"
                source.mkdir()
                os.chown(source, 0, self.gid)
                os.chmod(source, 0o750)
                write_file(source / CERT, certificate, 0o640, self.gid)
                write_file(source / KEY, key, 0o640, self.gid)
                sync_dir(source)
                source.rename(dest)
                sync_dir(self.versions)

    def ready(self, expected_leaf, seconds=25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                probe(self.host, self.address, self.port, self.ca, expected_leaf)
                return
            except (RotationError, OSError, ValueError, AttributeError, http.client.HTTPException):
                time.sleep(1)
        raise RotationError("verified_https_readiness_failed")

    def rollback(self, old, candidate, *, interrupted=False):
        self.point(old)
        atomic_state(self.rejected, candidate)
        self.pending.unlink(missing_ok=True)
        sync_dir(self.root)
        try:
            previous = self.validate(*self.pair(old))
            self.ready(previous)
        except (RotationError, OSError, ValueError):
            raise RotationError("rollback_restored_pointer_but_previous_https_unverified") from None
        event(3, "activation_interrupted_rolled_back" if interrupted else "activation_failed_rolled_back")

    def expiry(self):
        cert, _ = self.pair(self.current())
        try:
            leaf = leaf_der(cert.read_bytes())
            output = subprocess.check_output(
                ["/usr/bin/openssl", "x509", "-in", str(cert), "-enddate", "-noout"],
                env=ENV, timeout=5, stderr=subprocess.DEVNULL,
            ).decode().strip()
            expiry = ssl.cert_time_to_seconds(output.removeprefix("notAfter="))
        except (OSError, ValueError, RotationError, subprocess.SubprocessError):
            event(3, "active_certificate_expiry_unavailable")
            return
        left = expiry - time.time()
        threshold = next((days for days in (0, 1, 7, 15, 30) if left <= days * 86400), None)
        if threshold is not None:
            state = [hashlib.sha256(leaf).hexdigest(), threshold]
            if not self.alerts.exists() or json.loads(self.alerts.read_text()) != state:
                event(3 if threshold <= 1 else 4, "certificate_expiry", f"days_threshold={threshold}")
                atomic_state(self.alerts, state)

    def recover(self):
        old = self.current()
        if self.pending.exists():
            previous, candidate = json.loads(self.pending.read_text())
            if ((previous is not None and not DIGEST.fullmatch(previous))
                    or not DIGEST.fullmatch(candidate) or old not in (previous, candidate)):
                raise RotationError("invalid_pending_generation")
            self.rollback(previous, candidate, interrupted=True)
            old = previous
        return old

    def refresh(self, *, bootstrap=False, retry=False):
        old = self.recover()
        lineage = self.config.get("certbot_lineage")
        if lineage:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", lineage):
                raise RotationError("invalid_certbot_lineage")
            if not bootstrap:
                run(["/usr/bin/certbot", "renew", "--non-interactive", "--no-directory-hooks",
                     "--cert-name", lineage], "certbot_renewal_failed", timeout=420)
            source = CERTBOT_LIVE / lineage
            cert_path, key_path = source / "fullchain.pem", source / "privkey.pem"
        else:
            cert_path, key_path = self.config["source_cert"], self.config["source_key"]

        certificate = trusted(cert_path).read_bytes()
        key = trusted(key_path, private=True).read_bytes()
        version = hashlib.sha256(certificate + b"\0" + key).hexdigest()
        if version == old:
            self.ready(self.validate(*self.pair(old)))
            return
        if (not retry and self.rejected.exists()
                and json.loads(self.rejected.read_text()) == version):
            raise RotationError("previously_rejected_candidate_requires_review")

        self.stage(version, certificate, key)
        try:
            expected = self.validate(*self.pair(version))
        except (RotationError, OSError, ValueError):
            shutil.rmtree(self.versions / version)
            raise

        if bootstrap:
            if old is not None or any(path.exists() for path in self.pair(None)):
                raise RotationError("bootstrap_requires_new_installation")
            self.point(version)
            return

        # Journal before exposing the candidate. If killed before commit, the
        # next invocation restores the prior generation before trying renewal.
        atomic_state(self.pending, [old, version])
        try:
            self.point(version)
            self.ready(expected)
        except (RotationError, OSError):
            self.rollback(old, version)
            raise RotationError("candidate_activation_failed") from None
        self.pending.unlink()
        self.rejected.unlink(missing_ok=True)
        sync_dir(self.root)
        # Retain the previously active generation for operator recovery.
        for entry in self.versions.iterdir():
            if DIGEST.fullmatch(entry.name) and entry.name not in {old, version}:
                shutil.rmtree(entry)
        event(6, "activation_verified", f"leaf_sha256={hashlib.sha256(expected).hexdigest()}")


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-hook")
    mode.add_argument("--bootstrap", action="store_true")
    mode.add_argument("--retry", action="store_true")
    mode.add_argument("--verify-active", action="store_true")
    mode.add_argument("--recover-only", action="store_true")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise RotationError("root_required")
        if args.verify_hook:
            if not os.access(trusted(args.verify_hook), os.X_OK):
                raise RotationError("dns_hook_not_executable")
            return 0
        config_path = trusted(CONFIG, private=True)
        lifecycle = Lifecycle(json.loads(config_path.read_text()))
        with ExitStack() as locks:
            # Coordinate with both installed update entry points when the
            # #928 admission inode has been provisioned. Never replace it.
            retain_update_admission(locks)
            lifecycle.prepare()
            lock = locks.enter_context((lifecycle.root / ".lock").open("a"))
            os.chmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                if args.recover_only:
                    lifecycle.recover()
                elif args.verify_active:
                    cert, key = lifecycle.pair(lifecycle.current())
                    lifecycle.ready(lifecycle.validate(cert, key))
                else:
                    lifecycle.refresh(bootstrap=args.bootstrap, retry=args.retry)
            finally:
                if not (args.bootstrap or args.recover_only):
                    lifecycle.expiry()
    except RotationError as exc:
        event(3, "action_required", str(exc))
        return 1
    except BlockingIOError:
        event(4, "rotation_deferred", "controller_update_or_rotation_in_progress")
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        event(3, "action_required", "check_configuration_source_permissions_and_lifecycle_storage")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
