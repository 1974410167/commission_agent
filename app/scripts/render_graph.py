"""导出当前 LangGraph 状态机图。

优先输出 PNG，便于直接查看或贴到文档里；
同时也会保存一份 Mermaid 文本，方便在不支持 PNG 渲染的环境里调试。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.application.agent.graph import get_agent_workflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the Commission Agent LangGraph workflow.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("demo/output"),
        help="Directory used to store the rendered graph assets.",
    )
    parser.add_argument(
        "--png-name",
        default="agent_graph.png",
        help="PNG filename to write under output-dir.",
    )
    parser.add_argument(
        "--mermaid-name",
        default="agent_graph.mmd",
        help="Mermaid filename to write under output-dir.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    workflow = get_agent_workflow()
    graph = workflow.get_graph()

    mermaid_text = graph.draw_mermaid()
    mermaid_path = output_dir / args.mermaid_name
    mermaid_path.write_text(mermaid_text, encoding="utf-8")

    png_path = output_dir / args.png_name
    png_error: str | None = None
    try:
        png_bytes = graph.draw_mermaid_png()
        png_path.write_bytes(png_bytes)
    except Exception as exc:  # pragma: no cover - 这里是环境相关兜底
        png_error = f"{type(exc).__name__}: {exc}"

    print(f"Mermaid graph exported to: {mermaid_path.resolve()}")
    if png_error is None:
        print(f"PNG graph exported to: {png_path.resolve()}")
    else:
        print("PNG graph export failed.")
        print(f"Reason: {png_error}")
        print("You can still render the Mermaid file in Jupyter via:")
        print("from IPython.display import Image, display")
        print("display(Image(workflow.get_graph().draw_mermaid_png()))")


if __name__ == "__main__":
    main()
