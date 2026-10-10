"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { api } from "@/lib/api";
import type { AppPage, NotificationItem } from "@/lib/home-types";
import styles from "./NotificationBell.module.css";

const POLL_MS = 30000;

function ago(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "vừa xong";
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  return `${Math.floor(s / 86400)} ngày trước`;
}
function systemNotifications(): typeof Notification | null {
  return typeof window !== "undefined" && "Notification" in window ? (window as unknown as { Notification: typeof Notification }).Notification : null;
}

/** Chuông thông báo: chấm đỏ số chưa đọc, danh sách, và thông báo của hệ điều hành khi tab đang ẩn. */
export default function NotificationBell({ token, go }: { token: string; go: (p: AppPage) => void }) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [permission, setPermission] = useState<string>(() => systemNotifications()?.permission ?? "unsupported");
  const lastSeen = useRef<number | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.notifications(token);
      setItems(data.items); setUnread(data.unread);
      const newest = data.items[0]?.id ?? 0;
      const N = systemNotifications();
      if (lastSeen.current !== null && newest > lastSeen.current && N?.permission === "granted" && typeof document !== "undefined" && document.hidden) {
        for (const n of data.items.filter(i => i.id > (lastSeen.current ?? 0) && !i.read_at).slice(0, 3)) {
          try { new N(n.title, { body: n.body || undefined, icon: "/icons/icon-192.png", tag: `pb-${n.id}` }); } catch { /* một số trình duyệt chỉ cho qua service worker */ }
        }
      }
      lastSeen.current = Math.max(newest, lastSeen.current ?? 0);
    } catch { /* chuông là phụ: lỗi mạng thì thử lại ở lượt sau */ }
  }, [token]);

  useEffect(() => {
    void load();
    if (typeof window === "undefined" || typeof window.setInterval !== "function") return;
    const id = window.setInterval(() => void load(), POLL_MS);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => { window.clearInterval(id); window.removeEventListener("focus", onFocus); };
  }, [load]);

  useEffect(() => {
    if (!open || typeof document === "undefined") return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  async function openItem(n: NotificationItem) {
    setOpen(false);
    go(n.page);
    if (!n.read_at) {
      setItems(list => list.map(i => i.id === n.id ? { ...i, read_at: new Date().toISOString() } : i));
      try { setUnread((await api.readNotifications(token, [n.id])).unread); } catch { /* bỏ qua */ }
    }
  }
  async function readAll() {
    setItems(list => list.map(i => ({ ...i, read_at: i.read_at ?? new Date().toISOString() })));
    try { setUnread((await api.readNotifications(token)).unread); } catch { /* bỏ qua */ }
  }
  async function enableSystem() {
    const N = systemNotifications();
    if (!N) return;
    setPermission(await N.requestPermission());
  }

  return <div className={styles.wrap} ref={box}>
    <button type="button" className={styles.bell} aria-label={unread ? `Thông báo, ${unread} chưa đọc` : "Thông báo"} aria-expanded={open} onClick={() => { setOpen(o => !o); if (!open) void load(); }}>
      <Icon name="bell" />{unread > 0 && <em>{unread > 9 ? "9+" : unread}</em>}
    </button>
    {open && <div className={styles.panel} role="dialog" aria-label="Thông báo">
      <div className={styles.head}><b>Thông báo</b>{unread > 0 && <button type="button" onClick={() => void readAll()}>Đánh dấu đã đọc</button>}</div>
      {permission === "default" && <button type="button" className={styles.enable} onClick={() => void enableSystem()}>
        <Icon name="bell" />Bật thông báo trên máy để biết ngay khi bạn học check-in
      </button>}
      {items.length === 0 ? <p className={styles.empty}>Chưa có thông báo nào.</p>
        : <ul>{items.map(n => <li key={n.id}>
            <button type="button" className={n.read_at ? "" : styles.unread} onClick={() => void openItem(n)}>
              <b>{n.title}</b>{n.body && <small>{n.body}</small>}<em>{ago(n.created_at)}</em>
            </button>
          </li>)}</ul>}
    </div>}
  </div>;
}
