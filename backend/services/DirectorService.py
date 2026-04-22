import os
import glob
# 匯入你先前實作的 Phase 1-4 核心組件
from MediaProcessor.MediaProcessorFactory import MediaProcessorFactory
from TemplateEngine.TemplateAnalyzerFacade import TemplateAnalyzerFacade
from DirectorAgent.DirectorFacade import DirectorFacade

class DirectorService:
    """
    Service Pattern: 負責協調整個 AI 剪輯流水線 (Pipeline)
    """
    def __init__(self):
        # 取得 backend/assets 的絕對路徑
        self.base_assets_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        self.template_analyzer = TemplateAnalyzerFacade()
        self.director = DirectorFacade()

    def run_workflow(self, prompt: str, folder_name: str, template: str = None, 
                    subtitles: bool = True, filters: bool = True, old_timeline: dict = None):
        
        # --- 1. 資料夾映射與素材掃描 ---
        target_dir = os.path.join(self.base_assets_path, folder_name)
        if not os.path.isdir(target_dir):
            raise ValueError(f"找不到素材資料夾: {target_dir}")

        # 搜尋資料夾下的所有影片與圖片 (可根據需求擴充副檔名)
        extensions = ['*.mp4', '*.mov', '*.jpg', '*.png', '*.jpeg']
        asset_files = []
        for ext in extensions:
            asset_files.extend(glob.glob(os.path.join(target_dir, ext)))

        # --- 2. Phase 1: 素材感知 (Media Ingestion) ---
        print(f"[Service] 正在處理 {len(asset_files)} 個素材...")
        raw_assets_metadata = []
        for file_path in asset_files:
            # 這裡暫時預設影片為一般影片 (is_complex=False)，可根據前端需求調整
            processor = MediaProcessorFactory.create_processor(file_path, is_complex=False)
            metadata = processor.process(file_path)
            raw_assets_metadata.append(metadata)

        # --- 3. Phase 2: 範本 DNA 提取 ---
        template_dna = None
        if template:
            print(f"[Service] 正在提取範本 DNA: {template}")
            template_dna = self.template_analyzer.extract_dna(template)

        # --- 4. 處理勾選框邏輯 (Prompt 注入) ---
        # 如果使用者取消勾選字幕或濾鏡，我們在 Prompt 後面加上強制的約束限制
        enhanced_prompt = prompt
        if not subtitles:
            enhanced_prompt += " (注意：本影片不需要任何字幕，請讓 overlay_text 保持為空)"
        if not filters:
            enhanced_prompt += " (注意：請不要套用任何濾鏡，filter 欄位請設為 none)"

        # --- 5. Phase 4: 導演大腦 (Director Agent) ---
        print("[Service] 正在呼叫導演大腦生成藍圖...")
        final_blueprint, audio_dna = self.director.generate_timeline(
            user_prompt=enhanced_prompt,
            raw_assets=raw_assets_metadata,
            template_dna=template_dna,
            previous_timeline=old_timeline
        )

        # 回傳最終給前端 Remotion 渲染的資料包
        return {
            "blueprint": final_blueprint,
            "audio_dna": audio_dna,
            "assets_root_url": f"http://localhost:8000/static/{folder_name}/" # 讓前端知道去哪裡抓檔案
        }