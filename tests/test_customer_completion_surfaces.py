#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"dashboard"))
from customer_invitation_api import PUBLIC_INVITATION_PATHS,TEAM_INVITATION_PATHS
from customer_verification_api import CUSTOMER_VERIFICATION_PATHS
def test_completion_surfaces_are_separated():
    assert "/api/customer/invitations/accept" in PUBLIC_INVITATION_PATHS
    assert "/api/customer/team/invitations/create" in TEAM_INVITATION_PATHS
    assert "/api/customer/team/invitations/revoke" in TEAM_INVITATION_PATHS
    assert "/api/customer/email-verification" in CUSTOMER_VERIFICATION_PATHS
    assert not (PUBLIC_INVITATION_PATHS & TEAM_INVITATION_PATHS)
