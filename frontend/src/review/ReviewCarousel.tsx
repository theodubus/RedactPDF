import { useMemo, useState } from "react";

import { RegionThumbnail } from "./RegionThumbnail";
import { allConfirmed, coverageFor, reviewSteps } from "./reviewItems";
import type { PdfDoc } from "./pdfTypes";
import type { CoveredArea, ReviewItem } from "./reviewItems";

// Un bouton par écran, jamais une validation d'ensemble. La friction est le
// point : une case « tout confirmer » se coche sans regarder, et c'est
// exactement ce que cette étape doit empêcher.
//
// Ne défilent ici que les zones que le moteur n'a pas su lire. Les rectangles
// dessinés à la main n'y sont pas : ils y étaient, ils n'apportaient rien, et la
// friction dépensée à les reconfirmer n'était plus disponible pour ce qui compte.
// Ils apparaissent en surimpression, comme déjà traité.

const LABEL_KEY: Record<ReviewItem["kind"], string> = {
  opaque: "review.item.opaque",
  font: "review.item.font",
};

export function ReviewCarousel(props: {
  t: (k: string) => string;
  doc: PdfDoc | null;
  items: ReviewItem[];
  covered: CoveredArea[];
  onConfirmAll: () => void;
  onCancel: () => void;
}) {
  const { t, doc, items, covered, onConfirmAll, onCancel } = props;
  const [confirmed, setConfirmed] = useState<ReadonlySet<string>>(new Set());
  const [index, setIndex] = useState(0);
  // Ajusté par défaut : la zone entière tient à l'écran, donc rien n'est caché.
  // Agrandi à la demande : une page scannée réduite à la hauteur du panneau ne se
  // lit plus, et une vignette illisible ne vaut pas mieux que pas de vignette.
  const [zoomed, setZoomed] = useState(false);

  const steps = useMemo(() => reviewSteps(items), [items]);
  const done = useMemo(() => allConfirmed(steps, confirmed), [steps, confirmed]);
  const current = steps[Math.min(index, steps.length - 1)];
  const overlays = useMemo(
    () => (current ? coverageFor(current.head, covered) : []),
    [current, covered],
  );
  if (!current) return null;

  const head = current.head;

  const confirm = () => {
    const next = new Set(confirmed);
    next.add(head.id);
    setConfirmed(next);
    const remaining = steps.findIndex((s) => !next.has(s.head.id));
    if (remaining >= 0) setIndex(remaining);
  };

  const goTo = (i: number) => {
    setIndex(i);
    setZoomed(false);
  };

  // « page 3 » ou « 4 pages » : une image répétée est la même image, montrée une
  // fois, mais l'utilisateur doit savoir sur combien de pages porte son clic.
  const scope =
    current.pages.length > 1
      ? `${current.pages.length} ${t("review.pages")}`
      : `${t("review.page")} ${head.page + 1}`;

  return (
    <div className="reviewOverlay" role="dialog" aria-modal="true">
      <div className="reviewPanel">
        <div className="reviewTitle">{t("review.title")}</div>
        <p className="reviewIntro">{t("review.intro")}</p>

        <div className="reviewCount">
          {confirmed.size} / {steps.length}
        </div>

        <div className="reviewItem">
          <div className="reviewItemLabel">
            {t(LABEL_KEY[head.kind])} &middot; {scope}
          </div>
          <RegionThumbnail
            doc={doc}
            page={head.page}
            bbox={head.kind === "font" ? undefined : head.bbox}
            covered={overlays}
            zoomed={zoomed}
            label={t(LABEL_KEY[head.kind])}
          />
          <button type="button" className="reviewZoom" onClick={() => setZoomed((z) => !z)}>
            {zoomed ? t("review.fit") : t("review.zoom")}
          </button>
          <p className="reviewItemHint">{t(`${LABEL_KEY[head.kind]}.hint`)}</p>
          {overlays.length > 0 && (
            <p className="reviewCoverageHint">
              {overlays.length} {t("review.covered")}
            </p>
          )}
        </div>

        <div className="reviewNav">
          {steps.map((step, i) => (
            <button
              key={step.head.id}
              type="button"
              className={`reviewDot${confirmed.has(step.head.id) ? " done" : ""}${i === index ? " active" : ""}`}
              onClick={() => goTo(i)}
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
          <button type="button" onClick={confirm} disabled={confirmed.has(head.id)}>
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
