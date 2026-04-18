"""PostgreSQL Business Data Models - User, Department, Conversation, and Related Tables"""

from datetime import timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from yunesa.utils.datetime_utils import format_utc_datetime, utc_now_naive

Base = declarative_base()

MAX_LOGIN_FAILED_ATTEMPTS = 5
LOGIN_LOCK_DURATION_SECONDS = 300


class Department(Base):
    """departmentmodel"""

    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)

    # relationships
    users = relationship("User", back_populates="department",
                         cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": format_utc_datetime(self.created_at),
        }


class User(Base):
    """usermodel"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True,
                      index=True)  # display name
    user_id = Column(String, nullable=False,
                     unique=True, index=True)  # login ID
    phone_number = Column(String, nullable=True,
                          unique=True, index=True)  # phone number
    avatar = Column(String, nullable=True)  # avatarURL
    password_hash = Column(String, nullable=False)
    # role: superadmin, admin, user
    role = Column(String, nullable=False, default="user")
    department_id = Column(Integer, ForeignKey(
        "departments.id"), nullable=True)  # departmentID
    created_at = Column(DateTime, default=utc_now_naive)
    last_login = Column(DateTime, nullable=True)

    # Login failure limit related fields
    login_failed_count = Column(
        Integer, nullable=False, default=0)  # login failure count
    # last failed login time
    last_failed_login = Column(DateTime, nullable=True)
    login_locked_until = Column(DateTime, nullable=True)  # locked until

    # Soft delete related fields
    is_deleted = Column(Integer, nullable=False, default=0,
                        index=True)  # whether deleted: 0=no, 1=yes
    deleted_at = Column(DateTime, nullable=True)  # deletion time

    # associated operation logs
    operation_logs = relationship(
        "OperationLog", back_populates="user", cascade="all, delete-orphan")

    # associated department
    department = relationship("Department", back_populates="users")

    # associated API keys
    api_keys = relationship(
        "APIKey", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self, include_password: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "username": self.username,
            "user_id": self.user_id,
            "phone_number": self.phone_number,
            "avatar": self.avatar,
            "role": self.role,
            "department_id": self.department_id,
            "created_at": format_utc_datetime(self.created_at),
            "last_login": format_utc_datetime(self.last_login),
            "login_failed_count": self.login_failed_count,
            "last_failed_login": format_utc_datetime(self.last_failed_login),
            "login_locked_until": format_utc_datetime(self.login_locked_until),
            "is_deleted": self.is_deleted,
            "deleted_at": format_utc_datetime(self.deleted_at),
        }
        if include_password:
            result["password_hash"] = self.password_hash
        return result

    def is_login_locked(self) -> bool:
        """Check if user is in login lockout state"""
        if self.login_locked_until is None:
            return False
        return utc_now_naive() < self.login_locked_until

    def get_remaining_lock_time(self) -> int:
        """Get remaining lockout time (seconds)"""
        if self.login_locked_until is None:
            return 0
        remaining = int((self.login_locked_until -
                        utc_now_naive()).total_seconds())
        return max(0, remaining)

    def increment_failed_login(self):
        """Increment login failure count and lock login after reaching threshold"""
        self.login_failed_count += 1
        self.last_failed_login = utc_now_naive()
        if self.login_failed_count >= MAX_LOGIN_FAILED_ATTEMPTS:
            self.login_locked_until = self.last_failed_login + \
                timedelta(seconds=LOGIN_LOCK_DURATION_SECONDS)

    def reset_failed_login(self):
        """Reset login failure related fields"""
        self.login_failed_count = 0
        self.last_failed_login = None
        self.login_locked_until = None


class AgentConfig(Base):
    """Agent Configuration（Shared by department, multiple switchable）"""

    __tablename__ = "agent_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    department_id = Column(Integer, ForeignKey(
        "departments.id"), nullable=False, index=True)
    agent_id = Column(String(64), nullable=False, index=True)

    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    icon = Column(String(255), nullable=True)

    pics = Column(JSON, nullable=False, default=list)
    examples = Column(JSON, nullable=False, default=list)
    config_json = Column(JSON, nullable=False, default=dict)

    is_default = Column(Boolean, nullable=False, default=False, index=True)

    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive,
                        onupdate=utc_now_naive)

    __table_args__ = (
        UniqueConstraint("department_id", "agent_id", "name",
                         name="uq_agent_configs_department_agent_name"),
        Index(
            "uq_agent_configs_department_agent_default",
            "department_id",
            "agent_id",
            unique=True,
            postgresql_where=is_default.is_(True),
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "department_id": self.department_id,
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "pics": self.pics or [],
            "examples": self.examples or [],
            "config_json": self.config_json or {},
            "is_default": bool(self.is_default),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class Skill(Base):
    """Skill Metadata Model（Content stored in filesystem, index stored in database）"""

    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(128), nullable=False, unique=True, index=True,
                  comment="Skill unique identifier (directory name)")
    name = Column(String(128), nullable=False,
                  comment="Skill name (from SKILL.md frontmatter.name)")
    description = Column(
        Text, nullable=False, comment="Skill description (from SKILL.md frontmatter.description)")
    tool_dependencies = Column(
        JSON, nullable=False, default=list, comment="List of dependent built-in tool names")
    mcp_dependencies = Column(
        JSON, nullable=False, default=list, comment="List of dependent MCP service names")
    skill_dependencies = Column(
        JSON, nullable=False, default=list, comment="List of dependent skill slugs")
    dir_path = Column(String(512), nullable=False,
                      comment="Skill directory path (relative to save_dir)")
    version = Column(String(64), nullable=True,
                     comment="Skill version (built-in skills use semantic versioning)")
    is_builtin = Column(Boolean, nullable=False, default=False,
                        comment="Whether it is a built-in skill")
    content_hash = Column(String(128), nullable=True,
                          comment="Skill directory content hash (calculated during built-in skill installation)")
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive,
                        onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "tool_dependencies": self.tool_dependencies or [],
            "mcp_dependencies": self.mcp_dependencies or [],
            "skill_dependencies": self.skill_dependencies or [],
            "dir_path": self.dir_path,
            "version": self.version,
            "is_builtin": self.is_builtin,
            "content_hash": self.content_hash,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class Conversation(Base):
    """Conversation Table"""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True,
                autoincrement=True, comment="Primary key")
    thread_id = Column(String(64), unique=True, index=True,
                       nullable=False, comment="Thread ID (UUID)")
    user_id = Column(String(64), index=True, nullable=False, comment="User ID")
    agent_id = Column(String(64), index=True,
                      nullable=False, comment="Agent ID")
    title = Column(String(255), nullable=True, comment="Conversation title")
    status = Column(String(20), default="active",
                    comment="Status: active/archived/deleted")
    is_pinned = Column(Boolean, default=False, nullable=False,
                       index=True, comment="Is pinned to top")
    created_at = Column(DateTime, default=utc_now_naive,
                        comment="Creation time")
    updated_at = Column(DateTime, default=utc_now_naive,
                        onupdate=utc_now_naive, comment="Update time")
    extra_metadata = Column(JSON, nullable=True, comment="Additional metadata")

    # Relationships
    messages = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan")
    stats = relationship(
        "ConversationStats", back_populates="conversation", uselist=False, cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        metadata = self.extra_metadata or {}
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "title": self.title,
            "status": self.status,
            "is_pinned": bool(self.is_pinned),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
            "metadata": metadata,
        }


class Message(Base):
    """Message Table"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True,
                autoincrement=True, comment="Primary key")
    conversation_id = Column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True, comment="Conversation ID"
    )
    role = Column(String(20), nullable=False,
                  comment="Message role: user/assistant/system/tool")
    content = Column(Text, nullable=False, comment="Message content")
    message_type = Column(String(30), default="text",
                          comment="Message type: text/tool_call/tool_result")
    created_at = Column(DateTime, default=utc_now_naive,
                        comment="Creation time")
    token_count = Column(Integer, nullable=True,
                         comment="Token count (optional)")
    extra_metadata = Column(
        JSON, nullable=True, comment="Additional metadata (complete message dump)")
    image_content = Column(
        Text, nullable=True, comment="Base64 encoded image content for multimodal messages")

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    tool_calls = relationship(
        "ToolCall", back_populates="message", cascade="all, delete-orphan")
    feedbacks = relationship(
        "MessageFeedback", back_populates="message", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "message_type": self.message_type,
            "created_at": format_utc_datetime(self.created_at),
            "token_count": self.token_count,
            "metadata": self.extra_metadata or {},
            "image_content": self.image_content,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls] if self.tool_calls else [],
        }

    def to_simple_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
        }


class ToolCall(Base):
    """ToolCall Table"""

    __tablename__ = "tool_calls"

    id = Column(Integer, primary_key=True,
                autoincrement=True, comment="Primary key")
    message_id = Column(Integer, ForeignKey("messages.id"),
                        nullable=False, index=True, comment="Message ID")
    langgraph_tool_call_id = Column(
        String(100), nullable=True, index=True, comment="LangGraph tool_call_id")
    tool_name = Column(String(100), nullable=False, comment="Tool name")
    tool_input = Column(JSON, nullable=True, comment="Tool input parameters")
    tool_output = Column(Text, nullable=True, comment="Tool execution result")
    status = Column(String(20), default="pending",
                    comment="Status: pending/success/error")
    error_message = Column(Text, nullable=True,
                           comment="Error message if failed")
    created_at = Column(DateTime, default=utc_now_naive,
                        comment="Creation time")

    # Relationships
    message = relationship("Message", back_populates="tool_calls")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "langgraph_tool_call_id": self.langgraph_tool_call_id,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input or {},
            "tool_output": self.tool_output,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": format_utc_datetime(self.created_at),
        }


class ConversationStats(Base):
    """ConversationStats Table"""

    __tablename__ = "conversation_stats"

    id = Column(Integer, primary_key=True,
                autoincrement=True, comment="Primary key")
    conversation_id = Column(
        Integer, ForeignKey("conversations.id"), unique=True, nullable=False, comment="Conversation ID"
    )
    message_count = Column(Integer, default=0, comment="Total message count")
    total_tokens = Column(Integer, default=0, comment="Total tokens used")
    model_used = Column(String(100), nullable=True, comment="Model used")
    user_feedback = Column(JSON, nullable=True, comment="User feedback")
    created_at = Column(DateTime, default=utc_now_naive,
                        comment="Creation time")
    updated_at = Column(DateTime, default=utc_now_naive,
                        onupdate=utc_now_naive, comment="Update time")

    # Relationships
    conversation = relationship("Conversation", back_populates="stats")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "model_used": self.model_used,
            "user_feedback": self.user_feedback or {},
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class OperationLog(Base):
    """Operation Log Model"""

    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    operation = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    timestamp = Column(DateTime, default=utc_now_naive)

    # associated user
    user = relationship("User", back_populates="operation_logs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "operation": self.operation,
            "details": self.details,
            "ip_address": self.ip_address,
            "timestamp": format_utc_datetime(self.timestamp),
        }


class MessageFeedback(Base):
    """Message Feedback Table"""

    __tablename__ = "message_feedbacks"

    id = Column(Integer, primary_key=True,
                autoincrement=True, comment="Primary key")
    message_id = Column(
        Integer, ForeignKey("messages.id"), nullable=False, index=True, comment="Message ID being rated"
    )
    user_id = Column(String(64), nullable=False, index=True,
                     comment="User ID who provided feedback")
    rating = Column(String(10), nullable=False,
                    comment="Feedback rating: like or dislike")
    reason = Column(Text, nullable=True,
                    comment="Optional reason for dislike feedback")
    created_at = Column(DateTime, default=utc_now_naive,
                        comment="Feedback creation time")

    # Relationships
    message = relationship("Message", back_populates="feedbacks")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "user_id": self.user_id,
            "rating": self.rating,
            "reason": self.reason,
            "created_at": format_utc_datetime(self.created_at),
        }


class MCPServer(Base):
    """MCP Server Configuration Model"""

    __tablename__ = "mcp_servers"

    # Core field - name as primary key
    name = Column(String(100), primary_key=True,
                  comment="server name (unique identifier)")
    description = Column(String(500), nullable=True, comment="description")

    # Connection configuration
    transport = Column(String(20), nullable=False,
                       comment="Transport type: sse/streamable_http/stdio")
    url = Column(String(500), nullable=True,
                 comment="Server URL (sse/streamable_http)")
    command = Column(String(500), nullable=True, comment="Command (stdio)")
    args = Column(JSON, nullable=True,
                  comment="Command argument array (stdio)")
    env = Column(JSON, nullable=True, comment="Environment variables (stdio)")
    headers = Column(JSON, nullable=True, comment="HTTP request headers")
    timeout = Column(Integer, nullable=True, comment="HTTP timeout (seconds)")
    sse_read_timeout = Column(Integer, nullable=True,
                              comment="SSE read timeout (seconds)")

    # UI enhancement fields
    tags = Column(JSON, nullable=True, comment="Tag array")
    icon = Column(String(50), nullable=True, comment="Icon (emoji)")

    # Status fields
    enabled = Column(Integer, nullable=False, default=1,
                     comment="Enabled flag: 1=yes, 0=no")
    disabled_tools = Column(JSON, nullable=True,
                            comment="List of disabled tool names")

    # User audit fields
    created_by = Column(String(100), nullable=False,
                        comment="Creator username")
    updated_by = Column(String(100), nullable=False,
                        comment="Last modifier username")

    # Timestamps
    created_at = Column(DateTime, default=utc_now_naive,
                        comment="Creation time")
    updated_at = Column(DateTime, default=utc_now_naive,
                        onupdate=utc_now_naive, comment="Update time")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "transport": self.transport,
            "url": self.url,
            "command": self.command,
            "args": self.args or [],
            "env": self.env or {},
            "headers": self.headers or {},
            "timeout": self.timeout,
            "sse_read_timeout": self.sse_read_timeout,
            "tags": self.tags or [],
            "icon": self.icon,
            "enabled": bool(self.enabled),
            "disabled_tools": self.disabled_tools or [],
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }

    def to_mcp_config(self) -> dict[str, Any]:
        """Convert to MCP config format (used for loading into MCP_SERVERS cache)."""
        import json

        config = {"transport": self.transport}
        if self.url:
            config["url"] = self.url
        if self.command:
            config["command"] = self.command
        # args is only used for stdio transport and must be a list
        if self.transport == "stdio" and self.args:
            if isinstance(self.args, list):
                config["args"] = self.args
            elif isinstance(self.args, str):
                try:
                    config["args"] = json.loads(self.args)
                except json.JSONDecodeError:
                    pass
        if self.transport == "stdio" and self.env:
            if isinstance(self.env, dict):
                config["env"] = self.env
            elif isinstance(self.env, str):
                try:
                    config["env"] = json.loads(self.env)
                except json.JSONDecodeError:
                    pass
        # headers is only used for sse/streamable_http transport
        if self.transport in ("sse", "streamable_http") and self.headers:
            if isinstance(self.headers, dict):
                config["headers"] = self.headers
            elif isinstance(self.headers, str):
                try:
                    config["headers"] = json.loads(self.headers)
                except json.JSONDecodeError:
                    pass
        if self.timeout is not None:
            config["timeout"] = self.timeout
        if self.sse_read_timeout is not None:
            config["sse_read_timeout"] = self.sse_read_timeout
        if self.disabled_tools:
            config["disabled_tools"] = self.disabled_tools
        return config


class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(String(32), primary_key=True)
    name = Column(String(255), nullable=False)
    type = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    progress = Column(Float, nullable=False, default=0.0)
    message = Column(Text, nullable=False, default="")
    payload = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    cancel_requested = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now_naive, index=True)
    updated_at = Column(DateTime, default=utc_now_naive,
                        onupdate=utc_now_naive)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
            "started_at": format_utc_datetime(self.started_at),
            "completed_at": format_utc_datetime(self.completed_at),
            "payload": self.payload or {},
            "result": self.result,
            "error": self.error,
            "cancel_requested": bool(self.cancel_requested),
        }

    def to_summary_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("payload", None)
        data.pop("result", None)
        return data


class SubAgent(Base):
    """SubAgent model - used for dynamic subagent configuration."""

    __tablename__ = "subagents"

    name = Column(String(128), primary_key=True, comment="unique identifier")
    description = Column(Text, nullable=False, comment="description")
    system_prompt = Column(Text, nullable=False, comment="System prompt")
    tools = Column(JSON, nullable=False, default=list,
                   comment="Tool name list")
    model = Column(String(128), nullable=True,
                   comment="Optional model override")
    enabled = Column(Boolean, nullable=False, default=True,
                     comment="Whether enabled")

    is_builtin = Column(Boolean, nullable=False,
                        default=False, comment="Whether built-in")

    created_by = Column(String(100), nullable=True)
    updated_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive,
                        onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools": self.tools or [],
            "model": self.model,
            "enabled": bool(self.enabled),
            "is_builtin": bool(self.is_builtin),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }

    def to_subagent_spec(self) -> dict[str, Any]:
        """Convert to the spec format required by SubAgentMiddleware."""
        spec = {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools": self.tools or [],
        }
        if self.model:
            spec["model"] = self.model
        return spec


class APIKey(Base):
    """API Key model"""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(16), nullable=False)
    name = Column(String(100), nullable=False)

    user_id = Column(Integer, ForeignKey(
        "users.id"), nullable=True, index=True)
    department_id = Column(Integer, ForeignKey(
        "departments.id"), nullable=True, index=True)

    expires_at = Column(DateTime, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)
    last_used_at = Column(DateTime, nullable=True)

    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive)

    # associated
    user = relationship("User", back_populates="api_keys")
    department = relationship("Department")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key_prefix": self.key_prefix,
            "name": self.name,
            "user_id": self.user_id,
            "department_id": self.department_id,
            "expires_at": format_utc_datetime(self.expires_at),
            "is_enabled": bool(self.is_enabled),
            "last_used_at": format_utc_datetime(self.last_used_at),
            "created_by": self.created_by,
            "created_at": format_utc_datetime(self.created_at),
        }

    def is_valid(self) -> bool:
        """check Key whethervalid"""
        if not self.is_enabled:
            return False
        if self.expires_at and utc_now_naive() > self.expires_at:
            return False
        return True


class AgentRun(Base):
    """AgentRun table - run task records."""

    __tablename__ = "agent_runs"

    id = Column(String(64), primary_key=True, comment="Run ID (UUID)")
    thread_id = Column(String(64), index=True,
                       nullable=False, comment="Thread ID")
    agent_id = Column(String(64), index=True,
                      nullable=False, comment="Agent ID")
    user_id = Column(String(64), index=True, nullable=False, comment="User ID")
    status = Column(
        String(32),
        index=True,
        nullable=False,
        default="pending",
        comment="Run status: pending/running/completed/failed/cancel_requested/cancelled/interrupted",
    )
    request_id = Column(String(64), unique=True, index=True,
                        nullable=False, comment="Idempotency request ID")
    input_payload = Column(JSON, nullable=False,
                           default=dict, comment="Original input payload")
    error_type = Column(String(64), nullable=True, comment="Error type")
    error_message = Column(Text, nullable=True, comment="Error message")
    started_at = Column(DateTime, nullable=True, comment="Start time")
    finished_at = Column(DateTime, nullable=True, comment="Finish time")
    created_at = Column(DateTime, default=utc_now_naive,
                        comment="Creation time")
    updated_at = Column(DateTime, default=utc_now_naive,
                        onupdate=utc_now_naive, comment="Update time")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "status": self.status,
            "request_id": self.request_id,
            "input_payload": self.input_payload or {},
            "error_type": self.error_type,
            "error_message": self.error_message,
            "started_at": format_utc_datetime(self.started_at),
            "finished_at": format_utc_datetime(self.finished_at),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }
