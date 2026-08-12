# Archived — folded into Bondhive

2026-08-12: PROOF is archived. Its live dashboard pattern (zero-dependency
Python HTTP server, `/api/*` JSON endpoints, client-side live fetch — see
`dashboard/dashboard.py`) has been ported into
[bondhive](https://github.com/cryptonomicsed-byte/bondhive)'s
`web/dashboard.py`, adapted to Bondhive's own data model (pool/score/bonds)
and visual design.

PROOF's on-chain signing was never real (empty signature stub in the Solana
program) — that part was not carried forward. Bondhive's `core/` crate has
real BIP-340 Schnorr signing (see `bondhive-core`), tested.

No further development happens in this repository.
