---
title: "Python 零依赖架构实践"
date: 2026-10-29
tags: [python, architecture, zero-dependency]
category: notes/engineering
summary: "用 Python 标准库构建生产级 Web 应用的架构经验"
status: active
---

# Python 零依赖架构实践
> 用标准库构建可维护、可扩展的 Web 应用

## 核心要点
- http.server + sqlite3 + urllib 即可构建完整 CRUD 应用
- 零依赖意味着无供应链风险、快速部署、低学习成本
- 适合个人项目、内部工具、知识管理类应用
- 关键：分层清晰（数据层 → 业务层 → API 层 → 前端层）

## 分层架构

```
app.py          → HTTP 服务 + API 路由（入口层）
db.py           → SQLite 数据访问（数据层）
llm.py          → AI 接口封装（业务层）
pipeline.py     → 蒸馏/问答流水线（业务层）
metacognition.py → 元认知/SRS（业务层）
static/         → 前端（展示层）
```

## 关键设计模式
1. **自动提交模式**：`sqlite3.connect(path, isolation_level=None)` 避免手动 commit 遗漏
2. **WAL 模式**：`PRAGMA journal_mode=WAL` 提升并发读性能
3. **线程安全**：`ThreadingHTTPServer` + `daemon_threads=True` 避免线程泄漏
4. **安全响应头**：CSP、X-Frame-Options、X-XSS-Protection 等

## 相关文档
- [[GitHub 知识库系统构建指南]]
