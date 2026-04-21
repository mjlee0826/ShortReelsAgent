import os
import yt_dlp

class MediaDownloader:
    """
    Adapter Pattern: 封裝 yt-dlp 邏輯。
    統一介面，無縫支援 Instagram Reels, YouTube Shorts, TikTok 等平台。
    """
    def __init__(self, download_dir="temp_templates", cookies_path="cookies.txt"):
        self.download_dir = download_dir
        self.cookies_path = cookies_path
        
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)

    def fetch_video(self, input_source: str) -> dict:
        """
        獲取影片並返回本地路徑與 Metadata。
        """
        # 1. 處理本地檔案的情況 (供開發測試使用)
        if os.path.isfile(input_source):
            return {
                "video_path": input_source,
                "music_metadata": "Unknown (Local File)",
                "original_url": None
            }

        # 2. 處理網址的情況 (主力邏輯)
        # 針對 IG 特性設定參數
        ydl_opts = {
            # 確保畫質與音質都是最優
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            # IG 的 title 通常是一大段貼文，當檔名會出錯，所以改用 id 作為檔名
            'outtmpl': f'{self.download_dir}/%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            # 偽裝成正常的 Windows Chrome 瀏覽器，降低被 IG 阻擋的機率
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
        }

        # 【關鍵防護】如果專案根目錄有提供 cookies.txt，自動掛載以突破 IG 的登入牆
        if os.path.exists(self.cookies_path):
            ydl_opts['cookiefile'] = self.cookies_path
            print("[Downloader] 已掛載 cookies.txt，執行高權限扒取...")
        else:
            print("[Downloader] 警告：未偵測到 cookies.txt，IG 扒取可能會被阻擋。")

        print(f"[Downloader] 正在解析並下載遠端素材: {input_source}")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # extract_info 負責解析網頁並執行下載
                info = ydl.extract_info(input_source, download=True)
                video_path = ydl.prepare_filename(info)
                
                # 3. 擷取音樂資訊 (IG 的音樂 Metadata 邏輯)
                # IG 有時會把音樂放在 track, 有時在 alt_title
                music_info = info.get('track') or info.get('alt_title')
                
                if not music_info:
                    # 如果抓不到特定歌名，代表可能是作者自己的聲音 (Original Audio)
                    uploader = info.get('uploader') or info.get('channel') or "Unknown User"
                    music_info = f"Original Audio by {uploader}"

                return {
                    "video_path": video_path,
                    "music_metadata": music_info,
                    "original_url": input_source
                }
                
        except Exception as e:
            print(f"[Downloader Error] 下載失敗，可能是網址錯誤或被平台阻擋: {e}")
            raise ValueError(f"無法獲取影片素材: {input_source}")