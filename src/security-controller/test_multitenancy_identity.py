"""Package-root collection shim for the WS-G G1.3 (FR-13.1) identity regression.

The canonical test bodies + the ``mt_env`` moto fixture live in
``tests/test_multitenancy_identity.py`` (the existing multi-tenancy identity
suite, per ws-g-backend.md §B3/G1.3). The resolved unit-test command enumerates
``test_multitenancy_identity.py`` as a bare package-root path, so this shim
re-exposes the WS-G-owned test + the fixtures it depends on at the package root.
pytest collects the imported ``test_*`` function here and resolves its fixtures
from the names imported into this module's namespace.

Not a duplicate implementation — a single source of truth (tests/) surfaced at
both collection paths.
"""
from tests.test_multitenancy_identity import (  # noqa: F401 — re-exported for root collection
    FakeRequest,
    mt_env,
    test_resolution_uses_membership_not_email_domain,
)
