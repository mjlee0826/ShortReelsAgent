import os
import json
from TemplateEngine.TemplateAnalyzerFacade import TemplateAnalyzerFacade

def run_template_extraction_test():
    """
    Phase 2 (Template 逆向工程) 的單一測試管線。
    讓使用者輸入 IG/YT 短影音的網址或本地路徑，並產出 template_dna.json 結構。
    """
    print("="*60)
    print("🎬 Short Reels Agent - Phase 2 測試 (Template 逆向工程)")
    print("="*60)
    
    # 1. 讓使用者輸入網址或路徑
    input_source = input("\n請輸入爆款 Reels 的網址 (或本地 .mp4 測試檔路徑): ").strip()
    
    if not input_source:
        print("輸入不能為空，請重新執行程式。")
        return

    print(f"\n🚀 開始解析 Template: {input_source}\n")

    try:
        # 2. 實例化 Facade (Phase 2 最高指揮官)
        # 這裡會自動聯動 Downloader, Demuxer, PySceneDetect, Librosa 與 Gemini
        facade = TemplateAnalyzerFacade()
        
        # 3. 執行一鍵提取 DNA
        dna_result = facade.extract_dna(input_source)
        
        # 4. 輸出最終的剪輯藍圖
        print(f"\n{'='*60}")
        print("✨ 逆向解析完成！以下是萃取出的 Template DNA 藍圖：")
        print(f"{'='*60}\n")
        
        # 將 Dictionary 轉換為排版漂亮的 JSON 字串並印出
        # ensure_ascii=False 確保如果 Metadata 裡有中文歌名不會變成亂碼
        print(json.dumps(dna_result, indent=4, ensure_ascii=False))

        # 5. 額外貼心功能：將結果存成實體的 JSON 檔案，方便你用編輯器慢慢看
        # output_filename = "template_dna_result.json"
        # with open(output_filename, 'w', encoding='utf-8') as f:
        #     json.dump(dna_result, f, indent=4, ensure_ascii=False)
            
        # print(f"\n💾 該藍圖已自動存檔至專案目錄下的: {output_filename}")

    except Exception as e:
        # 捕捉下載失敗、FFmpeg 缺失或 API 逾時等錯誤
        print(f"\n❌ [測試失敗] 執行過程中發生例外狀況: {str(e)}")

if __name__ == "__main__":
    run_template_extraction_test()