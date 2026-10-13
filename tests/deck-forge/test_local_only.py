"""The hub's local-only guard: DNS-rebinding (Host) and cross-site (Origin)."""

import pytest
from fastapi.testclient import TestClient

from mtg_utils._deck_forge.app import ANY_HOST, build_app
from mtg_utils._deck_forge.state import DeckSession, ForgeState
from mtg_utils.deck_forge_server import allowed_hosts_for

_HUB = "http://127.0.0.1:8765"


def _client(base_url=_HUB, allowed_hosts=None):
    state = ForgeState(
        by_name={},
        search_fn=lambda **_: [],
        session=DeckSession("commander"),
    )
    return TestClient(build_app(state, allowed_hosts=allowed_hosts), base_url=base_url)


def _ask_agent(client, **headers):
    return client.post(
        "/api/agent/request",
        json={"kind": "explain", "payload": {"card": "Sol Ring"}},
        headers=headers,
    )


@pytest.mark.parametrize(
    "host", ["127.0.0.1:8765", "localhost:8765", "LOCALHOST", "[::1]:8765"]
)
def test_answers_to_loopback_names(host):
    # Host set by hand: TestClient can't parse an IPv6 base_url.
    r = _client().get("/api/health", headers={"host": host})
    assert r.status_code == 200


def test_rebinding_host_is_refused():
    # A rebinding page's requests carry its own domain as Host.
    client = _client("http://evil.example:8765")
    assert client.get("/api/health").status_code == 403
    assert _ask_agent(client).status_code == 403


def test_cross_site_post_is_refused_and_never_reaches_the_bridge():
    client = _client()
    assert _ask_agent(client, origin="https://evil.example").status_code == 403
    assert _ask_agent(client, origin="null").status_code == 403
    nxt = client.get("/api/agent/next", params={"timeout": 0.01})
    assert nxt.status_code == 204


def test_bodyless_cross_site_post_is_refused():
    # No JSON body to fail validation, so only the guard stands in the way.
    client = _client()
    r = client.post("/api/agent/heartbeat", headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.get("/api/agent/status").json() == {"attached": False}


@pytest.mark.parametrize(
    "origin",
    [
        None,  # the session agent's requests calls, curl
        _HUB,  # the built SPA
        "http://localhost:5173",  # the vite dev server's proxy
    ],
)
def test_local_callers_pass(origin):
    headers = {} if origin is None else {"origin": origin}
    assert _ask_agent(_client(), **headers).status_code == 200


def test_wildcard_bind_answers_any_host_but_checks_origin():
    lan = "http://192.168.1.5:8765"
    client = _client(lan, allowed_hosts={ANY_HOST})
    assert _ask_agent(client, origin=lan).status_code == 200
    assert _ask_agent(client, origin="https://evil.example").status_code == 403


def test_allowed_hosts_for_bind():
    assert allowed_hosts_for("0.0.0.0") == {ANY_HOST}
    assert allowed_hosts_for("192.168.1.5") >= {"192.168.1.5", "127.0.0.1"}
    assert allowed_hosts_for("127.0.0.1") == {"127.0.0.1", "localhost", "::1"}
