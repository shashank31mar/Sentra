"""Server-side image mode router `{evaluate|redact|block}` — WS-E2 / LLD 29 §3.6.

Image content is NOT handled at the edge (a Tesseract binary + OCR/vision model
cannot vendor into the stdlib-only SDK zip, §3.1) and is NOT a blanket "refuse
every image". A field the edge tagged as binary/image routes to a per-tool /
per-customer MODE resolved server-side:

  * `evaluate` (REQUIRED — B2C-fraud beachhead): pass the image INTACT, un-redacted
    to the fraud/threat evaluator (damaged-goods / insurance / return photos — the
    evaluator must see the pixels).
  * `redact`: route to the server-side image-redact pipeline — the ENGINE
    (Tesseract + Presidio image-redactor) is the named LATER build (out of scope
    here), plus two steps it does NOT cover: (1) FACES (Presidio image-redactor is
    text-only — needs Rekognition/Google DLP); (2) DICOM metadata PHI (a distinct
    metadata pass). This WS ships the mode CONTRACT + `evaluate`/`block` routing.
  * `block` (DEFAULT, fail-secure): refuse egress / pass-through per policy.

FOOTGUN (§3.6): default `block`, NEVER default `evaluate` — a default-evaluate
would pass raw pixels for a tool that never intended it. An unresolvable mode
fails toward `block` (tenet 1).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ImageMode(str, Enum):
    """The per-tool image-handling mode (LLD 29 §3.6). String values are the wire /
    tool-registry contract (`image_mode` field / Cedar attribute)."""

    EVALUATE = "evaluate"
    REDACT = "redact"
    BLOCK = "block"


# The only steps the later `redact`-mode engine will NOT cover — named so they are
# not silently assumed done (§3.6 / E6.3).
REDACT_ENGINE_GAPS = ("faces", "dicom_metadata")

# The fail-secure default (§3.6 FOOTGUN): a tool with no explicit mode, or an
# unresolvable/invalid mode, resolves to BLOCK — never EVALUATE.
DEFAULT_IMAGE_MODE = ImageMode.BLOCK


def resolve_image_mode(raw_mode: Optional[str]) -> ImageMode:
    """Resolve a tool's configured `image_mode` string to an :class:`ImageMode`.

    `raw_mode` is the per-tool tool-registry field (or Cedar attribute, §3.6). A
    None / unknown / malformed value fails toward :data:`DEFAULT_IMAGE_MODE`
    (`block`) — fail-secure (tenet 1). This is the single resolution point so the
    default can never be `evaluate` by omission (the §3.6 FOOTGUN)."""
    if raw_mode is None:
        return DEFAULT_IMAGE_MODE
    try:
        return ImageMode(str(raw_mode).strip().lower())
    except ValueError:
        logger.warning("unresolvable image_mode %r → fail-secure BLOCK", raw_mode)
        return DEFAULT_IMAGE_MODE


def route_image_field(raw_mode: Optional[str]) -> ImageMode:
    """Alias of :func:`resolve_image_mode` for the pipeline call site (the server-
    side image-field router). Returns the resolved mode; the caller then:
      * EVALUATE → forward the image intact to the fraud/threat evaluator;
      * REDACT   → route to the server-side image-redact pipeline (engine = later);
      * BLOCK    → refuse egress / pass-through per policy (fail-secure default).
    """
    return resolve_image_mode(raw_mode)


# ============================================================================
# The LIVE router — E6.2/E6.3, invoked on the content path (registry.py NER
# barrier node). The Tier-1 edge tagged a whole-value image/binary blob to an
# `⟦AEGR:{nonce}:IMAGE⟧` marker (SDK redaction.py `_maybe_blob_type` → IMAGE) and
# routed it here. This is where the marker is DETECTED in `content_text`, the
# per-tool mode is RESOLVED (default `block`), and the field is TRANSFORMED per
# the resolved behavior. Without this call site the E6 fail-secure default-block
# routing never executes on a real image field (integration-sentinel HIGH gap).
# ============================================================================

# The Tier-1 IMAGE marker grammar (mirrors the SDK `_wire_token(nonce, "IMAGE")`
# grammar `⟦AEGR:{nonce}:IMAGE⟧` and the nonce-less `⟦AEGR:IMAGE⟧`). Case-sensitive
# on the `IMAGE` class — the wire types are upper-case by construction (SDK
# redaction.py). A `content_text` carrying at least one such marker IS an image
# field the mode router governs.
_IMAGE_MARKER = re.compile(r"⟦AEGR:(?:[^⟧:]*:)?IMAGE⟧")

# What the router writes into `content_text` when the resolved mode is NOT
# `evaluate`. NEVER a raw pixel/base64 value (the raw was already dropped at the
# edge — only the marker travels). These are visible, auditable sentinels so the
# audit row records "an image was withheld / queued", not a silent hole.
_IMAGE_BLOCK_MARKER = "⟦AEGR:image_blocked⟧"     # BLOCK (fail-secure default)
_IMAGE_REDACT_PENDING = "⟦AEGR:image_redact_pending⟧"  # REDACT (engine = later build)


def content_has_image(content_text: Optional[str]) -> bool:
    """True iff `content_text` carries at least one Tier-1 `IMAGE` marker — i.e.
    the edge tagged a whole-value image/binary blob into this field (E6.1). Only
    then does the mode router run; ordinary free-text content is untouched (it
    flows to the Tier-2 NER pass instead)."""
    if not content_text:
        return False
    return _IMAGE_MARKER.search(content_text) is not None


@dataclass(frozen=True)
class ImageRouteResult:
    """The outcome of routing an image-tagged `content_text` (E6.2).

    Attributes:
        mode: the resolved :class:`ImageMode` (`block` on any unresolvable input).
        content_text: the field AFTER routing — INTACT for `evaluate`, the
            block/redact-pending sentinel for `block`/`redact`. NEVER a raw value.
        forwarded_intact: True ONLY for `evaluate` (the pixels reach the evaluator).
            Its inverse is the fail-secure guarantee: `block`/`redact` never egress
            the image onward from here.
    """

    mode: ImageMode
    content_text: Optional[str]
    forwarded_intact: bool


def route_image_content(content_text: Optional[str], *, raw_mode: Optional[str]) -> ImageRouteResult:
    """Route an image-tagged `content_text` by the per-tool resolved mode (E6.2).

    `raw_mode` is the tool's configured `image_mode` (tool-registry field / Cedar
    attribute); it is resolved fail-secure (default/unresolvable → `block`, §3.6
    FOOTGUN) via :func:`resolve_image_mode`. Behavior by mode:

      * `evaluate` (REQUIRED — B2C-fraud beachhead): the image is forwarded INTACT
        (`content_text` unchanged, `forwarded_intact=True`) to the fraud/threat
        evaluator — the ONLY mode that passes pixels through.
      * `redact`: routed to the server-side image-redact pipeline whose engine is a
        named LATER build (Tesseract + Presidio, plus the faces + DICOM-metadata
        gaps in :data:`REDACT_ENGINE_GAPS`); until that engine ships, the field is
        replaced by :data:`_IMAGE_REDACT_PENDING` — the image is NOT forwarded raw
        (fail-secure toward hold, never toward evaluate).
      * `block` (DEFAULT, fail-secure): the field is replaced by
        :data:`_IMAGE_BLOCK_MARKER`; the image is refused (never egressed).

    The caller (the content-path barrier) sets `request.content_text` to the
    returned value; `evaluate` leaves it intact for the evaluator, the other two
    leave only an auditable sentinel (the raw was already dropped at the edge)."""
    mode = resolve_image_mode(raw_mode)
    if mode is ImageMode.EVALUATE:
        return ImageRouteResult(mode=mode, content_text=content_text, forwarded_intact=True)
    if mode is ImageMode.REDACT:
        # The redact-mode engine is the named later build; hold behind the sentinel
        # until it ships — do NOT forward the (edge-dropped) image, do NOT fall
        # through to evaluate. `content_text` here is only the marker anyway.
        return ImageRouteResult(mode=mode, content_text=_IMAGE_REDACT_PENDING, forwarded_intact=False)
    # BLOCK (fail-secure default / unresolvable): refuse egress.
    return ImageRouteResult(mode=ImageMode.BLOCK, content_text=_IMAGE_BLOCK_MARKER, forwarded_intact=False)


def resolve_tool_image_mode(service, tool_name: Optional[str]) -> Optional[str]:
    """Read the per-tool `image_mode` from the tool registry (E6.3), fail-secure.

    The mode is a tool-registry `Item` attribute (`image_mode {redact|evaluate|
    block}`) — the SAME `sentra-tool-registry` table `policy_validator`/
    `agent_service` read (`get_item(Key={'tool_id': ...})`). This returns the RAW
    string (or None) for :func:`resolve_image_mode`/:func:`route_image_content` to
    resolve; ANY failure (no registry, missing tool, missing attribute, read error)
    returns None → the caller defaults to `block` (§3.6 FOOTGUN — a resolution
    hiccup must never fall open to `evaluate`). The lookup is best-effort and only
    runs when an image marker is actually present, so it never taxes the text path."""
    if not tool_name:
        return None
    try:
        from app.config import settings

        engine = getattr(service, "policy_engine", None)
        dynamodb = getattr(engine, "dynamodb", None)
        if dynamodb is None:
            return None
        # `sentra-tool-registry` is keyed by the plain `tool_id` (NOT tenancy-scoped)
        # — the same table + key policy_validator/agent_service read.
        registry = dynamodb.Table(settings.dynamodb_tool_registry_table)
        resp = registry.get_item(Key={"tool_id": tool_name})
        item = resp.get("Item") if resp else None
        if not item:
            return None
        return item.get("image_mode")
    except Exception:  # noqa: BLE001 — fail-secure: any hiccup → None → caller BLOCKs
        logger.debug("tool image_mode lookup failed for tool=%s; fail-secure BLOCK", tool_name)
        return None
