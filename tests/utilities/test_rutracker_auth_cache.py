"""Tests for the Rutracker provider's auth-cookie cache and cool-down."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from torrents.providers import rutracker as rt_module
from torrents.providers.rutracker import RutrackerTorrentProvider

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@pytest.fixture
def credentials() -> dict[str, str]:
    return {"username": "u", "password": "p"}


def _stub_authenticate(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[], Awaitable[dict[str, str]]],
) -> list[int]:
    """Replace module-level ``_authenticate`` with ``handler``; return a call counter."""
    calls = [0]

    async def fake(_credentials):
        calls[0] += 1
        return await handler()

    monkeypatch.setattr(rt_module, "_authenticate", fake)
    return calls


@pytest.mark.asyncio
async def test_get_cookies_caches_success(monkeypatch, credentials):
    """Given a successful login, when callers ask repeatedly, then only one auth happens."""

    async def ok():
        return {"bb_session": "fresh"}

    calls = _stub_authenticate(monkeypatch, ok)
    provider = RutrackerTorrentProvider(credentials=credentials)

    first = await provider._get_cookies()
    second = await provider._get_cookies()

    assert first == {"bb_session": "fresh"}
    assert second == {"bb_session": "fresh"}
    assert calls[0] == 1


@pytest.mark.asyncio
async def test_get_cookies_honors_failure_cooldown(monkeypatch, credentials):
    """Given an auth failure, when another caller arrives during cool-down,
    then it gets the cached empty cookies without re-trying."""

    async def fail():
        raise RuntimeError("rutracker is down")

    calls = _stub_authenticate(monkeypatch, fail)
    provider = RutrackerTorrentProvider(credentials=credentials)

    first = await provider._get_cookies()
    second = await provider._get_cookies()

    assert first == {}
    assert second == {}
    assert calls[0] == 1


@pytest.mark.asyncio
async def test_get_cookies_serializes_concurrent_callers(monkeypatch, credentials):
    """Given N concurrent callers, when authentication is slow, then only one login fires."""
    barrier = asyncio.Event()

    async def slow():
        await barrier.wait()
        return {"bb_session": "fresh"}

    calls = _stub_authenticate(monkeypatch, slow)
    provider = RutrackerTorrentProvider(credentials=credentials)

    pending = [asyncio.create_task(provider._get_cookies()) for _ in range(5)]
    await asyncio.sleep(0)
    barrier.set()
    results = await asyncio.gather(*pending)

    assert all(r == {"bb_session": "fresh"} for r in results)
    assert calls[0] == 1


@pytest.mark.asyncio
async def test_get_cookies_returns_empty_when_no_credentials(monkeypatch):
    """Given no credentials, when fetching cookies, then no auth call is made."""

    async def must_not_run():
        raise AssertionError("_authenticate must not be called without credentials")

    calls = _stub_authenticate(monkeypatch, must_not_run)
    provider = RutrackerTorrentProvider(credentials=None)

    cookies = await provider._get_cookies()

    assert cookies == {}
    assert calls[0] == 0
