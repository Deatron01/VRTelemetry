# src/interfaces/api/schemas/auth.py
"""Account authentication and hub-address models."""

from __future__ import annotations

from pydantic import BaseModel


class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    org_name: str
    display_name: str = ""


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class CentralUrlConfig(BaseModel):
    central_server_url: str


class CentralUrlCheck(BaseModel):
    """An address to test, or nothing to test the configured one.

    Optional on purpose: the researcher wants to check an address *before*
    committing to it, and also wants to check the one already saved when
    something has stopped working. Two questions, one route.
    """

    central_server_url: str | None = None
