import os
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

    def run_workflow(self, prompt: str, folder_name: str, template: str = None, 
                    subtitles: bool = True, filters: bool = True, old_timeline: dict = None,
                    video_strategy: str = "2"): # 預設為一般影片
        
        target_dir = os.path.join(self.base_assets_path, folder_name)
        if not os.path.isdir(target_dir):
            raise ValueError(f"找不到素材資料夾: {target_dir}")
        
        # --- 1. 素材標準化 ---
        self.standardizer.standardize_folder(target_dir)

        all_files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f))]
        
        # --- 2. Phase 1: 素材感知 ---
        print(f"[Service] 正在處理 {len(all_files)} 個素材...")
        raw_assets_metadata = []
        
        for filename in all_files:
            if "_std." not in filename:
                std_version = os.path.splitext(filename)[0] + "_std"
                if any(std_version in f for f in all_files):
                    continue 

            file_path = os.path.join(target_dir, filename)
            ext = os.path.splitext(filename)[1].lower()
            
            if ext not in ['.mp4', '.mov', '.jpg', '.jpeg', '.png', '.heic', '.heif']:
                continue

            is_complex = False
            if ext in ['.mp4', '.mov']:
                if video_strategy == '1':
                    is_complex = True
                elif video_strategy == '2':
                    is_complex = False
            
            try:
                print(f"   ⏳ 正在分析: {filename} (Complex Mode: {is_complex})")
                processor = MediaProcessorFactory.create_processor(file_path, is_complex=is_complex)
                metadata = processor.process(file_path)
                raw_assets_metadata.append(metadata)
            except Exception as e:
                print(f"   ⚠️ 分析失敗，跳過 {filename}: {str(e)}")

        if not raw_assets_metadata:
            raise ValueError("資料夾內沒有成功解析的有效素材！")

        # --- 3. Phase 2: 範本 DNA 提取 ---
        template_dna = None
        if template:
            print(f"[Service] 正在提取範本 DNA: {template}")
            template_dna = self.template_analyzer.extract_dna(template)

        # --- 4. 處理勾選框邏輯 ---
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

        # --- 【核心修正】6. 全域快取池：轉換為獨立 URL ---
        if audio_dna and isinstance(audio_dna, dict):
            source_audio_path = audio_dna.get("local_path", {}).get("standard", "")
            
            if source_audio_path and os.path.exists(source_audio_path):
                try:
                    # 取得專案根目錄與快取目錄
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    cache_dir = os.path.join(project_root, "temp_templates")
                    
                    # 計算相對路徑 (例如: music_cache/xxxx.wav)
                    rel_path = os.path.relpath(source_audio_path, cache_dir)
                    
                    # 組合出全域快取的 URL (使用 5174 Port)
                    audio_url = f"http://localhost:5174/cache/{rel_path}".replace('\\', '/')
                    
                    # 強制修正 JSON 藍圖，將 track_id 替換為完整 URL
                    if "bgm_track" in final_blueprint and isinstance(final_blueprint["bgm_track"], dict):
                        final_blueprint["bgm_track"]["track_id"] = audio_url
                        
                    print(f"🎵 [Service] 已套用全域快取配樂連結: {audio_url}")
                except Exception as e:
                    print(f"⚠️ [Service] 轉換快取連結失敗: {e}")
            else:
                print(f"⚠️ [Service] 找不到實體配樂檔案: {source_audio_path}")
        # ----------------------------------------------------

        return {
            "blueprint": final_blueprint,
            "audio_dna": audio_dna,
            "assets_root_url": f"http://localhost:5174/static/{folder_name}/" 
        }