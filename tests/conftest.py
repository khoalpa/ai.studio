from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def block_network_by_default(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Prove the default suite cannot make outbound or loopback connections."""
    if request.node.get_closest_marker("local_llm") is not None:
        yield
        return

    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden in the default test suite")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    yield
