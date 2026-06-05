import React, { useState } from 'react';
import { FaGoogleDrive } from 'react-icons/fa';
import { Modal, Input, Button } from '../ui';

/**
 * CreateProjectModal：建立新專案對話框。
 *
 * 依產品定位，新專案一律來自 Google Drive 資料夾，故「專案名稱」與「Drive 連結」皆為必填；
 * 送出後後端會建立雲端來源專案並於背景啟動首次同步（下載素材 + Phase 1）。
 */
export default function CreateProjectModal({ onClose, onCreate }) {
  const [displayName, setDisplayName] = useState('');
  const [driveLink, setDriveLink] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const canSubmit = displayName.trim() && driveLink.trim();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setIsCreating(true);
    try {
      await onCreate(displayName.trim(), driveLink.trim());
      onClose();
    } catch {
      // 失敗訊息由 store 寫入 errorMsg，這裡僅恢復可再次送出狀態
      setIsCreating(false);
    }
  };

  return (
    <Modal title="建立新專案" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input
          label="專案名稱"
          autoFocus
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="例：婚禮精華 2025"
          maxLength={60}
        />
        <Input
          label="Google Drive 資料夾連結"
          icon={<FaGoogleDrive />}
          value={driveLink}
          onChange={(e) => setDriveLink(e.target.value)}
          placeholder="https://drive.google.com/drive/folders/..."
          hint="請將資料夾分享設為「知道連結的任何人皆可檢視」；建立後素材會於背景自動下載並分析。"
        />
        <div className="flex justify-end gap-3 mt-1">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={!canSubmit} loading={isCreating}>建立專案</Button>
        </div>
      </form>
    </Modal>
  );
}
