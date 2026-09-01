#!/usr/bin/env bash
#
# Mira 后端部署脚本（Docker）
#
# 用法：
#   git pull origin master && ./deploy.sh     ← 标准用法
#
#   ./deploy.sh                # 校验 → 构建 → 启动 → 迁移 → 健康检查
#   ./deploy.sh --no-build     # 跳过镜像构建（只改了 .env / compose 配置时）
#   ./deploy.sh --skip-migrate # 跳过数据库迁移
#
# ⚠️ 本脚本不拉代码，git pull 由你显式执行。原因：
#    bash 是边读边执行的（分块读取，不是一次性载入）。脚本内部的 git pull
#    如果更新了 deploy.sh 自身，正在运行的 shell 会读到新旧混杂的内容，
#    表现为中途莫名的语法错误或静默跳步 —— 这类故障极难定位。
#    显式两步还有个好处：git pull 的输出（这次拉了哪些 commit）直接呈现在
#    眼前，而不是混在部署日志中间被忽略。
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

DO_BUILD=1; DO_MIGRATE=1
DEPRECATED_NOPULL=0
for arg in "$@"; do
  case "$arg" in
    --no-build)     DO_BUILD=0 ;;
    --skip-migrate) DO_MIGRATE=0 ;;
    # 兼容旧习惯：脚本已不再拉代码，这个参数成了空操作，接受但提示一次
    --no-pull)      DEPRECATED_NOPULL=1 ;;
    -h|--help)      sed -n '2,26p' "$0"; exit 0 ;;
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

# 2.2 DATABASE_URL 必须整行注释掉（既不能有值，也不能是空值）
#
# 旧版本这里只拦「非空」，把真正会崩的「空值」放过去了 —— 空值不是安全的
# 中间态，它比填错更糟：DATABASE_URL= 会让 pydantic 去解析空串并直接失败。
if grep -qE '^[[:space:]]*DATABASE_URL=' .env; then
  if [ -z "$(getenv DATABASE_URL)" ]; then
    err "DATABASE_URL= 是空值。声明类型为 Optional[PostgresDsn]（config.py:38），"
    err "  Optional 指可以是 None，不是可以是空字符串。空串会解析失败："
    err "    ValidationError: Input should be a valid URL, input is empty"
  else
    err "DATABASE_URL 非空。assemble_db_connection（config.py:41）只在它为 None"
    err "  时才自动拼装，非空会直接生效并忽略 DATABASE_HOST，"
    err "  导致即使 DATABASE_HOST=postgres 也依然连不上数据库。"
  fi
  err "  修复：把 .env 里这一行整行注释掉（前面加 #），连接串会自动拼装。"
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

# 2.5 密码字符集
#
# 两个密码都会被「裸拼」进连接 URL，代码里不做 percent-encode：
#   config.py:42-49   PostgresDsn.build(password=self.DATABASE_PASSWORD, ...)
#   config.py:79      f"redis://:{self.REDIS_PASSWORD}@{host}:{port}/{db}"
#
# 因此密码含 URL 保留字符时会出问题，且两者的表现完全不同：
#   - DATABASE_PASSWORD 含 "/" → authority 被截断，host/port 解析错位，
#     启动即报 ValidationError: invalid port number（好查）
#   - REDIS_PASSWORD 同样被截断，但 REDIS_URL 在 config.py:61 声明为 str，
#     pydantic 不做 URL 校验，错误会一路带到运行时 —— 表现为
#     「worker 起来了、日志也 ready，但任务永远不执行」（极难查）
#
# 所以这里对 Redis 密码和数据库密码用同一套标准，宁严勿松。
# 生成安全密码：openssl rand -hex 32
#
# 注：根治办法是在 config.py 两处对密码做 urllib.parse.quote_plus()，
#     那样任意密码都能用。本检查是在代码修好之前的前置拦截。
PW_FATAL_RE='[/@:#?%]|[[:space:]]'      # 确定会破坏 URL 结构
PW_UNRESERVED_RE='^[A-Za-z0-9._~-]+$'   # RFC 3986 unreserved，最安全的集合

for k in DATABASE_PASSWORD REDIS_PASSWORD; do
  v="$(getenv "$k")"
  [ -z "$v" ] && continue               # 空值已由 2.1 拦截，不重复报
  if printf '%s' "$v" | grep -qE "$PW_FATAL_RE"; then
    err "$k 含会破坏 URL 结构的字符（/ @ : # ? % 或空白）"
    err "  该密码会被裸拼进连接 URL（见本节注释），不做转义。"
    err "  修复：openssl rand -hex 32   然后更新 .env"
    if [ "$k" = "DATABASE_PASSWORD" ]; then
      err "  ⚠️ 改 DATABASE_PASSWORD 后必须重建数据卷才生效"
      err "     （POSTGRES_PASSWORD 只在卷为空时初始化一次）："
      err "       无数据：docker compose down -v"
      err "       有数据：先 pg_dump 导出，重建后再导入"
    fi
    FATAL=1
  elif ! printf '%s' "$v" | grep -qE "$PW_UNRESERVED_RE"; then
    warn "$k 含 RFC 3986 unreserved 之外的字符（如 + & = , ; ! \$ 等）"
    warn "  目前多数驱动能容忍，但不保证；建议换成 openssl rand -hex 32 生成的值"
  fi
done

# 2.6 通用兜底：空值 + 非 str 类型
#
# 前面 2.2 / 2.5 拦的是已知的具体坑。这一条是通用规则，config.py 以后新增
# Optional/List/int/bool 字段时自动覆盖，不用再回来加规则。
#
# 规则来源：.env 里的 «KEY=» 表示「值是空字符串」，不是「未设置」。
# 只有声明为 str 的字段能接受空串；其余类型都会在启动时解析失败：
#   List[...]  → SettingsError（json.loads 阶段，field_validator 来不及执行）
#   Optional[X]、int、bool → ValidationError
# 要表达「不设置」，必须把整行注释掉。
if [ -f app/core/config.py ]; then
  # 第一遍读 config.py 建「字段 → 声明类型」表，第二遍扫 .env 的空值键。
  # DATABASE_URL 已由 2.2 给出更具体的提示，这里跳过避免重复报错。
  EMPTY_BAD=$(awk '
    FNR==NR {
      if (match($0, /^[ \t]+[A-Z][A-Z0-9_]*[ \t]*:/)) {
        name = substr($0, 1, index($0, ":") - 1); gsub(/[ \t]/, "", name)
        rest = substr($0, index($0, ":") + 1)
        eq = index(rest, "=")
        if (eq > 0) rest = substr(rest, 1, eq - 1)
        gsub(/^[ \t]+|[ \t]+$/, "", rest)
        if (rest != "") type[name] = rest
      }
      next
    }
    /^[A-Z][A-Z0-9_]*=/ {
      key = substr($0, 1, index($0, "=") - 1)
      if (key == "DATABASE_URL") next
      t = type[key]
      if (t == "") next
      val = substr($0, index($0, "=") + 1)
      gsub(/^[ \t]+|[ \t\r]+$/, "", val)
      if (val == "") {
        if (t != "str" && t != "Optional[str]") printf "%s|%s|EMPTY\n", key, t
      } else if (t ~ /^(List|Set|Tuple)/) {
        # 复杂类型的值必须是合法 JSON。这里只做括号形状的近似判断 ——
        # 足以拦住 «ALLOWED_HOSTS=*» 和 «CORS=http://x,http://y» 这两类真实写法。
        if (val !~ /^\[.*\]$/) printf "%s|%s|NOTJSON\n", key, t
      } else if (t ~ /^Dict/) {
        if (val !~ /^\{.*\}$/) printf "%s|%s|NOTJSON\n", key, t
      }
    }
  ' app/core/config.py .env)

  if [ -n "$EMPTY_BAD" ]; then
    while IFS='|' read -r key typ reason; do
      [ -z "$key" ] && continue
      if [ "$reason" = "EMPTY" ]; then
        err "$key= 是空值，但 config.py 声明为 $typ —— 空字符串无法通过验证"
        case "$typ" in
          List*|Set*|Tuple*|Dict*)
            err "  要么整行注释掉，要么填合法 JSON，例如 [\"http://x\"] / [\"*\"]" ;;
          *)
            err "  «KEY=» 是空字符串而非未设置。请把整行注释掉以使用默认值。" ;;
        esac
      else
        err "$key 的值不是合法 JSON，但 config.py 声明为 $typ"
        err "  pydantic-settings 对复杂类型会先做 json.loads，裸值/逗号分隔都会失败："
        err "    正确：$key=[\"*\"]        错误：$key=*"
        err "    正确：$key=[\"http://a\",\"http://b\"]   错误：$key=http://a,http://b"
      fi
      FATAL=1
    done <<< "$EMPTY_BAD"
  fi
fi

[ "$FATAL" -eq 0 ] || { echo; err "配置校验未通过，已中止。"; exit 1; }
ok ".env 校验通过"

# 2.7 JWKS 连通性（非致命，但登录能否成功全看它）
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
# 4. 代码版本（只报告，不拉取）
#
# 拉代码由操作者显式执行（见文件头说明）。这里把「本次部署的到底是哪份代码」
# 打出来，因为构建用的是当前工作区内容 —— 工作区脏的话，镜像与仓库不一致。
# ------------------------------------------------------------
section "4/7 代码版本"

if [ "$DEPRECATED_NOPULL" -eq 1 ]; then
  warn "--no-pull 已无意义：脚本不再内置 git pull（保留该参数仅为兼容旧习惯）"
fi

if [ -d .git ]; then
  info "分支    : $(git rev-parse --abbrev-ref HEAD)"
  info "commit  : $(git log -1 --pretty='%h %s')"
  info "提交时间: $(git log -1 --pretty=%cd --date=iso)"
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    warn "工作区有未提交改动 —— 构建出的镜像与仓库内容不一致："
    git status --short --untracked-files=no | sed 's/^/         /'
  else
    ok "工作区干净"
  fi
else
  info "非 git 仓库，跳过版本信息"
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
