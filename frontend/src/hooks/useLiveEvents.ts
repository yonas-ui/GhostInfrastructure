import { useEffect, useRef, useState } from "react";
import { getToken } from "../api";
import type { LiveEvent } from "../types";

/** Subscribes to /ws/projects/:id with automatic reconnect. Returns whether the socket is open. */
export function useLiveEvents(projectId: number | null, onEvent: (e: LiveEvent) => void): boolean {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (projectId == null) return;
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/projects/${projectId}?token=${encodeURIComponent(getToken())}`);
      ws.onopen = () => {
        retry = 0;
        setConnected(true);
      };
      ws.onmessage = (m) => {
        try {
          handler.current(JSON.parse(m.data) as LiveEvent);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = window.setTimeout(connect, Math.min(10000, 1000 * 2 ** retry++));
      };
      ws.onerror = () => ws?.close();
    };
    connect();

    const ping = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25000);
    return () => {
      closed = true;
      window.clearInterval(ping);
      window.clearTimeout(timer);
      ws?.close();
      setConnected(false);
    };
  }, [projectId]);

  return connected;
}
