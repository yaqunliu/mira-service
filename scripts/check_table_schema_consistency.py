#!/usr/bin/env python3
"""
检查数据库表结构和 SQLAlchemy 模型的一致性
找出哪些字段多了，哪些字段缺失
"""
import sys
import os
import json
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import inspect
from app.db.base import engine
from app.models import (
    User, Product, Order, Subscription,
    CreemPayment, WechatPayment,
    CreemSubscription, WechatSubscription,
    SubscriptionPointsHistory, WebhookEvent,
    PointsAccount, PointsRecord
)

def get_database_columns(engine, table_name):
    """获取数据库表中的所有列"""
    inspector = inspect(engine)
    columns = inspector.get_columns(table_name)
    return {col['name']: {
        'type': str(col['type']),
        'nullable': col['nullable'],
        'default': col.get('default'),
        'primary_key': col.get('primary_key', False),
    } for col in columns}

def get_model_columns(model_class):
    """获取 SQLAlchemy 模型中的所有列"""
    mapper = inspect(model_class)
    columns = {}
    for column in mapper.columns:
        default_str = None
        if column.default:
            if hasattr(column.default, 'arg'):
                default_str = str(column.default.arg)
            else:
                default_str = str(column.default)
        columns[column.name] = {
            'type': str(column.type),
            'nullable': column.nullable,
            'default': default_str,
            'primary_key': column.primary_key,
        }
    return columns

def compare_schemas(db_columns, model_columns, table_name):
    """比较数据库表和模型的字段"""
    db_field_names = set(db_columns.keys())
    model_field_names = set(model_columns.keys())
    
    missing_in_model = db_field_names - model_field_names
    missing_in_db = model_field_names - db_field_names
    common_fields = db_field_names & model_field_names
    
    differences = []
    
    # 检查缺失的字段
    if missing_in_model:
        differences.append({
            'type': 'missing_in_model',
            'fields': missing_in_model,
            'details': {field: db_columns[field] for field in missing_in_model}
        })
    
    if missing_in_db:
        differences.append({
            'type': 'missing_in_db',
            'fields': missing_in_db,
            'details': {field: model_columns[field] for field in missing_in_db}
        })
    
    # 检查类型和可空性差异
    type_differences = []
    nullable_differences = []
    
    for field in common_fields:
        db_col = db_columns[field]
        model_col = model_columns[field]
        
        # 简化类型比较（忽略一些细节差异）
        db_type_str = str(db_col['type']).upper()
        model_type_str = str(model_col['type']).upper()
        
        # 类型映射（处理一些常见的类型差异）
        type_mapping = {
            'VARCHAR': 'STRING',
            'TEXT': 'TEXT',
            'INTEGER': 'INTEGER',
            'BIGINT': 'BIGINT',
            'BOOLEAN': 'BOOLEAN',
            'TIMESTAMP': 'DATETIME',
            'TIMESTAMPTZ': 'DATETIME',
            'JSONB': 'JSON',
            'UUID': 'UUID',
        }
        
        db_type_normalized = type_mapping.get(db_type_str.split('(')[0], db_type_str)
        model_type_normalized = type_mapping.get(model_type_str.split('(')[0], model_type_str)
        
        if db_type_normalized != model_type_normalized and not (
            'VARCHAR' in db_type_str and 'STRING' in model_type_str
        ):
            type_differences.append({
                'field': field,
                'db_type': db_col['type'],
                'model_type': model_col['type']
            })
        
        if db_col['nullable'] != model_col['nullable']:
            nullable_differences.append({
                'field': field,
                'db_nullable': db_col['nullable'],
                'model_nullable': model_col['nullable']
            })
    
    if type_differences:
        differences.append({
            'type': 'type_mismatch',
            'fields': type_differences
        })
    
    if nullable_differences:
        differences.append({
            'type': 'nullable_mismatch',
            'fields': nullable_differences
        })
    
    return differences

def main():
    """主函数"""
    # 使用已有的数据库连接
    try:
        inspector = inspect(engine)
    except Exception as e:
        print("=" * 80)
        print("❌ 无法连接到数据库")
        print("=" * 80)
        print(f"错误: {e}")
        print()
        print("请确保:")
        print("1. 数据库服务正在运行")
        print("2. 环境变量已正确配置 (DATABASE_HOST, DATABASE_USER, DATABASE_PASSWORD, DATABASE_NAME)")
        print("3. 数据库连接信息正确")
        print()
        print("如果使用 Docker，请确保容器正在运行:")
        print("  docker-compose up -d")
        print()
        return {}
    
    # 定义表名和模型的映射
    table_model_mapping = {
        'users': User,
        'products': Product,
        'orders': Order,
        'subscriptions': Subscription,
        'creem_payments': CreemPayment,
        'wechat_payments': WechatPayment,
        'creem_subscriptions': CreemSubscription,
        'wechat_subscriptions': WechatSubscription,
        'subscription_points_history': SubscriptionPointsHistory,
        'webhook_events': WebhookEvent,
        'points_accounts': PointsAccount,
        'points_records': PointsRecord,
    }
    
    all_differences = {}
    
    print("=" * 80)
    print("数据库表结构和 SQLAlchemy 模型一致性检查")
    print("=" * 80)
    print()
    
    # 检查每个表
    for table_name, model_class in table_model_mapping.items():
        try:
            # 检查表是否存在
            if not inspector.has_table(table_name):
                print(f"⚠️  表 '{table_name}' 在数据库中不存在")
                continue
            
            # 获取数据库表的列
            db_columns = get_database_columns(engine, table_name)
            
            # 获取模型的列
            model_columns = get_model_columns(model_class)
            
            # 比较
            differences = compare_schemas(db_columns, model_columns, table_name)
            
            if differences:
                all_differences[table_name] = {
                    'model': model_class.__name__,
                    'differences': differences,
                    'db_columns': db_columns,
                    'model_columns': model_columns
                }
                
                print(f"❌ 表 '{table_name}' ({model_class.__name__}) 存在差异")
                # 简要信息，详细信息在后面
                for diff in differences:
                    if diff['type'] == 'missing_in_model':
                        print(f"  ⚠️  数据库中有但模型中缺失的字段: {', '.join(diff['fields'])}")
                    elif diff['type'] == 'missing_in_db':
                        print(f"  ⚠️  模型中有但数据库中缺失的字段: {', '.join(diff['fields'])}")
                    elif diff['type'] == 'type_mismatch':
                        print(f"  ⚠️  类型不匹配的字段: {', '.join([item['field'] for item in diff['fields']])}")
                    elif diff['type'] == 'nullable_mismatch':
                        print(f"  ⚠️  可空性不匹配的字段: {', '.join([item['field'] for item in diff['fields']])}")
                print()
            else:
                print(f"✅ 表 '{table_name}' ({model_class.__name__}) 一致")
        except Exception as e:
            print(f"❌ 检查表 '{table_name}' 时出错: {e}")
            import traceback
            traceback.print_exc()
            print()
    
    print("=" * 80)
    print("检查完成")
    print("=" * 80)
    print()
    
    # 生成详细的迁移建议
    if all_differences:
        print("=" * 80)
        print("详细差异报告和迁移建议")
        print("=" * 80)
        print()
        
        for table_name, info in all_differences.items():
            print(f"\n{'=' * 80}")
            print(f"表: {table_name} (模型: {info['model']})")
            print(f"{'=' * 80}")
            
            for diff in info['differences']:
                if diff['type'] == 'missing_in_model':
                    print(f"\n【问题】数据库中有但模型中缺失的字段 ({len(diff['fields'])} 个):")
                    print(f"  字段列表: {', '.join(diff['fields'])}")
                    print(f"\n  详细信息:")
                    for field, details in diff['details'].items():
                        default_str = f", default={details['default']}" if details['default'] else ""
                        pk_str = ", primary_key=True" if details['primary_key'] else ""
                        print(f"    - {field}:")
                        print(f"       类型: {details['type']}")
                        print(f"       可空: {details['nullable']}")
                        print(f"       主键: {details['primary_key']}")
                        if details['default']:
                            print(f"       默认值: {details['default']}")
                    print(f"\n  【迁移建议】需要在模型中添加这些字段，或者从数据库中删除:")
                    print(f"  方案1 - 在模型中添加字段 (如果字段确实需要):")
                    for field, details in diff['details'].items():
                        nullable_str = "nullable=True" if details['nullable'] else "nullable=False"
                        default_str = f", default={details['default']}" if details['default'] else ""
                        pk_str = ", primary_key=True" if details['primary_key'] else ""
                        print(f"    {field} = Column({details['type']}, {nullable_str}{default_str}{pk_str})")
                    print(f"\n  方案2 - 从数据库中删除字段 (如果字段不再需要):")
                    for field in diff['fields']:
                        print(f"    op.drop_column('{table_name}', '{field}')")
                
                elif diff['type'] == 'missing_in_db':
                    print(f"\n【问题】模型中有但数据库中缺失的字段 ({len(diff['fields'])} 个):")
                    print(f"  字段列表: {', '.join(diff['fields'])}")
                    print(f"\n  详细信息:")
                    for field, details in diff['details'].items():
                        default_str = f", default={details['default']}" if details['default'] else ""
                        pk_str = ", primary_key=True" if details['primary_key'] else ""
                        print(f"    - {field}:")
                        print(f"       类型: {details['type']}")
                        print(f"       可空: {details['nullable']}")
                        print(f"       主键: {details['primary_key']}")
                        if details['default']:
                            print(f"       默认值: {details['default']}")
                    print(f"\n  【迁移建议】需要在数据库中添加这些字段:")
                    for field, details in diff['details'].items():
                        nullable_str = "nullable=True" if details['nullable'] else "nullable=False"
                        default_str = ""
                        if details['default']:
                            if isinstance(details['default'], str) and 'server_default' in details['default']:
                                default_str = f", server_default={details['default']}"
                            else:
                                default_str = f", server_default=sa.text('{details['default']}')"
                        print(f"    op.add_column('{table_name}', sa.Column('{field}', {details['type']}, {nullable_str}{default_str}))")
                
                elif diff['type'] == 'type_mismatch':
                    print(f"\n【问题】类型不匹配的字段 ({len(diff['fields'])} 个):")
                    for item in diff['fields']:
                        print(f"    - {item['field']}:")
                        print(f"       数据库类型: {item['db_type']}")
                        print(f"       模型类型: {item['model_type']}")
                    print(f"\n  【迁移建议】需要统一类型（通常需要修改数据库）:")
                    for item in diff['fields']:
                        print(f"    # 注意: 需要根据实际情况决定是修改数据库还是模型")
                        print(f"    # op.alter_column('{table_name}', '{item['field']}', type_={item['model_type']})")
                
                elif diff['type'] == 'nullable_mismatch':
                    print(f"\n【问题】可空性不匹配的字段 ({len(diff['fields'])} 个):")
                    for item in diff['fields']:
                        print(f"    - {item['field']}:")
                        print(f"       数据库可空: {item['db_nullable']}")
                        print(f"       模型可空: {item['model_nullable']}")
                    print(f"\n  【迁移建议】需要统一可空性:")
                    for item in diff['fields']:
                        if item['db_nullable'] and not item['model_nullable']:
                            print(f"    # 数据库允许 NULL，但模型不允许，需要修改数据库:")
                            print(f"    op.alter_column('{table_name}', '{item['field']}', nullable=False)")
                        elif not item['db_nullable'] and item['model_nullable']:
                            print(f"    # 数据库不允许 NULL，但模型允许，需要修改数据库:")
                            print(f"    op.alter_column('{table_name}', '{item['field']}', nullable=True)")
            
            print()
    else:
        print("✅ 所有表的结构都一致，没有发现差异！")
        print()
    
    # 输出 JSON 格式的摘要（便于程序处理）
    print("=" * 80)
    print("差异摘要 (JSON 格式)")
    print("=" * 80)
    summary = {}
    for table_name, info in all_differences.items():
        summary[table_name] = {
            'model': info['model'],
            'missing_in_model': [],
            'missing_in_db': [],
            'type_mismatch': [],
            'nullable_mismatch': []
        }
        for diff in info['differences']:
            if diff['type'] == 'missing_in_model':
                summary[table_name]['missing_in_model'] = list(diff['fields'])
            elif diff['type'] == 'missing_in_db':
                summary[table_name]['missing_in_db'] = list(diff['fields'])
            elif diff['type'] == 'type_mismatch':
                summary[table_name]['type_mismatch'] = [item['field'] for item in diff['fields']]
            elif diff['type'] == 'nullable_mismatch':
                summary[table_name]['nullable_mismatch'] = [item['field'] for item in diff['fields']]
    
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print()
    
    return all_differences

if __name__ == '__main__':
    main()
