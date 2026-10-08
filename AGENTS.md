# 选购助手协作规则

## 开工前

依次读取 README.md、docs/ARCHITECTURE.md、docs/CONTRACTS.md、docs/ACCEPTANCE_AND_RELEASE.md，检查实际代码和用户本轮范围。公开协作规则只依赖仓库公开文件；开发期间的内部进度与设计资料按用户会话指令维护，不能成为公开阅读路径的缺失依赖。

## UI 技能入口

优化已有界面前，完整读取 [.agents/skills/redesign-existing-projects/SKILL.md](.agents/skills/redesign-existing-projects/SKILL.md)，按审查、诊断、局部改进顺序应用。技能来源、固定版本与 MIT 许可见同目录 [SOURCE.md](.agents/skills/redesign-existing-projects/SOURCE.md) 和 [LICENSE](.agents/skills/redesign-existing-projects/LICENSE)。当前会话未自动列出该技能时，通过此入口显式读取；文件安装不等于自动加载。用户范围及本项目规则优先：保留中文系统字体、现有 CSS 与四页业务，不采用外部字体、装饰内容、复杂动画或额外框架。

## 范围与技术

保持 React + TypeScript + Vite、自定义 CSS；Python + FastAPI + Pydantic；PostgreSQL + pgvector。聊天与 embedding 独立配置，单 Agent + 原生 Tool Calling；MCP 使用官方 Python SDK。不要引入 Redis、消息队列、微服务、复杂权限、通用插件平台或第二套 Agent 框架。

按已授权模块完成端到端小功能，不顺手扩展购物车、支付或企业系统。完整骨架已获用户授权；预留签名不等于功能实现。英文文件/标识符便于工具链工作，关键入口附中文职责；Python 用 snake_case，React 用 PascalCase，TypeScript 函数用 camelCase。

## 业务与数据

金额为整数分，预算按当前到手价筛选，优惠由确定性代码计算；订单金额保留历史实付。事实来自数据库或真实工具结果，缺参数显示未知，无匹配不编造。演示种子只能幂等更新本项目来源记录，不清空其他数据。

工具参数用 Pydantic 校验，未知工具明确失败；尚未实现工具不注册给模型或 MCP。模型不持有数据库凭据。售后必须显式界面确认并保证重复确认不重复建单；未实现时明确标注，不显示静态成功。

禁止硬编码助手回复、字符哈希向量、假进度或假操作冒充在线模型、语义检索和实际执行。首版不流式输出；等待状态明确，请求失败保留输入，显式重试，不自动反复调用模型。

## 验证与维护

实现必须有可运行代码、实际结果与最少必要验证，页面/接口未联通不算完成。按 docs/ACCEPTANCE_AND_RELEASE.md 执行当前具备条件的检查；不写逐行镜像测试、不追求覆盖率、不重复未受变更影响的长检查。

新功能/演示更新 README，分层/入口更新 docs/ARCHITECTURE.md，接口/工具更新 docs/CONTRACTS.md，验证/交付更新 docs/ACCEPTANCE_AND_RELEASE.md。内部进度只维护用户指定的单一工作清单，不按模块创建重复说明。Pydantic/OpenAPI 与对应 TypeScript 是字段实际依据。

常规细节自行处理；新核心功能、技术栈改变或明显增加工期先说明具体影响再请求决定。环境阻塞先完成独立工作，明确记录缺项，不能删掉核心要求或伪造通过。

## 发布与边界

配置、密钥、日志、依赖、运行目录、个人机器信息、内部工作资料和原始阶段产物不进入公开跟踪；每次暂存使用明确范围并检查实际 Git 状态。忽略规则不能自动移除已跟踪文件。公开文档不得引用被排除的内部文件作为必需步骤。

不自动创建或发送外部消息；未获用户明确授权时，不上传 GitHub、不设置远端、不部署公开站点。项目许可证由用户决定，当前暂不添加；复用代码与图片保留原许可并记录来源和改动，不宣称全部自研。仓库提交身份使用 GitHub 隐藏邮箱，不能为发布修改全局 Git 配置或暴露个人邮箱。
