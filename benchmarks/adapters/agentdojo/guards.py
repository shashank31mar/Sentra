"""Sentra request and content guards for AgentDojo execution loop (LLD 41 §4.4, WS-E milestone E1)."""

import sys
from pathlib import Path

# Add agentdojo src path if not already in sys.path
agentdojo_src = "/Users/ruchikkachaudhary/closed-source/agentdojo/src"
if agentdojo_src not in sys.path and Path(agentdojo_src).exists():
    sys.path.insert(0, agentdojo_src)

from typing import Any, Callable, Dict, List, Sequence, Tuple
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.pi_detector import PromptInjectionDetector, DetectorTask
from agentdojo.agent_pipeline.tool_execution import ToolsExecutor, tool_result_to_str
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionsRuntime
from agentdojo.types import ChatMessage, ChatToolResultMessage, text_content_block_from_string, get_text_content_as_str

from app.api.models import ValidationRequest
from benchmarks.core.guard_client import GuardClient


class SentraContentGuard(PromptInjectionDetector):
    """phase=content guard. Sits AFTER ToolsExecutor; scans each ChatToolResultMessage.
    Constructed in message-mode, non-fatal — it must NEVER abort the loop.
    """

    def __init__(self, client: GuardClient, ctx: Any = None):
        super().__init__(mode="message", raise_on_injection=False)
        self.client = client
        self.ctx = ctx
        self.synthetic_content_skipped = 0

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: Sequence[ChatMessage] = [],
        extra_args: dict = {},
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict]:
        if len(messages) == 0 or messages[-1]["role"] != "tool":
            return query, runtime, env, messages, extra_args

        # Check self-contamination: stamp on message or extra_args
        last_msg = messages[-1]
        is_synthetic = (
            getattr(last_msg, "aegion_synthetic", False)
            or (isinstance(last_msg, dict) and last_msg.get("aegion_synthetic"))
            or extra_args.get("aegion_synthetic")
        )
        if is_synthetic:
            self.synthetic_content_skipped += 1
            if self.ctx and hasattr(self.ctx, "synthetic_content_skipped"):
                self.ctx.synthetic_content_skipped += 1
            return query, runtime, env, messages, extra_args

        try:
            return super().query(query, runtime, env, messages, extra_args)
        except Exception:
            # Content guard must NEVER raise / abort the loop
            return query, runtime, env, messages, extra_args

    def detect(self, tool_output: str) -> Tuple[bool, float]:
        """Validate content via GuardClient non-raising interface."""
        try:
            req = ValidationRequest(
                request_id="req-content",
                session_id=getattr(self.ctx, "session_id", "sess-bench"),
                agent_id=getattr(self.ctx, "agent_id", "agent-bench"),
                user_id="bench_user",
                tool_name="ingest_content",
                tool_params={},
                phase="content",
                operation_type="READ",
                user_input="",
                content_text=tool_output,
                timestamp="2026-08-02T12:00:00Z",
            )
            import asyncio
            # Run sync if already in loop or block
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If in running loop, use thread or task
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        decision = pool.submit(asyncio.run, self.client.validate(req, session_id=req.session_id, ctx=self.ctx, transport="in-process")).result()
                else:
                    decision = loop.run_until_complete(self.client.validate(req, session_id=req.session_id, ctx=self.ctx, transport="in-process"))
            except Exception:
                decision = asyncio.run(self.client.validate(req, session_id=req.session_id, ctx=self.ctx, transport="in-process"))

            if not decision.allowed:
                return True, 1.0
            return False, 0.0
        except Exception:
            return False, 0.0

    def transform(self, tool_output: List[Any]) -> List[Any]:
        return [
            text_content_block_from_string("Content denied by security policy.")
            if isinstance(block, dict) and block.get("type") == "text"
            else block
            for block in tool_output
        ]


class SentraRequestGuard(BasePipelineElement):
    """phase=request guard. Sits BEFORE ToolsExecutor; validates every tool_call in the turn."""

    def __init__(self, client: GuardClient, ctx: Any = None, formatter: Callable = tool_result_to_str):
        super().__init__()
        self.client = client
        self.ctx = ctx
        self.formatter = formatter
        self._private_executor = ToolsExecutor(tool_output_formatter=formatter)

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: Sequence[ChatMessage] = [],
        extra_args: dict = {},
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict]:
        # Branch (a): not assistant turn or no tool_calls -> pass through
        if len(messages) == 0 or messages[-1]["role"] != "assistant":
            return query, runtime, env, messages, extra_args
        
        tool_calls = messages[-1].get("tool_calls")
        if not tool_calls:
            return query, runtime, env, messages, extra_args

        # Validate each tool_call
        import asyncio
        verdicts = []
        for tc in tool_calls:
            req = ValidationRequest(
                request_id=f"req-{tc.id}",
                session_id=getattr(self.ctx, "session_id", "sess-bench"),
                agent_id=getattr(self.ctx, "agent_id", "agent-bench"),
                user_id="bench_user",
                tool_name=tc.function,
                tool_params=tc.args or {},
                phase="request",
                operation_type="WRITE",
                user_input=query,
                timestamp="2026-08-02T12:00:00Z",
            )
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        dec = pool.submit(asyncio.run, self.client.validate(req, session_id=req.session_id, ctx=self.ctx, transport="in-process")).result()
                else:
                    dec = loop.run_until_complete(self.client.validate(req, session_id=req.session_id, ctx=self.ctx, transport="in-process"))
            except Exception:
                dec = asyncio.run(self.client.validate(req, session_id=req.session_id, ctx=self.ctx, transport="in-process"))
            verdicts.append((tc, dec))

        all_allowed = all(dec.allowed for _, dec in verdicts)
        # Branch (b): ALL allowed -> pass through untouched
        if all_allowed:
            return query, runtime, env, messages, extra_args

        # Branch (c): MIXED or ALL-DENY
        merged_results: Dict[str, ChatToolResultMessage] = {}
        allowed_tcs = []

        for tc, dec in verdicts:
            if not dec.allowed:
                # Create synthetic error message with aegion_synthetic: true
                msg = ChatToolResultMessage(
                    role="tool",
                    content=[text_content_block_from_string("")],
                    tool_call_id=tc.id,
                    tool_call=tc,
                    error=dec.reason or f"Tool '{tc.function}' denied by security policy.",
                )
                if isinstance(msg, dict):
                    msg["aegion_synthetic"] = True
                merged_results[tc.id] = msg
            else:
                allowed_tcs.append(tc)

        # Delegate allowed subset to private executor
        if allowed_tcs:
            # Build shadow assistant message with allowed tool_calls
            shadow_assistant = dict(messages[-1])
            shadow_assistant["tool_calls"] = allowed_tcs
            shadow_messages = list(messages[:-1]) + [shadow_assistant]

            _, _, _, exec_messages, _ = self._private_executor.query(
                query, runtime, env, shadow_messages, extra_args
            )
            # Collect tool results generated for allowed calls
            for msg in exec_messages[len(shadow_messages):]:
                if msg["role"] == "tool" and "tool_call_id" in msg:
                    merged_results[msg["tool_call_id"]] = msg

        # Merge in original tool_call order
        ordered_results = [merged_results[tc.id] for tc in tool_calls if tc.id in merged_results]
        new_messages = list(messages) + ordered_results

        return query, runtime, env, new_messages, extra_args
