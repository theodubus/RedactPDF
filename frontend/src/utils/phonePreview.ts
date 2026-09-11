import { isPossiblePhoneNumber, isValidPhoneNumber } from "libphonenumber-js/max";
import type { CountryCode } from "libphonenumber-js";

// Ce module doit rester le miroir exact de `_phone_post_filter`
// (backend/redactpdf/presets.py). Un aperçu qui surligne un numéro est lu comme
// une promesse de caviardage : s'il surligne ce que le backend ne touchera pas,
// l'utilisateur reçoit un export réussi avec la donnée en clair, et l'audit ne
// le rattrape pas puisqu'il rejoue le même détecteur.
//
// D'où libphonenumber côté navigateur aussi, en métadonnées `max` : les
// métadonnées `min`, plus légères, divergent du backend. Et la région par
// défaut vient de /api/config, faute de quoi un numéro étranger valide serait
// surligné puis laissé intact.

const PHONE_EXTENSION_RX = /\b(?:ext\.?|extension|poste|x|#)\s*\d{1,6}\b/gi;

/** Réplique de `_normalize_phone_candidate` : extensions retirées, 00 -> +. */
export function normalizePhoneCandidate(raw: string): string {
  const withoutExt = raw.trim().replace(PHONE_EXTENSION_RX, "").trim();
  const s = /^\s*00/.test(withoutExt)
    ? "+" + withoutExt.replace(/^\s*00/, "").trimStart()
    : withoutExt;
  return s.startsWith("+") ? "+" + s.slice(1).replace(/\D+/g, "") : s.replace(/\D+/g, "");
}

/** Vrai quand le preset `phone` du backend caviarderait ce candidat. */
export function backendWouldRedactPhone(rawMatch: string, defaultRegion: string): boolean {
  const normalized = normalizePhoneCandidate(rawMatch);
  const digits = normalized.startsWith("+") ? normalized.slice(1) : normalized;
  if (!/^\d+$/.test(digits)) return false;
  if (digits.length < 7 || digits.length > 15) return false;

  try {
    if (normalized.startsWith("+")) {
      return isPossiblePhoneNumber(normalized) && isValidPhoneNumber(normalized);
    }
    const region = defaultRegion as CountryCode;
    return isPossiblePhoneNumber(normalized, region) && isValidPhoneNumber(normalized, region);
  } catch {
    return false;
  }
}
