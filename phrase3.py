import json
import time
from MusicEngine.MusicEngineFacade import MusicEngineFacade

def test_music_engine():
    """
    Phase 3 整合測試腳本
    測試目標：驗證 ytsearch 下載、FFmpeg 轉檔、Librosa 節拍分析與 Whisper 聽寫流水線。
    """
    print("=" * 60)
    print("🚀 啟動 Phase 3: 全網音樂直取引擎 (Any Music Engine) 測試")
    print("=" * 60)

    # 1. 實例化 Phase 3 指揮官
    engine = MusicEngineFacade()

    # 2. 設定測試用的 Search Query
    # 測試情境 A (有歌詞): "周杰倫 稻香" 或 "告五人 帶我去找夜生活"
    # 測試情境 B (無歌詞/純音樂): "Chill tropical house vlog bgm no copyright"
    test_query = "周杰倫 稻香" 
    
    print(f"\n🔍 準備發送檢索請求: '{test_query}'\n")
    
    start_time = time.time()

    try:
        # 3. 呼叫 Facade 的一鍵式工作流
        audio_dna = engine.fetch_and_analyze(query=test_query)
        
        end_time = time.time()
        elapsed_time = end_time - start_time

        # 4. 輸出並驗證結果
        print("\n" + "=" * 60)
        print(f"✅ 測試成功！(耗時: {elapsed_time:.2f} 秒)")
        print("=" * 60)
        print("🎵 萃取出的 Audio DNA:")
        
        # 為了避免終端機被龐大的 beats 和 onsets 陣列洗版，我們稍微做一點輸出截斷
        if "analysis" in audio_dna and audio_dna["status"] == "success":
            # 複製一份來修改顯示，避免改到原始資料
            display_dna = audio_dna.copy()
            beats = display_dna["analysis"]["beats"]
            onsets = display_dna["analysis"]["onsets"]
            
            # 只顯示前 5 個節拍點與能量點
            display_dna["analysis"]["beats"] = f"[{len(beats)} 個節拍點] (前5個: {beats[:5]}...)"
            display_dna["analysis"]["onsets"] = f"[{len(onsets)} 個能量點] (前5個: {onsets[:5]}...)"
            
            print(json.dumps(display_dna, indent=4, ensure_ascii=False))
        else:
            print(json.dumps(audio_dna, indent=4, ensure_ascii=False))

    except Exception as e:
        print(f"\n❌ 測試失敗: {e}")

if __name__ == "__main__":
    test_music_engine()