#!/usr/bin/env python3
"""Agent-side enrollment configuration contract."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class AgentEnrollmentConfig:
    controller_url: str
    pairing_token: str


def enrollment_config(controller_url: str, pairing_token: str) -> AgentEnrollmentConfig:
    url = str(controller_url).strip().rstrip("/")
    token = str(pairing_token).strip()
    if not url:
        raise ValueError("controller_url is required")
    if not token:
        raise ValueError("pairing_token is required")
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("controller_url must be an absolute HTTP(S) URL")
    # Production deployments should use HTTPS. HTTP remains accepted here for
    # local/bootstrap tests and is a transport policy decision, not identity.
    return AgentEnrollmentConfig(controller_url=url, pairing_token=token)
