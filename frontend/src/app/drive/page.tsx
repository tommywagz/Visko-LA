import React, { Suspense } from 'react';
import { DriveWorkspace } from '../../components/drive/DriveWorkspace';

export default function DrivePage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full w-full items-center justify-center bg-[#F8FAFC] text-xs text-slate-600">
          Loading Dataset Drive Explorer...
        </div>
      }
    >
      <DriveWorkspace />
    </Suspense>
  );
}
