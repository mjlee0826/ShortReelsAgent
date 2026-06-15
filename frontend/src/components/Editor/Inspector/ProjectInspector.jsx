import React from 'react';
import { useNavigate } from 'react-router-dom';
import useBlueprintStore from '../../../store/useBlueprintStore';
import { InspectorSection, ReadonlyRow, ToggleRow } from './controls';
import { Button } from '../../ui';
import { FaSyncAlt, FaCog } from 'react-icons/fa';

// 輸出規格（與 VideoPlayer 的 composition 尺寸一致，固定值）
const OUTPUT_RESOLUTION = '1080 × 1920';
const DEFAULT_FPS = 30;
const DEFAULT_ASPECT = '9:16';

// 運鏡旗標的退化預設（須與 MainTimeline 讀取時的 fallback 一致，避免顯示與實際渲染不符）：
// auto_motion 舊藍圖無欄位 → 視為關閉；auto_punch 舊藍圖無欄位 → 預設開（維持「運鏡開即有卡點」）。
const DEFAULT_AUTO_MOTION = false;
const DEFAULT_AUTO_PUNCH = true;

/**
 * ProjectInspector：未選取特定物件時的全域 / 輸出設定（檢視器預設面板）。
 *
 * fps / 比例 / 解析度為衍生值，唯讀顯示（D5 / 後端 #2）；
 * 字幕·濾鏡總開關與配樂策略屬「重新生成」，集中於 RegeneratePanel。
 * @param {() => void} onRequestRegenerate 要求開啟重新生成面板
 */
export default function ProjectInspector({ onRequestRegenerate }) {
  const global = useBlueprintStore((s) => s.blueprint?.global_settings);
  const updateGlobalSettingField = useBlueprintStore((s) => s.updateGlobalSettingField);
  const navigate = useNavigate();

  // render-time 視覺旗標：即時切換、預覽立即重算（不需重新生成）
  const autoMotion = global?.auto_motion ?? DEFAULT_AUTO_MOTION;
  const autoPunch = global?.auto_punch ?? DEFAULT_AUTO_PUNCH;

  return (
    <div className="flex flex-col">
      <div className="px-5 py-4 border-b border-border bg-surface-2/40">
        <h3 className="text-base font-bold text-ink flex items-center gap-2"><FaCog className="text-accent" /> 專案 / 輸出</h3>
        <p className="text-xs text-ink-faint mt-0.5">點選時間軸上的片段或配樂軌可編輯細項</p>
      </div>

      <InspectorSection title="輸出規格">
        <ReadonlyRow label="解析度" value={OUTPUT_RESOLUTION} locked />
        <ReadonlyRow label="FPS" value={global?.fps ?? DEFAULT_FPS} locked />
        <ReadonlyRow label="比例" value={global?.aspect_ratio || DEFAULT_ASPECT} locked />
      </InspectorSection>

      {/* 運鏡：兩個 render-time 視覺開關，即時切換、預覽立即重算（免重新生成）。
          卡點從屬於自動運鏡——運鏡關閉時整支無逐幀運動，卡點無從疊加，故置灰不可點。 */}
      <InspectorSection title="運鏡">
        <ToggleRow
          label="啟用自動運鏡"
          checked={autoMotion}
          onChange={(v) => updateGlobalSettingField('auto_motion', v)}
          hint="Ken Burns 推近 / 拉遠 / 平移，朝主體緩慢運鏡"
        />
        <ToggleRow
          label="節拍卡點 Punch"
          checked={autoMotion && autoPunch}
          disabled={!autoMotion}
          onChange={(v) => updateGlobalSettingField('auto_punch', v)}
          hint={autoMotion ? '踩配樂重拍的瞬間放大脈衝（需配樂含節拍）' : '需先啟用自動運鏡'}
        />
      </InspectorSection>

      <div className="p-5">
        <Button variant="secondary" size="md" fullWidth leftIcon={<FaSyncAlt size={12} />} onClick={onRequestRegenerate}>
          重新生成 / 變更設定
        </Button>
        <p className="text-xs text-ink-faint mt-2.5 leading-relaxed">
          字幕 / 濾鏡總開關、配樂策略與導演指令的變更需 AI 重新生成。
        </p>
      </div>

      {/* 偏好資料飛輪小提示：讓使用者知道編輯會用於改進 AI，並提供關閉入口（全域設定） */}
      <div className="px-5 pb-5 -mt-1">
        <p className="text-[11px] text-ink-faint/80 leading-relaxed">
          你的編輯會用於改進 AI ·{' '}
          <button
            type="button"
            onClick={() => navigate('/settings')}
            className="text-accent hover:underline"
          >
            可至設定關閉
          </button>
        </p>
      </div>
    </div>
  );
}
