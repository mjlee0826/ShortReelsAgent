import React, { useEffect } from 'react';
import { FaExclamationCircle, FaCog } from 'react-icons/fa';
import useSettingsStore from '../store/useSettingsStore';
import AppHeader from '../components/AppHeader/AppHeader';
import { Card, Select, Spinner } from '../components/ui';

/**
 * 素材預設策略的下拉選項（value 與後端 AssetStrategy 列舉對齊）。
 * 具名常數集中於此，避免 magic string 散落於 JSX。
 */
const STRATEGY_OPTIONS = [
  { value: 'simple', label: 'Simple（本地 Qwen，快速、免 API 成本）' },
  { value: 'complex', label: 'Complex（Gemini 深度分析，較慢、需付費 API）' },
];

/**
 * ToggleSwitch：無障礙開關（role="switch"）。
 *
 * 走 index.css 的 @theme 色票（accent / border / surface），不硬編顏色；
 * 開啟時把滑塊移到右側並轉為強調色，關閉時回中性表面色。
 */
function ToggleSwitch({ checked, onChange, disabled = false, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={[
        'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors',
        'focus:outline-none focus:ring-2 focus:ring-accent/50',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        checked ? 'bg-accent' : 'bg-surface-2 border border-border',
      ].join(' ')}
    >
      <span
        className={[
          'inline-block h-4 w-4 rounded-full bg-white shadow transition-transform',
          checked ? 'translate-x-6' : 'translate-x-1',
        ].join(' ')}
      />
    </button>
  );
}

/**
 * SettingsPage：全域使用者設定頁。
 *
 * 提供兩項偏好：(1) 建立專案後是否自動分析素材、(2) 素材預設分析策略。
 * 採「變更即存」—— 任一控制項變動即呼叫 store 的 updateSetting 送 PATCH。
 */
export default function SettingsPage() {
  const { settings, isLoading, isSaving, errorMsg, fetchSettings, updateSetting, clearError } =
    useSettingsStore();

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  return (
    <div className="flex flex-col h-screen bg-canvas font-sans">
      <AppHeader />

      <main className="flex-1 overflow-y-auto px-6 py-8 max-w-3xl mx-auto w-full">
        {/* 頁首 */}
        <div className="flex items-center gap-2.5 mb-7">
          <span className="w-8 h-8 rounded-lg bg-accent/15 text-accent flex items-center justify-center">
            <FaCog size={15} />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-ink tracking-tight">設定</h1>
            <p className="text-sm text-ink-faint mt-0.5">調整素材分析的預設行為</p>
          </div>
        </div>

        {/* 錯誤訊息 */}
        {errorMsg && (
          <div className="flex items-center gap-2 mb-5 px-4 py-3 bg-danger/10 border border-danger/30 rounded-xl text-danger text-sm">
            <FaExclamationCircle className="shrink-0" />
            <span className="flex-1">{errorMsg}</span>
            <button onClick={clearError} className="text-ink-faint hover:text-ink transition-colors">✕</button>
          </div>
        )}

        {isLoading ? (
          <div className="flex flex-col items-center gap-3 py-20 text-ink-faint">
            <Spinner />
            <p className="text-sm">載入設定中...</p>
          </div>
        ) : (
          <Card className="p-6 flex flex-col gap-7">
            {/* 設定一：建立後是否自動分析 */}
            <div className="flex items-start justify-between gap-6">
              <div className="min-w-0">
                <h2 className="text-sm font-medium text-ink">建立專案後自動分析素材</h2>
                <p className="text-xs text-ink-faint mt-1 leading-relaxed">
                  關閉時（預設），新專案僅會下載素材而不立即分析，讓你先到素材頁逐一挑選 Strategy 後再手動「開始生成」。
                </p>
              </div>
              <ToggleSwitch
                label="建立專案後自動分析素材"
                checked={settings.auto_analyze_on_create}
                disabled={isSaving}
                onChange={(next) => updateSetting({ auto_analyze_on_create: next })}
              />
            </div>

            {/* 分隔線 */}
            <div className="border-t border-border" />

            {/* 設定二：素材預設策略 */}
            <div className="flex flex-col gap-2">
              <Select
                label="素材預設分析策略"
                options={STRATEGY_OPTIONS}
                value={settings.default_asset_strategy}
                disabled={isSaving}
                onChange={(e) => updateSetting({ default_asset_strategy: e.target.value })}
                hint="套用到「未逐檔指定策略」的素材；個別素材在素材頁的設定仍會優先。"
                className="max-w-md"
              />
            </div>
          </Card>
        )}
      </main>
    </div>
  );
}
