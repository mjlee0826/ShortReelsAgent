import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import GenerationForm from './GenerationForm';
import { Modal } from '../ui';

const MUSIC_SEARCH_COPYRIGHT = 'search_copyright';

/**
 * RegeneratePanel：生成設定彈窗，依藍圖狀態同時擔任「初次生成」與「重新生成」入口。
 *
 * 收納所有屬「重新生成」邊界的設定（配樂策略 / 上傳 BGM / 字幕·濾鏡總開關 / 導演指令），
 * 送出後關閉彈窗，loading 遮罩由工作台顯示。已有藍圖時為「重新生成」（以全新藍圖取代，可用 Undo 還原），
 * 尚無藍圖時為「初次生成」（無覆蓋風險，且顯示當前專案唯讀列）。
 * @param {() => void} onClose 關閉彈窗
 */
export default function RegeneratePanel({ onClose }) {
  const musicStrategy = useBlueprintStore((s) => s.musicStrategy);
  const hasBlueprint = useBlueprintStore((s) => !!s.blueprint);

  return (
    <Modal title={hasBlueprint ? '重新生成 / 變更設定' : '初次生成影片'} onClose={onClose} maxWidth="max-w-lg">
      {/* 版權風險提示（search_copyright 策略時顯示）*/}
      {musicStrategy === MUSIC_SEARCH_COPYRIGHT && (
        <div className="bg-warning/10 border-l-4 border-warning text-warning px-4 py-3 text-sm rounded-r-xl mb-5">
          ⚠️ 此配樂策略可能含有版權音樂，發布至 IG / TikTok 可能遭靜音或下架。
        </div>
      )}

      {/* 手動編輯遺失警訊（僅在已有藍圖時顯示）：重新生成以全新藍圖取代，逐段就地編輯可能被覆蓋 */}
      {hasBlueprint && (
        <div className="bg-warning/10 border-l-4 border-warning text-warning px-4 py-3 text-sm rounded-r-xl mb-5">
          ⚠️ 重新生成會以全新藍圖取代目前影片，<strong>手動編輯的結果可能消失</strong>；必要時可用上方「復原」還原。
        </div>
      )}

      <GenerationForm
        submitLabel={hasBlueprint ? '🔄 重新生成' : '🎬 開始生成影片'}
        showProject={!hasBlueprint}
        onSubmitted={onClose}
      />
    </Modal>
  );
}
