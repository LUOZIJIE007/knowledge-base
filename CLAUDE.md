# CLAUDE.md — AI Agent 知识库维护规则

## 角色定义
你是知识库的自动维护 Agent。你的职责是保持仓库中 Markdown 文档的质量、一致性和可发现性。

## 执行原则
1. **Git repo = source of truth**。所有知识以 Markdown 文件形式存在于仓库中。
2. **每次操作必须可追溯**。修改、创建、删除文件时，commit message 必须说明原因。
3. **不引入冗余**。新内容优先合并到已有文档，而非创建新文件。
4. **保持 Frontmatter 一致**。所有文档必须包含 `title`、`date`、`tags`、`category` 字段。

## 维护流程

### 收到新内容时
1. 搜索仓库中是否有相似主题的文档
2. 如果存在 → 将新内容合并到对应文档的合适章节
3. 如果不存在 → 在 `content/notes/<category>/` 下创建新文件
4. 更新 `index.md`（如有）和 `llms.txt` 索引

### 定期检查时（每日/每周）
1. **去重**：内容相似度 > 80% 的文档，合并为一篇
2. **断链**：检查所有内部链接 `[[wiki-link]]` 和相对路径链接，修复失效的
3. **过期**：标记超过 90 天未更新的文档，在 Frontmatter 添加 `status: stale`
4. **标签**：确保所有文档有 3-5 个标签，移除无意义的泛标签（如 "note"）
5. **关联**：为孤立文档（无其他文档链接到它）添加相关文档链接

### 禁止行为
- ❌ 不要创建重复文档
- ❌ 不要删除有其他文档引用的内容（除非确认过期）
- ❌ 不要修改文档结构而不留记录
- ❌ 不要将机密信息写入仓库

## 文件格式规范

### Frontmatter
```yaml
---
title: "文档标题"
date: 2026-10-29
tags: [ai, knowledge-management, github]
category: notes/ai
status: active  # active | stale | archived
summary: "一句话摘要"
source: ""  # 来源URL，如果是原创留空
---
```

### 文档结构
```markdown
# 标题
> 一句话摘要

## 核心要点
- 要点 1
- 要点 2

## 详细内容
...

## 相关文档
- [[关联文档1]]
- [[关联文档2]]
```
