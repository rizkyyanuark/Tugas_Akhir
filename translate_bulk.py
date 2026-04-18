"""
Bulk Mandarin → English translation script for the Yunesa project.
This script applies a dictionary-based translation to all Python and Markdown files
in the backend directory. It handles docstrings, comments, error messages, logger messages,
and description fields.
"""
import os
import re

# ====================================================================
# TRANSLATION DICTIONARY
# Common Chinese phrases → English translations
# Organized by category for maintainability
# ====================================================================

TRANSLATIONS = {
    # === Knowledge Base ===
    "知识库": "knowledge base",
    "知识文件": "knowledge file",
    "知识管理": "knowledge management",
    "知识": "knowledge",
    
    # === Database / Storage ===
    "数据库": "database",
    "数据表": "data table",
    "数据源": "data source",
    "数据": "data",
    "存储": "storage",
    "表": "table",
    
    # === User / Auth ===
    "用户": "user",
    "部门": "department",
    "密码": "password",
    "角色": "role",
    "权限": "permission",
    "认证": "authentication",
    "授权": "authorization",
    "登录": "login",
    "注册": "register",
    "头像": "avatar",
    "手机号": "phone number",
    "显示名称": "display name",
    "锁定": "lock",
    "超级管理员": "super admin",
    "管理员": "admin",
    
    # === Operations ===
    "创建": "create",
    "删除": "delete",
    "更新": "update",
    "修改": "modify",
    "查询": "query",
    "获取": "get",
    "设置": "set",
    "保存": "save",
    "上传": "upload",
    "下载": "download",
    "导入": "import",
    "导出": "export",
    "添加": "add",
    "移除": "remove",
    "检查": "check",
    "验证": "verify",
    "解析": "parse",
    "处理": "process",
    "执行": "execute",
    "启动": "start",
    "停止": "stop",
    "关闭": "close",
    "重置": "reset",
    "加载": "load",
    "初始化": "initialize",
    "配置": "configure",
    "计算": "calculate",
    "统计": "statistics",
    "搜索": "search",
    "切换": "switch",
    "合并": "merge",
    "分割": "split",
    "构建": "build",
    "生成": "generate",
    "转换": "convert",
    "提取": "extract",
    "清理": "clean up",
    "刷新": "refresh",
    "连接": "connect",
    "断开": "disconnect",
    "注入": "inject",
    "注销": "logout",
    "返回": "return",
    "发送": "send",
    "接收": "receive",
    "读取": "read",
    "写入": "write",
    "编辑": "edit",
    "复制": "copy",
    "移动": "move",
    "重命名": "rename",
    "排序": "sort",
    "过滤": "filter",
    "分页": "paginate",
    "绑定": "bind",
    "注册到": "register to",
    
    # === Status / State ===
    "成功": "successful",
    "失败": "failed",
    "错误": "error",
    "异常": "exception",
    "警告": "warning",
    "完成": "completed",
    "进行中": "in progress",
    "等待": "waiting",
    "已取消": "cancelled",
    "已存在": "already exists",
    "不存在": "does not exist",
    "已过期": "expired",
    "已锁定": "locked",
    "未找到": "not found",
    "不支持": "not supported",
    "不允许": "not allowed",
    "不合法": "invalid",
    "不可用": "unavailable",
    "无效": "invalid",
    "有效": "valid",
    "禁用": "disabled",
    "启用": "enabled",
    "开启": "enabled",
    "关闭": "disabled",
    "已删除": "deleted",
    "未删除": "not deleted",
    "软删除": "soft delete",
    "是否": "whether",
    "正在": "currently",
    "准备": "preparing",
    
    # === Models / AI ===
    "模型": "model",
    "智能体": "agent",
    "对话": "conversation",
    "消息": "message",
    "会话": "session",
    "提示": "prompt",
    "回复": "reply",
    "回答": "answer",
    "问题": "question",
    "技能": "skill",
    "工具": "tool",
    "插件": "plugin",
    "扩展": "extension",
    "嵌入": "embedding",
    "向量": "vector",
    "索引": "index",
    "检索": "retrieval",
    "重排序": "reranker",
    "推理": "inference",
    "训练": "training",
    "微调": "fine-tuning",
    "评估": "evaluation",
    "基准": "benchmark",
    "报告": "report",
    "深度报告": "deep report",
    "深度代理": "deep agent",
    "子代理": "subagent",
    "预设": "preset",
    "分块": "chunking",
    "切片": "slicing",
    "令牌": "token",
    
    # === Graph / KG ===
    "图谱": "graph",
    "图数据库": "graph database",
    "知识图谱": "knowledge graph",
    "实体": "entity",
    "关系": "relationship",
    "三元组": "triple",
    "节点": "node",
    "边": "edge",
    "属性": "property",
    "标签": "label",
    "适配器": "adapter",
    
    # === Document / File ===
    "文档": "document",
    "文件": "file",
    "目录": "directory",
    "路径": "path",
    "文件夹": "folder",
    "扩展名": "extension",
    "格式": "format",
    "内容": "content",
    "正文": "body",
    "标题": "title",
    "描述": "description",
    "备注": "remark",
    "名称": "name",
    "类型": "type",
    "大小": "size",
    "状态": "status",
    "版本": "version",
    "哈希": "hash",
    "页面": "page",
    "页码": "page number",
    "章节": "chapter",
    "段落": "paragraph",
    "行": "row",
    "列": "column",
    "字符": "character",
    
    # === System / Config ===
    "系统": "system",
    "服务": "service",
    "服务器": "server",
    "客户端": "client",
    "接口": "interface",
    "参数": "parameter",
    "选项": "option",
    "默认": "default",
    "必填": "required",
    "可选": "optional",
    "唯一": "unique",
    "关联": "associated",
    "依赖": "dependency",
    "环境": "environment",
    "日志": "log",
    "缓存": "cache",
    "超时": "timeout",
    "重试": "retry",
    "限制": "limit",
    "阈值": "threshold",
    "频率": "frequency",
    "优先级": "priority",
    "备份": "backup",
    "恢复": "restore",
    "迁移": "migration",
    "部署": "deploy",
    "发布": "release",
    "调试": "debug",
    "测试": "test",
    "监控": "monitor",
    "通知": "notification",
    "邮件": "email",
    "短信": "SMS",
    "推送": "push",
    "回调": "callback",
    "钩子": "hook",
    "中间件": "middleware",
    "过滤器": "filter",
    "拦截器": "interceptor",
    "守卫": "guard",
    "路由": "route",
    "控制器": "controller",
    "仓库": "repository",
    "管理器": "manager",
    "处理器": "handler",
    "工厂": "factory",
    "注册表": "registry",
    "调度器": "scheduler",
    "执行器": "executor",
    "加载器": "loader",
    "解析器": "parser",
    "转换器": "converter",
    "编码": "encoding",
    "解码": "decoding",
    "序列化": "serialization",
    "反序列化": "deserialization",
    "压缩": "compression",
    "解压": "decompression",
    
    # === Business Logic ===
    "操作日志": "operation log",
    "操作": "operation",
    "反馈": "feedback",
    "收藏": "favorite",
    "分享": "share",
    "点赞": "like",
    "评论": "comment",
    "审核": "review",
    "审批": "approval",
    "流程": "workflow",
    "任务": "task",
    "计划": "plan",
    "进度": "progress",
    "总数": "total",
    "数量": "count",
    "次数": "times",
    "次": "times",
    "个": "",
    "条": "",
    "项": "items",
    
    # === Common phrases ===
    "请求": "request",
    "响应": "response",
    "输入": "input",
    "输出": "output",
    "结果": "result",
    "详情": "details",
    "列表": "list",
    "分组": "group",
    "管理": "management",
    "概览": "overview",
    "摘要": "summary",
    "全部": "all",
    "部分": "partial",
    "开始": "start",
    "结束": "end",
    "时间": "time",
    "日期": "date",
    "今天": "today",
    "昨天": "yesterday",
    "最近": "recent",
    "相关": "related",
    "关联关系": "relationships",
    "唯一标识": "unique identifier",
    "基础配置": "basic configuration",
    "高级配置": "advanced configuration",
    
    # === Specific to codebase ===
    "PostgreSQL 知识库模型": "PostgreSQL Knowledge Base Models",
    "KnowledgeBase、KnowledgeFile、评估相关表": "KnowledgeBase, KnowledgeFile, and Evaluation Tables",
    "PostgreSQL 业务数据模型": "PostgreSQL Business Data Models",
    "用户、部门、对话等相关表": "User, Department, Conversation, and Related Tables",
    "评估基准模型": "Evaluation Benchmark Model",
    "评估结果模型": "Evaluation Result Model",
    "评估结果详情模型": "Evaluation Result Detail Model",
    "智能体配置": "Agent Configuration",
    "按部门共享，多份可切换": "Shared by department, multiple switchable",
    "Skill 元数据模型": "Skill Metadata Model",
    "内容存文件系统，索引存数据库": "Content stored in filesystem, index stored in database",
    "技能唯一标识（目录名）": "Skill unique identifier (directory name)",
    "技能名称（来自 SKILL.md frontmatter.name）": "Skill name (from SKILL.md frontmatter.name)",
    "技能描述（来自 SKILL.md frontmatter.description）": "Skill description (from SKILL.md frontmatter.description)",
    "依赖的内置工具名列表": "List of dependent built-in tool names",
    "依赖的 MCP 服务名列表": "List of dependent MCP service names",
    "依赖的其他 skill slug 列表": "List of dependent skill slugs",
    "技能目录路径（相对 save_dir）": "Skill directory path (relative to save_dir)",
    "技能版本（内置 skill 使用语义化版本）": "Skill version (built-in skills use semantic versioning)",
    "是否为内置 skill": "Whether it is a built-in skill",
    "技能目录内容哈希（内置 skill 安装时计算）": "Skill directory content hash (calculated during built-in skill installation)",
    "Conversation table - 对话表": "Conversation Table",
    "Message table - 消息表": "Message Table",
    "ToolCall table - 工具调用表": "ToolCall Table",
    "ConversationStats table - 对话统计表": "ConversationStats Table",
    "操作日志模型": "Operation Log Model",
    "Message feedback table - 消息反馈表": "Message Feedback Table",
    "MCP 服务器配置模型": "MCP Server Configuration Model",
    "检查用户是否处于登录锁定状态": "Check if user is in login lockout state",
    "获取剩余锁定时间（秒）": "Get remaining lockout time (seconds)",
    "增加登录失败计数，并在达到阈值后锁定登录": "Increment login failure count and lock login after reaching threshold",
    "重置登录失败相关字段": "Reset login failure related fields",
    "保存目录": "Save directory",
    "默认对话模型": "Default chat model",
    "是否开启重排序": "Enable reranker",
    "设置配置文件路径": "Set config file paths",
    "登录ID": "login ID",
    "登录失败次数": "login failure count",
    "最后一次登录失败时间": "last failed login time",
    "锁定到什么时候": "locked until",
    "是否已删除：0=否，1=是": "whether deleted: 0=no, 1=yes",
    "删除时间": "deletion time",
    "关联操作日志": "associated operation logs",
    "关联用户": "associated user",
    "关联部门": "associated department",
    "关联 API Keys": "associated API keys",
    "登录失败限制相关字段": "Login failure limit related fields",
    "目录的包初始化文件": "Package initialization file for directory",
    "不支持本地文件路径，只允许 MinIO URL。请先通过文件上传接口上传文件。": "Local file paths are not supported; only MinIO URLs are allowed. Please upload the file via the file upload endpoint first.",
    
    # === Upload Graph Service ===
    "Upload 类型图谱业务逻辑服务": "Upload-type graph business logic service",
    "专门处理用户上传文件、实体管理、向量索引等业务逻辑": "Handles user file uploads, entity management, vector indexing and other business logic",
    "时加载": "loaded during",
    "尝试加载已保存的图数据库信息": "Attempt to load saved graph database info",
    "创建新的图数据库配置": "Creating new graph database configuration",
    "获取数据库驱动": "Get database driver",
    "获取连接状态": "Get connection status",
    "启动连接": "Start connection",
    "关闭数据库连接": "Close database connection",
    "检查图数据库是否正在运行": "Check if graph database is running",
    "创建新的数据库，如果已存在则返回已有数据库的名称": "Create new database; if it already exists, return existing database name",
    "已存在数据库": "Database already exists",
    "返回所有已有数据库名称": "Return all existing database names",
    "数据库 '": "Database '",
    "' 创建成功.": "' created successfully.",
    "返回创建的数据库名称": "Return created database name",
    "切换到指定数据库": "Switch to specified database",
    "传入的数据库名称 '": "Provided database name '",
    "' 与当前实例的数据库名称 '": "' does not match current instance database name '",
    "' 不一致": "'",
    "从JSONL文件添加实体三元组到Neo4j": "Add entity triples from JSONL file to Neo4j",
    "检测到 URL，正在从 MinIO 下载文件": "URL detected, downloading file from MinIO",
    "使用知识库的方式：直接解析 URL 并使用内部 endpoint 下载（避免 HOST_IP 配置问题）": "Using KB approach: parse URL directly and download via internal endpoint (avoid HOST_IP config issues)",
    "直接下载文件内容": "Download file content directly",
    "成功从 MinIO 下载文件": "Successfully downloaded file from MinIO",
    "创建临时文件": "Create temporary file",
    "清理临时文件": "Clean up temporary file",
    "本地文件路径 - 拒绝不安全的本地路径": "Local file path - reject unsafe local paths",
    "处理文件失败": "Failed to process file",
    "更新并保存图数据库信息": "Update and save graph database info",
    "添加实体三元组": "Add entity triples",
    "检查索引是否存在": "Check if index exists",
    "解析节点数据，返回 (name, props)": "Parse node data, return (name, props)",
    "解析关系数据，返回 (type, props)": "Parse relationship data, return (type, props)",
    "添加一个三元组": "Add a single triple",
    "创建向量索引": "Create vector index",
    "NOTE 这里是否是会重复构建索引？": "NOTE: Does this rebuild the index repeatedly?",
    "获取没有embedding的节点列表": "Get list of nodes without embeddings",
    "构建参数字典，将列表转换为": "Build parameter dict, converting list to",
    "构建查询参数列表": "Build query parameter list",
    "执行查询": "Execute query",
    "批量设置实体的嵌入向量": "Batch set entity embedding vectors",
    "检查是否允许更新模型": "Check if model update is allowed",
    "判断模型名称是否匹配": "Check if model name matches",
    "允许 self.embed_model_name 与 config.embed_model 不同（用户自定义选择的情况）": "Allow self.embed_model_name to differ from config.embed_model (user custom selection case)",
    "但必须在支持的模型列表中": "But it must be in the supported model list",
    "如果是 URL": "If it is a URL",
    
    # === Graphs adapters ===
    "图谱适配器抽象基类": "Graph adapter abstract base class",
    "图谱适配器工厂": "Graph adapter factory",
    
    # === Common log/error patterns ===
    "不能为空": "cannot be empty",
    "不能重复": "cannot be duplicated",
    "不能超过": "cannot exceed",
    "必须是": "must be",
    "必须包含": "must contain",
    "格式不正确": "format is incorrect",
    "已被使用": "is already in use",
    "已被禁用": "has been disabled",
    "无权访问": "no access permission",
    "您没有": "you do not have",
    "无法连接": "unable to connect",
    "连接失败": "connection failed",
    "超时了": "timed out",
    "暂不支持": "not yet supported",
}


def translate_line(line: str) -> str:
    """Translate a single line using the dictionary, longest match first."""
    # Sort keys by length (longest first) to avoid partial replacements
    sorted_keys = sorted(TRANSLATIONS.keys(), key=len, reverse=True)
    
    result = line
    for cn in sorted_keys:
        if cn in result:
            result = result.replace(cn, TRANSLATIONS[cn])
    
    return result


def translate_file(filepath: str) -> tuple[bool, int]:
    """Translate a file in-place. Returns (changed, num_lines_changed)."""
    cn_pattern = re.compile(r'[\u4e00-\u9fff]')
    
    with open(filepath, 'r', encoding='utf-8') as f:
        original_lines = f.readlines()
    
    new_lines = []
    changes = 0
    
    for line in original_lines:
        if cn_pattern.search(line):
            new_line = translate_line(line)
            if new_line != line:
                changes += 1
            new_lines.append(new_line)
        else:
            new_lines.append(line)
    
    if changes > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
    
    return changes > 0, changes


def main():
    base = 'c:/Users/rizky_11yf1be/Desktop/Tugas_Akhir'
    
    dirs_to_scan = [
        'backend/server/routers',
        'backend/package/yunesa',
    ]
    
    total_files = 0
    total_changes = 0
    
    for d in dirs_to_scan:
        full_dir = os.path.join(base, d)
        if not os.path.exists(full_dir):
            continue
        for root, dirs, files in os.walk(full_dir):
            for f in sorted(files):
                if not (f.endswith('.py') or f.endswith('.md')):
                    continue
                fpath = os.path.join(root, f)
                try:
                    changed, num = translate_file(fpath)
                    if changed:
                        rel = os.path.relpath(fpath, base)
                        print(f"  Translated {rel}: {num} lines")
                        total_files += 1
                        total_changes += num
                except Exception as e:
                    print(f"  ERROR: {os.path.relpath(fpath, base)}: {e}")
    
    print(f"\nDone! Translated {total_changes} lines across {total_files} files.")


if __name__ == '__main__':
    main()
