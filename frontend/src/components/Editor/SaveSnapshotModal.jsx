import React, { useState } from 'react';
import { Modal, Input, Button } from '../ui';
import { FaLayerGroup } from 'react-icons/fa';

/**
 * SaveSnapshotModal：「存成版本」的命名彈窗（取代原生 window.prompt）。
 *
 * 以設計系統的 Modal + Input 呈現；Enter 直接儲存、Esc / 取消關閉。
 * @param {string} defaultLabel 預設版本名稱
 * @param {(label: string) => void} onSave 確認儲存（傳出最終名稱）
 * @param {() => void} onClose 關閉彈窗
 */
export default function SaveSnapshotModal({ defaultLabel = '', onSave, onClose }) {
  const [label, setLabel] = useState(defaultLabel);

  // 名稱留空時退回預設名，避免存出空白標題
  const handleSave = () => {
    onSave(label.trim() || defaultLabel);
    onClose();
  };

  // Enter 即儲存（輸入框內快速確認）
  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSave();
    }
  };

  return (
    <Modal
      title="存成版本"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button variant="primary" onClick={handleSave}>儲存版本</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-start gap-3 text-sm text-ink-muted">
          <span className="w-9 h-9 rounded-xl bg-accent/15 text-accent flex items-center justify-center shrink-0">
            <FaLayerGroup />
          </span>
          <p className="leading-relaxed">
            為目前的編輯狀態建立一個版本檢查點，之後可隨時從左側清單還原。
          </p>
        </div>
        <Input
          label="版本名稱"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="例如：節奏加快版"
          autoFocus
        />
      </div>
    </Modal>
  );
}
