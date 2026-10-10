"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Icon, IconName } from "@/components/icons";
import { Matching } from "@/components/peer-connections/Matching";
import { Connections } from "@/components/peer-connections/Connections";
import StudySessions from "@/components/ProductSessions";
import StudyPlan from "@/components/StudyPlan";
import StudyCheckin from "@/components/StudyCheckin";
import InstructorModeration from "@/components/InstructorModeration";
import Overview from "@/components/ProductOverview";
import Avatar from "@/components/Avatar";
import NotificationBell from "@/components/NotificationBell";
import AiAnalytics from "@/components/AiAnalytics";
import AdminDashboard from "@/components/AdminDashboard";
import AdminSessions from "@/components/AdminSessions";
import Landing from "@/components/Landing";
import { api, ApiError, subscribeToUnauthorized } from "@/lib/api";
import type { Intent, ProfileMeResponse, ProfileMeUpdate, Role } from "@/lib/types";

type Page = "dashboard" | "matching" | "connections" | "sessions" | "plan" | "checkin" | "profile" | "moderation" | "analytics" | "architecture" | "admin" | "admin-sessions";
type AuthMode = "login" | "register";
type ProfileFormState = {
  display_name: string;
  school: string;
  major: string;
  bio: string;
  free_days: string;
  free_start: string;
  free_end: string;
  subjects: string;
  learning_goals: string;
  needs_help_with: string;
  can_help_with: string;
};

const TOKEN_KEY = "peerbridge_token";
const emptyProfileForm: ProfileFormState = {
  display_name: "",
  school: "",
  major: "",
  bio: "",
  free_days: "",
  free_start: "19:00",
  free_end: "21:00",
  subjects: "",
  learning_goals: "",
  needs_help_with: "",
  can_help_with: "",
};

// Thanh điều hướng chính
const navStudent: Array<[Page, IconName, string]> = [["dashboard","home","Tổng quan"],["matching","search","Tìm bạn"],["plan","calendar","Kế hoạch"],["checkin","check","Check-in"],["sessions","message","Phiên học"]];
// Các trang phụ nằm trong menu tài khoản.
const menuStudent: Array<[Page, IconName, string]> = [["connections","users","Kết nối của tôi"],["profile","user","Hồ sơ của tôi"]];
// Admin: giám sát phiên học, log kiểm duyệt (HITL) và chi phí AI.
const navAdmin: Array<[Page, IconName, string]> = [["admin","chart","Tổng quan"],["admin-sessions","message","Phiên học"],["moderation","shield","Kiểm duyệt"]];
const menuAdmin: Array<[Page, IconName, string]> = [];
const ADMIN_PAGES: Page[] = ["admin", "admin-sessions", "moderation"];

export default function Home() {
  const [page, setPage] = useState<Page>("dashboard");
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [showAuth, setShowAuth] = useState(false);
  const [toast, setToast] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authReady, setAuthReady] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [token, setToken] = useState("");
  const [profileBundle, setProfileBundle] = useState<ProfileMeResponse | null>(null);
  const [profileForm, setProfileForm] = useState<ProfileFormState>(emptyProfileForm);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const nav = isAdmin ? navAdmin : navStudent;
  const studentName = profileBundle?.profile.display_name || "Bạn";
  const studentInitials = initials(studentName);
  const studentMeta = profileMeta(profileBundle);

  function go(next: Page) {
    setPage(next);
    setMobileOpen(false);
    window.history.replaceState(null, "", next === "sessions" && activeSessionId !== null ? `#sessions/${activeSessionId}` : `#${next}`);
  }
  function selectSession(id: number | null) {
    setActiveSessionId(id);
    window.history.replaceState(null, "", id === null ? "#sessions" : `#sessions/${id}`);
  }
  function notify(message: string) { setToast(message); window.setTimeout(() => setToast(""), 2600); }

  function storeToken(nextToken: string) {
    setToken(nextToken);
    window.localStorage.setItem(TOKEN_KEY, nextToken);
  }

  function signOut(message = "Bạn đã đăng xuất.") {
    window.localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setProfileBundle(null);
    setIsAdmin(false);
    setProfileForm(emptyProfileForm);
    setProfileError("");
    setAuthMode("login");
    setAuthError("");
    setAuthNotice(message);
    setPage("dashboard");
    setActiveSessionId(null);
    window.history.replaceState(null, "", "#dashboard");
    setMobileOpen(false);
  }

  async function loadProfile(activeToken: string) {
    setProfileLoading(true);
    setProfileError("");
    try {
      const [data, me] = await Promise.all([api.profile(activeToken), api.whoami(activeToken).catch(() => null)]);
      const admin = Boolean(me?.is_admin);
      setIsAdmin(admin);
      setPage(current => admin ? (ADMIN_PAGES.includes(current) ? current : "admin") : (ADMIN_PAGES.includes(current) ? "dashboard" : current));
      setProfileBundle(data);
      setProfileForm(profileToForm(data));
      setAuthError("");
      return true;
    } catch (error) {
      const message = errorMessage(error);
      if (error instanceof ApiError && error.status === 401) {
        signOut("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
      } else {
        window.localStorage.removeItem(TOKEN_KEY);
        setToken("");
        setAuthError(message);
      }
      return false;
    } finally {
      setProfileLoading(false);
      setAuthReady(true);
    }
  }

  async function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setAuthLoading(true);
    setAuthError("");
    setAuthNotice("");
    try {
      const data = await api.login({
        email: stringField(form, "email"),
        password: stringField(form, "password", false),
      });
      storeToken(data.access_token);
      const loaded = await loadProfile(data.access_token);
      if (loaded) notify("Đăng nhập thành công.");
    } catch (error) {
      setAuthError(errorMessage(error));
    } finally {
      setAuthLoading(false);
    }
  }

  async function demoLogin(slug: string) {
    setAuthLoading(true);
    setAuthError("");
    setAuthNotice("");
    try {
      const data = await api.demoLogin(slug);
      storeToken(data.access_token);
      if (await loadProfile(data.access_token)) notify("Đã vào tài khoản thử.");
    } catch (error) {
      setAuthError(errorMessage(error));
    } finally {
      setAuthLoading(false);
    }
  }

  async function submitRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setAuthLoading(true);
    setAuthError("");
    setAuthNotice("");
    try {
      const data = await api.register({
        email: stringField(form, "email"),
        password: stringField(form, "password", false),
        display_name: stringField(form, "display_name"),
        age: numberField(form, "age"),
        city: stringField(form, "city"),
        intent: "conversation",
      });
      storeToken(data.access_token);
      const loaded = await loadProfile(data.access_token);
      if (loaded) {
        go("profile");
        notify("Chọn mục tiêu và giờ rảnh để tìm người đồng hành nhé.");
      }
    } catch (error) {
      setAuthError(errorMessage(error));
    } finally {
      setAuthLoading(false);
    }
  }

  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    setProfileSaving(true);
    setProfileError("");
    try {
      if (profileForm.free_days && profileForm.free_end <= profileForm.free_start) throw new Error("Giờ kết thúc cần sau giờ bắt đầu.");
      const payload = buildProfilePayload(profileForm, profileBundle);
      const updated = await api.updateProfile(token, payload);
      setProfileBundle(updated);
      setProfileForm(profileToForm(updated));
      notify("Đã lưu mục tiêu và giờ rảnh. Sẵn sàng tìm bạn đồng hành!");
      go("matching");
    } catch (error) {
      const message = errorMessage(error);
      setProfileError(message);
      if (error instanceof ApiError && error.status === 401) signOut("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
    } finally {
      setProfileSaving(false);
    }
  }

  useEffect(() => {
    const restoreNavigation = () => {
      const savedPage = window.location.hash.slice(1);
      if (savedPage === "profile" || savedPage === "matching" || savedPage === "connections" || savedPage === "plan" || savedPage === "checkin"
        || savedPage === "admin" || savedPage === "admin-sessions" || savedPage === "moderation") setPage(savedPage);
      const sessionRoute = /^sessions(?:\/([1-9]\d*))?$/.exec(savedPage);
      if (sessionRoute) {
        setPage("sessions");
        const id = sessionRoute[1] ? Number(sessionRoute[1]) : null;
        setActiveSessionId(id !== null && Number.isSafeInteger(id) ? id : null);
      }
    };
    restoreNavigation();
    window.addEventListener("hashchange", restoreNavigation);
    window.addEventListener("popstate", restoreNavigation);
    const savedToken = window.localStorage.getItem(TOKEN_KEY);
    if (!savedToken) {
      setAuthReady(true);
    } else {
      setToken(savedToken);
      void loadProfile(savedToken);
    }
    return () => {
      window.removeEventListener("hashchange", restoreNavigation);
      window.removeEventListener("popstate", restoreNavigation);
    };
  }, []);

  useEffect(() => {
    if (!token) return;
    return subscribeToUnauthorized((expiredToken) => {
      if (expiredToken === token && window.localStorage.getItem(TOKEN_KEY) === expiredToken) {
        signOut("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
      }
    });
  }, [token]);

  useEffect(() => {
    // Cài như app (PWA): đăng ký service worker khi trình duyệt hỗ trợ.
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => { /* không bắt buộc */ });
  }, []);

  if (!authReady) {
    return <div className="splash" aria-busy="true"><span className="brand-mark"><span>P</span><span>B</span></span><b>PeerBridge</b></div>;
  }

  if (!token || !profileBundle) {
    if (!showAuth && !authNotice && !authError) {
      return <Landing onStart={() => { setAuthMode("register"); setShowAuth(true); }} onLogin={() => { setAuthMode("login"); setShowAuth(true); }} />;
    }
    return <AuthScreen mode={authMode} setMode={setAuthMode} loading={authLoading} error={authError} notice={authNotice} onLogin={submitLogin} onRegister={submitRegister} onDemo={demoLogin}
      onBack={() => { setShowAuth(false); setAuthError(""); setAuthNotice(""); }} />;
  }

  const home: Page = isAdmin ? "admin" : "dashboard";
  const avatarText = studentInitials;
  return <div className="app">
    <header className="appbar">
      <button className="brand" onClick={() => go(home)} aria-label="PeerBridge, về trang chính">
        <span className="brand-mark"><span>P</span><span>B</span></span><span>PeerBridge</span>
      </button>
      <nav className="appnav" aria-label="Điều hướng chính">
        {nav.map(([id, icon, label]) => <button key={id} className={page === id ? "active" : ""} aria-current={page === id ? "page" : undefined} onClick={() => go(id)}><Icon name={icon}/><span>{label}</span></button>)}
      </nav>
      <div className="appbar-actions">
        <NotificationBell token={token} go={go} />
        <AccountMenu avatarSeed={profileBundle.profile.user_id} name={studentName} meta={isAdmin ? "Admin" : studentMeta} initials={avatarText}
          items={isAdmin ? menuAdmin : menuStudent} active={page} onGo={go} onSignOut={() => signOut()} />
      </div>
    </header>
    <main id="main">
      {isAdmin ? <>
        {page === "admin" && <AdminDashboard key={token} token={token} onSessions={() => go("admin-sessions")} onModeration={() => go("moderation")} />}
        {page === "admin-sessions" && <AdminSessions key={token} token={token} onModeration={() => go("moderation")} />}
        {page === "moderation" && <InstructorModeration key={token} token={token} />}
      </> : <>
      {page === "dashboard" && <Overview key={token} token={token} go={go} />}
      {page === "matching" && <Matching key={token} token={token} notify={notify} onConnections={() => go("connections")} />}
      {page === "connections" && <Connections key={token} token={token} userId={profileBundle.profile.user_id} notify={notify} onMatching={() => go("matching")} onPlan={() => go("plan")} onSessions={() => go("sessions")} />}
      {page === "plan" && <StudyPlan key={token} token={token} userId={profileBundle.profile.user_id} onConnections={() => go("connections")} />}
      {page === "checkin" && <StudyCheckin key={token} token={token} onConnections={() => go("connections")} onPlan={() => go("plan")} />}
      {page === "sessions" && <StudySessions key={`${token}:${profileBundle.profile.user_id}`} token={token} userId={profileBundle.profile.user_id} sessionId={activeSessionId} onSessionChange={selectSession} onConnections={() => go("connections")} onCheckin={() => go("checkin")} />}
      {page === "profile" && <Profile bundle={profileBundle} form={profileForm} setForm={setProfileForm} loading={profileLoading} saving={profileSaving} error={profileError} onSubmit={submitProfile} />}
      </>}
    </main>
    <nav className="tabbar" aria-label="Điều hướng nhanh">
      {nav.map(([id, icon, label]) => <button key={id} className={page === id ? "active" : ""} aria-current={page === id ? "page" : undefined} onClick={() => go(id)}><Icon name={icon}/><span>{label}</span></button>)}
    </nav>
    <div className={`toast ${toast ? "show" : ""}`} role="status"><Icon name="check" />{toast}</div>
  </div>;
}

function AccountMenu({ avatarSeed, name, meta, initials, items, active, onGo, onSignOut }: {
  avatarSeed: number; name: string; meta: string; initials: string; items: Array<[Page, IconName, string]>; active: Page;
  onGo: (p: Page) => void; onSignOut: () => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open || typeof document === "undefined") return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return <div className="account" ref={box}>
    <button className="account-button" aria-label={`Tài khoản: ${name}`} aria-expanded={open} onClick={() => setOpen(o => !o)}><Avatar seed={avatarSeed}/></button>
    {open && <div className="account-menu" role="menu">
      <div className="account-head"><Avatar seed={avatarSeed}/><div><b>{name}</b><small>{meta}</small></div></div>
      {items.map(([id, icon, label]) => <button key={id} role="menuitem" className={active === id ? "active" : ""} onClick={() => { setOpen(false); onGo(id); }}><Icon name={icon}/>{label}</button>)}
      <button role="menuitem" className="signout" onClick={() => { setOpen(false); onSignOut(); }}><Icon name="arrow"/>Đăng xuất</button>
    </div>}
  </div>;
}

function AuthScreen({
  mode,
  setMode,
  loading,
  error,
  notice,
  onLogin,
  onRegister,
  onBack,
  onDemo,
}: {
  mode: AuthMode;
  setMode: (mode: AuthMode) => void;
  loading: boolean;
  error: string;
  notice: string;
  onLogin: (event: FormEvent<HTMLFormElement>) => void;
  onRegister: (event: FormEvent<HTMLFormElement>) => void;
  onBack?: () => void;
  onDemo?: (slug: string) => void;
}) {
  const isLogin = mode === "login";
  const [demo, setDemo] = useState<{ slug: string; name: string }[]>([]);
  useEffect(() => {
    api.demoInfo().then(d => setDemo(d.enabled ? d.accounts : [])).catch(() => setDemo([]));
  }, []);
  return <main className="auth-screen">
    <section className="auth-intro" aria-hidden="true">
      <span className="auth-logo"><span className="brand-mark"><span>P</span><span>B</span></span>PeerBridge</span>
      <h2>Tự học bớt cô đơn khi có một người cùng nhịp.</h2>
      <p>Ghép cặp với bạn cùng mục tiêu, lập kế hoạch tuần, chụp một tấm ảnh mỗi buổi học để bạn kia biết bạn vẫn đang cố gắng.</p>
      <ul className="auth-points">
        <li><Icon name="users" />Ghép cặp theo mục tiêu và giờ rảnh</li>
        <li><Icon name="calendar" />Kế hoạch tuần vừa sức cho từng người</li>
        <li><Icon name="check" />Check-in bằng ảnh, AI ghi nhận giúp</li>
      </ul>
    </section>
    <section className="auth-card panel animate-in">
      {onBack && <button type="button" className="auth-back" onClick={onBack}><Icon name="arrow" />Về trang giới thiệu</button>}
      <div className="auth-brand">
        <span className="brand-mark"><span>P</span><span>B</span></span>
        <div><b>{isLogin ? "Chào mừng bạn quay lại" : "Tạo tài khoản"}</b><small>{isLogin ? "Đăng nhập để tiếp tục buổi học." : "Mất chưa tới một phút."}</small></div>
      </div>
      <div className="auth-tabs" aria-label="Chọn hành động">
        <button type="button" className={isLogin ? "active" : ""} onClick={() => setMode("login")}>Đăng nhập</button>
        <button type="button" className={!isLogin ? "active" : ""} onClick={() => setMode("register")}>Đăng ký</button>
      </div>
      {notice && <p className="form-success"><Icon name="check" />{notice}</p>}
      {error && <p className="form-error">{error}</p>}
      {isLogin ? (
        <form className="auth-form" onSubmit={onLogin}>
          <label>Email<input name="email" type="email" placeholder="ban@example.com" autoComplete="email" required /></label>
          <label>Mật khẩu<input name="password" type="password" placeholder="Tối thiểu 8 ký tự" autoComplete="current-password" required /></label>
          <button className="primary wide" disabled={loading}>{loading ? "Đang đăng nhập..." : "Đăng nhập"}</button>
          {onDemo && demo.length > 0 && <div className="demo-login">
            <small>Dùng thử không cần đăng ký (mở hai cửa sổ để đóng vai hai bạn học):</small>
            <div>{demo.map(a => <button key={a.slug} type="button" className="secondary" disabled={loading} onClick={() => onDemo(a.slug)}>Vào thử: {a.name.split(" (")[0]}</button>)}</div>
          </div>}
        </form>
      ) : (
        <form className="auth-form" onSubmit={onRegister}>
          <label>Tên hiển thị<input name="display_name" placeholder="Nguyễn Linh Anh" maxLength={60} required /></label>
          <label>Email<input name="email" type="email" placeholder="ban@example.com" autoComplete="email" required /></label>
          <label>Mật khẩu<input name="password" type="password" minLength={8} maxLength={128} placeholder="Tối thiểu 8 ký tự" autoComplete="new-password" required /></label>
          <div className="form-row">
            <label>Tuổi<input name="age" type="number" min={18} max={100} defaultValue={20} required /></label>
            <label>Thành phố<input name="city" defaultValue="Hà Nội" maxLength={80} required /></label>
          </div>
          <button className="primary wide" disabled={loading}>{loading ? "Đang tạo tài khoản..." : "Tạo tài khoản"}</button>
        </form>
      )}
    </section>
  </main>;
}

function stringField(form: FormData, name: string, trim = true) {
  const value = form.get(name);
  if (typeof value !== "string") return "";
  return trim ? value.trim() : value;
}

function numberField(form: FormData, name: string) {
  const value = Number.parseInt(stringField(form, name), 10);
  return Number.isFinite(value) ? value : 18;
}

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return "Không thể kết nối máy chủ.";
}

function splitList(value: string) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinList(items: string[]) {
  return items.join(", ");
}

function profileToForm(bundle: ProfileMeResponse): ProfileFormState {
  return {
    display_name: bundle.profile.display_name ?? "",
    school: bundle.profile.school ?? "",
    major: bundle.profile.major ?? "",
    bio: bundle.profile.bio ?? "",
    free_days: bundle.availability.map(w => w.day_of_week).filter((v,i,a) => a.indexOf(v) === i).join(","),
    free_start: bundle.availability[0]?.start_time.slice(0,5) || "19:00",
    free_end: bundle.availability[0]?.end_time.slice(0,5) || "21:00",
    subjects: joinList(bundle.profile.subjects ?? []),
    learning_goals: joinList(bundle.profile.learning_goals ?? []),
    needs_help_with: joinList(bundle.needs_help_with.map((item) => item.topic)),
    can_help_with: joinList(bundle.can_help_with.map((item) => item.topic)),
  };
}

function buildProfilePayload(form: ProfileFormState, bundle: ProfileMeResponse | null): ProfileMeUpdate {
  const existingNeeds = new Map((bundle?.needs_help_with ?? []).map((item) => [item.topic.trim().toLowerCase(), item]));
  const existingOffers = new Map((bundle?.can_help_with ?? []).map((item) => [item.topic.trim().toLowerCase(), item]));
  return {
    profile: {
      display_name: form.display_name.trim(),
      bio: form.bio.trim(),
      school: form.school.trim(),
      major: form.major.trim(),
      subjects: splitList(form.subjects),
      learning_goals: splitList(form.learning_goals),
    },
    needs_help_with: splitList(form.needs_help_with).map((topic) => {
      const existing = existingNeeds.get(topic.toLowerCase());
      return {
        topic,
        description: existing?.description ?? "",
        current_level: existing?.current_level ?? "",
        target_outcome: existing?.target_outcome ?? "",
      };
    }),
    can_help_with: splitList(form.can_help_with).map((topic) => {
      const existing = existingOffers.get(topic.toLowerCase());
      return {
        topic,
        description: existing?.description ?? "",
        proficiency_level: existing?.proficiency_level ?? "",
        max_sessions_per_week: existing?.max_sessions_per_week ?? 3,
      };
    }),
    availability: form.free_days.split(",").filter(Boolean).map(day => ({
      day_of_week: Number(day), start_time: form.free_start, end_time: form.free_end, timezone: "Asia/Ho_Chi_Minh",
    })),
  };
}

function profileMeta(bundle: ProfileMeResponse | null) {
  if (!bundle) return "Sinh viên";
  const details = [bundle.profile.major, bundle.profile.school].filter(Boolean);
  return details.join(" · ") || "Sinh viên";
}

function profileCompletion(bundle: ProfileMeResponse, form: ProfileFormState) {
  const filled = [
    form.display_name,
    form.school,
    form.major,
    form.bio,
    form.subjects,
    form.learning_goals,
    form.needs_help_with,
    form.can_help_with,
  ].filter((value) => value.trim()).length;
  return Math.round((filled / 8) * 100);
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "PB";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

function PageTitle({ eyebrow, title, text, actions }: { eyebrow: string; title: string; text: string; actions?: React.ReactNode }) {
  return <div className="page-title"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{text}</p></div>{actions && <div className="page-actions">{actions}</div>}</div>;
}


function Sessions({ role, notify }: { role:Role; notify:(m:string)=>void }) {
  const [message,setMessage]=useState(""); const [messages,setMessages]=useState(["Chào Trang, mình vẫn chưa hiểu cách xoay cây AVL.","Mình thử bắt đầu từ điều kiện mất cân bằng nhé. Bạn nhớ balance factor được tính thế nào không?"]);
  function submit(e:FormEvent){e.preventDefault();if(!message.trim())return;setMessages([...messages,message]);setMessage("");notify("Tin nhắn đã gửi qua WebSocket");}
  return <div className="page session-page animate-in"><PageTitle eyebrow={role==="STUDENT"?"Study room · Đang hoạt động":"Quan sát phiên học"} title="Cây nhị phân & phép duyệt" text="CS201 · Phiên PB-1024 · 19:30–20:30" actions={<span className="room-status"><i/> {role==="STUDENT"?"Minh Trang đang trực tuyến":"Đang theo dõi realtime"}</span>} />
    <div className="study-layout"><section className="study-room panel"><div className="study-header"><div className="peer-pair"><span className="avatar">LA</span><span className="avatar teal">MT</span><div><b>Linh Anh & Minh Trang</b><small>2 người tham gia</small></div></div><span className="session-timer"><Icon name="clock"/> 00:24:18</span></div><div className="messages">{messages.map((m,i)=><div className={`message ${i%2===0?"mine":""}`} key={`${m}-${i}`}><div className="message-author">{i%2===0?"Bạn":"Minh Trang"}<span>{i===0?"19:34":"19:36"}</span></div><p>{m}</p></div>)}<div className="ai-guidance"><span><Icon name="spark"/></span><div><b>Gợi ý từ PeerGuide</b><p>Thử tính chiều cao của cây con trái và phải trước. Hiệu của hai giá trị đó nói lên điều gì về độ cân bằng?</p><small><Icon name="book"/> Dựa trên Bài giảng 06 · Cây cân bằng, trang 14</small></div></div></div><form className="composer" onSubmit={submit}><button type="button">＋</button><input value={message} onChange={e=>setMessage(e.target.value)} placeholder="Nhập tin nhắn hoặc câu hỏi của bạn..."/><button className="send-button" aria-label="Gửi"><Icon name="send"/></button></form></section>
      <aside className="session-aside"><section className="panel safety-panel"><span className="safety-mark"><Icon name="shield"/></span><h3>Không gian học an toàn</h3><p>PeerGuide giúp cuộc trao đổi tập trung vào cách tư duy, không đưa đáp án hoàn chỉnh.</p><div className="safety-status"><span><i/> AI Moderator</span><b>Đang hoạt động</b></div></section><section className="panel agenda"><h3>Mục tiêu phiên học</h3><label><input type="checkbox" defaultChecked/> Hiểu balance factor</label><label><input type="checkbox"/> Phân biệt xoay trái/phải</label><label><input type="checkbox"/> Tự giải một bài AVL</label><div className="progress"><span style={{width:"33%"}}/></div><small>1/3 mục tiêu hoàn thành</small></section></aside></div>
  </div>;
}

function Profile({
  bundle,
  form,
  setForm,
  loading,
  saving,
  error,
  onSubmit,
}: {
  bundle: ProfileMeResponse;
  form: ProfileFormState;
  setForm: (next: ProfileFormState) => void;
  loading: boolean;
  saving: boolean;
  error: string;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const completion = profileCompletion(bundle, form);
  const name = form.display_name || bundle.profile.display_name || "Bạn";
  const meta = profileMeta(bundle);
  const update = (field: keyof ProfileFormState, value: string) => setForm({ ...form, [field]: value });
  return <div className="page narrow animate-in"><PageTitle eyebrow="Hồ sơ học tập" title="Cho bạn học biết bạn cần gì" text="Chọn điều bạn muốn đạt được. Mình sẽ tìm một người cùng giữ nhịp."/>
    <div className="profile-grid">
      <section className="panel profile-card">
        <Avatar seed={bundle.profile.user_id} size={96}/>
        <h2>{name}</h2>
        <p>{meta}</p>
        <span className="profile-chip">Hồ sơ hoàn thiện {completion}%</span>
        <div className="profile-stats">
          <div><b>{bundle.needs_help_with.length}</b><span>Cần hỗ trợ</span></div>
          <div><b>{bundle.can_help_with.length}</b><span>Có thể hỗ trợ</span></div>
          <div><b>{bundle.availability.length}</b><span>Lịch rảnh</span></div>
        </div>
      </section>
      <form className="panel profile-form" onSubmit={onSubmit}>
        {loading && <p className="status-line">Đang tải hồ sơ từ backend...</p>}
        {error && <p className="form-error">{error}</p>}
        <div className="form-row">
          <label>Họ và tên<input value={form.display_name} onChange={(event) => update("display_name", event.target.value)} maxLength={80} required /></label>
          <label>Trường<input value={form.school} onChange={(event) => update("school", event.target.value)} maxLength={120} /></label>
        </div>
        <div className="form-row">
          <label>Chuyên ngành<input value={form.major} onChange={(event) => update("major", event.target.value)} maxLength={120} /></label>
          <label>Môn học quan tâm<input value={form.subjects} onChange={(event) => update("subjects", event.target.value)} placeholder="LLM, Agent, RAG" /></label>
        </div>
        <div className="profile-goal-first"><label>Mục tiêu học tập của tôi<input required value={form.learning_goals} onChange={e=>update("learning_goals",e.target.value)} placeholder="Học tiếng Anh giao tiếp trong 7 tuần"/></label><small>Mục tiêu này giúp gợi ý người đồng hành và kế hoạch phù hợp.</small></div>
        <label>Giới thiệu<textarea value={form.bio} onChange={(event) => update("bio", event.target.value)} maxLength={800} /></label>
        <label>Tôi cần hỗ trợ<input value={form.needs_help_with} onChange={(event) => update("needs_help_with", event.target.value)} placeholder="VD: RAG Pipeline, Agent và ReAct (cách nhau bằng dấu phẩy)" /></label>
        <label>Tôi có thể hỗ trợ<input value={form.can_help_with} onChange={(event) => update("can_help_with", event.target.value)} placeholder="VD: Prompt Engineering và Tool Calling, Triển khai Agent lên Cloud" /></label>
        <fieldset className="availability-picker"><legend>🗓️ Khung giờ bạn thường rảnh</legend><p>Chọn các ngày bạn muốn dành thời gian học.</p><div className="day-chips">{["T2","T3","T4","T5","T6","T7","CN"].map((day,i) => { const selected = form.free_days.split(",").includes(String(i)); return <button key={day} type="button" aria-pressed={selected} className={selected ? "active" : ""} onClick={() => update("free_days", (selected ? form.free_days.split(",").filter(d => d !== String(i)) : [...form.free_days.split(",").filter(Boolean), String(i)]).join(","))}>{day}</button>; })}</div><div className="form-row"><label>Từ<input type="text" inputMode="numeric" placeholder="HH:mm" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" value={form.free_start} onChange={e => update("free_start", e.target.value)}/></label><label>Đến<input type="text" inputMode="numeric" placeholder="HH:mm" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" value={form.free_end} onChange={e => update("free_end", e.target.value)}/></label></div></fieldset>
        <div className="form-footer"><span><Icon name="shield"/> Chỉ chia sẻ thông tin học tập cần thiết</span><button className="primary" disabled={saving}>{saving ? "Đang lưu..." : "Lưu & tìm bạn đồng hành"}</button></div>
      </form>
    </div>
  </div>;
}

function Architecture(){return <div className="page animate-in"><PageTitle eyebrow="" title="Kiến trúc PeerBridge" text="Giao diện, logic nghiệp vụ, AI và dữ liệu được tách lớp rõ ràng." actions={<a className="outline button-link" href="/peerbridge-architecture.svg" download>Tải sơ đồ</a>}/><section className="panel architecture-panel"><img src="/peerbridge-architecture.svg" alt="Sơ đồ kiến trúc PeerBridge"/></section><div className="principles"><div><b>01</b><h3>Giao diện tách biệt</h3><p>Next.js chỉ gọi backend qua REST và WebSocket, cài được như app trên điện thoại.</p></div><div><b>02</b><h3>Logic ở backend</h3><p>FastAPI giữ phân quyền, ghép cặp, kế hoạch, check-in và thông báo.</p></div><div><b>03</b><h3>AI có rào chắn</h3><p>LangGraph điều phối; AI Vision chỉ chọn concept trong kế hoạch, có trần chi phí mỗi ngày.</p></div><div><b>04</b><h3>Dữ liệu không mất</h3><p>SQLite được sao lưu liên tục (Litestream) và tự khôi phục khi server khởi động lại.</p></div></div></div>}
