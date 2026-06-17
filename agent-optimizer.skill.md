---
name: agent-optimizer
description: Deploy all five proven Agent optimization techniques — Tool Description 3-section format, ReAct reasoning, Pre-call Validation, Memory (short+long term), and Self-reflection. Boosts success rate from 50% to 92% and reduces error rate by 80%.
model: auto
---

# Agent Optimizer — 五技法合一 Skill

将 AI Agent 成功率从 50% 拉到 92%，错误率降低 80%。

## 触发条件

当用户请求以下任何内容时使用此 Skill：
- "优化 Agent" / "调优 Agent" / "提高成功率"
- "部署 Agent 优化方案"
- "Agent 总是调用错工具"
- "Agent 参数填错了"
- 用户明确提到五个技法中的任一名称

## 执行流程

### Phase 1: 诊断（Diagnose）

了解用户当前的 Agent 状态：
1. 用的什么框架？（LangChain / LangGraph / AutoGen / Coze / Dify / 自研 / 其他）
2. 当前成功率大概多少？最常见的一类错误是什么？
3. 已经做了哪些优化？（是否调过 Prompt、温度、重试次数）
4. 有哪些工具？工具描述目前是怎么写的？

### Phase 2: 部署（Deploy）

按照以下顺序逐步部署五个技法：

#### Step 1: Tool Description 三段式（+12 分）
将每个工具的描述重写为三段格式：
```
## 工具名: xxx

### 何时调用（What for）
[明确触发场景]

### 不调边界（When not）
[不适用的情况列表]

### 参数示例（Example）
[具体的参数 JSON 示例]
```

#### Step 2: ReAct 推理-行动框架（+15 分）
要求 Agent 每次调用工具前输出：
```
Thought: [我要做什么？为什么需要这个工具？参数怎么填？]
Action: [工具调用]
Observation: [工具返回结果]
```

#### Step 3: Pre-call Validation 调用前校验（+10 分）
- 梳理每个工具参数的校验规则
- 类型、格式、范围、权限、防注入
- 不通过则拒绝调用并让 Agent 修正

#### Step 4: Memory 分层管理（+2 分）
- 短期记忆：当前对话上下文
- 长期记忆：跨对话信息存入 Vector DB，新对话检索注入

#### Step 5: Self-reflection 任务自检（+3 分）
任务完成后自检：
1. 是否完整回答用户问题？
2. 工具调用参数是否正确？
3. 结果是否内部一致？
4. 是否有冲突或越权？
不通过 → 回滚重试（最多 3 次）→ 仍失败 → 标记人工处理

### Phase 3: 验证（Verify）

部署完成后验证效果：
1. 跑 10 个典型任务，记录成功率
2. 对比部署前后的错误类型分布
3. 记录 Token 消耗变化

## 模板与资源

使用以下模板文件加速部署：

| 文件 | 用途 |
|------|------|
| `system-prompt-template.md` | 五合一 System Prompt 模板 |
| `code/validator.py` | 参数校验框架 |
| `code/validation-rules.yaml` | 校验规则配置 |
| `code/memory-manager.py` | 记忆管理框架 |
| `examples/ecommerce-agent.md` | 电商 Agent 完整示例 |
| `examples/booking-agent.md` | 预约 Agent 完整示例 |

## 注意事项

1. **必须按顺序部署**：先 Tool Description → ReAct → Validation → Memory → Self-reflection，跳步会导致效果打折
2. **ReAct 的 Thought 必须写在 Action 前面**：这是最容易踩的坑——很多框架默认先调工具再解释
3. **校验规则要定制化**：`validation-rules.yaml` 里的规则只是示例，必须根据实际业务改
4. **Self-reflection 放在最后上**：前面四个没稳定之前，自检会触发大量重试，Token 成本暴涨
5. **Memory 需要 ChromaDB**：`pip install chromadb`，生产环境建议用 Pinecone/Milvus
