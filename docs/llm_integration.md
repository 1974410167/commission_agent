# LLM Integration

当前项目的 chat / NLU 走统一的 OpenAI 兼容客户端，支持三种 provider：

- `local`
- `bailian`
- `zhipu`
- `volcengine`

embedding 仍然单独配置，当前推荐默认保留在 `bailian`。

## Provider 选择

chat provider：

```env
MODEL_PROVIDER=local
```

可选值：

- `local`
- `bailian`
- `zhipu`
- `volcengine`

embedding provider：

```env
EMBEDDING_PROVIDER=bailian
```

可选值：

- `bailian`
- `zhipu`
- `local`
- `volcengine`

说明：

- `local` 只内置了 chat 预设，不内置 embedding 预设
- 若 `EMBEDDING_PROVIDER=local` 且未显式设置 `EMBEDDING_*`，embedding 会视为不可用

## 环境变量

```env
MODEL_PROVIDER=local
EMBEDDING_PROVIDER=bailian
LLM_ENABLED=true
RAG_ENABLED=true

CHAT_BASE_URL=
CHAT_API_KEY=
CHAT_MODEL=
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_MODEL=

BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
BAILIAN_API_KEY=
BAILIAN_CHAT_MODEL=qwen3.5-flash
BAILIAN_EMBEDDING_MODEL=text-embedding-v4

ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
ZHIPU_API_KEY=
ZHIPU_CHAT_MODEL=glm-4.7

VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
VOLCENGINE_API_KEY=
VOLCENGINE_CHAT_MODEL=DeepSeek-V3.2

LOCAL_CHAT_BASE_URL=http://127.0.0.1:18080/v1
LOCAL_CHAT_API_KEY=local-llm
LOCAL_CHAT_MODEL=qwen-local
```

优先级：

1. 显式 `CHAT_*` / `EMBEDDING_*`
2. provider 预设
3. 旧变量兼容项 `OPENAI_COMPATIBLE_*`

## 当前接入点

1. `OpenAICompatibleClient`
   - chat
   - embeddings
   - 支持按 provider 切换

2. `LLMBasedNLU`
   - intent classification
   - slot extraction

3. `KnowledgeEmbeddingService`
   - 生成 markdown chunk embedding

## 自动选择逻辑

- 项目只使用 `LLMBasedNLU`
- 当当前 chat provider 配置可用时，`debug.nlu_mode=llm_based`
- 当当前 chat provider 配置不完整时，`debug.nlu_mode=llm_unavailable`
- LLM 调用失败时会直接报错，不再伪装成业务上的 `UNKNOWN`

## 当前 provider 预设

### local

- base URL: `http://127.0.0.1:18080/v1`
- model: `qwen-local`
- 适配本地 `llama-server`

### bailian

- base URL: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- model: `qwen3.5-flash`
- embedding model: `text-embedding-v4`

### zhipu

- base URL: `https://open.bigmodel.cn/api/paas/v4/`
- model: `glm-4.7`

### volcengine

- base URL: `https://ark.cn-beijing.volces.com/api/coding/v3`
- model: `DeepSeek-V3.2`

官方参考：

- [智谱 OpenAI API](https://docs.bigmodel.cn/cn/guide/develop/openapi/introduction)
- [智谱 GLM-4.7](https://docs.bigmodel.cn/cn/guide/models/text/glm-4.7)
- [阿里百炼 OpenAI 兼容](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
- [火山引擎 Ark OpenAI 兼容接口](https://ark.cn-beijing.volces.com/api/coding/v3)

## 启用方式

本地模型：

```bash
MODEL_PROVIDER=local
```

阿里百炼：

```bash
MODEL_PROVIDER=bailian
```

智谱：

```bash
MODEL_PROVIDER=zhipu
```

火山引擎：

```bash
MODEL_PROVIDER=volcengine
```

验证：

```bash
python -m app.scripts.validate_llm_nlu
```

## API 调试字段

开发环境下 `/api/chat` 会返回：

- `debug.nlu_mode`
- `debug.llm_provider`
- `debug.chat_model`
- `debug.retrieved_chunks`
- `debug.selected_tool`

用于快速确认当前请求到底走的是哪一个 provider。
