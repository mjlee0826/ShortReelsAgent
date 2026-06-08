import React, { useState } from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import useProjectStore from '../../store/useProjectStore';
import { Modal, Select, Input, Button } from '../ui';
import { FaMusic, FaSpinner, FaTimes } from 'react-icons/fa';

// 配樂策略選項（與生成表單一致）
const MUSIC_OPTIONS = [
  { value: 'search_copyright', label: '🎵 搜尋配樂（可能含版權）' },
  { value: 'search_free', label: '🆓 搜尋免費配樂 (Jamendo CC 授權)' },
  { value: 'none', label: '🔇 移除配樂' },
];
const MUSIC_NONE = 'none';
const ALLOWED_AUDIO_ACCEPT = '.mp3,.wav,.m4a,.aac,.flac,.ogg';

/**
 * ChangeMusicModal：music-only 換曲彈窗（只換配樂、保留時間軸）。
 *
 * 由 BgmInspector 開啟。選策略 / 輸入風格關鍵字 / 或上傳自訂 BGM 後套用，
 * 透過 store.changeMusic 呼叫後端 music-only 路徑，回傳的 bgm_track 就地套用（可 Undo）。
 * @param {() => void} onClose 關閉彈窗
 */
export default function ChangeMusicModal({ onClose }) {
  const folderName = useProjectStore((s) => s.currentProject?.name);
  const {
    uploadedMusicFile, isUploadingMusic, isChangingMusic,
    uploadMusic, clearUploadedMusic, changeMusic,
  } = useBlueprintStore();

  const [strategy, setStrategy] = useState('search_copyright');
  const [query, setQuery] = useState('');

  const handleUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    uploadMusic(folderName, file);
    e.target.value = '';
  };

  // 套用：呼叫 music-only 換曲；成功才清掉上傳暫存並關閉
  const handleApply = async () => {
    const ok = await changeMusic(folderName, {
      musicStrategy: strategy,
      userMusicFile: strategy === MUSIC_NONE ? null : uploadedMusicFile,
      userPrompt: query,
    });
    if (ok) {
      clearUploadedMusic();
      onClose();
    }
  };

  return (
    <Modal
      title="變更配樂"
      onClose={onClose}
      maxWidth="max-w-lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isChangingMusic}>取消</Button>
          <Button variant="primary" onClick={handleApply} loading={isChangingMusic}>
            {isChangingMusic ? '挑選配樂中...' : '套用配樂'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-sm text-ink-faint leading-relaxed">
          只更換配樂、<span className="text-ink-muted">不會重剪時間軸</span>。套用後可用「復原」還原。
        </p>

        <Select
          label="配樂策略"
          icon={<FaMusic />}
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          options={MUSIC_OPTIONS}
        />

        {strategy !== MUSIC_NONE && (
          <>
            <Input
              label="音樂風格關鍵字（選填）"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="例如：輕快、lofi、史詩感、夏日海灘"
            />

            <div className="flex flex-col gap-1.5">
              <label className="text-sm text-ink-muted">或上傳自訂 BGM（優先於搜尋）</label>
              {uploadedMusicFile ? (
                <div className="flex items-center gap-2 bg-success/10 border border-success/30 rounded-xl px-3 py-2">
                  <span className="text-success text-sm flex-1 truncate">✓ {uploadedMusicFile}</span>
                  <button
                    type="button"
                    onClick={clearUploadedMusic}
                    className="text-ink-faint hover:text-danger transition-colors shrink-0"
                    title="移除自訂音樂"
                  >
                    <FaTimes />
                  </button>
                </div>
              ) : (
                <label
                  className={`flex items-center justify-center gap-2 p-2.5 rounded-xl border border-dashed border-border-strong cursor-pointer transition-colors text-sm text-ink-faint ${
                    isUploadingMusic ? 'opacity-50 cursor-not-allowed' : 'hover:border-accent hover:text-accent'
                  }`}
                >
                  {isUploadingMusic
                    ? <><FaSpinner className="animate-spin" /> 上傳中...</>
                    : '+ 選擇音訊檔案 (.mp3 / .wav / .m4a)'}
                  <input
                    type="file"
                    accept={ALLOWED_AUDIO_ACCEPT}
                    onChange={handleUpload}
                    disabled={isUploadingMusic}
                    className="hidden"
                  />
                </label>
              )}
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
