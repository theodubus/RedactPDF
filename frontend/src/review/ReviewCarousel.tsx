import { useMemo, useState } from "react";

import { RegionThumbnail } from "./RegionThumbnail";
import { allConfirmed, reviewSteps } from "./reviewItems";
import type { PdfDoc } from "./pdfTypes";
import type { Preview, ReviewItem } from "./reviewItems";

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
  previews: Record<string, Preview>;
  onConfirmAll: () => void;
  onCancel: () => void;
}) {
  const { t, doc, items, previews, onConfirmAll, onCancel } = props;
  const [confirmed, setConfirmed] = useState<ReadonlySet<string>>(new Set());
  const [index, setIndex] = useState(0);
  // Ajusté par défaut : la zone entière tient à l'écran, donc rien n'est caché.
  // Agrandi à la demande : une page scannée réduite à la hauteur du panneau ne se
  // lit plus, et une vignette illisible ne vaut pas mieux que pas de vignette.
  const [zoomed, setZoomed] = useState(false);

  const steps = useMemo(() => reviewSteps(items), [items]);
  const done = useMemo(() => allConfirmed(steps, confirmed), [steps, confirmed]);
  const current = steps[Math.min(index, steps.length - 1)];
  if (!current) return null;

  const head = current.head;
  const overlays = head.kind === "opaque" ? head.covered : [];
  const preview = head.kind === "opaque" ? previews[head.digest] : undefined;
  // Comptées à part, et dites à part : un rectangle posé à la main est une
  // décision prise, une proposition n'en est pas une. Les additionner sous
  // « déjà couvert » ferait lire la suggestion comme une garantie, ce que toute
  // la mise en forme du dessous s'applique justement à éviter.
  const manualCount = overlays.filter((a) => a.source === "manual").length;
  const proposedCount = overlays.filter((a) => a.source === "ocr").length;

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

        <div className={zoomed ? "reviewItem reviewItemZoomed" : "reviewItem"}>
          <div className="reviewItemLabel">
            {t(LABEL_KEY[head.kind])} &middot; {scope}
          </div>
          <RegionThumbnail
            preview={preview}
            covered={overlays}
            doc={doc}
            page={head.page}
            label={t(LABEL_KEY[head.kind])}
          />
          <button type="button" className="reviewZoom" onClick={() => setZoomed((z) => !z)}>
            {zoomed ? t("review.fit") : t("review.zoom")}
          </button>
          <p className="reviewItemHint">
            {t(head.kind === "opaque" && !preview
              ? "review.item.opaque.nopreview"
              : `${LABEL_KEY[head.kind]}.hint`)}
          </p>
          {manualCount > 0 && (
            <p className="reviewCoverageHint">
              {manualCount} {t("review.covered")}
            </p>
          )}
          {proposedCount > 0 && (
            <p className="reviewCoverageHint reviewProposedHint">
              {proposedCount} {t("review.proposed")}
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
