import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import GenerationForm from './GenerationForm';
import { Modal } from '../ui';

const MUSIC_SEARCH_COPYRIGHT = 'search_copyright';

/**
 * RegeneratePanel：編輯階段的「重新生成 / 變更設定」彈窗。
 *
 * 收納所有屬「重新生成」邊界的設定（配樂策略 / 上傳 BGM / 字幕·濾鏡總開關 / 導演指令），
 * 送出後關閉彈窗，loading 遮罩由工作台顯示。重新生成會以全新藍圖取代（可用 Undo 還原）。
 * @param {() => void} onClose 關閉彈窗
 */
export default function RegeneratePanel({ onClose }) {
  const musicStrategy = useBlueprintStore((s) => s.musicStrategy);

  return (
    <Modal title="重新生成 / 變更設定" onClose={onClose} maxWidth="max-w-lg">
      {/* 版權風險提示（search_copyright 策略時顯示）*/}
      {musicStrategy === MUSIC_SEARCH_COPYRIGHT && (
        <div className="bg-warning/10 border-l-4 border-warning text-warning px-4 py-3 text-sm rounded-r-xl mb-5">
          ⚠️ 此配樂策略可能含有版權音樂，發布至 IG / TikTok 可能遭靜音或下架。
        </div>
      )}

      <p className="text-xs text-ink-faint mb-4 leading-relaxed">
        變更以下設定將請 AI 重新生成整支影片。手動編輯的細節可能被覆蓋，必要時可用上方「復原」還原。
      </p>

      <GenerationForm submitLabel="🔄 重新生成" showProject={false} onSubmitted={onClose} />
    </Modal>
  );
}
