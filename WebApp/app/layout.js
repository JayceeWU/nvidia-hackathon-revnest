import "./globals.css";

export const metadata = {
  title: "RevNest Agent",
  description: "Autonomous hospitality revenue management dashboard",
  icons: {
    icon: "/icon.png",
    shortcut: "/icon.png",
    apple: "/icon.png",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
