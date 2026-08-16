"""The peer registry: lookup, precedence, and failing at startup rather than later."""

from __future__ import annotations

from datetime import timedelta

import httpx2
import pytest
from pydantic import ValidationError

from conftest import json_response, recording
from mint_client import Client, ClientsConfig, UnknownPeerError
from mint_client.config import PeerConfig


class TestLookup:
    def test_a_peer_is_found_by_its_key(self, clients_config: ClientsConfig) -> None:
        assert clients_config.peer("parts_svc").base_url == "http://parts-svc.test:8080"

    def test_a_peer_is_found_by_its_hyphenated_name(self, clients_config: ClientsConfig) -> None:
        """Callers say "parts-svc"; the environment can only say PARTS_SVC.

        Both have to reach the same entry, or the config key and the name in the
        code drift apart and nobody notices until an override silently does
        nothing.
        """
        assert clients_config.peer("parts-svc").base_url == "http://parts-svc.test:8080"

    def test_an_unknown_peer_names_the_ones_that_exist(self, clients_config: ClientsConfig) -> None:
        with pytest.raises(UnknownPeerError) as caught:
            clients_config.peer("nope")

        message = str(caught.value)
        assert "parts_svc" in message
        assert "slow_svc" in message

    def test_an_empty_registry_is_not_an_error(self) -> None:
        # Most services call nothing.
        config = ClientsConfig()
        assert config.peers == {}
        with pytest.raises(UnknownPeerError):
            config.peer("anything")

    def test_the_peer_label_defaults_to_the_dns_name(self, clients_config: ClientsConfig) -> None:
        assert clients_config.peer_name("parts_svc") == "parts-svc"

    def test_an_explicit_name_wins(self) -> None:
        config = ClientsConfig.model_validate(
            {"peers": {"legacy_thing": {"base_url": "http://x.test", "name": "legacy.thing"}}}
        )
        assert config.peer_name("legacy_thing") == "legacy.thing"


class TestPrecedence:
    def test_a_peer_without_overrides_uses_the_shared_defaults(
        self, clients_config: ClientsConfig
    ) -> None:
        peer = clients_config.peer("parts_svc")
        assert clients_config.timeout_for(peer).total == timedelta(seconds=5)

    def test_a_peer_may_override_the_shared_defaults(self, clients_config: ClientsConfig) -> None:
        peer = clients_config.peer("slow_svc")
        assert clients_config.timeout_for(peer).total == timedelta(seconds=30)


class TestValidation:
    def test_a_base_url_without_a_scheme_is_rejected(self) -> None:
        """Caught here, not at the first call.

        httpx would take "localhost:8081" as a *path* on a relative URL and fail
        with something that reads nothing like "you forgot the scheme".
        """
        with pytest.raises(ValidationError, match="http://"):
            PeerConfig(base_url="localhost:8081")

    def test_an_unknown_key_is_a_typo_worth_failing_on(self) -> None:
        with pytest.raises(ValidationError):
            PeerConfig.model_validate({"base_url": "http://x.test", "timeoutt": "5s"})

    def test_a_zero_timeout_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClientsConfig.model_validate({"timeout": {"total": "0s"}})

    def test_keepalive_cannot_exceed_the_pool(self) -> None:
        with pytest.raises(ValidationError, match="max_keepalive_connections"):
            ClientsConfig.model_validate(
                {"pool": {"max_connections": 5, "max_keepalive_connections": 10}}
            )

    def test_go_style_durations_are_accepted(self) -> None:
        config = ClientsConfig.model_validate({"timeout": {"total": "1m30s", "connect": "500ms"}})
        assert config.timeout.total == timedelta(seconds=90)
        assert config.timeout.connect == timedelta(milliseconds=500)

    def test_durations_render_back_to_the_way_they_are_written(self) -> None:
        config = ClientsConfig.model_validate({"timeout": {"total": "1m30s"}})
        assert config.model_dump(mode="json")["timeout"]["total"] == "1m30s"


class TestForPeer:
    def test_it_builds_a_client_from_the_registry(self, clients_config: ClientsConfig) -> None:
        handler, _ = recording(json_response(200, {}))
        client = Client.for_peer(
            clients_config, "parts-svc", transport=httpx2.MockTransport(handler)
        )

        assert client.peer == "parts-svc"
        assert client.base_url == "http://parts-svc.test:8080"

    def test_an_undeclared_peer_fails_at_construction(self, clients_config: ClientsConfig) -> None:
        # At startup, which is when the composition root calls this — not at the
        # first call in production.
        with pytest.raises(UnknownPeerError):
            Client.for_peer(clients_config, "not-declared")

    async def test_the_peer_headers_and_user_agent_are_applied(
        self, clients_config: ClientsConfig
    ) -> None:
        handler, seen = recording(json_response(200, {}))
        async with Client.for_peer(
            clients_config, "slow-svc", transport=httpx2.MockTransport(handler)
        ) as client:
            await client.get("/things")

        assert seen[0].headers["x-api-key"] == "static"
        assert seen[0].headers["user-agent"].startswith("widget-svc/0.1.0 mint-client/")
