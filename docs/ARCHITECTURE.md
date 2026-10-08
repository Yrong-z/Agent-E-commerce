# 选购助手架构

本文说明当前实现的分层、入口和数据流。能力边界见 [README](../README.md#实际能力)，验收证据见 [验收与发布](ACCEPTANCE_AND_RELEASE.md)，字段与错误以 [契约](CONTRACTS.md) 为准。

## 1. 总体调用关系

顾客界面 → FastAPI 接口 → Agent 工具循环 → 本地工具执行器 → 业务服务 → 数据库 / 模拟业务适配器。

政策问答分支：知识检索服务 → embedding 适配器 → pgvector → 检索片段 → 模型解释与引用。

MCP 分支：MCP 客户端 → 本项目只读 MCP Server → 同一商品 / 订单业务服务。首版主聊天直接调用本地执行器，不走 MCP，也不依赖 MCP 服务是否启动。

保持五种职责即可：展示、接口与数据校验、Agent 编排、业务规则、外部适配 / 存储。不是五个微服务，不引入事件总线。

## 2. 技术与状态

React + TypeScript + Vite、自定义 CSS；Python + FastAPI + Pydantic；PostgreSQL + pgvector。直接使用选定数据库驱动，无需额外引入完整 ORM 平台。聊天与 embedding 分别配置。MCP 使用锁定的官方 Python SDK 1.30.0，服务与客户端沿用同一版本接口。

当前数据库表：products（商品）、orders（已有订单含物流 JSON）、sessions（会话状态与必要历史 JSON）、knowledge_chunks（资料片段与向量）、after_sales（预览/申请状态）、traces（执行摘要）。优惠首版一个服务内规则，无需优惠规则数据库。会话消息与请求缓存按下文限量保留；数据库历史记录没有自动清理任务。

## 3. 后端文件与关键入口

路径相对项目根目录。除入口、初始化文件与配置外，优先保留下表的紧凑结构。

| 文件路径 | 中文职责 | 关键函数 / 类及中文含义 |
|---|---|---|
| api/app/main.py | 应用装配、路由注册、启动检查 | create_app() 创建应用；lifespan() 管理数据库连接 |
| api/app/config.py | 读取并校验环境配置 | Settings 配置模型；get_settings() 获取配置 |
| api/app/db.py | 连接数据库及短事务 | get_connection() 获取连接；init_schema() 初始化演示表 |
| api/app/schemas.py | 接口和业务数据模型 | ChatRequest/ChatResponse 会话请求响应；Product 商品；SessionState 会话状态；AfterSalesPreview 售后预览；ApiError 错误 |
| api/app/routes.py | HTTP 入口，禁止放业务规则 | health() 健康检查；chat() 处理消息；list_sessions()/get_session() 列表与会话恢复；page_sessions()/delete_session()/delete_sessions()/delete_all_sessions() 分页及删除；list_products() 商品列表；product_detail() 商品详情；compare_products_route() 比较入口；list_orders() 已有订单；order_detail() 订单物流；preview_after_sales_route() 预览入口；confirm_after_sales_route() 确认入口；cancel_after_sales_route() 取消入口；list_after_sales() 申请列表；list_knowledge_sources() 资料列表；get_trace() 读取记录；demo_status() 只读管理快照；get_eval_report() 读取评测；get_capabilities() 能力状态 |
| api/app/agent/runtime.py | 模型→工具→模型有限循环 | run_agent_turn() 执行一轮会话；build_view_state() 根据真实工具结果生成界面状态 |
| api/app/agent/tools.py | 工具名称、说明、参数与本地分派 | build_tool_definitions() 生成原生工具声明；LocalToolExecutor.execute() 执行已注册工具 |
| api/app/agent/prompts.py | 提示词与上下文组织 | build_system_prompt() 生成任务规则；build_model_messages() 组织历史与业务状态 |
| api/app/agent/state.py | 会话保存、需求合并及指代 | list_customer_sessions() 最近会话；page_customer_sessions() 分页；delete_customer_sessions() 原子删除；session_lock() 单进程协调；load_session() 读取会话；save_session() 保存；resolve_product_reference() 解析候选指代；merge_search_constraints() 更新筛选条件 |
| api/app/services/catalog.py | 商品检索、详情、两款比较 | search_products() 搜索商品；get_product() 获取详情；compare_products() 固定字段比较 |
| api/app/services/pricing.py | 确定性优惠计算 | calculate_offer() 计算原价/优惠/到手价 |
| api/app/services/orders.py | 订单与物流查询 | list_customer_orders() 用户订单列表；get_order() 读取订单；get_logistics() 读取物流 |
| api/app/services/after_sales.py | 售后规则和状态变更 | evaluate_eligibility() 判断条件；prepare_after_sales() 建立预览；confirm_after_sales() 确认并返回申请；cancel_after_sales() 取消；get_after_sales() 查询状态 |
| api/app/services/knowledge.py | 少量资料入库和语义检索 | ingest_documents() 文本切分与向量写入；search_knowledge() 检索资料片段；list_sources() 已入库资料列表 |
| api/app/services/trace.py | 执行摘要与能力记录 | record_trace_event() 记录事件；get_request_trace() 读取一次请求记录；get_demo_status() 读取只读服务/会话快照；get_capability_status() 仍预留 |
| api/app/adapters/model.py | 国内模型原生工具接口 | ChatModelAdapter.complete_with_tools() 调用模型；probe_tool_calling() 检查原生 tools 可用性 |
| api/app/adapters/embedding.py | 独立 embedding 接口 | EmbeddingAdapter.embed_texts() 生成真实向量；probe_embedding() 检查维度与可用性 |
| api/app/adapters/commerce.py | 商业系统替换边界 | CommerceAdapter 业务数据接口；MockCommerceAdapter 当前模拟实现；read_products()/read_order()/read_logistics() 读取数据 |
| api/app/mcp_server.py | 两个只读工具的 MCP 导出 | create_mcp_server() 创建服务；search_products() 与 get_order() 为薄包装，不复制规则 |
| api/scripts/seed_demo.py | 生成统一演示数据与相对日期 | seed_demo_data() 幂等初始化合成数据 |
| api/scripts/ingest_knowledge.py | 资料入库命令 | main() 调用 ingest_documents() |
| api/scripts/run_eval.py | 有限评测及报告写入 | run_evaluation() 执行案例；write_report() 输出真实报告 |
| api/scripts/check_mcp.py | 最小 MCP 客户端验证 | check_mcp_tools() 列举并调用两个工具 |
| api/tests/test_business_rules.py | 金额、比较与售后状态关键断言 | 使用少量参数化案例，不为每个函数建立测试文件 |
| api/tests/test_api_contract.py | 接口结果和确认流程检查 | 检查真实模型以外的确定性接口 |

services 中 search_products() 等函数是唯一业务实现；HTTP、原生工具和 MCP 都调用它们。同名包装在不同模块中允许存在，须只做参数适配与调用。

## 4. 前端文件与关键入口

| 文件路径 | 中文职责 | 关键组件 / 函数 |
|---|---|---|
| web/src/main.tsx | 挂载入口 | 挂载 App |
| web/src/App.tsx | 应用壳和四个页面切换 | App（应用）；navigateTo() 切换页面 |
| web/src/api.ts | 集中封装请求，不散落 fetch | sendMessage() 发消息；fetchSessions()/fetchSession() 会话；fetchProducts()/fetchProduct() 商品；fetchComparison() 对比；fetchOrders()/fetchOrder() 订单；previewAfterSales()/confirmAfterSales()/cancelAfterSales()/fetchAfterSales() 售后；fetchDemoStatus() 管理快照；fetchKnowledgeSources()/fetchTrace() 资料与记录；完整评测/能力接口仍预留 |
| web/src/types.ts | 前端领域类型 | ChatResponse、Product、ViewState、AfterSalesPreview；与 Pydantic/OpenAPI 核对 |
| web/src/hooks/useShoppingSession.ts | 会话、等待与请求状态 | useShoppingSession() 会话钩子；submitMessage() 提交；startNewSession() 新会话；restoreSession() 恢复；removeSessions() 删除并同步本地/标签状态 |
| web/src/pages/ShoppingPage.tsx | 导购主页面 | ShoppingPage（购物页） |
| web/src/pages/OrdersPage.tsx | 已有订单与物流 | OrdersPage（订单页） |
| web/src/pages/AfterSalesPage.tsx | 售后预览和申请记录 | AfterSalesPage（售后页） |
| web/src/pages/DemoAdminPage.tsx | 只读工程展示 | DemoAdminPage（管理页） |
| web/src/components/SessionManager.tsx | 会话项菜单与轻量管理抽屉 | SessionItem 右键/按钮菜单；SessionManager 分页、选择及独立删除确认 |
| web/src/components/Sidebar.tsx | 导航、历史会话 | Sidebar（侧栏） |
| web/src/components/Conversation.tsx | 消息和真实工具结果展示 | Conversation（会话）；MessageComposer（输入框），先同文件 |
| web/src/components/ProductCard.tsx | 商品图片、价格和操作 | ProductCard（商品卡片） |
| web/src/components/ContextPanel.tsx | 需求、比较、已有订单 | ContextPanel（上下文栏）；ComparisonPanel（对比面板），先同文件 |
| web/src/components/DetailDrawer.tsx | 商品与订单物流详情抽屉 | DetailDrawer（详情抽屉） |
| web/src/components/AfterSalesPreview.tsx | 明确确认与取消 | AfterSalesPreview（售后确认卡） |
| web/src/styles.css | 全局变量和布局 | 不为每个小组件创建独立样式文件 |

不强制引入 Redux、复杂路由器或自动客户端生成平台。少量类型可人工维护，但必须用接口检查避免漂移。

## 5. 配置、资料与产物

| 路径 | 中文作用 |
|---|---|
| api/pyproject.toml 与选定锁文件 | 后端依赖及实际验证版本 |
| web/package.json 与包管理器锁文件 | 前端启动、构建及版本 |
| .env.example | 无密钥配置样例 |
| compose.yaml | PostgreSQL/pgvector 与独立 profile 本地 TEI；不含应用容器 |
| data/products.json、data/orders.json | 商品与已有订单种子 |
| data/knowledge/*.md | 少量明确标为演示规则的政策 |
| data/eval_cases.jsonl | 20 个有明确断言的案例 |
| web/public/products/ | 少量无品牌商品图片 |
| artifacts/eval-report.json | 真实评测结果，未运行不能填成功 |
| artifacts/mcp-check.json | 真实 MCP 联通结果 |
| docs/evidence/ui-shopping.jpg、ui-admin.jpg、evaluation-summary.json、mcp-summary.json | 脱敏真实界面与协议证据 |
| README.md、docs/USER_GUIDE.md | 安装配置与开发者入口；面向使用者的页面操作 |

## 6. 明确的扩展位置

- 企业数据：实现 CommerceAdapter 的三个读取方法及数据字段转换；售后外部提交接口另行扩展，当前只保存模拟申请。
- 远程工具：预留 ToolExecutor.execute(tool_name, arguments, session) 行为契约，未来增加 McpToolExecutor；首版只创建 LocalToolExecutor，不建空的远程执行器文件。
- 评价：预留 summarize_reviews(product_id, reviews) 的结构化结果约定；未实现前不注册到模型工具列表。
- 多 Agent：可以把业务工具组交给专门编排模块，当前不生成规划器/监督器等空壳。

## 7. 实施时核对的官方资料

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP 架构](https://modelcontextprotocol.io/docs/learn/architecture)

已于 2026-10-03 核对。文档只规定两个工具与传输行为；具体导入、启动和握手由安装并锁定的 SDK 版本决定，不手写协议。

## 8. 会话与有限循环


run_agent_turn 顺序执行原生调用：四次模型、八次工具、整体六十秒（入口留两秒记录整体超时，处理预算58秒）。build_model_messages 只传系统规则、业务状态和最后六个完整用户轮次；assistant/tool ID 成组追加，超限也为批次中每个 ID 回传失败。ChatModelAdapter 禁用 SDK 重试；DeepSeek 官方主机明确设置 thinking=disabled，保持用户模型，不持久化隐藏推理。

merge_search_constraints 使用 exclude_unset 区分省略与 null；工具 Schema 移除默认值，提示模型只传用户修改字段。search_products 调用商品服务，成功更新候选（包括空数组），清空详情/比较；get_product 用最新候选解析指代，只改焦点；compare/order 操作关闭详情焦点，订单保留导购状态。pending_question 记录 order_id 或 logistics_order_id，补充时模型继续原任务。

SessionState 在既有 sessions.state JSON 中补充 view_state、display_messages、response_cache、title、candidate_limit、last_order_id；没有新表或平行状态层。session_lock 的弱引用 asyncio.Lock 覆盖加载、执行、缓存与保存，适用于现有单进程服务；不持有模型等待期间的数据库事务。新会话 ID 由顾客/client_message_id 稳定生成；最近二十条请求缓存按cached_at裁剪（jsonb重排键），校验相同 ID 的内容，冲突409，恢复返回404或真实快照。显示消息最多24条，不渲染原生工具历史。

会话管理复用 sessions 与既有单进程锁，不新增表或状态层。分页用同一只读快照计数/读取；删除使用事务，当前顾客删除标记与进行中操作计数封住竞态，锁住归属会话后才删除；忙碌整批409，全部删除校验用户确认的实际数量。聊天最终 save_session 使用 allow_create=False 更新，避免迟到保存重建已删除会话。after_sales 无删除级联，业务记录保留；traces 仅按被删响应缓存的确切请求ID且无其他会话引用清理，旧无法归属记录保留。具体响应和错误见[会话管理契约](CONTRACTS.md#会话管理与删除)。

useShoppingSession 驻留 App，保存最近本地选中会话；发送中禁止重复提交，网络失败沿用原消息 ID，明确 failed 后新 ID 显式重试。ShoppingPage 接收 ViewState 驱动既有商品卡片/详情/对比，ContextPanel 同步条件和已有订单。手动浏览独立，不把手动候选误认为模型候选。删除当前会话清除钩子状态、重试缓存与本地恢复编号，并重建 ShoppingPage 的局部视图；删除其他会话保持当前状态。通过同源 storage 通知及 focus 时存在性检查处理其他标签页，404恢复直接回到新会话；管理抽屉复用 DetailDrawer 焦点/Escape，不增加主导航。

trace.py 使用既有 traces 保存参数/结果摘要、耗时和错误，模型与循环错误也记录；文本 query 只记长度，未知工具不记原始参数，不记录请求头/密钥/隐藏推理。get_request_trace 已接通，缺记录404；能力和评测HTTP接口仍501；CLI二十案例评测已实现。

## 9. 政策RAG和模拟售后

services/policies.py 将三个明确演示政策文件对应到文档ID，并提供最小policy_id映射。七天窗口由代码判断，不由模型批准。after_sales检查当前用户/签收/期限/原因及全部订单商品政策，金额使用历史实付；政策来源读取公开文本，卡片标注确定性规则来源，不冒充检索引用。

knowledge.ingest_documents：白名单校验→段落切分→独立真实embedding→来源锁/事务替换。本来源shopping-assistant-policy-v1；knowledge_chunks新增source_owner，不覆盖其他来源。稳定内容ID避免重复片段，写入与检索校验模型/维度；更换模型需整套重新入库。search_knowledge使用pgvector余弦距离和相关性下限，返回真实片段及ID，无缓存/假向量/旧引用兜底。0.50相关性下限已由本地BGE少量正负样本验证，不表示概率或通用准确率。

after_sales表保存pending/submitted/cancelled/expired及资格、金额、原因、政策来源和十分钟有效期。sessions保存当前预览ID及独立after_sales_draft。事务锁定会话/预览，确认重读订单与商品，首次生成application_id，重复确认同ID；过期状态提交后才返回410。更换订单/原因取消旧待确认预览，失败的新输入不能继续提交旧内容。恢复会话重新查询售后表最新状态，不恢复静态成功。

HTTP确认/取消与聊天共享会话锁；模型只新增search_knowledge/prepare_after_sales/get_after_sales，无确认或取消工具。POST /sessions为空会话入口，手动售后无需模型。ViewState.active_task 由 SessionState.active_task 同步，恢复旧记录同样读取实际任务。购物页仅在当前售后任务且聊天未失败/未等待时展示售后卡；售后页始终可查看保留的申请与记录。已提交卡不再突出预览编号/有效期，申请编号保持。

明确失败后的相同输入重试替换该失败轮的显示结果与完整原生历史块，不重复追加用户输入；HTTP 响应未取得时仍沿用 client_message_id 保持幂等。刷新恢复最后失败轮时恢复输入和主要错误入口。ChatModelAdapter 对异常链仅记录类型、数值错误码/HTTP状态与 httpcore 连接阶段，不记录异常正文、请求或代理地址；每进程首次调用记录工作目录匹配与配置/代理环境变量是否存在，不输出变量值。本地 embedding 的绕过环境代理规则保持，聊天仍使用原环境代理和 TLS 校验，无自动重试或更换模型。

embedding链路：Python OpenAI SDK → 独立Compose embedding服务的 /v1/embeddings → TEI 1.8.2 Candle CPU → 只读本地BGE权重。模型目录仅在本地配置；服务127.0.0.1:8082、离线加载、不拉镜像；不复用其他项目容器或缓存卷。无需新建适配框架。仅本地embedding的httpx客户端trust_env=False，云端及聊天代理行为保持。SDK请求encoding_format=float，校验index、数量、非空、有限值、非零及实测维度。本次实测1024维，同语料统一模型与维度。

申请原因须具体；流程名称不算原因，工具保存待补状态而不生成预览；结构化规则同样检查该边界。

## 10. 页面与只读管理

App 保持会话钩子驻留，购物、订单、售后、管理四页复用现有组件与 CSS。管理页打开/当前会话变化时取一次快照，手动刷新清旧结果，无自动轮询。订单与售后明确等待、空、失败、重试；聊天失败时标注上次成功结果，不能冒充本次操作。窄屏侧栏导航、抽屉与确认按钮可用。

GET /api/demo/status → trace.get_demo_status：读取本项目知识来源、实际入库模型/维度，复用当前用户会话缓存和 traces，返回最近十次记录。模型状态只取属于现存当前用户会话的最近带时间模型调用；没有记录为未检查，不进行收费探测。本地 embedding 仅请求 TEI /health，沿用绕过环境代理，不推断推理成功率。

TraceEvent 新增 checked_at 与 sources：新事件写实际 UTC 时间，成功 search_knowledge 保存当次真实 KnowledgeHit。管理页仅导出工具/错误码/耗时/时间/来源，不导出原始参数、模型日志或隐藏推理。历史事件无字段按 null/空来源处理，不能拿当前引用填补过去记录。数据库或请求失败不能显示为真实零条记录。

提示词将名称查询与用途约束分开，避免把用途句子作为名称关键词造成无匹配。商品筛选和优惠仍由确定性服务处理。

## 11. 只读MCP

api/app/mcp_server.py 使用官方 FastMCP 1.30.0，只注册 search_products/get_order，标记 readOnlyHint、idempotentHint，返回 SDK 校验的 Product 数组和 Order 结构化结果。包装只校验协议输入、注入配置中的演示顾客并调用 catalog/orders；不复制规则、不调用模型、不写会话/业务表、不注册售后工具。

独立服务 lifespan 开启/关闭同一 db.py 连接池，不调用 init_schema。服务进程使用既有 Windows Selector 循环，stdio 的 JSON-RPC 交给 SDK；日志只写 stderr。主聊天仍走 LocalToolExecutor，与 MCP 生命周期无耦合。

api/scripts/check_mcp.py 使用官方 ClientSession/stdio_client 和默认客户端事件循环启动子进程，实际 initialize/list_tools/call_tool。独立故障子进程覆盖 DATABASE_URL 验证依赖不可用，不更改本地 .env 或数据库。关闭输入后核对连接池关闭标记和协议解析错误计数。原始报告/日志内部忽略，公开摘要在 docs/evidence。

## 12. 启动与进程管理

根目录 `setup.cmd` → `dev.ps1 -Action Setup -Mode Deployment`，`start.cmd` → `launch.ps1` → `dev.ps1 -Action Start`，`stop.cmd` → `dev.ps1 -Action Stop`。三个 CMD 均为自身目录定位、UTF-8提示与退出码传递的薄包装；锁、依赖准备、进程归属、启停与浏览器去重仍由 dev.ps1 统一管理。模式及托管路径见[本地部署路径](#本地部署路径)，实际命令见 [README](../README.md#开发运行与本地部署)。

## 13. CLI评测与证据

api/scripts/run_eval.py读取data/eval_cases.jsonl，执行12个业务服务/规则案例和8个在线Agent案例。确定性部分复用catalog/pricing/orders/after_sales/knowledge；D12复用现有ASGI去重测试。在线部分通过HTTP调用既有Agent入口并核对trace、原生消息配对、ViewState及数据库事实；A08只在本次ASGI请求内注入检索依赖故障，恢复后仍调用真实embedding。

每次写入不可覆盖的时间戳原始报告，latest为便于读取的副本；--cases仅执行指定案例，存在完整baseline时合并对应结果，保留原报告。程序通过仍须语义审阅，manual_review=pending不能作为人工审阅通过。正式脱敏摘要只取实际最终结果；无第二个模型裁判或并行Agent。命令见README，原始证据本地保留，不作为公开运行依赖。

## UI 展示维护

四页继续复用 App、Sidebar、ProductCard、DetailDrawer 与售后组件，样式集中在 web/src/styles.css；窄屏导航改为顶部，聊天输入位于会话后，政策来源与执行记录默认折叠。此展示调整不改变 HTTP/工具契约、会话持久化、显式售后确认或后端数据流。项目级 UI 技能入口与应用约束见 [AGENTS](../AGENTS.md#ui-技能入口)。

## 本地部署路径

`start.cmd` → `scripts/launch.ps1`（薄包装，默认 Deployment）→ `scripts/dev.ps1`（唯一锁、依赖/容器准备、进程登记与浏览器去重）。Development 保留 Vite 5173 + FastAPI 8000；Deployment 由 Vite 构建 `web/dist`，FastAPI 8000 单进程托管静态资源。两种模式默认只监听 127.0.0.1，共用数据库/embedding 和业务层，不运行 Vite preview。

`api/app/frontend.py` 的 `mount_frontend()` 在业务/API及文档路由之后注册页面处理；启动脚本在应用进程内设置 `SERVE_FRONTEND`，开发模式关闭。真实构建文件按路径返回，缺失资源、未知 `/api` 和含隐藏路径段的请求（如 `/.env`、`/.git/config`）返回错误，不回退 HTML或公开隐藏文件；其他无扩展名页面路径可回退 index，支持 SPA 刷新。前端 `web/src/api.ts` 始终使用同源 `/api`，构建资源路径为 `/assets`、`/products`，不暴露密钥。

`api/scripts/prepare_local.py` 是状态检查与调用入口，复用 `seed_demo_data()`、真实维度探测及 `ingest_documents()`，没有第二套初始化规则：商品与订单均空才生成种子，本项目知识为空才探测/入库；已有数据跳过，部分缺失或模型维度冲突明确中断。数据库卷、订单签收日期、已有申请不因启停重写。

`Setup` 复用 `Install-Dependencies()`、`prepare_local --preflight --require-chat`、`Ensure-Docker()`、镜像/端口检查与 `Build-Frontend()`，不启动本项目业务容器或应用，不写业务库；可能尝试拉起未就绪的 Docker Desktop。缺模型/镜像/聊天配置明确失败且不下载；普通 Start 仍允许聊天未配置时运行手动功能。`Stop` 复用原归属校验与进程树停止，补核对8000/5173及本项目容器停止结果，不关闭引擎、不移除卷。

进程登记仍使用 PID/启动时间/项目命令归属，增加模式与配置指纹；模式/配置变化重建本项目应用。同一启停锁覆盖安装/启动/停止，停止确认进程退出并容忍子进程退出后父进程已自行结束的竞态；失败保留诊断登记。正常状态下重复启动复用，浏览器去重沿用实际进程会话，不通过删除状态文件制造新会话。
