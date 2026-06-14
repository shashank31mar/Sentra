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

logger = logging.getLogger(__name__)

# WS24 M3.2: the cross-instance rule-set version lives as a single item in the
# sigma metadata table. Any enforcement-affecting CRUD bumps it; every task polls
# it (throttled) and reloads when it moves.
_SIGMA_VERSION_ITEM_ID = "__sigma_version__"


class SigmaRulesLoadError(Exception):
    """Raised when Sigma rules cannot be loaded"""
    pass


class SigmaRule:
    """Represents a parsed Sigma rule"""

    def __init__(
        self,
        rule_id: str,
        title: str,
        patterns: List[str],
        severity: str,
        threat_type: str,
        action: str,
    ):
        self.id = rule_id
        self.title = title
        self.patterns = patterns
        self.severity = severity
        self.threat_type = threat_type
        self.action = action


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
    ):
        self.s3_bucket = s3_bucket or settings.s3_bucket
        self.s3_prefix = s3_prefix or "sigma_rules/llm/"
        self.cache_ttl_seconds = cache_ttl_seconds or getattr(
            settings, "sigma_rules_cache_ttl_seconds", 300
        )
        self.rules_cache: Optional[List[SigmaRule]] = None
        self.cache_timestamp = 0.0
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

            # Step 3: Update cache
            if rules:
                self.rules_cache = rules
                self.cache_timestamp = current_time
                self.cache_version = loaded_version  # WS24 M3.2
                logger.info(f"Loaded {len(rules)} Sigma rules into cache (hybrid approach)")
            else:
                logger.warning("No rules successfully loaded")
                if self.rules_cache:
                    logger.warning("Using stale cache")
                    return self.rules_cache
                raise SigmaRulesLoadError("No rules could be loaded")

            return rules

        except SigmaRulesLoadError:
            # Already logged, re-raise
            raise
        except ClientError as e:
            logger.exception("S3 error loading Sigma rules")
            # If cache exists, use stale cache (fail-open for availability)
            if self.rules_cache:
                logger.warning(
                    f"Using stale cache due to S3 error ({len(self.rules_cache)} rules)"
                )
                return self.rules_cache
            # No cache available - fail-secure
            raise SigmaRulesLoadError(f"Cannot load Sigma rules and no cache available: {e}")
        except Exception as e:
            logger.exception("Unexpected error loading Sigma rules")
            if self.rules_cache:
                logger.warning("Using stale cache due to error")
                return self.rules_cache
            raise SigmaRulesLoadError(f"Unexpected error: {e}")

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
        Parse Sigma rule YAML into SigmaRule object.

        Args:
            rule_data: Parsed YAML dict

        Returns:
            SigmaRule object
        """
        patterns = []
        detection = rule_data.get("detection", {})

        # Extract all pattern lists from detection selections
        for selection_name, selection_data in detection.items():
            if selection_name == "condition":
                continue  # Skip condition field

            if isinstance(selection_data, dict):
                for field, values in selection_data.items():
                    if "|contains" in field and isinstance(values, list):
                        patterns.extend(values)

        # Extract threat type from tags
        threat_type = self._extract_threat_type(rule_data)

        return SigmaRule(
            rule_id=rule_data.get("id", "unknown"),
            title=rule_data.get("title", "Unknown Rule"),
            patterns=patterns,
            severity=rule_data.get("level", "medium"),
            threat_type=threat_type,
            action=rule_data.get("response", {}).get("action", "DENY"),
        )

    def _extract_threat_type(self, rule_data: Dict) -> str:
        """Extract threat type from tags or title"""
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
        Match user input against all Sigma rules.

        Args:
            user_input: User's input text to check

        Returns:
            ValidationResult with decision (ALLOW/DENY)
        """
        try:
            # Load rules (from cache or S3)
            rules = await self.load_rules_from_s3()
            user_input_lower = user_input.lower()

            # Check each rule
            for rule in rules:
                for pattern in rule.patterns:
                    if pattern.lower() in user_input_lower:
                        logger.warning(
                            f"Sigma rule matched: {rule.title} - pattern: '{pattern}'"
                        )
                        # Record the match in CloudWatch (per-RuleId series). This
                        # is what drives the console's "Matches" column; the DDB
                        # stats.match_count_* fields are dead. Fire-and-forget so
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
            logger.debug("No Sigma rule matches found")
            return ValidationResult(
                decision="ALLOW", reason="No threats detected", should_deny=False
            )

        except SigmaRulesLoadError as e:
            logger.error(f"Sigma rules load error: {e}", exc_info=True)
            # Fail-secure: deny if rules can't be loaded
            return ValidationResult(
                decision="DENY",
                reason="Threat detection unavailable",
                violation_type="RULE_ENGINE_ERROR",
                penalty=-10,
                should_deny=True,
            )
        except Exception as e:
            logger.exception(f"Sigma rule matching error: {e}")
            # Fail-secure: deny on errors
            return ValidationResult(
                decision="DENY",
                reason="Threat detection error",
                violation_type="RULE_ENGINE_ERROR",
                penalty=-10,
                should_deny=True,
            )


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
