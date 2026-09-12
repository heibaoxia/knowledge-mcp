# 建筑专家 Agent — 系统架构

> 关联需求文档：[`2026-04-26-architecture-agent-spec.md`](./2026-04-26-architecture-agent-spec.md)  
> 日期：2026-04-26  
> 状态：草稿 v0.1

---

## 1. 分层架构总览

```text
┌──────────────────────────────────────────────────────────┐
│                   前端层 (React 18 + Vite)                 │
│         聊天界面 / 文件上传（预留）/ 对话历史                 │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTP REST + SSE 流式
┌───────────────────────▼──────────────────────────────────┐
│                   后端层 (FastAPI)                         │
│                                                          │
│  ┌─────────────┐  ┌──────────────────┐                  │
│  │  对话路由     │  │   项目管理路由     │                  │
│  │  POST /chat │  │   /project/*     │                  │
│  └──────┬──────┘  └────────┬─────────┘                  │
│         │                  │                             │
│  ┌──────▼──────────────────▼─────────┐                  │
│  │           Agent 核心层             │                  │
│  │  System Prompt / 对话上下文管理     │                  │
│  │  追问-记忆-分析逻辑 / 工具调度       │                  │
│  │  模型路由 (ModelManager)           │                  │
│  └──────┬────────────────────────────┘                  │
│         │                                                │
│  ┌──────▼──────┐ ┌──────────┐ ┌──────────┐             │
│  │  websearch  │ │calculator │ │doc_reader│             │
│  │  (Tavily)   │ │          │ │(PDF/DOC) │             │
│  └─────────────┘ └──────────┘ └──────────┘             │
│                                                          │
│  ┌──────────────────────────────────────┐               │
│  │        FileWatcher (watchdog)        │               │
│  │   静默监听项目文件夹文件变化           │               │
│  └──────────────────────────────────────┘               │
└───────────────────────┬──────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────┐
│                     数据层                                │
│                                                          │
│  ┌─────────────────┐  ┌───────────────┐                 │
│  │   PostgreSQL    │  │   ChromaDB    │                 │
│  │ 项目/会话/记忆   │  │ 文档向量/模板  │                 │
│  └─────────────────┘  └───────────────┘                 │
│                                                          │
│  ┌──────────────────────────────────────┐               │
│  │           本地文件系统                │               │
│  │   projects/<项目名>/                 │               │
│  │     01_input/  02_drawings/  ...    │               │
│  └──────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────┘
```

---

## 2. 模块职责

### 2.1 前端层

| 模块 | 职责 | 关联 spec |
|------|------|-----------|
| ChatView | 对话列表、消息渲染（Markdown + 来源引用） | `1.2.3 Agent 对话行为规范` |
| MessageInput | 文本输入 + 文件上传入口（预留） | `1.5 交互形态` |
| ChatStream | SSE 流式接收，打字机效果 | |

### 2.2 后端层

#### 2.2.1 路由层

| 路由 | 方法 | 职责 | 关联 spec |
|------|------|------|-----------|
| `/api/chat` | POST | 发送消息，返回 SSE 流式响应 | `1.2.3` |
| `/api/projects` | GET | 列出所有项目 | `1.4.2 项目文件夹结构` |
| `/api/projects/{id}` | GET | 获取项目详情 + 建筑基本信息 | `1.4.1 项目基本信息策略` |
| `/api/projects/{id}/refresh` | POST | 触发项目全量扫描更新 | `1.4.5 文件变更检测策略` |
| `/api/projects/{id}/files` | GET | 浏览项目文件 | |

#### 2.2.2 Agent 核心层

| 子模块 | 职责 | 关联 spec |
|--------|------|-----------|
| ChatManager | 管理对话上下文、System Prompt 注入 | `1.2.2 MVP 角色定义` |
| ToolDispatcher | 判断是否需要调用工具，调度执行 | `1.2.1 已确认工具` |
| ModelManager | 管理多模型注册、路由、回退 | `2.5 多模型架构设计` |
| MemoryManager | 对话内信息记忆（暂不做跨对话持久化） | `1.2.3 Agent 对话行为规范` |

**System Prompt 结构：**

```text
[角色定义]     你是建筑专家顾问，通晓规范/设计院知识
[行为规则]     追问-记忆-分析-结论，不重复追问
[搜索规则]     优先 gov.cn，带上来源+怎么用
[输出格式]     每条规范引用附带来源链接和使用方式
[当前上下文]    （由 ChatManager 注入：本次对话已知的项目信息）
```

#### 2.2.3 工具层

| 工具 | 依赖 | 接口 | 关联 spec |
|------|------|------|-----------|
| websearch | Tavily API | `websearch(query, max_results)` | `3.1` |
| calculator | 纯 Python | `calculator(expression)` 或结构化计算 | `1.2.1` |
| doc_reader | python-docx / pdfplumber / openpyxl | `doc_reader(file_path)` | `1.2.1` |

所有工具实现统一接口供 Agent 调用：

```python
class BaseTool:
    name: str
    description: str
    async def run(self, **kwargs) -> ToolResult
```

#### 2.2.4 FileWatcher

| 触发 | 行为 | 关联 spec |
|------|------|-----------|
| 文件新增/修改/删除 | 静默更新内存文件索引，不触发分析 | `1.4.5` |
| 用户说"更新项目" | 触发全量扫描 + 内容抽取 + 更新 `latest/` + 更新 `changelog.md` | `1.4.7` |

### 2.3 数据层

| 存储 | 内容 | 关联 spec |
|------|------|-----------|
| PostgreSQL | 项目元数据、建筑基本信息、对话会话记录、模板索引 | `1.4.1`、`1.4.7` |
| ChromaDB | 项目文档向量片段、可复用模板向量 | `1.4.2` |
| 本地文件系统 | 项目原始文件、图片、图纸、生成文件 | `1.4.2`、`1.4.4` |

**数据库核心表（MVP 后引入）：**

```sql
projects           -- 项目基本信息（1.4.1 字段映射到数据库列）
project_files      -- 项目文件索引（路径、类型、版本、修改时间）
project_versions   -- 版本变更记录（changelog.md 的结构化存储）
conversations      -- 对话会话（开始时间、项目ID、摘要）
messages           -- 对话消息（角色、内容、工具调用记录）
document_chunks    -- 文档片段元数据（对应 ChromaDB 向量）
templates          -- 可复用输出模板索引
```

---

## 3. 核心流程

### 3.1 MVP 对话流程

```text
用户输入
  │
  ▼
ChatManager 组装上下文
  ├── System Prompt（建筑专家角色 + 行为规则）
  ├── 本次对话已知信息（由 MemoryManager 提供）
  └── 用户当前消息
  │
  ▼
ToolDispatcher 判断：需要搜索规范吗？
  ├── 是 → websearch(query) → 搜索结果注入上下文
  └── 否 → 直接发送给 LLM
  │
  ▼
ModelManager 调用 DeepSeek-V4（流式）
  │
  ▼
SSE 流式输出 → 前端逐字显示
```

### 3.2 项目更新流程（后续版本）

```text
用户说"更新项目"
  │
  ▼
Agent 扫描项目文件夹
  ├── 比对新旧文件
  ├── 发现新文件 → doc_reader 抽取文字
  ├── 对比内容差异 → 更新建筑基本信息
  ├── 发现版本变化 → 更新 latest/ + changelog.md
  └── 检查信息矛盾 → 提示用户
  │
  ▼
Agent 回复：检测到 X 个变化，更新了 Y 个字段，Z 个字段仍缺失
```

### 3.3 设计条件变更流程

```text
用户在 archive/2026-05-01/ 放入新版设计条件
  │
  ▼
FileWatcher 静默检测到变化（不通知用户）
  │
  ▼
用户说"更新项目"
  │
  ▼
Agent 读取最新文件 → 对比 latest/ 旧版本
  ├── 发现容积率 2.5→3.0、限高 60→80m
  ├── 更新 01_input/设计条件/latest/
  ├── 写入 changelog.md：变化 + 影响评估
  └── 更新项目基本信息 PostgreSQL 记录
  │
  ▼
Agent 回复：设计条件已更新，容积率从 2.5 改为 3.0，
    限高从 60m 改为 80m。之前基于旧条件的方案结论需要重新评估。
    要我帮你重新检查退线和面积配比吗？
```

---

## 4. 多模型架构

```text
                    ┌──────────────────┐
                    │   ModelManager   │
                    │                  │
                    │  model_registry  │
                    │  ├─ default      │
                    │  ├─ image        │  (后续)
                    │  ├─ review       │  (后续)
                    │  └─ fallback     │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        DeepSeek-V4     ImageModel      ReviewModel
         (对话/分析)     (DALL·E等)     (GPT-4o等)
```

**接口规范：**

```python
class BaseModel(ABC):
    model_id: str
    model_type: str  # "chat" | "image" | "vision"

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> str: ...

    @abstractmethod
    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...

class DeepSeekModel(BaseModel):
    model_id = "deepseek-v4"
    model_type = "chat"
    # 对接 DeepSeek API（兼容 OpenAI SDK）

class ImageGenModel(BaseModel):       # 后续实现
    model_id = "dalle-3"
    model_type = "image"
```

---

## 5. 项目目录结构（代码仓库）

```text
knowledge/
├── docker-compose.yml
├── .env.example
├── docs/
│   └── specs/
│       ├── 2026-04-26-architecture-agent-spec.md    ← 需求文档
│       └── 2026-04-26-architecture.md               ← 本文档
├── src/
│   ├── backend/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app/
│   │   │   ├── main.py              # FastAPI 入口
│   │   │   ├── config.py            # 环境变量 / 配置
│   │   │   ├── routes/
│   │   │   │   ├── chat.py          # /api/chat
│   │   │   │   └── projects.py      # /api/projects/*
│   │   │   ├── agent/
│   │   │   │   ├── chat_manager.py  # 对话上下文 + System Prompt
│   │   │   │   ├── tool_dispatcher.py
│   │   │   │   ├── memory_manager.py
│   │   │   │   └── model_manager.py # 多模型路由
│   │   │   ├── tools/
│   │   │   │   ├── base.py          # BaseTool 抽象
│   │   │   │   ├── websearch.py     # Tavily 搜索
│   │   │   │   ├── calculator.py    # 指标计算
│   │   │   │   └── doc_reader.py    # 文档读取
│   │   │   ├── services/
│   │   │   │   ├── file_watcher.py  # watchdog 监听
│   │   │   │   ├── project_scanner.py
│   │   │   │   └── rag_service.py   # 向量检索
│   │   │   └── models/
│   │   │       ├── project.py       # SQLAlchemy 模型
│   │   │       └── conversation.py
│   │   └── alembic/                 # 数据库迁移
│   │
│   └── frontend/
│       ├── Dockerfile
│       ├── package.json
│       ├── vite.config.ts
│       └── src/
│           ├── App.tsx
│           ├── components/
│           │   ├── ChatView.tsx
│           │   ├── MessageInput.tsx
│           │   └── ProjectPanel.tsx    # 预留
│           ├── hooks/
│           │   └── useChatStream.ts
│           └── api/
│               └── client.ts
├── projects/                         # 用户项目数据（挂载卷）
│   └── .gitkeep
├── tests/
│   ├── test_websearch.py
│   ├── test_calculator.py
│   └── test_chat.py
└── scripts/
    └── init_db.py
```

---

## 6. 部署架构

```text
Docker Compose 服务编排：

┌────────────────────────────────────────────────┐
│              docker-compose.yml                 │
│                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ frontend │  │ backend  │  │ postgres │     │
│  │  :5173   │  │  :8000   │  │  :5432   │     │
│  └──────────┘  └──────────┘  └──────────┘     │
│                      │              │           │
│  ┌──────────┐        │              │           │
│  │ chromadb │────────┘              │           │
│  │  :8001   │                       │           │
│  └──────────┘                       │           │
│                                     │           │
│  volumes:                           │           │
│    ./projects:/app/projects ◄───────┘           │
│    postgres_data:/var/lib/postgresql/data       │
│    chroma_data:/chroma/chroma                   │
└────────────────────────────────────────────────┘
```

---

## 7. 版本对照

| 版本 | 范围 | 对应 spec 章节 |
|------|------|---------------|
| v0.1 MVP | 聊天界面 + DeepSeek-V4 + websearch | `1.2.2` |
| v0.2 | + calculator + doc_reader | `1.2.1` |
| v0.3 | + 项目管理 + 文件目录 + watchdog | `1.4.2` ~ `1.4.5` |
| v0.4 | + PostgreSQL + ChromaDB + RAG | `1.4.1` |
| v0.5 | + Agent 记忆 + 版本回溯 + changelog | `1.4.6` ~ `1.4.7` |
| v1.0 | + 多模态审图 + 生图模型 | `1.3` |

---

## 8. 修改约定

本文件与 [`2026-04-26-architecture-agent-spec.md`](./2026-04-26-architecture-agent-spec.md) 互相引用。

**任何一方修改后，修改者必须：**
1. 检查另一方是否需要同步更新
2. 如果需要，同时更新另一方并更新两者的版本号和时间戳
3. 在修改说明中注明"已确认 spec 已同步"或"spec 无需变更"
