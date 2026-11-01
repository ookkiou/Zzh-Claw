"""Opt-in repair profile. Requires the separately pinned agent-r1 runtime on PYTHONPATH.

The normal Agent tools, prompts and summarization are deliberately not used here.
The trained JSON protocol and environment remain owned by agent-r1.
"""

import asyncio
import json
import time
import urllib.parse
import urllib.request

from .core import Agent


class VllmRepairTransport:
    """Exact token budgets through vLLM 0.11 tokenize/completion endpoints."""

    def __init__(self, origin, model, *, seed=17):
        url = urllib.parse.urlsplit(origin)
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1")
                or url.username or url.password or url.path not in ("", "/")
                or url.query or url.fragment):
            raise ValueError("Repair inference requires a loopback HTTP origin (use SSH forwarding)")
        if not model or type(seed) is not int or seed < 0:
            raise ValueError("A model alias and nonnegative integer seed are required")
        self.origin, self.model, self.seed = origin.rstrip("/"), model, seed
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.deadline = None
        self.decision = 0
        self.last_ids, self.last_text = None, None

    def begin(self, seconds=240):
        self.deadline = time.monotonic() + seconds
        self.decision = 0
        self.last_ids, self.last_text = None, None

    def request(self, path, payload):
        remaining = self.deadline - time.monotonic() if self.deadline else 10
        if remaining <= 0:
            raise TimeoutError("Repair inference deadline exceeded")
        request = urllib.request.Request(self.origin + path,
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
            headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=min(remaining, 240)) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Inference response exceeds size limit")
        return json.loads(body)

    @staticmethod
    def tokens(value):
        if not isinstance(value, list) or any(type(n) is not int or n < 0 for n in value):
            raise ValueError("Inference server did not return actual token IDs")
        return value

    async def encode(self, messages, tools):
        response = await asyncio.to_thread(self.request, "/tokenize", {
            "model": self.model, "messages": messages, "tools": tools,
            "add_generation_prompt": True, "add_special_tokens": False})
        ids = self.tokens(response["tokens"])
        if response.get("count") != len(ids) or response.get("max_model_len", 0) < 4608:
            raise ValueError("Tokenizer count/context capacity mismatch")
        return ids

    async def generate(self, prompt_ids):
        from code_repair.agent_session import GeneratedTokens

        response = await asyncio.to_thread(self.request, "/v1/completions", {
            "model": self.model, "prompt": prompt_ids, "max_tokens": 512,
            "temperature": 0.6, "top_p": 0.95, "top_k": 20,
            "repetition_penalty": 1.1, "seed": self.seed + self.decision,
            "n": 1, "stream": False, "return_token_ids": True,
            "skip_special_tokens": False, "stop_token_ids": [151645, 151643]})
        choices = response["choices"]
        if len(choices) != 1:
            raise ValueError("Expected exactly one generated response")
        choice = choices[0]
        ids = self.tokens(choice.get("token_ids"))
        if not ids or len(ids) > 512 or not isinstance(choice.get("text"), str):
            raise ValueError("Empty, oversized or malformed completion")
        if choice.get("finish_reason") not in ("stop", "length"):
            raise ValueError("Generation did not finish normally")
        # Completion text may omit an EOS/stop token even with skip_special_tokens=False.
        # Decode the actual returned IDs using the serving tokenizer, as in training.
        decoded = await asyncio.to_thread(self.request, "/detokenize", {
            "model": self.model, "tokens": ids})
        if not isinstance(decoded.get("prompt"), str):
            raise ValueError("Malformed detokenization result")
        self.last_ids, self.last_text = ids, decoded["prompt"]
        self.decision += 1
        return GeneratedTokens(ids)

    def decode(self, ids):
        if ids != self.last_ids:
            raise ValueError("Generated token IDs were changed or truncated")
        return self.last_text


class CodeRepairAgent(Agent):
    """ZzhClaw session/events around the unchanged six-decision repair runner.

    Explicitly selected by `zzhclaw repair`; never switches the general Agent.
    One run creates one new isolated application session. No native tool parser,
    shell, arbitrary host file tools, historical messages or skill injection.
    """

    def __init__(self, task, evaluator, transport, *, task_split, session_manager=None):
        if task_split != "dev":
            raise ValueError("Application integration is restricted to dev; final test is sealed")
        super().__init__(llm=transport, session_manager=session_manager,
                         system_prompt=None, permission_mode="auto")
        self.task, self.evaluator, self.transport = task, evaluator, transport
        self.last_result = None

    def run(self, user_input=None, on_tool_call=None, on_tool_result=None,
            confirm_tool=None, on_token=None, max_iterations=6, on_event=None):
        from code_repair.agent_session import RepairSession, run_trajectory

        if user_input not in (None, self.task.instruction):
            raise ValueError("Repair profile accepts the fixed task instruction only")
        if max_iterations != 6 or confirm_tool is not None:
            raise ValueError("Repair profile uses the fixed autonomous six-decision contract")
        # Fail before creating any coroutine when called from an asynchronous UI.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Run the synchronous repair profile in a worker thread")
        self.new_session("repair:" + self.task.task_id)
        self.last_result = None
        emit = lambda kind, **payload: on_event and on_event({"event_type": kind, **payload})
        patch = self.task.starter_source

        class ObservedSession(RepairSession):
            def step(inner, text):
                nonlocal patch
                if on_token:
                    on_token(text)  # One completed decision; not token streaming.
                result = super().step(text)
                trace = inner.trace[-1]
                action = trace["action"]
                if action and "name" in action:
                    name, arguments = action["name"], action["arguments"]
                    emit("tool_call", tool_name=name, arguments=arguments,
                         metadata={"contract_valid": trace["contract_valid"]})
                    if on_tool_call:
                        on_tool_call(name, arguments)
                    if on_tool_result:
                        on_tool_result(name, json.dumps(result.tool_response, ensure_ascii=False))
                    emit("tool_result", tool_name=name, result=result.tool_response)
                patch = (inner.environment.workspace / "solution.py").read_text(encoding="utf-8")
                return result

        session = ObservedSession(self.task, self.evaluator, max_steps=6,
                                  episode_timeout=240, test_timeout=10)
        started = time.monotonic()
        emit("agent_start", metadata={"profile": "code-repair-v1", "task_id": self.task.task_id})
        try:
            self.transport.begin(240)
            steps, info, timings = asyncio.run(run_trajectory(session, self.transport.encode,
                self.transport.generate, self.transport.decode,
                max_prompt_length=4096, max_response_length=512))
            self.last_result = {"profile": "code-repair-v1", "task_id": self.task.task_id,
                "seed": self.transport.seed, "model": self.transport.model,
                "terminal": info, "reward": steps[-1].reward if steps else 0.0,
                "decisions": len(steps), "patch": patch,
                "trace": session.trace, "timings": timings,
                "elapsed_seconds": time.monotonic() - started,
                "prompt_tokens": [len(s.prompt_ids) for s in steps],
                "response_tokens": [len(s.response_ids) for s in steps],
                "backend": "vllm-0.11-token-completions", "final_test": False}
            summary = json.dumps({"task_id": self.task.task_id, "decisions": len(steps),
                                  "terminal": info}, ensure_ascii=False)
            emit("agent_final", content=summary)
            return summary
        except Exception as error:
            emit("agent_error", error=type(error).__name__, metadata={"profile": "code-repair-v1"})
            raise
        finally:
            # Mirror the exact protocol history without summaries or native tool messages.
            for message in getattr(session, "messages", []):
                self.session_manager.add_message(message["role"], message["content"])
            self.save()
