"""确定性单品满减规则，金额统一为分。"""
from app.schemas import Offer

def calculate_offer(list_price_fen: int, promotion_eligible: bool) -> Offer:
    """仅适用商品原价满 20000 分减 2000 分，无叠加规则。"""
    if isinstance(list_price_fen, bool) or not isinstance(list_price_fen, int) or list_price_fen < 0:
        raise ValueError('原价必须是非负整数分')
    if not isinstance(promotion_eligible, bool):
        raise ValueError('优惠适用标记必须是布尔值')
    discount = 2000 if promotion_eligible and list_price_fen >= 20000 else 0
    return Offer(list_price_fen=list_price_fen, discount_fen=discount, sale_price_fen=list_price_fen - discount, promotion_label='满200元减20元' if discount else None)
