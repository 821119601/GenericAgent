# Obsidian知识库写作SOP

## 0. 适用范围
向 Deeting Knowledge Vault (E:\Deeting_knowledge\Deeting_knowledge) 写入任何内容时遵循。

## 1. 写入硬约束
- .raw/ 目录**不可变**，禁止修改/删除其中任何文件
- 禁止删除已有页面（除非用户明确指示）
- 优先更新现有页面 > 创建新页面（先查重）
- 每次写入后**必须**：更新索引 → 追加日志(顶部) → 更新热缓存(~500字)

## 2. 文件命名
- 中文优先，2-10字，避免特殊字符
- 日期前缀：`YYYY-MM-DD-标题.md`
- 系列文章：`系列名-01-标题.md`
- 决策：`ADR-XXX-标题.md`
- 来源：`来源-标题.md`
- 禁止：新建文档/未命名/纯数字/test/临时/副本

## 3. Frontmatter（每页必需）
```yaml
---
type: [goal|concept|source|entity|paper|project|decision|module|strategy|meta]
title: "标题"
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [标签1, 标签2]  # 最少2个，推荐3-4个，最多5-6个
---
```

### 按类型附加字段
- Goal: status, area, priority, target_date, progress
- Concept: status, category, difficulty
- Source: status, source_type, source_url, author, date
- Entity: category, domain, website
- Paper: status, year, authors, venue
- Project: status, start_date, progress, priority
- Decision: status, date, context
- Module: path, status, language, purpose

## 4. 标签体系（5层）
1. **类型标签**（必需）：goal/concept/source/entity/paper/project/decision/module/meta
2. **领域标签**（推荐）：学习/营销/DTC/技术/研究
3. **主题标签**（可选）：SEO/React/增长黑客
4. **状态标签**（可选）：进行中/已完成/暂停
5. **时间标签**（可选）：2026/2026Q2

## 5. 链接规范
- 每页至少3-5个双向链接 `[[页面名]]`
- 主动连接孤立页面
- 有意义链接文本：`[[页面名|显示文本]]`
- 操作后检查死链接

## 6. 内容格式
- 标题层级：`#`文档标题 → `##`主章节 → `###`子章节
- 正文中文为主，技术术语保留英文
- Callout标注：`[!note]` `[!warning]` `[!tip]` `[!important]`
- 自定义标注：`[!stale]`(过时) `[!contradiction]`(矛盾) `[!gap]`(知识缺口) `[!key-insight]`(关键洞察)

## 7. 写入后三连操作
1. **索引同步**：新建页→更新Wiki/索引.md + 对应子索引
2. **日志追加**：重要操作记入Wiki/日志.md（新条目加顶部，格式：`## [ISO时间] 操作类型 | 描述`）
3. **热缓存更新**：更新Wiki/热缓存.md（最近事实+最近变更+活跃线程，~500字）

## 8. 目录结构速查
```
Wiki/目标/ Wiki/学习/ Wiki/项目/
Wiki/电商/独立站/ Wiki/电商/淘宝/
Wiki/研究/论文/ Wiki/研究/概念/ Wiki/研究/开放问题/
Wiki/代码库/模块/ Wiki/代码库/组件/ Wiki/代码库/决策/
Wiki/实体/ Wiki/概念/ Wiki/来源/ Wiki/元数据/
_模板/  .raw/(不可变!)  .archive/  GA-Brain/
```

## 9. Templates目录映射(Templater)
- wiki/目标/ → _模板/goal.md
- wiki/研究/论文/ → _模板/paper.md
- wiki/代码库/模块/ → _模板/module.md
- wiki/代码库/决策/ → _模板/decision.md
- wiki/实体/ → _模板/entity.md
- wiki/来源/ → _模板/source.md

## 10. Obsidian Bridge API 速查(v2.0)
桥接工具: `memory/obsidian_bridge.py` → `ObsidianBridge()`

### P0 读取能力
| 方法 | 说明 |
|------|------|
| `read_page(section, filename, base)` | 读取页面内容+元数据 |
| `search_vault(query, scope)` | 全文搜索 |
| `get_backlinks(page_name, scope)` | 获取反向链接 |
| `list_pages(section, base)` | 列出目录下所有页面 |
| `page_exists(section, filename, base)` | 检查页面是否存在 |

### P1 丰富化写入
| 方法 | 说明 |
|------|------|
| `enrich_and_write(section, filename, ga_content)` | GA压缩知识→OB详尽页面 |
| `write_to_wiki(section, filename, content)` | 写入Wiki区域(遵循本SOP) |
| `sync_sop(sop_name)` | 同步单个SOP到OB |
| `sync_all_sops()` | 批量同步所有SOP |
| `sync_delta()` | 增量同步(只同步变更) |
| `write_note(title, content)` | 写入GA-Brain区域 |

### P2 质量保证
| 方法 | 说明 |
|------|------|
| `validate_links(scope)` | 双链有效性检查(零假阳性) |
| `update_stale_flags()` | 标记过时页面(GA源已变) |
| `diff_against_ga(section, filename)` | OB↔GA差异比对 |
| `get_recent_changes(hours)` | 最近变更列表 |

### 数据流三原则
1. **GA→OB丰富化写入**: GA为权威源，压缩知识展开为详尽页面
2. **OB→GA按需回读**: OB作为信息源，按需读取回GA工作记忆
3. **OB→GA变更感知**: 检测OB变更，标记需复核内容
