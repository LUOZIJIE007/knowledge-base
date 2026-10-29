# AGENTS.md — AI Agent 接口规范

## 读取接口

### 方式一：直接读取文件
AI Agent 可直接读取 `content/notes/**/*.md` 文件获取知识内容。

### 方式二：通过 llms.txt 导航
1. 读取 `llms.txt` 了解仓库结构
2. 读取 `CLAUDE.md` 了解维护规则
3. 按分类路径访问对应文档

### 方式三：通过搜索索引
```
GET /assets/search-index.json
```
返回所有文档的结构化索引（标题、内容、标签、URL）。

## 写入接口

### 方式一：直接编辑
1. 在 `content/notes/<category>/` 下创建或编辑 `.md` 文件
2. 使用 `content/_templates/note-template.md` 作为模板
3. 确保 Frontmatter 包含：title、date、tags、category

### 方式二：通过 AI 脚本
```bash
python scripts/extract_knowledge.py
```
自动从现有内容中提取知识并生成摘要。

## 维护接口

### 去重检查
```bash
python scripts/check_links.py
```
检查所有内部链接是否有效。

### Frontmatter 校验
```bash
python scripts/check_frontmatter.py
```
校验所有文档的元数据格式。

### 搜索索引重建
```bash
python scripts/build_search_index.py
```
重新生成全文搜索索引。

## 提交规范

| 操作 | Commit message 前缀 |
|------|---------------------|
| 新增文档 | `docs: add` |
| 更新文档 | `docs: update` |
| AI 自动处理 | `chore(ai):` |
| 修复链接 | `fix(links):` |
| 重构结构 | `refactor:` |

## 目录约定

| 路径 | 用途 | 是否公开 |
|------|------|----------|
| `content/notes/` | 个人笔记 | 仓库可见 |
| `content/team/` | 团队共享 | 仓库可见 |
| `content/public/` | 对外发布 | GitHub Pages 发布 |
| `content/_templates/` | 模板 | 仓库可见 |
| `scripts/` | 自动化脚本 | 仓库可见 |
| `.cache/` | AI 提取缓存 | 不提交（.gitignore） |
