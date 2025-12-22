# 数据库迁移脚本说明

## 脚本列表

### 1. `cleanup_and_reset_migration.py` - 清理并重置迁移 ⚠️ 完全重置

**用途：** 完全重置迁移状态，删除所有表、数据，回滚迁移版本。

**使用场景：**
- ✅ 迁移失败后需要重新开始
- ✅ 需要完全重置迁移状态
- ✅ 数据库状态和迁移记录不一致

**执行的操作：**
1. 删除所有订单、订阅、积分历史、webhook事件（数据）
2. 删除所有支付相关的表（表结构）：products, orders, subscriptions, creem_payments, wechat_payments等
3. 删除webhook_events表的source字段
4. 回滚迁移版本到 `merge_uuid_supabase_temp`

**使用方式：**
```bash
cd mira-service
python scripts/cleanup_and_reset_migration.py
# 输入: CLEAN ALL

# 然后运行迁移
uv run alembic upgrade head
```

---

### 2. `clear_all_orders_and_subscriptions.py` - 只清空数据 📝 保留表结构

**用途：** 只删除数据，保留表结构。**不删除表，不回滚迁移版本。**

**使用场景：**
- ✅ 迁移成功后，只需要清空测试数据
- ✅ 测试环境重置数据
- ✅ 保留表结构，只清理数据

**执行的操作：**
1. 删除所有订单、订阅、积分历史、webhook事件（仅数据）
2. **不删除表结构**
3. **不回滚迁移版本**

**使用方式：**
```bash
cd mira-service
python scripts/clear_all_orders_and_subscriptions.py
# 输入: DELETE ALL

# 迁移已完成，无需再次运行
```

---

## 使用场景对比

| 场景 | 使用哪个脚本 | 说明 |
|------|------------|------|
| 迁移失败，需要重新开始 | `cleanup_and_reset_migration.py` | 删除表结构，回滚版本 |
| 迁移成功，只想清空测试数据 | `clear_all_orders_and_subscriptions.py` | 保留表结构，只删数据 |
| 数据库状态和迁移记录不一致 | `cleanup_and_reset_migration.py` | 完全重置 |
| 生产环境（不要用！） | ❌ 都不要用 | 先备份数据库 |

---

## 完整迁移流程

### 场景1：迁移失败，需要重新开始

```bash
# 1. 完全重置（删除表、数据，回滚版本）
python scripts/cleanup_and_reset_migration.py
# 输入: CLEAN ALL

# 2. 运行新的迁移
uv run alembic upgrade head
```

### 场景2：迁移成功，只想清空测试数据

```bash
# 只清空数据（保留表结构）
python scripts/clear_all_orders_and_subscriptions.py
# 输入: DELETE ALL

# 迁移已完成，无需再次运行
```

---

## 重要提示

⚠️ **这两个脚本不需要都执行！根据场景选择其中一个：**

- **迁移失败/重置** → 用 `cleanup_and_reset_migration.py`
- **只清空数据** → 用 `clear_all_orders_and_subscriptions.py`

⚠️ **这些脚本会永久删除数据，无法恢复！**

- 仅用于开发环境
- 项目未上线时使用
- 生产环境请先备份数据库

---

## 注意事项

⚠️ **这些脚本会永久删除数据，无法恢复！**

- 仅用于开发环境
- 项目未上线时使用
- 生产环境请先备份数据库
