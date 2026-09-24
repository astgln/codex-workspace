"""Compatibility facade; domain behavior lives in focused modules.

Existing collectors and legacy adapters can retain imports during migration.
No domain logic or I/O belongs here.
"""
from .access import Forbidden, is_owner, permitted_threads, can_submit
from .identity import Unauthorized, SESSION_TTL, issue_session, verify_session, bind_user
from .catalog import sync_catalog
from .requests import MAX_TEXT, public_item, submit, collect, dispatch_allowed
from .responses import publish, public_event
from .views import view
