# Metis Agent 开发计划

> 模仿 nanobot 的轻量级设计哲学，以 **学习** 为核心目标，从零构建一个具备工具调用、Skill 系统、数据库存储、会话总结和知识图谱等能力的完整 Agent。

---

## 一、项目现状评估

### 已完成 ✅
| 模块 | 文件 | 状态 |
|------|------|------|
| YAML 配置系统 | `config/config.py` | ✅ 单例模式，支持 reload |
| Pydantic 数据模型 | `config/schema.py` | ✅ 基类 + ChannelsConfig |
| LLM 抽象基类 | `providers/base.py` | ✅ 重试机制、消息清洗、chat/chat_stream 协议 |
| OpenAI 兼容 Provider | `providers/openai_compat_provider.py` | ✅ 异步、流式、推理模型支持 |
| Provider 快照模型 | `providers/factory.py` | ✅ ProviderSnapshot 数据类 |
| PostgreSQL JSON 存储 | `utils/pgsql_store.py` | ✅ 单例、CRUD、JSONB 查询 |
| Docker Compose | `docker-compose.yml` | ✅ PostgreSQL 17 |

### 未完成 ❌
| 模块 | 说明 |
|------|------|
| Provider 工厂 | `factory.py` 的 `make_provider()` 函数体缺失 |
| 项目依赖声明 | 无 `pyproject.toml` / `requirements.txt` |
| Agent 主循环 | `main.py` 为空，无 ReAct/P-A-O 循环 |
| 工具系统 | 无工具注册/发现/执行框架 |
| Skill 系统 | 无 Skill 加载/管理机制 |
| 会话管理 | 无对话历史持久化、自动总结 |
| 知识图谱 | 无图数据库集成 |
| CLI / 通道 | 无命令行交互或消息通道 |
| 导入问题 | `pgsql_store.py` 使用 `from config import config` 应改为 `from metis.config import config` |

---

## 二、目标架构

借鉴 nanobot 的 **Perceive → Think → Act → Loop** 核心设计，Metis 的目标架构如下：

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLI / Channel                           │
│                    (命令行交互 / 消息通道)                         │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                       Agent Loop (核心)                           │
│                                                                  │
│   ┌─────────┐    ┌──────────┐    ┌─────────┐    ┌───────────┐  │
│   │ Perceive │───▶│  Think   │───▶│   Act   │───▶│ Observe   │  │
│   │ (感知)   │    │ (LLM推理) │    │(工具执行)│    │ (观察结果) │  │
│   └─────────┘    └──────────┘    └─────────┘    └─────┬─────┘  │
│        ▲                                              │         │
│        └──────────────────────────────────────────────┘         │
│                     (循环直到任务完成)                             │
└──┬──────────┬──────────┬──────────┬──────────┬──────────────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐
│Tools │ │Skills│ │Memory│ │ KG   │ │ Provider │
│(工具) │ │(技能) │ │(记忆) │ │(图谱) │ │  Factory  │
└──────┘ └──────┘ └──────┘ └──────┘ └──────────┘
     │                    │         │
     ▼                    ▼         ▼
┌──────────────────────────────────────────────┐
│           PostgreSQL (JSONB + 存储)           │
│        会话历史 / Skill 元数据 / 向量索引       │
└──────────────────────────────────────────────┘
```

---

## 三、分阶段开发计划

### 阶段一：补全基础设施（让项目跑起来）

> **目标**：修复现有问题，补全项目骨架，能启动并完成一次基本的 LLM 对话。

#### 1.1 创建 `pyproject.toml` — 项目依赖声明

```
metis/
├── pyproject.toml    # 新建
```

**内容要点**：
- 声明 Python >= 3.11
- 依赖：`openai`, `psycopg2-binary`, `pyyaml`, `pydantic`, `neo4j`（预留）, `httpx`
- 开发依赖：`pytest`, `pytest-asyncio`
- 入口点：`metis.cli:main`

#### 1.2 修复 `pgsql_store.py` 的导入

```python
# 修改前
from config import config

# 修改后
from metis.config import config
```

#### 1.3 完善 `factory.py` — Provider 工厂

```python
def make_provider(config) -> ProviderSnapshot:
    """根据配置创建 LLMProvider 实例"""
```

**逻辑**：
- 从 `config` 读取 `provider.type`（默认 `openai_compat`）
- 读取 `api_key`、`api_base`、`model`、`context_window_tokens`
- 实例化对应的 Provider
- 返回 `ProviderSnapshot`

#### 1.4 创建 `config.yaml.example` — 示例配置

```yaml
provider:
  type: openai_compat
  api_key: "sk-xxx"
  api_base: "https://api.openai.com/v1"
  model: "gpt-4o-mini"
  context_window_tokens: 128000

postgres:
  host: localhost
  port: 5432
  user: metis
  password: metis
  dbname: metis
```

#### 1.5 补全 `config/schema.py` — Provider 配置模型

添加 `ProviderConfig` Pydantic 模型，用于配置校验。

---

### 阶段二：Agent 核心循环（让 Agent 能思考）

> **目标**：实现 Agent Loop，让 Metis 能够与 LLM 进行多轮对话，并在 LLM 返回工具调用时正确处理。

#### 2.1 创建 Agent Loop

```
metis/
├── agent/
│   ├── __init__.py
│   ├── loop.py         # 核心：Perceive-Think-Act-Loop
│   ├── state.py        # Agent 状态管理（消息历史、当前步骤等）
│   └── prompts.py      # 系统 Prompt 管理
```

**核心逻辑 `loop.py`**：

```python
class AgentLoop:
    def __init__(self, provider_snapshot, tools_registry, memory_store):
        self.provider = provider_snapshot.provider
        self.model = provider_snapshot.model
        self.tools = tools_registry
        self.memory = memory_store
        self.max_iterations = 10  # 防止无限循环

    async def run(self, user_message: str, session_id: str) -> str:
        """
        Agent 主循环：
        1. 将用户消息加入历史
        2. 调用 LLM（传入工具定义）
        3. 如果 LLM 返回工具调用 → 执行工具 → 将结果加入历史 → 回到步骤 2
        4. 如果 LLM 返回普通文本 → 返回给用户
        5. 超过最大迭代次数 → 强制停止
        """
        messages = await self.memory.load_history(session_id)
        messages.append({"role": "user", "content": user_message})

        for iteration in range(self.max_iterations):
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
            )

            if response.has_tool_calls:
                # 执行每个工具调用
                messages.append({
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [tc.to_openai_tool_call() for tc in response.tool_calls]
                })
                for tool_call in response.tool_calls:
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result)
                    })
            else:
                # LLM 给出最终回复
                messages.append({"role": "assistant", "content": response.content})
                await self.memory.save_history(session_id, messages)
                return response.content

        return "达到最大迭代次数，任务未完成。"
```

**这是整个 Agent 的灵魂**，参照 nanobot 的 `agent/loop.py` 设计。核心思路：
- LLM 既是"大脑"也是"调度器"
- 工具调用不是硬编码，而是由 LLM 自主决策
- 循环直到 LLM 认为任务完成（不返回工具调用）或达到安全上限

#### 2.2 创建 Agent 状态管理 `state.py`

- `AgentState` 数据类：当前会话 ID、消息历史、迭代计数、状态标记（idle/thinking/acting）
- 提供状态序列化/反序列化，用于持久化到数据库

#### 2.3 创建 Prompt 管理 `prompts.py`

- 系统提示词模板（可从配置文件加载）
- 支持动态插入当前日期、可用工具描述、Skill 描述等上下文信息
- 参照 nanobot 的 `AGENTS.md` 思路：让 Agent 知道自己是谁、能做什么

---

### 阶段三：工具系统（让 Agent 能行动）

> **目标**：实现工具的注册、发现、执行框架，让 Agent 能真正"动手"操作。

#### 3.1 创建工具框架

```
metis/
├── tools/
│   ├── __init__.py
│   ├── base.py         # Tool 抽象基类
│   ├── registry.py     # 工具注册中心
│   ├── builtin/        # 内置工具
│   │   ├── __init__.py
│   │   ├── shell.py    # Shell 命令执行
│   │   ├── file.py     # 文件读写
│   │   ├── web.py      # 网页抓取
│   │   └── search.py   # 搜索工具
│   └── mcp/            # MCP 协议工具
│       ├── __init__.py
│       └── client.py   # MCP 客户端
```

#### 3.2 `tools/base.py` — 工具抽象

```python
from abc import ABC, abstractmethod
from typing import Any

class Tool(ABC):
    """所有工具的基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称（唯一标识）"""

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述（LLM 看到的说明）"""

    @abstractmethod
    def parameters(self) -> dict:
        """工具参数的 JSON Schema 定义"""

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """执行工具逻辑"""

    def to_openai_tool(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }
```

#### 3.3 `tools/registry.py` — 工具注册中心

```python
class ToolRegistry:
    """工具注册与执行中心"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_many(self, tools: list[Tool]) -> None:
        for t in tools:
            self.register(t)

    def get_definitions(self) -> list[dict]:
        """返回所有工具的 OpenAI 格式定义"""
        return [t.to_openai_tool() for t in self._tools.values()]

    async def execute(self, name: str, arguments: dict) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return f"Error executing tool '{name}': {str(e)}"
```

#### 3.4 内置工具实现

**`shell.py`** — Shell 命令执行：
- 执行 shell 命令并返回输出
- 安全限制：命令白名单 / 确认机制 / 超时控制

**`file.py`** — 文件操作：
- `read_file(path)` — 读取文件内容
- `write_file(path, content)` — 写入文件
- `list_dir(path)` — 列出目录

**`web.py`** — 网页抓取：
- `fetch_url(url)` — 获取网页内容（使用 httpx）

**`search.py`** — 搜索工具：
- 可对接 SearXNG / SerpAPI / Tavily

#### 3.5 MCP 协议客户端（基础版）

- 实现 MCP 客户端连接外部 MCP Server
- 自动发现 MCP Server 提供的工具并注册到 ToolRegistry
- 使用 SSE 或 stdio 传输协议

---

### 阶段四：Skill 系统（让 Agent 有专长）

> **目标**：模仿 nanobot 的 Skill 机制，让 Agent 具备领域专长。Skill 本质是"给 LLM 的专家提示 + 配套工具"。

#### 4.1 创建 Skill 框架

```
metis/
├── skills/
│   ├── __init__.py
│   ├── base.py         # Skill 抽象 & 加载器
│   ├── manager.py      # Skill 管理器
│   └── builtins/       # 内置 Skill
│       ├── daily_briefing/
│       │   └── SKILL.md
│       └── code_assistant/
│           ├── SKILL.md
│           └── scripts/
│               └── lint.py
```

#### 4.2 Skill 结构定义

每个 Skill 是一个目录，包含：

```
skill-name/
├── SKILL.md          # 必须：YAML frontmatter + Markdown 指令
│   ---
│   name: skill-name
│   description: "什么时候触发、做什么"
│   ---
│   # 使用指南
│   具体步骤和上下文信息...
└── scripts/          # 可选：配套脚本
    └── helper.py
└── references/       # 可选：参考资料
    └── api_docs.md
```

#### 4.3 `skills/base.py` — Skill 模型

```python
@dataclass
class Skill:
    name: str
    description: str          # LLM 用来判断是否触发
    instructions: str         # 触发后加载到上下文的详细指令
    scripts_path: Path | None # 配套脚本目录
    references_path: Path | None # 参考资料目录
    tools: list[Tool] = field(default_factory=list) # Skill 附带的工具

class SkillLoader:
    """从文件系统加载 Skill"""
    def load_from_dir(self, skill_dir: Path) -> Skill:
        """解析 SKILL.md 的 frontmatter + body"""
    def load_all(self, skills_root: Path) -> list[Skill]:
        """扫描目录，加载所有 Skill"""
```

#### 4.4 `skills/manager.py` — Skill 管理器

```python
class SkillManager:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def load_skills(self, skills_dir: Path) -> None:
        """启动时自动加载所有 Skill"""

    def get_skill_descriptions(self) -> str:
        """返回所有 Skill 的 name + description，用于系统提示"""

    def get_skill_instructions(self, name: str) -> str | None:
        """获取 Skill 的详细指令，按需加载"""

    def get_skill_tools(self) -> list[Tool]:
        """收集所有 Skill 附带的工具，注册到 ToolRegistry"""
```

**关键设计**（学习 nanobot 的 Token 效率思想）：
- 启动时只加载 Skill 的 **name + description**（轻量元数据）
- 当 LLM 判断需要某个 Skill 时，才加载其 **instructions**（按需加载）
- 参考资料只在 Skill 内部指令指引时读取（惰性加载）
- 这样避免一次性把所有 Skill 塞满上下文窗口

#### 4.5 内置 Skill 示例

**`daily_briefing`**：每日简报 Skill
- description: "获取天气、新闻摘要、日程提醒"
- instructions: 调用 web 工具获取信息，组织成简报格式

**`code_assistant`**：代码助手 Skill
- description: "代码编写、审查、调试、重构"
- instructions: 代码规范、项目结构说明
- scripts/: lint.py 格式化脚本

---

### 阶段五：数据库存储与会话管理（让 Agent 有记忆）

> **目标**：基于现有的 PgJsonStore，实现会话历史持久化、自动上下文压缩、会话总结。

#### 5.1 会话存储层

```
metis/
├── memory/
│   ├── __init__.py
│   ├── session_store.py   # 会话 CRUD（基于 PgJsonStore）
│   ├── message_store.py   # 消息历史存储
│   └── summary.py         # 自动总结/压缩
```

#### 5.2 `memory/session_store.py` — 会话管理

```python
class SessionStore:
    """会话生命周期管理"""

    async def create_session(self, user_id: str) -> str:
        """创建新会话，返回 session_id"""

    async def get_session(self, session_id: str) -> Session:
        """获取会话信息"""

    async def list_sessions(self, user_id: str) -> list[Session]:
        """列出用户的所有会话"""

    async def delete_session(self, session_id: str) -> None:
        """删除会话"""
```

#### 5.3 `memory/message_store.py` — 消息存储

**设计方案**：使用 PgJsonStore 的 JSONB 存储，每条会话的消息列表存为一个文档。

```python
class MessageStore:
    """消息历史存储"""

    async def append_message(self, session_id: str, message: dict) -> None:
        """追加消息到会话"""

    async def get_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        """获取最近 N 条消息"""

    async def get_message_count(self, session_id: str) -> int:
        """获取消息数量"""

    async def clear_messages(self, session_id: str) -> None:
        """清空会话消息"""
```

**存储结构**（PostgreSQL JSONB）：
```json
{
  "user_id": "user_123",
  "title": "帮助我写一个 Python 脚本",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "...", "content": "..."}
  ],
  "summary": null,
  "token_count": 1500,
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:05:00Z"
}
```

#### 5.4 `memory/summary.py` — 自动上下文压缩

**这是 nanobot 最有价值的设计之一**：当消息历史超过上下文窗口的阈值时，自动压缩旧消息为摘要。

```python
class ContextCompressor:
    """上下文自动压缩器"""

    def __init__(self, provider: LLMProvider, model: str, max_context_tokens: int):
        self.provider = provider
        self.model = model
        self.max_context_tokens = max_context_tokens
        self.compress_threshold = 0.7  # 达到 70% 时触发压缩

    async def should_compress(self, messages: list[dict]) -> bool:
        """判断是否需要压缩（基于 token 估算）"""

    async def compress(self, messages: list[dict]) -> list[dict]:
        """
        压缩策略：
        1. 保留系统消息和最近 N 轮对话
        2. 对旧消息使用 LLM 生成摘要
        3. 返回 [系统消息, 摘要消息, 最近对话]
        """

    async def generate_summary(self, old_messages: list[dict]) -> str:
        """使用 LLM 对旧消息生成结构化摘要"""
```

**压缩后的消息结构**：
```python
[
    {"role": "system", "content": "系统提示..."},
    {"role": "system", "content": "[会话摘要] 用户之前在讨论XXX，Agent 使用了YYY工具完成了ZZZ..."},
    {"role": "user", "content": "最近的消息..."},
    {"role": "assistant", "content": "最近的回复..."},
]
```

---

### 阶段六：知识图谱（让 Agent 有知识网络）

> **目标**：集成 Neo4j 图数据库，让 Agent 能构建和查询知识图谱，实现关系推理。

#### 6.1 知识图谱框架

```
metis/
├── knowledge/
│   ├── __init__.py
│   ├── graph_store.py     # Neo4j 图存储层
│   ├── schema.py          # 图谱 Schema 定义
│   ├── extractor.py       # 从文本中提取实体和关系
│   └── queries.py         # 常用图查询
```

#### 6.2 `knowledge/graph_store.py` — Neo4j 存储层

```python
class GraphStore:
    """Neo4j 知识图谱存储"""

    def __init__(self, uri: str, user: str, password: str):
        # 使用 neo4j Python 驱动

    async def add_entity(self, entity: Entity) -> str:
        """添加实体节点"""

    async def add_relation(self, relation: Relation) -> None:
        """添加关系边"""

    async def query(self, cypher: str, params: dict = None) -> list[dict]:
        """执行 Cypher 查询"""

    async def search_entities(self, name: str, limit: int = 10) -> list[Entity]:
        """模糊搜索实体"""

    async def get_neighbors(self, entity_id: str, depth: int = 1) -> dict:
        """获取实体的邻居（用于上下文扩展）"""

    async def get_subgraph(self, entity_ids: list[str]) -> dict:
        """获取子图（用于可视化或推理）"""
```

#### 6.3 `knowledge/schema.py` — 图谱数据模型

```python
@dataclass
class Entity:
    id: str
    name: str
    type: str           # Person / Organization / Concept / Event / ...
    properties: dict    # 额外属性

@dataclass
class Relation:
    source_id: str
    target_id: str
    relation_type: str  # related_to / works_for / depends_on / ...
    properties: dict
```

#### 6.4 `knowledge/extractor.py` — 知识提取器

```python
class KnowledgeExtractor:
    """使用 LLM 从文本中提取实体和关系"""

    async def extract(self, text: str) -> tuple[list[Entity], list[Relation]]:
        """
        调用 LLM 分析文本，提取：
        - 命名实体（人名、组织、概念等）
        - 实体间关系
        返回结构化的 Entity + Relation 列表
        """

    async def extract_and_store(self, text: str, graph_store: GraphStore) -> None:
        """提取并直接存入图数据库"""
```

#### 6.5 将知识图谱集成到 Agent Loop

在 Agent Loop 中增加知识图谱的读写能力：
- **写入**：当用户分享新知识时，Agent 自动提取并存储到图谱
- **读取**：当讨论某个话题时，Agent 查询相关实体和关系，作为额外上下文注入
- **工具化**：将图谱查询暴露为工具，LLM 可自主决定何时查询

```python
# 注册为工具
class GraphSearchTool(Tool):
    name = "knowledge_graph_search"
    description = "在知识图谱中搜索实体和关系"

class GraphAddTool(Tool):
    name = "knowledge_graph_add"
    description = "向知识图谱中添加实体和关系"
```

#### 6.6 更新 Docker Compose

```yaml
services:
  neo4j:
    image: neo4j:5-community
    container_name: metis_kg
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}
    ports:
      - "7474:7474"  # Browser
      - "7687:7687"  # Bolt
    volumes:
      - neo4jdata:/data
```

---

### 阶段七：CLI 交互与集成（让 Agent 能沟通）

> **目标**：提供命令行交互界面，将所有模块串联起来，形成一个可运行的完整 Agent。

#### 7.1 CLI 入口

```
metis/
├── cli.py              # CLI 入口
```

```python
# 使用 argparse 或 click
# metis chat          → 进入交互式对话
# metis chat -m "xxx" → 单次对话
# metis sessions      → 列出历史会话
# metis skills        → 列出已加载的 Skill
# metis tools         → 列出可用工具
```

#### 7.2 `main.py` — 主入口串联

```python
async def main():
    # 1. 加载配置
    cfg = config

    # 2. 创建 Provider
    provider_snapshot = make_provider(cfg)

    # 3. 初始化存储
    pg_store = get_pg_store()
    pg_store.init_table("sessions")
    pg_store.init_table("messages")

    # 4. 加载工具
    tool_registry = ToolRegistry()
    tool_registry.register_many([
        ShellTool(),
        FileReadTool(),
        FileWriteTool(),
        WebFetchTool(),
    ])

    # 5. 加载 Skills
    skill_manager = SkillManager()
    skill_manager.load_skills(Path("skills"))
    # 将 Skill 附带的工具注册到 tool_registry
    tool_registry.register_many(skill_manager.get_skill_tools())

    # 6. 初始化记忆
    session_store = SessionStore(pg_store)
    message_store = MessageStore(pg_store)
    compressor = ContextCompressor(provider_snapshot.provider, provider_snapshot.model, 
                                    provider_snapshot.context_window_tokens)

    # 7. 创建 Agent Loop
    agent = AgentLoop(provider_snapshot, tool_registry, message_store, 
                      skill_manager, compressor)

    # 8. 启动交互
    await cli_interactive(agent, session_store)
```

---

## 四、最终目录结构

```
Metis/
├── pyproject.toml
├── docker-compose.yml          # PostgreSQL + Neo4j
├── .env.example
├── metis/
│   ├── __init__.py
│   ├── main.py                 # 主入口
│   ├── cli.py                  # CLI 交互
│   ├── config/
│   │   ├── __init__.py
│   │   ├── config.py           # YAML 配置（已有）
│   │   ├── config.yaml.example # 示例配置（新建）
│   │   └── schema.py           # Pydantic 模型（已有，扩展）
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py             # LLM 抽象基类（已有）
│   │   ├── factory.py          # 工厂（补全）
│   │   └── openai_compat_provider.py  # OpenAI 兼容（已有）
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── loop.py             # 核心 Agent 循环
│   │   ├── state.py            # 状态管理
│   │   └── prompts.py          # Prompt 管理
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py             # Tool 抽象基类
│   │   ├── registry.py         # 工具注册中心
│   │   ├── builtin/
│   │   │   ├── __init__.py
│   │   │   ├── shell.py        # Shell 执行
│   │   │   ├── file.py         # 文件操作
│   │   │   ├── web.py          # 网页抓取
│   │   │   └── search.py       # 搜索
│   │   └── mcp/
│   │       ├── __init__.py
│   │       └── client.py       # MCP 客户端
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── base.py             # Skill 模型 & 加载器
│   │   ├── manager.py          # Skill 管理器
│   │   └── builtins/
│   │       ├── daily_briefing/
│   │       │   └── SKILL.md
│   │       └── code_assistant/
│   │           ├── SKILL.md
│   │           └── scripts/
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── session_store.py    # 会话管理
│   │   ├── message_store.py    # 消息存储
│   │   └── summary.py          # 自动压缩
│   ├── knowledge/
│   │   ├── __init__.py
│   │   ├── graph_store.py      # Neo4j 存储
│   │   ├── schema.py           # 图谱数据模型
│   │   ├── extractor.py        # 知识提取
│   │   └── queries.py          # 常用查询
│   └── utils/
│       ├── __init__.py
│       └── pgsql_store.py      # PostgreSQL 存储（已有）
├── tests/
│   ├── test_agent_loop.py
│   ├── test_tool_registry.py
│   ├── test_skill_loader.py
│   └── test_memory.py
└── skills/                     # 用户自定义 Skill 目录
    └── my_skill/
        └── SKILL.md
```

---

## 五、开发优先级与时间线

```
Week 1-2  │ 阶段一 + 阶段二          │ 基础设施 + Agent Loop
Week 3-4  │ 阶段三                   │ 工具系统（含内置工具）
Week 5-6  │ 阶段四 + 阶段五          │ Skill 系统 + 会话存储
Week 7-8  │ 阶段六                   │ 知识图谱
Week 9    │ 阶段七                   │ CLI 集成 + 端到端测试
Week 10   │ 优化 & 文档              │ 性能调优、错误处理、使用文档
```

---

## 六、关键学习要点

### 从 nanobot 学到的核心设计思想

1. **Agent Loop 是灵魂**：所有复杂性都围绕一个简单的循环展开 — LLM 决策 → 工具执行 → 观察结果 → 再决策
2. **Token 是公共资源**：Skill 的元数据和指令分离加载，避免上下文窗口浪费
3. **工具是 Agent 的手**：Tool 的 `name + description + parameters` JSON Schema 是 LLM 理解工具的唯一途径，写好描述至关重要
4. **记忆需要压缩**：无限增长的消息历史不可行，必须实现自动摘要机制
5. **Skill 不是代码，是知识**：Skill 的核心是 SKILL.md 中的指令文本，而非 Python 代码。它教 LLM "怎么做"，而非替 LLM "做"
6. **知识图谱增强推理**：结构化的实体-关系信息让 LLM 能做更深层的关系推理，而非仅依赖上下文中的文本

### 每个阶段的学习目标

| 阶段 | 学到什么 |
|------|---------|
| 一 | Python 项目工程化：pyproject.toml、配置管理、工厂模式 |
| 二 | Agent 核心循环：ReAct 模式、异步编程、LLM API 交互 |
| 三 | 工具抽象与注册：ABC 模式、JSON Schema、MCP 协议 |
| 四 | Prompt 工程：Skill 设计、元数据驱动加载、上下文管理 |
| 五 | 数据持久化：PostgreSQL JSONB、会话生命周期、自动压缩算法 |
| 六 | 图数据库：Neo4j、Cypher、知识提取、结构化推理 |
| 七 | 系统集成：模块编排、CLI 设计、端到端测试 |

---

## 七、技术选型

| 领域 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 生态丰富，学习成本低 |
| LLM API | OpenAI SDK (async) | 兼容性最广，已有实现 |
| 关系数据库 | PostgreSQL 17 + JSONB | 已有实现，灵活 schema |
| 图数据库 | Neo4j 5 Community | 成熟稳定，Python 驱动完善 |
| CLI | argparse / click | 轻量，无额外依赖 |
| 异步 | asyncio + httpx | 与现有 OpenAI async 一致 |
| 配置 | YAML + Pydantic | 已有基础，类型安全 |
| 测试 | pytest + pytest-asyncio | Python 标准选择 |

---

## 八、风险与应对

| 风险 | 应对 |
|------|------|
| LLM 幻觉导致工具调用错误 | 工具执行加 try-catch，返回错误信息给 LLM 自我修正 |
| 上下文窗口溢出 | 自动压缩机制 + Token 计数预警 |
| 知识图谱提取质量不稳定 | 少样本提示 + 人工校验模式，后期可微调 |
| MCP 协议对接复杂度 | 先实现基础版（stdio），后续迭代 SSE |
| 异步/同步混合问题 | 存储层逐步迁移到 asyncpg，或使用 `asyncio.to_thread` 桥接 |
