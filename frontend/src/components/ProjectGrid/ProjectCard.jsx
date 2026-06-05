import React, { useState } from 'react';
import { FaPlay, FaFilm, FaTrash, FaThLarge, FaPen, FaGoogleDrive, FaHdd } from 'react-icons/fa';
import { Card, Badge, Button, IconButton } from '../ui';
import { SOURCE_GDRIVE, COVER_ASPECT, deriveProjectStatus, coverGradientStyle } from './projectStatus';

/**
 * ProjectCard：媒體優先的專案卡片（IG 動態風）。
 *
 * 一致性設計（沿用 AssetCard 的嚴格等高技法）：所有狀態共用同一版型——固定比例漸層封面、
 * 右上唯一主狀態膠囊、左下素材數、標題 / meta / 標籤列皆單行恆渲染、操作列 mt-auto 釘底。
 * 狀態差異「只改固定槽位的內容/顏色」，絕不新增或移除整個區塊，故不論專案狀態為何，每張卡片高度一致。
 *
 * 互動：點卡片進編輯器、「管理」進素材頁、hover 顯示刪除（二次確認）。
 */
export default function ProjectCard({ project, onOpen, onManage, onDelete }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const isDrive = project.source === SOURCE_GDRIVE;
  const status = deriveProjectStatus(project);

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
      {/* 封面：確定性漸層 + 置中播放鈕（影片感）+ 主狀態膠囊 + 素材數 */}
      <div className={`relative w-full shrink-0 ${COVER_ASPECT}`} style={coverGradientStyle(project.name)}>
        {/* 置中播放鈕，hover 放大 */}
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="w-12 h-12 rounded-full bg-white/15 backdrop-blur-sm ring-1 ring-white/25 flex items-center justify-center text-white text-lg transition-transform group-hover:scale-110">
            <FaPlay className="ml-0.5" />
          </span>
        </div>

        {/* 底部暗化，讓左下素材數可讀 */}
        <div className="absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-black/40 to-transparent" />

        {/* 右上：唯一主狀態膠囊（永遠存在，只變色/變字）*/}
        <div className="absolute top-2.5 right-2.5">
          <Badge tone={status.tone}>
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
            <IconButton tone="danger" className="w-7 h-7" onClick={() => setConfirmDelete(true)} title="刪除專案">
              <FaTrash size={11} />
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

        {/* 操作列（mt-auto 釘底；按鈕 stopPropagation 避免與卡片點擊衝突）*/}
        <div className="mt-auto flex items-center gap-2 pt-1">
          <Button
            variant="primary"
            size="sm"
            fullWidth
            leftIcon={<FaPen size={11} />}
            onClick={(e) => { e.stopPropagation(); onOpen(project); }}
          >
            進入編輯器
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<FaThLarge size={11} />}
            onClick={(e) => { e.stopPropagation(); onManage(project); }}
          >
            管理
          </Button>
        </div>
      </div>
    </Card>
  );
}
