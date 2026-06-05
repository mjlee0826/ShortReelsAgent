import React from 'react';

/**
 * EmptyState：空 / 載入狀態的置中版面（圖示 + 標題 + 說明 + 選填動作）。
 */
export default function EmptyState({ icon = null, title, description = null, action = null }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-20 gap-3">
      {icon && <div className="text-ink-faint/40 text-5xl mb-1">{icon}</div>}
      <p className="text-ink-muted text-base">{title}</p>
      {description && <p className="text-sm text-ink-faint max-w-sm">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
