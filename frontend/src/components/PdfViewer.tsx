import { useEffect, useMemo, useRef, useState } from "react";
import type { UiRule } from "../types/uiRules";

type PdfViewport = {
  width: number;
  height: number;
  transform: number[];
};

type PdfTextContent = {
  items: unknown[];
};

type PdfPageProxy = {
  getViewport: (params: { scale: number }) => PdfViewport;
  getTextContent: () => Promise<PdfTextContent>;
  render: (params: {
    canvasContext: CanvasRenderingContext2D;
    viewport: PdfViewport;
    transform?: number[];
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
  TextLayer: new (params: {
    textContentSource: PdfTextContent;
    container: HTMLDivElement;
    viewport: PdfViewport;
  }) => { render: () => Promise<void> };
};

const PDFJS_SCRIPT_URL = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.8.69/pdf.min.mjs";
const PDFJS_WORKER_URL = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.8.69/pdf.worker.min.mjs";

async function ensurePdfJsLoaded(): Promise<PdfJsLib> {
  const lib = (await import(/* @vite-ignore */ PDFJS_SCRIPT_URL)) as unknown as PdfJsLib;
  lib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
  return lib;
}

export function PdfViewer(props: {
  file: File;
  rules: UiRule[];
  t: (k: string) => string;
}) {
  const { file, rules, t } = props;

  const [pdfDoc, setPdfDoc] = useState<PdfDocumentProxy | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRefs = useRef<Array<HTMLCanvasElement | null>>([]);
  const textLayerRefs = useRef<Array<HTMLDivElement | null>>([]);
  const previewLayerRefs = useRef<Array<HTMLDivElement | null>>([]);
  const pdfjsRef = useRef<PdfJsLib | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const updateWidth = () => {
      setContainerWidth(Math.max(320, Math.floor(el.clientWidth) - 20));
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
        pdfjsRef.current = pdfjsLib;

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
    if (!pdfDoc || containerWidth <= 0 || !pdfjsRef.current) return;

    let cancelled = false;
    const pdfjsLib = pdfjsRef.current;

    (async () => {
      for (const pageNumber of pageNumbers) {
        if (cancelled) return;

        const page = await pdfDoc.getPage(pageNumber);
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = containerWidth / baseViewport.width;
        const viewport = page.getViewport({ scale });

        const canvas = canvasRefs.current[pageNumber - 1];
        const textLayer = textLayerRefs.current[pageNumber - 1];
        const previewLayer = previewLayerRefs.current[pageNumber - 1];
        if (!canvas || !textLayer || !previewLayer) continue;

        const displayWidth = viewport.width;
        const displayHeight = viewport.height;
        const outputScale = window.devicePixelRatio || 1;

        canvas.style.width = `${displayWidth}px`;
        canvas.style.height = `${displayHeight}px`;
        canvas.width = Math.floor(displayWidth * outputScale);
        canvas.height = Math.floor(displayHeight * outputScale);

        const layerWidth = `${displayWidth}px`;
        const layerHeight = `${displayHeight}px`;

        textLayer.style.width = layerWidth;
        textLayer.style.height = layerHeight;
        textLayer.style.setProperty("--scale-factor", String(scale));
        textLayer.replaceChildren();

        previewLayer.style.width = layerWidth;
        previewLayer.style.height = layerHeight;
        previewLayer.replaceChildren();

        const context = canvas.getContext("2d");
        if (!context) continue;

        await page.render({
          canvasContext: context,
          viewport,
          transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
        }).promise;

        const textContent = await page.getTextContent();
        const textLayerTask = new pdfjsLib.TextLayer({
          textContentSource: textContent,
          container: textLayer,
          viewport,
        });
        await textLayerTask.render();
        applyPreviewHighlights(textLayer, previewLayer, rules);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pdfDoc, pageNumbers, containerWidth, rules]);

  useEffect(() => {
    for (const [index, textLayer] of textLayerRefs.current.entries()) {
      const previewLayer = previewLayerRefs.current[index];
      if (!textLayer || !previewLayer) continue;
      applyPreviewHighlights(textLayer, previewLayer, rules);
    }
  }, [rules]);

  if (error) {
    return <div className="pdfViewerMessage bad">{error}</div>;
  }

  return (
    <div className="pdfViewer" ref={containerRef} aria-label={t("viewer.title")}>
      {isLoading ? <div className="pdfViewerMessage muted">{t("viewer.loading")}</div> : null}

      <div className="pdfCanvasStack" aria-live="polite">
        {pageNumbers.map((pageNumber) => (
          <div key={pageNumber} className="pdfPage">
            <canvas
              className="pdfCanvas"
              ref={(el) => {
                canvasRefs.current[pageNumber - 1] = el;
              }}
            />
            <div
              className="pdfPreviewLayer"
              ref={(el) => {
                previewLayerRefs.current[pageNumber - 1] = el;
              }}
            />
            <div
              className="pdfTextLayer textLayer"
              ref={(el) => {
                textLayerRefs.current[pageNumber - 1] = el;
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function applyPreviewHighlights(
  textLayer: HTMLDivElement,
  previewLayer: HTMLDivElement,
  rules: UiRule[],
) {
  previewLayer.replaceChildren();
  if (!rules.length) return;

  const layerBounds = textLayer.getBoundingClientRect();
  if (!layerBounds.width || !layerBounds.height) return;

  const spans = textLayer.querySelectorAll("span");
  for (const span of spans) {
    const textNode = span.firstChild;
    if (!textNode || textNode.nodeType !== Node.TEXT_NODE) continue;

    const raw = textNode.textContent ?? "";
    if (!raw) continue;

    const ranges = collectMatches(raw, rules);
    if (ranges.length === 0) continue;

    for (const rangeDef of ranges) {
      const range = document.createRange();
      range.setStart(textNode, rangeDef.start);
      range.setEnd(textNode, rangeDef.end);

      for (const rect of range.getClientRects()) {
        const width = rect.width;
        const height = rect.height;
        if (!width || !height) continue;

        const highlight = document.createElement("div");
        highlight.className = "redactionPreviewRect";
        highlight.style.left = `${rect.left - layerBounds.left}px`;
        highlight.style.top = `${rect.top - layerBounds.top}px`;
        highlight.style.width = `${width}px`;
        highlight.style.height = `${height}px`;
        previewLayer.appendChild(highlight);
      }

      range.detach();
    }
  }
}

function collectMatches(text: string, rules: UiRule[]): Array<{ start: number; end: number }> {
  const matches: Array<{ start: number; end: number }> = [];
  for (const rule of rules) {
    const value = rule.value.trim();
    if (!value) continue;
    const ranges =
      rule.kind === "exact"
        ? findExactMatches(text, value, rule.caseSensitive, rule.ignoreAccents, rule.allowSubwords)
        : findRegexMatches(text, value, rule.caseSensitive, rule.ignoreAccents, rule.allowSubwords);
    matches.push(...ranges);
  }
  return mergeRanges(matches);
}

function findExactMatches(
  text: string,
  query: string,
  caseSensitive: boolean,
  ignoreAccents: boolean,
  allowSubwords: boolean,
) {
  const source = prepareText(text, caseSensitive, ignoreAccents);
  const needle = prepareText(query, caseSensitive, ignoreAccents);
  if (!needle.value) return [];

  const ranges: Array<{ start: number; end: number }> = [];
  let from = 0;
  while (from < source.value.length) {
    const at = source.value.indexOf(needle.value, from);
    if (at < 0) break;

    const endAt = at + needle.value.length;
    const start = source.starts[at] ?? at;
    const end = source.ends[endAt - 1] ?? endAt;
    if (allowSubwords || hasWordBoundaries(text, start, end)) {
      ranges.push({ start, end });
    }

    from = at + Math.max(1, needle.value.length);
  }
  return ranges;
}

function findRegexMatches(
  text: string,
  pattern: string,
  caseSensitive: boolean,
  ignoreAccents: boolean,
  allowSubwords: boolean,
) {
  const source = prepareText(text, caseSensitive, ignoreAccents);
  const flags = `g${caseSensitive ? "" : "i"}s`;
  let re: RegExp;
  try {
    re = new RegExp(pattern, flags);
  } catch {
    return [];
  }

  const ranges: Array<{ start: number; end: number }> = [];
  for (const match of source.value.matchAll(re)) {
    if (typeof match.index !== "number") continue;
    const matchedText = match[0] ?? "";
    if (!matchedText.length) continue;

    const endAt = match.index + matchedText.length;
    const start = source.starts[match.index] ?? match.index;
    const end = source.ends[endAt - 1] ?? endAt;
    if (allowSubwords || hasWordBoundaries(text, start, end)) {
      ranges.push({ start, end });
    }
  }
  return ranges;
}

function prepareText(input: string, caseSensitive: boolean, ignoreAccents: boolean) {
  if (!ignoreAccents) {
    const value = caseSensitive ? input : input.toLocaleLowerCase();
    const starts = Array.from({ length: value.length }, (_, i) => i);
    const ends = Array.from({ length: value.length }, (_, i) => i + 1);
    return { value, starts, ends };
  }

  let value = "";
  const starts: number[] = [];
  const ends: number[] = [];

  let offset = 0;
  for (const char of input) {
    const start = offset;
    offset += char.length;
    const folded = char.normalize("NFD").replace(/\p{M}+/gu, "");
    const prepared = caseSensitive ? folded : folded.toLocaleLowerCase();
    for (const foldedChar of prepared) {
      value += foldedChar;
      starts.push(start);
      ends.push(offset);
    }
  }

  return { value, starts, ends };
}

function hasWordBoundaries(input: string, start: number, end: number) {
  const left = start > 0 ? input[start - 1] : "";
  const right = end < input.length ? input[end] : "";
  return !isWordChar(left) && !isWordChar(right);
}

function isWordChar(char: string) {
  return !!char && /[\p{L}\p{N}_]/u.test(char);
}

function mergeRanges(ranges: Array<{ start: number; end: number }>) {
  if (ranges.length === 0) return ranges;
  const sorted = [...ranges].sort((a, b) => a.start - b.start || a.end - b.end);
  const merged = [sorted[0]];
  for (const current of sorted.slice(1)) {
    const previous = merged[merged.length - 1];
    if (current.start <= previous.end) {
      previous.end = Math.max(previous.end, current.end);
      continue;
    }
    merged.push(current);
  }
  return merged;
}
