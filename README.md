# 选购助手

源码仓库：[Yrong-z/Agent-E-commerce](https://github.com/Yrong-z/Agent-E-commerce)。本项目提供本地运行与部署步骤，仓库发布不代表公网服务上线。项目当前暂不添加自身许可证，第三方技能及依赖的许可声明保持原样。

单机电商导购与已有订单演示：React + TypeScript + Vite、自定义CSS；Python + FastAPI + Pydantic；PostgreSQL + pgvector。单Agent使用原生Tool Calling，聊天与embedding独立配置。商品、订单和政策均为合成演示数据，MockCommerceAdapter实际读取数据库。

当前可完成导购、已有订单查询、政策问答与模拟售后。首次使用请按下文准备环境并初始化数据，日常使用从 [用户操作手册](docs/USER_GUIDE.md) 开始。真实验收范围、失败历史和未验证项集中在 [验收与发布](docs/ACCEPTANCE_AND_RELEASE.md)。

## 文档导航

| 文档 | 中文用途 |
|---|---|
| [README](README.md) | 项目介绍、实际能力、环境准备、安装配置、快速开始和开发者命令 |
| [用户操作手册](docs/USER_GUIDE.md) | 启停、四页操作、完整演示与常见问题 |
| [架构](docs/ARCHITECTURE.md) | 实际分层、主要入口与数据流 |
| [契约](docs/CONTRACTS.md) | HTTP 接口、工具、字段与错误约定 |
| [协作规则](AGENTS.md) | 后续开发与维护规则 |
| [验收与发布](docs/ACCEPTANCE_AND_RELEASE.md) | 实际证据、验证限制和发布核对 |
| [精选证据](docs/evidence/README.md) | 真实脱敏截图、评测与 MCP 摘要及证据日期 |
| [数据说明](data/README.md)、[政策资料](data/knowledge/README.md)、[商品资源](web/public/products/README.md) | 合成数据、政策与图片的来源和边界 |

## 实际能力

| 能力 | 实现与验证状态 | 边界 |
|---|---|---|
| 原生Tool Calling、多轮会话 | 已实现且在有限案例中验证 | 八工具；最新候选指代、条件修改、任务切换、保存/恢复；单进程 |
| 会话管理 | 已实现且专项验证 | 最近20条侧栏、分页历史、单条/多选/全部删除；仅当前顾客聊天状态，业务记录保留 |
| 商品搜索、详情、两款比较、订单与物流 | 已实现且已验证 | 12个合成SKU/3个已有演示订单；商品文字包含查询，预算按到手价，订单金额为历史快照 |
| PostgreSQL/pgvector、本地真实embedding RAG | 已实现且有限验证 | TEI+BGE真实1024维，三文档三片段、可追溯引用、无证据和故障恢复；0.50下限不是通用准确率 |
| 模拟售后 | 已实现且已验证 | 具体原因/资格/10分钟预览；用户显式按钮确认，重复确认同申请；聊天不能提交；不执行退款 |
| trace/运行记录、只读管理快照 | 已实现且已验证 | 实际时间/工具/结果/耗时/RAG来源；打开管理不调用聊天模型，未知保持未知 |
| 官方Python SDK MCP Server | 已实现且有限协议验证 | stdio，只有search_products/get_order两个只读工具；主聊天仍直接调用八工具 |
| CLI二十案例评测 | 已实现且已验证 | 12确定性+8在线；程序断言和直接语义审阅，保留首次失败及选择性重跑 |
| 评测/能力HTTP接口、评价摘要签名 | 仅预留接口 | 两个HTTP入口明确501；CLI及本能力表不等于实现这些接口 |
| 真实交易、购物车、支付、企业接入、远程MCP/认证、多Agent调度 | 本项目未实现 | 不声称生产部署或企业规模能力 |

## 环境前提

现有环境实际验证：Python 3.12.14、Node 24.19.0、pnpm 11.19.0；FastAPI 0.142.2、Pydantic 2.13.5、uvicorn 0.54.0；React 19.3.0、TypeScript 5.9.3、Vite 7.3.6；PostgreSQL 17.11、pgvector 0.8.7、psycopg 3.3.6、MCP SDK 1.30.0。

准备Python 3.12或3.13、Node 22.12以上及pnpm 11.19、Docker Desktop的Linux容器引擎。后端使用api/requirements.lock，前端使用web/pnpm-lock.yaml；冻结安装，不自行升级。首次需联网安装依赖、取得数据库/TEI镜像，在线聊天需要支持原生tools的Chat Completions接口和有效配置。下面启动脚本面向Windows PowerShell；其他系统未做启停脚本验收。

本地CPU embedding不需要GPU。已有完整BGE目录约1.30GB；本次空闲快照TEI约1.29GiB、数据库约38MiB，仅为一次观察，不是最低内存或负载容量保证。为Docker预留至少4GiB、宿主8GiB及数GB依赖/镜像/模型空间是准备估算，实际需求受负载影响，本轮没有资源压力测试。

## 首次安装与配置

Windows 首次使用按“准备模型/镜像与 `.env` → 双击 `setup.cmd` → 双击 `start.cmd`”执行；日常双击 `start.cmd`，结束时双击 `stop.cmd`。三个入口都按自身位置定位项目，目录可以包含空格，失败显示具体提示且保留非零退出码。

日常使用双击根目录 `start.cmd`，默认进行**本地部署**：检查运行时与 Docker、按锁文件补缺依赖、保留已有 `.env`、检查只读模型目录、启动数据库/embedding、按空库状态初始化、构建前端，再启动 FastAPI 单进程托管生产页面。健康与页面检查通过后自动打开 [本地部署页面](http://127.0.0.1:8000)。这不代表公网上线。

模型和镜像须事先准备，脚本不会猜密钥、下载大模型或拉取镜像。聊天配置不完整只禁用聊天，手动功能仍可用；模型目录/镜像/数据库等启动前提缺失会明确中断。缺 `.env` 时从样例生成，已有文件不覆盖。首次自动准备与环境限制见[本地部署验收](docs/ACCEPTANCE_AND_RELEASE.md#本地部署与启停专项验收2026-10-04)。

以下PowerShell命令从项目根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Action Install
```

`Install` 只准备依赖与样例配置，不能代替完整部署准备。首次没有 `.env` 可先双击 `setup.cmd`，依赖检查后会生成样例，再按缺项提示填写配置并重试；已有配置不覆盖。`Setup` 还检查模型、Docker/本地镜像、端口并构建前端，聊天配置缺项时不报告准备成功；不启动数据库、embedding 或应用，不初始化数据、不打开浏览器。首次业务/知识空库初始化仍由 `start.cmd` 调用已有实现。准备完成不代表模型接口已联网验证。

Install创建根目录.venv、按锁文件补齐依赖。Python实际安装版本及前端已安装锁文件一致时跳过安装，不每次重装。若找不到已有运行时，可从根目录运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Action Setup -Mode Deployment` 并指定-PythonPath、-NodePath、-PnpmCli参数；例如分别传入自己安装的python.exe、node.exe、pnpm.cjs完整路径。定位保存在忽略的.runtime/runtime.json，只调整子进程PATH，不修改系统PATH或全局执行策略。

编辑根目录.env（不提交、不发送到聊天）：

| 配置 | 用途/示例 |
|---|---|
| DATABASE_URL | 与POSTGRES_USER/PASSWORD/DB/PORT一致；样例为本地5433、shopping数据库 |
| CHAT_BASE_URL / CHAT_API_KEY / CHAT_MODEL | 自行配置兼容Chat Completions且实测支持tools的接口、Key、模型 |
| EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL | 默认http://127.0.0.1:8082/v1、local-no-secret、bge-large-zh-v1.5；Key只是本地SDK占位值 |
| EMBEDDING_MODEL_DIR / EMBEDDING_PORT | 自行准备的模型目录/默认8082；不设个人机器路径为默认 |
| EMBEDDING_DIMENSION | 首次留空，实际探测后保存，本次1024 |
| APP_MODE / DEMO_CUSTOMER_ID | demo / demo-user，无完整登录系统 |

样例数据库密码仅供本地演示。已建立数据卷后改.env密码不会自动修改库内角色密码。聊天配置缺失时明确禁用聊天，手动商品/订单仍可用。配置变化后建议停止并重新启动加载；再次启动还会核对 `.env` 指纹，变化时重新创建本项目进程；操作见 [用户手册](docs/USER_GUIDE.md#一键启动与停止)。当前DeepSeek模型以同模型非思考模式实际验证；其他兼容提供商须分别实测，不能只凭兼容声明推定原生tools可用。

## 准备本地模型

权重不随仓库发布。自行从[BAAI/bge-large-zh-v1.5模型仓库](https://huggingface.co/BAAI/bge-large-zh-v1.5)准备完整目录，至少包括匹配的config.json、tokenizer.json、分词器配置及权重；本项目实际加载pytorch_model.bin。保留下载版本及原许可，将目录填入本地EMBEDDING_MODEL_DIR；不要把权重放入Git。可使用项目相对目录data/embedding-model（已忽略），或自己选定的外部目录。

本地 embedding 默认镜像ghcr.io/huggingface/text-embeddings-inference:cpu-1.8.2须预先备妥。新环境可先执行`docker pull ghcr.io/huggingface/text-embeddings-inference:cpu-1.8.2`；这是准备命令示例，本轮没有重新拉取或下载大型模型。StartEmbedding使用pull_policy: never和离线加载，只读挂载权重，不自动下载。数据库镜像同样须预先备妥；在根目录运行 `docker compose pull db` 可按 compose.yaml 的固定摘要取得镜像。此为新环境准备示例，本轮未执行镜像拉取。一键启动对数据库也使用 `--pull never`。模型/镜像来源见[TEI](https://github.com/huggingface/text-embeddings-inference)，CPU使用Candle后端。

## 启动、种子与知识入库

日常启动使用 `start.cmd`。当商品和订单表均为空时，启动器调用已有 `seed_demo_data()`；本项目知识为空时，复用已有真实维度探测与政策入库。已有商品/订单与知识跳过，**不刷新订单日期，不重建知识**。部分数据缺失或已入库模型/维度不一致会停止自动准备，提示维护者有意修复，避免覆盖已有状态。

以下仅供维护者明确刷新演示日期或更换模型时使用；不需每天执行。命令均从根目录开始，已有环境先按下节 Stop 停应用，再启动本项目容器：

```powershell
docker compose up -d --wait --pull never db
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Action StartEmbedding
Push-Location api
try {
  # 有意刷新本项目种子日期，非日常启动步骤
  ..\.venv\Scripts\python.exe -m scripts.seed_demo
  # 更换向量模型/维度时有意执行
  ..\.venv\Scripts\python.exe -m scripts.probe_embedding --set-dimension
  ..\.venv\Scripts\python.exe -m scripts.ingest_knowledge
} finally { Pop-Location }
```

种子只 upsert 本项目来源记录，不清表或覆盖其他来源；重复种子会刷新演示订单相对签收日期。不刷新时签收日期固定，002 会随时间超过七天资格。知识入库只处理登记的三份政策；真实向量全部成功后才在事务内替换本项目资料。操作完成后双击 `start.cmd` 加载最新配置。

## 开发运行与本地部署

以下命令均在**项目根目录**执行，复用同一脚本、进程登记与启动锁：

| 用途 | 入口 | 页面与进程 |
|---|---|---|
| 首次配置/部署准备，或检查配置改动 | 双击 `setup.cmd` | 调用唯一 `dev.ps1 -Action Setup -Mode Deployment`；缺依赖按锁安装，已有依赖与构建复用；不启动业务服务 |
| 本地部署，日常使用 | 双击 `start.cmd` | http://127.0.0.1:8000；FastAPI 单进程托管 `web/dist`，不使用 Vite dev/preview |
| 本地部署，不自动开浏览器 | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch.ps1 -NoBrowser` | 同上，手动访问页面 |
| 开发调试 | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch.ps1 -Mode Development` | http://127.0.0.1:5173；Vite 开发服务器代理 `/api` 到 8000 |
| 停止本项目 | 双击 `stop.cmd`；或 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Action Stop` | 停已核对 PID/启动时间/归属的进程树和本项目 db/embedding，核对退出与端口；保留数据卷、配置和模型；重复停止可完成 |
| 配置重载 | `stop.cmd` → 修改本地 `.env` → `setup.cmd` → `start.cmd` → 刷新页面 | 重新创建应用，读取配置；已有库与知识不刷新。只使用手动功能且有意不配聊天时可跳过 Setup 的完整聊天检查 |

重复启动同一模式且配置未变时复用进程和生产构建；同一运行会话只自动打开一次浏览器。停止再启动或切换模式会建立新进程会话。模式切换先停止已登记的本项目应用，再使用目标模式；未知端口占用会拒绝启动，不结束未知进程。API 文档始终在 [8000/docs](http://127.0.0.1:8000/docs)，健康检查在 [8000/api/health](http://127.0.0.1:8000/api/health)。

构建随源码/资源/配置指纹变化更新，运行时与构建状态保存在忽略的 `.runtime`。三个入口共用启停锁。配置与停止窗口等待按键供阅读结果；启动成功后退出窗口，后台服务继续运行。部分失败保留实际登记与本项目容器状态，查看提示和本地日志，再 `stop.cmd` 后重试，不清库。未知端口占用不会被强行结束，停止也会明确报告未释放的端口。`dev.ps1 -Action Start` 默认为开发模式；`-SkipDocker` 仅供维护者已准备好健康数据库/embedding 时使用，不替代依赖准备。

公网部署需独立目标、密钥与访问配置，本轮没有公网上线、反向代理或多 workers。

手动调试（不要与脚本启动的进程同时占用端口）：

```powershell
# 根目录终端：先启动数据库，再前台运行API
# 模型问答还需要按上面的步骤启动embedding并完成入库
docker compose up -d --wait --pull never db
Push-Location api
try { ..\.venv\Scripts\python.exe -m uvicorn app.main:app --loop app.db:create_event_loop --host 127.0.0.1 --port 8000 } finally { Pop-Location }
```

```powershell
# 另一个根目录终端：Install成功后，读取实际运行时并启动前端
$taskRuntime = Get-Content .\.runtime\runtime.json -Raw | ConvertFrom-Json
& $taskRuntime.node $taskRuntime.pnpm --dir web run dev
```

前台终端分别用 Ctrl+C 停止，根目录运行 `docker compose stop db embedding` 停止本项目容器并保留数据卷。以上手动组合仅做路径、语法与配置审查，不宣称本轮完整执行。

## 演示与检查

页面操作及可直接输入的连续演示见 [用户手册：完整演示路径](docs/USER_GUIDE.md#一条完整演示路径)。检查范围与实际结果以 [验收说明](docs/ACCEPTANCE_AND_RELEASE.md) 为准；以下为维护者命令。

服务/种子/知识准备后，在根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pytest api/tests -q
$taskRuntime = Get-Content .\.runtime\runtime.json -Raw | ConvertFrom-Json
& $taskRuntime.node $taskRuntime.pnpm --dir web run typecheck
& $taskRuntime.node $taskRuntime.pnpm --dir web run build
Push-Location api
try { ..\.venv\Scripts\python.exe -m scripts.run_eval } finally { Pop-Location }
# 修复后只选择受影响案例，例如：
# api目录：..\.venv\Scripts\python.exe -m scripts.run_eval --cases D06 A08
```

run_eval执行二十案例，实际调用在线聊天（可能收费），不自动重试。程序断言通过的在线案例仍需直接检查正文、参数及事实：manual_review=pending不能当语义验收通过。原始报告与每次时间戳历史保存在artifacts，失败/环境缺失不掩盖，最新完整baseline可合并选择性重跑。公开仅发布[脱敏摘要](docs/evidence/evaluation-summary.json)。新环境没有数据库/模型/政策时不保证通过，也不使用假回复/假向量替代。

## MCP

官方Python SDK 1.30.0的独立stdio服务，search_products返回structuredContent.result数组，get_order返回Order；客户端先检查isError。输入由SDK/Pydantic校验，顾客身份服务端注入，不写业务数据。正常退出释放池，stdout只有JSON-RPC，日志stderr。

```powershell
# 根目录，服务会占用当前终端，供MCP客户端以stdio启动
Push-Location api
try { ..\.venv\Scripts\python.exe -m app.mcp_server } finally { Pop-Location }
# 独立协议检查终端：根目录
Push-Location api
try { ..\.venv\Scripts\python.exe -m scripts.check_mcp } finally { Pop-Location }
```

客户端配置：command为项目根目录.venv/Scripts/python.exe的实际绝对路径，args为["-m","app.mcp_server"]，cwd为本项目api目录，设置PYTHONIOENCODING=utf-8。服务不依赖聊天模型；必须先按上文初始化数据库/种子。两个工具的真实SDK协议结果见[MCP摘要](docs/evidence/mcp-summary.json)。本轮共享实现未修改，沿用O6证据，没有重复协议检查。

## 限制、来源与许可

首版不流式输出；每轮最多4次模型调用/8次工具/60秒，同会话单进程锁，保留最近6轮原生历史和20条消息ID去重缓存；超出缓存窗口不保证去重。失败保留输入且显式重试，不自动反复调用。数据库无自动清理历史记录的任务；可通过[会话管理](docs/USER_GUIDE.md#会话管理)主动删除聊天状态，不能据此清空业务记录或所有日志；演示管理显示最近记录，不表示全部历史都有限保留。无公网生产认证、压力测试、多浏览器矩阵或企业规模证明。主观佩戴/隔音建议未实测；检索分数不是可信概率。

全新机器安装未验证，各启动分支的证据见 [验收说明](docs/ACCEPTANCE_AND_RELEASE.md#运行与报告)。满足上述前提可按步骤复现本地演示，聊天输出不保证措辞或每次模型行为完全一致。

商品/订单/政策按项目规格合成；SVG由本项目绘制中性几何示意图，没有复制第三方商品照片或裁切设计基准。概念参考知微客服/知识检索和E-Commerce Agents结构化导购的业务划分，未直接集成或复制其业务代码。依赖使用其公开发行包，不把第三方库说成项目自研；UI 优化使用项目级 [Taste redesign-existing-projects 技能](.agents/skills/redesign-existing-projects/SOURCE.md)，固定 commit、上游来源与 MIT 声明随技能保留；仅复用该技能说明，未引入上游产品代码或其他设计技能。

[BGE模型卡](https://huggingface.co/BAAI/bge-large-zh-v1.5/blob/main/README.md)标注MIT；[TEI许可](https://github.com/huggingface/text-embeddings-inference/blob/main/LICENSE)为Apache-2.0（2026-10-04核对）。自行取得权重/镜像并遵守对应许可；本仓库不分发权重。项目自身按用户选择暂不添加许可证，不将第三方许可证视为本项目整体许可。

公开文档入口见上方导航。内部任务、设计讨论、阶段记录、原始报告与日志仅本地保留，不是公开启动的必需资料；模型、密钥与个人配置不发布。

2026-10-04 四页 UI 已完成局部优化：聊天输入紧邻会话、商品与状态层级统一、窄屏顶部导航、政策与执行记录按需展开。最新真实截图见[精选证据](docs/evidence/README.md)，Codex 浏览器走查结果见[验收记录](docs/ACCEPTANCE_AND_RELEASE.md#taste-技能与-ui-浏览器检查2026-10-04)。用户人工验收仍为 pending，不以源码发布代替人工或生产验收。

2026-10-08 用户反馈聊天连接失败及旧售后干扰，当时暂停发布。后续针对性修复与实际恢复范围见[最新验收记录](docs/ACCEPTANCE_AND_RELEASE.md#人工反馈后的针对性修复2026-10-08)。VPN 保持开启，未修改密钥/模型或关闭 TLS；历史连接失败的具体阶段因原异常链缺失仍待定位，不把本次恢复当永久修复。
