"""Vendored subset of the ``aegion_guard`` SDK for the Azure Function edge.

This is NOT the full SDK package. The Azure Function (``function_app.py``) is
stdlib-only BY DESIGN — Azure B1 Linux Oryx Remote Build does not reliably
pip-install dependencies (lesson learned WS15 M3, 2026-05-23), so the SDK cannot
be a ``requirements.txt`` dependency. We therefore VENDOR only the two modules
the edge needs to redact structured PII/PCI out of the ``/v1/validate`` payload
BEFORE it egresses (FR-3.13; LLD 29 §3 / WS-E1), mirroring the way the SDK
itself vendors unchanged into a Lambda zip / Azure Function (LLD 23 §2):

    aegion_guard/
        __init__.py      <- this minimal shim (makes the dir a package so
                            redaction.py's ``from .exceptions import ...`` resolves)
        redaction.py     <- BYTE-IDENTICAL copy of the audited Tier-1 redactor
        exceptions.py    <- BYTE-IDENTICAL copy (provides RedactionError)

Deliberately empty of imports: the full SDK ``__init__`` pulls in adapters /
config / guard / identity (which carry runtime deps and heavy surface area we do
NOT want on the edge). Keeping this shim import-free means the vendored redactor
stays stdlib-only and the two ``.py`` files remain byte-for-byte identical to the
on-main SDK versions — the same audited code, verifiable by ``shasum``.

To re-sync after an SDK redactor change, re-copy those two files verbatim from
``demo-agents/sdk/aegion-guard-python/src/aegion_guard/{redaction,exceptions}.py``
and re-verify the checksums; do not hand-edit the vendored copies.
"""
