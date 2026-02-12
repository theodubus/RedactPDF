import { useEffect, useMemo, useRef, useState } from "react";

type PdfPageProxy = {
  getViewport: (params: { scale: number }) => { width: number; height: number };
  render: (params: {
    canvasContext: CanvasRenderingContext2D;
    viewport: { width: number; height: number };
  }) => { promise: Promise<void> };
};

type PdfDocumentProxy = {
  numPages: number;
  getPage: (pageNumber: number) => Promise<PdfPageProxy>;
  destroy: () => void;
};

type PdfJsLib = {
  GlobalWorkerOptions: { workerSrc: string };
  getDocument: (params: { data: Uint8Array }) => { promise: Promise<PdfDocumentProxy> };
};


const PDFJS_SCRIPT_URL =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.8.69/pdf.min.mjs";
const PDFJS_WORKER_URL =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.8.69/pdf.worker.min.mjs";

async function ensurePdfJsLoaded(): Promise<PdfJsLib> {
  const lib = (await import(/* @vite-ignore */ PDFJS_SCRIPT_URL)) as unknown as PdfJsLib;
  lib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
  return lib;
}

export function PdfViewer(props: {
  file: File;
  t: (k: string) => string;
}) {
  const { file, t } = props;

  const [pdfDoc, setPdfDoc] = useState<PdfDocumentProxy | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRefs = useRef<Array<HTMLCanvasElement | null>>([]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const updateWidth = () => {
      setContainerWidth(Math.max(320, Math.floor(el.clientWidth)));
    };

    updateWidth();

    const observer = new ResizeObserver(updateWidth);
    observer.observe(el);

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let active = true;
    let loadedDoc: PdfDocumentProxy | null = null;

    setPdfDoc(null);
    setError(null);
    setIsLoading(true);

    (async () => {
      try {
        const pdfjsLib = await ensurePdfJsLoaded();
        const bytes = new Uint8Array(await file.arrayBuffer());
        const doc = await pdfjsLib.getDocument({ data: bytes }).promise;
        loadedDoc = doc;

        if (!active) {
          doc.destroy();
          return;
        }

        setPdfDoc(doc);
      } catch {
        if (!active) return;
        setError(t("viewer.error.load"));
      } finally {
        if (active) setIsLoading(false);
      }
    })();

    return () => {
      active = false;
      if (loadedDoc) loadedDoc.destroy();
    };
  }, [file, t]);

  const pageNumbers = useMemo(() => {
    if (!pdfDoc) return [];
    return Array.from({ length: pdfDoc.numPages }, (_, i) => i + 1);
  }, [pdfDoc]);

  useEffect(() => {
    if (!pdfDoc || containerWidth <= 0) return;

    let cancelled = false;

    (async () => {
      for (const pageNumber of pageNumbers) {
        if (cancelled) return;

        const canvas = canvasRefs.current[pageNumber - 1];
        if (!canvas) continue;

        const page = await pdfDoc.getPage(pageNumber);
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = containerWidth / baseViewport.width;
        const viewport = page.getViewport({ scale });

        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);

        const context = canvas.getContext("2d");
        if (!context) continue;

        await page.render({ canvasContext: context, viewport }).promise;
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pdfDoc, pageNumbers, containerWidth]);

  if (error) {
    return <div className="pdfViewerMessage bad">{error}</div>;
  }

  return (
    <div className="pdfViewer" ref={containerRef} aria-label={t("viewer.title")}>
      {isLoading ? <div className="pdfViewerMessage muted">{t("viewer.loading")}</div> : null}

      <div className="pdfCanvasStack" aria-live="polite">
        {pageNumbers.map((pageNumber) => (
          <canvas
            key={pageNumber}
            className="pdfCanvas"
            ref={(el) => {
              canvasRefs.current[pageNumber - 1] = el;
            }}
          />
        ))}
      </div>
    </div>
  );
}
