# Supervisor + ReAct Workers 架构改造文档

> **改造日期**: 2026-02-03  
> **Commit**: `ef62670` feat: support supervisor

---

## 一、改造目标

将生产子图从固定流水线改造为 **Supervisor + ReAct Workers** 架构，实现：

1. **智能调度** - Supervisor 根据用户意图动态决定执行顺序
2. **约束检查** - 自动检测操作是否会破坏数据一致性
3. **原子化操作** - 支持单个资产的重新生成、版本回滚
4. **渐进式改造** - Feature Flag 控制，可随时切换回 Legacy 模式

---

## 二、架构概览

```
┌─────────────────────────────────────────────────────────┐
│                    Comic Drama Subgraph                  │
├─────────────────────────────────────────────────────────┤
│  stage_router → supervisor → workers → stage_complete   │
│                     ↑                       │            │
│                     └───────────────────────┘            │
└─────────────────────────────────────────────────────────┘
```

### Supervisor 模式
- 入口：`stage_router` → `supervisor`
- Supervisor 通过 ReAct 循环决策，调用工具查询状态、检查约束
- `route_to_worker` 工具调度到具体 Worker
- Worker 完成后回到 `supervisor` 决定下一步

### Legacy 模式
- 入口：`stage_router` 直接路由到 Worker
- 固定流水线顺序执行

---

## 三、新增文件

| 文件 | 用途 |
|------|------|
| `nodes/supervisor.py` | Supervisor Node，ReAct 调度中心 |
| `nodes/teams/react_worker_base.py` | ReAct Worker 基类 |
| `tools/regenerate_tools.py` | 原子化资源操作（清空、提交生成、重新生成） |
| `tools/version_tools.py` | 版本历史管理（查询、回滚） |
| `tools/context_tools.py` | 上下文获取 + 约束检查 |

---

## 四、修改文件

| 文件 | 变更 |
|------|------|
| `comic_drama_subgraph.py` | 添加 `USE_SUPERVISOR_MODE` Feature Flag |
| `nodes/teams/script_analyst.py` | 继承 `ReActWorkerNode` 基类 |
| `nodes/teams/asset_director.py` | 添加 `USE_REACT` 标记 |
| `state/schemas.py` | 新增 `production_cache`, `next_worker`, `needs_input` |
| `tools/__init__.py` | 导出新工具 |
| `nodes/__init__.py` | 导出 `supervisor_node`, `route_from_supervisor` |

---

## 五、核心工具清单

### Supervisor 工具

| 工具 | 用途 |
|------|------|
| `query_production_status` | 查询生产状态并缓存 |
| `check_constraints` | 检查操作约束（如分镜已生成不能改角色） |
| `route_to_worker` | 调度任务到指定 Worker |
| `request_user_confirmation` | 请求用户确认 |

### 原子化工具

| 工具 | 用途 |
|------|------|
| `clear_asset` | 清空单个资产的图片/视频 |
| `submit_generation` | 提交生成任务 |
| `regenerate` | 组合工具：清空 + 生成 |
| `clear_all` | 批量清空 |

### 版本工具

| 工具 | 用途 |
|------|------|
| `get_version_history` | 获取资产历史版本 |
| `restore_version` | 回滚到指定版本 |

### 上下文工具

| 工具 | 用途 |
|------|------|
| `get_script_context` | 获取剧本上下文 |
| `get_adjacent_shots` | 获取相邻分镜 |
| `get_character_scene_for_shot` | 获取分镜相关角色/场景 |

---

## 六、Feature Flag 配置

```python
# comic_drama_subgraph.py
USE_SUPERVISOR_MODE = True   # 启用 Supervisor 模式
USE_SUPERVISOR_MODE = False  # Legacy 模式

# script_analyst.py
USE_REACT = True   # 启用 ReAct 循环
USE_REACT = False  # Legacy 直接调用 LLM
```

---

## 七、State 新增字段

```python
class ComicDramaState(TypedDict):
    # ... 原有字段 ...
    
    # Supervisor 模式新增
    production_cache: Dict[str, Any]  # 生产状态缓存
    next_worker: Optional[str]        # 下一个要执行的 Worker
    needs_input: bool                 # 是否需要用户输入
```

---

## 八、测试验证

```bash
# 运行独立测试
docker exec video_generator_api python /app/tests/test_supervisor_standalone.py

# 结果
✅ 工具导入 (regenerate_tools: 4, version_tools: 2, context_tools: 4)
✅ Supervisor Node 导入
✅ route_to_worker 工具
✅ route_from_supervisor 路由
✅ 子图构建
✅ State Schema
总计: 6/6 通过
```

---

## 九、后续优化

- [ ] 完整改造 AssetDirectorNode 为 ReAct 模式
- [ ] 完整改造 StoryboardDirectorNode 为 ReAct 模式
- [ ] 添加更多约束规则
- [ ] 优化 Supervisor 提示词
