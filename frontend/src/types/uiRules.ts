export type RuleKind = "exact" | "regex";

export type UiRect = {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

export type UiRule =
  | {
      id: string;
      kind: "exact";
      value: string;
      caseSensitive: boolean;
      allowSubwords: boolean; // UI "Sous-mot" (whole_word = !allowSubwords côté API)
      ignoreAccents: boolean;
    }
  | {
      id: string;
      kind: "regex";
      value: string; // 1 regex
      caseSensitive: boolean;
      multiline: boolean;
      allowSubwords: boolean;
      ignoreAccents: boolean;
    }
  | {
      id: string;
      kind: "selection";
      value: string;
      rects: UiRect[];
    }
  | {
      id: string;
      kind: "page";
      value: string;
      pageNumber: number;
      rect: UiRect;
    }
  | {
      id: string;
      kind: "rectangle";
      value: string;
      rectangleNumber: number;
      pageNumber: number;
      rect: UiRect;
    };
