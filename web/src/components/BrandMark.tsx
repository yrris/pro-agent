// 品牌星芒（替代字符「✳」）：8 向圆头短射线，视觉对齐 Claude 的 sunburst 记号。
// currentColor 取色，尺寸由 className 控制（默认 size-8）。
export function BrandMark({ className = "size-8" }: { className?: string }) {
  const rays = Array.from({ length: 8 }, (_, i) => {
    const angle = (i * Math.PI) / 4;
    const r1 = 4.6;
    const r2 = 10.4;
    return {
      x1: 12 + r1 * Math.cos(angle),
      y1: 12 + r1 * Math.sin(angle),
      x2: 12 + r2 * Math.cos(angle),
      y2: 12 + r2 * Math.sin(angle),
    };
  });
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <g stroke="currentColor" strokeWidth={2.4} strokeLinecap="round">
        {rays.map((r, i) => (
          <line key={i} x1={r.x1} y1={r.y1} x2={r.x2} y2={r.y2} />
        ))}
      </g>
    </svg>
  );
}
