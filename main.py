import os
import json
from MediaProcessor.MediaProcessorFactory import MediaProcessorFactory

def get_video_strategy() -> str:
    """
    讓使用者選擇影片處理的全局策略。
    """
    print("\n請選擇影片處理策略：")
    print("1. 全部視為「複雜/重要影片」 (使用 Gemini API 進行精確時間碼索引)")
    print("2. 全部視為「一般影片」 (使用本地端 Qwen 進行全局分析)")
    print("3. 每次遇到影片時，個別詢問")
    
    while True:
        choice = input("請輸入選項 (1/2/3): ").strip()
        if choice in ['1', '2', '3']:
            return choice
        print("無效的輸入，請輸入 1, 2 或 3。")

def run_pipeline_test():
    """
    Stage 1 的單執行緒測試管線。
    讓使用者輸入資料夾路徑，並將分析結果輸出至終端機。
    """
    # 1. 讓使用者輸入包含照片與影片的資料夾路徑
    directory_path = input("請輸入要測試的素材資料夾路徑 (例如: ./assets): ").strip()

    # 2. 驗證資料夾是否存在
    if not os.path.isdir(directory_path):
        print(f"錯誤：找不到指定的資料夾 '{directory_path}'，請確認路徑是否正確。")
        return

    # 3. 詢問影片處理策略
    video_strategy = get_video_strategy()

    print(f"\n開始掃描資料夾: {directory_path} ...")
    
    # 取得資料夾內所有的「檔案」(排除子資料夾)
    all_files = [
        f for f in os.listdir(directory_path) 
        if os.path.isfile(os.path.join(directory_path, f))
    ]
    
    if not all_files:
        print("資料夾是空的，沒有找到任何檔案。")
        return

    print(f"共找到 {len(all_files)} 個檔案，開始逐一分析（單執行緒模式）...\n")

    # 4. 遍歷檔案，交由 Factory 分發處理
    for filename in all_files:
        file_path = os.path.join(directory_path, filename)
        ext = os.path.splitext(filename)[1].lower()
        
        print(f"{'='*60}")
        print(f"正在分析: {filename}")
        print(f"{'='*60}")

        # 決定當前檔案的 is_complex 狀態
        is_complex = False
        if ext in ['.mp4', '.mov']:
            if video_strategy == '1':
                is_complex = True
            elif video_strategy == '2':
                is_complex = False
            elif video_strategy == '3':
                # 策略 3：每次遇到影片都詢問一次
                while True:
                    ans = input(f"影片 '{filename}' 是否為複雜/重要影片？(y/n): ").strip().lower()
                    if ans in ['y', 'yes']:
                        is_complex = True
                        break
                    elif ans in ['n', 'no']:
                        is_complex = False
                        break
                    print("請輸入 y 或 n。")

        try:
            # 將決定好的 is_complex 參數傳入 Factory
            processor = MediaProcessorFactory.create_processor(file_path, is_complex=is_complex)
            
            # 執行分析策略
            result = processor.process(file_path)
            
            # 將回傳的 Dictionary 轉換為排版漂亮的 JSON 字串並印出
            # ensure_ascii=False 確保如果遇到中文路徑或字元不會變成亂碼
            print(json.dumps(result, indent=4, ensure_ascii=False))

        except ValueError as e:
            # 捕捉 MediaProcessorFactory 拋出的「不支援檔案格式」錯誤
            print(f"[跳過檔案] {str(e)}")
        except Exception as e:
            # 捕捉其他模型推論或 OpenCV 讀取時的未預期錯誤
            print(f"[系統錯誤] 處理 {filename} 時發生異常: {str(e)}")
            
    print(f"\n{'-'*60}")
    print("測試完畢！所有檔案皆已處理。")
    print(f"{'-'*60}\n")

if __name__ == "__main__":
    # 確保終端機能正常印出資訊
    run_pipeline_test()