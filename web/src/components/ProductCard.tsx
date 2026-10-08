/** 真实接口商品卡片；合成数据和示意图明确标注。 */
import type { Product } from '../types';
interface Props { product: Product; selected?: boolean; selectionDisabled?: boolean; onSelect?: () => void; onDetail?: () => void }
export function ProductCard({ product, selected = false, selectionDisabled = false, onSelect, onDetail }: Props) {
  return <article className={`product-card ${selected ? 'selected' : ''}`} data-testid={`product-${product.product_id}`}>
    <div className="product-image"><img src={product.image_url} alt={`${product.name} · 中性耳机示意图`} /><span>合成商品 · 示意图</span></div>
    <div className="product-content"><h2>{product.name}</h2><p className="product-meta">{product.category} <span>{product.use_cases.join(' / ')}</span></p>
      <div className="product-price"><small className="price-label">到手价</small><strong>¥{(product.sale_price_fen / 100).toFixed(2)}</strong>{product.discount_fen > 0 && <del>¥{(product.list_price_fen / 100).toFixed(2)}</del>}<span className={product.stock > 0 ? 'stock' : 'no-stock'}>{product.stock > 0 ? `有货 · ${product.stock} 件` : '无货'}</span></div>
      {product.promotion_label ? <span className="promotion">{product.promotion_label}</span> : <small className="muted">无促销优惠</small>}
      <dl className="spec-list"><div><dt>佩戴</dt><dd>{product.specs.wearing_style ?? '未知'}</dd></div><div><dt>降噪</dt><dd>{product.specs.anc === null ? '未知' : product.specs.anc ? '主动降噪' : '无主动降噪'}</dd></div><div><dt>续航</dt><dd>{product.specs.battery_hours === null ? '未知' : `${product.specs.battery_hours} 小时`}</dd></div></dl>
      {onDetail && <button className="detail-button" onClick={onDetail} aria-label={`查看${product.name}详情`}>查看详情</button>}
      {onSelect && <label className="select-product"><input type="checkbox" checked={selected} disabled={selectionDisabled && !selected} onChange={onSelect} />选择 {product.name} 对比</label>}
    </div>
  </article>;
}
