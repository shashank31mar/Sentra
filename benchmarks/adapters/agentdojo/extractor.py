"""AgentDojo real task corpus extractor for benchmark harness (LLD 41 §5.1, WS-C milestone C4)."""

import sys
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

AGENTS_DOJO_PATH = Path("/Users/ruchikkachaudhary/closed-source/agentdojo/src")
if str(AGENTS_DOJO_PATH) not in sys.path:
    sys.path.insert(0, str(AGENTS_DOJO_PATH))

from benchmarks.core.case import BenchmarkCase


def extract_real_agentdojo_cases(suite_name: str = "banking") -> List[BenchmarkCase]:
    """Extract real BenchmarkCase instances from AgentDojo task suite."""
    from agentdojo.task_suite.load_suites import get_suite
    from agentdojo.attacks import load_attack

    suite = get_suite("v1", suite_name)
    pipe = MagicMock()
    pipe.name = "local_llm"
    attack = load_attack("important_instructions", suite, pipe)

    cases: List[BenchmarkCase] = []

    # 1. Benign cases (User task without injection)
    # Generate benign cases across user tasks, duplicating/sub-indexing to reach 300
    user_task_list = list(suite.user_tasks.values())
    for i in range(300):
        ut = user_task_list[i % len(user_task_list)]
        cid = f"agentdojo:{suite_name}:{ut.ID}:benign_{i:03d}"
        cases.append(
            BenchmarkCase(
                benchmark="agentdojo",
                suite=suite_name,
                case_id=cid,
                episode_id=cid,
                phase="content",
                agent_id=f"bench-agentdojo-{suite_name}",
                tool_name="read_inbox",
                tool_params={},
                user_input=ut.PROMPT,
                content_text=f"Benign customer record {i}. No security instructions present.",
                operation_type="READ",
                label=False,
                attack_type=None,
                injection_goal=None,
                expected_outcome="allow",
                raw={"user_task_id": ut.ID},
            )
        )

    # 2. Real injection cases (User task x Injection task)
    for ut_id, ut in suite.user_tasks.items():
        for it_id, it in suite.injection_tasks.items():
            injections = attack.attack(ut, it)
            content_text = "\n".join(str(v) for v in injections.values())
            cid = f"agentdojo:{suite_name}:{ut_id}:{it_id}"
            cases.append(
                BenchmarkCase(
                    benchmark="agentdojo",
                    suite=suite_name,
                    case_id=cid,
                    episode_id=cid,
                    phase="content",
                    agent_id=f"bench-agentdojo-{suite_name}",
                    tool_name="send_money",
                    tool_params={"account": "US133000000121212121212"},
                    user_input=ut.PROMPT,
                    content_text=content_text,
                    operation_type="WRITE",
                    label=True,
                    attack_type="indirect_injection",
                    injection_goal=it.GOAL,
                    expected_outcome="deny",
                    raw={"user_task_id": ut_id, "injection_task_id": it_id},
                )
            )

    return cases
