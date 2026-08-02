"""Session ID generation for benchmark runs (LLD 41 §4.6 D6, FR-14.8)."""

from hashlib import sha256


def session_id_for(episode_id: str, *, run_id: str) -> str:
    """Generate a deterministic, run-unique, episode-scoped session ID.
    
    Format: bench-{run_id}-{12 hex of sha256(episode_id)}
    """
    digest = sha256(episode_id.encode("utf-8")).hexdigest()[:12]
    return f"bench-{run_id}-{digest}"
