"""Explicit user-visible DayZ instance roots; never include private control state.

The customer file manager uses a virtual top level because the physical root
must be group-traversable (0710), not group-listable or group-writable.
"""
DAYZ_CUSTOMER_FILE_DIRS = (
    "config",
    "profiles",
    "mpmissions",
    "storage_1",
    "content",
)

# Content is managed by the Agent/UCP. Never broaden its permissions here.
DAYZ_MANAGED_CONTENT_DIRS = frozenset({"content"})
