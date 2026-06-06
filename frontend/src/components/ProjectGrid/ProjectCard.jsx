import React, { useState } from 'react';
import { FaPlay, FaFilm, FaTrash, FaThLarge, FaGoogleDrive, FaHdd, FaSync } from 'react-icons/fa';
import { Card, Badge, Button, IconButton, Spinner } from '../ui';
import { SOURCE_GDRIVE, COVER_ASPECT, deriveProjectStatus } from './projectStatus';

// 刪除鈕圖示尺寸（具名常數，避免 magic number；較舊版放大以利點擊）
const DELETE_ICON_SIZE = 16;
// 同步鈕圖示尺寸（具名常數，避免 magic number）
const SYNC_ICON_SIZE = 13;

/**
 * ProjectCard：媒體優先的專案卡片（IG 動態風）。
 *
 * 一致性設計（沿用 AssetCard 的嚴格等高技法）：所有狀態共用同一版型——固定比例封面
 * （美學最高素材縮圖，缺則中性佔位）、右上唯一主狀態膠囊（實心高對比）、左下素材數、
 * 標題 / meta / 標籤列皆單行恆渲染、操作列 mt-auto 釘底。狀態差異「只改固定槽位的內容/顏色」，
 * 絕不新增或移除整個區塊，故不論專案狀態為何，每張卡片高度一致。
 *
 * 互動：點卡片 / 播放鈕進編輯器、「管理素材」進素材頁、hover 顯示刪除（二次確認）。
 */
export default function ProjectCard({ project, onOpen, onManage, onDelete, onSync }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  // 同步為阻塞操作（下載 + Phase 1，可能久），以本地狀態鎖住按鈕避免重複點擊
  const [syncing, setSyncing] = useState(false);
  const isDrive = project.source === SOURCE_GDRIVE;
  const status = deriveProjectStatus(project);

  // 觸發手動同步：完成後 store 會 refetch 刷新 sync_status / 素材數；失敗訊息由 store 設到 errorMsg
  const handleSync = async (e) => {
    e.stopPropagation();
    if (syncing) return;
    setSyncing(true);
    try {
      await onSync?.(project.name);
    } catch {
      // 錯誤已由 store 寫入 errorMsg，此處僅需還原按鈕狀態
    } finally {
      setSyncing(false);
    }
  };

  // 修改日期（鎖單行恆渲染，確保各卡 meta 高度一致）
  const lastModified = new Date(project.last_modified).toLocaleDateString('zh-TW', {
    year: 'numeric', month: 'short', day: 'numeric',
  });

  return (
    <Card
      interactive
      onClick={() => onOpen(project)}
      className="group relative h-full flex flex-col overflow-hidden"
    >
      {/* 封面：美學最高素材縮圖（缺則中性佔位）+ 置中播放鈕 + 主狀態膠囊 + 素材數 */}
      <div className={`relative w-full shrink-0 overflow-hidden bg-surface-2 ${COVER_ASPECT}`}>
        {project.cover_thumbnail_url ? (
          <>
            {/* 底層：美學最高素材縮圖（object-cover 正規化任意尺寸）*/}
            <img
              src={project.cover_thumbnail_url}
              alt={project.display_name}
              loading="lazy"
              className="absolute inset-0 w-full h-full object-cover"
            />
            {/* 置中播放鈕，hover 放大（疊在縮圖上，傳達「播放 / 進編輯器」）*/}
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="w-12 h-12 rounded-full bg-white/15 backdrop-blur-sm ring-1 ring-white/25 flex items-center justify-center text-white text-lg transition-transform group-hover:scale-110">
                <FaPlay className="ml-0.5" />
              </span>
            </div>
          </>
        ) : (
          // 無已分析素材：乾淨中性佔位（置中影片圖示，比照 AssetCard）
          <div className="absolute inset-0 flex items-center justify-center text-ink-faint/40 text-4xl">
            <FaFilm />
          </div>
        )}

        {/* 底部暗化，讓左下素材數可讀 */}
        <div className="absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-black/40 to-transparent" />

        {/* 右上：唯一主狀態膠囊（永遠存在，只變色/變字；實心高對比以疊在縮圖上仍清楚）*/}
        <div className="absolute top-2.5 right-2.5">
          <Badge tone={status.tone} solid>
            {status.pulse && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
            {status.label}
          </Badge>
        </div>

        {/* 左下：素材數（永遠存在，0 也顯示）*/}
        <span className="absolute left-2.5 bottom-2.5 inline-flex items-center gap-1 text-[11px] font-medium text-white/95">
          <FaFilm size={10} /> {project.asset_count} 素材
        </span>

        {/* hover 刪除（左上，與右上膠囊錯開）*/}
        <div
          className="absolute top-2.5 left-2.5 opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={(e) => e.stopPropagation()}
        >
          {confirmDelete ? (
            <div className="flex items-center gap-1">
              <button
                onClick={() => onDelete(project.name)}
                className="text-[11px] px-2 py-1 bg-danger/90 hover:bg-danger text-white rounded-lg transition-colors"
              >
                確認刪除
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="text-[11px] px-2 py-1 bg-black/50 text-white/90 hover:bg-black/70 rounded-lg transition-colors"
              >
                取消
              </button>
            </div>
          ) : (
            <IconButton tone="overlay-danger" className="w-9 h-9" onClick={() => setConfirmDelete(true)} title="刪除專案">
              <FaTrash size={DELETE_ICON_SIZE} />
            </IconButton>
          )}
        </div>
      </div>

      {/* 資訊 + 操作（p-4 內距；flex-1 撐高使操作列釘底）*/}
      <div className="flex flex-col gap-2 p-4 flex-1">
        {/* 標題（單行）*/}
        <h3 className="text-ink font-semibold text-base leading-tight truncate" title={project.display_name}>
          {project.display_name}
        </h3>

        {/* meta（單行恆渲染，固定行高）*/}
        <p className="text-ink-faint text-xs truncate h-4 leading-4">
          {project.asset_count} 個素材 · {lastModified}
        </p>

        {/* 標籤列（固定 min-h 恆渲染；來源 chip 永遠存在 → 各卡等高）*/}
        <div className="flex flex-wrap items-center gap-1.5 min-h-[22px]">
          {isDrive ? (
            <Badge tone="accent"><FaGoogleDrive size={10} /> Drive</Badge>
          ) : (
            <Badge tone="neutral"><FaHdd size={10} /> 本機</Badge>
          )}
          {project.has_blueprint && <Badge tone="success">已有藍圖</Badge>}
        </div>

        {/* 操作列（mt-auto 釘底）：管理素材 + Drive 專案的手動同步鈕；進編輯器改由點卡片 / 播放鈕觸發 */}
        <div className="mt-auto pt-1 flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            fullWidth
            leftIcon={<FaThLarge size={11} />}
            onClick={(e) => { e.stopPropagation(); onManage(project); }}
          >
            管理素材
          </Button>
          {/* 同步鈕僅雲端來源專案顯示；同步中顯示 Spinner 並禁用，避免重複觸發 */}
          {isDrive && (
            <IconButton
              tone="accent"
              className="shrink-0"
              disabled={syncing}
              onClick={handleSync}
              title={syncing ? '同步中…' : '同步 Google Drive 素材'}
            >
              {syncing ? <Spinner size="sm" /> : <FaSync size={SYNC_ICON_SIZE} />}
            </IconButton>
          )}
        </div>
      </div>
    </Card>
  );
}
