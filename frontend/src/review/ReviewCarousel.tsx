import { useMemo, useState } from "react";

import { RegionThumbnail } from "./RegionThumbnail";
import { allConfirmed } from "./reviewItems";
import type { PdfDoc } from "./pdfTypes";
import type { ReviewItem } from "./reviewItems";

// Un bouton par élément, jamais une validation d'ensemble. La friction est le
// point : une case « tout confirmer » se coche sans regarder, et c'est
// exactement ce que cette étape doit empêcher.

const LABEL_KEY: Record<ReviewItem["kind"], string> = {
  rect: "review.item.rect",
  opaque: "review.item.opaque",
  font: "review.item.font",
};

export function ReviewCarousel(props: {
  t: (k: string) => string;
  doc: PdfDoc | null;
  items: ReviewItem[];
  onConfirmAll: () => void;
  onCancel: () => void;
}) {
  const { t, doc, items, onConfirmAll, onCancel } = props;
  const [confirmed, setConfirmed] = useState<ReadonlySet<string>>(new Set());
  const [index, setIndex] = useState(0);

  const done = useMemo(() => allConfirmed(items, confirmed), [items, confirmed]);
  const current = items[Math.min(index, items.length - 1)];
  if (!current) return null;

  const confirm = () => {
    const next = new Set(confirmed);
    next.add(current.id);
    setConfirmed(next);
    const remaining = items.findIndex((i) => !next.has(i.id));
    if (remaining >= 0) setIndex(remaining);
  };

  return (
    <div className="reviewOverlay" role="dialog" aria-modal="true">
      <div className="reviewPanel">
        <div className="reviewTitle">{t("review.title")}</div>
        <p className="reviewIntro">{t("review.intro")}</p>

        <div className="reviewCount">
          {confirmed.size} / {items.length}
        </div>

        <div className="reviewItem">
          <div className="reviewItemLabel">
            {t(LABEL_KEY[current.kind])} {t("review.page")} {current.page + 1}
          </div>
          <RegionThumbnail
            doc={doc}
            page={current.page}
            bbox={current.kind === "font" ? undefined : current.bbox}
            label={t(LABEL_KEY[current.kind])}
          />
          <p className="reviewItemHint">{t(`${LABEL_KEY[current.kind]}.hint`)}</p>
        </div>

        <div className="reviewNav">
          {items.map((item, i) => (
            <button
              key={item.id}
              type="button"
              className={`reviewDot${confirmed.has(item.id) ? " done" : ""}${i === index ? " active" : ""}`}
              onClick={() => setIndex(i)}
              aria-label={`${i + 1}`}
            >
              {i + 1}
            </button>
          ))}
        </div>

        <div className="reviewActions">
          <button type="button" onClick={onCancel}>
            {t("review.cancel")}
          </button>
          <button type="button" onClick={confirm} disabled={confirmed.has(current.id)}>
            {t("review.checked")}
          </button>
          <button type="button" className="primary" onClick={onConfirmAll} disabled={!done}>
            {t("review.export")}
          </button>
        </div>
      </div>
    </div>
  );
}
