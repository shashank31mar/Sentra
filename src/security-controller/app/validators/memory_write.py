"""D3 — memory-integrity validator (memory phase).

WS-L / LLD 32 §5.3 / FR-3.9. Runs on `phase=memory` as a tier-1 `ValidatorNode`
(`Source.SENTRA_MEMORY`) at the memory-WRITE chokepoint. Guards the agent's
long-term memory against poisoning: a malicious memory-write that would later
loosen the agent's own security posture (grant a tool, raise a limit, skip a
check) or self-promote an untrusted source into a trusted directive.

Guards are STRUCTURAL / METADATA (not value-dependent — they hold over the
REDACTED memory candidate, SEC-4):
  * provenance mandatory        — a write with no provenance DENYs.
  * untrusted cannot self-promote — trust_weight ≤ 0.3 cap on untrusted-sourced
                                    memory (an ingested/tool-sourced memory cannot
                                    claim operator-level trust).
  * memory tightens, never loosens — a write expanding `allowed_tools`, raising a
                                    limit, or skipping a check → MEMORY_POISONING.
  * signed + tamper-evident      — a MAC over the CANONICALIZED immutable birth
                                    facts (KMS GenerateMac/VerifyMac when available,
                                    local HMAC otherwise). Re-verify must survive a
                                    byte-different-but-logically-identical candidate
                                    (canonicalize BEFORE hash/MAC — the named
                                    footgun) and must FAIL a genuinely tampered one.
  * decay-bounded per-kind       — short TTL for AGENT_INFERENCE, long/none for
                                    OPERATOR_DIRECTIVE.

Live-enforce, FP/precision-gated (R5-C) — same mechanism as D2. Read-path stays
OFF (`AGENT_MEMORY_READ_ENABLED=false`); no read-path check is built here.
A no-denier memory run fails secure to DENY via the phase-aware `all_allow`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import unicodedata
from typing import Any, Dict, Optional

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source

logger = logging.getLogger(__name__)

REASON_MEMORY = "MEMORY_POISONING"

# Untrusted-sourced memory cannot claim more than this trust weight (self-promotion
# cap, LLD 32 §5.3). An ingested/tool-sourced memory that asserts a higher weight is
# trying to promote itself into a trusted directive.
UNTRUSTED_TRUST_CAP = 0.3

# Per-kind decay bounds (seconds). A short-lived inference must not persist as long
# as an operator directive (LLD 32 §5.3 decay-bounded).
_DECAY_TTL_SECONDS = {
    "AGENT_INFERENCE": 3600,          # 1h
    "TOOL_OUTPUT": 86_400,            # 1d
    "OPERATOR_DIRECTIVE": None,       # long/none
}

# The self-promotion cap is DEFAULT-UNTRUSTED (fail-secure): EVERY write is capped
# at UNTRUSTED_TRUST_CAP unless its provenance is in this small server-recognized
# TRUSTED allowlist. Keying the cap on an "is this source in an UNTRUSTED denylist?"
# check is a bypass — `provenance.source` rides in the attacker-controlled request
# payload, so any string OUTSIDE a denylist (e.g. "operator"/"system"/"user") would
# skip the cap and self-promote to trust_weight 1.0. Default-untrusted closes that:
# an unrecognized/self-asserted label is treated as untrusted and capped.
#
# NOTE (design): membership here is a *recognized-trusted label*, NOT a proof of
# trust. The durable fix (SEC / engineering.md "never trust external data") is to
# derive the trusted determination from a SERVER-ATTESTED provenance stamp (the
# verified identity-gate anchor), never a self-declared label; this allowlist is the
# fail-secure floor until that server-set stamp exists. Do NOT widen it to accept an
# arbitrary caller-supplied string — in particular the bare "operator"/"system"/"user"
# labels a poisoning attacker sets are NOT trusted (they are not server-attested).
_TRUSTED_SOURCES = frozenset({"operator_directive"})


def _canonicalize(value: Any) -> bytes:
    """Deterministic byte encoding for hashing/MAC — the NAMED footgun (LLD 32
    §5.3): the SAME logical memory must hash/MAC identically regardless of Unicode
    form, whitespace, or JSON key order, else re-verify spuriously fails. Normalize
    Unicode (NFC), collapse insignificant whitespace in strings, and sort JSON keys.
    Determinism holds over the REDACTED view (D3 reads content_text post-NER).
    """
    def _norm(v: Any) -> Any:
        if isinstance(v, str):
            # NFC-normalize then collapse runs of whitespace to a single space and
            # strip — the same logical string in a different form canonicalizes equal.
            return " ".join(unicodedata.normalize("NFC", v).split())
        if isinstance(v, dict):
            return {k: _norm(v[k]) for k in sorted(v)}
        if isinstance(v, (list, tuple)):
            return [_norm(x) for x in v]
        return v

    return json.dumps(_norm(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def compute_mac(birth_facts: Dict[str, Any], *, kms_client=None, key_id: Optional[str] = None) -> str:
    """MAC over the canonicalized immutable birth facts (LLD 32 §5.3).

    Prefers KMS `GenerateMac` (HMAC_SHA_256) when a client + key are supplied
    (production, in-VPC); falls back to a local HMAC over a fixed dev key so the
    integrity check is exercisable offline. Both operate on the SAME canonical bytes
    so a KMS-signed birth fact re-verifies against a local computation of the same
    canonical form.
    """
    message = _canonicalize(birth_facts)
    if kms_client is not None and key_id:
        resp = kms_client.generate_mac(
            KeyId=key_id, MacAlgorithm="HMAC_SHA_256", Message=message,
        )
        return resp["Mac"].hex() if isinstance(resp["Mac"], (bytes, bytearray)) else str(resp["Mac"])
    # A KMS client configured but NO key_id is a MISCONFIG on the enforce path — do
    # NOT silently fall back to the offline dev key (that would let a KMS-mode
    # deployment authenticate a self-forgeable MAC). Fail secure.
    if kms_client is not None:
        raise ValueError("KMS client configured but no key_id — refusing local dev-key MAC fallback")
    # Local HMAC fallback (dev / offline ONLY). The key is a fixed, non-secret dev
    # key: it is offline-forgeable by anyone, so it is NEVER authoritative in an
    # enforce decision (that path requires KMS above). Its only job offline is to
    # exercise the CANONICALIZATION determinism, not key custody.
    return hmac.new(b"sentra-memory-integrity-dev", message, hashlib.sha256).hexdigest()


def verify_mac(birth_facts: Dict[str, Any], expected_mac: str, *, kms_client=None,
               key_id: Optional[str] = None) -> bool:
    """Constant-time compare of the recomputed MAC against `expected_mac`.

    Fail-secure: when a KMS client is configured (prod/enforce) the recompute goes
    through the KMS `GenerateMac` path — a self-forgeable local dev-key MAC is never
    accepted as authentic here. If the KMS recompute cannot be performed (misconfig
    / KMS error) the verification FAILS rather than falling back to the dev key.
    """
    try:
        recomputed = compute_mac(birth_facts, kms_client=kms_client, key_id=key_id)
    except Exception:  # noqa: BLE001 — KMS misconfig/error on an enforce verify → fail secure
        logger.warning("MAC recompute failed; failing verification secure")
        return False
    return hmac.compare_digest(recomputed, expected_mac)


class MemoryWriteValidator:
    """D3 memory-write integrity guard — LLD 32 §5.3.

    Reads the memory candidate off `ValidationRequest.tool_params["memory"]` (the
    memory-write payload) + the REDACTED `content_text`. Guards are structural.
    """

    def __init__(self, service=None, kms_client=None, kms_key_id: Optional[str] = None):
        self._service = service
        self._kms = kms_client
        self._key_id = kms_key_id

    async def validate(self, req: ValidationRequest) -> ValidationResult:
        memory = self._extract_memory(req)
        if memory is None:
            # No memory-write payload to inspect — abstain (the phase-aware
            # all_allow fails secure to DENY when no node decides).
            return ValidationResult.abstain("memory_write: no memory candidate")

        # 1) provenance mandatory.
        provenance = memory.get("provenance")
        if not provenance:
            return self._deny("memory write lacks provenance")

        # 2) untrusted cannot self-promote (DEFAULT-UNTRUSTED, fail-secure).
        #    The cap applies to EVERY write whose provenance is NOT a recognized
        #    trusted label — an attacker-set "operator"/"system"/"user"/unknown
        #    string is untrusted and capped (closing the denylist bypass where any
        #    label outside a closed untrusted set skipped the cap).
        source = str(provenance.get("source", "")).lower()
        trust_weight = memory.get("trust_weight")
        source_is_trusted = source in _TRUSTED_SOURCES
        if not source_is_trusted and trust_weight is not None:
            try:
                if float(trust_weight) > UNTRUSTED_TRUST_CAP:
                    return self._deny(
                        f"untrusted/unattested-sourced memory ({source!r}) claims "
                        f"trust_weight {trust_weight} > cap {UNTRUSTED_TRUST_CAP}"
                    )
            except (TypeError, ValueError):
                return self._deny(f"memory trust_weight not numeric: {trust_weight!r}")

        # 3) memory tightens, never loosens security.
        loosen = self._loosens_security(memory)
        if loosen:
            return self._deny(f"memory write loosens security: {loosen}")

        # 4) tamper-evidence — the MAC is MANDATORY for any write that ASSERTS
        #    elevated trust (a trusted-label write claiming trust_weight above the
        #    untrusted cap), never optional. Omitting `mac`/`birth_facts` must NOT
        #    skip the integrity gate (that is a fail-open where a poisoning attacker
        #    just drops the field). A write that carries a MAC is always re-verified.
        birth_facts = memory.get("birth_facts")
        claimed_mac = memory.get("mac")
        try:
            asserts_elevated_trust = (
                source_is_trusted
                and trust_weight is not None
                and float(trust_weight) > UNTRUSTED_TRUST_CAP
            )
        except (TypeError, ValueError):
            return self._deny(f"memory trust_weight not numeric: {trust_weight!r}")
        if asserts_elevated_trust and (birth_facts is None or claimed_mac is None):
            return self._deny(
                "elevated-trust memory write must carry a birth-fact MAC "
                "(missing mac/birth_facts — integrity gate is mandatory, not skip)"
            )
        if birth_facts is not None and claimed_mac is not None:
            # Never accept a self-forgeable LOCAL-dev-key MAC as authentic in an
            # enforce decision: when a KMS client is configured (prod/enforce),
            # authenticity REQUIRES the KMS VerifyMac path. The local HMAC fallback
            # (fixed dev key, offline-forgeable) is dev/offline-only and must not
            # decide a security verdict when KMS is available.
            if not verify_mac(birth_facts, claimed_mac, kms_client=self._kms, key_id=self._key_id):
                return self._deny("memory birth-fact MAC verification failed (tampered)")

        # 5) decay-bounded per-kind: an unbounded TTL on a decaying kind is a poison
        #    tell (a fleeting inference masquerading as a durable directive).
        kind = str(memory.get("kind", "")).upper()
        if kind in _DECAY_TTL_SECONDS:
            bound = _DECAY_TTL_SECONDS[kind]
            ttl = memory.get("ttl_seconds")
            if bound is not None and ttl is not None:
                try:
                    if float(ttl) > bound:
                        return self._deny(
                            f"memory kind {kind} ttl {ttl}s exceeds decay bound {bound}s"
                        )
                except (TypeError, ValueError):
                    return self._deny(f"memory ttl_seconds not numeric: {ttl!r}")

        # Well-formed, provenance-bearing memory write → ALLOW (a real decider).
        return ValidationResult(
            decision="ALLOW",
            reason="memory_write: integrity guards passed",
            should_deny=False,
            source=Source.SENTRA_MEMORY,
        )

    # ------------------------------------------------------------------ helpers
    def _extract_memory(self, req: ValidationRequest) -> Optional[Dict[str, Any]]:
        params = getattr(req, "tool_params", None) or {}
        mem = params.get("memory")
        return mem if isinstance(mem, dict) else None

    def _loosens_security(self, memory: Dict[str, Any]) -> Optional[str]:
        """A memory write that EXPANDS the agent's permissions is poisoning
        (memory tightens, never loosens — LLD 32 §5.3)."""
        effects = memory.get("effects") or {}
        if not isinstance(effects, dict):
            return "malformed effects block"
        if effects.get("expand_allowed_tools") or effects.get("add_tools"):
            return "expands allowed_tools"
        if effects.get("raise_limit") or effects.get("increase_limit"):
            return "raises a limit"
        if effects.get("skip_check") or effects.get("disable_check"):
            return "skips a check"
        return None

    def _deny(self, detail: str) -> ValidationResult:
        return ValidationResult(
            decision="DENY",
            reason=f"{REASON_MEMORY}: {detail}",
            violation_type=REASON_MEMORY,
            threat_type=REASON_MEMORY,
            should_deny=True,
            source=Source.SENTRA_MEMORY,
            confidence=1.0,
        )
