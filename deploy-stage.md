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
BACKEND_CORS_ORIGINS=
```
方案 B 下浏览器只与前端同源通信，**不需要配 CORS**，留空即可。
（若将来改回方案 A 直连，必须填 `http://45.130.164.189:8001`，否则 `DEBUG=False` + 空值时
`app/main.py` 根本不装载 CORS 中间件，只打一句 `UserWarning`，浏览器侧全被拦却查不出原因。）

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
      `openssl rand -base64 24` 生成。

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

- [ ] `package.json` 增加 `"packageManager": "pnpm@10.25.0"`
      理由：Dockerfile 用了 `corepack enable`，但 `package.json` 无 `packageManager` 字段；lockfile 是 `lockfileVersion: '9.0'`，需 pnpm 9+。若 corepack 解析到 pnpm 8，`--frozen-lockfile` 会直接构建失败。
- [ ] **修两个硬编码兜底页面**（见 0.5 节 B）：`|| 'http://localhost:8000'` → `|| ''`
- [ ] `Dockerfile` builder 阶段加 `ARG BACKEND_URL` / `ENV BACKEND_URL`（见 0.5 节 A）
- [ ] `docker-compose.yml`：
      - 加入 external 网络 `mira-net`
      - build args 增加 `BACKEND_URL=http://mira-api:8100`
      - **`NEXT_PUBLIC_API_URL` 显式置空并删掉那个默认值**
        （现值 `${NEXT_PUBLIC_API_URL:-https://api-creator.mira-studio.ai}` 是 `:-` 形式，
        把变量设成空字符串仍会回落到默认值，而该域名已确认 NXDOMAIN）
      - Supabase 两个变量改用 `:?` 形式，缺失时构建直接失败，避免把 `undefined` 烘进产物
- [ ] 写 `.env.docker`：
      ```
      PORT=8001
      NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
      NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>
      ```
- [ ] **构建前先停掉 celery worker 腾内存**：后端目录 `docker compose stop celery_worker`
- [ ] `docker compose --env-file .env.docker up -d --build`
- [ ] 构建完成后恢复 worker：`docker compose start celery_worker`

> 🔴 **本阶段最容易踩的坑**：`NEXT_PUBLIC_*` 和 `BACKEND_URL` 都是 **构建时** 固化的，不是运行时读取。
> 改了任何一个之后，**必须 `--build` 重新构建**，光重启容器无效。

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
| `README.md` 引用的 `DEPLOYMENT.md` 不存在 | 前端 README | 文档断链 | 低优先 |
| `waitForSupabaseToken` 是死函数 | 前端 utils | 无人调用 | 低优先 |
| 前端 74 条既有 TS 类型错误 | 全项目 | 被 `ignoreBuildErrors: true` 绕过 | 低优先 |
| `ENV` 变量在 Python 代码中完全未使用 | `config.py` | 无 | 低优先 |
| `SECRET_KEY` / `ALGORITHM` 为遗留死配置 | `config.py` / `security.py` | 认证已全走 Supabase，可留空 | 低优先 |

---

## 加域名后要做的事（下一轮）

1. 装 Caddy（自动申请续期证书），代理 `前端域名 → :8001`
2. Supabase：Site URL / Redirect URLs 换成 HTTPS 域名；此时才可以配 Google OAuth
3. **前端无需重新构建** —— 方案 B 下代理目标是容器内地址 `http://mira-api:8100`，与对外域名无关
4. Supabase 升级 Pro（免费项目会自动暂停，不能用于正式环境）
5. 配自定义 SMTP，重新打开 Confirm email
6. 回头处理「已知问题清单」里决策 ③ 的三项
