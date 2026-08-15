// Package service holds the business logic. It takes and returns domain types:
// no http.Request, no huma types, no driver types. The transport layer calls
// into it; it never calls back out.
//
// One file per resource. Each declares the repository interface it needs — the
// consumer owns the interface — and the composition root injects an
// implementation.
package service

import (
	"crypto/rand"
	"encoding/hex"
	"time"
)

// Clock returns the current time. Injected so tests get deterministic output
// without touching the machine clock.
type Clock func() time.Time

// IDGenerator returns a new unique identifier.
type IDGenerator func() string

// SystemClock is the real clock, truncated to milliseconds because that is the
// precision the API publishes.
func SystemClock() time.Time {
	return time.Now().UTC().Truncate(time.Millisecond)
}

// RandomID returns a 16-character hex identifier.
func RandomID() string {
	buf := make([]byte, 8)
	// crypto/rand.Read cannot fail as of Go 1.24; it panics instead.
	_, _ = rand.Read(buf)
	return hex.EncodeToString(buf)
}
