"""Intent-classification lexicons for MemoryRetrievalPlanner.

Each lane has a frozenset of trigger words matched against
``jieba.lcut(user_message.lower())`` tokens. See spec §7 of
docs/superpowers/specs/2026-04-20-memory-retrieval-fixes-design.md
for rationale.

Note: High-frequency tokens like '是', 'i', 'my', 'this', 'how'
are intentional — they serve as weak signals in combination with
other tokens after jieba segmentation. Planner callers are
responsible for any additional context-based filtering (e.g., the
small-talk short-circuit uses ``len(tokens) <= 3``).
"""

from __future__ import annotations

# Profile Lane — 画像/偏好/稳定身份触发语
PROFILE_LANE_WORDS: frozenset[str] = frozenset(
    {
        # 自指代词
        "我",
        "我的",
        "本人",
        "自己",
        # 偏好动词
        "喜欢",
        "偏好",
        "爱好",
        "讨厌",
        "不喜欢",
        "讨厌的",
        "最爱",
        "prefer",
        "like",
        "love",
        "hate",
        "dislike",
        "favorite",
        # 身份陈述
        "是",
        "我是",
        "am",
        "i",
        "i'm",
        "my",
        "mine",
        # 隐式偏好意图（推荐/建议类动词）
        "推荐",
        "建议",
        "觉得",
        "认为",
        "想要",
        "希望",
        "recommend",
        "suggest",
        "think",
        "believe",
        "want",
        "wish",
        # 口味/性格描述
        "口味",
        "风格",
        "习惯",
        "性格",
        "脾气",
        "style",
        "habit",
        "taste",
        "personality",
    }
)

# Context Lane — 当前时间/动态性副词与进展询问
CONTEXT_LANE_WORDS: frozenset[str] = frozenset(
    {
        # 时间指示
        "现在",
        "今天",
        "最近",
        "这两天",
        "本周",
        "这周",
        "目前",
        "当前",
        "正在",
        "此刻",
        "今晚",
        "今早",
        "今晨",
        "now",
        "today",
        "tonight",
        "currently",
        "recent",
        "recently",
        "this",
        "week",
        # 进展询问
        "进展",
        "进度",
        "情况",
        "状态",
        "怎么样",
        "如何",
        "到哪了",
        "status",
        "progress",
        "update",
        "how",
        # 正在做
        "在做",
        "在忙",
        "在干",
        "doing",
        "working",
    }
)

# Episode Lane — 历史回忆触发语
EPISODE_LANE_WORDS: frozenset[str] = frozenset(
    {
        # 时间回指
        "上次",
        "之前",
        "以前",
        "曾经",
        "那时",
        "当时",
        "last",
        "previously",
        "before",
        "earlier",
        "ago",
        # 回忆动词
        "记得",
        "想起",
        "回忆",
        "回顾",
        "忘了",
        "忘记",
        "remember",
        "recall",
        "forgot",
        "forget",
        "reminded",
        # 历史讨论
        "讨论过",
        "说过",
        "聊过",
        "提过",
        "讲过",
        "discussed",
        "mentioned",
        "said",
        "told",
        # 过往事件
        "那次",
        "那天",
        "那一次",
        "that",
        "time",
    }
)

# Relation Lane — 静态通用称谓（动态部分由 Entity Registry 运行期合并）
RELATION_LANE_STATIC_WORDS: frozenset[str] = frozenset(
    {
        # 家庭
        "老婆",
        "妻子",
        "太太",
        "爱人",
        "老公",
        "丈夫",
        "伴侣",
        "孩子",
        "儿子",
        "女儿",
        "宝宝",
        "娃",
        "爸爸",
        "妈妈",
        "父母",
        "爸",
        "妈",
        "父亲",
        "母亲",
        "哥哥",
        "姐姐",
        "弟弟",
        "妹妹",
        "兄弟",
        "姐妹",
        "wife",
        "husband",
        "kid",
        "kids",
        "son",
        "daughter",
        "dad",
        "mom",
        "father",
        "mother",
        "parent",
        "parents",
        "brother",
        "sister",
        "sibling",
        # 工作
        "同事",
        "老板",
        "下属",
        "上司",
        "领导",
        "队友",
        "项目",
        "团队",
        "小组",
        "colleague",
        "coworker",
        "team",
        "teammate",
        "project",
        "boss",
        "manager",
        "lead",
        # 社交
        "朋友",
        "好友",
        "伙伴",
        "邻居",
        "friend",
        "buddy",
        "partner",
        "neighbor",
        # 宠物
        "宠物",
        "猫",
        "狗",
        "小猫",
        "小狗",
        "pet",
        "cat",
        "dog",
    }
)

# Small-talk 短路词（tokens & SMALL_TALK_WORDS 且 len(tokens) <= 3 → 所有 lane 关闭）
SMALL_TALK_WORDS: frozenset[str] = frozenset(
    {
        # 英文问候
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "morning",
        "evening",
        "night",
        # 中文问候
        "你好",
        "您好",
        "嗨",
        "哈喽",
        "早",
        "早上好",
        "晚上好",
        "晚安",
        # 确认/致谢
        "ok",
        "okay",
        "好",
        "好的",
        "行",
        "嗯",
        "收到",
        "谢谢",
        "多谢",
        "感谢",
        "thanks",
        "thank",
        "thx",
        "ty",
        # 告别
        "bye",
        "再见",
        "拜拜",
    }
)
