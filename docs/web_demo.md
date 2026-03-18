# Web Demo

第四阶段新增了一个面试演示用的 Web Chat 页面，基于 FastAPI + Jinja2Templates + 原生 HTML/CSS/JS 实现。

## 页面区域

1. 标题区
2. 会话控制区
3. Demo Guide
4. 快捷问题区
5. 聊天消息区
6. 调试面板

## 调试面板内容

- `action`
- `intent`
- `nlu_mode`
- `selected_tool`
- `conversation_id`
- `request_ms`
- `normalized_filters`
- `missing_slots`
- `evidence`
- `retrieved_chunks`

## 启动

```bash
cd /Users/gehaoyuan/code/commission_agent
conda activate commission_env
uvicorn app.api.main:app --host 127.0.0.1 --port 8001
```

打开：

- [http://127.0.0.1:8001](http://127.0.0.1:8001)

## Demo Script

```bash
python -m app.scripts.run_demo_chat
```

输出：

- [demo/output/demo_transcript.md](/Users/gehaoyuan/code/commission_agent/demo/output/demo_transcript.md)
- [demo/output/demo_transcript.json](/Users/gehaoyuan/code/commission_agent/demo/output/demo_transcript.json)

## 面试建议顺序

1. operator 查达人近 30 天分佣
2. 追问只看不可分佣
3. 按视频展开
4. 查某视频为什么不可分佣
5. 查某订单什么时候到账
6. 解释闭环 CPS 和 CPT
7. 切到 creator 身份验证权限限制
