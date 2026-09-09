import { useState } from "react";

// Un document chiffré ne se refuse pas avec le message brut de la bibliothèque.
// « document closed or encrypted » n'indique ni la cause ni le remède ; ici on
// demande ce qui manque, et on distingue « il en faut un » de « celui-là est
// faux », parce que redemander sans le dire est cruel.
//
// Le mot de passe ne sert qu'à déchiffrer le flux en mémoire, le temps de la
// requête. Il n'est ni stocké ni renvoyé.

export function PasswordModal(props: {
  t: (k: string) => string;
  wrong: boolean;
  onCancel: () => void;
  onSubmit: (password: string) => void;
}) {
  const { t, wrong, onCancel, onSubmit } = props;
  const [value, setValue] = useState("");

  return (
    <div className="reviewOverlay" role="dialog" aria-modal="true">
      <form
        className="reviewPanel ocrWarningPanel"
        onSubmit={(e) => {
          e.preventDefault();
          if (value) onSubmit(value);
        }}
      >
        <div className="reviewTitle">{t("password.title")}</div>
        <p>{t(wrong ? "password.wrong" : "password.body")}</p>
        <input
          type="password"
          className="input"
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t("password.placeholder")}
        />
        <div className="reviewActions">
          <button type="button" onClick={onCancel}>
            {t("password.cancel")}
          </button>
          <button type="submit" className="primary" disabled={!value}>
            {t("password.submit")}
          </button>
        </div>
      </form>
    </div>
  );
}
