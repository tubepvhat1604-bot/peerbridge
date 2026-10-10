import type { Metadata, Viewport } from "next";
import { Be_Vietnam_Pro } from "next/font/google";
import "./globals.css";
import "./product.css";

// Be Vietnam Pro: thiết kế cho tiếng Việt, dấu rõ ở mọi cỡ chữ.
const sans = Be_Vietnam_Pro({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "PeerBridge — Học cùng nhau, tiến xa hơn",
  description: "Ghép cặp bạn tự học, cùng lập kế hoạch và check-in bằng ảnh để giữ nhịp học mỗi ngày.",
  manifest: "/manifest.webmanifest",
  applicationName: "PeerBridge",
  appleWebApp: { capable: true, title: "PeerBridge", statusBarStyle: "default" },
  icons: { icon: "/favicon.png", apple: "/icons/apple-touch-icon.png" },
  openGraph: {
    title: "PeerBridge — Học cùng nhau, tiến xa hơn",
    description: "Ghép cặp bạn tự học, lập kế hoạch tuần và check-in bằng ảnh.",
    locale: "vi_VN",
    type: "website",
  },
};

export const viewport: Viewport = { themeColor: "#1d6b52", width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi" className={sans.variable}>
      <body>{children}</body>
    </html>
  );
}
