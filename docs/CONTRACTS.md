# 选购助手接口与工具契约

本文登记当前实际契约和明确标注的预留接口。[api/app/schemas.py](../api/app/schemas.py)、[web/src/types.ts](../web/src/types.ts) 与 FastAPI OpenAPI 为字段依据；修改契约必须同步前端类型与有关验收，不能各自改名。

## 通用约定

- ID 为字符串；金额统一整数分，后端字段以 _fen 结尾，界面格式化为元。模型收到说明和明确单位，不能把 300 元当 300 分。
- 日期采用含时区 ISO 8601；演示业务日按 Asia/Shanghai 计算，数据库时间统一保存 UTC。
- 接口 JSON 使用 snake_case，TypeScript 函数使用 camelCase；对象字段保留接口原名。
- 当前顾客由服务端 DEMO_CUSTOMER_ID 配置取得（默认 demo-user），不接受模型传入任意 customer_id。没有完整登录系统。
- 错误格式 ApiError：code、message、retryable、request_id。错误详情不能含密钥、完整环境变量或模型内部推理。
- 常用错误：PRODUCT_NOT_FOUND、ORDER_NOT_FOUND、NO_MATCH、INVALID_ARGUMENT、PREVIEW_EXPIRED、STATE_CONFLICT、MODEL_UNAVAILABLE、KNOWLEDGE_UNAVAILABLE、TOOL_FAILED。NO_MATCH 是成功查询中的空结果，不是服务异常。
- 输入错误 422；资源不存在 404；状态冲突 409；过期预览 410；服务不可用 503。重试和可用能力以实际返回为准。

## 关键数据模型与中文含义

| 模型 | 必要字段 | 中文含义 |
|---|---|---|
| Product | product_id、name、image_url、category、use_cases、list_price_fen、sale_price_fen、discount_fen、promotion_label、stock、specs | 商品事实；specs 至少含 wearing_style、anc、battery_hours，允许未知 |
| SearchConstraints | query、budget_max_fen、use_case、in_stock_only | 当前检索条件；预算可为空，in_stock_only 默认 true |
| Comparison | product_ids、rows、recommendation_basis | 正好两款；rows 为 field、label、values，缺参数的值为空，前端显示未知 |
| Order | order_id、customer_id、items、paid_total_fen、status、signed_at、logistics、policy_id | 已有订单；status 严格为 shipped 或 delivered |
| KnowledgeHit | chunk_id、document_id、title、excerpt、score | 真正检索得到的资料；score 为检索分数，不包装成可信概率 |
| AfterSalesPreview | preview_id、order_id、reason、status、eligible、explanation、refund_amount_fen、policy_source_ids、policy_sources、expires_at、application_id | 售后预览；application_id 在确认前为空；eligible=false 不能确认 |
| SessionState | session_id、constraints、candidate_product_ids、focused_product_ids、active_task、pending_question、pending_after_sales_id、recent_messages、updated_at | 会话上下文；不把模型隐藏推理存入状态 |
| ViewState | active_task、products、focused_product、comparison、order、after_sales_preview、citations、constraints | active_task 从会话实际任务同步，取 shopping/orders/after_sales/knowledge；保存历史售后不代表当前任务，不由模型正文猜测 |
| CapabilityStatus | name、implementation_status、verification_status、verified_at、detail | 预留模型，HTTP仍501；区分 implemented/reserved/not_implemented 和 passed/failed/not_run |

示例价格：A1 的 list_price_fen=19900、sale_price_fen=19900；B2 为 29900、27900、discount_fen=2000。商品仅在 promotion_eligible=true 且原价达到 20000 分时适用规则。排序和预算过滤使用同一 calculate_offer() 结果。

## HTTP 接口

| 方法与路径 | 中文用途 | 输入 / 输出要点 |
|---|---|---|
| GET /api/health | 检查服务 | 应用与数据库状态，不外呼付费模型 |
| POST /api/chat | Agent 一轮消息 | ChatRequest：session_id 可空、message、client_message_id；ChatResponse 见下文 |
| POST /api/sessions | 建立空会话 | 无模型调用，返回 SessionResponse |
| GET /api/sessions | 最近会话 | 当前顾客最近20条 session_id、标题、更新时间 |
| GET /api/sessions/page | 分页历史 | offset 默认0、limit 默认20（1–50）；SessionPage |
| DELETE /api/sessions/{session_id} | 删除单条 | 当前顾客范围；SessionDeletionResult |
| POST /api/sessions/delete | 批量删除 | DeleteSessionsRequest：session_ids；SessionDeletionResult |
| DELETE /api/sessions | 删除全部 | JSON DeleteAllSessionsRequest：expected_count；SessionDeletionResult |
| GET /api/sessions/{session_id} | 恢复会话 | SessionResponse：state 和 view_state；state 含 display_messages，response_cache 置空 |
| GET /api/products | 商品筛选 / 管理只读列表 | query、budget_max_fen、use_case、in_stock_only、limit |
| GET /api/products/{product_id} | 商品详情 | 一个 Product |
| POST /api/products/compare | 两款比较 | product_ids 长度等于 2，返回 Comparison |
| GET /api/orders | 我的已有订单 | demo-user 的订单列表 |
| GET /api/orders/{order_id} | 订单和物流 | Order，只返回当前演示用户的数据 |
| POST /api/after-sales/preview | 建立售后预览 | session_id、order_id、reason，返回 AfterSalesPreview |
| POST /api/after-sales/{preview_id}/confirm | 显式确认 | session_id，确认有效预览；返回固定 application_id 与 submitted 状态 |
| POST /api/after-sales/{preview_id}/cancel | 取消待确认预览 | session_id；返回 cancelled；已提交申请不可在此取消 |
| GET /api/after-sales/{preview_id} | 查询一条预览 / 申请 | AfterSalesPreview，绑定当前用户 |
| GET /api/after-sales | 查询申请 / 预览 | 当前演示用户记录，未确认状态明确区分 |
| GET /api/traces/{request_id} | 查看工具执行 | 事件列表，结果为摘要，无隐藏思维链 |
| GET /api/knowledge/sources | 查看知识资料 | 已入库文档标题、ID、片段数，无编辑功能 |
| GET /api/demo/status | 只读管理快照 | session_id 可省略，返回 DemoStatus；见管理契约 |
| GET /api/evaluations/latest | 预留评测HTTP入口 | 501 NOT_IMPLEMENTED；实际评测使用CLI |
| GET /api/capabilities | 预留能力HTTP入口 | 501 NOT_IMPLEMENTED；实际能力见README |

ChatResponse 固定字段：request_id、session_id、answer、status、view_state、error。status 为 completed、needs_input 或 failed；详细输入限制、错误与重试约定见“会话与工具契约”。

## 会话管理与删除

SessionPage 返回 items、total、offset、limit、has_more；items 为 SessionSummary（session_id、title、updated_at）。offset 为非负整数，limit 为1–50；按 updated_at 降序及 session_id 排序，同一数据库快照内取总数与页面。GET /api/sessions 保持最近20条兼容接口；分页不代表全量已加载，记录变化后可刷新。

删除顾客身份只从服务端配置取，不接受客户端 customer_id。单条 ID 必须非空、最多100字符；批量 session_ids 原始数组为1–100项，每项非空、最多100字符，重复 ID 去重后执行，非法参数或额外字段返回422 INVALID_ARGUMENT。全部删除请求必须含严格非负整数 expected_count（不是布尔值），与事务内实际数量不符时返回409 SESSION_COUNT_CHANGED，不执行删除，需要重新读取总数并确认。

删除响应 SessionDeletionResult：deleted_count（实际会话数量）、deleted_ids、not_found_ids、deleted_trace_count（实际执行摘要条数）。单条/批量重复删除为200，实际数量0，不存在或非当前顾客的 ID 放入 not_found_ids，不暴露他人记录是否存在；全部重复删除在 expected_count=0 时为200/0。ID结果不承诺请求顺序。

忙碌会话或同顾客删除执行中返回409 SESSION_BUSY；多选中任意已归属会话忙碌则整批不删，全部删除与当前顾客任何聊天/售后操作冲突。事务同时删除会话及可靠关联执行摘要，内部失败整批回滚。复用单进程 session_lock，删除期间阻止新聊天、售后和会话创建；聊天完成保存采用仅更新既有记录，不能重新插入已删除会话。缺会话仍返回404 SESSION_NOT_FOUND，客户端清除旧恢复状态并回到新会话。

删除 sessions 行即删除其显示消息、模型历史、候选、来源和响应缓存。不删除 products、orders、knowledge_chunks、after_sales；已有售后申请仍由 GET /api/after-sales 查看，申请编号不变。原待确认预览不能用已删除 session_id 继续确认（404）；不承诺删除业务记录。

traces 没有稳定的 session_id/customer_id 字段：仅删除被删会话 response_cache 内确切 request_id 对应且不被其他现存会话缓存引用的记录。缓存窗口外或无法可靠归属的旧记录保留；这不是所有日志彻底清除，不增加新的 trace 归属系统。

## 原生 Tool Calling

| 工具名称 | 中文作用 | 关键参数 |
|---|---|---|
| search_products | 搜索符合条件的商品 | query、budget_max_fen、use_case、in_stock_only、limit（最大 6） |
| get_product | 查看候选商品详情 | product_id；也可接 reference，并通过服务解析“第二款” |
| compare_products | 比较两款商品 | product_ids；默认可使用最近两款候选，但必须校验数量与存在性 |
| get_order | 查询已有订单 | order_id |
| get_logistics | 查询已有订单物流 | order_id |
| search_knowledge | 搜索商品相关政策 | query、product_id 可空、top_k（最大 3） |
| prepare_after_sales | 判断并建立售后预览 | order_id、reason，当前会话由执行器注入 |
| get_after_sales | 恢复待确认 / 已提交申请 | preview_id 可空，空时使用会话中的当前记录 |

优惠由商品服务内部 calculate_offer() 统一计算，不给模型再维护一套促销逻辑。工具名称与 JSON Schema 从同一注册表生成。参数校验、默认值、业务状态和错误由执行器处理。

循环：组织消息与状态 → 向模型发送原生 tools 声明 → 接收 assistant.tool_calls → 校验并执行 → 回传带正确 tool_call_id 的 tool 消息 → 模型给出最终解释或继续工具调用。禁止解析模型普通文字冒充原生调用。

最多 4 次模型调用、8 次工具执行；整体请求约 60 秒预算，具体超时受剩余预算约束。同一轮模型返回多个 tool_calls 时按 SDK 协议回传所有结果；首版依次执行即可，不开发并行调度框架。超出预算说明未完成并记录失败，不伪造最终成功。

Tool Calling 只说明模型调用工具，MCP 是工具暴露/访问协议，两者不能互相替代。

## 其他预留契约

CommerceAdapter：read_products() → 商品原始记录；read_order(order_id, customer_id) → 订单；read_logistics(order_id) → 物流。MockCommerceAdapter 当前读演示数据库；未来外部适配器在此转换企业字段，业务服务不直接访问企业 API。

LocalToolExecutor.execute(tool_name, arguments, session) 当前返回 ToolResult：ok、data、error、view_updates；通用 ToolExecutor / McpToolExecutor 仅为未来替换边界，尚无远程实现。

评价摘要 summarize_reviews(product_id, reviews) → ReviewSummary：product_id、sample_count、strengths、weaknesses、source_ids、data_mode。首版仅预留，reviews 必须来自数据，不能虚构评分或数量。

## 环境配置

配置名称、准备步骤与示例统一见 [README：首次安装与配置](../README.md#首次安装与配置)。聊天与向量分别配置；embedding 维度须以真实探测结果为准，不能混用不同模型的语料。

## 子字段与错误约定

健康成功返回 HealthResponse（status/application/chat_model/database/pgvector/detail）；数据库或扩展不可用返回 503 同模型。所有尚未实现业务接口使用 501 ApiError，code=NOT_IMPLEMENTED；参数校验仍为 422 INVALID_ARGUMENT。未知工具为 UNKNOWN_TOOL，未实现工具显式失败，不生成原生声明或 MCP 注册。

会话恢复结构为 SessionResponse（state: SessionState、view_state: ViewState）；列表接口中，会话摘要、商品、订单、售后、资料、执行记录为对应类型数组；管理返回 DemoStatus 对象，能力HTTP仍501，不返回真实列表。对比 rows.values 固定两值并保持 product_ids 顺序，recommendation_basis 为字符串数组。

Product 明确包含 promotion_eligible（默认 false）和 policy_id（可空）。specs 使用 ProductSpecs；订单 items 使用 OrderItem（product_id/name/quantity/paid_price_fen），logistics 为 Logistics（summary/events），events 为 time/description。所有日期类型使用含时区 ISO 8601。其余细分模型以 schemas.py/OpenAPI 为准，同步定义于前端 types.ts。

类型、501接口或扩展签名不代表功能实现。

## 商品和订单确定性行为

已实现 GET /api/products、GET /api/products/{product_id}、POST /api/products/compare、GET /api/orders、GET /api/orders/{order_id}。health 正常 200，基础设施故障 503。

商品 query 对名称/编号/品类/用途作忽略大小写的文字包含匹配，去除前后空格；use_case 精确筛选用途；budget_max_fen 为非负整数分，按统一到手价过滤。in_stock_only 默认 true，limit 默认 6、范围 1–6，按 product_id 排序后截取。空结果为 200/空数组，页面提示修改条件。

比较严格为两个不同且存在的 ID，顺序与请求一致。固定行 sale_price_fen、wearing_style、anc、battery_hours、stock；缺值 null，前端显示未知。recommendation_basis 仅为事实依据说明，无模型建议。

未知商品或比较 ID 返回 404 PRODUCT_NOT_FOUND；未知/不属于当前配置顾客的订单返回 404 ORDER_NOT_FOUND，不暴露其他顾客记录。订单金额与物流取数据库快照，不重算当前价格。未新增物流 HTTP 路径，订单详情包含 logistics，get_logistics 为服务入口。

_seed_source 是数据库种子所有权标记，signed_days_ago 仅供种子生成相对日期，两者不进入 HTTP。日期 UTC 保存，界面按 Asia/Shanghai 显示。MockCommerceAdapter读取合成数据库。


## 会话与工具契约

health 的 chat_model=configured|not_configured 只检查配置，不发模型请求。

ChatRequest.message 长度1–2000，空白拒绝；client_message_id 长度1–100。ChatResponse 包含 error:ApiError|null。已接收轮次返回200 + completed/needs_input/failed；配置、协议、模型、超时、工具错误都明确 failed/error。未知会话404 SESSION_NOT_FOUND，重复ID内容冲突409 MESSAGE_ID_CONFLICT，整体超时504 REQUEST_TIMEOUT。缓存返回最初 request_id，用该ID查询trace；网络未拿到响应时沿用同ID，明确failed后重试新ID。缓存以内部cached_at时间裁剪（jsonb键顺序不可作时间依据），最近二十条去重记录，超出窗口不保证去重；新会话无session_id的同ID请求也得到稳定会话ID。

唯一TOOL_REGISTRY包含上表八个工具，确认未注册。参数严格校验，拒绝未知字段、布尔金额和字符串冒充整数。SearchProductsArgs 仅合并 exclude_unset：未提供保留，预算/use_case 的 null 清除；in_stock_only 不可null。limit 未提供保留最近limit（初始6，范围1–6）。普通HTTP商品筛选采用上文所列默认值，不等同多轮工具局部更新。

GetProductArgs.reference 以最新 candidate_product_ids 解析第一/第二/第三款；ID与reference同时提供必须一致。未知指代 REFERENCE_NOT_FOUND；详情不改变候选。CompareProductsArgs 省略ID用前两款，数量不足 NEEDS_INPUT；成功比较清除详情焦点。GetOrderArgs.order_id 允许省略/null 触发 NEEDS_INPUT，不能猜订单；pending_question=order_id、logistics_order_id 或比较缺候选时product_ids，补充后查询并清空追问。未知工具 UNKNOWN_TOOL，参数 INVALID_ARGUMENT，领域错误保留原码，异常 TOOL_FAILED；未实现工具和售后确认没有声明。

SessionState 包含 display_messages（最多24条正文/status）、response_cache（最近20条结果，恢复接口置空，不向前端传内部缓存）、view_state（最近工具事实快照）、title、candidate_limit、last_order_id。recent_messages 保存最近六轮完整原生消息组，不含 reasoning_content。active_task区分shopping/orders/knowledge/after_sales，查订单保留导购条件/候选；空搜索清空候选、对比和详情。

ViewState 包含 focused_product:Product|null。products 为最近聊天搜索候选，详情只改 focused_product；order 是最近成功查询的已有订单。前端事实只读 ViewState，不解析正文。恢复返回 SessionResponse；日期含时区，模型不能把UTC当北京时间或从policy_id推导政策。

同会话现有单进程串行，超时预算包含锁等待，不引入分布式锁；每个 assistant.tool_calls ID 都配对tool结果后保存，超出预算也回传错误，不突破四次模型/八次工具。TraceEvent保留既有字段，不记录凭据、请求头或隐藏推理，不存在记录404 TRACE_NOT_FOUND。失败仍可恢复此前真实状态，不能将 failed 当 completed。

## 售后和知识契约

八工具单注册表：SearchKnowledgeArgs（非空query、product_id可空、top_k 1–3）、PrepareAfterSalesArgs（order_id/reason可省略或null，缺项保存后追问）、GetAfterSalesArgs（preview_id可省略，恢复当前记录）。HTTP预览仍要求session_id/order_id/reason；原因最多500字符，去空格后至少两字符且不能只写退货/售后等流程名称；订单号最多100字符。SessionState包含after_sales_draft:dict[str,str]，active_task包含knowledge；导购切换保留草稿/售后ID，换订单清旧原因。

AfterSalesPreview包含policy_sources:PolicyReference[]（document_id/title/excerpt），为确定性规则来源快照；policy_source_ids为文档ID。KnowledgeHit仍为实际chunk_id/document_id/title/excerpt/score，score为余弦相似度，不是可信概率。每轮引用清空后只接受本轮成功检索；search_knowledge工具data为hits、evidence_status（retrieved|insufficient）及证据边界说明。规则引用与检索证据不可混淆。

资格要求当前用户、已签收、非未来签收时间、签收起不超过7×24小时（含等于）、订单与全部商品policy_id一致且允许、原因完整。未知/禁止政策、运输中、超期422 INELIGIBLE；金额仅用订单paid_total_fen快照，确认时条件/政策/金额变化409 STATE_CONFLICT，不使用当前售价。

pending有效十分钟，application_id=null；专用界面确认才pending→submitted，事务重查，重复/并发同ID。cancelled/expired不能提交；submitted取消409，重复取消返回cancelled；过期410 PREVIEW_EXPIRED且持久化expired。确认/取消绑定会话和用户，越权或不存在404 AFTER_SALES_NOT_FOUND/SESSION_NOT_FOUND。成功只表示“模拟售后申请已保存”，无商家批准或退款承诺。

缺配置/维度/语料503 KNOWLEDGE_UNAVAILABLE；真实上游失败503 EMBEDDING_FAILED（安全错误类型/HTTP状态）；维度不符503 EMBEDDING_DIMENSION_MISMATCH；非法响应502 EMBEDDING_INVALID_RESPONSE；语料模型不一致KNOWLEDGE_MODEL_MISMATCH；来源冲突409 KNOWLEDGE_SOURCE_CONFLICT。不相关/不足证据返回空hits/insufficient，不推导资料未覆盖的运费、法律或保修批准。

本地TEI无鉴权，Key可留空或使用local-no-secret占位值；仅本地embedding绕过环境代理。OpenAI-compatible请求显式float输出；检索失败清除旧引用，不注册confirm_after_sales。实际模型维度及检索验证范围见 [验收说明](ACCEPTANCE_AND_RELEASE.md)。

## 只读管理契约

`GET /api/demo/status?session_id=...` → DemoStatus。session_id 可省略，提供时长度1–100且按当前顾客校验；不存在/不属于返回404 SESSION_NOT_FOUND。省略时不查询执行记录。打开页面不发聊天调用，不接受修改请求。

- backend/database/embedding/chat：ServiceStatus，status=available|unavailable|not_checked，checked_at=含时区时间或null，detail为安全说明。聊天为最近真实调用的历史结果，不表示刚刚探测；旧记录无时间为未检查。embedding为本地/health检查；非本地地址不额外探测。
- chat_model、embedding_model、embedding_dimension：配置的模型标识和实测保存的维度；sources、document_count、chunk_count、corpus_models（model/dimension）：本项目实际入库信息。数据库不可用时统计未知，界面不将返回的默认零值宣称为实际数量。
- executions：当前会话最近十条请求缓存对应的 ExecutionRecord，含 request_id、status=completed|needs_input|failed、checked_at、steps。ExecutionStep含tool_name、duration_ms、error、checked_at、sources；sources沿用真实KnowledgeHit（document_id、chunk_id、标题、片段、score）。score不是可信概率。

TraceEvent包含checked_at（旧记录null）和sources（旧记录空）。仅真实检索成功保存当次来源，失败为空。管理快照不含arguments_summary、原始请求/响应、密钥、地址、个人路径、隐藏推理或日志。请求失败清旧快照并显式重试；完整评测/能力接口仍501。

## MCP契约

stdio MCP，官方SDK1.30.0；list_tools仅两个只读工具，不注册售后确认或写入工具。业务数据为合成演示数据库，顾客由服务配置注入，客户端不能指定其他顾客。

| 工具 | 输入 | 成功 structuredContent |
|---|---|---|
| search_products | query:string=''；budget_max_fen:非负整数或null；use_case:string或null；in_stock_only:boolean=true；limit:整数1–6，默认6 | `{ "result": [Product, ...] }`；无匹配为`{ "result": [] }` |
| get_order | order_id:必填非空字符串；去除两端空白，纯空白拒绝 | Order，含paid_total_fen历史实付、items快照、物流和状态 |

SDK生成并发布inputSchema/outputSchema，数值与布尔输入严格校验（不接受字符串limit）；参数错误返回CallToolResult.isError=true及校验文本。订单缺失/非当前顾客：isError=true，文本含ORDER_NOT_FOUND；空白号含INVALID_ARGUMENT；数据库连接失败/超时含DEPENDENCY_UNAVAILABLE。失败没有成功结构化业务结果，客户端必须先检查isError再读取structuredContent。MCP不套用HTTP状态码或Agent的ToolResult外壳。

生命周期只管理连接池，不初始化表或写业务数据；正常关闭stdin后释放池。stdout仅JSON-RPC、日志stderr。独立启动/调用方式见README，聊天Agent仍原生调用本地八工具。

## CLI评测报告

run_eval使用EvalReport字段：checked_at、git_commit（本地无提交为null）、environment、case_count、passed、failed、not_run、cases。case包含case_id/mode/assertions/status/duration_ms/evidence；失败有failure_kind（environment或business_or_assertion）及安全错误说明；在线程序通过有manual_review=pending，正文语义需另行核验。

二十个案例一次全量；修复后--cases选择性执行。每次原报告时间戳归档；已有二十案例baseline时，最新副本合并受影响结果，并保留每例重跑日期。不重置或掩盖首次失败。缺聊天配置在线not_run；实际依赖异常failed/environment；受控预期故障和恢复均满足断言才passed。CLI不改变两个501HTTP接口，也不让管理页读取本地产物。

## 本地页面托管边界

业务接口与字段未改变。本地部署与 API 同源 127.0.0.1:8000；开发页面仍为 5173，代理 `/api`。启用生产页面后，GET/HEAD 的未知 API、缺失静态资源或含隐藏路径段的请求（如 `/.env`、`/.git/config`）返回 404 JSON（`NOT_FOUND` 与现有 ApiError），不能回退成 HTML或返回隐藏文件；其他不支持的方法保持 404/405。`/docs`、`/redoc`、`/openapi.json` 保留原用途；已有构建资源正常返回，其他无扩展名页面路径可回退入口并刷新。
