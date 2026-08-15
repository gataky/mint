// Package memory implements the repository interfaces declared in
// internal/service, backed by a map.
//
// It is the real implementation at runtime and the fake in tests — there is
// only one, so the thing the tests exercise is the thing that runs.
//
// One file per resource, mirroring internal/service. A Postgres implementation
// would be a sibling package (internal/repository/postgres) selected by the
// composition root; nothing outside internal/repository would change, because
// the interfaces live with their consumer.
package memory

import (
	"context"

	"{@ module_path @}/internal/domain"
)

// checkContext reports a cancelled request before doing any work.
//
// A map lookup cannot block, so this is not about responsiveness — it is so
// that a handler which has already given up does not go on to mutate state, and
// so the signature is honest about respecting the deadline it was given.
func checkContext(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return domain.Internal(err, "request cancelled")
	}
	return nil
}
