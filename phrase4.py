import os
import json
from datetime import datetime

# 匯入你實作的各 Phase 指揮官與工廠
from MediaProcessor.MediaProcessorFactory import MediaProcessorFactory
from TemplateEngine.TemplateAnalyzerFacade import TemplateAnalyzerFacade
from DirectorAgent.DirectorFacade import DirectorFacade

def save_json(data, filename):
    """工具函式：將產出的 Dictionary 儲存為格式化的 JSON 檔案"""
    if data is None:
        print(f"⚠️ 警告：要儲存的 {filename} 資料為 None，已跳過。")
        return
        
    # 建立 output 資料夾以保持目錄整潔
    os.makedirs("output", exist_ok=True)
    filepath = os.path.join("output", filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"💾 成功儲存 JSON: {filepath}")

def run_integration_test():
    print("=" * 60)
    print("🎬 Short Reels Agent: Phase 1 ~ 4 深度整合測試")
    print("=" * 60)

    # ---------------------------------------------------------
    # 準備階段：收集使用者輸入
    # ---------------------------------------------------------
    asset_dir = input("\n[1/3] 請輸入素材資料夾路徑 (例如: ./assets): ").strip()
    if not os.path.isdir(asset_dir):
        print(f"❌ 找不到資料夾 '{asset_dir}'，測試終止。")
        return

    template_source = input("[2/3] 請輸入 Template 網址或檔案路徑 (若無請直接按 Enter 跳過): ").strip()
    user_prompt = input("[3/3] 請輸入剪輯指令 (例如: 幫我剪一支熱血的 Vlog，配合快節奏音樂): ").strip()

    # ---------------------------------------------------------
    # Phase 1: 素材感知與特徵萃取
    # ---------------------------------------------------------
    print("\n" + "-" * 60)
    print("🧠 [Phase 1] 啟動多模態素材感知...")
    raw_assets_metadata = []
    
    # 抓取資料夾內所有檔案
    all_files = [f for f in os.listdir(asset_dir) if os.path.isfile(os.path.join(asset_dir, f))]
    
    for filename in all_files:
        file_path = os.path.join(asset_dir, filename)
        ext = os.path.splitext(filename)[1].lower()
        
        # 簡單判定：這裡為了測試流暢，影片預設視為一般影片 (is_complex=False)
        # 你可以依據需求改為 True 或加入互動詢問
        is_complex = False 
        
        try:
            print(f"   ⏳ 正在分析: {filename}")
            processor = MediaProcessorFactory.create_processor(file_path, is_complex=is_complex)
            metadata = processor.process(file_path)
            raw_assets_metadata.append(metadata)
        except Exception as e:
            print(f"   ⚠️ 跳過 {filename}: {str(e)}")

    # 儲存 Phase 1 結果
    save_json(raw_assets_metadata, "phase1_assets.json")

    # ---------------------------------------------------------
    # Phase 2: 範本 DNA 提取
    # ---------------------------------------------------------
    template_dna = None
    if template_source:
        print("\n" + "-" * 60)
        print(f"🧬 [Phase 2] 啟動範本逆向工程: {template_source} ...")
        try:
            template_facade = TemplateAnalyzerFacade()
            template_dna = template_facade.extract_dna(template_source)
            save_json(template_dna, "phase2_template.json")
        except Exception as e:
            print(f"❌ 範本解析失敗: {str(e)}")
    else:
        print("\n" + "-" * 60)
        print("⏩ [Phase 2] 使用者未提供 Template，跳過此階段。")

    # ---------------------------------------------------------
    # Phase 3 & 4: 導演大腦排程 (包含動態音樂擷取)
    # ---------------------------------------------------------
    print("\n" + "-" * 60)
    print("🎬 [Phase 4] 喚醒導演大腦 (內部將自動觸發 Phase 3 抓取配樂)...")
    
    try:
        director = DirectorFacade()
        # 注意：我們修改了 DirectorFacade 讓它回傳兩個值
        final_timeline, audio_dna = director.generate_timeline(
            user_prompt=user_prompt,
            raw_assets=raw_assets_metadata,
            template_dna=template_dna
        )

        # 儲存 Phase 3 結果 (Audio DNA)
        save_json(audio_dna, "phase3_audio_dna.json")

        # 儲存 Phase 4 結果 (Final Timeline Draft)
        save_json(final_timeline, "phase4_timeline_blueprint.json")

        # ---------------------------------------------------------
        # 測試對話式微調 (Refinement Mode) - 可選
        # ---------------------------------------------------------
        print("\n" + "-" * 60)
        do_refine = input("🤔 測試完成！是否要測試『對話式微調 (Phase 4 Refinement)』？(y/n): ").strip().lower()
        if do_refine in ['y', 'yes']:
            refine_prompt = input("請輸入修改意見 (例如: 把節奏放慢，刪掉特定畫面): ").strip()
            print("🔄 正在根據舊藍圖進行微調重構...")
            v2_timeline, _ = director.generate_timeline(
                user_prompt=refine_prompt,
                raw_assets=raw_assets_metadata,
                template_dna=template_dna,
                previous_timeline=final_timeline # 把剛剛的結果當作舊稿餵回去
            )
            save_json(v2_timeline, "phase4_timeline_blueprint_V2.json")
            print("✅ V2 版本微調成功！")

        print("\n🎉 系統端到端 (End-to-End) 整合測試圓滿結束！所有 JSON 已存入 output/ 資料夾。")

    except Exception as e:
        print(f"\n❌ [Phase 4 致命錯誤] 導演大腦當機: {str(e)}")


if __name__ == "__main__":
    run_integration_test()