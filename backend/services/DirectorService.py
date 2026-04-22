import os
import json
# 匯入你先前實作的 Phase 1-4 核心組件
from MediaProcessor.MediaProcessorFactory import MediaProcessorFactory
from MediaTools.MediaStandardizer import MediaStandardizer
from TemplateEngine.TemplateAnalyzerFacade import TemplateAnalyzerFacade
from DirectorAgent.DirectorFacade import DirectorFacade

class DirectorService:
    """
    Service Pattern: 負責協調整個 AI 剪輯流水線 (Pipeline)
    """
    def __init__(self):
        # 取得 backend/assets 的絕對路徑
        self.base_assets_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        self.standardizer = MediaStandardizer()
        self.template_analyzer = TemplateAnalyzerFacade()
        self.director = DirectorFacade()

    def _save_json_dump(self, data, filename):
        """新增：輔助方法，將中間結果儲存為 JSON 以供偵錯"""
        try:
            os.makedirs("output", exist_ok=True)
            filepath = os.path.join("output", filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            print(f"💾 [Dump] 成功儲存中間產物: {filepath}")
        except Exception as e:
            print(f"⚠️ [Dump] 儲存 {filename} 失敗: {str(e)}")

    def run_workflow(self, prompt: str, folder_name: str, template: str = None, 
                    subtitles: bool = True, filters: bool = True, old_timeline: dict = None,
                    video_strategy: str = "2"): # 預設為一般影片
        
        # --- 1. 資料夾映射與素材掃描 (復刻 phrase4.py) ---
        target_dir = os.path.join(self.base_assets_path, folder_name)
        if not os.path.isdir(target_dir):
            raise ValueError(f"找不到素材資料夾: {target_dir}")
        
        # self.standardizer.standardize_folder(target_dir)

        # 抓取資料夾內所有檔案 (忽略大小寫問題，比 glob 更穩)
        all_files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f))]
        
        # --- 2. Phase 1: 素材感知 (Media Ingestion) ---
        print(f"[Service] 正在處理 {len(all_files)} 個素材...")
        raw_assets_metadata = []
        
        for filename in all_files:
            if "_std." not in filename:
                std_version = os.path.splitext(filename)[0] + "_std"
                # 檢查目錄下是否有對應的標準化版本
                if any(std_version in f for f in all_files):
                    continue # 跳過非標素材，改用標素材

            file_path = os.path.join(target_dir, filename)
            ext = os.path.splitext(filename)[1].lower()
            
            # 過濾不支援的檔案
            if ext not in ['.mp4', '.mov', '.jpg', '.jpeg', '.png', '.heic', '.heif']:
                print(f"   ⚠️ 跳過不支援的檔案: {filename}")
                continue

            # 根據策略決定當前檔案的 is_complex 狀態
            is_complex = False
            if ext in ['.mp4', '.mov']:
                if video_strategy == '1':
                    is_complex = True
                elif video_strategy == '2':
                    is_complex = False
                # 注意：在 API 模式下，無法像 CLI 一樣中斷並詢問使用者 (策略 3)。
            
            try:
                print(f"   ⏳ 正在分析: {filename} (Complex Mode: {is_complex})")
                processor = MediaProcessorFactory.create_processor(file_path, is_complex=is_complex)
                metadata = processor.process(file_path)
                raw_assets_metadata.append(metadata)
            except Exception as e:
                print(f"   ⚠️ 分析失敗，跳過 {filename}: {str(e)}")

        if not raw_assets_metadata:
            raise ValueError("資料夾內沒有成功解析的有效素材！")

        self._save_json_dump(raw_assets_metadata, "phase1_assets.json")

        # --- 3. Phase 2: 範本 DNA 提取 ---
        template_dna = None
        if template:
            print(f"[Service] 正在提取範本 DNA: {template}")
            template_dna = self.template_analyzer.extract_dna(template)
            self._save_json_dump(template_dna, "phase2_template.json")

        # --- 4. 處理勾選框邏輯 (Prompt 注入) ---
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

        self._save_json_dump(audio_dna, "phase3_audio_dna.json")
        self._save_json_dump(final_blueprint, "phase4_timeline_blueprint.json")

        # 回傳最終給前端 Remotion 渲染的資料包
        return {
            "blueprint": final_blueprint,
            "audio_dna": audio_dna,
            "assets_root_url": f"http://localhost:5174/static/{folder_name}/" # 讓前端知道去哪裡抓檔案
        }