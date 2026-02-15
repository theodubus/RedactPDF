import { useEffect, useMemo, useRef, useState } from "react";
import type { PresetKey } from "../api";
import type { UiRect, UiRule } from "../types/uiRules";

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
  presetKeys: PresetKey[];
  t: (k: string) => string;
  onSelectionChange: (selection: { text: string; rects: UiRect[] } | null) => void;
  onCurrentPageChange: (pageNumber: number | null) => void;
  onPageSizeChange: (pageNumber: number, size: { width: number; height: number }) => void;
}) {
  const { file, rules, presetKeys, t, onSelectionChange, onCurrentPageChange, onPageSizeChange } = props;

  const [pdfDoc, setPdfDoc] = useState<PdfDocumentProxy | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRefs = useRef<Array<HTMLCanvasElement | null>>([]);
  const textLayerRefs = useRef<Array<HTMLDivElement | null>>([]);
  const previewLayerRefs = useRef<Array<HTMLDivElement | null>>([]);
  const pageRefs = useRef<Array<HTMLDivElement | null>>([]);
  const pageScalesRef = useRef<Array<number>>([]);
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

    onSelectionChange(null);
    onCurrentPageChange(null);
    pageScalesRef.current = [];
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
        onCurrentPageChange(1);
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
  }, [file, onSelectionChange, onCurrentPageChange]);

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
        onPageSizeChange(pageNumber, { width: baseViewport.width, height: baseViewport.height });
        const scale = containerWidth / baseViewport.width;
        const viewport = page.getViewport({ scale });

        pageScalesRef.current[pageNumber - 1] = scale;

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
        applyPreviewHighlights(textLayer, previewLayer, rules, presetKeys, pageNumber - 1, scale);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pdfDoc, pageNumbers, containerWidth, rules, presetKeys, onPageSizeChange]);

  useEffect(() => {
    for (const [index, textLayer] of textLayerRefs.current.entries()) {
      const previewLayer = previewLayerRefs.current[index];
      const scale = pageScalesRef.current[index] ?? 1;
      if (!textLayer || !previewLayer) continue;
      applyPreviewHighlights(textLayer, previewLayer, rules, presetKeys, index, scale);
    }
  }, [rules, presetKeys]);

  useEffect(() => {
    if (!containerRef.current || pageNumbers.length === 0) return;

    const container = containerRef.current;
    const observer = new IntersectionObserver(
      (entries) => {
        let bestPage: number | null = null;
        let bestRatio = 0;

        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const page = Number((entry.target as HTMLElement).dataset.pageNumber ?? "0");
          if (!page) continue;
          if (entry.intersectionRatio > bestRatio) {
            bestRatio = entry.intersectionRatio;
            bestPage = page;
          }
        }

        if (bestPage) onCurrentPageChange(bestPage);
      },
      { root: container, threshold: [0.25, 0.5, 0.75] },
    );

    for (const pageEl of pageRefs.current) {
      if (pageEl) observer.observe(pageEl);
    }

    return () => observer.disconnect();
  }, [pageNumbers, onCurrentPageChange]);

  useEffect(() => {
    const computeSelection = () => {
      const selection = window.getSelection();
      if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        onSelectionChange(null);
        return;
      }

      const selectedText = selection.toString().trim();
      if (!selectedText) {
        onSelectionChange(null);
        return;
      }

      const range = selection.getRangeAt(0);
      const anchorNode = range.commonAncestorContainer;
      if (!anchorNode) {
        onSelectionChange(null);
        return;
      }

      const pageIndex = textLayerRefs.current.findIndex((layer) => layer?.contains(anchorNode) ?? false);
      if (pageIndex < 0) {
        onSelectionChange(null);
        return;
      }

      const textLayer = textLayerRefs.current[pageIndex];
      const scale = pageScalesRef.current[pageIndex] ?? 1;
      if (!textLayer || scale <= 0) {
        onSelectionChange(null);
        return;
      }

      const layerBounds = textLayer.getBoundingClientRect();
      const rects: UiRect[] = [];

      for (const rect of range.getClientRects()) {
        const localLeft = rect.left - layerBounds.left;
        const localRight = rect.right - layerBounds.left;
        const localTop = rect.top - layerBounds.top;
        const localBottom = rect.bottom - layerBounds.top;

        if (localRight <= localLeft || localBottom <= localTop) continue;

        rects.push({
          page: pageIndex,
          x0: localLeft / scale,
          y0: localTop / scale,
          x1: localRight / scale,
          y1: localBottom / scale,
        });
      }

      if (rects.length === 0) {
        onSelectionChange(null);
        return;
      }

      onSelectionChange({ text: selectedText, rects });
      onCurrentPageChange(pageIndex + 1);
    };

    document.addEventListener("selectionchange", computeSelection);
    return () => {
      document.removeEventListener("selectionchange", computeSelection);
    };
  }, [onSelectionChange, onCurrentPageChange]);

  if (error) {
    return <div className="pdfViewerMessage bad">{error}</div>;
  }

  return (
    <div className="pdfViewer" ref={containerRef} aria-label={t("viewer.title")}>
      {isLoading ? <div className="pdfViewerMessage muted">{t("viewer.loading")}</div> : null}

      <div className="pdfCanvasStack" aria-live="polite">
        {pageNumbers.map((pageNumber) => (
          <div
            key={pageNumber}
            className="pdfPage"
            data-page-number={pageNumber}
            ref={(el) => {
              pageRefs.current[pageNumber - 1] = el;
            }}
          >
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
  presetKeys: PresetKey[],
  pageIndex: number,
  scale: number,
) {
  previewLayer.replaceChildren();

  const layerBounds = textLayer.getBoundingClientRect();
  if (!layerBounds.width || !layerBounds.height) return;

  const spans = textLayer.querySelectorAll("span");
  for (const span of spans) {
    const textNode = span.firstChild;
    if (!textNode || textNode.nodeType !== Node.TEXT_NODE) continue;

    const raw = textNode.textContent ?? "";
    if (!raw) continue;

    const ranges = collectMatches(raw, rules, presetKeys);
    if (ranges.length === 0) continue;

    for (const rangeDef of ranges) {
      const range = document.createRange();
      range.setStart(textNode, rangeDef.start);
      range.setEnd(textNode, rangeDef.end);

      for (const rect of range.getClientRects()) {
        drawPreviewRect(previewLayer, {
          left: rect.left - layerBounds.left,
          top: rect.top - layerBounds.top,
          width: rect.width,
          height: rect.height,
        });
      }

      range.detach();
    }
  }

  if (presetKeys.includes("phone")) {
    highlightPhonePresetMatches(textLayer, previewLayer, layerBounds);
  }

  const pageRules = rules.filter((r): r is Extract<UiRule, { kind: "page" }> => r.kind === "page");
  for (const pageRule of pageRules) {
    if (pageRule.pageNumber !== pageIndex + 1) continue;
    drawPreviewRect(previewLayer, {
      left: 0,
      top: 0,
      width: layerBounds.width,
      height: layerBounds.height,
    });
  }

  const selectionRules = rules.filter((r): r is Extract<UiRule, { kind: "selection" }> => r.kind === "selection");
  for (const selectionRule of selectionRules) {
    for (const rect of selectionRule.rects) {
      if (rect.page !== pageIndex) continue;
      drawPreviewRect(previewLayer, {
        left: rect.x0 * scale,
        top: rect.y0 * scale,
        width: (rect.x1 - rect.x0) * scale,
        height: (rect.y1 - rect.y0) * scale,
      });
    }
  }
}

function drawPreviewRect(
  previewLayer: HTMLDivElement,
  rect: { left: number; top: number; width: number; height: number },
) {
  const width = rect.width;
  const height = rect.height;
  if (!width || !height) return;

  const highlight = document.createElement("div");
  highlight.className = "redactionPreviewRect";
  highlight.style.left = `${rect.left}px`;
  highlight.style.top = `${rect.top}px`;
  highlight.style.width = `${width}px`;
  highlight.style.height = `${height}px`;
  previewLayer.appendChild(highlight);
}

function collectMatches(
  text: string,
  rules: UiRule[],
  presetKeys: PresetKey[],
): Array<{ start: number; end: number }> {
  const matches: Array<{ start: number; end: number }> = [];
  for (const rule of rules) {
    if (rule.kind === "selection" || rule.kind === "page") continue;
    const value = rule.value.trim();
    if (!value) continue;
    const ranges =
      rule.kind === "exact"
        ? findExactMatches(text, value, rule.caseSensitive, rule.ignoreAccents, rule.allowSubwords)
        : findRegexMatches(text, value, rule.caseSensitive, rule.ignoreAccents, rule.allowSubwords);
    matches.push(...ranges);
  }
  matches.push(...findPresetMatches(text, presetKeys));
  return mergeRanges(matches);
}


const PHONE_PRESET_REGEX = /\b(?:\+|00)?\s*(?:\d[\s().-]?){6,20}\d\b/gi;

function findPresetMatches(text: string, presetKeys: PresetKey[]) {
  const ranges: Array<{ start: number; end: number }> = [];

  for (const key of presetKeys) {
    if (key === "phone") continue;

    const regex =
      key === "email"
        ? /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/gi
        : /\b(?:\d[ -]*?){13,19}\b/gi;

    for (const match of text.matchAll(regex)) {
      if (typeof match.index !== "number") continue;
      const value = match[0] ?? "";
      if (!value) continue;
      ranges.push({ start: match.index, end: match.index + value.length });
    }
  }

  return ranges;
}

function isLikelyPhonePresetMatch(rawMatch: string) {
  const value = rawMatch.trim();
  if (!value) return false;
  if (/[A-Za-z/]/.test(value)) return false;

  const hasIntlPrefix = /^\s*(?:\+|00)/.test(value);
  const digits = value.replace(/\D+/g, "");
  const minDigits = hasIntlPrefix ? 8 : 10;
  if (digits.length < minDigits || digits.length > 15) return false;

  if (!hasIntlPrefix && !digits.startsWith("0")) return false;
  if (!/[+\s().-]/.test(value)) return false;

  return true;
}

type LayerTextNode = {
  node: Text;
  start: number;
  end: number;
};

function highlightPhonePresetMatches(
  textLayer: HTMLDivElement,
  previewLayer: HTMLDivElement,
  layerBounds: DOMRect,
) {
  const { fullText, nodes } = collectLayerTextNodes(textLayer);
  if (!fullText || nodes.length === 0) return;

  const phoneRegex = new RegExp(PHONE_PRESET_REGEX.source, PHONE_PRESET_REGEX.flags);
  for (const match of fullText.matchAll(phoneRegex)) {
    if (typeof match.index !== "number") continue;
    const value = match[0] ?? "";
    if (!value) continue;
    if (!isLikelyPhonePresetMatch(value)) continue;

    const matchStart = match.index;
    const matchEnd = match.index + value.length;

    for (const item of nodes) {
      const localStart = Math.max(matchStart, item.start) - item.start;
      const localEnd = Math.min(matchEnd, item.end) - item.start;
      if (localEnd <= localStart) continue;

      const range = document.createRange();
      range.setStart(item.node, localStart);
      range.setEnd(item.node, localEnd);

      for (const rect of range.getClientRects()) {
        drawPreviewRect(previewLayer, {
          left: rect.left - layerBounds.left,
          top: rect.top - layerBounds.top,
          width: rect.width,
          height: rect.height,
        });
      }
      range.detach();
    }
  }
}

function collectLayerTextNodes(textLayer: HTMLDivElement) {
  const nodes: LayerTextNode[] = [];
  let fullText = "";
  let cursor = 0;

  const spans = textLayer.querySelectorAll("span");
  for (const span of spans) {
    const textNode = span.firstChild;
    if (!textNode || textNode.nodeType !== Node.TEXT_NODE) continue;

    const value = textNode.textContent ?? "";
    if (!value) continue;

    const start = cursor;
    const end = start + value.length;
    nodes.push({ node: textNode as Text, start, end });

    fullText += value;
    cursor = end;

    fullText += "\n";
    cursor += 1;
  }

  return { fullText, nodes };
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
