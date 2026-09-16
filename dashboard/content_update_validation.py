#!/usr/bin/env python3
"""Shared validation for policy-driven content update dispatchers."""
from __future__ import annotations
from typing import Any
from content_update_detector import _artifact_revision


def verify_content_update_revision(item:dict[str,Any],current:dict[str,Any]|None)->int:
 value=current if isinstance(current,dict) else {};before=int(item.get('assignment_revision') or 0);after=int(value.get('revision') or 0)
 if after<=before:raise RuntimeError('content update did not create a new canonical revision')
 provider=str(item.get('provider') or '').strip().lower();available=str(item.get('available_version') or '').strip()
 if provider in {'steam','steam-workshop'}:
  resolved=str(value.get('version') or '').strip()
  if not available or resolved!=available:raise RuntimeError('Steam Workshop canonical revision does not match detected upstream revision')
 elif provider in {'modrinth','curseforge'}:
  resolved=_artifact_revision(value.get('artifact') if isinstance(value.get('artifact'),dict) else {})
  if not available or resolved!=available:raise RuntimeError('structured provider canonical revision does not match detected upstream revision')
 return after


__all__=['verify_content_update_revision']
