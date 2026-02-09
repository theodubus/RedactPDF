import { useState } from "react";

export function JsonBlock(props: { value: unknown; t: (k: string) => string }) {
  const [open, setOpen] = useState(true);
  const { t } = props;

  return (
    <div className="jsonBlock">
      <button className="link" onClick={() => setOpen((v) => !v)} type="button">
        {open ? t("debug.hide") : t("debug.show")}
      </button>
      {open ? <pre className="pre">{JSON.stringify(props.value, null, 2)}</pre> : null}
    </div>
  );
}
