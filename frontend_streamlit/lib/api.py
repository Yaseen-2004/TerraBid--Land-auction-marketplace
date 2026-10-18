"""Thin REST client for the FastAPI backend.

Unlike the original React SPA, this runs server-side inside the Streamlit
process — the viewer's browser never talks to the backend directly, only to
Streamlit. That sidesteps CORS and cross-origin WebSocket concerns entirely,
at the cost of true push updates: "live" data here is refreshed by polling
(see lib/live.py), not pushed instantly over a socket.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import requests
import streamlit as st

DEFAULT_BASE_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 10


def base_url() -> str:
    # st.secrets raises if no secrets.toml exists at all; fall back cleanly.
    try:
        secret = st.secrets.get("API_BASE_URL")
    except Exception:
        secret = None
    return (secret or os.environ.get("API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


class ApiError(Exception):
    """Raised for any non-2xx response. Carries the backend's structured error envelope."""

    def __init__(self, message: str, status: int, code: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details


def _token() -> str | None:
    return st.session_state.get("auth_token")


def request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    headers: dict | None = None,
    auth: bool = True,
) -> Any:
    url = f"{base_url()}{path}"
    final_headers = {"Accept": "application/json", **(headers or {})}
    token = _token() if auth else None
    if token:
        final_headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.request(
            method, url, json=json, params=params, headers=final_headers, timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach the backend at {base_url()}: {exc}", 0, "NETWORK_ERROR") from exc

    body: Any = None
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = None

    if not response.ok:
        message = (body or {}).get("message") or response.reason or "Request failed."
        code = (body or {}).get("error_code") or "HTTP_ERROR"
        details = (body or {}).get("details")
        if response.status_code == 401 and token:
            # Session's token is stale/expired — drop it so the UI prompts to log in again.
            st.session_state.pop("auth_token", None)
            st.session_state.pop("auth_user", None)
        raise ApiError(message, response.status_code, code, details)
    return body


# ---------------------------------------------------------------------------- auth


def register(name: str, email: str, password: str, role: str = "BIDDER") -> dict:
    return request("POST", "/api/auth/register", json={"name": name, "email": email, "password": password, "role": role}, auth=False)


def login(email: str, password: str) -> dict:
    return request("POST", "/api/auth/login", json={"email": email, "password": password}, auth=False)


def me() -> dict:
    return request("GET", "/api/auth/me")


# ---------------------------------------------------------------------------- system


def public_config() -> dict:
    try:
        return request("GET", "/api/config", auth=False)
    except ApiError:
        return {}


def health() -> dict:
    return request("GET", "/api/health", auth=False)


# ---------------------------------------------------------------------------- properties


def list_properties(**params: Any) -> list[dict]:
    return request("GET", "/api/properties", params=_clean(params), auth=False)


def get_property(property_id: int) -> dict:
    return request("GET", f"/api/properties/{property_id}", auth=False)


def create_property(payload: dict) -> dict:
    return request("POST", "/api/properties", json=payload)


def update_property(property_id: int, payload: dict) -> dict:
    return request("PUT", f"/api/properties/{property_id}", json=payload)


def delete_property(property_id: int) -> None:
    request("DELETE", f"/api/properties/{property_id}")


# ---------------------------------------------------------------------------- auctions


def list_auctions(**params: Any) -> list[dict]:
    return request("GET", "/api/auctions", params=_clean(params), auth=False)


def get_auction(auction_id: int) -> dict:
    return request("GET", f"/api/auctions/{auction_id}", auth=False)


def create_auction(payload: dict) -> dict:
    return request("POST", "/api/auctions", json=payload)


def update_auction(auction_id: int, payload: dict) -> dict:
    return request("PUT", f"/api/auctions/{auction_id}", json=payload)


def start_auction(auction_id: int) -> dict:
    return request("PUT", f"/api/auctions/{auction_id}/start")


def end_auction(auction_id: int) -> dict:
    return request("PUT", f"/api/auctions/{auction_id}/end")


def cancel_auction(auction_id: int) -> dict:
    return request("PUT", f"/api/auctions/{auction_id}/cancel")


# ---------------------------------------------------------------------------- bids


def place_bid(auction_id: int, amount: float, expected_current_price: float | None = None) -> dict:
    idempotency_key = str(uuid.uuid4())
    payload = {"amount": amount, "expected_current_price": expected_current_price}
    return request(
        "POST",
        f"/api/auctions/{auction_id}/bid",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )


def list_bids(auction_id: int, *, include_rejected: bool = False, limit: int = 50) -> list[dict]:
    return request(
        "GET",
        f"/api/auctions/{auction_id}/bids",
        params={"include_rejected": include_rejected, "limit": limit},
        auth=include_rejected,
    )


# ---------------------------------------------------------------------------- admin


def admin_stats() -> dict:
    return request("GET", "/api/admin/stats")


def admin_users(limit: int = 500) -> list[dict]:
    return request("GET", "/api/admin/users", params={"limit": limit})


def update_user(user_id: int, payload: dict) -> dict:
    return request("PATCH", f"/api/admin/users/{user_id}", json=payload)


def auction_bidders(auction_id: int) -> list[dict]:
    return request("GET", f"/api/admin/auctions/{auction_id}/bidders")


def _clean(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None and v != ""}
