# Knowledge Base

> 个人与团队知识管理平台 — 基于 GitHub 全栈方案

## 快速开始

```bash
# 克隆到本地
git clone https://github.com/yourname/knowledge-base.git

# 用 Obsidian 打开
# File → Open Folder as Vault → 选择 knowledge-base/content/

# 编辑笔记
# 在 content/notes/<category>/ 下创建 .md 文件

# 提交并推送
git add .
git commit -m "docs: add new note"
git push
# → GitHub Actions 自动构建并发布到 GitHub Pages
```

## 目录结构

```
content/
├── notes/        # 个人笔记（按分类）
├── team/         # 团队共享文档
├── public/       # 对外发布文章
└── _templates/   # 模板文件
scripts/          # 自动化脚本
.github/workflows/ # CI/CD 流水线
```

## AI Agent 使用

1. 阅读 `CLAUDE.md` 了解维护规则
2. 使用 `llms.txt` 了解仓库结构
3. 通过 `scripts/extract_knowledge.py` 进行 AI 知识提取

## 许可证

MIT
