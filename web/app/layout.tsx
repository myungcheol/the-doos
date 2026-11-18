import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "杜氏世譜 · 두씨 족보 열람실",
  description: "원본 족보를 펼치고, 인물의 기록과 선조·후손을 따라가 보세요.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
