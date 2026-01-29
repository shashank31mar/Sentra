"""
Helper utilities for Security Controller
"""
import time

# Track application start time for uptime calculation
_app_start_time = time.time()


def get_uptime_seconds() -> int:
    """Calculate application uptime in seconds"""
    return int(time.time() - _app_start_time)
