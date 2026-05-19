"""
obsidian_bridge.py v2.0 — GA ↔ Obsidian 双向桥接工具
让GA可以读取和写入Obsidian vault，实现神经-皮层双记忆模型

核心升级(v2.0):
  P0: 读取能力 - read_page / search_vault / get_backlinks
  P1: 丰富化写入 - enrich_and_write / write_to_wiki / sync_delta
  P2: 质量保证 - validate_links / update_stale_flags / diff_against_ga

用法(从GA内):
    from memory.obsidian_bridge import ObsidianBridge
    ob = ObsidianBridge()
    
    # ===== 写入(GA→OB) =====
    ob.write_note("知识库/PPT设计", "测试.md", "内容", tags=["测试"])
    ob.write_to_wiki("代码库/模块", "新模块.md", "内容", tags=["模块"])
    ob.enrich_and_write("AI中转站", expanded_content)
    ob.sync_delta(since_hours=24)
    ob.append_log("完成了XX任务")
    ob.log_decision("选X方案", "因为Y原因")
    
    # ===== 读取(OB→GA) =====
    page = ob.read_page("代码库/模块", "核心引擎.md")
    results = ob.search_vault("PPT", scope="Wiki")
    links = ob.get_backlinks("核心引擎")
    exists = ob.page_exists("代码库/模块", "核心引擎.md")
    
    # ===== 质量保证 =====
    broken = ob.validate_links(scope="Wiki")
    stale = ob.update_stale_flags()
    diff = ob.diff_against_ga("AI中转站")
    changes = ob.get_recent_changes(hours=48)
"""
import os
import re
import json
from datetime import datetime

VAULT_PATH = r"E:\Deeting_knowledge\Deeting_knowledge"
GA_BRAIN = "GA-Brain"
GA_MEMORY = r"C:\Users\82111\GenericAgent\memory"

# SOP分类映射: 文件名前缀 → Obsidian子目录
SOP_CATEGORY_MAP = {
    "ppt": "PPT设计",
    "skillforge": "PPT设计",
    "ljqCtrl": "开发工具",
    "tmwebdriver": "开发工具",
    "vision": "开发工具",
    "ocr": "开发工具",
    "adb": "开发工具",
    "asr": "开发工具",
    "vue3": "开发工具",
    "memory": "系统运维",
    "scheduled": "系统运维",
    "autonomous": "系统运维",
    "supervisor": "系统运维",
    "ga_upstream": "系统运维",
    "github": "系统运维",
    "web": "系统运维",
    "plan_sop": "系统运维",
    "deepresearch": "系统运维",
    "code_review": "系统运维",
    "review": "系统运维",
    "metapi": "系统运维",
    "morphling": "系统运维",
    "goal": "系统运维",
}

# L2 section → Wiki页面映射(丰富化写入时用)
L2_SECTION_MAP = {
    "基本环境": ("实体", "GenericAgent"),
    "AI中转站生态": ("概念", "AI中转站"),
    "依赖环境": ("代码库/模块", "记忆系统"),
    "PPT设计工具库": ("概念", "PPT自动化能力"),
    "GA Git": ("代码库/模块", "工具集"),
    "TUI v2 Monitor": ("代码库/组件", "前端界面"),
    "GA Manager": ("代码库/模块", "工具集"),
    "Obsidian知识库": ("概念", "知识库架构"),
}


class ObsidianBridge:
    def __init__(self, vault_path=VAULT_PATH, ga_memory=GA_MEMORY):
        self.vault_path = vault_path
        self.ga_brain = os.path.join(vault_path, GA_BRAIN)
        self.wiki_path = os.path.join(vault_path, "Wiki")
        self.ga_memory = ga_memory
        os.makedirs(self.ga_brain, exist_ok=True)

    # ============================================================
    #  内部工具方法
    # ============================================================

    def _resolve_path(self, category: str, filename: str, 
                      base: str = None) -> str:
        """解析完整路径，自动.md后缀
        base: None=GA-Brain, 'wiki'=Wiki/, 'vault'=vault根目录
        """
        if not filename.endswith(".md"):
            filename += ".md"
        if base == "wiki":
            root = self.wiki_path
        elif base == "vault":
            root = self.vault_path
        else:
            root = self.ga_brain
        return os.path.join(root, category, filename)

    def _parse_frontmatter(self, content: str) -> dict:
        """解析markdown frontmatter"""
        if not content.startswith("---"):
            return {}
        end = content.find("---", 3)
        if end == -1:
            return {}
        fm_text = content[3:end].strip()
        result = {}
        for line in fm_text.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                # 解析列表
                if val.startswith("[") and val.endswith("]"):
                    val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                result[key] = val
        return result

    def _build_frontmatter(self, tags: list = None, 
                           source: str = "GA-Bridge",
                           ga_sync_ver: str = None,
                           extra: dict = None) -> str:
        """构建frontmatter字符串"""
        fm = "---\n"
        fm += f"created: {datetime.now().strftime('%Y-%m-%d')}\n"
        fm += f"updated: {datetime.now().strftime('%Y-%m-%d')}\n"
        fm += f"source: {source}\n"
        if ga_sync_ver:
            fm += f"ga_sync_ver: \"{ga_sync_ver}\"\n"
        if tags is None:
            tags = []
        if "ga-brain" not in tags and source == "GA-Bridge":
            tags.insert(0, "ga-brain")
        if tags:
            fm += f"tags: [{', '.join(tags)}]\n"
        if extra:
            for k, v in extra.items():
                fm += f"{k}: {v}\n"
        fm += "---\n\n"
        return fm

    def _extract_wikilinks(self, content: str) -> list:
        """提取内容中的所有[[双链]]"""
        return re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content)

    def _get_sync_ver(self) -> str:
        """获取当前GA记忆版本(基于L2 mtime)"""
        l2_path = os.path.join(self.ga_memory, "global_mem.txt")
        if os.path.exists(l2_path):
            mtime = os.path.getmtime(l2_path)
            return datetime.fromtimestamp(mtime).strftime('%Y-%m-%dT%H:%M')
        return datetime.now().strftime('%Y-%m-%dT%H:%M')

    # ============================================================
    #  P0: 读取能力 (OB → GA)
    # ============================================================

    def read_page(self, category: str, filename: str,
                  base: str = None) -> dict:
        """读取Obsidian页面，返回{frontmatter, body, path, exists}
        base: None=GA-Brain, 'wiki'=Wiki/
        """
        filepath = self._resolve_path(category, filename, base)
        if not os.path.exists(filepath):
            return {"exists": False, "path": filepath, 
                    "frontmatter": {}, "body": ""}
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        fm = self._parse_frontmatter(content)
        # 提取body(fronmatter之后的内容)
        if content.startswith("---"):
            end = content.find("---", 3)
            body = content[end + 3:].strip()
        else:
            body = content
        
        return {
            "exists": True,
            "path": filepath,
            "frontmatter": fm,
            "body": body,
            "size": len(content)
        }

    def search_vault(self, keyword: str, scope: str = None,
                     max_results: int = 20) -> list:
        """全文搜索vault
        scope: None=全vault, 'wiki'=Wiki/, 'brain'=GA-Brain/
        返回: [{path, title, snippet, score}]
        """
        results = []
        keyword_lower = keyword.lower()
        
        if scope == "wiki":
            search_root = self.wiki_path
        elif scope == "brain":
            search_root = self.ga_brain
        else:
            # 搜索两个区域
            return self._search_multi_scope(
                keyword, [self.wiki_path, self.ga_brain], max_results)
        
        for dirpath, _, filenames in os.walk(search_root):
            for fn in filenames:
                if not fn.endswith('.md'):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, 'r', encoding='utf-8') as f:
                        content = f.read()
                except (UnicodeDecodeError, PermissionError):
                    continue
                
                content_lower = content.lower()
                count = content_lower.count(keyword_lower)
                if count == 0:
                    continue
                
                # 提取snippet(关键词前后80字)
                idx = content_lower.find(keyword_lower)
                start = max(0, idx - 80)
                end_idx = min(len(content), idx + len(keyword) + 80)
                snippet = content[start:end_idx].replace('\n', ' ')
                if start > 0:
                    snippet = "..." + snippet
                if end_idx < len(content):
                    snippet = snippet + "..."
                
                rel = os.path.relpath(fp, search_root)
                title = fn.replace('.md', '')
                
                results.append({
                    "path": rel,
                    "title": title,
                    "snippet": snippet,
                    "score": count
                })
        
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]

    def _search_multi_scope(self, keyword: str, roots: list,
                            max_results: int) -> list:
        """多区域搜索辅助"""
        all_results = []
        for root in roots:
            if not os.path.exists(root):
                continue
            for dirpath, _, filenames in os.walk(root):
                for fn in filenames:
                    if not fn.endswith('.md'):
                        continue
                    fp = os.path.join(dirpath, fn)
                    try:
                        with open(fp, 'r', encoding='utf-8') as f:
                            content = f.read()
                    except (UnicodeDecodeError, PermissionError):
                        continue
                    
                    count = content.lower().count(keyword.lower())
                    if count == 0:
                        continue
                    
                    idx = content.lower().find(keyword.lower())
                    start = max(0, idx - 60)
                    end_idx = min(len(content), idx + len(keyword) + 60)
                    snippet = content[start:end_idx].replace('\n', ' ')
                    
                    rel = os.path.relpath(fp, root)
                    all_results.append({
                        "path": rel,
                        "title": fn.replace('.md', ''),
                        "snippet": snippet,
                        "score": count,
                        "root": os.path.basename(root)
                    })
        
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:max_results]

    def get_backlinks(self, page_title: str, 
                      scope: str = None) -> list:
        """获取指向某页面的反向链接列表
        返回: [{path, title, context}]
        """
        results = []
        # 将页面标题转为[[双链]]格式
        link_pattern = f"[[{page_title}"
        
        search_root = self.wiki_path if scope == "wiki" else self.vault_path
        
        for dirpath, _, filenames in os.walk(search_root):
            # 跳过.raw目录
            if ".raw" in dirpath:
                continue
            for fn in filenames:
                if not fn.endswith('.md'):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, 'r', encoding='utf-8') as f:
                        content = f.read()
                except (UnicodeDecodeError, PermissionError):
                    continue
                
                if link_pattern.lower() in content.lower():
                    # 提取包含链接的行作为上下文
                    for line in content.split('\n'):
                        if link_pattern.lower() in line.lower():
                            results.append({
                                "path": os.path.relpath(fp, search_root),
                                "title": fn.replace('.md', ''),
                                "context": line.strip()
                            })
                            break  # 每个文件只取第一个
        
        return results

    def page_exists(self, category: str, filename: str,
                    base: str = None) -> bool:
        """检查页面是否存在"""
        filepath = self._resolve_path(category, filename, base)
        return os.path.exists(filepath)

    def list_pages(self, category: str = "", 
                   base: str = None) -> list:
        """列出某目录下所有页面
        返回: [{filename, path, size, updated}]
        """
        if base == "wiki":
            root = os.path.join(self.wiki_path, category) if category else self.wiki_path
        elif base == "vault":
            root = os.path.join(self.vault_path, category) if category else self.vault_path
        else:
            root = os.path.join(self.ga_brain, category) if category else self.ga_brain
        
        if not os.path.exists(root):
            return []
        
        results = []
        for dirpath, _, filenames in os.walk(root):
            if ".raw" in dirpath:
                continue
            for fn in filenames:
                if not fn.endswith('.md'):
                    continue
                fp = os.path.join(dirpath, fn)
                mtime = os.path.getmtime(fp)
                results.append({
                    "filename": fn,
                    "path": os.path.relpath(fp, root),
                    "size": os.path.getsize(fp),
                    "updated": datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                })
        
        return sorted(results, key=lambda x: x["updated"], reverse=True)

    # ============================================================
    #  写入方法 (GA → OB) - 保留v1并增强
    # ============================================================

    def write_note(self, category: str, filename: str, content: str,
                   tags: list = None, overwrite: bool = False,
                   ga_sync_ver: str = None) -> str:
        """写入笔记到GA-Brain区域
        v2增强: 支持ga_sync_ver版本追踪
        """
        filepath = self._resolve_path(category, filename)
        if os.path.exists(filepath) and not overwrite:
            return f"⚠️ 文件已存在且未设置覆盖: {filepath}"

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        if ga_sync_ver is None:
            ga_sync_ver = self._get_sync_ver()

        frontmatter = self._build_frontmatter(
            tags=tags, source="GA-Bridge", ga_sync_ver=ga_sync_ver)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(frontmatter + content)

        return f"✅ 写入: {os.path.relpath(filepath, self.ga_brain)}"

    def write_to_wiki(self, category: str, filename: str, content: str,
                      tags: list = None, overwrite: bool = False,
                      ga_sync_ver: str = None) -> str:
        """写入页面到Wiki区域(遵循obsidian_writing_sop规范)
        - 自动添加frontmatter(type/created/updated/source/tags/ga_sync_ver)
        - 写入后自动更新对应子索引+日志+热缓存
        """
        filepath = self._resolve_path(category, filename, base="wiki")
        if os.path.exists(filepath) and not overwrite:
            return f"⚠️ 文件已存在且未设置覆盖: {filepath}"

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        if ga_sync_ver is None:
            ga_sync_ver = self._get_sync_ver()

        # 根据目录推断type
        page_type = "page"
        cat_lower = category.lower()
        if "模块" in cat_lower:
            page_type = "module"
        elif "组件" in cat_lower:
            page_type = "module"
        elif "决策" in cat_lower:
            page_type = "decision"
        elif "概念" in cat_lower:
            page_type = "concept"
        elif "实体" in cat_lower:
            page_type = "entity"
        elif "来源" in cat_lower:
            page_type = "source"
        elif "元数据" in cat_lower:
            page_type = "meta"

        extra = {"type": page_type}
        frontmatter = self._build_frontmatter(
            tags=tags, source="GA-Wiki", 
            ga_sync_ver=ga_sync_ver, extra=extra)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(frontmatter + content)

        # 三连更新
        self._update_sub_index(category)
        self._append_sync_log(f"写入Wiki/{category}/{filename}")
        self._update_hot_cache()

        return f"✅ Wiki写入: {category}/{filename}"

    def append_note(self, category: str, filename: str, 
                    content: str) -> str:
        """追加内容到已有笔记末尾"""
        filepath = self._resolve_path(category, filename)
        if not os.path.exists(filepath):
            return self.write_note(category, filename, content)

        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(f"\n\n---\n*追加于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n")
            f.write(content)
        return f"✅ 追加: {os.path.relpath(filepath, self.ga_brain)}"

    def append_log(self, message: str, log_type: str = "工作日志") -> str:
        """快速追加日志条目"""
        today = datetime.now().strftime('%Y-%m-%d')
        filename = f"{today}.md"
        filepath = self._resolve_path("日志", filename)

        entry = f"- **{datetime.now().strftime('%H:%M')}** {message}\n"

        if os.path.exists(filepath):
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(entry)
        else:
            content = f"# 📋 {today} {log_type}\n\n{entry}"
            self.write_note("日志", filename, content, 
                          tags=["日志", log_type], overwrite=True)

        return f"✅ 日志: {entry.strip()}"

    def log_decision(self, decision: str, reason: str, 
                     context: str = "") -> str:
        """记录决策日志"""
        today = datetime.now().strftime('%Y-%m-%d')
        filename = f"{today}-决策.md"
        filepath = self._resolve_path("记忆/决策日志", filename)

        entry = f"## 决策: {decision}\n"
        entry += f"- **原因**: {reason}\n"
        if context:
            entry += f"- **上下文**: {context}\n"
        entry += f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        if os.path.exists(filepath):
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(entry)
        else:
            self.write_note("记忆/决策日志", filename, entry,
                          tags=["决策日志"], overwrite=True)
        return f"✅ 决策记录: {decision[:30]}..."

    # ============================================================
    #  P1: 丰富化写入 (GA → OB 展开叙事+自动双链)
    # ============================================================

    def enrich_and_write(self, page_title: str, expanded_content: str,
                         category: str = None,
                         tags: list = None) -> str:
        """丰富化写入：将GA压缩知识展开为Obsidian详尽页面
        - 自动添加[[双链]]
        - 自动追踪ga_sync_ver
        - 如有category映射，写入Wiki；否则写入GA-Brain
        """
        # 检查是否已有Wiki页面
        if category is None:
            # 尝试从L2映射表找
            for section, (cat, title) in L2_SECTION_MAP.items():
                if title == page_title:
                    category = cat
                    break
        
        if category:
            # 写入Wiki区域
            result = self.write_to_wiki(
                category, page_title, expanded_content,
                tags=tags or [], overwrite=True)
        else:
            # 写入GA-Brain区域
            result = self.write_note(
                "知识库", page_title, expanded_content,
                tags=tags or [], overwrite=True)
        
        return f"✅ 丰富化写入: {page_title} → {result}"

    def sync_delta(self, since_hours: int = 24) -> dict:
        """增量同步：只同步GA记忆中变更的部分
        返回: {synced: [页面列表], skipped: [跳过列表], errors: [错误列表]}
        """
        result = {"synced": [], "skipped": [], "errors": []}
        cutoff = datetime.now().timestamp() - since_hours * 3600

        # 扫描GA memory中最近修改的文件
        for fn in os.listdir(self.ga_memory):
            if not (fn.endswith('.md') or fn.endswith('.py')):
                continue
            if fn.startswith('global_mem') or fn.startswith('file_access'):
                continue
            
            fp = os.path.join(self.ga_memory, fn)
            mtime = os.path.getmtime(fp)
            
            if mtime < cutoff:
                result["skipped"].append(fn)
                continue
            
            # 检查OB侧是否需要更新
            base_name = fn.replace('.md', '').replace('.py', '')
            
            # 检查Wiki区域是否有对应页面
            wiki_updated = False
            for section, (cat, title) in L2_SECTION_MAP.items():
                if base_name.lower().startswith(section.lower()[:4]):
                    ob_page = self.read_page(cat, title, base="wiki")
                    if not ob_page["exists"]:
                        r = self.sync_sop(fn)
                        result["synced"].append(f"{fn} → {r}")
                        wiki_updated = True
                        break
                    # 检查ga_sync_ver
                    ob_ver = ob_page["frontmatter"].get("ga_sync_ver", "")
                    ga_ver = self._get_sync_ver()
                    if ob_ver != ga_ver:
                        r = self.sync_sop(fn)
                        result["synced"].append(f"{fn} (版本更新) → {r}")
                        wiki_updated = True
                        break
            
            if not wiki_updated:
                # 同步到GA-Brain
                r = self.sync_sop(fn)
                result["synced"].append(f"{fn} → GA-Brain")

        return result

    def sync_sop(self, sop_filename: str) -> str:
        """从GA memory同步SOP到Obsidian"""
        src = os.path.join(self.ga_memory, sop_filename)
        if not os.path.exists(src):
            return f"❌ 文件不存在: {src}"

        with open(src, 'r', encoding='utf-8') as f:
            content = f.read()

        # 自动分类
        category = "知识库/系统运维"
        base_name = sop_filename.replace('.md', '').replace('.py', '')
        for prefix, cat in SOP_CATEGORY_MAP.items():
            if base_name.lower().startswith(prefix.lower()):
                category = f"知识库/{cat}"
                break

        return self.write_note(category, sop_filename, content,
                             tags=["SOP", "auto-sync"], overwrite=True)

    def sync_all_sops(self) -> list:
        """批量同步所有SOP"""
        results = []
        for f in os.listdir(self.ga_memory):
            if f.endswith('.md') or f.endswith('.py'):
                if f.startswith('global_mem') or f.startswith('file_access'):
                    continue
                r = self.sync_sop(f)
                results.append(r)
        return results

    # ============================================================
    #  P2: 质量保证与变更感知
    # ============================================================

    # 模板占位符与示例链接过滤规则
    # 这些双链来自模板示例/书写规范，不应判为断链
    _TEMPLATE_PLACEHOLDERS = {
        "_index",  # 首页索引占位
    }
    
    # 模板页/规范页(这些页面中的双链是示例，整体跳过验证)
    _SKIP_VALIDATE_PAGES = {
        "元数据/书写规范.md",
        "元数据/关联与链接规范.md",
    }
    
    # 示例链接的模式匹配(正则) — 匹配书写规范中的占位符
    _TEMPLATE_LINK_PATTERNS = [
        r'^来源\d*$',           # 来源1, 来源2, 来源
        r'^相关来源\d*$',       # 相关来源1, 相关来源2
        r'^概念\d+$',           # 概念1, 概念2
        r'^实体\d+$',           # 实体1, 实体2
        r'^页面\d+$',           # 页面1, 页面2
        r'^方案[AB]$',          # 方案A, 方案B
        r'^概念[ABC]$',         # 概念A, 概念B, 概念C
        r'^页面名称',           # 页面名称, 页面的章节标题
        r'^ADR-\d+$',          # ADR-001, ADR-002 (架构决策记录占位)
        r'^图片名称\.\w+$',    # 图片名称.png
        r'^相关人物/组织$',     # 模板占位
        r'^竞品/替代品$',       # 模板占位
        r'^互补产品$',          # 模板占位
        r'^密钥与配置$',        # 安全占位(不应创建)
        r'^\w+\.py$',          # 代码文件名引用(ga.py等)
        r'^\w+\.md$',          # 日志文件名引用(daily.md等)
        r'^来源-',              # 来源-GA4完全指南 等
        r'^案例-',              # 案例-Airbnb早期增长 等(种子未创建)
        r'^模块-',              # 模块-用户认证 等(种子未创建)
        r'^项目-',              # 项目-独立站增长 等(种子未创建)
        r'^目标-',              # 目标-提升转化率 等(种子未创建)
        r'^论文-',              # 论文-增长理论研究 等(种子未创建)
    ]

    def _is_template_link(self, link: str) -> bool:
        """判断双链是否为模板占位符/示例链接"""
        if link in self._TEMPLATE_PLACEHOLDERS:
            return True
        # 截取#号前的页面名部分
        page_name = link.split('#')[0]
        # 同时检查路径最后一段(如 goals/_index → _index)
        link_base = page_name.rsplit('/', 1)[-1]
        if link_base in self._TEMPLATE_PLACEHOLDERS:
            return True
        import re
        for pattern in self._TEMPLATE_LINK_PATTERNS:
            if re.match(pattern, page_name) or re.match(pattern, link_base):
                return True
        return False

    def validate_links(self, scope: str = "wiki") -> list:
        """检查所有[[双链]]是否有效，返回无效链接列表
        修复: ①路径式双链[[dir/file]]按文件名部分匹配
              ②过滤模板占位符白名单
        返回: [{source_page, broken_link}]
        """
        broken = []
        search_root = self.wiki_path if scope == "wiki" else self.vault_path
        
        # 收集所有存在的页面(双索引: 文件名 + 相对路径)
        all_page_names = set()   # 如 "核心引擎"
        all_page_paths = set()   # 如 "代码库/模块/核心引擎"
        for dirpath, _, filenames in os.walk(search_root):
            if ".raw" in dirpath:
                continue
            for fn in filenames:
                if fn.endswith('.md'):
                    name = fn.replace('.md', '')
                    all_page_names.add(name)
                    rel = os.path.relpath(
                        os.path.join(dirpath, fn), search_root)
                    # 统一使用/分隔符(与Obsidian双链格式一致)
                    rel_key = rel.replace('.md', '').replace('\\', '/')
                    all_page_paths.add(rel_key)

        # 扫描所有双链
        for dirpath, _, filenames in os.walk(search_root):
            if ".raw" in dirpath:
                continue
            for fn in filenames:
                if not fn.endswith('.md'):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, 'r', encoding='utf-8') as f:
                        content = f.read()
                except (UnicodeDecodeError, PermissionError):
                    continue
                
                links = self._extract_wikilinks(content)
                rel = os.path.relpath(fp, search_root).replace('\\', '/')
                page_key = rel
                
                # 跳过模板/规范页面(整页跳过)
                if page_key in self._SKIP_VALIDATE_PAGES:
                    continue
                
                for link in links:
                    # 跳过外部链接
                    if link.startswith("http"):
                        continue
                    
                    # 跳过模板占位符/示例链接(正则匹配)
                    if self._is_template_link(link):
                        continue
                    
                    # 匹配逻辑: 1.精确路径匹配 2.文件名匹配 3.路径式匹配
                    link_base = link.rsplit('/', 1)[-1]  # [[goals/_index]] → _index
                    is_valid = (
                        link in all_page_names or       # [[核心引擎]]
                        link in all_page_paths or       # [[代码库/模块/核心引擎]]
                        link_base in all_page_names     # [[goals/_index]] → 匹配 _index
                    )
                    
                    if not is_valid:
                        broken.append({
                            "source_page": page_key,
                            "broken_link": link
                        })
        
        return broken

    def update_stale_flags(self) -> list:
        """检查并标记过时页面(GA源已变但OB未同步)
        返回: [{page, ga_ver, ob_ver}]
        """
        stale = []
        ga_ver = self._get_sync_ver()
        
        # 扫描所有包含ga_sync_ver的页面
        for dirpath, _, filenames in os.walk(self.wiki_path):
            if ".raw" in dirpath:
                continue
            for fn in filenames:
                if not fn.endswith('.md'):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, 'r', encoding='utf-8') as f:
                        content = f.read()
                except (UnicodeDecodeError, PermissionError):
                    continue
                
                fm = self._parse_frontmatter(content)
                ob_ver = fm.get("ga_sync_ver", "")
                if ob_ver and ob_ver != ga_ver:
                    stale.append({
                        "page": os.path.relpath(fp, self.wiki_path),
                        "ga_ver": ga_ver,
                        "ob_ver": ob_ver
                    })
        
        return stale

    def diff_against_ga(self, page_title: str) -> dict:
        """比对Obsidian页面与GA知识是否一致
        返回: {match, ob_exists, ob_ver, ga_ver}
        """
        ga_ver = self._get_sync_ver()
        
        # 尝试在Wiki中找该页面
        for dirpath, _, filenames in os.walk(self.wiki_path):
            for fn in filenames:
                if fn.replace('.md', '') == page_title:
                    fp = os.path.join(dirpath, fn)
                    with open(fp, 'r', encoding='utf-8') as f:
                        content = f.read()
                    fm = self._parse_frontmatter(content)
                    ob_ver = fm.get("ga_sync_ver", "")
                    return {
                        "ob_exists": True,
                        "match": ob_ver == ga_ver,
                        "ob_ver": ob_ver,
                        "ga_ver": ga_ver,
                        "path": os.path.relpath(fp, self.wiki_path)
                    }
        
        return {"ob_exists": False, "match": False, 
                "ga_ver": ga_ver, "ob_ver": ""}

    def get_recent_changes(self, hours: int = 24) -> list:
        """检测OB侧最近被修改的页面(可能被人手动编辑)
        返回: [{path, mtime, size}]
        """
        cutoff = datetime.now().timestamp() - hours * 3600
        changes = []
        
        for scope_path in [self.wiki_path, self.ga_brain]:
            if not os.path.exists(scope_path):
                continue
            for dirpath, _, filenames in os.walk(scope_path):
                if ".raw" in dirpath:
                    continue
                for fn in filenames:
                    if not fn.endswith('.md'):
                        continue
                    fp = os.path.join(dirpath, fn)
                    mtime = os.path.getmtime(fp)
                    if mtime >= cutoff:
                        changes.append({
                            "path": os.path.relpath(fp, scope_path),
                            "scope": "Wiki" if scope_path == self.wiki_path else "GA-Brain",
                            "mtime": datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M'),
                            "size": os.path.getsize(fp)
                        })
        
        changes.sort(key=lambda x: x["mtime"], reverse=True)
        return changes

    # ============================================================
    #  统计与维护
    # ============================================================

    def get_stats(self) -> dict:
        """获取统计信息(v2增强: Wiki+GA-Brain双区域)"""
        stats = {
            "ga_brain": {"total_files": 0, "categories": {}},
            "wiki": {"total_files": 0, "categories": {}},
            "last_sync": datetime.now().strftime('%Y-%m-%d %H:%M'),
            "ga_sync_ver": self._get_sync_ver()
        }
        
        for scope_name, scope_path in [("ga_brain", self.ga_brain), 
                                         ("wiki", self.wiki_path)]:
            if not os.path.exists(scope_path):
                continue
            for dirpath, _, filenames in os.walk(scope_path):
                if ".raw" in dirpath:
                    continue
                mds = [f for f in filenames if f.endswith('.md')]
                if mds:
                    rel_dir = os.path.relpath(dirpath, scope_path)
                    stats[scope_name]["categories"][rel_dir] = len(mds)
                    stats[scope_name]["total_files"] += len(mds)
        
        return stats

    # ============================================================
    #  内部维护方法
    # ============================================================

    def _update_sub_index(self, category: str):
        """更新Wiki子索引文件"""
        cat_dir = os.path.join(self.wiki_path, category)
        if not os.path.exists(cat_dir):
            return
        
        # 找到子索引文件
        for fn in os.listdir(cat_dir):
            if "索引" in fn and fn.endswith('.md'):
                index_fp = os.path.join(cat_dir, fn)
                # 收集该目录下所有页面
                pages = []
                for sub_fn in sorted(os.listdir(cat_dir)):
                    if sub_fn.endswith('.md') and sub_fn != fn:
                        title = sub_fn.replace('.md', '')
                        pages.append(f"- [[{title}]]")
                
                # 读取现有内容，只替换页面列表部分
                try:
                    with open(index_fp, 'r', encoding='utf-8') as f:
                        content = f.read()
                    # 简单追加新页面（如果不在索引中）
                    for page_line in pages:
                        if page_line not in content:
                            # 在最后一个列表项后追加
                            content += f"\n{page_line}"
                    with open(index_fp, 'w', encoding='utf-8') as f:
                        f.write(content)
                except Exception:
                    pass

    def _append_sync_log(self, action: str):
        """追加同步操作到日志"""
        self.append_log(f"[桥接同步] {action}")

    def _update_hot_cache(self):
        """更新热缓存摘要"""
        cache_fp = os.path.join(self.wiki_path, "热缓存.md")
        if not os.path.exists(cache_fp):
            return
        
        # 读取最近变更
        recent = self.get_recent_changes(hours=72)
        recent_lines = []
        for r in recent[:10]:
            recent_lines.append(
                f"- {r['scope']}/{r['path']} ({r['mtime']})")
        
        # 构建热缓存内容
        content = "---\ntype: meta\ntitle: \"热缓存\"\ncreated: 2026-05-20\n"
        content += f"updated: {datetime.now().strftime('%Y-%m-%d')}\n"
        content += "tags: [meta, 热缓存, 运行时]\n---\n\n"
        content += "# 热缓存\n\n"
        content += "> 自动维护 - 最近活跃页面速览\n\n"
        content += "## 最近变更(72h)\n"
        content += "\n".join(recent_lines) + "\n"
        content += f"\n*最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n"
        
        with open(cache_fp, 'w', encoding='utf-8') as f:
            f.write(content)


# 快速测试
if __name__ == "__main__":
    ob = ObsidianBridge()
    
    # P0: 读取能力测试
    print("=== P0: 读取能力 ===")
    page = ob.read_page("代码库/模块", "核心引擎.md", base="wiki")
    print(f"  read_page: exists={page['exists']}, size={page.get('size', 0)}B")
    
    results = ob.search_vault("PPT", scope="wiki")
    print(f"  search_vault('PPT'): {len(results)}条结果")
    
    links = ob.get_backlinks("核心引擎", scope="wiki")
    print(f"  get_backlinks('核心引擎'): {len(links)}条")
    
    exists = ob.page_exists("代码库/模块", "核心引擎.md", base="wiki")
    print(f"  page_exists: {exists}")
    
    # P1: 丰富化写入测试
    print("\n=== P1: 丰富化写入 ===")
    sync = ob.sync_delta(since_hours=48)
    print(f"  sync_delta(48h): synced={len(sync['synced'])}, skipped={len(sync['skipped'])}")
    
    # P2: 质量保证测试
    print("\n=== P2: 质量保证 ===")
    broken = ob.validate_links(scope="wiki")
    print(f"  validate_links: {len(broken)}个断链")
    if broken:
        for b in broken[:5]:
            print(f"    ⚠️ {b['source_page']} → [[{b['broken_link']}]]")
    
    stale = ob.update_stale_flags()
    print(f"  update_stale_flags: {len(stale)}个过时页面")
    
    changes = ob.get_recent_changes(hours=72)
    print(f"  get_recent_changes(72h): {len(changes)}个变更")
    
    # 统计
    print("\n=== 统计 ===")
    stats = ob.get_stats()
    print(f"  GA-Brain: {stats['ga_brain']['total_files']}个文件")
    print(f"  Wiki: {stats['wiki']['total_files']}个文件")
    print(f"  GA同步版本: {stats['ga_sync_ver']}")
