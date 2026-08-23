import { useEffect } from "react";

const HEARTBEAT_URL = "/api/heartbeat";
const CLOSE_URL = "/api/heartbeat/close";
const INTERVAL_MS = 5000;

/**
 * Desktop-launcher liveness.
 *
 * Pings the backend periodically and signals a close on tab teardown so the
 * launcher (launch.py) can stop the server promptly. Completely harmless in
 * dev / reverse-proxy production: the endpoint just records a timestamp that
 * nothing acts on unless the app was started via launch.py.
 */
export function useHeartbeat(): void {
  useEffect(() => {
    const ping = () => {
      void fetch(HEARTBEAT_URL, { method: "POST", keepalive: true }).catch(() => {});
    };

    ping();
    const timer = window.setInterval(ping, INTERVAL_MS);

    const onVisibility = () => {
      if (document.visibilityState === "visible") ping();
    };
    const onClose = () => {
      navigator.sendBeacon?.(CLOSE_URL);
    };

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onClose);

    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onClose);
    };
  }, []);
}
