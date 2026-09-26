/**
 * the shell every page renders inside: the <html> tag, the font, and the page title.
 */

import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import "./globals.css";

// next/font downloads the font at build time and serves it from our own server,
// so the browser never waits on google fonts
const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Fantano",
  description: "Discover music from the internet's busiest music nerd.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${spaceGrotesk.variable} h-full antialiased`}>
      <body className="min-h-full font-sans">{children}</body>
    </html>
  );
}
