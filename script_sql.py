#!/usr/bin/env python3
"""
MySQL数据库连接脚本
用于连接远程MySQL服务器并执行基本操作
"""

import pymysql
from typing import Optional


class MySQLConnection:
    """MySQL数据库连接类"""
    
    def __init__(
        self,
        host: str = "106.75.254.80",
        user: str = "root",  # 默认用户名，可根据实际情况修改
        password: str = "aEKexS7vByGxfm6Z",
        database: str = "bead",
        port: int = 3306,
        charset: str = "utf8mb4"
    ):
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.port = port
        self.charset = charset
        self.connection: Optional[pymysql.Connection] = None
    
    def connect(self) -> bool:
        """建立数据库连接"""
        try:
            self.connection = pymysql.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database,
                port=self.port,
                charset=self.charset,
                cursorclass=pymysql.cursors.DictCursor
            )
            print(f"✓ 成功连接到MySQL服务器: {self.host}:{self.port}")
            print(f"✓ 当前数据库: {self.database}")
            return True
        except pymysql.Error as e:
            print(f"✗ 连接失败: {e}")
            return False
    
    def execute_query(self, sql: str, params: tuple = None) -> Optional[list]:
        """执行查询语句"""
        if not self.connection:
            print("✗ 数据库未连接，请先调用connect()方法")
            return None
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                result = cursor.fetchall()
                return result
        except pymysql.Error as e:
            print(f"✗ 查询执行失败: {e}")
            return None
    
    def execute_update(self, sql: str, params: tuple = None) -> bool:
        """执行更新语句（INSERT, UPDATE, DELETE）"""
        if not self.connection:
            print("✗ 数据库未连接，请先调用connect()方法")
            return False
        
        try:
            with self.connection.cursor() as cursor:
                affected_rows = cursor.execute(sql, params)
                self.connection.commit()
                print(f"✓ 执行成功，影响行数: {affected_rows}")
                return True
        except pymysql.Error as e:
            self.connection.rollback()
            print(f"✗ 更新执行失败: {e}")
            return False
    
    def get_tables(self) -> list:
        """获取数据库中的所有表"""
        sql = "SHOW TABLES"
        result = self.execute_query(sql)
        if result:
            # 提取表名（SHOW TABLES返回的键名可能因MySQL版本而异）
            tables = []
            for row in result:
                tables.extend(list(row.values()))
            return tables
        return []
    
    def get_table_info(self, table_name: str) -> Optional[list]:
        """获取表结构信息"""
        sql = f"DESCRIBE {table_name}"
        return self.execute_query(sql)
    
    def close(self):
        """关闭数据库连接"""
        if self.connection:
            self.connection.close()
            print("✓ 数据库连接已关闭")


def main():
    """主函数 - 测试连接和基本操作"""
    # 创建连接实例
    db = MySQLConnection(
        host="106.75.254.80",
        user="root",  # 如果用户名不是root，请修改此处
        password="aEKexS7vByGxfm6Z",
        database="bead",
        port=3306
    )
    
    # 连接数据库
    if not db.connect():
        return
    
    try:
        # 测试查询：获取MySQL版本
        print("\n" + "="*50)
        print("测试查询：MySQL版本信息")
        print("="*50)
        version_result = db.execute_query("SELECT VERSION() as version")
        if version_result:
            print(f"MySQL版本: {version_result[0]['version']}")
        
        # 获取数据库中的所有表
        print("\n" + "="*50)
        print("数据库表列表")
        print("="*50)
        tables = db.get_tables()
        if tables:
            for i, table in enumerate(tables, 1):
                print(f"{i}. {table}")
        else:
            print("数据库中没有表")
        
        # 如果存在表，显示第一个表的结构
        if tables:
            print("\n" + "="*50)
            print(f"表 '{tables[0]}' 的结构")
            print("="*50)
            table_info = db.get_table_info(tables[0])
            if table_info:
                for field in table_info:
                    print(f"字段: {field.get('Field')}, 类型: {field.get('Type')}, "
                          f"空值: {field.get('Null')}, 键: {field.get('Key')}")
        
        # 示例：查询表中的数据（如果表存在且有数据）
        if tables:
            print("\n" + "="*50)
            print(f"查询表 '{tables[0]}' 的前5条数据")
            print("="*50)
            sample_data = db.execute_query(f"SELECT * FROM {tables[0]} LIMIT 5")
            if sample_data:
                for row in sample_data:
                    print(row)
            else:
                print("表中没有数据")
        
    except Exception as e:
        print(f"✗ 发生错误: {e}")
    finally:
        # 关闭连接
        db.close()


if __name__ == "__main__":
    main()

