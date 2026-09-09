# -*- coding: utf-8 -*-
"""v4 兜底增强层

当检索器未命中时，路由器按问题性质把请求分发给：
    - LLM 兜底   （通识问答）
    - 实时 API   （天气等）
    - 固定话术   （校园事务 / LLM 失败时降级）

设计原则：
    1. 校园事务绝不进 LLM
    2. 实时问题用真实数据，不靠 LLM 记忆
    3. 任何一层失败都降级到固定话术，永远不裸抛异常
"""
from .router import FallbackRouter, QueryType, dispatch  # noqa: F401