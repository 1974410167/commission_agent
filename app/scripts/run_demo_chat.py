"""运行演示对话并导出演示文稿。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from app.application.agent.graph import get_agent_workflow
from app.domain.agent_models import UserContext
from app.web.demo_data import load_sample_conversations


def main() -> None:
    """顺序执行样例会话，并生成 markdown/json transcript。"""
    output_dir = Path("/Users/gehaoyuan/code/commission_agent/demo/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    workflow = get_agent_workflow()
    conversations = load_sample_conversations()
    transcript: list[dict] = []

    for index, item in enumerate(conversations, start=1):
        turn_started = perf_counter()
        # 每轮都打印进度，避免串行 LLM 调用时看起来像“脚本卡死”。
        print(
            f"[{index}/{len(conversations)}] {item['category']} -> {item['message']}",
            flush=True,
        )
        result = workflow.invoke(
            {
                "conversation_id": item["conversation_id"],
                "message": item["message"],
                "user_context": UserContext(
                    user_role=item["role"],
                    bound_creator_id=item.get("bound_creator_id"),
                ),
            }
        )
        response = result["response"].model_dump()
        debug = response.get("debug") or {}
        record = {
            "category": item["category"],
            "conversation_id": item["conversation_id"],
            "role": item["role"],
            "bound_creator_id": item.get("bound_creator_id"),
            "query": item["message"],
            "action": response["action"],
            "intent": response["intent"],
            "selected_tool": debug.get("selected_tool"),
            "nlu_mode": debug.get("nlu_mode"),
            "answer": response["answer"],
            "evidence": response["evidence"],
        }
        transcript.append(record)
        elapsed = perf_counter() - turn_started
        print(f"\n[{record['category']}] {record['role']} -> {record['query']}", flush=True)
        print(
            f"action={record['action']} intent={record['intent']} tool={record['selected_tool']} elapsed={elapsed:.2f}s",
            flush=True,
        )
        print(f"answer={record['answer'][:180]}", flush=True)
        print(
            "evidence="
            + "; ".join(
                f"{item['type']}:{item['title']}" for item in record["evidence"][:3]
            ),
            flush=True,
        )

    json_path = output_dir / "demo_transcript.json"
    md_path = output_dir / "demo_transcript.md"
    json_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_to_markdown(transcript), encoding="utf-8")

    print(f"\nGenerated: {json_path}", flush=True)
    print(f"Generated: {md_path}", flush=True)


def _to_markdown(transcript: list[dict]) -> str:
    """把结构化 transcript 转成更适合截图展示的 markdown。"""
    lines = [
        "# Demo Transcript",
        "",
        f"Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
    ]
    for item in transcript:
        lines.extend(
            [
                f"## {item['category']}",
                f"- role: `{item['role']}`",
                f"- conversation_id: `{item['conversation_id']}`",
                f"- action: `{item['action']}`",
                f"- intent: `{item['intent']}`",
                f"- selected_tool: `{item['selected_tool']}`",
                f"- nlu_mode: `{item['nlu_mode']}`",
                f"- query: {item['query']}",
                "",
                "### Answer",
                item["answer"],
                "",
                "### Evidence",
            ]
        )
        for evidence in item["evidence"]:
            lines.append(
                f"- `{evidence['type']}` {evidence['title']} | {evidence['source']} | {evidence['content_summary']}"
            )
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
