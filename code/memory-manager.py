"""
Memory Manager — 短期记忆 + 长期记忆 分层管理

功能：
1. 短期记忆：自动管理当前会话的对话轮次，滑动窗口防止上下文溢出
2. 长期记忆：通过 ChromaDB 存储和检索跨会话的用户信息

用法:
    from memory_manager import MemoryManager

    mm = MemoryManager()
    mm.add_conversation(user_id="u_001", role="user", content="我喜欢电动车")
    mm.add_conversation(user_id="u_001", role="assistant", content="好的，我记住了")

    # 新会话时检索
    memories = mm.retrieve_long_term("u_001", query="电动车推荐")
    # → [{"content": "用户喜欢电动车", "score": 0.92}, ...]
"""

import json
import hashlib
import time
from typing import Optional
from collections import defaultdict, deque
from dataclasses import dataclass, field


# ─── 数据模型 ────────────────────────────────


@dataclass
class Message:
    role: str       # "user" | "assistant" | "system" | "tool"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


@dataclass
class LongTermMemory:
    id: str
    content: str
    category: str  # "preference" | "fact" | "event" | "feedback"
    importance: int  # 1-5, 5=最重要
    timestamp: float
    metadata: dict = field(default_factory=dict)


# ─── 短期记忆管理 ────────────────────────────


class ShortTermMemory:
    """
    滑动窗口式短期记忆
    - 保留最近 N 轮对话
    - 自动摘要超过窗口的对话内容
    - 提取关键实体信息注入当前上下文
    """

    def __init__(self, max_turns: int = 20, summary_threshold: int = 15):
        self.max_turns = max_turns
        self.summary_threshold = summary_threshold
        self.conversations: dict[str, deque[Message]] = defaultdict(
            lambda: deque(maxlen=max_turns)
        )
        self.summaries: dict[str, str] = {}

    def add(self, session_id: str, role: str, content: str, metadata: dict = None):
        msg = Message(role=role, content=content, metadata=metadata or {})
        self.conversations[session_id].append(msg)

        # 超过阈值时生成摘要
        if len(self.conversations[session_id]) > self.summary_threshold:
            self._summarize_old(session_id)

        # 提取关键实体并注入元数据
        self._extract_entities(msg)

    def get_context(self, session_id: str, last_n: int = None) -> list[dict]:
        """获取当前会话上下文"""
        msgs = list(self.conversations[session_id])
        if last_n:
            msgs = msgs[-last_n:]

        context = []
        if session_id in self.summaries:
            context.append({
                "role": "system",
                "content": f"[对话历史摘要] {self.summaries[session_id]}"
            })

        for m in msgs:
            entry = {"role": m.role, "content": m.content}
            if m.metadata:
                entry["metadata"] = m.metadata
            context.append(entry)

        return context

    def _summarize_old(self, session_id: str):
        """将早期对话压缩为摘要（实际项目中调 LLM 生成）"""
        msgs = list(self.conversations[session_id])
        old_msgs = msgs[: len(msgs) // 2]
        recent_msgs = msgs[len(msgs) // 2 :]

        # 简化版摘要：提取关键主题
        topics = set()
        for m in old_msgs:
            if m.role == "user":
                # 简单的关键实体提取（生产环境建议用 LLM 或 NER）
                keywords = [w for w in m.content.split() if len(w) > 2]
                topics.update(keywords[:5])

        self.summaries[session_id] = f"用户讨论过: {', '.join(list(topics)[:10])}"
        self.conversations[session_id] = deque(recent_msgs, maxlen=self.max_turns)

    def _extract_entities(self, msg: Message):
        """提取关键实体（生产环境建议接入 NER 模型）"""
        # 预留接口：可接入 SpaCy / LLM 做实体提取
        pass


# ─── 长期记忆管理 ────────────────────────────


class LongTermMemory:
    """
    基于 ChromaDB 的长期记忆
    - 存储用户偏好、历史事实、反馈
    - 新会话时语义检索相关记忆
    - 重要性评分决定记忆保留策略
    """

    def __init__(self, persist_dir: str = "./memory_db"):
        self.persist_dir = persist_dir
        self._storage: dict[str, list[LongTermMemory]] = defaultdict(list)
        self._chroma_available = False

        # 尝试初始化 ChromaDB
        try:
            import chromadb
            self.client = chromadb.PersistentClient(path=persist_dir)
            self.collection = self.client.get_or_create_collection("long_term_memory")
            self._chroma_available = True
            print(f"[Memory] ChromaDB 已初始化: {persist_dir}")
        except ImportError:
            print("[Memory] ChromaDB 未安装，使用内存存储（重启丢失）")
            print("[Memory] 安装: pip install chromadb")

    def store(self, user_id: str, content: str, category: str = "fact",
              importance: int = 3, metadata: dict = None):
        """存储一条长期记忆"""
        memory_id = hashlib.md5(
            f"{user_id}:{content}:{time.time()}".encode()
        ).hexdigest()[:12]

        memory = LongTermMemory(
            id=memory_id,
            content=content,
            category=category,
            importance=importance,
            timestamp=time.time(),
            metadata=metadata or {},
        )

        if self._chroma_available:
            self.collection.add(
                ids=[memory_id],
                documents=[content],
                metadatas=[{
                    "user_id": user_id,
                    "category": category,
                    "importance": importance,
                    **(metadata or {}),
                }],
            )
        else:
            self._storage[user_id].append(memory)

        return memory_id

    def retrieve(self, user_id: str, query: str, top_k: int = 5,
                 min_score: float = 0.5) -> list[dict]:
        """语义检索相关记忆"""
        if self._chroma_available:
            results = self.collection.query(
                query_texts=[query],
                where={"user_id": user_id},
                n_results=top_k,
            )
            memories = []
            if results["ids"] and results["ids"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    score = 1 - (results["distances"][0][i] if results["distances"] else 0)
                    if score >= min_score:
                        memories.append({
                            "content": doc,
                            "score": round(score, 3),
                            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        })
            return memories
        else:
            # 简易关键词匹配
            results = []
            for mem in self._storage.get(user_id, []):
                overlap = len(set(query) & set(mem.content)) / max(len(query), 1)
                if overlap >= min_score:
                    results.append({
                        "content": mem.content,
                        "score": round(overlap, 3),
                        "category": mem.category,
                    })
            return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]

    def retrieve_all(self, user_id: str, category: str = None) -> list[dict]:
        """获取用户所有长期记忆"""
        if self._chroma_available:
            where = {"user_id": user_id}
            if category:
                where["category"] = category
            results = self.collection.get(where=where)
            return [
                {"content": doc, "metadata": meta}
                for doc, meta in zip(
                    results.get("documents", []),
                    results.get("metadatas", [])
                )
            ]
        else:
            memories = self._storage.get(user_id, [])
            if category:
                memories = [m for m in memories if m.category == category]
            return [{"content": m.content, "category": m.category} for m in memories]

    def forget(self, user_id: str, memory_id: str):
        """删除一条记忆"""
        if self._chroma_available:
            self.collection.delete(ids=[memory_id])
        else:
            self._storage[user_id] = [
                m for m in self._storage.get(user_id, []) if m.id != memory_id
            ]

    def auto_extract_and_store(self, user_id: str, conversation_text: str):
        """
        从对话中自动提取值得长期记忆的信息
        生产环境建议接入 LLM 做信息提取
        """
        # 预留接口：调 LLM 提取关键信息
        # prompt = f"从以下对话中提取值得长期记住的用户信息（偏好/事实/反馈）：\n{conversation_text}"
        # extracted = llm_call(prompt)
        # for item in extracted:
        #     self.store(user_id, item.content, item.category, item.importance)
        pass


# ─── 记忆管理器（整合短期+长期）──────────────


class MemoryManager:
    """
    记忆管理器 —— 整合短期和长期记忆

    用法:
        mm = MemoryManager()

        # 存储对话
        mm.add_conversation("u_001", "user", "我下个月去东京")

        # 存储长期记忆
        mm.remember("u_001", "用户计划下个月去东京旅行", category="event", importance=4)

        # 构建上下文
        context = mm.build_context("u_001", "有什么推荐？")
        # 包含: 短期对话历史 + 长期记忆检索结果
    """

    def __init__(self, persist_dir: str = "./memory_db"):
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory(persist_dir=persist_dir)

    def add_conversation(self, user_id: str, role: str, content: str):
        """添加一条对话到短期记忆"""
        self.short_term.add(user_id, role, content)

    def remember(self, user_id: str, content: str, category: str = "fact",
                 importance: int = 3, metadata: dict = None) -> str:
        """存储一条长期记忆"""
        return self.long_term.store(user_id, content, category, importance, metadata)

    def build_context(self, user_id: str, query: str,
                      include_long_term: bool = True,
                      long_term_top_k: int = 5) -> list[dict]:
        """构建完整的上下文（短期 + 长期记忆），用于注入 System Prompt"""

        context = []

        # 短期记忆
        short_context = self.short_term.get_context(user_id)
        context.extend(short_context)

        # 长期记忆
        if include_long_term:
            memories = self.long_term.retrieve(user_id, query, top_k=long_term_top_k)
            if memories:
                memory_text = "\n".join([
                    f"- {m['content']} (相关度: {m['score']})"
                    for m in memories
                ])
                context.append({
                    "role": "system",
                    "content": f"[Memory: 用户历史信息]\n{memory_text}"
                })

        return context

    def build_context_text(self, user_id: str, query: str,
                           include_long_term: bool = True) -> str:
        """构建上下文文本（用于拼接 Prompt）"""
        msgs = self.build_context(user_id, query, include_long_term)
        return "\n".join([
            f"[{m['role'].upper()}] {m['content']}" for m in msgs
        ])

    def get_user_profile(self, user_id: str) -> dict:
        """获取用户画像（汇总长期记忆）"""
        memories = self.long_term.retrieve_all(user_id)
        profile = {
            "preferences": [m for m in memories if m.get("category") == "preference"],
            "facts": [m for m in memories if m.get("category") == "fact"],
            "events": [m for m in memories if m.get("category") == "event"],
            "feedback": [m for m in memories if m.get("category") == "feedback"],
        }
        return profile


# ─── 使用示例 ────────────────────────────────

if __name__ == "__main__":
    mm = MemoryManager()

    # 模拟对话
    mm.add_conversation("u_001", "user", "我特别喜欢特斯拉的电车")
    mm.add_conversation("u_001", "assistant", "特斯拉确实不错，您有具体的车型偏好吗？")
    mm.add_conversation("u_001", "user", "Model Y，主要是家庭用")

    # 存储长期记忆
    mm.remember("u_001", "用户偏好特斯拉品牌", category="preference", importance=5)
    mm.remember("u_001", "用户需要家庭用车，考虑 Model Y", category="preference", importance=5)
    mm.remember("u_001", "用户之前咨询过充电桩安装问题", category="fact", importance=3)

    # 新会话时构建上下文
    print("=== 构建上下文 ===")
    context = mm.build_context("u_001", "推荐电动车")
    for m in context:
        print(f"[{m['role']}] {m['content'][:100]}...")

    print("\n=== 用户画像 ===")
    profile = mm.get_user_profile("u_001")
    for key, items in profile.items():
        print(f"\n{key}:")
        for item in items:
            print(f"  - {item['content']}")
