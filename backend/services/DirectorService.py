import os
import json
from MediaProcessor.MediaProcessorFactory import MediaProcessorFactory
from MediaTools.MediaStandardizer import MediaStandardizer
from TemplateEngine.TemplateAnalyzerFacade import TemplateAnalyzerFacade
from DirectorAgent.DirectorFacade import DirectorFacade

class DirectorService:
    """
    Service Pattern: 負責協調整個 AI 剪輯流水線 (Pipeline)
    """
    def __init__(self):
        self.base_assets_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        self.standardizer = MediaStandardizer()
        self.template_analyzer = TemplateAnalyzerFacade()
        self.director = DirectorFacade()
        self.backend_url = os.getenv("BACKEND_URL", "http://localhost:5174")

    def run_workflow(self, prompt: str, folder_name: str, template: str = None, 
                    subtitles: bool = True, filters: bool = True, old_timeline: dict = None,
                    video_strategy: str = "2"):
        
        target_dir = os.path.join(self.base_assets_path, folder_name)
        if not os.path.isdir(target_dir):
            raise ValueError(f"找不到素材資料夾: {target_dir}")
        
        # --- 定義各階段的 JSON 儲存路徑 ---
        phase1_dump_path = os.path.join(target_dir, "phase1_assets_metadata.json")
        phase2_dump_path = os.path.join(target_dir, "phase2_template_dna.json")
        phase3_dump_path = os.path.join(target_dir, "phase3_audio_dna.json") # 【新增】Phase 3 存檔路徑
        blueprint_dump_path = os.path.join(target_dir, "phase4_blueprint.json")

        raw_assets_metadata = []
        template_dna = None
        audio_dna = None # 【新增】預設為 None
        
        is_refinement = old_timeline is not None

        # --- 【修改】如果是微調，連同 Phase 3 一起讀取 ---
        if is_refinement and os.path.exists(phase1_dump_path):
            print(f"[Service] 🎯 偵測到微調模式 (Refinement)，跳過耗時感知，載入本地素材快取...")
            with open(phase1_dump_path, 'r', encoding='utf-8') as f:
                raw_assets_metadata = json.load(f)
            
            if template and os.path.exists(phase2_dump_path):
                print(f"[Service] 🎯 載入本地範本 DNA 快取...")
                with open(phase2_dump_path, 'r', encoding='utf-8') as f:
                    template_dna = json.load(f)
                    
            # 【新增】載入 Phase 3 的配樂 DNA
            if os.path.exists(phase3_dump_path):
                print(f"[Service] 🎯 載入本地配樂 DNA (Phase 3) 快取...")
                with open(phase3_dump_path, 'r', encoding='utf-8') as f:
                    audio_dna = json.load(f)
        
        # --- 否則，執行完整的新生成流程 ---
        else:
            self.standardizer.standardize_folder(target_dir)
            all_files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f))]
            
            print(f"[Service] 正在處理 {len(all_files)} 個素材...")
            for filename in all_files:
                if "_std." not in filename:
                    std_version = os.path.splitext(filename)[0] + "_std"
                    if any(std_version in f for f in all_files):
                        continue 

                file_path = os.path.join(target_dir, filename)
                ext = os.path.splitext(filename)[1].lower()
                
                if ext not in ['.mp4', '.mov', '.jpg', '.jpeg', '.png', '.heic', '.heif']:
                    continue

                is_complex = video_strategy == '1' if ext in ['.mp4', '.mov'] else False
                
                try:
                    print(f"   ⏳ 正在分析: {filename} (Complex Mode: {is_complex})")
                    processor = MediaProcessorFactory.create_processor(file_path, is_complex=is_complex)
                    metadata = processor.process(file_path)
                    raw_assets_metadata.append(metadata)
                except Exception as e:
                    print(f"   ⚠️ 分析失敗，跳過 {filename}: {str(e)}")

            if not raw_assets_metadata:
                raise ValueError("資料夾內沒有成功解析的有效素材！")

            with open(phase1_dump_path, 'w', encoding='utf-8') as f:
                json.dump(raw_assets_metadata, f, ensure_ascii=False, indent=2)
                print(f"💾 [Dump] 素材特徵已儲存至 {phase1_dump_path}")

            if template:
                print(f"[Service] 正在提取範本 DNA: {template}")
                template_dna = self.template_analyzer.extract_dna(template)
                
                with open(phase2_dump_path, 'w', encoding='utf-8') as f:
                    json.dump(template_dna, f, ensure_ascii=False, indent=2)
                    print(f"💾 [Dump] 範本 DNA 已儲存至 {phase2_dump_path}")

        enhanced_prompt = prompt
        if not subtitles:
            enhanced_prompt += " (注意：本影片不需要任何字幕，請讓 overlay_text 保持為空)"
        if not filters:
            enhanced_prompt += " (注意：請不要套用任何濾鏡，filter 欄位請設為 none)"

        # --- 5. Phase 4: 導演大腦 (Director Agent) ---
        print("[Service] 正在呼叫導演大腦生成藍圖...")
        
        # 【修改】接收大腦產出的 new_audio_dna
        final_blueprint, new_audio_dna = self.director.generate_timeline(
            user_prompt=enhanced_prompt,
            raw_assets=raw_assets_metadata,
            template_dna=template_dna,
            previous_timeline=old_timeline
        )

        # 【新增】如果大腦有去抓新的音樂 (new_audio_dna 有值)，就覆寫舊的並 Dump 存檔
        if new_audio_dna:
            audio_dna = new_audio_dna
            with open(phase3_dump_path, 'w', encoding='utf-8') as f:
                json.dump(audio_dna, f, ensure_ascii=False, indent=2)
                print(f"💾 [Dump] 配樂 DNA 已更新並儲存至 {phase3_dump_path}")

        # --- 6. 全域快取池：轉換為獨立 URL ---
        if audio_dna and isinstance(audio_dna, dict):
            source_audio_path = audio_dna.get("local_path", {}).get("standard", "")
            
            if source_audio_path and os.path.exists(source_audio_path):
                try:
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    cache_dir = os.path.join(project_root, "temp_templates")
                    rel_path = os.path.relpath(source_audio_path, cache_dir)
                    audio_url = f"{self.backend_url}/cache/{rel_path}".replace('\\', '/')
                    
                    if "bgm_track" in final_blueprint and isinstance(final_blueprint["bgm_track"], dict):
                        final_blueprint["bgm_track"]["track_id"] = audio_url
                        
                    print(f"🎵 [Service] 已套用全域快取配樂連結: {audio_url}")
                except Exception as e:
                    print(f"⚠️ [Service] 轉換快取連結失敗: {e}")
            else:
                print(f"⚠️ [Service] 找不到實體配樂檔案: {source_audio_path}")
        
        with open(blueprint_dump_path, 'w', encoding='utf-8') as f:
            json.dump(final_blueprint, f, ensure_ascii=False, indent=2)
            print(f"💾 [Dump] 最終劇本藍圖已儲存至 {blueprint_dump_path}")

        return {
            "blueprint": final_blueprint,
            "audio_dna": audio_dna,
            "assets_root_url": f"{self.backend_url}/static/{folder_name}/" 
        }