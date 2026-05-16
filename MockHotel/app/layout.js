import "./globals.css";

export const metadata = {
  title: "MockHotel Price Manager",
  description: "Room price management for MockHotel"
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
