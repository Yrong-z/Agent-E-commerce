# 数据目录

products.json 是 12 个明确合成的耳机 SKU，覆盖无货、超预算、不同用途和未知参数，不填销量/评分。orders.json 是三个已有演示订单的种子模板，signed_days_ago 仅供初始化生成相对日期，不是 HTTP 字段；订单金额是历史快照，不按当前商品价重算。

seed_demo_data 写入标记 shopping-assistant-demo-v1，仅更新已有同来源记录，不清表或覆盖其他来源的同名记录。重复运行刷新本项目订单的相对日期，数量不增加。客户 ID 由后端 DEMO_CUSTOMER_ID 注入。此数据与模拟读取适配器不代表真实商家/企业接入。

eval_cases.jsonl保存20个明确预期案例，api/scripts/run_eval.py实际执行。knowledge包含三份合成政策，先真实探测embedding维度再入库；文件存在不代表新环境已入库。
