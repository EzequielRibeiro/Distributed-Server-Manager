#!/usr/bin/env python3
"""Opt-in, one-shot unattended SteamCMD session verification; no credentials read.

Default is plan-only. Run as the exact SteamCMD service user, under the same
HOME as the unattended runtime. Never logs subprocess output or Steam username.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from steam_session_audit import compare, snapshot

# Fixed status codes only. Raw SteamCMD messages and account identifiers are
# processed in memory, never printed, persisted or included in exceptions.
_AUTH_FAILURE = re.compile(r'ERROR!.*(?:Login|Password|Authentication)|Login Failure|authentication failed|Invalid Password|Steam Guard.*(required|failed)|two-factor.*(required|failed)|Access Denied', re.I)
_CONNECTION_FAILURE = re.compile(r'No connection|Failed to connect|Could not connect|Connection timed out|Network is unreachable|Offline mode', re.I)
_GENERIC_FAILURE = re.compile(r'ERROR!|FAILED!', re.I)
_NAMED = re.compile(r'Logging in user (.+?) to Steam Public(?:\.\.\.|\s*:\s*)', re.I)
_SUCCESS = re.compile(r'Logged in OK|Logging in user .+? to Steam Public\.\.\.OK', re.I)


def classify(output: str, code: int, expected_account: str) -> str:
    """Return one reason code without retaining or displaying SteamCMD output."""
    if _AUTH_FAILURE.search(output):
        return 'authentication_rejected'
    if _CONNECTION_FAILURE.search(output):
        return 'connection_failure'
    if _GENERIC_FAILURE.search(output):
        return 'steamcmd_reported_error'
    if code != 0:
        return 'steamcmd_nonzero_exit'
    named = [name.strip().strip("'\"").casefold() for name in _NAMED.findall(output)]
    if named and any(name != expected_account.casefold() for name in named):
        return 'account_mismatch'
    if _SUCCESS.search(output):
        return 'verified'
    return 'no_explicit_login_confirmation'


def check_once(binary: Path, home: Path, account: str, *, runner=subprocess.run) -> dict:
    before = snapshot(home)
    result = 'not_verified'
    env = dict(os.environ, HOME=str(home), CAPIVARA_STEAM_HOME=str(home))
    # Existing XDG_DATA_HOME could redirect Steam state to another account.
    env.pop('XDG_DATA_HOME', None)
    try:
        completed = runner([str(binary), '+login', account, '+quit'], env=env,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=75, check=False)
        result = classify(completed.stdout or '', completed.returncode, account)
    except subprocess.TimeoutExpired:
        result = 'timeout'
    finally:
        after = snapshot(home)
    return {'kind':'steam_reuse_probe_once', 'result':result, 'session_metadata':compare(before,after)['changes']}


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home', type=Path, required=True)
    p.add_argument('--steamcmd', type=Path, required=True)
    p.add_argument('--execute', action='store_true', help='Explicitly run ONE noninteractive +login; never prompts or supplies credentials')
    args=p.parse_args()
    # Print only constant metadata and paths; never print Steam user or output.
    if not args.execute:
        print(json.dumps({'kind':'steam_reuse_probe_plan','will_run':False,'requires':'--execute; DSM_STEAM_USER in environment; exact runtime UID/HOME','reads_credential_file_contents':False},sort_keys=True))
        return 0
    account=os.environ.get('DSM_STEAM_USER','').strip()
    if not account or account.lower() == 'anonymous':
        print(json.dumps({'kind':'steam_reuse_probe_once','result':'missing_account'}))
        return 2
    home=args.home.absolute()
    if not home.is_dir() or home.is_symlink() or home.stat().st_uid != os.geteuid():
        print(json.dumps({'kind':'steam_reuse_probe_once','result':'unsafe_home'}))
        return 2
    if not args.steamcmd.is_file() or not os.access(args.steamcmd,os.X_OK):
        print(json.dumps({'kind':'steam_reuse_probe_once','result':'missing_steamcmd'}))
        return 2
    try:
        result=check_once(args.steamcmd, home, account)
    except (OSError, ValueError):
        print(json.dumps({'kind':'steam_reuse_probe_once','result':'probe_error'}))
        return 1
    print(json.dumps(result,sort_keys=True))
    return 0 if result['result']=='verified' else 1

if __name__=='__main__':
    sys.exit(main())
