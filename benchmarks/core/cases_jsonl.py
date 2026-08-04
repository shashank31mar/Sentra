"""Row writer and resume ledger for cases.jsonl (LLD 41 §12, §14.2, FR-14.5, FR-14.8)."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


CASES_JSONL_FIELDS = (
    "case_id",
    "episode_id",
    "session_id",
    "arm",
    "phase",
    "label",
    "expected_outcome",
    "decision",
    "deciding_source",
    "trust_score_after",
    "quarantined",
    "first_deny_in_episode",
    "reason",
    "latency_ms",
    "attack_success",
    "utility",
)


@dataclass
class CaseLedgerRow:
    case_id: str
    episode_id: str
    session_id: str
    arm: Optional[str]  # "with", "without", or None for Mode A
    phase: str
    label: bool
    expected_outcome: str  # "deny" or "allow"
    decision: str  # "ALLOW", "DENY", or "ERROR" — ERROR is first-class, never coerced
    deciding_source: Optional[str]
    trust_score_after: Optional[float]
    quarantined: bool
    first_deny_in_episode: bool
    reason: str
    latency_ms: float
    attack_success: Optional[bool] = None
    utility: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        assert set(d.keys()) == set(CASES_JSONL_FIELDS), f"Row fields mismatch: {set(d.keys()) ^ set(CASES_JSONL_FIELDS)}"
        return d


class CasesJsonlWriter:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def read_completed_pairs(self) -> Set[Tuple[str, Optional[str]]]:
        """Read existing (case_id, arm) pairs for resume ledger."""
        completed: Set[Tuple[str, Optional[str]]] = set()
        if not self.file_path.exists():
            return completed

        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    completed.add((data["case_id"], data.get("arm")))
                except (json.JSONDecodeError, KeyError):
                    continue
        return completed

    def append_row(self, row: CaseLedgerRow) -> None:
        """Append one row and fsync immediately (RPO = 1 episode)."""
        row_dict = row.to_dict()
        line = json.dumps(row_dict) + "\n"
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def load_cases_jsonl(file_path: Path) -> List[Dict[str, Any]]:
    """Load all rows from a cases.jsonl file."""
    rows = []
    if not file_path.exists():
        return rows
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
