"""Cedar authorization for the Sentra policy pipeline (feature: cedar-policy).

In-process Cedar engine (CT01 build-spike → `cedarpy==4.8.4` wheel, no sidecar).
This package owns the Sentra-owned Cedar schema, the thin evaluator wrapper, and
the policy-engine adapter that reproduces the legacy signal contract.
"""
