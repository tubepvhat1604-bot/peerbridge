"use client";

import { Icon } from "@/components/icons";
import styles from "./Landing.module.css";

/** Trang giới thiệu cho người chưa đăng nhập. Nội dung mô tả đúng những gì app làm được, không có số liệu bịa. */
export default function Landing({ onStart, onLogin }: { onStart: () => void; onLogin: () => void }) {
  return <div className={styles.page}>
    <header className={styles.nav}>
      <span className={styles.logo}><span className="brand-mark"><span>P</span><span>B</span></span>PeerBridge</span>
      <nav aria-label="Giới thiệu">
        <a href="#cach-hoat-dong">Cách hoạt động</a>
        <a href="#tinh-nang">Tính năng</a>
        <a href="#hoi-dap">Hỏi đáp</a>
      </nav>
      <div className={styles.navActions}>
        <button type="button" className="ghost" onClick={onLogin}>Đăng nhập</button>
        <button type="button" className="primary" onClick={onStart}>Bắt đầu</button>
      </div>
    </header>

    <main>
      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <span className={styles.pill}><i />Dành cho sinh viên tự học</span>
          <h1>Tự học bớt cô đơn khi có một người <em>cùng nhịp</em>.</h1>
          <p>Ghép cặp theo mục tiêu, lập kế hoạch tuần, chụp một tấm ảnh mỗi buổi học. AI ghi nhận giúp hai bạn.</p>
          <div className={styles.ctas}>
            <button type="button" className="primary" onClick={onStart}>Bắt đầu học cùng bạn <Icon name="arrow" /></button>
            <button type="button" className={styles.textLink} onClick={onLogin}>Đã có tài khoản? Đăng nhập</button>
          </div>
        </div>

        <div className={styles.mock} aria-hidden="true">
          <div className={styles.window}>
            <div className={styles.dots}><i /><i /><i /></div>
            <div className={styles.code}>
              <span><b>Bài 8</b> · RAG Pipeline</span>
              <span><b>1.</b> Chunking tài liệu môn học</span>
              <span><b>2.</b> Embedding vào vector store</span>
              <span><b>3.</b> Truy xuất top-k đoạn liên quan</span>
              <span><b>4.</b> Sinh câu trả lời kèm trích nguồn</span>
            </div>
          </div>
          <div className={`${styles.chip} ${styles.chipAi}`}><Icon name="spark" /><div><b>AI đã ghi nhận</b><small>Đọc bài RAG Pipeline · khớp kế hoạch</small></div></div>
          <div className={`${styles.chip} ${styles.chipPartner}`}><span className="avatar small">LA</span><div><b>Lan vừa check-in</b><small>Học Prompt Engineering · 2 phút trước</small></div></div>
          <div className={`${styles.chip} ${styles.chipStreak}`}><b>5</b><small>ngày liên tiếp cùng học</small></div>
        </div>
      </section>

      <section id="cach-hoat-dong" className={styles.steps}>
        <h2>Ba bước để không bỏ cuộc giữa chừng</h2>
        <ol>
          <li><span>1</span><div><h3>Ghép cặp</h3><p>Chọn mục tiêu và giờ rảnh. Hệ thống gợi ý bạn học hợp nhịp, hai bên đồng ý mới thành cặp.</p></div></li>
          <li><span>2</span><div><h3>Lập kế hoạch tuần</h3><p>Mỗi người một kế hoạch riêng, chia thành việc 30–90 phút, xếp vào đúng khung giờ rảnh.</p></div></li>
          <li><span>3</span><div><h3>Check-in bằng ảnh</h3><p>Chụp màn hình hay trang vở lúc học. AI đoán bạn học phần nào, đánh dấu xong và báo cho bạn cặp.</p></div></li>
        </ol>
      </section>

      <section id="tinh-nang" className={styles.bento}>
        <article className={styles.big}>
          <span className={styles.icon}><Icon name="check" /></span>
          <h3>AI Vision nhìn ảnh, không cần bạn khai báo</h3>
          <p>Ảnh rõ thì tự ghi nhận đúng việc trong kế hoạch. Không chắc thì hỏi lại một câu, bạn chọn trong 3 gợi ý.</p>
          <div className={styles.options}><span className={styles.optOn}>Đọc bài RAG Pipeline</span><span>Viết system prompt và tool schema</span><span>Mình học thứ khác</span></div>
        </article>
        <article><span className={styles.icon}><Icon name="calendar" /></span><h3>Kế hoạch vừa sức</h3><p>Chỉ xếp tối đa 80% số phút bạn cam kết, chừa chỗ cho ngày bận.</p></article>
        <article><span className={styles.icon}><Icon name="bell" /></span><h3>Nhắc nhẹ, không làm phiền</h3><p>Bạn cặp có thể nhắc bạn check-in, nhưng không nhắc trong giờ nghỉ 22:00–07:00.</p></article>
        <article className={styles.tinted}><span className={styles.icon}><Icon name="shield" /></span><h3>Ảnh của bạn là của bạn</h3><p>Chỉ bạn và bạn cặp xem được. Thông tin cá nhân trong ảnh không được chép vào ghi chú của AI.</p></article>
      </section>

      <section id="hoi-dap" className={styles.faq}>
        <h2>Hỏi nhanh</h2>
        <dl>
          <div><dt>Có mất phí không?</dt><dd>Không. PeerBridge đang chạy thử miễn phí với sinh viên.</dd></div>
          <div><dt>Mình chưa có bạn học thì sao?</dt><dd>Điền mục tiêu và giờ rảnh, vào “Tìm bạn” để gửi lời mời cho người hợp nhịp.</dd></div>
          <div><dt>AI có chấm điểm mình không?</dt><dd>Không. AI chỉ ghi nhận bạn đã học phần nào để cập nhật tiến độ của hai bạn.</dd></div>
          <div><dt>Dùng trên điện thoại được không?</dt><dd>Được. Mở bằng trình duyệt, chọn “Thêm vào màn hình chính” để dùng như một app.</dd></div>
        </dl>
      </section>

      <section className={styles.final}>
        <h2>Buổi học tới, đừng học một mình.</h2>
        <button type="button" className="primary" onClick={onStart}>Tạo tài khoản</button>
      </section>
    </main>

    <footer className={styles.footer}><span>PeerBridge · Dự án AI20K</span><span>Học cùng nhau, tiến xa hơn</span></footer>
  </div>;
}
