# Agent 工作流数据库迁移指南

## 问题修复

已修复 SQLAlchemy `metadata` 保留字段冲突：
- `AgentSession.metadata` → `AgentSession.session_metadata`
- `AgentMessage.metadata` → `AgentMessage.message_metadata`
- `AgentCheckpoint.metadata` → `AgentCheckpoint.checkpoint_metadata`

## 在 Docker 中生成迁移

### 1. 进入 Docker 容器

```bash
docker exec -it mira-service bash
```

### 2. 生成迁移脚本

```bash
cd /app
alembic revision --autogenerate -m "Add Agent workflow support"
```

### 3. 检查生成的迁移文件

迁移文件位于 `alembic/versions/` 目录，检查内容是否包含：

**预期包含的变更**：

#### 3.1 创建枚举类型

```sql
CREATE TYPE workflow_mode_enum AS ENUM ('traditional', 'agent');
CREATE TYPE production_stage_enum AS ENUM ('init', 'script_analysis', 'asset_generation', 'storyboard_creation', 'audio_processing', 'editing', 'completed');
CREATE TYPE checkpoint_status_enum AS ENUM ('pending', 'approved', 'rejected', 'partial');
CREATE TYPE message_role_enum AS ENUM ('user', 'assistant', 'system');
CREATE TYPE event_type_enum AS ENUM ('message', 'tool_call', 'tool_output', 'progress', 'board_action', 'action_request', 'thinking', 'error');
```

#### 3.2 扩展 creations 表

```sql
ALTER TABLE creations
ADD COLUMN workflow_mode workflow_mode_enum DEFAULT 'traditional' NOT NULL,
ADD COLUMN agent_session_id VARCHAR(100);

CREATE INDEX ix_creations_workflow_mode ON creations(workflow_mode);
CREATE INDEX ix_creations_agent_session_id ON creations(agent_session_id);
```

#### 3.3 创建 agent_sessions 表

```sql
CREATE TABLE agent_sessions (
    session_id SERIAL PRIMARY KEY,
    uuid UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    creation_id INTEGER NOT NULL REFERENCES creations(creation_id) ON DELETE CASCADE,
    thread_id VARCHAR(100) NOT NULL UNIQUE,
    current_stage production_stage_enum DEFAULT 'init' NOT NULL,
    checkpoint_data JSONB,
    user_feedback JSONB,
    checkpoint_status checkpoint_status_enum,
    session_metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX ix_agent_sessions_uuid ON agent_sessions(uuid);
CREATE INDEX ix_agent_sessions_creation_id ON agent_sessions(creation_id);
CREATE INDEX ix_agent_sessions_thread_id ON agent_sessions(thread_id);
CREATE INDEX ix_agent_sessions_current_stage ON agent_sessions(current_stage);
```

#### 3.4 创建 agent_messages 表

```sql
CREATE TABLE agent_messages (
    message_id SERIAL PRIMARY KEY,
    uuid UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    session_id INTEGER NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
    role message_role_enum NOT NULL,
    content TEXT,
    event_type event_type_enum DEFAULT 'message' NOT NULL,
    message_metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX ix_agent_messages_uuid ON agent_messages(uuid);
CREATE INDEX ix_agent_messages_session_id ON agent_messages(session_id);
CREATE INDEX ix_agent_messages_role ON agent_messages(role);
CREATE INDEX ix_agent_messages_event_type ON agent_messages(event_type);
CREATE INDEX ix_agent_messages_created_at ON agent_messages(created_at);
```

#### 3.5 创建 agent_checkpoints 表

```sql
CREATE TABLE agent_checkpoints (
    thread_id VARCHAR(255) PRIMARY KEY,
    checkpoint_id VARCHAR(255) NOT NULL,
    parent_checkpoint_id VARCHAR(255),
    checkpoint_data JSONB NOT NULL,
    checkpoint_metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_checkpoint_thread_id ON agent_checkpoints(thread_id);
CREATE INDEX idx_checkpoint_id ON agent_checkpoints(checkpoint_id);
CREATE INDEX idx_checkpoint_created_at ON agent_checkpoints(created_at);
CREATE INDEX idx_checkpoint_thread_created ON agent_checkpoints(thread_id, created_at);
```

### 4. 执行迁移

```bash
alembic upgrade head
```

### 5. 验证迁移

```bash
# 检查表是否创建成功
psql -U postgres -d video_generator -c "\dt agent_*"

# 检查 creations 表新字段
psql -U postgres -d video_generator -c "\d creations" | grep -A 2 workflow_mode

# 检查枚举类型
psql -U postgres -d video_generator -c "\dT+ *_enum"
```

## 回滚迁移（如需要）

```bash
# 回滚上一个迁移
alembic downgrade -1

# 回滚到特定版本
alembic downgrade <revision_id>
```

## 常见问题

### Q1: 迁移生成失败

**可能原因**：
- 数据库连接失败
- 模型导入错误（已修复 metadata 字段冲突）

**解决方案**：
```bash
# 检查数据库连接
psql -U postgres -d video_generator -c "SELECT 1"

# 检查 Python 导入
python -c "from app.models import AgentSession, AgentMessage, AgentCheckpoint"
```

### Q2: 枚举类型冲突

**错误信息**：`type "workflow_mode_enum" already exists`

**解决方案**：
```sql
-- 删除已存在的枚举类型
DROP TYPE IF EXISTS workflow_mode_enum CASCADE;
DROP TYPE IF EXISTS production_stage_enum CASCADE;
DROP TYPE IF EXISTS checkpoint_status_enum CASCADE;
DROP TYPE IF EXISTS message_role_enum CASCADE;
DROP TYPE IF EXISTS event_type_enum CASCADE;

-- 重新运行迁移
alembic upgrade head
```

### Q3: 外键约束失败

**错误信息**：`foreign key constraint fails`

**解决方案**：
- 确保 `creations` 表存在且有数据
- 检查 `creation_id` 字段类型匹配

## 迁移完成检查清单

- [ ] 5 个枚举类型创建成功
- [ ] `creations` 表添加了 2 个新字段
- [ ] `agent_sessions` 表创建成功
- [ ] `agent_messages` 表创建成功
- [ ] `agent_checkpoints` 表创建成功
- [ ] 所有索引创建成功
- [ ] 外键约束正常工作

## 下一步

迁移成功后，可以继续执行：
1. 安装新依赖：`pip install -e .`
2. 重启服务：`docker-compose restart mira-service`
3. 测试 Agent 模式创建：创建一个 `workflow_mode=agent` 的 Creation

---

**需要帮助？** 查看迁移日志：`docker logs mira-service | grep alembic`
