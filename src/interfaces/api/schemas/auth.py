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
