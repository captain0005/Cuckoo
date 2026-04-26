import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cuckoo 电商图片翻译",
  description: "跨境电商商品图 OCR 翻译与英文版图片生成工作台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
