import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 改為傳入 mode 來動態讀取環境變數
export default defineConfig(({ mode }) => {
  // 載入目前目錄下的 .env 檔案
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [react(), tailwindcss()],
    server: {
      // 從環境變數讀取 Port，如果沒設定就退回 5173
      port: parseInt(env.VITE_PORT || 5173),
      
      // 【防呆機制】如果 5173 被佔用，直接報錯，不要自動變成 5174
      // 這樣可以防止後端的 CORS (只允許 5173) 突然把前端擋在門外
      strictPort: true, 
      
      // 允許外部 IP 連線 (等同於 0.0.0.0)，方便用手機測試
      host: true 
    }
  }
})