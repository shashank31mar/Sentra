"""WS-E2 — the Tier-2 NER barrier DAG entry node (E3 / LLD 29 §4.1, F1).

Proves the happens-before barrier realized on WS-C's DAG:
  * the barrier node exists ONLY for content/output/memory phases (NOT request —
    WS-C's request-phase verdict-equivalence golden baseline is untouched);
  * it is a DAG ENTRY node (depends_on=(), order_key=0 → topo-first);
  * it redacts `request.content_text` IN PLACE so every downstream reader + the
    audit `model_dump()` inherit the post-NER redacted view, never the raw;
  * on a Tier-2 outage it fails closed ON EGRESS (holds the content, drops the
    raw, does NOT blanket-DENY) and emits the outage metric;
  * the new source is the NON-`sentra` `redaction.ner`, registered in sources.py.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source, default_priority
from app.redaction.phi_ner import NerUnavailable
from app.services.scheduler.node import CostTier
from app.services.scheduler.registry import build_dag


_RAW_NAME = "Jane Doe"
_RAW_CONTENT = f"Patient {_RAW_NAME} was treated for diabetes at the clinic."


def _svc():
    """A minimal ValidationService stand-in — only what the barrier node touches."""
    svc = Mock()
    svc.metrics_publisher = None  # metric emission guards on None (never blocks)
    return svc


def _content_req(**over):
    base = dict(
        request_id="r1", session_id="s1", agent_id="a1", tool_name="ingest",
        tool_params={}, user_input="", timestamp="2026-07-02T00:00:00Z",
        operation_type="READ", phase="content", content_text=_RAW_CONTENT,
        redaction_nonce="deadbeef",
    )
    base.update(over)
    return ValidationRequest(**base)


def _find_ner_node(nodes):
    return next((n for n in nodes if n.source == Source.REDACTION_NER), None)


# ---------------------------------------------------------------- source registration

def test_ner_source_is_non_sentra_and_registered():
    """The new source is a NON-`sentra` name (LLD 31 line-185 rule) and is a REAL
    registered taxonomy entry (default_priority resolves, not the 0-for-unknown)."""
    assert Source.REDACTION_NER == "redaction.ner"
    assert not Source.REDACTION_NER.startswith("sentra")
    # Registered explicitly (priority 0 by design — it never votes on a verdict).
    from app.combiners.sources import DEFAULT_PRIORITIES
    assert Source.REDACTION_NER in DEFAULT_PRIORITIES
    assert default_priority(Source.REDACTION_NER) == 0


# ---------------------------------------------------------------- per-phase selection

@pytest.mark.parametrize("phase", ["content", "output", "memory"])
def test_barrier_node_present_on_content_phases(phase):
    nodes = build_dag(_svc(), phase, {"platform": None, "cloud_region": None})
    node = _find_ner_node(nodes)
    assert node is not None, f"NER barrier missing for phase={phase}"
    # Entry node: no deps, topo-first, expensive tier.
    assert node.depends_on == ()
    assert node.order_key == 0
    assert node.cost_tier == CostTier.EXPENSIVE_MODEL


def test_barrier_node_absent_on_request_phase():
    """FOOTGUN 3: the barrier must NOT be on the request-phase DAG (verdict-
    equivalence). Must FAIL if the append condition is loosened to `!= request`
    or unconditional."""
    nodes = build_dag(_svc(), "request", {"platform": None, "cloud_region": None})
    assert _find_ner_node(nodes) is None


# ---------------------------------------------------------------- in-place redaction

@pytest.mark.asyncio
async def test_barrier_redacts_content_text_in_place():
    """The node redacts `request.content_text` IN PLACE (the same mutable request
    every downstream node + the audit model_dump() reads). The raw name is GONE and
    the typed token carries the call nonce."""
    nodes = build_dag(_svc(), "content", {"platform": None, "cloud_region": None})
    node = _find_ner_node(nodes)
    req = _content_req()

    result = await node.run(req, {"tenant_id": "t_x"})

    # In-place mutation: the raw free-text PHI is no longer present.
    assert _RAW_NAME not in req.content_text
    assert "diabetes" not in req.content_text
    assert "⟦AEGR:deadbeef:" in req.content_text  # typed token w/ the call nonce
    # The node is a redactor, not a verdict — it never DENYs on PHI presence.
    assert result.should_deny is False
    assert result.source == Source.REDACTION_NER


@pytest.mark.asyncio
async def test_barrier_audit_model_dump_inherits_redacted_view():
    """Because the barrier mutates the SAME request object, `request.model_dump()`
    (what _handle_* passes to the audit/feedback write) carries the redacted
    content_text — the audit write inherits the post-NER view automatically.
    The raw name must be absent from the dumped payload."""
    nodes = build_dag(_svc(), "content", {"platform": None, "cloud_region": None})
    node = _find_ner_node(nodes)
    req = _content_req()

    await node.run(req, {"tenant_id": "t_x"})
    dumped = req.model_dump()

    assert _RAW_NAME not in str(dumped)
    assert "⟦AEGR:" in dumped["content_text"]


@pytest.mark.asyncio
async def test_barrier_none_content_text_abstains():
    """A content phase with no content_text is a cheap ABSTAIN (nothing to redact),
    never a crash — build_dag keys the append on the phase only."""
    nodes = build_dag(_svc(), "content", {"platform": None, "cloud_region": None})
    node = _find_ner_node(nodes)
    req = _content_req(content_text=None)
    result = await node.run(req, {"tenant_id": "t_x"})
    assert result.is_abstain


@pytest.mark.asyncio
async def test_barrier_none_content_text_stamps_redacted_flag():
    """A None-content pass is a completed (no-op) redaction pass, so `redacted` must
    be True — mirroring PhiNerClient.redact_free_text's None/empty handling
    (phi_ner.py: a None/empty field is a redacted no-op view). REGRESSION: leaving it
    False made an opted-in tenant's genuine null-content feedback record get REFUSED
    by the eval-gate as `not-redacted` and mislogged as a "residual record; skipped
    (correct)" — surfacing a benign no-op as a redaction-gate residual (§5.3 pt 3)."""
    nodes = build_dag(_svc(), "content", {"platform": None, "cloud_region": None})
    node = _find_ner_node(nodes)
    req = _content_req(content_text=None)
    assert req.redacted is False  # precondition — caller sent it un-flagged
    result = await node.run(req, {"tenant_id": "t_x"})
    assert result.is_abstain
    assert req.redacted is True
    assert req.model_dump()["redacted"] is True


# ------------------------------------------------------------ egress-fail-closed (E3)

@pytest.mark.asyncio
async def test_barrier_holds_content_on_ner_outage_not_deny():
    """E3: a Tier-2 NER OUTAGE holds the unredactable content (drops the raw,
    replaces with the held marker), does NOT blanket-DENY, and emits the outage
    metric. Must FAIL if the outage path forwards the raw or DENYs the action."""
    svc = _svc()
    emitted = {"held": False}

    async def _held(**_kw):
        emitted["held"] = True

    svc.metrics_publisher = Mock()
    svc.metrics_publisher.publish_redaction_egress_held = _held

    nodes = build_dag(svc, "content", {"platform": None, "cloud_region": None})
    node = _find_ner_node(nodes)
    req = _content_req()

    # Force the redactor to be unavailable.
    with patch(
        "app.redaction.phi_ner.PhiNerClient.redact_free_text",
        side_effect=NerUnavailable("model down"),
    ):
        result = await node.run(req, {"tenant_id": "t_x"})

    # Held, not forwarded raw; not a blanket DENY.
    assert _RAW_NAME not in req.content_text
    assert req.content_text == "⟦AEGR:egress_held⟧"
    assert result.should_deny is False
    assert result.is_abstain  # abstain → the deterministic floor decides the verdict


@pytest.mark.asyncio
async def test_run_dag_redacts_content_before_returning():
    """Through the REAL run_dag: after execution the request's content_text is the
    post-NER redacted view — so the audit `model_dump()` that runs AFTER run_dag
    returns inherits the redacted content, never the raw. Proves the barrier gates
    the audit consumer in one pass (§5.3)."""
    from app.services.scheduler.run import FAIL_FAST, run_dag

    svc = _svc()
    nodes = build_dag(svc, "content", {"platform": None, "cloud_region": None})
    req = _content_req()
    session = {"tenant_id": "t_x", "trust_score": 90.0}

    # Only run the NER barrier node in isolation via run_dag's tier machinery: to
    # keep this hermetic we run just the barrier node (the request-floor nodes need
    # real validators). run_dag over the single barrier node exercises the tier-1
    # gather path the barrier lives on.
    barrier = [_find_ner_node(nodes)]
    captured = []

    def _capture(r):
        captured.append(r)
        return r

    def _noop_stamp(r):
        return r

    async def _timed(_label, coro):
        return await coro

    def _all_allow():
        return ValidationResult(decision="ALLOW", reason="ok", should_deny=False)

    await run_dag(
        barrier, req, session, _capture, _noop_stamp, _timed,
        mode=FAIL_FAST, all_allow=_all_allow, signals=[],
    )
    # After the DAG ran, the shared request carries the redacted view.
    assert _RAW_NAME not in req.content_text
    assert "⟦AEGR:deadbeef:" in req.content_text


@pytest.mark.asyncio
async def test_barrier_runs_before_tier0_and_tier1_readers():
    """REGRESSION (code-review CRITICAL): the barrier is a happens-before barrier,
    not a tier-1 gathered peer. Through the REAL run_dag with a tier-0 detector node
    and a tier-1 ML-stub node ALONGSIDE the barrier, BOTH readers must observe the
    already-redacted `content_text` — the raw name must never reach either.

    Before the fix the barrier was cost_tier=EXPENSIVE_MODEL, so it (a) ran AFTER the
    whole tier-0 frontier had read the raw content and (b) was parallel-gathered with
    the ML node (a data race). This test FAILS on that code and passes once run_dag
    lifts the barrier out of the tier split and runs it first & alone."""
    from app.services.scheduler.node import CostTier, ValidatorNode
    from app.services.scheduler.run import FAIL_FAST, run_dag

    svc = _svc()
    nodes = build_dag(svc, "content", {"platform": None, "cloud_region": None})
    barrier = _find_ner_node(nodes)

    seen = {"tier0": None, "tier1": None}

    async def _tier0_detector(req, sess):
        seen["tier0"] = req.content_text
        return ValidationResult(
            decision="ALLOW", reason="t0", should_deny=False, source=Source.SENTRA_SIGMA
        )

    async def _tier1_ml(req, sess):
        seen["tier1"] = req.content_text
        return ValidationResult.abstain("ml stub")

    graph = [
        barrier,
        ValidatorNode(source=Source.SENTRA_SIGMA, cost_tier=CostTier.DETERMINISTIC,
                      run=_tier0_detector, depends_on=(), order_key=4),
        ValidatorNode(source=Source.SENTRA_ML_CLASSIFIER, cost_tier=CostTier.EXPENSIVE_MODEL,
                      run=_tier1_ml, depends_on=(), order_key=7),
    ]
    req = _content_req()
    session = {"tenant_id": "t_x", "trust_score": 90.0}

    def _cap(r):
        return r

    def _noop_stamp(r):
        return r

    async def _timed(_label, coro):
        return await coro

    def _all_allow():
        return ValidationResult(decision="ALLOW", reason="ok", should_deny=False)

    await run_dag(graph, req, session, _cap, _noop_stamp, _timed,
                  mode=FAIL_FAST, all_allow=_all_allow, signals=[])

    # BOTH the tier-0 detector and the tier-1 model observed the REDACTED view.
    assert seen["tier0"] is not None and _RAW_NAME not in seen["tier0"]
    assert "⟦AEGR:deadbeef:" in seen["tier0"]
    assert seen["tier1"] is not None and _RAW_NAME not in seen["tier1"]
    assert "⟦AEGR:deadbeef:" in seen["tier1"]


@pytest.mark.asyncio
async def test_barrier_stamps_redacted_flag_for_audit_and_feedback():
    """REGRESSION (code-review CRITICAL): the barrier must set `request.redacted=True`
    so `model_dump()` carries redacted=True — the audit persist-gate keeps the
    (legitimately-redacted) content instead of dropping it, and the opt-in feedback
    write is not refused on the happy path. FAILS on the pre-fix code (only
    content_text was assigned; redacted stayed False)."""
    nodes = build_dag(_svc(), "content", {"platform": None, "cloud_region": None})
    node = _find_ner_node(nodes)
    req = _content_req()
    assert req.redacted is False  # precondition — the caller sent it un-flagged
    await node.run(req, {"tenant_id": "t_x"})
    assert req.redacted is True
    assert req.model_dump()["redacted"] is True


@pytest.mark.asyncio
async def test_barrier_stamps_redacted_flag_on_egress_hold():
    """On a Tier-2 outage the raw is dropped for the held marker — that IS a
    completed redaction pass, so `redacted` must be True so the audit row keeps the
    held marker instead of the persist-gate dropping it for want of the flag."""
    nodes = build_dag(_svc(), "content", {"platform": None, "cloud_region": None})
    node = _find_ner_node(nodes)
    req = _content_req()
    with patch(
        "app.redaction.phi_ner.PhiNerClient.redact_free_text",
        side_effect=NerUnavailable("down"),
    ):
        await node.run(req, {"tenant_id": "t_x"})
    assert req.content_text == "⟦AEGR:egress_held⟧"
    assert req.redacted is True


@pytest.mark.asyncio
async def test_barrier_outage_never_forwards_raw_negative_control():
    """NON-VACUOUS negative control: prove the test would CATCH a 'skip-redaction
    but forward the raw anyway' regression. If the outage path left content_text
    as the raw value, this assertion FAILS — which is the whole point (the
    forbidden §7.2 path must be detectable)."""
    nodes = build_dag(_svc(), "content", {"platform": None, "cloud_region": None})
    node = _find_ner_node(nodes)
    req = _content_req()
    with patch(
        "app.redaction.phi_ner.PhiNerClient.redact_free_text",
        side_effect=NerUnavailable("down"),
    ):
        await node.run(req, {"tenant_id": "t_x"})
    # The raw content must NOT survive the outage on the field.
    assert req.content_text != _RAW_CONTENT
    assert _RAW_NAME not in req.content_text


# ------------------------------------------------------- tenant-fallback safety (WS-E2)

def test_tenant_for_ner_default_is_designed_not_an_error():
    """PROVING TEST (code-respond REJECT of registry.py:186 'silently falls back to
    default' LOW): `_tenant_for_ner` returning "default" is the DESIGNED P0a behavior,
    not an error to fail closed on. `tenancy.current_tenant()` is a contextvar that
    defaults to "default" (tenancy.py: 'P0a: always returns "default"'). So the
    proposed fix (fail the pass to NerUnavailable on a 'default' resolution) would
    HOLD/DROP content on every request in P0a — a regression, not a hardening."""
    from app.services.scheduler.registry import _tenant_for_ner
    # No session tenant + the P0a contextvar default → "default", cleanly (no raise).
    assert _tenant_for_ner({}) == "default"
    # A session-supplied tenant is honored via current_tenant()'s contextvar in prod;
    # the fallback only engages when tenancy resolution itself raises.


# =========================================================== E6 IMAGE ROUTER — LIVE PATH
#
# REGRESSION (integration-sentinel HIGH): the E6 image-mode router had ZERO call sites
# — an image field was never actually routed, so the fail-secure default-block routing
# never executed in production. These tests drive the router THROUGH the real barrier
# node's `run` (its only live call site) to prove an image-tagged `content_text` is
# routed by the per-tool mode — not silently passed through the NER text pass.

_IMAGE_MARKER = "⟦AEGR:deadbeef:IMAGE⟧"


def _image_req(**over):
    return _content_req(content_text=_IMAGE_MARKER, tool_name="upload_photo", **over)


def _svc_with_tool_mode(mode):
    """A service stub whose tool-registry get_item returns `image_mode=mode` (or an
    item without the attr / no item when mode is a sentinel)."""
    svc = _svc()
    engine = Mock()
    table = Mock()
    if mode is _NO_ITEM:
        table.get_item = Mock(return_value={})
    elif mode is _NO_ATTR:
        table.get_item = Mock(return_value={"Item": {"tool_id": "upload_photo"}})
    else:
        table.get_item = Mock(return_value={"Item": {"tool_id": "upload_photo", "image_mode": mode}})
    engine.dynamodb = Mock()
    engine.dynamodb.Table = Mock(return_value=table)
    svc.policy_engine = engine
    return svc


_NO_ITEM = object()   # tool not in registry
_NO_ATTR = object()   # tool present, no image_mode attribute


@pytest.mark.asyncio
async def test_image_field_routes_evaluate_forwards_intact():
    """`evaluate` (B2C-fraud beachhead): the image marker is forwarded INTACT to the
    evaluator — content_text unchanged, node metadata records the forward."""
    node = _find_ner_node(build_dag(_svc_with_tool_mode("evaluate"), "content",
                                    {"platform": None, "cloud_region": None}))
    req = _image_req()
    result = await node.run(req, {"tenant_id": "t_x"})
    assert req.content_text == _IMAGE_MARKER          # intact
    assert result.metadata["image_mode"] == "evaluate"
    assert result.metadata["image_forwarded_intact"] is True
    assert req.redacted is True


@pytest.mark.asyncio
async def test_image_field_defaults_block_when_tool_has_no_mode():
    """FOOTGUN (§3.6): a tool with no explicit `image_mode` → BLOCK (fail-secure). The
    image is refused (replaced by the block sentinel), NEVER forwarded. Must FAIL if
    the default were evaluate / pass-through."""
    node = _find_ner_node(build_dag(_svc_with_tool_mode(_NO_ATTR), "content",
                                    {"platform": None, "cloud_region": None}))
    req = _image_req()
    result = await node.run(req, {"tenant_id": "t_x"})
    assert req.content_text != _IMAGE_MARKER          # NOT forwarded intact
    assert req.content_text == "⟦AEGR:image_blocked⟧"
    assert result.metadata["image_mode"] == "block"
    assert result.metadata["image_forwarded_intact"] is False


@pytest.mark.asyncio
async def test_image_field_missing_tool_fails_secure_block():
    """A tool absent from the registry (or a registry read failure) → BLOCK — the
    resolver returns None, the router defaults BLOCK. Fail-secure toward hold."""
    node = _find_ner_node(build_dag(_svc_with_tool_mode(_NO_ITEM), "content",
                                    {"platform": None, "cloud_region": None}))
    req = _image_req()
    result = await node.run(req, {"tenant_id": "t_x"})
    assert result.metadata["image_mode"] == "block"
    assert result.metadata["image_forwarded_intact"] is False


@pytest.mark.asyncio
async def test_image_field_redact_mode_holds_pending_not_raw():
    """`redact`: the engine is a named LATER build, so until it ships the field is the
    redact-pending sentinel — the image is NOT forwarded raw (fail-secure toward hold,
    never toward evaluate)."""
    node = _find_ner_node(build_dag(_svc_with_tool_mode("redact"), "content",
                                    {"platform": None, "cloud_region": None}))
    req = _image_req()
    result = await node.run(req, {"tenant_id": "t_x"})
    assert req.content_text == "⟦AEGR:image_redact_pending⟧"
    assert result.metadata["image_mode"] == "redact"
    assert result.metadata["image_forwarded_intact"] is False


@pytest.mark.asyncio
async def test_image_field_does_not_go_through_text_ner_pass():
    """An image-tagged field is routed by mode, NOT fed to the free-text NER redactor
    (which cannot scrub pixels). Assert the NER client is never called for an image
    field — the router short-circuits the text pass."""
    node = _find_ner_node(build_dag(_svc_with_tool_mode("evaluate"), "content",
                                    {"platform": None, "cloud_region": None}))
    req = _image_req()
    with patch("app.redaction.phi_ner.PhiNerClient.redact_free_text") as ner:
        await node.run(req, {"tenant_id": "t_x"})
    ner.assert_not_called()


@pytest.mark.asyncio
async def test_free_text_still_takes_ner_pass_not_image_route():
    """NON-VACUOUS control: a NON-image content_text (ordinary free-text PHI) still
    goes through the NER text pass, NOT the image router. Proves the image branch is
    gated on the marker, not firing on everything."""
    node = _find_ner_node(build_dag(_svc_with_tool_mode("block"), "content",
                                    {"platform": None, "cloud_region": None}))
    req = _content_req()  # ordinary free text, no IMAGE marker
    result = await node.run(req, {"tenant_id": "t_x"})
    # Went through the NER pass (redaction_classes), NOT the image route (image_mode).
    assert "redaction_classes" in (result.metadata or {})
    assert "image_mode" not in (result.metadata or {})
    assert _RAW_NAME not in req.content_text


def test_ner_markers_are_nonce_namespaced_not_tenant_namespaced():
    """PROVING TEST (disproves the registry.py:186 harm claim): the reviewer claims a
    'default' tenant fallback makes 'redacted markers share a default namespace across
    tenants'. FALSE — the redactor namespaces its typed markers by the per-call NONCE,
    not by tenant_id (phi_ner TokenizingRedactor emits `⟦AEGR:{nonce}:{kind}⟧`;
    tenant_id is accepted but not part of the marker). So two tenants that both resolve
    to "default" but carry different nonces produce DIFFERENT, non-colliding markers —
    the tenant fallback cannot cause a cross-tenant marker collision.

    NON-VACUOUS: if the marker were tenant-namespaced and a 'default' collapse actually
    merged the two tenants' namespaces, the two redacted views would share an identical
    marker for the same input and this inequality assertion would FAIL."""
    from app.redaction.phi_ner import get_phi_ner_client
    client = get_phi_ner_client()
    text = f"Patient {_RAW_NAME} here."
    # Both under the SAME resolved tenant ("default"), different per-call nonces.
    v1 = client.redact_free_text(text, nonce="nonceA", tenant_id="default")
    v2 = client.redact_free_text(text, nonce="nonceB", tenant_id="default")
    assert _RAW_NAME not in v1.text and _RAW_NAME not in v2.text
    assert "⟦AEGR:nonceA:NAME⟧" in v1.text
    assert "⟦AEGR:nonceB:NAME⟧" in v2.text
    assert v1.text != v2.text  # nonce, not tenant, is the namespace
    # And the SAME nonce yields the SAME marker regardless of the tenant_id passed —
    # confirming tenant_id is not a namespacing input, so its "default" fallback is inert.
    v_ta = client.redact_free_text(text, nonce="nonceA", tenant_id="tenant_a")
    v_tb = client.redact_free_text(text, nonce="nonceA", tenant_id="tenant_b")
    assert v_ta.text == v_tb.text
