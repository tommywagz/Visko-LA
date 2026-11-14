import type { Metadata } from 'next';
import React from 'react';
import './globals.css';
import { PlatformProvider } from '../context/PlatformContext';
import { AppShell } from '../components/shell/AppShell';

export const metadata: Metadata = {
  title: 'Visko-LA | Synthetic Aerial World & Telemetry Platform',
  description:
    'Live Drone-POV world simulation powered by Reactor and Visko Orbis Stable with coupled ISA/Dryden flight telemetry, GCS MP4 archival, and BigQuery dataset explorer.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <PlatformProvider>
          <AppShell>{children}</AppShell>
        </PlatformProvider>
      </body>
    </html>
  );
}
