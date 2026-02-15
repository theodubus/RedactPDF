import type { CSSProperties, ReactNode } from "react";
import type { RuleKind, UiRule } from "../../types/uiRules";
import { truncate } from "../../utils/redactionUtils";

const actionButtonStyle: CSSProperties = {
  border: "1px solid #d6dbe8",
  borderRadius: 10,
  width: 34,
  minWidth: 34,
  height: 34,
  padding: 0,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  background: "#fff",
  cursor: "pointer",
  fontWeight: 700,
};

const optionPillStyle: CSSProperties = {
  border: "1px solid #d6dbe8",
  borderRadius: 999,
  background: "#f5f7ff",
  color: "#2f3f86",
  fontSize: 12,
  fontWeight: 500,
  padding: "2px 8px",
  lineHeight: 1.2,
};

function RuleOptionPills(props: {
  rule: Extract<UiRule, { kind: "exact" | "regex" }>;
  t: (k: string) => string;
}) {
  const { rule, t } = props;
  const pills: ReactNode[] = [];

  if (rule.kind === "regex") {
    pills.push(
      <span key="regex" style={optionPillStyle} title={t("rules.toggle.regex")}>
        .* 
      </span>
    );
  }
  if (rule.caseSensitive) {
    pills.push(
      <span key="case" style={optionPillStyle} title={t("rules.option.caseSensitive")}>
        Aa
      </span>
    );
  }
  if (!rule.ignoreAccents) {
    pills.push(
      <span key="accents" style={optionPillStyle} title={t("rules.option.respectAccents")}>
        ëà
      </span>
    );
  }
  if (rule.kind === "regex" && rule.multiline) {
    pills.push(
      <span key="multiline" style={optionPillStyle} title={t("rules.option.multiline")}>
        ↵
      </span>
    );
  }
  if (rule.allowSubwords) {
    pills.push(
      <span key="subword" style={optionPillStyle} title={t("rules.option.subword")}>
        sub<strong style={{ fontWeight: 800, color: "#1f2f6b" }}>word</strong>
      </span>
    );
  }

  if (pills.length === 0) return null;
  return <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>{pills}</div>;
}

export function RulesList(props: {
  t: (k: string) => string;
  rules: UiRule[];
  kindLabel: (k: RuleKind | "selection" | "page") => string;
  onEdit: (r: UiRule) => void;
  onDelete: (id: string) => void;
}) {
  const { t, rules, kindLabel, onEdit, onDelete } = props;

  return (
    <div
      style={{
        marginTop: 10,
        border: "1px solid rgba(47,63,134,0.16)",
        borderRadius: 12,
        padding: 10,
        height: 270,
        overflowY: "auto",
        overflowX: "hidden",
        background: "rgba(255,255,255,0.75)",
        width: "100%",
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
                border: "1px solid rgba(47,63,134,0.12)",
                borderRadius: 10,
                padding: "10px 12px",
                gap: 12,
                minHeight: 58,
                maxWidth: "100%",
                overflow: "hidden",
                background: "#fff",
              }}
            >
              <div style={{ minWidth: 0, flex: 1 }}>
                <div
                  style={{
                    fontWeight: 600,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={r.value}
                >
                  {truncate(r.value, 24)}
                </div>

                <div className="muted" style={{ fontSize: 12 }}>
                  {kindLabel(r.kind)}
                </div>

                {r.kind === "page" ? (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                    <span style={optionPillStyle}>{`${t("rules.page.pill")} ${r.pageNumber}`}</span>
                  </div>
                ) : null}
                {r.kind !== "selection" && r.kind !== "page" ? <RuleOptionPills rule={r} t={t} /> : null}
              </div>

              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                {r.kind !== "selection" && r.kind !== "page" ? (
                  <button
                    type="button"
                    style={actionButtonStyle}
                    onClick={() => onEdit(r)}
                    aria-label={t("rules.item.edit")}
                    title={t("rules.item.edit")}
                  >
                    ✎
                  </button>
                ) : null}
                <button
                  type="button"
                  style={actionButtonStyle}
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
