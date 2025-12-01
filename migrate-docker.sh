#!/bin/bash

# Docker 环境数据库迁移脚本
# 用途：在 Docker 容器中执行 Alembic 数据库迁移到最新版本

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 打印分隔线
print_separator() {
    echo "=========================================="
}

# 主函数
main() {
    print_separator
    print_info "Docker 环境数据库迁移脚本"
    print_separator
    
    # 检查 docker-compose.yml 是否存在
    if [ ! -f "docker-compose.yml" ]; then
        print_error "未找到 docker-compose.yml 文件，请确保在项目根目录执行此脚本"
        exit 1
    fi
    
    # 尝试检测服务名称（通常是 web 或 api）
    SERVICE_NAME=""
    if docker-compose ps | grep -q "web"; then
        SERVICE_NAME="web"
    elif docker-compose ps | grep -q "api"; then
        SERVICE_NAME="api"
    elif docker-compose ps | grep -q "app"; then
        SERVICE_NAME="app"
    else
        print_warning "无法自动检测服务名称，请手动指定"
        read -p "请输入 Docker 服务名称: " SERVICE_NAME
    fi
    
    if [ -z "$SERVICE_NAME" ]; then
        print_error "服务名称不能为空"
        exit 1
    fi
    
    print_info "使用服务: $SERVICE_NAME"
    echo ""
    
    # 检查容器是否运行
    if ! docker-compose ps | grep -q "$SERVICE_NAME.*Up"; then
        print_warning "服务 $SERVICE_NAME 未运行，尝试启动..."
        docker-compose up -d "$SERVICE_NAME"
        sleep 2
    fi
    
    # 显示当前 Alembic 版本
    print_info "检查当前数据库版本..."
    if docker-compose exec -T "$SERVICE_NAME" alembic current 2>/dev/null; then
        echo ""
    else
        print_warning "无法获取当前版本，可能是新数据库"
    fi
    
    # 显示待执行的迁移
    print_info "检查待执行的迁移..."
    docker-compose exec -T "$SERVICE_NAME" alembic heads
    echo ""
    
    # 确认执行
    print_warning "即将在 Docker 容器中执行迁移命令: alembic upgrade head"
    read -p "是否继续？(y/N): " -n 1 -r
    echo ""
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "已取消迁移"
        exit 0
    fi
    
    print_separator
    print_info "执行迁移中..."
    print_separator
    
    # 执行迁移
    if docker-compose exec -T "$SERVICE_NAME" alembic upgrade head; then
        print_separator
        print_success "数据库迁移成功完成！"
        print_separator
        
        # 显示迁移后的版本
        print_info "当前数据库版本："
        docker-compose exec -T "$SERVICE_NAME" alembic current
        
        print_separator
        exit 0
    else
        print_separator
        print_error "数据库迁移失败！"
        print_separator
        exit 1
    fi
}

# 执行主函数
main "$@"
