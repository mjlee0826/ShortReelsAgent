import React, { useEffect } from 'react';
import { FaTimes } from 'react-icons/fa';

/**
 * Modal：置中對話框。點背景遮罩或按 Esc 皆可關閉；標題列含關閉鈕。
 * footer 為選填的底部動作區（通常放取消 / 確認按鈕）。
 */
export default function Modal({ title, onClose, children, footer = null, maxWidth = 'max-w-md' }) {
  // 按 Esc 關閉，與點背景遮罩一致的關閉體驗
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 px-4"
      onClick={onClose}
    >
      {/* 內層阻止冒泡，避免點面板本身也觸發關閉 */}
      <div
        className={`bg-elevated border border-border rounded-2xl shadow-2xl w-full ${maxWidth} overflow-hidden`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-border">
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink transition-colors" title="關閉">
            <FaTimes />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
        {footer && (
          <div className="flex justify-end gap-3 px-6 py-4 border-t border-border bg-surface/50">{footer}</div>
        )}
      </div>
    </div>
  );
}
