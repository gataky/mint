"""Repository implementations.

The interfaces these satisfy are ``Protocol`` declarations in ``service/``,
because the consumer owns the interface. Nothing here is imported by the service
layer — only by the composition root, which chooses which implementation to
inject.

``memory`` is the only implementation today. A Postgres one would be a sibling
package selected by the composition root, and nothing outside this directory
would change.
"""
