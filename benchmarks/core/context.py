"""RunContext definition for benchmark execution (LLD 41 §4.6 D6, FR-14.8)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from .session import session_id_for


def generate_run_id(timestamp: datetime | None = None, manifest_hash: str = "000000") -> str:
    """Generate a run_id string formatted as UTC-timestamp-manifest_hash."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    ts_str = timestamp.strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{ts_str}-{manifest_hash[:6]}"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_clock_iso: str
    transcript_dir: Path
    model_id: str = "default-model"
    benchmark_version: str = "1.0.0"
    attack_name: str = "default"
    transport: str = "in-process"
    arms: Sequence[str] = field(default_factory=lambda: ("P1", "P2", "P3"))
    mode: str = "A"

    def session_id_for(self, episode_id: str) -> str:
        """Derive session ID for a given episode_id under this RunContext's run_id."""
        return session_id_for(episode_id, run_id=self.run_id)
