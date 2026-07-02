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
