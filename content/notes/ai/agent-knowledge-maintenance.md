---
title: "AI Agent 知识库维护最佳实践"
date: 2026-10-29
tags: [ai, agent, knowledge-management, claude]
category: notes/ai
summary: "如何让 AI Agent 自动维护 GitHub 知识库的完整方法论"
status: active
---

# AI Agent 知识库维护最佳实践
> 让 AI 成为知识库的自动化管理员

## 核心要点
- Git repo 是唯一事实来源（source of truth）
- CLAUDE.md 定义 Agent 维护规则
- 内容指纹（SHA256）避免重复提取
- 定期检查：去重、断链、过期、标签、关联
- 禁止行为：创建重复文档、删除被引用内容

## Agent 维护流程

### 收到新内容
1. 搜索仓库相似主题
2. 存在 → 合并到已有文档
3. 不存在 → 创建新文件
4. 更新索引

### 定期检查（每日/每周）
1. **去重**：相似度 > 80% 合并
2. **断链**：修复失效链接
3. **过期**：标记 90 天未更新内容
4. **标签**：确保 3-5 个有效标签
5. **关联**：为孤立文档添加链接

## 实现方案

| 方案 | 技术 | 成本 |
|------|------|------|
| GitHub Actions | 定时触发 AI 脚本 | $0 |
| GitHub Models | GPT-4o-mini 提取实体 | $0/月 |
| 缓存 | SHA256 内容指纹 | $0 |
| 通知 | GitHub RSS / Email | $0 |

## 相关文档
- [[GitHub 知识库系统构建指南]]
- [[Python 零依赖架构实践]]
