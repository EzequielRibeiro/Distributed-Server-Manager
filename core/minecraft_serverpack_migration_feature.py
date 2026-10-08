#!/usr/bin/env python3
"""Fail-closed feature policy for Minecraft Server Pack migrations.

Production execution is intentionally disabled by default. Homologation keeps
its legacy opt-in for compatibility with PR #855 evidence. Production requires
three independent pieces of configuration on both Controller and Agent:
  1. CAPIVARA_SERVERPACK_MIGRATION_MODE=production
  2. CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK=AUTHORIZED
  3. exact instance and Agent allow-list membership

This module performs policy evaluation only. It does not authorize a migration
plan, bypass backup/readiness gates, or mutate any runtime state.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

_MODE_ENV="CAPIVARA_SERVERPACK_MIGRATION_MODE"
_LEGACY_HOMOLOGATION_ENV="CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION"
_PRODUCTION_ACK_ENV="CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK"
_ALLOWED_INSTANCES_ENV="CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_INSTANCES"
_ALLOWED_AGENTS_ENV="CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_AGENTS"

_LAB_PREFIX="pr855-"
_LAB_AGENT_ID="pr839-isolated-agent"


def _items(value:Any)->set[str]:
    return {
        item.strip()
        for item in str(value or "").split(",")
        if item.strip()
    }


def migration_feature_decision(
    *,
    instance_id:str,
    agent_id:str,
    environ:Mapping[str,str]|None=None,
)->dict[str,Any]:
    env=os.environ if environ is None else environ
    iid=str(instance_id or "").strip()
    aid=str(agent_id or "").strip()
    raw_mode=str(env.get(_MODE_ENV,"") or "").strip().lower()

    # Preserve the already-homologated PR #855 switch only when the new mode
    # was not configured. Explicit new policy always wins.
    if not raw_mode and str(env.get(_LEGACY_HOMOLOGATION_ENV,"") or "").strip().upper()=="YES":
        raw_mode="homologation"

    if raw_mode in {"","disabled","off"}:
        return {
            "allowed":False,
            "mode":"disabled",
            "reason":"Server Pack migration feature is disabled",
            "production":False,
            "homologation":False,
        }

    if raw_mode=="homologation":
        allowed=iid.startswith(_LAB_PREFIX) and aid==_LAB_AGENT_ID
        return {
            "allowed":allowed,
            "mode":"homologation",
            "reason":(
                "PR855 homologation identity accepted"
                if allowed
                else "homologation mode accepts only PR855 lab instance and Agent identities"
            ),
            "production":False,
            "homologation":True,
        }

    if raw_mode!="production":
        return {
            "allowed":False,
            "mode":"invalid",
            "reason":"Server Pack migration feature mode is invalid",
            "production":False,
            "homologation":False,
        }

    if str(env.get(_PRODUCTION_ACK_ENV,"") or "")!="AUTHORIZED":
        return {
            "allowed":False,
            "mode":"production",
            "reason":"production migration acknowledgement is missing",
            "production":True,
            "homologation":False,
        }

    instances=_items(env.get(_ALLOWED_INSTANCES_ENV,""))
    agents=_items(env.get(_ALLOWED_AGENTS_ENV,""))
    if not instances or not agents:
        return {
            "allowed":False,
            "mode":"production",
            "reason":"production migration allow-lists must both be non-empty",
            "production":True,
            "homologation":False,
        }

    allowed=iid in instances and aid in agents
    return {
        "allowed":allowed,
        "mode":"production",
        "reason":(
            "production migration identity is explicitly allow-listed"
            if allowed
            else "instance or Agent is not allow-listed for production migration"
        ),
        "production":True,
        "homologation":False,
    }


def migration_feature_allowed(
    *,
    instance_id:str,
    agent_id:str,
    environ:Mapping[str,str]|None=None,
)->bool:
    return bool(migration_feature_decision(
        instance_id=instance_id,
        agent_id=agent_id,
        environ=environ,
    )["allowed"])


__all__=[
    "migration_feature_allowed",
    "migration_feature_decision",
]
