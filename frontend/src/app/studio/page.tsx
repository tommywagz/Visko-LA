import React, { Suspense } from 'react';
import { StudioWorkspace } from '../../components/studio/StudioWorkspace';

export default function StudioPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full w-full items-center justify-center bg-[#070B12] text-xs text-sky-300">
          Loading Visko Aerial Studio...
        </div>
      }
    >
      <StudioWorkspace />
    </Suspense>
  );
}
