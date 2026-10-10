"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon, type IconName } from "@/components/icons";
import { api } from "@/lib/api";
import type { AppPage, HomeOverview } from "@/lib/home-types";
import styles from "./Overview.module.css";

function greeting(name: string) {
  const h = new Date().getHours();
  const part = h < 11 ? "Chào buổi sáng" : h < 14 ? "Chào buổi trưa" : h < 18 ? "Chào buổi chiều" : "Chào buổi tối";
  return `${part}, ${name}`;
}
function when(iso: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("vi-VN", { weekday: "short", hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
}
const KIND_ICON: Record<string, IconName> = {
  checkin: "check", reaction: "spark", comment: "message", nudge: "bell",
  connection_request: "users", connection_accepted: "users", plan: "calendar", system: "spark",
};

const COACH_PAGE: Record<string, AppPage> = { reminder: "checkin", replan: "plan", pair_replan: "plan", offer_support: "sessions" };
const COACH_CTA: Record<string, string> = { reminder: "Check-in ngay", replan: "Xem phương án giảm tải", pair_replan: "Xem phương án giảm tải", offer_support: "Hẹn phiên học" };

function Pace({ label, side }: { label: string; side: { pacing: number | null; completed_minutes: number; due_minutes: number } }) {
  const pct = side.pacing === null ? null : Math.round(side.pacing * 100);
  return <div className={styles.pace}>
    <span>{label}</span>
    <div className={styles.bar}><i style={{ width: `${Math.min(100, pct ?? 0)}%` }} className={pct !== null && pct < 70 ? styles.low : ""} /></div>
    <b>{pct === null ? "Chưa đến hạn" : `${pct}%`}</b>
    <small>{side.completed_minutes}/{side.due_minutes} phút</small>
  </div>;
}

/** Thẻ "Nhịp học của hai bạn" + "Coach gợi ý" (vòng AI: check-in → đo tiến độ → coach). */
export function LoopCards({ data, go }: { data: HomeOverview; go: (p: AppPage) => void }) {
  if (!data.pair || (!data.progress && !data.coach)) return null;
  return <div className={styles.loop}>
    {data.progress && <section className="panel" aria-label="Nhịp học của hai bạn">
      <div className={styles.sectionHead}><h2>Nhịp học của hai bạn</h2>
        {data.progress.available && <span className={data.progress.needs_attention ? styles.badgeWarn : styles.badgeOk}>
          {data.progress.needs_attention ? "Cần chú ý" : "Đang đúng nhịp"}</span>}</div>
      {!data.progress.available ? <p className={styles.muted}>{data.progress.reason}</p> : <>
        <Pace label="Bạn" side={data.progress.me} />
        <Pace label={data.pair.partner_name} side={data.progress.partner} />
        <p className={styles.muted}>
          {data.progress.i_am_lagging ? "Bạn đang chậm hơn bạn cặp. Làm một việc nhỏ hôm nay để bắt kịp nhé."
            : data.progress.needs_attention ? "Một trong hai bạn đang chậm so với kế hoạch."
            : "Hai bạn đang theo kịp kế hoạch đã đặt."}
          {" "}Nhịp = phút đã xong ÷ phút đáng lẽ xong tới hôm nay.
        </p>
      </>}
    </section>}
    {data.coach && data.coach.text && <section className={`panel ${styles.coach}`} aria-label="Lời khuyên của coach">
      <div className={styles.sectionHead}><h2>Coach gợi ý</h2><small>{data.coach.source === "ai" ? "AI viết" : "Theo quy tắc"}</small></div>
      <p>{data.coach.text}</p>
      <button type="button" className="secondary" onClick={() => go(COACH_PAGE[data.coach!.action] || "plan")}>{COACH_CTA[data.coach.action] || "Mở kế hoạch"}</button>
    </section>}
  </div>;
}

function Skeleton() {
  return <div className="page" aria-busy="true" aria-label="Đang tải tổng quan">
    <div className={styles.skelTitle} />
    <div className={styles.tiles}>{[0, 1, 2, 3].map(i => <div key={i} className={styles.skelTile} />)}</div>
    <div className={styles.grid}><div className={styles.skelBlock} /><div className={styles.skelBlock} /></div>
  </div>;
}

export default function Overview({ token, go }: { token: string; go: (p: AppPage) => void }) {
  const [data, setData] = useState<HomeOverview | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try { setData(await api.home(token)); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Không tải được dữ liệu."); }
  }, [token]);
  useEffect(() => { void load(); }, [load]);

  if (!data && error) return <div className="page animate-in"><section className={`panel ${styles.state}`}>
    <h2>Chưa tải được trang tổng quan</h2><p>{error}</p>
    <button type="button" className="primary" onClick={() => void load()}>Thử lại</button>
  </section></div>;
  if (!data) return <Skeleton />;

  const stepsDone = data.steps.filter(s => s.done).length;
  const nextStep = data.steps.find(s => !s.done);
  const p = data.plan, c = data.checkin;
  const weekPct = p.week_total ? Math.round(p.week_done * 100 / p.week_total) : 0;

  return <div className="page animate-in">
    <div className={styles.head}>
      <div>
        <h1>{greeting(data.display_name)}</h1>
        <p>{data.pair
          ? c.checked_in_today ? `Hôm nay bạn đã check-in. ${c.partner_checked_in_today ? `${data.pair.partner_name} cũng vậy.` : `${data.pair.partner_name} chưa check-in.`}`
            : `Bạn và ${data.pair.partner_name} đang học cùng nhau. Hôm nay bạn chưa check-in.`
          : "Kết nối với một bạn học để bắt đầu học cùng nhau."}</p>
      </div>
      <button type="button" className="primary" onClick={() => go(data.pair ? "checkin" : "matching")}>
        <Icon name={data.pair ? "check" : "search"} />{data.pair ? "Check-in ngay" : "Tìm bạn học"}
      </button>
    </div>

    {stepsDone < data.steps.length && <section className={`panel ${styles.steps}`} aria-label="Các bước bắt đầu">
      <div className={styles.stepsHead}>
        <div><h2>Bắt đầu với PeerBridge</h2><p>{stepsDone}/{data.steps.length} bước đã xong</p></div>
        <div className={styles.ring} style={{ ["--p" as string]: `${stepsDone * 25}` }} aria-hidden="true"><span>{stepsDone * 25}%</span></div>
      </div>
      <ol>{data.steps.map((s, i) => <li key={s.key} className={s.done ? styles.done : s === nextStep ? styles.current : ""}>
        <span className={styles.num}>{s.done ? <Icon name="check" /> : i + 1}</span>
        <div><b>{s.title}</b><small>{s.hint}</small></div>
        {!s.done && <button type="button" className={s === nextStep ? "primary" : "ghost"} onClick={() => go(s.page)}>{s === nextStep ? "Làm ngay" : "Mở"}</button>}
      </li>)}</ol>
    </section>}

    <div className={styles.tiles}>
      <div className={styles.tile}><small>Chuỗi ngày học cùng</small><b>{c.streak}<em> ngày</em></b><span>{c.streak ? "Giữ lửa bằng một check-in hôm nay" : "Cả hai cùng check-in để bắt đầu chuỗi"}</span></div>
      <div className={styles.tile}><small>Kế hoạch tuần này</small><b>{p.week_done}<em>/{p.week_total} việc</em></b>
        <div className={styles.bar}><i style={{ width: `${weekPct}%` }} /></div></div>
      <div className={styles.tile}><small>Check-in đã ghi nhận</small><b>{c.total_done}</b><span>{c.checked_in_today ? "Hôm nay: đã check-in" : "Hôm nay: chưa check-in"}</span></div>
      <div className={styles.tile}><small>Kết nối</small><b>{data.connections}</b>
        <span>{data.pending_invites ? <button type="button" className={styles.link} onClick={() => go("connections")}>{data.pending_invites} lời mời đang chờ</button> : "Không có lời mời mới"}</span></div>
    </div>

    {data.pair && (data.progress || data.coach) && <div className={styles.loop}>
      {data.progress && <section className="panel" aria-label="Nhịp học của hai bạn">
        <div className={styles.sectionHead}><h2>Nhịp học của hai bạn</h2>
          {data.progress.available && <span className={data.progress.needs_attention ? styles.badgeWarn : styles.badgeOk}>
            {data.progress.needs_attention ? "Cần chú ý" : "Đang đúng nhịp"}</span>}</div>
        {!data.progress.available ? <p className={styles.muted}>{data.progress.reason}</p> : <>
          <Pace label="Bạn" side={data.progress.me} />
          <Pace label={data.pair.partner_name} side={data.progress.partner} />
          <p className={styles.muted}>
            {data.progress.i_am_lagging ? "Bạn đang chậm hơn bạn cặp. Làm một việc nhỏ hôm nay để bắt kịp nhé."
              : data.progress.needs_attention ? "Một trong hai bạn đang chậm so với kế hoạch."
              : "Hai bạn đang theo kịp kế hoạch đã đặt."}
            {" "}Nhịp = phút đã xong ÷ phút đáng lẽ xong tới hôm nay.
          </p>
        </>}
      </section>}
      {data.coach && data.coach.text && <section className={`panel ${styles.coach}`} aria-label="Lời khuyên của coach">
        <div className={styles.sectionHead}><h2>Coach gợi ý</h2><small>{data.coach.source === "ai" ? "AI viết" : "Theo quy tắc"}</small></div>
        <p>{data.coach.text}</p>
        <button type="button" className="secondary" onClick={() => go(COACH_PAGE[data.coach!.action] || "plan")}>{COACH_CTA[data.coach.action] || "Mở kế hoạch"}</button>
      </section>}
    </div>}

    <div className={styles.grid}>
      <section className="panel">
        <div className={styles.sectionHead}><h2>Việc sắp tới</h2>{p.has_plan && <button type="button" className={styles.link} onClick={() => go("plan")}>Xem kế hoạch</button>}</div>
        {!data.pair ? <div className={styles.empty}><p>Bạn cần một bạn học trước khi lập kế hoạch.</p><button type="button" className="secondary" onClick={() => go("matching")}>Tìm bạn học</button></div>
          : !p.has_plan ? <div className={styles.empty}><p>Chưa có kế hoạch. Hai bạn chốt mục tiêu và giờ rảnh, hệ thống chia việc giúp.</p><button type="button" className="secondary" onClick={() => go("plan")}>Lập kế hoạch</button></div>
          : p.next.length === 0 ? <div className={styles.empty}><p>Bạn đã xong hết việc đã xếp. Tuyệt vời.</p></div>
          : <ul className={styles.list}>{p.next.map(i => <li key={i.id}>
              <span className={styles.when}>{i.due_now ? "Đến giờ" : when(i.scheduled_start)}</span>
              <div><b>{i.label}</b><small>{i.est_minutes} phút</small></div>
              {i.due_now && <button type="button" className="secondary" onClick={() => go("checkin")}>Check-in</button>}
            </li>)}</ul>}
        {data.sessions.length > 0 && <>
          <h3 className={styles.sub}>Phiên học đã hẹn</h3>
          <ul className={styles.list}>{data.sessions.map(s => <li key={s.id}><span className={styles.when}>{when(s.scheduled_start)}</span><div><b>{s.topic}</b></div>
            <button type="button" className="ghost" onClick={() => go("sessions")}>Mở</button></li>)}</ul>
        </>}
      </section>

      <section className="panel">
        <div className={styles.sectionHead}><h2>Hoạt động gần đây</h2></div>
        {data.pair && c.partner_latest && <button type="button" className={styles.partner} onClick={() => go("checkin")}>
          <span className="avatar small">{data.pair.partner_name.slice(0, 2).toUpperCase()}</span>
          <div><b>{c.partner_latest.headline}</b><small>{c.partner_latest.relative}</small></div>
        </button>}
        {data.activity.length === 0 ? <div className={styles.empty}><p>Chưa có hoạt động. Khi bạn học check-in, gửi lời mời hay thả cảm xúc, bạn sẽ thấy ở đây.</p></div>
          : <ul className={styles.activity}>{data.activity.map(a => <li key={a.id} className={a.unread ? styles.unread : ""}>
              <span className={styles.kind}><Icon name={KIND_ICON[a.kind] || "spark"} /></span>
              <button type="button" onClick={() => go(a.page)}><b>{a.title}</b>{a.body && <small>{a.body}</small>}<em>{a.relative}</em></button>
            </li>)}</ul>}
      </section>
    </div>
  </div>;
}
