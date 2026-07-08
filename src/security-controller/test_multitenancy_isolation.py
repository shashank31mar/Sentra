"""Package-root collection shim for the WS-G G1.3 (FR-13.1) isolation regression.

Canonical bodies + the ``mt_env`` moto fixture live in
``tests/test_multitenancy_isolation.py`` (per ws-g-backend.md §B3/G1.3). The
resolved unit-test command lists ``test_multitenancy_isolation.py`` as a bare
package-root path; this shim re-exposes the WS-G-owned isolation test + its
fixture at the package root so that path resolves and runs the same test.
"""
from tests.test_multitenancy_isolation import (  # noqa: F401 — re-exported for root collection
    mt_env,
    test_domain_matching_tenant_never_auto_bound,
)
