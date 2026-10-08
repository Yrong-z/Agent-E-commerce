"""商品检索、详情和固定字段比较的唯一业务入口。"""
from app.schemas import Product, Comparison, ComparisonRow, ReviewSummary, SearchProductsArgs, CompareProductsRequest, DomainError
from app.adapters.commerce import MockCommerceAdapter
from app.services.pricing import calculate_offer

async def search_products(query: str = '', budget_max_fen: int | None = None, use_case: str | None = None, in_stock_only: bool = True, limit: int = 6) -> list[Product]:
    """按文字、当前到手价、用途与库存筛选，稳定返回最多六款。"""
    args = SearchProductsArgs(query=query, budget_max_fen=budget_max_fen, use_case=use_case, in_stock_only=in_stock_only, limit=limit)
    matches = []
    for record in await MockCommerceAdapter().read_products():
        product = _priced_product(record)
        searchable = ' '.join([product.product_id, product.name, product.category, *product.use_cases]).casefold()
        if args.query.strip().casefold() not in searchable:
            continue
        if args.budget_max_fen is not None and product.sale_price_fen > args.budget_max_fen:
            continue
        if args.use_case and args.use_case not in product.use_cases:
            continue
        if args.in_stock_only and product.stock <= 0:
            continue
        matches.append(product)
    return matches[:args.limit]

def _priced_product(record: dict) -> Product:
    """读取时统一计算优惠，过滤与详情使用同一价格来源。"""
    offer = calculate_offer(record['list_price_fen'], record['promotion_eligible'])
    return Product.model_validate({**record, **offer.model_dump()})

async def get_product(product_id: str) -> Product:
    """读取数据库商品事实，未知 ID 明确失败。"""
    for record in await MockCommerceAdapter().read_products():
        if record['product_id'] == product_id:
            return _priced_product(record)
    raise DomainError('PRODUCT_NOT_FOUND', '未找到该商品')

async def compare_products(product_ids: list[str]) -> Comparison:
    """比较正好两款不同商品；缺参数保持 null，不补造推荐。"""
    args = CompareProductsRequest(product_ids=product_ids)
    products = [await get_product(product_id) for product_id in args.product_ids]
    fields = [
        ('sale_price_fen', '到手价（分）', [p.sale_price_fen for p in products]),
        ('wearing_style', '佩戴', [p.specs.wearing_style for p in products]),
        ('anc', '主动降噪', [p.specs.anc for p in products]),
        ('battery_hours', '续航（小时）', [p.specs.battery_hours for p in products]),
        ('stock', '库存', [p.stock for p in products]),
    ]
    return Comparison(product_ids=args.product_ids, rows=[ComparisonRow(field=field, label=label, values=values) for field,label,values in fields], recommendation_basis=['依据数据库商品参数、当前到手价和库存进行固定字段比较；未知参数显示未知。'])

async def summarize_reviews(product_id: str, reviews: list[dict]) -> ReviewSummary:
    """评价摘要扩展签名；不注册工具，尚未实现。"""
    raise NotImplementedError('评价摘要仅预留')
