import type { RuleKind, UiRule } from "../../types/uiRules";
import { truncate } from "../../utils/redactionUtils";

export function RulesList(props: {
  t: (k: string) => string;
  rules: UiRule[];
  kindLabel: (k: RuleKind | "selection") => string;
  onEdit: (r: UiRule) => void;
  onDelete: (id: string) => void;
}) {
  const { t, rules, kindLabel, onEdit, onDelete } = props;

  return (
    <div
      style={{
        marginTop: 10,
        border: "1px solid rgba(0,0,0,0.12)",
        borderRadius: 12,
        padding: 10,
        height: 240,
        overflowY: "auto",
        background: "rgba(255,255,255,0.6)",
      }}
    >
      {rules.length === 0 ? (
        <div className="muted" style={{ padding: 6 }}>
          {t("rules.empty")}
        </div>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {rules.map((r) => (
            <div
              key={r.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                border: "1px solid rgba(0,0,0,0.10)",
                borderRadius: 10,
                padding: "10px 12px",
                gap: 12,
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div
                  style={{
                    fontWeight: 600,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={r.value}
                >
                  {truncate(r.value)}
                </div>

                <div className="muted" style={{ fontSize: 12 }}>
                  {kindLabel(r.kind)}
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                {r.kind !== "selection" ? (
                  <button
                    type="button"
                    className="buttonSecondary"
                    onClick={() => onEdit(r)}
                    aria-label={t("rules.item.edit")}
                    title={t("rules.item.edit")}
                  >
                    ✎
                  </button>
                ) : null}
                <button
                  type="button"
                  className="buttonSecondary"
                  onClick={() => onDelete(r.id)}
                  aria-label={t("rules.item.delete")}
                  title={t("rules.item.delete")}
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
