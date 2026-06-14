"""
MetricsQueryService — fast dashboard metrics from CloudWatch *Metrics*.

WS-21 T02 / C2. The legacy ``MetricsService`` queries CloudWatch *Logs Insights*
(``start_query`` + poll), which is seconds-scale and returns zeros on timeout.
This service reads the pre-aggregated **CloudWatch Metrics** emitted by
``MetricsPublisher`` (WS-21 T01) via ``GetMetricData`` — ~100-300ms, no polling.

Only the CloudWatch-owned numbers live here (counts, latency, deny, trust,
decision time-series). DDB-owned numbers (active agents, cloud-provider
distribution, quarantined counts) are joined by the route layer (T20/T21).

Metric names/namespace MUST mirror ``app/utils/metrics_publisher.py``.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3

from app.config import settings

logger = logging.getLogger(__name__)

# Mirrors MetricsPublisher (do not drift). See metrics_publisher.py.
NAMESPACE = "Sentra/SecurityController"

# range token -> total seconds
_RANGE_SECONDS: Dict[str, int] = {
    "1h": 3600,
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
}
# bucket token -> period seconds (for the decisions time-series)
_BUCKET_SECONDS: Dict[str, int] = {"1h": 3600, "1d": 86400}

# UI/area-chart guard (LLD 21 §11.2): reject combos that produce too many
# buckets to chart sensibly (e.g. 30d @ 1h = 720). CloudWatch's own hard cap is
# far higher (100,800 points/query), so this is the binding limit, not CW's.
_MAX_TIMESERIES_POINTS = 200


class MetricsQueryService:
    """Aggregates CloudWatch Metrics for the SOC dashboard."""

    def __init__(self, cloudwatch_client: Optional[Any] = None):
        # Allow injection for tests; default to a real client.
        self.cloudwatch = cloudwatch_client or boto3.client(
            "cloudwatch", region_name=settings.aws_region
        )

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _range_window(range_token: str) -> Tuple[datetime, datetime, int]:
        """Return (start, end, seconds) for a range token. Defaults to 24h."""
        seconds = _RANGE_SECONDS.get(range_token, _RANGE_SECONDS["24h"])
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=seconds)
        return start, end, seconds

    def _get_metric_data(
        self,
        queries: List[Dict[str, Any]],
        start: datetime,
        end: datetime,
    ) -> Dict[str, List[float]]:
        """Run GetMetricData and return {query_id: [values...]}, paging tokens."""
        results: Dict[str, List[float]] = {}
        next_token: Optional[str] = None
        while True:
            kwargs: Dict[str, Any] = {
                "MetricDataQueries": queries,
                "StartTime": start,
                "EndTime": end,
                "ScanBy": "TimestampAscending",
            }
            if next_token:
                kwargs["NextToken"] = next_token
            resp = self.cloudwatch.get_metric_data(**kwargs)
            for r in resp.get("MetricDataResults", []):
                results.setdefault(r["Id"], []).extend(r.get("Values", []))
            next_token = resp.get("NextToken")
            if not next_token:
                break
        return results

    @staticmethod
    def _search(metric: str, stat: str, period: int, decision: Optional[str] = None) -> str:
        """Build a SUM/AVG(SEARCH(...)) expression that collapses per-agent series.

        SEARCH matches every series for ``metric`` (across AgentId/Decision dims)
        so we don't have to enumerate agents. The outer math fn collapses the
        matched series into one.
        """
        schema = '{%s,AgentId,Decision}' % NAMESPACE if decision else '{%s,AgentId}' % NAMESPACE
        filt = f' MetricName="{metric}"'
        if decision:
            filt += f' Decision="{decision}"'
        outer = "SUM" if stat == "Sum" else "AVG"
        return f"{outer}(SEARCH('{schema}{filt}', '{stat}', {period}))"

    # --------------------------------------------------------------- queries

    def overview(self, range_token: str = "24h") -> Dict[str, Any]:
        """CloudWatch-owned KPI numbers for GET /v1/metrics/overview.

        Returns requests_total, allowed, denied (threats_blocked), avg_latency_ms,
        trust_score. DDB-owned fields are added by the route (T20).
        """
        start, end, seconds = self._range_window(range_token)
        period = seconds  # one bucket over the whole range → scalar
        # NOTE: ValidationsTotal is always published with BOTH {AgentId, Decision} dims
        # (metrics_publisher), so a SEARCH schema without Decision matches nothing. Rather than a
        # separate unfiltered "total" series (which returned 0 — every metric carries a Decision),
        # total = allowed + denied. DENY/ALLOW are the only decisions emitted for this counter.
        q = [
            {"Id": "allowed", "Expression": self._search("ValidationsTotal", "Sum", period, "ALLOW"), "ReturnData": True},
            {"Id": "denied", "Expression": self._search("ValidationsTotal", "Sum", period, "DENY"), "ReturnData": True},
            {"Id": "latency", "Expression": self._search("ValidationLatency", "Average", period), "ReturnData": True},
            {"Id": "trust", "Expression": self._search("TrustScoreAverage", "Average", period), "ReturnData": True},
        ]
        data = self._get_metric_data(q, start, end)

        def _sum(key: str) -> float:
            return float(sum(data.get(key, []) or []))

        def _avg(key: str) -> Optional[float]:
            vals = data.get(key, []) or []
            return (sum(vals) / len(vals)) if vals else None

        allowed = int(_sum("allowed"))
        denied = int(_sum("denied"))
        requests_total = allowed + denied
        avg_latency = _avg("latency")
        trust = _avg("trust")
        return {
            "range": range_token,
            "requests_total": requests_total,
            "allowed": allowed,
            "denied": denied,
            "threats_blocked": denied,
            "avg_latency_ms": int(round(avg_latency)) if avg_latency is not None else 0,
            "trust_score": int(round(trust)) if trust is not None else None,
        }

    def attack_category_count(self) -> int:
        """Count distinct ThreatType dimension values seen on the DenyRate metric.

        Backs the overview 'attack_categories' KPI. Uses ListMetrics (which
        reflects metrics seen in the trailing ~2 weeks) — good enough for a
        category count; not time-range-scoped.
        """
        seen = set()
        token = None
        while True:
            kwargs: Dict[str, Any] = {"Namespace": NAMESPACE, "MetricName": "DenyRate"}
            if token:
                kwargs["NextToken"] = token
            resp = self.cloudwatch.list_metrics(**kwargs)
            for metric in resp.get("Metrics", []):
                for dim in metric.get("Dimensions", []):
                    if dim.get("Name") == "ThreatType":
                        seen.add(dim.get("Value"))
            token = resp.get("NextToken")
            if not token:
                break
        return len(seen)

    def decisions_timeseries(
        self, range_token: str = "24h", bucket: str = "1h"
    ) -> Dict[str, Any]:
        """Allowed-vs-blocked dense time-series for GET /v1/metrics/decisions-timeseries.

        Raises ValueError if the range/bucket combo exceeds the point cap
        (e.g. 30d @ 1h) — the route maps this to HTTP 400.
        """
        start, end, seconds = self._range_window(range_token)
        period = _BUCKET_SECONDS.get(bucket, _BUCKET_SECONDS["1h"])
        if seconds // period > _MAX_TIMESERIES_POINTS:
            raise ValueError(
                f"range={range_token} with bucket={bucket} produces too many points "
                f"(>{_MAX_TIMESERIES_POINTS}); use a coarser bucket (e.g. 1d)"
            )
        q = [
            {"Id": "allowed", "Expression": self._search("ValidationsTotal", "Sum", period, "ALLOW"),
             "ReturnData": True, "Period": period},
            {"Id": "blocked", "Expression": self._search("ValidationsTotal", "Sum", period, "DENY"),
             "ReturnData": True, "Period": period},
        ]
        # Need timestamps too — fetch raw results (not just values).
        resp_results = self._get_metric_data_with_ts(q, start, end)
        allowed_ts = resp_results.get("allowed", {})
        blocked_ts = resp_results.get("blocked", {})

        # Build a dense series over all bucket boundaries seen.
        all_ts = sorted(set(allowed_ts) | set(blocked_ts))
        series = [
            {
                "t": ts,
                "allowed": int(allowed_ts.get(ts, 0)),
                "blocked": int(blocked_ts.get(ts, 0)),
            }
            for ts in all_ts
        ]
        return {"range": range_token, "bucket": bucket, "series": series}

    def _get_metric_data_with_ts(
        self, queries: List[Dict[str, Any]], start: datetime, end: datetime
    ) -> Dict[str, Dict[str, float]]:
        """Like _get_metric_data but keyed {query_id: {iso_ts: value}}."""
        out: Dict[str, Dict[str, float]] = {}
        next_token: Optional[str] = None
        while True:
            kwargs: Dict[str, Any] = {
                "MetricDataQueries": queries,
                "StartTime": start,
                "EndTime": end,
                "ScanBy": "TimestampAscending",
            }
            if next_token:
                kwargs["NextToken"] = next_token
            resp = self.cloudwatch.get_metric_data(**kwargs)
            for r in resp.get("MetricDataResults", []):
                bucket = out.setdefault(r["Id"], {})
                for ts, val in zip(r.get("Timestamps", []), r.get("Values", [])):
                    iso = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(ts, datetime) else str(ts)
                    bucket[iso] = val
            next_token = resp.get("NextToken")
            if not next_token:
                break
        return out

    # ----------------------------------------------------- sigma rule matches

    def _list_sigma_rule_ids(self) -> List[str]:
        """Enumerate every RuleId dimension ever seen on the SigmaRuleMatches metric.

        ListMetrics reflects metrics observed in the trailing ~2 weeks, which is
        wider than any of our ranges, so we then sum each series over the actual
        window. A rule that has never matched has no series here and so is
        (correctly) absent from the result — the caller defaults it to 0.
        """
        rule_ids: set = set()
        token = None
        while True:
            kwargs: Dict[str, Any] = {
                "Namespace": NAMESPACE,
                "MetricName": "SigmaRuleMatches",
            }
            if token:
                kwargs["NextToken"] = token
            resp = self.cloudwatch.list_metrics(**kwargs)
            for metric in resp.get("Metrics", []):
                for dim in metric.get("Dimensions", []):
                    if dim.get("Name") == "RuleId":
                        rule_ids.add(dim.get("Value"))
            token = resp.get("NextToken")
            if not token:
                break
        return sorted(rule_ids)

    def sigma_match_counts(self, range_token: str = "24h") -> Dict[str, int]:
        """Per-rule Sigma match counts over the range, keyed {rule_id: count}.

        Source of truth for the console's "Matches" column (the DDB
        stats.match_count_* fields are dead). Returns only rules that have at
        least one series in CloudWatch; the caller defaults unseen rules to 0.
        Defaults to a 24h window to match the dashboard's default selector.
        """
        rule_ids = self._list_sigma_rule_ids()
        if not rule_ids:
            return {}

        start, end, seconds = self._range_window(range_token)
        period = seconds  # one bucket over the whole range -> scalar per rule

        # One GetMetricData query per rule. Metric math ids must be
        # alphanumeric and start with a lowercase letter, so map rule_id ->
        # "r<index>" and keep a reverse lookup.
        id_map: Dict[str, str] = {f"r{i}": rid for i, rid in enumerate(rule_ids)}
        queries = [
            {
                "Id": qid,
                "MetricStat": {
                    "Metric": {
                        "Namespace": NAMESPACE,
                        "MetricName": "SigmaRuleMatches",
                        "Dimensions": [{"Name": "RuleId", "Value": rid}],
                    },
                    "Period": period,
                    "Stat": "Sum",
                },
                "ReturnData": True,
            }
            for qid, rid in id_map.items()
        ]

        data = self._get_metric_data(queries, start, end)
        counts: Dict[str, int] = {}
        for qid, rid in id_map.items():
            counts[rid] = int(sum(data.get(qid, []) or []))
        return counts
