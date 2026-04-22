import subprocess
import os

class RemotionAdapter:
    """
    Adapter Pattern: 將底層的 Node.js/Remotion CLI 指令封裝為 Python 友善的介面。
    只負責「跨語言呼叫」，不處理任何商業邏輯。
    """
    def __init__(self):
        # 精確定位到 frontend 資料夾，這是執行 npx 指令的必須條件 (CWD)
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.frontend_dir = os.path.join(self.project_root, "frontend")
        
        # 假設你的 Remotion 註冊點在 Root.jsx (請依據你的專案實際檔名調整)
        self.entry_file = "src/remotion.index.jsx"

    def render_video(self, composition_id: str, props_path: str, output_path: str):
        """
        發射系統指令，啟動無頭瀏覽器進行逐格算圖。
        """
        cmd = [
            "npx", "remotion", "render", 
            self.entry_file,       # 渲染入口檔
            composition_id,        # 畫布 ID
            output_path,           # 輸出 MP4 路徑
            f"--props={props_path}"# 注入的 JSON 藍圖
        ]

        print(f"[RemotionAdapter] 啟動背景算圖指令: {' '.join(cmd)}")
        
        # 執行指令並掛起等待 (capture_output 攔截日誌供除錯)
        result = subprocess.run(
            cmd, 
            cwd=self.frontend_dir, 
            capture_output=True, 
            text=True
        )

        if result.returncode != 0:
            print(f"❌ [RemotionAdapter] 算圖崩潰，Node.js 報錯:\\n{result.stderr}")
            raise RuntimeError(f"Remotion 算圖失敗: {result.stderr}")
        
        return True