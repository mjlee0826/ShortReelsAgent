import React from 'react';
import SidebarForm from './SidebarForm';
import ChatBox from './ChatBox';
import useBlueprintStore from '../../store/useBlueprintStore';

export default function RightPanel() {
  const { errorMsg } = useBlueprintStore();

  return (
    // 【修改這裡】加寬面板並使用 shrink-0 防止變形
    <div className="w-[450px] xl:w-[500px] shrink-0 h-full flex flex-col bg-gray-900 border-l border-gray-800 shadow-2xl z-10">
      
      {/* 頂部標題 */}
      <div className="p-6 border-b border-gray-800 bg-black">
        <h2 className="text-xl font-bold text-white tracking-wide">AI Director</h2>
        <p className="text-xs text-gray-500 mt-1">Short Reels Agent 控制台</p>
      </div>

      {/* 系統錯誤提示 */}
      {errorMsg && (
        <div className="bg-red-900 text-red-200 p-3 text-sm font-semibold">
          ⚠️ {errorMsg}
        </div>
      )}

      {/* 首次生成設定表單 */}
      <SidebarForm />

      {/* 對話式微調區 */}
      <ChatBox />
    </div>
  );
}