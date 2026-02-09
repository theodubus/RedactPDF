import React from "react";

export function FilePickerSection(props: {
  t: (k: string) => string;
  file: File | null;
  onPickFile: React.ChangeEventHandler<HTMLInputElement>;
}) {
  const { t, file, onPickFile } = props;

  return (
    <section className="section">
      <div className="sectionTitle">{t("form.section.file")}</div>
      <label className="fileRow">
        <input type="file" accept="application/pdf" onChange={onPickFile} />
        <span className="fileHelp">
          {file ? `${t("form.file.selected")}: ${file.name}` : t("form.file.choose")}
        </span>
      </label>
    </section>
  );
}
