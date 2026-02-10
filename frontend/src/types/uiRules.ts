export type RuleKind = "exact" | "regex";

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
    };
