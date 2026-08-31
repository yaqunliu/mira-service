#!/usr/bin/env bash
#
# Mira 后端部署脚本（Docker）
#
# 用法：
#   ./deploy.sh                # 完整流程：拉代码 → 构建 → 启动 → 迁移 → 健康检查
#   ./deploy.sh --no-pull      # 跳过 git pull（本地有改动、或不想动代码时）
#   ./deploy.sh --no-build     # 跳过镜像构建（只改了 .env / compose 配置时）
#   ./deploy.sh --skip-migrate # 跳过数据库迁移
#
# 幂等：可重复执行。
#
# 取代原 migrate-docker.sh —— 那个脚本用的是 docker-compose v1 命令，
# 新版 Docker 只有 docker compose 子命令，已经跑不起来。

set -euo pipefail

cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()      { echo -e "${GREEN}[ OK ]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()     { echo -e "${RED}[FAIL]${NC} $1"; }
section() { echo; echo "=========================================="; echo " $1"; echo "=========================================="; }

DO_PULL=1; DO_BUILD=1; DO_MIGRATE=1
for arg in "$@"; do
  case "$arg" in
    --no-pull)      DO_PULL=0 ;;
    --no-build)     DO_BUILD=0 ;;
    --skip-migrate) DO_MIGRATE=0 ;;
    -h|--help)      sed -n '2,20p' "$0"; exit 0 ;;
    *) err "未知参数: $arg"; exit 1 ;;
  esac
done

SHARED_NET="mira-net"

# ------------------------------------------------------------
# 1. 环境检查
# ------------------------------------------------------------
section "1/7 环境检查"

command -v docker >/dev/null 2>&1 || { err "未安装 docker"; exit 1; }
docker compose version >/dev/null 2>&1 || {
  err "docker compose (v2) 不可用。本脚本不支持 v1 的 docker-compose 独立二进制。"
  exit 1
}
ok "docker $(docker --version | awk '{print $3}' | tr -d ,) / compose $(docker compose version --short)"

docker info >/dev/null 2>&1 || { err "Docker daemon 未运行"; exit 1; }
ok "Docker daemon 正常"

# ------------------------------------------------------------
# 2. .env 校验
#
# 这里的检查项都对应着「不检查就会在启动后才暴露、且报错信息误导性很强」的坑
# ------------------------------------------------------------
section "2/7 校验 .env"

[ -f .env ] || { err ".env 不存在。请执行: cp env.docker.example .env 然后填写"; exit 1; }

# 只取变量，不 source（避免 .env 里的内容被当成命令执行）
getenv() { grep -E "^${1}=" .env | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*$//'; }

FATAL=0

# 2.1 必填非空
for k in DATABASE_HOST DATABASE_PORT DATABASE_USER DATABASE_PASSWORD DATABASE_NAME \
         REDIS_PASSWORD SUPABASE_URL SUPABASE_ANON_KEY; do
  if [ -z "$(getenv "$k")" ]; then
    err "$k 为空（必填）"; FATAL=1
  fi
done

# 2.2 DATABASE_URL 必须为空，否则会覆盖 DATABASE_HOST 等字段
if [ -n "$(getenv DATABASE_URL)" ]; then
  err "DATABASE_URL 非空。config.py 会优先使用它并忽略 DATABASE_HOST，"
  err "  导致即使 DATABASE_HOST=postgres 也依然连不上数据库。请清空这一项。"
  FATAL=1
fi

# 2.3 容器内 localhost 指容器自己，必须用 compose 服务名
if echo "$(getenv DATABASE_HOST)" | grep -qE '^(localhost|127\.0\.0\.1)$'; then
  err "DATABASE_HOST=$(getenv DATABASE_HOST)，Docker 中应为服务名 postgres"; FATAL=1
fi
for k in REDIS_URL REDIS_BROKER_URL REDIS_BACKEND_URL; do
  v="$(getenv "$k")"
  if [ -n "$v" ] && echo "$v" | grep -qE '://(:[^@]*@)?(localhost|127\.0\.0\.1)'; then
    err "$k 指向 localhost，Docker 中应为 redis://redis:6379/N"; FATAL=1
  fi
done

# 2.4 SUPABASE_URL 不能带路径后缀（最常见的抄错来源：抄成了 Data API 地址）
SB_URL="$(getenv SUPABASE_URL)"
if echo "$SB_URL" | grep -qE '/(rest|auth|storage|realtime)/v[0-9]'; then
  err "SUPABASE_URL 带了路径后缀: $SB_URL"
  err "  应填 Project URL，形如 https://xxxxxxxx.supabase.co（不带任何路径）"
  FATAL=1
fi

[ "$FATAL" -eq 0 ] || { echo; err "配置校验未通过，已中止。"; exit 1; }
ok ".env 校验通过"

# 2.5 JWKS 连通性（非致命，但登录能否成功全看它）
if command -v curl >/dev/null 2>&1; then
  JWKS="${SB_URL%/}/auth/v1/.well-known/jwks.json"
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$JWKS" || echo 000)
  if [ "$CODE" = "200" ]; then
    ok "Supabase JWKS 可访问 ($JWKS)"
  else
    warn "Supabase JWKS 返回 HTTP $CODE — 登录会失败，请检查 SUPABASE_URL"
    warn "  $JWKS"
  fi
fi

# ------------------------------------------------------------
# 3. 共享网络
# ------------------------------------------------------------
section "3/7 共享网络 $SHARED_NET"

if docker network inspect "$SHARED_NET" >/dev/null 2>&1; then
  ok "网络 $SHARED_NET 已存在"
else
  docker network create "$SHARED_NET" >/dev/null
  ok "已创建网络 $SHARED_NET"
fi

# ------------------------------------------------------------
# 4. 拉取代码
# ------------------------------------------------------------
section "4/7 拉取代码"

if [ "$DO_PULL" -eq 1 ] && [ -d .git ]; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD)
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    warn "工作区有未提交改动，跳过 git pull（如需强制拉取请先手工处理）"
  else
    git pull --ff-only origin "$BRANCH"
    ok "已更新到 origin/$BRANCH"
  fi
else
  info "跳过 git pull"
fi

# ------------------------------------------------------------
# 5. 构建与启动
# ------------------------------------------------------------
section "5/7 构建与启动"

if [ "$DO_BUILD" -eq 1 ]; then
  info "构建镜像（首次约几分钟：要装 ffmpeg 与中文字体）..."
  docker compose build
  ok "镜像构建完成"
else
  info "跳过构建"
fi

# depends_on: condition: service_healthy 会让 compose 等 postgres/redis healthy
# 之后才启动 api 与 worker
info "启动容器..."
docker compose up -d
ok "容器已启动"

# ------------------------------------------------------------
# 6. 等待 API 就绪 + 数据库迁移
# ------------------------------------------------------------
section "6/7 等待就绪并迁移"

# 注意：镜像里没有装 curl，用 python 做健康检查
HEALTH_PY='import sys,urllib.request
try:
    r=urllib.request.urlopen("http://localhost:8100/health",timeout=3)
    sys.exit(0 if r.status==200 else 1)
except Exception:
    sys.exit(1)'

info "等待 API 就绪（最多 120 秒）..."
READY=0
for i in $(seq 1 60); do
  if docker compose exec -T api python -c "$HEALTH_PY" >/dev/null 2>&1; then
    READY=1; break
  fi
  sleep 2
done

if [ "$READY" -ne 1 ]; then
  err "API 未在 120 秒内就绪。最近日志："
  docker compose logs --tail=40 api
  exit 1
fi
ok "API 已就绪"

if [ "$DO_MIGRATE" -eq 1 ]; then
  info "执行数据库迁移 (alembic upgrade head)..."
  docker compose exec -T api alembic upgrade head
  ok "迁移完成，当前版本："
  docker compose exec -T api alembic current
else
  info "跳过迁移"
fi

# ------------------------------------------------------------
# 7. 结果
# ------------------------------------------------------------
section "7/7 部署结果"

docker compose ps

echo
ok "后端部署完成"
echo
info "端口说明（均只绑 127.0.0.1，不对公网暴露）："
info "  API      127.0.0.1:8100   前端通过共享网络以 http://mira-api:8100 访问"
info "  Postgres 127.0.0.1:5432"
info "  Redis    127.0.0.1:6379"
echo
info "本机验证：  docker compose exec -T api python -c '$HEALTH_PY' && echo OK"
info "远程调试：  ssh -L 8100:127.0.0.1:8100 <user>@<server>  然后本地开 http://localhost:8100/docs"
info "查看日志：  docker compose logs -f api"
info "            docker compose logs -f celery_worker"
info "内存占用：  docker stats --no-stream"
echo
warn "celery_beat 已在 docker-compose.yml 中注释关闭（演示期省内存）"
