import React, { useState } from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import useProjectStore from '../../store/useProjectStore';
import { Modal, Select, Input, Button } from '../ui';
import { FaMusic } from 'react-icons/fa';
import { makeMusicOptions, MUSIC_NONE, MUSIC_STRATEGY_DEFAULT } from '../../constants/music';
import MusicUploadField from './MusicUploadField';

// 配樂策略選項（none 標籤：換曲情境用「移除配樂」）
const MUSIC_OPTIONS = makeMusicOptions('🔇 移除配樂');

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

  const [strategy, setStrategy] = useState(MUSIC_STRATEGY_DEFAULT);
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

            <MusicUploadField
              uploadedFile={uploadedMusicFile}
              isUploading={isUploadingMusic}
              onSelectFile={handleUpload}
              onClear={clearUploadedMusic}
              label="或上傳自訂 BGM（優先於搜尋）"
            />
          </>
        )}
      </div>
    </Modal>
  );
}
