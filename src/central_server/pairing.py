"""The hub's half of workstation pairing: codes, their limits, and the routes.

The protocol is in :mod:`src.infrastructure.hub_pairing`, shared with the
workstation; read its docstring first. This module decides who may run it and
how often.

**One code at a time.** A workstation's first message is computed from the code
it was given, and the hub cannot tell which of several codes that was without
the workstation saying something about the code -- which is exactly what the
protocol avoids. So issuing a code replaces the previous one. Pairing a room of
workstations is one code each, in turn; each takes seconds.

**The limits.** An attacker without the code gets one guess per exchange, so
what bounds them is the number of exchanges:

* a code expires :data:`CODE_TTL_SECONDS` after it is issued;
* it is retired by the first workstation that completes the exchange;
* it is locked after :data:`MAX_ATTEMPTS_PER_CODE` exchanges are *started*,
  successful or not -- the hub cannot tell a wrong code from a right one until
  the workstation confirms, so every start counts;
* each client address may make :data:`RATE_LIMIT_PER_ADDRESS` pairing requests
  per :data:`RATE_WINDOW_SECONDS`, and the hub as a whole
  :data:`RATE_LIMIT_GLOBAL`, which also bounds the 2048-bit exponentiations an
  unauthenticated caller can make the hub do.

Five starts against a million codes is a five-in-a-million chance, per code.

Kept out of ``server.py`` so it can be tested in-process: importing ``server``
initialises two databases at module scope (VRT-15). Everything here is built
by :func:`build_router`, which ``server.py`` mounts.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.infrastructure import hub_pairing as protocol
from src.utils.clock import utc_now
from src.utils.logger import logger

CODE_TTL_SECONDS = 600
MAX_ATTEMPTS_PER_CODE = 5
#: How long a started exchange waits for the workstation's confirmation.
ATTEMPT_TTL_SECONDS = 60
RATE_WINDOW_SECONDS = 60
RATE_LIMIT_PER_ADDRESS = 10
RATE_LIMIT_GLOBAL = 60


class PairingRefusedError(Exception):
    """A pairing request the hub will not serve; mapped to an HTTP error."""

    def __init__(self, status: int, reason: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.message = message
        self.retry_after = retry_after


@dataclass
class _Code:
    code: str
    generator: int
    issued_at: float
    expires_at: float
    issued_at_utc: str
    expires_at_utc: str
    issued_by: str
    ca_fingerprint: str
    attempts: int = 0
    used_at_utc: str | None = None
    used_by: str | None = None


@dataclass
class _Attempt:
    code: _Code
    key: bytes
    a_value: int
    b_value: int
    fingerprint: bytes
    client: str
    started_at: float


@dataclass
class _RateLimiter:
    """Sliding-window request counts, per address and in total."""

    window: float
    per_address: int
    overall: int
    _by_address: dict[str, deque[float]] = field(default_factory=dict)
    _all: deque[float] = field(default_factory=deque)

    def check(self, address: str, now: float) -> None:
        cutoff = now - self.window
        for stamps in (*self._by_address.values(), self._all):
            while stamps and stamps[0] <= cutoff:
                stamps.popleft()
        for empty in [a for a, s in self._by_address.items() if not s]:
            del self._by_address[empty]

        mine = self._by_address.setdefault(address, deque())
        for stamps, limit in ((mine, self.per_address), (self._all, self.overall)):
            if len(stamps) >= limit:
                retry_after = max(1, int(stamps[0] + self.window - now) + 1)
                raise PairingRefusedError(
                    429,
                    "rate_limited",
                    f"Too many pairing attempts. Try again in {retry_after} s.",
                    retry_after=retry_after,
                )
        mine.append(now)
        self._all.append(now)


class PairingService:
    """Issues pairing codes and runs the hub's side of the exchange.

    Holds everything in memory: a code lives ten minutes, and a hub restart
    simply means the administrator generates another.

    Args:
        ca_pem: Returns the hub's CA certificate, PEM. Called per request, so a
            certificate regenerated on a running hub is the one paired with.
        clock: Monotonic seconds; injectable so tests can expire a code.
    """

    def __init__(
        self,
        ca_pem: Callable[[], str],
        *,
        clock: Callable[[], float] = time.monotonic,
        code_ttl: float = CODE_TTL_SECONDS,
        max_attempts: int = MAX_ATTEMPTS_PER_CODE,
        attempt_ttl: float = ATTEMPT_TTL_SECONDS,
        rate_window: float = RATE_WINDOW_SECONDS,
        rate_per_address: int = RATE_LIMIT_PER_ADDRESS,
        rate_overall: int = RATE_LIMIT_GLOBAL,
    ) -> None:
        self._ca_pem = ca_pem
        self._clock = clock
        self._code_ttl = code_ttl
        self._max_attempts = max_attempts
        self._attempt_ttl = attempt_ttl
        self._limiter = _RateLimiter(rate_window, rate_per_address, rate_overall)
        self._lock = threading.Lock()
        self._code: _Code | None = None
        self._attempts: dict[str, _Attempt] = {}

    # --- the CA --------------------------------------------------------------

    def _ca(self) -> tuple[str, bytes]:
        try:
            pem = self._ca_pem()
            der = protocol.certificate_der(pem)
        except (OSError, ValueError) as exc:
            raise PairingRefusedError(
                503,
                "pairing_unavailable",
                f"This hub has no CA certificate to pair with ({exc}). Pairing is for a hub "
                "whose certificate was created by vrtelemetry-hub setup or gen-cert.",
            ) from exc
        return pem, protocol.fingerprint(der)

    # --- the administrator's side -------------------------------------------

    def issue(self, issued_by: str) -> dict[str, Any]:
        """A new code, replacing any active one."""
        _, digest = self._ca()
        now, wall = self._clock(), utc_now()
        code = f"{secrets.randbelow(10**protocol.CODE_DIGITS):0{protocol.CODE_DIGITS}d}"
        with self._lock:
            self._code = _Code(
                code=code,
                generator=protocol.generator(code),
                issued_at=now,
                expires_at=now + self._code_ttl,
                issued_at_utc=wall.isoformat(),
                expires_at_utc=(wall + timedelta(seconds=self._code_ttl)).isoformat(),
                issued_by=issued_by,
                ca_fingerprint=protocol.format_fingerprint(digest),
            )
            self._attempts.clear()
        logger.warning(f"Admin {issued_by} issued a workstation pairing code")
        return self.status()

    def revoke(self) -> None:
        with self._lock:
            self._code = None
            self._attempts.clear()

    def status(self) -> dict[str, Any]:
        """The active code and its state, for the admin UI."""
        with self._lock:
            code, now = self._code, self._clock()
            if code is None:
                return {"state": "none"}
            if code.used_at_utc:
                state = "used"
            elif now >= code.expires_at:
                state = "expired"
            elif code.attempts >= self._max_attempts:
                state = "locked"
            else:
                state = "active"
            return {
                "state": state,
                "code": code.code if state == "active" else None,
                "issued_at": code.issued_at_utc,
                "expires_at": code.expires_at_utc,
                "expires_in": max(0, int(code.expires_at - now)),
                "attempts": code.attempts,
                "max_attempts": self._max_attempts,
                "used_at": code.used_at_utc,
                "used_by": code.used_by,
                "ca_fingerprint": code.ca_fingerprint,
            }

    # --- the workstation's side ---------------------------------------------

    def _usable_code(self, now: float) -> _Code:
        code = self._code
        if code is None:
            raise PairingRefusedError(
                404,
                "no_pairing_code",
                "This hub has no pairing code. Generate one in its admin UI.",
            )
        if code.used_at_utc:
            raise PairingRefusedError(
                410,
                "pairing_code_used",
                "That pairing code has already been used. Generate a new one in the admin UI.",
            )
        if now >= code.expires_at:
            raise PairingRefusedError(
                410,
                "pairing_code_expired",
                "The pairing code has expired. Generate a new one in the hub's admin UI.",
            )
        return code

    def start(self, a_hex: Any, client: str) -> dict[str, Any]:
        """Answer a workstation's first message; counts against the code."""
        pem, digest = self._ca()
        with self._lock:
            now = self._clock()
            self._limiter.check(client, now)
            code = self._usable_code(now)
            if code.attempts >= self._max_attempts:
                raise PairingRefusedError(
                    410,
                    "pairing_code_locked",
                    "Too many attempts were made with this pairing code. Generate a new one.",
                )
            try:
                a_value = protocol.decode_element(a_hex)
            except ValueError as exc:
                raise PairingRefusedError(
                    400, "bad_request", f"Invalid pairing request: {exc}"
                ) from exc
            code.attempts += 1
            # Drop exchanges nobody finished, so the table cannot grow without bound.
            for stale in [
                k for k, a in self._attempts.items() if now - a.started_at > self._attempt_ttl
            ]:
                del self._attempts[stale]
            generator = code.generator

        b_secret, b_value = protocol.new_ephemeral(generator)
        key = protocol.session_key(b_secret, a_value, a_value, b_value)
        attempt_id = secrets.token_urlsafe(18)
        with self._lock:
            self._attempts[attempt_id] = _Attempt(
                code=code,
                key=key,
                a_value=a_value,
                b_value=b_value,
                fingerprint=digest,
                client=client,
                started_at=now,
            )
        logger.info(f"Pairing exchange started from {client} (attempt {code.attempts})")
        return {
            "version": protocol.PROTOCOL_VERSION,
            "attempt_id": attempt_id,
            "B": protocol.encode_element(b_value),
            "ca_pem": pem,
            "confirm": protocol.hub_confirmation(key, digest, a_value, b_value),
        }

    def finish(self, attempt_id: Any, confirm: Any, client: str) -> dict[str, Any]:
        """Check the workstation's confirmation and retire the code."""
        with self._lock:
            now = self._clock()
            self._limiter.check(client, now)
            attempt = self._attempts.pop(attempt_id, None) if isinstance(attempt_id, str) else None
            if attempt is None or now - attempt.started_at > self._attempt_ttl:
                raise PairingRefusedError(
                    403, "pairing_failed", "Unknown or expired pairing exchange. Start again."
                )
            if attempt.code is not self._code:
                raise PairingRefusedError(
                    410,
                    "pairing_code_replaced",
                    "The pairing code was replaced while pairing. Use the new one.",
                )
            self._usable_code(now)
            expected = protocol.workstation_confirmation(
                attempt.key, attempt.fingerprint, attempt.a_value, attempt.b_value
            )
            if not protocol.confirmations_match(expected, confirm):
                logger.warning(f"Pairing confirmation from {client} did not verify")
                raise PairingRefusedError(
                    403, "pairing_failed", "The pairing confirmation did not verify."
                )
            attempt.code.used_at_utc = utc_now().isoformat()
            attempt.code.used_by = client
            self._attempts.clear()
        logger.warning(f"Workstation at {client} paired with this hub")
        return {"ok": True}


class PairingStartRequest(BaseModel):
    version: int = protocol.PROTOCOL_VERSION
    A: str


class PairingFinishRequest(BaseModel):
    attempt_id: str
    confirm: str


def _http_error(exc: PairingRefusedError) -> HTTPException:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return HTTPException(
        status_code=exc.status,
        detail={"reason": exc.reason, "message": exc.message},
        headers=headers,
    )


def build_router(service: PairingService, require_admin: Callable[..., dict]) -> APIRouter:
    """The pairing routes, for ``server.py`` to mount.

    ``/admin/pairing/code`` is the administrator's; ``/pairing/*`` is
    unauthenticated by necessity -- the workstation has no account on this
    hub yet, and cannot verify it -- and is protected by the code and the
    limits instead.
    """
    router = APIRouter(tags=["pairing"])

    def _client(request: Request) -> str:
        return request.client.host if request.client else ""

    @router.post("/admin/pairing/code")
    def admin_issue_pairing_code(admin: dict = Depends(require_admin)) -> dict[str, Any]:
        try:
            return service.issue(admin.get("email", "?"))
        except PairingRefusedError as exc:
            raise _http_error(exc) from exc

    @router.get("/admin/pairing/code", dependencies=[Depends(require_admin)])
    def admin_pairing_code_status() -> dict[str, Any]:
        return service.status()

    @router.delete("/admin/pairing/code")
    def admin_revoke_pairing_code(admin: dict = Depends(require_admin)) -> dict[str, Any]:
        service.revoke()
        logger.warning(f"Admin {admin.get('email', '?')} cancelled the pairing code")
        return {"ok": True}

    @router.post("/pairing/start")
    def pairing_start(payload: PairingStartRequest, request: Request) -> dict[str, Any]:
        if payload.version != protocol.PROTOCOL_VERSION:
            raise HTTPException(
                status_code=400,
                detail={
                    "reason": "unsupported_version",
                    "message": f"This hub speaks pairing version {protocol.PROTOCOL_VERSION}.",
                },
            )
        try:
            return service.start(payload.A, _client(request))
        except PairingRefusedError as exc:
            raise _http_error(exc) from exc

    @router.post("/pairing/finish")
    def pairing_finish(payload: PairingFinishRequest, request: Request) -> dict[str, Any]:
        try:
            return service.finish(payload.attempt_id, payload.confirm, _client(request))
        except PairingRefusedError as exc:
            raise _http_error(exc) from exc

    return router
