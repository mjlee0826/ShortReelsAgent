import os
import yt_dlp

class MediaDownloader:
    """
    Adapter Pattern: 封裝 yt-dlp 邏輯。
    統一介面，無縫支援 Instagram Reels, YouTube Shorts, TikTok 等平台。
    """
    def __init__(self, download_dir="temp_templates", cookies_path="cookies.txt"):
        self.download_dir = os.path.abspath(download_dir)
        self.cookies_path = os.path.abspath(cookies_path)

        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

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
    
    def _cleanup_music_cache(self, music_dir: str, max_files: int = 20):
        """刪除最舊的快取檔案，防止 music_cache 無限膨脹。"""
        try:
            files = sorted(
                [os.path.join(music_dir, f) for f in os.listdir(music_dir)
                 if os.path.isfile(os.path.join(music_dir, f))],
                key=os.path.getmtime
            )
            while len(files) > max_files:
                oldest = files.pop(0)
                os.remove(oldest)
                print(f"[Downloader] 🗑 清理音樂快取: {os.path.basename(oldest)}")
        except OSError:
            pass

    def search_and_download_audio(self, search_query: str) -> str:
        """
        [Phase 3 新增]
        功能：透過自然語言搜尋全網音樂，並下載為高品質音訊檔。
        """
        music_dir = os.path.join(self.download_dir, "music_cache")
        if not os.path.exists(music_dir):
            os.makedirs(music_dir)

        self._cleanup_music_cache(music_dir, max_files=20)

        # 設定 yt-dlp 參數：僅下載音訊，取搜尋結果的第一筆
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{music_dir}/%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytmsearch1', # 關鍵點：搜尋並取首選
            'nocheckcertificate': True,
        }

        # 掛載 Cookie 以防被阻擋
        if os.path.exists(self.cookies_path):
            ydl_opts['cookiefile'] = self.cookies_path
            print(f"[Downloader] 成功找到並掛載 Cookie: {self.cookies_path}")
        else:
            print(f"[Downloader] 警告：找不到 Cookie 檔案於 {self.cookies_path}")

        print(f"[Downloader] 正在全網搜尋音樂: {search_query}")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=True)
                
                # 處理搜尋結果的資料結構
                if 'entries' in info:
                    info = info['entries'][0]
                
                downloaded_path = ydl.prepare_filename(info)
                return downloaded_path
        except Exception as e:
            print(f"[Downloader Error] 搜尋下載失敗: {e}")
            raise RuntimeError(f"無法獲取音樂資源: {search_query}")