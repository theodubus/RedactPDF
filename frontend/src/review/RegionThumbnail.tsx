import { useEffect, useRef, useState } from "react";

import type { PdfDoc } from "./pdfTypes";
import type { CoveredArea } from "./reviewItems";

// L'outil ne sait pas lire l'image, alors il la montre à quelqu'un qui sait.
// C'est tout l'objet de ce composant : rendre la zone telle qu'elle est, à une
// taille où un nom ou un numéro se lisent, et laisser la décision à l'humain.

// La vignette doit être lisible, pas décorative : si on n'y déchiffre pas un nom,
// l'étape ne sert à rien. On rend donc à une échelle nettement supérieure à la
// taille d'affichage, et le CSS ramène le tout à la largeur du panneau.
const TARGET_WIDTH_PX = 700;
const RENDER_OVERSAMPLE = 2;
const MAX_SCALE = 8;

// Ce qui est déjà traité se dessine par-dessus, pour que la décision porte sur ce
// qui reste. Un rectangle posé à la main est une décision prise : trait plein.
// Une proposition automatique (OCR, quand il existera) n'en est pas une : trait
// pointillé, et une teinte différente. La distinction est le point, pas la
// décoration : confondre les deux ferait lire une suggestion comme une garantie.
const COVER_STYLE: Record<CoveredArea["source"], { stroke: string; fill: string; dash: number[] }> = {
  manual: { stroke: "#1c7c4a", fill: "rgba(28, 124, 74, 0.22)", dash: [] },
  ocr: { stroke: "#b8860b", fill: "rgba(184, 134, 11, 0.16)", dash: [6, 4] },
};

export function RegionThumbnail(props: {
  doc: PdfDoc | null;
  page: number;
  bbox?: [number, number, number, number];
  covered?: CoveredArea[];
  /** Vrai : rendu à taille lisible, le conteneur défile. Faux : ajusté au panneau. */
  zoomed?: boolean;
  label: string;
}) {
  const { doc, page, bbox, covered, zoomed, label } = props;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!doc) return;
    let active = true;

    (async () => {
      const pdfPage = await doc.getPage(page + 1);

      // Sans boîte (cas d'une police illisible), on montre la page entière : on
      // ne sait pas *où* est le texte concerné, justement parce qu'on ne sait pas
      // le lire.
      const full = pdfPage.getViewport({ scale: 1 });
      const region = bbox ?? [0, 0, full.width, full.height];
      const width = Math.max(1, region[2] - region[0]);
      const height = Math.max(1, region[3] - region[1]);

      const scale = Math.min(
        MAX_SCALE,
        Math.max(1, (TARGET_WIDTH_PX / width) * RENDER_OVERSAMPLE),
      );
      const viewport = pdfPage.getViewport({ scale });

      const offscreen = document.createElement("canvas");
      offscreen.width = Math.ceil(viewport.width);
      offscreen.height = Math.ceil(viewport.height);
      const offCtx = offscreen.getContext("2d");
      if (!offCtx) return;

      await pdfPage.render({ canvasContext: offCtx, viewport }).promise;
      if (!active) return;

      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx) return;

      canvas.width = Math.ceil(width * scale);
      canvas.height = Math.ceil(height * scale);
      // Le CSS s'occupe de la taille affichée (100 % du panneau) ; le canvas est
      // sur-échantillonné pour rester net.
      canvas.style.removeProperty("width");
      ctx.drawImage(
        offscreen,
        region[0] * scale,
        region[1] * scale,
        canvas.width,
        canvas.height,
        0,
        0,
        canvas.width,
        canvas.height,
      );

      // Les boîtes arrivent en coordonnées PDF, comme `region` : même repère, il
      // suffit de retrancher l'origine de la zone et d'appliquer l'échelle.
      ctx.lineWidth = Math.max(1, scale);
      for (const area of covered ?? []) {
        const style = COVER_STYLE[area.source];
        const x = (area.bbox[0] - region[0]) * scale;
        const y = (area.bbox[1] - region[1]) * scale;
        const w = (area.bbox[2] - area.bbox[0]) * scale;
        const h = (area.bbox[3] - area.bbox[1]) * scale;
        ctx.setLineDash(style.dash.map((d) => d * scale));
        ctx.fillStyle = style.fill;
        ctx.strokeStyle = style.stroke;
        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x, y, w, h);
      }
      ctx.setLineDash([]);
    })().catch(() => {
      if (active) setFailed(true);
    });

    return () => {
      active = false;
    };
  }, [doc, page, bbox, covered]);

  if (failed) return <div className="thumbFailed">{label}</div>;
  return (
    <canvas
      ref={canvasRef}
      className={zoomed ? "reviewThumb reviewThumbZoomed" : "reviewThumb"}
      aria-label={label}
    />
  );
}
