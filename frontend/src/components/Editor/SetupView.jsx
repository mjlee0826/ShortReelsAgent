import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import GenerationForm from './GenerationForm';
import { FaMagic } from 'react-icons/fa';

const MUSIC_SEARCH_COPYRIGHT = 'search_copyright';

/**
 * SetupView：兩階段中的「生成前」聚焦畫面。
 *
 * blueprint 尚未產生時顯示，置中呈現生成表單，把使用者注意力集中在拿到第一版影片。
 * 生成成功後 EditorPage 會切換到 Workbench（編輯工作台）。
 */
export default function SetupView() {
  const { errorMsg, musicStrategy } = useBlueprintStore();

  return (
    <div className="flex-1 overflow-y-auto bg-canvas">
      <div className="max-w-xl mx-auto px-6 py-12">
        {/* 標題區 */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-accent/15 text-accent flex items-center justify-center text-2xl mx-auto mb-4">
            <FaMagic />
          </div>
          <h1 className="text-2xl font-bold text-ink tracking-wide">AI 導演工作台</h1>
          <p className="text-sm text-ink-faint mt-2">描述你的需求，讓 AI 導演為你剪出第一版短影音</p>
        </div>

        {/* 系統錯誤提示 */}
        {errorMsg && (
          <div className="bg-danger/15 text-danger px-4 py-3 text-sm font-medium rounded-xl border border-danger/30 mb-5">
            ⚠️ {errorMsg}
          </div>
        )}

        {/* 版權風險提示（search_copyright 策略時顯示）*/}
        {musicStrategy === MUSIC_SEARCH_COPYRIGHT && (
          <div className="bg-warning/10 border-l-4 border-warning text-warning px-4 py-3 text-sm rounded-r-xl mb-5">
            ⚠️ 此配樂策略可能含有版權音樂，發布至 IG / TikTok 可能遭靜音或下架。建議直接在發布平台套用官方音樂庫。
          </div>
        )}

        {/* 生成表單卡片 */}
        <div className="bg-surface border border-border rounded-2xl p-6">
          <GenerationForm submitLabel="🎬 開始生成影片" showProject />
        </div>
      </div>
    </div>
  );
}
