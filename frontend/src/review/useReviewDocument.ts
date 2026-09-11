import { useEffect, useState } from "react";

import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import type { PdfDoc, PdfLib } from "./pdfTypes";

// Le document est chargé une fois pour toute la revue plutôt qu'une fois par
// vignette : ouvrir un PDF de deux cents pages une fois par zone signalée serait
// absurde sur les documents où la revue sert le plus.
export function useReviewDocument(file: File | null): PdfDoc | null {
  const [doc, setDoc] = useState<PdfDoc | null>(null);

  useEffect(() => {
    if (!file) {
      setDoc(null);
      return;
    }
    let active = true;
    let loaded: PdfDoc | null = null;

    (async () => {
      const lib = (await import("pdfjs-dist")) as unknown as PdfLib;
      lib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
      const bytes = new Uint8Array(await file.arrayBuffer());
      const opened = await lib.getDocument({ data: bytes }).promise;
      loaded = opened;
      if (!active) {
        opened.destroy();
        return;
      }
      setDoc(opened);
    })().catch(() => setDoc(null));

    return () => {
      active = false;
      loaded?.destroy();
    };
  }, [file]);

  return doc;
}
