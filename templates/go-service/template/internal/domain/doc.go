// Package domain holds the entities and the error taxonomy. It is the innermost
// layer: it imports nothing from the rest of the service, and everything else
// imports it.
//
// One file per resource. Adding a resource means adding a file here, a file in
// internal/service, one in internal/repository/memory, and one in
// internal/transport/http.
//
// The entities carry `json` and OpenAPI struct tags, so one type serves as both
// the domain model and the wire format. That is deliberate for a service
// starting out: a second set of transport DTOs is real work and buys nothing
// until the two shapes actually need to differ. When they do — an internal
// field that must not be published, or a wire format that must stay stable
// across a rename — introduce DTOs in internal/transport/http and map to them
// there, rather than distorting the entity to serve both.
package domain
