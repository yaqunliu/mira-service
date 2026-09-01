# Mira 部署计划（IP 直连版）

> 目标场景：**海外服务器 2C4G / 无域名 / IP + HTTP 访问 / 暂不接支付 / 给客户演示跑通全流程**
> 暂不安装 Caddy 或任何反向代理，等有域名后再单独加。
>
> 本文件用于跨步骤保存上下文 —— 每完成一个阶段就勾掉对应的 checkbox。

**服务器公网 IP：`45.130.164.189`**

---

## 0. 当前状态

### 已完成（本次部署之前）

- [x] **JWKS 验签改造**：删除 `app/services/supabase_service.py` 与 `app/core/security.py` 中两处硬编码的 EC 公钥（属于一个已删除的旧 Supabase 项目），新增 `app/core/jwks.py`，改为从 `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` 动态拉取公钥。支持 ES256 / RS256，进程内缓存 1 小时，kid 未命中自动刷新（密钥轮换无需重启）。已用自签密钥 + 本地模拟 JWKS 端点跑通 12/12 测试。
- [x] **前端硬编码地址修复**：`src/lib/utils/wait-for-supabase-token.ts` 里写死的 `https://niybedmvebmymaiivtjl.supabase.co`（该域名已 NXDOMAIN）改为读 `NEXT_PUBLIC_SUPABASE_URL`，并修掉 `includes('')` 恒真的隐藏 bug。

**由此带来的配置变化（写 .env 时注意）：**

| 变量 | 改造前 | 改造后 |
|---|---|---|
| `SUPABASE_URL` | 死配置，填什么都不影响 | **必须正确**，验签公钥从它推导 |
| `SUPABASE_JWT_SECRET` | 必填 | 云项目（ES256/RS256）**可留空**；仅本地 supabase CLI 的 HS256 才需要 |

### 决策（已确认）

- [x] **① 前端如何访问后端 → 方案 B：Next 同源代理**
      理由：后续加域名时前端不用动；不需要 curl / Swagger 直连调试。
- [x] **② 演示期关闭 celery beat → 关闭**
      其 6 个定时任务全是积分过期 / 订阅续费 / 订单轮询，不接支付时用不上，省约 300MB。
- [x] **③ 后端 Dockerfile 的 `uv.lock` / `start_celery_beat.sh` 缺失 → 本轮不动**
      等 IP 版跑通后再收拾，避免一次改太多不好定位问题。

---

## 0.5 方案 B 的两个连带问题（已查证，必须处理）

选了同源代理之后，多出两个原计划里没有的必修项。

### 🔴 A. Next 的 rewrites 是**构建时固化**的，`BACKEND_URL` 必须作为 build ARG 传入

已用最小 Next 应用实测验证：

- 以 `BACKEND_URL=http://BUILDTIME-VALUE:9999` 构建后，该值被写死进 `.next/routes-manifest.json`
- standalone 产物中**没有** `next.config.js`，`server.js` 里的配置是 JSON 内联的（函数无法序列化）
- 结论：**运行时设置 `BACKEND_URL` 完全无效**，必须在 `docker build` 阶段注入

因此前端 `Dockerfile` 的 builder 阶段要加：

```dockerfile
ARG BACKEND_URL
ENV BACKEND_URL=$BACKEND_URL
```

> 好消息：代理目标是容器内部地址 `http://mira-api:8100`，**加域名时它不变**，所以「后面加域名不想动前端」这个诉求仍然成立。

### 🔴 B. 有两个页面硬编码了 `http://localhost:8000` 兜底，方案 B 下会崩

```
src/app/[locale]/create-dynamic-comic/page.tsx:19
src/app/[locale]/dynamic-comic-editor/page.tsx:57

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
```

方案 B 下 `NEXT_PUBLIC_API_URL` 为空 → 这两个页面回落到 `http://localhost:8000` → 在**客户的浏览器**里指向客户自己的电脑 → 请求全失败。

必须把兜底值改成 `''`（空字符串 = 同源相对路径）。

其余调用点写法正确，无需改动：
- `src/lib/api/client.ts:14` — 空值时 `baseURL=''`，走同源 ✅
- `src/hooks/use-agent-chat.ts:545`、`src/lib/api/agent-api.ts:36` — 用的是 `|| ''` ✅

### 已核查通过的项

- 前端所有后端请求路径都在 `/api/v1/` 前缀下，正好被 rewrites 覆盖
- 没有 `EventSource` 或写死绝对地址的 `fetch` / `axios` 绕过代理
- 生成的图片/视频存在 US3（外部地址），不经过代理，无需额外处理

### 方案 B 带来的好处

- **不需要配 CORS**：浏览器只与 `:8001` 通信，后端调用是服务端到服务端
- 后端 `8100` 不必暴露公网，防火墙只需放行 `22 / 8001`

---

## 1. 硬约束：4GB 内存跑不动当前配置

各进程常驻内存粗估（本后端 import 了 langchain + chromadb，单进程基线偏高）：

| 进程 | 估算 |
|---|---|
| postgres 15 | 150–300 MB |
| redis | 30–80 MB |
| api (uvicorn) | 400–600 MB |
| **celery worker（现配置 `--concurrency=4` prefork）** | **1.5–2.5 GB** ⚠️ |
| celery beat | 250–350 MB |
| 前端容器（运行时） | 150–250 MB |

按现配置总量顶到 3.5–4GB 以上，加系统本身会触发 OOM killer。它通常先杀最大的进程（celery worker），现象是「任务莫名消失」，极难排查。

叠加问题：`next build` 峰值约 2GB，若在后端运行时构建前端几乎必炸。

**对策（已并入下面各阶段）：**

1. worker 并发 `4 → 2`
2. 关闭 celery beat（决策 ②）
3. 建 4GB swap
4. 构建前端时先停掉 celery worker

---

## 阶段 0：服务器准备

- [ ] 安装 Docker 及 compose 插件，确认 `docker compose version` 可用
      （注意是 `docker compose` 子命令，不是 v1 的 `docker-compose` 独立二进制）
- [ ] 创建 4GB swap 并设为开机生效
- [ ] 防火墙仅放行 **`22 / 8001`**（方案 B 下 8100 不对外）
- [ ] 创建共享网络：`docker network create mira-net`
- [ ] 确认两个仓库已 clone，记录路径：
      - 后端 `______________________`
      - 前端 `______________________`

**产出**：可直接粘贴执行的命令清单。

---

## 阶段 1：改后端 `docker-compose.yml`

| 项 | 现状 | 改为 |
|---|---|---|
| postgres 端口 | `5432:5432`（绑 0.0.0.0，公网可达） | `127.0.0.1:5432:5432` |
| redis 端口 | `6379:6379`（同上） | `127.0.0.1:6379:6379` |
| api 端口 | `8100:8100`（公网） | `127.0.0.1:8100:8100`（仅本机，可 SSH 隧道调试） |
| postgres 密码 / 库名 / 用户 | 硬编码 `password` 等 | `${DATABASE_PASSWORD:?}` 等，从 .env 读 |
| redis 密码 | 为空时无密码启动 | `${REDIS_PASSWORD:?}`，删掉无密码分支 |
| celery worker | `bash start_celery.sh`（写死 concurrency=4） | 直接用 celery 命令，`--concurrency=2` |
| celery beat | 启用 | 注释掉（决策 ②） |
| 共享网络 | 无 | 新增 external 网络 `mira-net`，api 挂上去并起别名 `mira-api` |
| 健康检查 | 无 | postgres / redis 加 healthcheck，api 与 worker 用 `depends_on: condition: service_healthy` |
| `version: '3.8'` | 已废弃字段 | 删除 |

**为什么用 `${DATABASE_PASSWORD:?}`**：`.env` 里没设密码时直接启动失败，而不是悄悄用弱密码起来。

**为什么绕开 `start_celery.sh`**：该脚本含 `read -p` 交互确认，容器无 TTY 时读到空值 → `exit 1` → 在 `restart: unless-stopped` 下进入重启循环。目前仅在检测到已有 worker 进程时触发（新容器检测不到，侥幸没爆），属隐患。改用 `celery` 命令还有个附带好处：不再执行 `uv run`，也就不会在挂载的宿主机目录里生成 `.venv`。

> 🔴 端口收内网是本阶段最重要的一项。当前配置等于把 `postgres/password` 的数据库和**可能无密码的 Redis** 直接挂在公网上 —— 在海外服务器上会被自动化扫描器很快打穿（无密码 Redis 是经典 RCE 入口）。

- [x] 完成改造，`docker compose config` 校验通过：
      - 三个端口均渲染为 `host_ip: 127.0.0.1`
      - 缺少 `REDIS_PASSWORD` 时按预期报错并拒绝启动
      - `mira_shared` 外部网络 + `mira-api` 别名就位
      - `celery_beat` 已从渲染结果中完全消失

---

## 阶段 2：后端 `.dockerignore`

实测仓库体积 **484MB**，其中 `.venv` 456MB、`.git` 14MB、`documents/` 3.8MB —— 占 97%，
在没有 `.dockerignore` 的情况下全部会被发给 Docker daemon。

- [x] 新建 `.dockerignore`，构建上下文降到 10MB 量级

**两个排除时必须避开的坑（已核查）：**

1. **`README.md` 不能被 `*.md` 连带排除** —— `Dockerfile:24` 有 `COPY README.md ./`，
   排除了会导致构建直接失败。用 `*.md` 后紧跟 `!README.md` 放行（顺序不可颠倒）。
2. **`docs/` 不能排除** —— `app/agent/tools/voice_selection_tools.py:22,24` 运行时读
   `docs/finalfish.json` 与 `docs/FISH_AUDIO_VOICES_REAL.json`（音色选择，在演示链路上）。
   `documents/` 无任何代码引用，可以安全排除。

另外 `uv.lock` 也保留未排除，供将来 Dockerfile 补 `COPY uv.lock` 时使用。

**验证**：本机 Docker daemon 未运行，无法跑真实 build。改用脚本按 Docker 的匹配语义
（逐条匹配、后匹配者胜、`!` 为例外）对 15 条必须保留路径 + 13 条应排除路径做判定，全部符合预期。
**真实 build 验证留到阶段 4 在服务器上做** —— 若 `.dockerignore` 有误，第一次 `docker compose build`
会立即报 COPY 失败，很好定位。

> 顺带发现：`docs/` 同样没有被 Dockerfile COPY，目前也是靠 `./:/app` 挂载兜住的。
> 已补进下方「已知问题清单」。

---

## 阶段 3：后端 `.env` 模板 + 部署脚本

### 3.1 `.env` 模板

> 关于行尾注释：`env.example` 里有 13 个键写成 `REDIS_URL=redis://...  # 说明文字` 这种形式。
> 已用 `docker compose config` 实测确认 **Compose v2 会正确剥离行尾注释**
> （`ACCESS_TOKEN_EXPIRE_MINUTES` 渲染为 `"1440"` 而非带注释的字符串），
> 因此这不构成问题，无需专门清理。新增条目仍建议注释单独占行。

### 3.0 现有 `.env` 已发现的问题（部署前必须修）

对本机 `.env`（81 个键）的体检结果 —— 它是从 `env.example` 复制的**本地开发**配置，
直接拿去 Docker 部署会有 5 处失败：

| # | 键 | 当前值 | 必须改为 | 不改的后果 |
|---|---|---|---|---|
| 1 | `SUPABASE_URL` | `https://hiorjudyyaemiimpwzgd.supabase.co/rest/v1/` | `https://hiorjudyyaemiimpwzgd.supabase.co` | 🔴 **所有人登不进去** |
| 2 | `DATABASE_HOST` | `localhost` | `postgres` | 🔴 连不上数据库 |
| 3 | `REDIS_URL` / `REDIS_BROKER_URL` / `REDIS_BACKEND_URL` | `redis://localhost:6379/N` | `redis://redis:6379/N` | 🔴 Celery 任务全不执行 |
| 4 | `REDIS_PASSWORD` | 空 | 强密码 | 🔴 compose `:?` 直接拒绝启动 |
| 5 | `DEBUG` | `True` | `False` | 🟡 会开放 `/points/test/add-points` |
| 6 | `DATABASE_URL` | `=`（空值） | **整行注释掉** | 🔴 `Optional[PostgresDsn]` 解析空串失败，启动即崩 |
| 7 | `BACKEND_CORS_ORIGINS` | `=`（空值） | **整行注释掉** | 🔴 `List` 类型先做 `json.loads`，空串非法 JSON |
| 8 | `ALLOWED_HOSTS` | `*` | `["*"]` | 🔴 同上，裸值非法 JSON |
| 9 | 两个密码 | `openssl rand -base64` 生成 | `openssl rand -hex 32` | 🔴 `/` 截断连接 URL；Redis 侧还是静默失败 |

> **6-9 是实际部署时新踩到的**，`env.docker.example` / `deploy.sh` / `config.py` 均已修。
> 统一的认知：`.env` 里 `KEY=` 是「空字符串」而非「未设置」——
> 只有声明为 `str` 的字段能接受空串，`Optional[X]` / `List[X]` / `int` / `bool` 都会解析失败。
> `deploy.sh` 的 2.6 已加通用兜底检查，`config.py` 以后新增此类字段会被自动覆盖。

**#1 的细节**：多带了 `/rest/v1/` 后缀（那是 Data API 地址，不是 Project URL）。已实测：

```
错误值拼出 → .../rest/v1/auth/v1/.well-known/jwks.json  → HTTP 401
正确值拼出 → .../auth/v1/.well-known/jwks.json          → HTTP 200 ✅
```

正确地址返回的是 **ES256** 密钥（kid `423d5c6e-…`）—— 印证了该项目使用非对称签名，
正是旧硬编码公钥必然失败、而本次 JWKS 改造所解决的场景。
同时也确认 **`SUPABASE_JWT_SECRET` 可以留空**。

> 注意：`SUPABASE_URL` 在 JWKS 改造前是死配置，填错也看不出来；改造后它承载验签公钥的获取，
> 填错的表现是「注册登录都提示失败，后端日志报 JWKS 获取失败」。

**#2/#3 的原因**：Docker 里 `localhost` 指容器自身，必须用 compose 的服务名 `postgres` / `redis`。
（`REDIS_PASSWORD` 设好后，代码里的 `assemble_redis_urls` 会自动把密码拼进这三个 URL，但主机名要自己改对。）

- [ ] 按上表修正 `.env`

**必填（不填起不来）**
```
DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_USER=<自定义>
DATABASE_PASSWORD=<强密码>
DATABASE_NAME=video_generator
REDIS_PASSWORD=<强密码>
REDIS_URL=redis://redis:6379/0
REDIS_BROKER_URL=redis://redis:6379/0
REDIS_BACKEND_URL=redis://redis:6379/1
```
（Redis 密码会由代码根据 `REDIS_PASSWORD` 自动拼进这三个 URL）

**必填（不填登不进去）**
```
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<anon public key>
SUPABASE_JWT_SECRET=
```

**CORS / DEBUG**
```
DEBUG=False
# BACKEND_CORS_ORIGINS=["http://example.com"]
ALLOWED_HOSTS=["*"]
```

> 🔴 **实际部署时踩到的坑（已修，记录原因）**：这两个字段声明为
> `List[AnyHttpUrl]` / `List[str]`（`config.py:20-21`），pydantic-settings 对复杂类型
> 会**先做 `json.loads`**，因此：
>
> | 写法 | 结果 |
> |---|---|
> | `BACKEND_CORS_ORIGINS=` | 🔴 空串非法 JSON → `SettingsError`，启动失败 |
> | `ALLOWED_HOSTS=*` | 🔴 裸值非法 JSON → 同上 |
> | `BACKEND_CORS_ORIGINS=http://a,http://b` | 🔴 逗号分隔也非法 JSON → 同上 |
> | 整行注释掉 | ✅ 用类定义的默认值 |
> | `ALLOWED_HOSTS=["*"]` | ✅ |
>
> 关键认知：**`.env` 里的 `KEY=` 表示「值是空字符串」，不是「未设置」。**
> 要表达「不设置」必须整行注释。`config.py:23` 那个 `mode="before"` 的
> field_validator 是按 pydantic v1 语义写的，在 v2 下对环境变量输入已失效
> （报错发生在配置源层，validator 来不及执行）。
>
> `ALLOWED_HOSTS` 保持 `["*"]`：方案 B 下后端收到的 `Host` 是 `mira-api:8100`，
> 公网 IP 它看不到，收紧成公网地址会把所有请求拦掉。

方案 B 下浏览器只与前端同源通信，**不需要配 CORS**（注释掉即可）。
若将来改回方案 A 直连，必须填成 **JSON 数组** `["http://45.130.164.189:8001"]`——
否则 `DEBUG=False` + 未配置时 `app/main.py` 根本不装载 CORS 中间件，
只打一句 `UserWarning`，浏览器侧全被拦却查不出原因。

`DEBUG` 保持 `False`：设为 `True` 会额外开放 `/points/test/add-points`（可给任意用户加积分）。
注册自动送 10000 积分，演示够用。

**要"出片"才需要的**
```
OPENAI_API_KEY / OPENAI_BASE_URL      # LLM：角色/场景/分镜/剧本解析
ARK_API_KEY / ARK_BASE_URL            # 火山方舟：文生图 Seedream、视频 Seedance
FISH_AUDIO_API_KEY                    # TTS 配音
US3_PUBLIC_KEY / US3_PRIVATE_KEY / US3_BUCKET / DOWNLOAD_SUFFIX / UPLOAD_SUFFIX
                                      # 对象存储 —— 缺了生成物无处存放，流程会断
```

**省钱开关（仅演示界面和流程、不烧 API 费用时打开）**
```
DEBUG_GENERATE_IMAGE=True
DEBUG_GENERATE_VIDEO=True
```

- [x] 产出 `env.docker.example`（另建一份，不改动现有 `.env`）
      服务器上执行 `cp env.docker.example .env` 后逐项填写。
      模板中 `REDIS_PASSWORD` / `DATABASE_PASSWORD` 留空，在服务器上用
      **`openssl rand -hex 32`** 生成。
      > ⚠️ 不要用 `openssl rand -base64` —— 字符集含 `/` `+` `=`，密码里的 `/`
      > 会截断连接 URL 的 authority，导致 `invalid port number`（数据库侧启动即崩），
      > 或 Redis 侧静默连不上（`REDIS_URL` 声明为 `str` 不做校验，
      > 表现为「worker 日志 ready 但任务永不执行」）。
      > `config.py` 现已对密码做 percent-encode（`_urlsafe()`），但 `-hex` 更省事。

### 3.2 部署脚本 `deploy.sh`

幂等、可重复执行：

```
校验 .env 存在且关键项非空
  → 校验 mira-net 网络存在
  → git pull
  → docker compose build
  → docker compose up -d
  → 等待 postgres healthy
  → alembic upgrade head
  → 容器内 curl /health 健康检查
  → 打印各容器状态
```

> 现有的 `migrate-docker.sh` **在新版 Docker 上跑不起来** —— 它用的是 v1 的 `docker-compose ps` / `docker-compose exec` 命令，新版 Docker 只有 `docker compose` 子命令。迁移这步直接并进 `deploy.sh`，旧脚本不再使用。

- [x] 产出 `deploy.sh`（已 `chmod +x`，`bash -n` 语法通过）

支持 `--no-pull` / `--no-build` / `--skip-migrate` 三个开关，幂等可重复执行。

**内置的 5 类配置校验**（都对应「不拦住就会在启动后才暴露、且报错极具误导性」的坑）：

1. 必填项非空
2. `DATABASE_URL` 必须为空，否则会覆盖 `DATABASE_HOST`
3. `DATABASE_HOST` / `REDIS_*` 不得指向 `localhost`
4. `SUPABASE_URL` 不得带 `/rest/v1` 等路径后缀
5. 实际请求一次 JWKS 端点，非 200 时告警（非致命）

**实测结果**：用当前 `.env` 的错误形态跑，5 类问题全部被拦下并中止；
改成正确配置后校验通过，且 JWKS 探测返回 200。

**两个实现细节**：
- 健康检查用 `python -c` 而非 `curl` —— 镜像里只装了 `gcc/g++/ffmpeg/fonts-wqy-zenhei`，**没有 curl**
- 读取 `.env` 用 `grep` 提取而非 `source`，避免 `.env` 内容被当成命令执行

---

## 阶段 4：后端启动 + 验证

- [ ] `docker compose up -d`
- [ ] `alembic upgrade head`
      （已确认：53 个迁移，单根单 head，无分叉，可直接 upgrade）
- [ ] `docker compose exec api curl -s localhost:8100/health` → `{"status":"healthy"}`
      （8100 不对外，从容器内或 SSH 隧道验证）
- [ ] `docker compose logs -f celery_worker` → 确认 worker ready、无重启循环
- [ ] `free -h` / `docker stats` 看真实占用，必要时把 `--concurrency` 再降到 1

> **这一步是分水岭，后端不通不要往下走。**

---

## 阶段 5：前端

### 5.1 代码改动（本机已完成）

- [x] `package.json` 增加 `"packageManager": "pnpm@10.25.0"`
      理由：Dockerfile 用了 `corepack enable`，但原先没有 `packageManager` 字段；lockfile 是
      `lockfileVersion: '9.0'` 需 pnpm 9+。若 corepack 解析到 pnpm 8，`--frozen-lockfile` 直接构建失败。
- [x] **修两个硬编码兜底页面**（见 0.5 节 B）：`|| 'http://localhost:8000'` → `|| ''`
      - `src/app/[locale]/create-dynamic-comic/page.tsx:19`
      - `src/app/[locale]/dynamic-comic-editor/page.tsx:57`
      已确认这两页的请求全部形如 `${API_BASE_URL}/api/v1/...`，正好落在 rewrites 覆盖范围内。
- [x] `Dockerfile`：builder 阶段加 `ARG/ENV BACKEND_URL`（默认 `http://mira-api:8100`），
      并把 `NEXT_PUBLIC_API_URL` 的死域名默认值改为空串
- [x] `docker-compose.yml` 重写：
      - 接入 external 网络 `mira_shared` → `mira-net`
      - build args 增加 `BACKEND_URL`
      - `NEXT_PUBLIC_API_URL` **写死空串**（不再从环境变量取 —— `${VAR:-default}` 在变量为
        空字符串时仍回落到默认值，这个坑绕不过去，只能写死）
      - Supabase 两个变量改 `:?`，缺失时构建直接失败
      - **顺手修掉一个端口错配隐患**：原 `PORT: ${PORT:-8001}` 配合 `ports "${PORT}:8001"`，
        一旦 `PORT=9000`，容器会监听 9000 而端口映射目标仍是 8001。现改为容器内固定 8001，
        `PORT` 只控制宿主机端口。
- [x] `.env.docker.example` 重写为方案 B 版本
- [x] **改名 `.env.docker` → `.env`**（模板同步改名为 `.env.example`）
      理由：compose 默认只读 `.env` 做插值，文件叫 `.env.docker` 时**每一条** compose
      命令都得带 `--env-file .env.docker`（不只是 `up`，`ps` / `logs` / `exec` / `restart`
      全都要，因为任何子命令都要先完整插值 compose 文件）。实际部署时就漏在了
      `exec` 上，报 `required variable NEXT_PUBLIC_SUPABASE_URL is missing a value`。
      改名后前端命令与后端完全一致，`docker compose ps` 直接可用。
      安全性已核查：`.dockerignore:15-16` 是 `.env*` + `!.env.example`，所以 `.env`
      不进构建上下文，`next build` 也读不到它，不存在与 build args 冲突或密钥进镜像；
      `.gitignore:35-36` 同为 `.env*` + `!.env*.example`，`.env` 不会被提交。
- [x] 新增前端 `deploy.sh`（不内置 `git pull`，见下）

**验证**：`docker compose config` 渲染正确（`BACKEND_URL: http://mira-api:8100`、
`NEXT_PUBLIC_API_URL: ""`、`mira-net` external、容器端口固定 8001）；缺 Supabase 变量时按预期拒绝；
`tsc --noEmit` 错误数 74，与改动前基线一致，无新增。

### 5.2 服务器上执行

首次：

```bash
cd <FE>
cp .env.example .env
vi .env                    # 填 NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY
                           # 必须与后端 .env 的 SUPABASE_* 是同一个项目
./deploy.sh
```

以后每次改了前端：

```bash
cd <FE> && git pull origin master && ./deploy.sh
```

`deploy.sh` 做的事（6 段）：

| 段 | 内容 |
|---|---|
| 1 | docker / compose v2 / daemon 可用性 |
| 2 | `.env` 校验：两个 Supabase 值非空、URL 无路径后缀、**与后端 `.env` 项目一致性核对** |
| 3 | `mira-net` 网络存在（不存在则创建）+ 打印当前 commit、工作区是否干净 |
| 4 | 打印内存 → 停掉后端 `celery_worker` 腾内存（`trap EXIT` 保证异常退出也恢复） |
| 5 | `docker compose up -d --build` |
| 6 | 容器 running → `BACKEND_URL` 固化检查 → 前端→后端连通 → 同源代理生效判定 |

参数：`--no-build`（只重启）、`--keep-worker`（不动 worker）。
后端路径默认取 `../mira-service`，否则 `/opt/mira-service`，可用 `BACKEND_DIR=/path` 覆盖。

**为什么不内置 `git pull`**：bash 是边读边执行的（分块读取），脚本内部的 `git pull` 若更新了
`deploy.sh` 自身，正在运行的 shell 会读到新旧混杂内容，表现为中途莫名语法错误或静默跳步。
显式两步还能让「本次部署了哪些 commit」直接呈现，而不是混在部署日志中被忽略。
后端 `deploy.sh` 同步移除了内置 `git pull`（原第 4 段改为只报告代码版本）。

**为什么 worker 恢复必须挂 `trap EXIT`**：构建失败时脚本会退出，若恢复动作写在末尾就不会执行。
那样你在排查构建问题的同时，后端任务正在静默地不执行 —— 极易被误判成两个不相干的故障。
脚本还会记录 worker 原本是否在运行，本来就停着的话结束时不会擅自启动它。

> 🔴 **本阶段最容易踩的坑**：`NEXT_PUBLIC_*` 和 `BACKEND_URL` 都是 **构建时** 固化的，不是运行时读取。
> 改了任何一个之后，**必须 `--build` 重新构建**，光重启容器无效。
> 前端**没有** bind mount（对比后端的 `./:/app`），所以改前端代码同样必须重新构建 ——
> 这是前后端部署方式最主要的差异：后端 `git pull` + `restart` 即可，前端必须 `--build`。

**同源代理的验证方法**（`deploy.sh` 6.4 已自动做）：请求一个不存在的 `/api/v1/xxx`，看 content-type。
两种情况 HTTP 状态码都是 404，只有 content-type 能区分请求有没有出前端容器：

| content-type | 含义 |
|---|---|
| `application/json` | ✅ FastAPI 返回的 404，代理生效 |
| `text/html` | ❌ Next 自己的 404 页面，rewrites 未生效 |

---

## 阶段 6：Supabase 配置 + 端到端验证

### Supabase 控制台

- [ ] Site URL：`http://45.130.164.189:8001`
- [ ] Redirect URLs：`http://45.130.164.189:8001/**`
- [ ] Authentication → Providers → Email → **关闭 Confirm email**（演示不值得配 SMTP）
- [ ] **不配 Google 登录** —— Google OAuth 的回调地址基本不接受 `http://` + IP 的组合，配了也回跳不回来。演示只用邮箱密码登录。
- [ ] 记下 Project URL / anon key，填进前后端配置

> 免费项目闲置约一周会自动暂停，**客户演示前一天记得去控制台确认项目没睡着**。

### 端到端验证

- [ ] 打开 `http://45.130.164.189:8001`
- [ ] 注册新账号 → 自动同步建本地用户 + 送 10000 积分
- [ ] 登录后刷新页面，session 保持（验证 JWKS 验签走通）
- [ ] 浏览器 Network 面板确认 `/api/v1/*` 请求发往 `45.130.164.189:8001`（同源），且返回 200
- [ ] 上传小说 → 触发一次生成
- [ ] `docker compose logs -f celery_worker` 跟踪任务执行
- [ ] 确认生成物能正常存到 US3 并在前端展示

---

## 已知问题清单（本轮不修，记录备查）

| 问题 | 位置 | 影响 | 处理时机 |
|---|---|---|---|
| Dockerfile 未 `COPY uv.lock` | `Dockerfile:20` | 构建不锁依赖版本，可能漂移 | 决策 ③，IP 版跑通后 |
| Dockerfile 未 `COPY start_celery_beat.sh` | `Dockerfile:25-26` | 镜像不完整，现靠 bind mount 兜住 | 同上 |
| Dockerfile 未 `COPY docs/` | `Dockerfile:20-26` | 音色选择的数据文件不在镜像里，现靠 bind mount 兜住 | 同上 |
| `./:/app` 全量挂载 | `docker-compose.yml` | 容器实际跑宿主机代码，镜像形同虚设 | 同上 |
| `migrate-docker.sh` 用 v1 命令 | 全文件 | 在新 Docker 上直接失败 | 已被 `deploy.sh` 取代 |
| ~~密码未 URL 编码~~ | `config.py:42-49` / `:79` | ~~含 `/` 的密码破坏连接 URL~~ | ✅ 已修：新增 `_urlsafe()` |
| `assemble_cors_origins` 是死代码 | `config.py:23-30` | `mode="before"` 在 pydantic v2 下收不到环境变量原值（报错发生在配置源层），逗号分隔语法实际不可用 | 低优先，删掉或改用 `NoDecode` 注解 |
| `README.md` 引用的 `DEPLOYMENT.md` 不存在 | 前端 README | 文档断链 | 低优先 |
| `waitForSupabaseToken` 是死函数 | 前端 utils | 无人调用 | 低优先 |
| 前端 74 条既有 TS 类型错误 | 全项目 | 被 `ignoreBuildErrors: true` 绕过 | 低优先 |
| `ENV` 变量在 Python 代码中完全未使用 | `config.py` | 无 | 低优先 |
| `SECRET_KEY` / `ALGORITHM` 为遗留死配置 | `config.py` / `security.py` | 认证已全走 Supabase，可留空 | 低优先 |

---

## 附录：服务器执行手册

以下命令在服务器上按顺序执行。`<BE>` = 后端仓库路径，`<FE>` = 前端仓库路径。

### A. 一次性准备

```bash
# 1. 确认 Docker（必须是 compose v2 子命令）
docker --version && docker compose version

# 2. 建 4GB swap（2C4G 机器上是前端构建和内存尖峰的保命绳）
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h

# 3. 防火墙：只放行 SSH 与前端端口
#    后端 8100 走容器内部网络，不需要对外
sudo ufw allow 22/tcp && sudo ufw allow 8001/tcp
sudo ufw enable && sudo ufw status

# 4. 创建前后端共享网络
docker network create mira-net
```

### B. 后端

```bash
cd <BE>
git pull origin master

cp env.docker.example .env

# 生成两个强密码填进 .env 的 DATABASE_PASSWORD / REDIS_PASSWORD
# 必须用 -hex：-base64 的字符集含 / + = ，"/" 会破坏连接 URL
openssl rand -hex 32
openssl rand -hex 32

vi .env
#   必填：DATABASE_PASSWORD / REDIS_PASSWORD
#         SUPABASE_URL（Project URL，不带 /rest/v1）/ SUPABASE_ANON_KEY
#   出片还需要：OPENAI_API_KEY / OPENAI_BASE_URL / FISH_AUDIO_API_KEY / US3_*
#   先跑通链路建议保留 DEBUG_GENERATE_IMAGE=True / DEBUG_GENERATE_VIDEO=True

./deploy.sh
```

`deploy.sh` 会自己校验配置、建网络、构建、启动、等就绪、跑迁移、健康检查。
配置有问题会在构建前就中止并说明原因。

### C. 前端

```bash
cd <FE>
git pull origin master

cp .env.example .env
vi .env      # 填 NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY
             # 必须与后端 .env 是同一个 Supabase 项目（deploy.sh 会自动核对）

./deploy.sh

docker compose logs -f mira-fe
```

`deploy.sh` 已经把「停 worker → 构建 → 恢复 worker → 验证代理」全包了，
worker 的停/恢复不用手动管（恢复挂在 `trap EXIT`，构建失败也会执行）。

### D. 验证

```bash
# 后端健康（8100 不对外，从容器内查）
cd <BE> && docker compose exec -T api python -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8100/health').read().decode())"

# 前端能否通过共享网络访问后端 —— 这是方案 B 的关键链路
cd <FE> && docker compose exec mira-fe node -e \
  "fetch('http://mira-api:8100/health').then(r=>r.text()).then(console.log).catch(e=>console.error('FAIL',e.message))"

# 内存占用（关注总量是否接近 4G）
docker stats --no-stream

# 浏览器打开
#   http://45.130.164.189:8001
```

浏览器里重点看 Network 面板：`/api/v1/*` 请求应发往 `45.130.164.189:8001`（同源）
并返回 200 —— 若发往别的地址，说明 `NEXT_PUBLIC_API_URL` 没有正确置空，需重新 `--build`。

### E. 常用运维

```bash
cd <BE>
docker compose logs -f api
docker compose logs -f celery_worker
docker compose ps
./deploy.sh --no-pull --no-build     # 只重启并重跑迁移
./deploy.sh --skip-migrate           # 跳过迁移

# 内存吃紧时把并发降到 1：编辑 docker-compose.yml 的 --concurrency=2 → 1
docker compose up -d celery_worker

# 需要临时调后端接口时开隧道，本地即可访问 Swagger
# ssh -L 8100:127.0.0.1:8100 <user>@45.130.164.189
# 然后本地浏览器打开 http://localhost:8100/docs
```

---

## 加域名后要做的事（下一轮）

1. 装 Caddy（自动申请续期证书），代理 `前端域名 → :8001`
2. Supabase：Site URL / Redirect URLs 换成 HTTPS 域名；此时才可以配 Google OAuth
3. **前端无需重新构建** —— 方案 B 下代理目标是容器内地址 `http://mira-api:8100`，与对外域名无关
4. Supabase 升级 Pro（免费项目会自动暂停，不能用于正式环境）
5. 配自定义 SMTP，重新打开 Confirm email
6. 回头处理「已知问题清单」里决策 ③ 的三项
