"""The shape of the ``clients`` config section — and nothing that reads it.

**This module reads no environment variables and no files, and it never will.**
py-service enforces "configuration is read in exactly one place" with a lint
rule; a library that read its own environment would defeat that rule from
outside the tree it checks, and ``make config`` would stop being able to name
the source of every value.

So the split is: this package owns the *schema* (it is the thing that validates
and consumes the values), and the service owns the *loading*. A service embeds
:class:`ClientsConfig` in its own ``Config`` and pydantic-settings fills it from
the same four-layer precedence as everything else::

    class Config(BaseSettings):
        ...
        clients: ClientsConfig = ClientsConfig()

which yields, with no extra work::

    clients.peers.parts_svc.base_url      MINT_CLIENTS__PEERS__PARTS_SVC__BASE_URL

Peer keys use underscores
-------------------------
``parts_svc``, not ``parts-svc``. This is forced, not chosen: ``__`` separates
config levels in an environment variable name, so the key has to survive
``MINT_CLIENTS__PEERS__<KEY>__BASE_URL`` being lower-cased — and a hyphen cannot
appear in a shell variable name at all. :meth:`ClientsConfig.peer` normalises
hyphens on lookup, so calling code may spell it either way, and
:attr:`PeerConfig.name` keeps the real DNS name for labels and span attributes.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mint_client.duration import Duration
from mint_client.errors import UnknownPeerError

__all__ = ["ClientsConfig", "PeerConfig", "PoolConfig", "TimeoutConfig"]


class TimeoutConfig(BaseModel):
    """Per-phase timeouts.

    Every one is non-zero. A missing connect timeout is how a single unreachable
    peer eventually consumes every worker in the process.

    ``total`` is the one that actually bounds a call: the per-phase timeouts are
    each measured from the start of *their* phase, so a peer that trickles a
    byte every four seconds satisfies a 5s read timeout forever. ``total`` is
    enforced by the client with ``asyncio.timeout``, and is also the value the
    request budget is compared against.
    """

    model_config = ConfigDict(extra="forbid")

    total: Duration = Field(default=timedelta(seconds=5), gt=timedelta(0))
    connect: Duration = Field(default=timedelta(seconds=2), gt=timedelta(0))
    read: Duration = Field(default=timedelta(seconds=5), gt=timedelta(0))
    write: Duration = Field(default=timedelta(seconds=5), gt=timedelta(0))
    pool: Duration = Field(default=timedelta(seconds=2), gt=timedelta(0))


class PoolConfig(BaseModel):
    """Connection pool limits, per peer."""

    model_config = ConfigDict(extra="forbid")

    max_connections: int = Field(default=100, ge=1)
    max_keepalive_connections: int = Field(default=20, ge=0)
    keepalive_expiry: Duration = Field(default=timedelta(seconds=5), ge=timedelta(0))

    @model_validator(mode="after")
    def _keepalive_within_total(self) -> PoolConfig:
        if self.max_keepalive_connections > self.max_connections:
            raise ValueError("max_keepalive_connections cannot exceed max_connections")
        return self


class PeerConfig(BaseModel):
    """One upstream service this service is allowed to call."""

    model_config = ConfigDict(extra="forbid")

    #: Scheme, host and port. A path is allowed and is prefixed onto every call.
    base_url: str = Field(min_length=1)

    #: The peer's real name, for the ``peer`` metric label and the span
    #: attribute. Defaults to the registry key with underscores turned back into
    #: hyphens, which is right for every service named as a DNS label.
    name: str = ""

    #: Overrides for this peer. Unset fields fall back to the top-level
    #: defaults, so a registry of ten peers needs one timeout block, not ten.
    timeout: TimeoutConfig | None = None
    pool: PoolConfig | None = None

    #: Sent on every request to this peer. For a static API key or a routing
    #: header — never for anything derived per-request.
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_scheme(self) -> PeerConfig:
        # Caught here rather than at first call: httpx would accept
        # "localhost:8081" as a *path* on a relative URL and fail with something
        # that reads nothing like "you forgot the scheme".
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError(f'base_url must start with http:// or https://, got "{self.base_url}"')
        return self


class ClientsConfig(BaseModel):
    """The ``clients`` section: defaults, and the registry of who may be called.

    An empty registry is the default and is not an error — most services call
    nothing.
    """

    model_config = ConfigDict(extra="forbid")

    timeout: TimeoutConfig = Field(default_factory=TimeoutConfig)
    pool: PoolConfig = Field(default_factory=PoolConfig)

    #: Appended to the service's own User-Agent. Set by the composition root
    #: from ``service.name`` and ``service.version``; not usually written in
    #: YAML.
    user_agent: str = ""

    #: Every upstream this service may call, keyed by underscored name.
    peers: dict[str, PeerConfig] = Field(default_factory=dict)

    def peer(self, name: str) -> PeerConfig:
        """Look a peer up by name, accepting either spelling.

        Raises :class:`~mint_client.errors.UnknownPeerError` naming what *is*
        configured. A typo should not require reading the YAML to diagnose.
        """
        key = name.replace("-", "_")
        found = self.peers.get(key)
        if found is None:
            known = ", ".join(sorted(self.peers)) or "none"
            raise UnknownPeerError(
                f'no peer "{name}" is configured (known peers: {known})', peer=name
            )
        return found

    def timeout_for(self, peer: PeerConfig) -> TimeoutConfig:
        """The effective timeouts for a peer: its own, or the shared default."""
        return peer.timeout or self.timeout

    def pool_for(self, peer: PeerConfig) -> PoolConfig:
        """The effective pool limits for a peer: its own, or the shared default."""
        return peer.pool or self.pool

    def peer_name(self, key: str) -> str:
        """The label to report a peer under."""
        peer = self.peers.get(key.replace("-", "_"))
        if peer is not None and peer.name:
            return peer.name
        return key.replace("_", "-")
