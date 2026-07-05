"""
Sigma Rule Engine - Step 3 of Validation Pipeline

Detects threat patterns in user input using Sigma rules.
Implements in-memory caching for performance.

Requirements: LLD 03 Section 3.2.1, 8.1
"""
import asyncio
import logging
import threading
import time
from typing import List, Dict, Optional

import boto3
import yaml
from botocore.exceptions import ClientError

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.config import settings
from app.utils.clients import get_clients
from app.validators._signal_stamp import stamps
from app.validators import sigma_dialect
from app.validators.sigma_dialect import (
    Condition,
    DialectError,
    Selection,
    compile_selections,
    parse_condition,
)
from app.validators.threat_type_remap import derive_threat_type

logger = logging.getLogger(__name__)

# WS24 M3.2: the cross-instance rule-set version lives as a single item in the
# sigma metadata table. Any enforcement-affecting CRUD bumps it; every task polls
# it (throttled) and reloads when it moves.
_SIGMA_VERSION_ITEM_ID = "__sigma_version__"

# WS-F §6d: HARD cap on total matchers across the whole ruleset (fat-corpus DoS).
_MATCHERS_PER_RULESET = sigma_dialect.DEFAULT_MATCHERS_PER_RULESET

# WS-F §12/§6c: stale-pin page thresholds — page (not WARN-log) when the engine
# serves a last-known-good ruleset across N consecutive failed reloads OR > T
# seconds since the last successful compile.
_STALE_PIN_MAX_CONSEC_FAILS = 3
_STALE_PIN_MAX_STALE_SECONDS = 30 * 60  # 30 minutes


class SigmaRulesLoadError(Exception):
    """Raised when Sigma rules cannot be loaded"""
    pass


class SigmaRule:
    """Represents a parsed prompt-signature rule (WS-F closed dialect, lld/35 §4).

    Grown ADDITIVELY (lld/35 §4.1): `selections` + `condition` carry the compiled
    dialect (matched on the hot path via the boolean-AST fold); `patterns` is
    retained (the flat list of raw `|contains`/`|all` literals) for logging/console/
    trail AND as the F1 migration oracle's substring surface. `tags` is retained so
    F7's threat-type derivation is reorder-stable and testable.
    """

    def __init__(
        self,
        rule_id: str,
        title: str,
        patterns: List[str],
        severity: str,
        threat_type: str,
        action: str,
        selections: Optional[Dict[str, Selection]] = None,
        condition: Optional[Condition] = None,
        tags: Optional[List[str]] = None,
    ):
        self.id = rule_id
        self.title = title
        self.patterns = patterns
        self.severity = severity
        self.threat_type = threat_type
        self.action = action
        # WS-F additive dialect fields.
        self.selections: Dict[str, Selection] = selections if selections is not None else {}
        self.condition: Condition = condition if condition is not None else parse_condition(None)
        self.tags: List[str] = tags or []

    def evaluate(self, text: str) -> bool:
        """Hot-path match: compute each selection's bool via compiled `.search()`,
        then FOLD the condition AST over the per-selection bool map. NO re.compile
        here (all compilation is load-time, lld/35 §4.4 / NFR-1) and NO eval()."""
        sel_bools = {name: sel.matches(text) for name, sel in self.selections.items()}
        return self.condition.evaluate(sel_bools)


class SigmaEngine:
    """
    Detects threats using Sigma rules with in-memory caching.

    Features:
    - Loads rules from S3 (s3://sentra-mvp-artifacts/sigma_rules/llm/)
    - In-memory cache with configurable TTL (default: 5 minutes)
    - Pattern matching against user input
    - Fail-secure on errors
    """

    def __init__(
        self,
        s3_bucket: str = None,
        s3_prefix: str = None,
        cache_ttl_seconds: int = None,
        metrics_publisher=None,
        remap_threat_types: bool = True,
    ):
        self.s3_bucket = s3_bucket or settings.s3_bucket
        self.s3_prefix = s3_prefix or "sigma_rules/llm/"
        self.cache_ttl_seconds = cache_ttl_seconds or getattr(
            settings, "sigma_rules_cache_ttl_seconds", 300
        )
        # WS-F F7: when True (the shipped default) the derived `threat_type` is the
        # canonical 8-value enum (via threat_type_remap). The F1 equivalence-freeze
        # sets this False to reproduce the OLD first-tag-uppercase extraction so the
        # migration diff is measured against the true legacy behavior (the remap is
        # a LABELED F7 change, NOT part of the 0-diff migration).
        self.remap_threat_types = remap_threat_types
        self.rules_cache: Optional[List[SigmaRule]] = None
        self.cache_timestamp = 0.0
        # WS-F §12/§6c: last-known-good resiliency + stale-pin bookkeeping.
        self._last_good_compile_ts: float = 0.0
        self._consecutive_reload_failures: int = 0
        # Retain fire-and-forget alarm tasks: asyncio only holds a WEAK reference
        # to a bare ensure_future() Task, so CPython may GC a still-pending task and
        # silently drop the stale-pin page it exists to fire. Keep a strong ref until
        # the task completes (discarded in the done-callback).
        self._pending_alarms: set = set()
        # WS24 M3.2: the rule-set version we last loaded against. A cheap,
        # throttled get_item on the shared version row lets this task notice a
        # rule change (made via the CRUD API on any task) within
        # `version_check_interval`s, instead of waiting out the full TTL.
        self.cache_version: int = -1
        self._last_version_check: float = 0.0
        self.version_check_interval = getattr(
            settings, "sigma_version_check_interval_seconds", 10)
        # WS24 M2.3: reuse pooled clients from the registry instead of building a
        # new boto3 client/resource on every cold load.
        self.s3_client = get_clients().s3()
        self.dynamodb = get_clients().dynamodb_resource()
        # Emits one SigmaRuleMatches count (per RuleId) to CloudWatch on every
        # match — the real source of truth for the console's "Matches" column.
        # Lazily constructed so tests/offline paths can run without one.
        self._metrics_publisher = metrics_publisher

    async def load_rules_metadata_from_dynamodb(self) -> List[Dict]:
        """
        Load Sigma rule metadata from DynamoDB.

        Returns list of metadata dicts with s3_key, s3_bucket, rule_id, etc.
        Only loads stable rules (status='stable').

        Returns:
            List of metadata dictionaries

        Raises:
            SigmaRulesLoadError: If DynamoDB query fails
        """
        try:
            # WS24 M2.3/M4.3: reuse the pooled resource (no per-call construction)
            # and offload the synchronous query off the event loop.
            table = self.dynamodb.Table(settings.dynamodb_sigma_rules_metadata_table)

            # Query using status-index GSI to get only stable rules
            response = await asyncio.to_thread(
                table.query,
                IndexName='status-index',
                KeyConditionExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': 'stable'},
            )

            metadata_list = response.get('Items', [])
            logger.info(f"Loaded {len(metadata_list)} Sigma rule metadata items from DynamoDB")

            return metadata_list

        except ClientError as e:
            logger.exception("DynamoDB error loading Sigma rule metadata")
            raise SigmaRulesLoadError(f"Cannot load rule metadata from DynamoDB: {e}")
        except Exception as e:
            logger.exception("Unexpected error loading Sigma rule metadata")
            raise SigmaRulesLoadError(f"Unexpected error: {e}")

    async def load_rules_from_s3(self) -> List[SigmaRule]:
        """
        Load Sigma rules using hybrid DynamoDB + S3 approach.

        Process:
        1. Check in-memory cache (5-minute TTL)
        2. If cache miss: Query DynamoDB for metadata
        3. Download full YAML content from S3 using s3_key from metadata
        4. Parse YAML and create SigmaRule objects
        5. Update cache

        Returns:
            List of SigmaRule objects

        Raises:
            SigmaRulesLoadError: If rules cannot be loaded and no cache available
        """
        try:
            current_time = time.time()

            # WS24 M3.2: serve the cache, but periodically re-check the shared
            # version row so a rule change made on ANY task propagates here within
            # `version_check_interval`s — without paying a DDB read every request.
            if self.rules_cache is not None:
                within_ttl = (current_time - self.cache_timestamp) < self.cache_ttl_seconds
                if (current_time - self._last_version_check) < self.version_check_interval:
                    if within_ttl:
                        return self.rules_cache
                else:
                    self._last_version_check = current_time
                    remote_version = await self._fetch_version()
                    if remote_version == -1 and within_ttl:
                        return self.rules_cache  # check failed → keep fresh-enough cache
                    if remote_version == self.cache_version and within_ttl:
                        return self.rules_cache  # unchanged → keep cache
                    # else: version moved or TTL lapsed → reload below

            # Cache miss / stale / version bumped — reload from DynamoDB + S3
            logger.info("Loading Sigma rules from DynamoDB metadata + S3 content")
            loaded_version = await self._fetch_version()

            # Step 1: Load metadata from DynamoDB
            metadata_list = await self.load_rules_metadata_from_dynamodb()

            if not metadata_list:
                logger.warning("No Sigma rule metadata found in DynamoDB")
                if self.rules_cache:
                    logger.warning("Using stale cache")
                    return self.rules_cache
                raise SigmaRulesLoadError("No Sigma rules found in DynamoDB")

            # Step 2: Download full rules from S3 using metadata.
            # WS24 M3.4: fetch all rule bodies CONCURRENTLY instead of a serial
            # get_object loop. This is fan-out I/O within a single step (allowed —
            # LLD 24 §1.2.1; distinct from the prohibited validator-pipeline gather)
            # and only runs on a cold load / cache miss, which the singleton (M2)
            # already made rare. One bad rule is skipped without failing the set.
            async def _fetch_rule(metadata: Dict) -> Optional[SigmaRule]:
                rule_id = metadata.get('rule_id', 'unknown')
                s3_bucket = metadata.get('s3_bucket')
                s3_key = metadata.get('s3_key')
                if not s3_bucket or not s3_key:
                    logger.warning(f"Rule {rule_id} missing S3 reference, skipping")
                    return None
                try:
                    rule_obj = await asyncio.to_thread(
                        self.s3_client.get_object, Bucket=s3_bucket, Key=s3_key
                    )
                    rule_content = rule_obj['Body'].read().decode('utf-8')
                    rule_data = yaml.safe_load(rule_content)
                    sigma_rule = self._parse_sigma_rule(rule_data)
                    logger.debug(f"Loaded rule: {sigma_rule.title}")
                    return sigma_rule
                except Exception as e:
                    logger.warning(f"Failed to load rule {rule_id}: {e}")
                    return None

            fetched = await asyncio.gather(*[_fetch_rule(m) for m in metadata_list])
            rules = [r for r in fetched if r is not None]

            # WS-F §6d: HARD ruleset-wide matcher cap (fat-corpus DoS). If the whole
            # loaded set exceeds the cap, treat the reload as failed — keep the last
            # known-good (do NOT admit a DoS-sized set into the hot path).
            total_matchers = sum(len(sel.matchers) for r in rules for sel in r.selections.values())
            if total_matchers > _MATCHERS_PER_RULESET:
                logger.error(
                    "prompt-signature ruleset exceeds matcher cap (%d > %d) — reload rejected",
                    total_matchers, _MATCHERS_PER_RULESET,
                )
                rules = []  # force the last-known-good / cold-start-fail path below

            # Step 3: Update cache
            if rules:
                self.rules_cache = rules
                self.cache_timestamp = current_time
                self.cache_version = loaded_version  # WS24 M3.2
                # WS-F §6c: record a successful compile — resets the stale-pin clock.
                self._last_good_compile_ts = current_time
                self._consecutive_reload_failures = 0
                logger.info(f"Loaded {len(rules)} Sigma rules into cache (hybrid approach)")
            else:
                # WS-F §6c mitigation-1: a reload that produced ZERO usable rules
                # while a previously-good set exists KEEPS the last-known-good (do NOT
                # go blind). ABSTAIN happens only on genuine cold-start-no-cache.
                logger.warning("No rules successfully loaded")
                if self.rules_cache:
                    self._note_failed_reload(current_time)
                    logger.warning(
                        "Keeping last-known-good ruleset (%d rules) — reload produced none",
                        len(self.rules_cache),
                    )
                    return self.rules_cache
                raise SigmaRulesLoadError("No rules could be loaded")

            return rules

        except SigmaRulesLoadError:
            # Already logged, re-raise
            raise
        except ClientError as e:
            logger.exception("S3 error loading Sigma rules")
            # If cache exists, serve stale cache (availability) — but count it toward
            # the stale-pin page so a persistent outage cannot silently freeze the
            # floor on an old ruleset forever (WS-F §12).
            if self.rules_cache:
                self._note_failed_reload(time.time())
                logger.warning(
                    f"Using stale cache due to S3 error ({len(self.rules_cache)} rules)"
                )
                return self.rules_cache
            # No cache available - fail-secure
            raise SigmaRulesLoadError(f"Cannot load Sigma rules and no cache available: {e}")
        except Exception as e:
            logger.exception("Unexpected error loading Sigma rules")
            if self.rules_cache:
                self._note_failed_reload(time.time())
                logger.warning("Using stale cache due to error")
                return self.rules_cache
            raise SigmaRulesLoadError(f"Unexpected error: {e}")

    def _note_failed_reload(self, now: float) -> None:
        """WS-F §12/§6c stale-pin control. Increment the consecutive-failure counter
        and PAGE (a HIGH alarm, not just a WARN log) when the engine has served a
        last-known-good set across N consecutive failed reloads OR > T seconds since
        the last successful compile — the signal that an attacker may be pushing
        repeated compile-FAILING version bumps to freeze the floor on a stale set."""
        self._consecutive_reload_failures += 1
        stale_seconds = (
            now - self._last_good_compile_ts if self._last_good_compile_ts else 0.0
        )
        if (
            self._consecutive_reload_failures >= _STALE_PIN_MAX_CONSEC_FAILS
            or (self._last_good_compile_ts and stale_seconds > _STALE_PIN_MAX_STALE_SECONDS)
        ):
            task = asyncio.ensure_future(self._fire_alarm(
                "PromptSignatureRulesStalePinned",
                consecutive_failures=self._consecutive_reload_failures,
                stale_seconds=int(stale_seconds),
            ))
            # Strong-ref the task so it can't be GC'd before it fires (see __init__).
            self._pending_alarms.add(task)
            task.add_done_callback(self._pending_alarms.discard)

    async def _fire_alarm(self, alarm_name: str, **dims) -> None:
        """Fire a HIGH operational alarm (fire-and-forget). A publish failure must
        never turn an otherwise-correct verdict into an error (WS-F §6a/§12)."""
        try:
            if self._metrics_publisher is None:
                from app.utils.metrics_publisher import MetricsPublisher
                self._metrics_publisher = MetricsPublisher()
            await self._metrics_publisher.publish_sigma_alarm_metric(alarm_name, **dims)
        except Exception as e:
            logger.warning("Could not fire prompt-signature alarm %s: %s", alarm_name, e)

    async def _fetch_version(self) -> int:
        """Read the shared sigma rule-set version (one cheap get_item).

        Returns 0 when the version row doesn't exist yet, and -1 when the read
        fails — on -1 the caller keeps its existing cache rather than reloading
        on a transient error (fail-to-cache, not fail-to-reload-storm).
        """
        try:
            table = self.dynamodb.Table(settings.dynamodb_sigma_rules_metadata_table)
            resp = await asyncio.to_thread(
                table.get_item, Key={'rule_id': _SIGMA_VERSION_ITEM_ID})
            item = resp.get('Item')
            return int(item['version']) if item and 'version' in item else 0
        except Exception as e:
            logger.warning(f"sigma version check failed (keeping cache): {e}")
            return -1

    def invalidate(self) -> None:
        """Write-through hook (WS24 M3.2): drop the enforcement cache so the next
        `match_rules` reloads immediately on THIS task after a rule write. Other
        tasks converge via the version row within `version_check_interval`s."""
        self.rules_cache = None
        self.cache_version = -1
        self._last_version_check = 0.0
        logger.info("Sigma enforcement cache invalidated (write-through)")

    def _parse_sigma_rule(self, rule_data: Dict) -> SigmaRule:
        """
        Parse a prompt-signature rule YAML into a SigmaRule (WS-F F1/F2/F6.3).

        Compiles every `|contains`/`|all` (escaped) + `|re` (validated as untrusted
        external data) matcher at LOAD, parses the `condition` to a boolean AST, and
        verifies every condition Ref names a defined selection.

        Raises DialectError on a rule that violates the closed dialect (uncompilable
        condition, undefined selection, matcher-cap over) so the caller SKIPS that
        rule + logs — one bad rule never fails the whole set (§6d), but it never
        silently evaluates false either.
        """
        detection = rule_data.get("detection", {})

        # --- F2: compile selections (escaped |contains/|all, validated |re) --- #
        selections, _ = compile_selections(detection)

        # --- flat raw-pattern list retained for logging + F1 oracle surface --- #
        patterns: List[str] = []
        for sel in selections.values():
            patterns.extend(m.raw for m in sel.matchers)

        # --- F2.3/F2.4: parse condition AST + reject an undefined-selection ref - #
        condition = parse_condition(detection.get("condition"))
        undefined = condition.refs() - set(selections.keys())
        if undefined:
            # A condition naming a selection that has no compiled matcher is a
            # fail-open trap (a typo'd/param-only selection that "passes"). Fail the
            # rule's LOAD (skip + log), never silently evaluate it false. A
            # param/session-only selection legitimately drops to zero matchers, so
            # only FAIL when the condition still REFERENCES the dropped name; a rule
            # whose condition doesn't name the dropped selection is left inert.
            raise DialectError(
                f"condition references undefined/empty selection(s) {sorted(undefined)}"
            )

        tags = rule_data.get("tags", []) or []
        threat_type = self._derive_threat_type(rule_data, tags)

        return SigmaRule(
            rule_id=rule_data.get("id", "unknown"),
            title=rule_data.get("title", "Unknown Rule"),
            patterns=patterns,
            severity=rule_data.get("level", "medium"),
            threat_type=threat_type,
            action=rule_data.get("response", {}).get("action", "DENY"),
            selections=selections,
            condition=condition,
            tags=tags,
        )

    def _derive_threat_type(self, rule_data: Dict, tags: List[str]) -> str:
        """Derive the rule's threat_type.

        Default (remap_threat_types=True): the canonical, reorder-stable 8-value
        enum (WS-F F7, via threat_type_remap). When False: the LEGACY first-tag-
        uppercase extraction — used ONLY by the F1 equivalence-freeze so the 0-diff
        migration is measured against true legacy behavior before the F7 relabel.
        """
        if self.remap_threat_types:
            return derive_threat_type(tags)
        return self._extract_threat_type(rule_data)

    def _extract_threat_type(self, rule_data: Dict) -> str:
        """LEGACY threat-type extraction (first `llm.<x>` tag by YAML order,
        uppercased). Retained ONLY for the F1 migration oracle; the shipped engine
        uses `derive_threat_type` (F7). YAML-order-fragile by design here."""
        tags = rule_data.get("tags", [])
        for tag in tags:
            if tag.startswith("llm."):
                return tag.replace("llm.", "").upper()
        return "UNKNOWN_THREAT"

    async def _emit_match(self, rule_id: str) -> None:
        """Record a rule match to CloudWatch (fire-and-forget).

        The publisher is constructed lazily on first use so the engine stays
        cheap to instantiate and so offline/test paths that never match a rule
        don't pull in a CloudWatch client. Any failure is swallowed — emitting a
        metric must never turn an otherwise-correct DENY into an error.
        """
        try:
            if self._metrics_publisher is None:
                from app.utils.metrics_publisher import MetricsPublisher
                self._metrics_publisher = MetricsPublisher()
            await self._metrics_publisher.publish_sigma_match_metric(rule_id)
        except Exception as e:
            logger.warning(f"Could not emit Sigma match metric for {rule_id}: {e}")

    @stamps(Source.SENTRA_SIGMA)
    async def match_rules(self, user_input: str) -> ValidationResult:
        """
        Match user input against every prompt-signature rule (WS-F closed dialect).

        Per rule: compute each selection's bool via its COMPILED matchers (`.search()`
        — no per-request re.compile, NFR-1) then FOLD the condition AST. On a True
        condition, emit the SAME DENY ValidationResult the substring engine did.

        Error contract (lld/35 §6):
          * rule-load failure with no usable cache -> ABSTAIN (no signal) + HIGH
            `PromptSignatureRulesUnavailable` alarm. NOT a fabricated `RULE_ENGINE_ERROR`
            DENY — a fake-200-DENY lies to every audit/console consumer and can mask a
            real detection outage. ABSTAIN lets the other tier-0 layers + the tier-1
            ML backstop still decide (abstain != deny).
          * a genuine unexpected crash PROPAGATES (raise) to the honest outer handler
            (5XX) — it is NOT swallowed into a per-layer DENY.
        """
        try:
            # Load rules (from cache or S3). On genuine no-cache this raises
            # SigmaRulesLoadError (-> ABSTAIN below), NOT a fabricated DENY.
            rules = await self.load_rules_from_s3()

            # Single case-fold pass over the whole prompt (NFR-1). Matchers are
            # compiled IGNORECASE, so we match on the raw text; the lowering here is
            # retained only for the raw-substring log parity in _emit-adjacent code.
            for rule in rules:
                if rule.evaluate(user_input):
                    logger.warning(
                        "prompt-signature rule matched: %s (threat_type=%s)",
                        rule.title, rule.threat_type,
                    )
                    # §6e reason discipline: cite the indicator (threat_type + rule
                    # title), NEVER the prompt verbatim (avoids prompt-echo / co-tenant
                    # content leak). The matched pattern is logged server-side only.
                    logger.warning(
                        "prompt-signature match detail (server-side only): rule=%s selections=%s",
                        rule.id, list(rule.selections.keys()),
                    )
                    # Record the match in CloudWatch (per-RuleId series). This is
                    # what drives the console's "Matches" column; fire-and-forget so
                    # a metrics failure never blocks the DENY.
                    await self._emit_match(rule.id)
                    return ValidationResult(
                        decision="DENY",
                        reason=f"Threat detected: {rule.threat_type}",
                        violation_type=rule.threat_type,
                        threat_type=rule.threat_type,
                        matched_rule=rule.title,
                        severity=rule.severity.upper(),
                        penalty=-20 if rule.severity == "high" else -15,
                        should_deny=True,
                    )

            # No threats detected
            logger.debug("No prompt-signature rule matches found")
            return ValidationResult(
                decision="ALLOW", reason="No threats detected", should_deny=False
            )

        except SigmaRulesLoadError as e:
            # WS-F §6a: rule store unavailable AND no usable cache -> ABSTAIN (emit
            # NO signal), NOT a fabricated `RULE_ENGINE_ERROR` DENY. Fire a HIGH
            # alarm so the signature-blind window is visible/paged. The other layers
            # + ML backstop still decide the request.
            logger.error("prompt-signature rules unavailable — ABSTAIN: %s", e)
            await self._fire_alarm("PromptSignatureRulesUnavailable")
            return ValidationResult.abstain(
                "prompt-signature rules unavailable (rule store outage)"
            )
        # NOTE: no blanket `except Exception` here (was a §6b fake-200-DENY). A
        # genuine crash (e.g. a TypeError in AST eval) PROPAGATES to the honest
        # outer handler -> 5XX, never a fabricated per-layer DENY.


# --------------------------------------------------------------------------- #
# Process-wide singleton (WS24 M3.2)
# --------------------------------------------------------------------------- #
# Shared by the enforcement path (ValidationService) and the CRUD service
# (sigma_rules_service) so a rule write can WRITE-THROUGH-invalidate the live
# enforcement cache via `get_sigma_engine().invalidate()`.
_sigma_engine_singleton: Optional[SigmaEngine] = None
_sigma_engine_lock = threading.Lock()


def get_sigma_engine() -> SigmaEngine:
    """Return the process-wide SigmaEngine (singleton)."""
    global _sigma_engine_singleton
    if _sigma_engine_singleton is None:
        with _sigma_engine_lock:
            if _sigma_engine_singleton is None:
                _sigma_engine_singleton = SigmaEngine()
    return _sigma_engine_singleton
