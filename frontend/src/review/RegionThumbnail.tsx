import { useEffect, useRef, useState } from "react";

import { previewUrl } from "./reviewItems";
import type { PdfDoc } from "./pdfTypes";
import type { CoveredArea, Preview } from "./reviewItems";

// L'outil ne sait pas lire l'image, alors il la montre à quelqu'un qui sait.
//
// Ce qu'on montre, c'est **l'image**, pas la région de page. Une version
// précédente rendait la région avec pdf.js, ce qui composait par dessus la couche
// texte, et cette couche est exactement ce que les règles ont su lire. Le
// relecteur voyait du texte net, en concluait « lisible, rien de caché », et
// jugeait autre chose que l'objet en question. Les pixels viennent donc du
// serveur, qui sait précisément quelle image il a signalée.
//
// Le rendu pdf.js reste, pour un seul cas : une police illisible, où il n'y a pas
// d'image du tout et où la zone concernée est la page entière.

export function RegionThumbnail(props: {
  preview?: Preview;
  covered?: CoveredArea[];
  doc: PdfDoc | null;
  page: number;
  label: string;
}) {
  const { preview, covered, doc, page, label } = props;

  if (preview) {
    return (
      <div className="thumbFrame">
        <img className="reviewThumb" src={previewUrl(preview)} alt={label} />
        {(covered ?? []).map((area, i) => (
          <span
            key={i}
            className={area.source === "ocr" ? "coverBox coverBoxOcr" : "coverBox"}
            style={{
              // Coordonnées déjà normalisées dans le repère de l'image par le
              // serveur : des pourcentages suffisent, et l'affichage reste juste
              // quelle que soit la taille rendue, agrandissement compris.
              left: `${area.bbox[0] * 100}%`,
              top: `${area.bbox[1] * 100}%`,
              width: `${(area.bbox[2] - area.bbox[0]) * 100}%`,
              height: `${(area.bbox[3] - area.bbox[1]) * 100}%`,
            }}
          />
        ))}
      </div>
    );
  }

  return <PageThumbnail doc={doc} page={page} label={label} />;
}

// La vignette doit être lisible, pas décorative : si on n'y déchiffre pas un nom,
// l'étape ne sert à rien. On rend donc à une échelle nettement supérieure à la
// taille d'affichage, et le CSS ramène le tout à la largeur du panneau.
const TARGET_WIDTH_PX = 700;
const RENDER_OVERSAMPLE = 2;
const MAX_SCALE = 8;

/** La page entière, pour une police illisible : on ne sait pas où est le texte. */
function PageThumbnail(props: { doc: PdfDoc | null; page: number; label: string }) {
  const { doc, page, label } = props;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!doc) return;
    let active = true;

    (async () => {
      const pdfPage = await doc.getPage(page + 1);
      const full = pdfPage.getViewport({ scale: 1 });
      const scale = Math.min(
        MAX_SCALE,
        Math.max(1, (TARGET_WIDTH_PX / full.width) * RENDER_OVERSAMPLE),
      );
      const viewport = pdfPage.getViewport({ scale });

      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx || !active) return;
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      await pdfPage.render({ canvasContext: ctx, viewport }).promise;
    })().catch(() => {
      if (active) setFailed(true);
    });

    return () => {
      active = false;
    };
  }, [doc, page]);

  if (failed) return <div className="thumbFailed">{label}</div>;
  return (
    <div className="thumbFrame">
      <canvas ref={canvasRef} className="reviewThumb" aria-label={label} />
    </div>
  );
}
