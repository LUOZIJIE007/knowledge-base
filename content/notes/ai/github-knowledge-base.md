---
title: "GitHub 知识库系统构建指南"
date: 2026-10-29
tags: [ai, knowledge-management, github, automation]
category: notes/ai
summary: "利用 GitHub 生态构建全栈知识管理平台的完整方案"
status: active
source: ""
---

# GitHub 知识库系统构建指南
> 个人与团队知识管理平台 — 基于 GitHub 全栈方案

## 核心要点
- GitHub 仓库 = source of truth，Markdown 存储知识
- GitHub Pages 提供免费静态网站托管
- GitHub Actions 实现全流程自动化
- GitHub Models 提供免费 AI 能力
- Obsidian + Git 插件实现本地编辑与云端同步

## 技术栈

| 组件 | 技术 | 成本 |
|------|------|------|
| 托管 | GitHub 仓库 + Pages | $0 |
| 版本控制 | Git | $0 |
| CI/CD | GitHub Actions | $0 |
| 静态网站 | Jekyll/Hugo | $0 |
| 全文搜索 | Lunr.js（客户端） | $0 |
| AI 处理 | GitHub Models (GPT-4o-mini) | $0/月 |
| AI Agent | Claude/GPT 直接读 Markdown | $0 |

## 六大自动化流程

1. **格式校验**（每次 Push）— Markdown lint、链接检查、Frontmatter 校验
2. **搜索构建**（每次 Push）— 自动生成全文搜索索引
3. **网站部署**（每次 Push）— 构建静态站点并发布
4. **AI 知识提取**（每日定时）— LLM 提取实体、生成摘要、建立关联
5. **每日摘要**（每日定时）— 汇总当日变更
6. **过期检测**（每周定时）— 标记长期未更新内容

## 与现有系统迁移

| 现有资产 | 迁移方式 |
|----------|----------|
| 本地知识卡片 | 导出为 Markdown → Push 到 GitHub |
| 采集内容 | 整理为 content/notes/ 下的分类文档 |
| 运维系统逻辑 | 移植为 GitHub Actions workflows |
| SRS 复习机制 | 改为 Issue 定时提醒 + 脚本追踪 |
| 运维看板 | 替换为 GitHub Pages 网站 |

## 相关文档
- [[CLAUDE.md]]
- [[llms.txt]]
