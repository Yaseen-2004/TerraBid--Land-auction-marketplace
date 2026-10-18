"""Session-scoped auth state.

Streamlit's session_state lives only as long as the browser tab's connection
to this server session — a full page reload starts a fresh session and the
user is logged out. That's a real trade-off versus the original SPA's
localStorage-persisted JWT; see README for the documented limitation.
"""

from __future__ import annotations

import streamlit as st

from lib import api
from lib.api import ApiError


def init_session() -> None:
    st.session_state.setdefault("auth_token", None)
    st.session_state.setdefault("auth_user", None)
    st.session_state.setdefault("selected_property_id", None)
    st.session_state.setdefault("auth_error", None)


def current_user() -> dict | None:
    return st.session_state.get("auth_user")


def is_authenticated() -> bool:
    return current_user() is not None


def has_role(*roles: str) -> bool:
    user = current_user()
    return bool(user) and user["role"] in roles


def can_manage_listings() -> bool:
    return has_role("SELLER", "ADMIN")


def is_admin() -> bool:
    return has_role("ADMIN")


def _apply_session(token_response: dict) -> dict:
    st.session_state["auth_token"] = token_response["access_token"]
    st.session_state["auth_user"] = token_response["user"]
    return token_response["user"]


def login(email: str, password: str) -> tuple[bool, str | None]:
    try:
        user = _apply_session(api.login(email, password))
        return True, f"Welcome back, {user['name']}!"
    except ApiError as exc:
        return False, exc.message


def register(name: str, email: str, password: str, role: str) -> tuple[bool, str | None]:
    try:
        user = _apply_session(api.register(name, email, password, role))
        return True, f"Account created — welcome, {user['name']}!"
    except ApiError as exc:
        return False, exc.message


def logout() -> None:
    st.session_state["auth_token"] = None
    st.session_state["auth_user"] = None


def require_role(*roles: str) -> bool:
    """Renders a stop-page warning and returns False if the current user lacks any of `roles`."""
    if not is_authenticated():
        st.warning("Please log in from the sidebar to view this page.")
        return False
    if roles and not has_role(*roles):
        st.error("You do not have permission to view this page.")
        return False
    return True
