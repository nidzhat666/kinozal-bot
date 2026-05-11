"""Tests for the Rutracker HTTP retry helper."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from services.exceptions import RutrackerApiError
from torrents.providers import rutracker as rt_module
from torrents.providers.rutracker import _request_with_retry

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip actual sleeps between retries so tests run quickly."""

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(rt_module.asyncio, "sleep", fake_sleep)


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response | Exception],
) -> list[httpx.Request]:
    """Replace ``_make_client`` with one backed by a MockTransport.

    The transport records every request it sees and lets ``handler``
    decide the response (or raise) for the n-th call.
    """
    captured: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        outcome = handler(request)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def fake_make_client(_cookies, timeout):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(transport_handler),
            follow_redirects=True,
            timeout=timeout,
        )

    monkeypatch.setattr(rt_module, "_make_client", fake_make_client)
    return captured


@pytest.mark.asyncio
async def test_returns_response_on_success(monkeypatch):
    """Given a 200 response, when called once, then it's returned and not retried."""
    captured = _install_transport(monkeypatch, lambda _r: httpx.Response(200, text="ok"))

    response = await _request_with_retry("GET", "https://example.com/x")

    assert response.status_code == 200
    assert response.text == "ok"
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_retries_on_5xx_then_succeeds(monkeypatch):
    """Given a 500 then a 200, when called, then the helper returns the 200."""
    responses = iter([httpx.Response(500), httpx.Response(200, text="ok")])

    captured = _install_transport(monkeypatch, lambda _r: next(responses))

    response = await _request_with_retry("GET", "https://example.com/x")

    assert response.status_code == 200
    assert response.text == "ok"
    assert len(captured) == 2


@pytest.mark.asyncio
async def test_retries_on_transport_error_then_succeeds(monkeypatch):
    """Given a transport timeout then a 200, when called, then it recovers."""
    attempts = iter(
        [
            httpx.ReadTimeout("timeout"),
            httpx.Response(200, text="ok"),
        ]
    )

    captured = _install_transport(monkeypatch, lambda _r: next(attempts))

    response = await _request_with_retry("GET", "https://example.com/x")

    assert response.status_code == 200
    assert len(captured) == 2


@pytest.mark.asyncio
async def test_non_transient_http_status_raises_immediately(monkeypatch):
    """Given a 404, when called, then it raises without any retries."""
    captured = _install_transport(monkeypatch, lambda _r: httpx.Response(404))

    with pytest.raises(RutrackerApiError):
        await _request_with_retry("GET", "https://example.com/missing")

    assert len(captured) == 1


@pytest.mark.asyncio
async def test_retries_exhausted_raises_with_last_status(monkeypatch):
    """Given persistent 5xx, when retries exhaust, then a RutrackerApiError is raised."""
    captured = _install_transport(monkeypatch, lambda _r: httpx.Response(503))

    with pytest.raises(RutrackerApiError, match="last_status=503"):
        await _request_with_retry("POST", "https://example.com/y", data={"k": "v"})

    assert len(captured) == rt_module._MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_non_transient_transport_error_raises_immediately(monkeypatch):
    """Given a non-retryable httpx error, when called, then it raises without retrying."""

    class FakeError(httpx.HTTPError):
        pass

    captured = _install_transport(monkeypatch, lambda _r: FakeError("nope"))

    with pytest.raises(RutrackerApiError):
        await _request_with_retry("GET", "https://example.com/x")

    assert len(captured) == 1


@pytest.mark.asyncio
async def test_forwards_method_params_data(monkeypatch):
    """Given method/params/data, when called, then they reach the transport verbatim."""
    captured = _install_transport(monkeypatch, lambda _r: httpx.Response(200))

    await _request_with_retry(
        "POST",
        "https://example.com/y",
        params={"nm": "query"},
        data={"k": "v"},
    )

    request = captured[0]
    assert request.method == "POST"
    assert "nm=query" in str(request.url)
    assert request.content == b"k=v"
