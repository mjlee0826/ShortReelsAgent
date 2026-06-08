import React, { useEffect } from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import useProjectStore from '../../store/useProjectStore';
import { Button, IconButton, EmptyState } from '../ui';
import { FaPlus, FaTrashAlt, FaHistory, FaLayerGroup } from 'react-icons/fa';

/** 把 ISO 時間轉成精簡的本地顯示字串 */
function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/**
 * SnapshotPanel：三欄版型左欄——專案的版本快照清單（持久化，跨重整還原）。
 *
 * 「存成版本」把當前 blueprint 存到後端；每筆可還原或刪除。
 * 與工具列的線性 Undo/Redo 互補：這裡是具名檢查點、可跳回任一版本。
 */
export default function SnapshotPanel() {
  const folderName = useProjectStore((s) => s.currentProject?.name);
  const snapshots = useBlueprintStore((s) => s.snapshots);
  const hasBlueprint = useBlueprintStore((s) => !!s.blueprint);
  const loadSnapshots = useBlueprintStore((s) => s.loadSnapshots);
  const saveSnapshot = useBlueprintStore((s) => s.saveSnapshot);
  const restoreSnapshot = useBlueprintStore((s) => s.restoreSnapshot);
  const deleteSnapshot = useBlueprintStore((s) => s.deleteSnapshot);

  // 進入 / 切換專案時載入版本清單
  useEffect(() => {
    if (folderName) loadSnapshots(folderName);
  }, [folderName, loadSnapshots]);

  // 存成版本：以目前時間為預設名，讓使用者可改名
  const handleSave = () => {
    const defaultLabel = `版本 ${formatTime(new Date().toISOString())}`;
    const label = window.prompt('為這個版本命名：', defaultLabel);
    if (label === null) return; // 取消
    saveSnapshot(folderName, label.trim() || defaultLabel);
  };

  const handleDelete = (snapshot) => {
    if (window.confirm(`刪除版本「${snapshot.label}」？`)) {
      deleteSnapshot(folderName, snapshot.id);
    }
  };

  return (
    <div className="w-full h-full flex flex-col bg-surface border-r border-border">
      {/* 標題 + 存成版本 */}
      <div className="px-4 py-4 border-b border-border bg-surface-2/40 shrink-0">
        <h3 className="text-base font-bold text-ink flex items-center gap-2 mb-3">
          <FaLayerGroup className="text-accent" /> 版本快照
        </h3>
        <Button
          variant="secondary"
          size="md"
          fullWidth
          leftIcon={<FaPlus size={12} />}
          disabled={!hasBlueprint}
          onClick={handleSave}
        >
          存成版本
        </Button>
      </div>

      {/* 版本清單 */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
        {snapshots.length === 0 ? (
          <EmptyState icon={<FaLayerGroup />} title="尚無版本" description="編輯到滿意時，按「存成版本」保存一個檢查點。" />
        ) : (
          snapshots.map((snap) => (
            <div
              key={snap.id}
              className="group bg-surface-2 border border-border rounded-xl p-3 hover:border-border-strong transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-ink truncate">{snap.label}</p>
                  <p className="text-xs text-ink-faint mt-0.5">{formatTime(snap.created_at)}</p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <IconButton tone="accent" title="還原此版本" onClick={() => restoreSnapshot(folderName, snap.id)}>
                    <FaHistory size={13} />
                  </IconButton>
                  <IconButton tone="danger" title="刪除此版本" onClick={() => handleDelete(snap)}>
                    <FaTrashAlt size={12} />
                  </IconButton>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
