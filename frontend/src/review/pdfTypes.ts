// Le sous-ensemble de pdf.js dont la revue a besoin, isolé pour que le hook et
// le composant vivent dans des fichiers séparés : react-refresh n'accepte pas
// qu'un module exporte à la fois un composant et autre chose.

export type PdfPage = {
  getViewport: (p: { scale: number }) => { width: number; height: number };
  render: (p: { canvasContext: CanvasRenderingContext2D; viewport: unknown }) => {
    promise: Promise<void>;
  };
};
export type PdfDoc = { getPage: (n: number) => Promise<PdfPage>; destroy: () => void };
export type PdfLib = {
  GlobalWorkerOptions: { workerSrc: string };
  getDocument: (p: { data: Uint8Array }) => { promise: Promise<PdfDoc> };
};

