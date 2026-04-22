import React from 'react';
import SidebarForm from './SidebarForm';
import ChatBox from './ChatBox';
import useBlueprintStore from '../../store/useBlueprintStore';
// 【新增】引入 Spinner 圖示
import { FaSpinner } from 'react-icons/fa';

export default function RightPanel() {
  // 【修改】把 isProcessing 也拿出來
  const { errorMsg, isProcessing } = useBlueprintStore();

  return (
    // 注意這裡原本就有 relative，這是 absolute 遮罩能正確覆蓋的關鍵
    <div className="w-[450px] xl:w-[500px] shrink-0 h-full flex flex-col bg-gray-900 border-l border-gray-800 shadow-2xl z-10 relative">
      
      {/* --- 【新增】載入中遮罩 (Loading Overlay) --- */}
      {isProcessing && (
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm z-50 flex flex-col items-center justify-center transition-all duration-300">
          <FaSpinner className="animate-spin text-blue-500 text-6xl mb-6 shadow-blue-500/50 drop-shadow-lg" />
          <h3 className="text-white font-bold text-xl tracking-widest">AI 導演思考中...</h3>
          <p className="text-gray-400 text-sm mt-3 animate-pulse">正在精確計算時間軸與混音策略</p>
        </div>
      )}
      {/* ------------------------------------------- */}

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