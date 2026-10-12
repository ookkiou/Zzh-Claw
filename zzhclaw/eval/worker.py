"""独立进程中的 ZzhClaw；逐事件刷新，允许父进程终止并保存部分轨迹。"""

import json
import sys
from pathlib import Path

from zzhclaw.agent import Agent
from zzhclaw.ai import LLMClient
from zzhclaw.coding.session import SessionManager
from zzhclaw.coding.tools import set_cwd, set_sandbox

from .recorder import TrajectoryRecorder
from .storage import write_json_atomic


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    set_cwd(request["workspace"])
    set_sandbox(True)
    agent = Agent(
        llm=LLMClient(model=request["model"]),
        system_prompt=request["system_prompt"],
        session_manager=SessionManager(storage_dir=request["sessions"]),
        permission_mode="auto",
    )
    recorder = TrajectoryRecorder()
    with Path(request["events"]).open("w", encoding="utf-8") as stream:

        def record(raw):
            event = recorder(raw)
            stream.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            stream.flush()

        answer = agent.run(
            request["prompt"], max_iterations=request["max_iterations"], on_event=record
        )
    write_json_atomic(request["answer"], {"final_answer": answer})


if __name__ == "__main__":
    main()
