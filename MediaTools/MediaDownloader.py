import os
import yt_dlp


class MediaDownloader:
    """
    Adapter Pattern：將 yt-dlp 的複雜介面封裝成簡潔的領域介面。
    對外只暴露 fetch_video / search_and_download_audio 兩個方法，
    呼叫端無需了解 yt-dlp 的設定細節。
    """

    def __init__(self, download_dir: str = "temp_templates", cookies_path: str = "cookies.txt"):
        self.download_dir = os.path.abspath(download_dir)
        self.cookies_path = os.path.abspath(cookies_path)
        os.makedirs(self.download_dir, exist_ok=True)

    # ------------------------------------------------------------------ #
    # 私有工具方法                                                         #
    # ------------------------------------------------------------------ #

    def _base_ydl_opts(self) -> dict:
        """
        Template Method Pattern：提供所有下載任務共用的基礎參數。
        各公開方法在此基礎上用 ** 解包後再擴充，確保 cookies 等設定一致。
        """
        opts: dict = {
            'quiet': False,
            'no_warnings': False,
            'nocheckcertificate': True,
            'js_runtimes': 'nodejs',
        }
        # 若專案根目錄有 cookies.txt，自動掛載以突破平台登入牆
        if os.path.exists(self.cookies_path):
            opts['cookiefile'] = self.cookies_path
        return opts

    # ------------------------------------------------------------------ #
    # 公開介面                                                             #
    # ------------------------------------------------------------------ #

    def fetch_video(self, input_source: str) -> dict:
        """從 URL 或本地路徑取得影片，回傳路徑與音樂 Metadata。"""
        # 本地檔案直接回傳，供開發測試使用
        if os.path.isfile(input_source):
            return {
                "video_path": input_source,
                "music_metadata": "Unknown (Local File)",
                "original_url": None,
            }

        ydl_opts = {
            **self._base_ydl_opts(),
            # 優先取最高畫質 mp4 + m4a；IG title 常是長貼文，改用 id 當檔名避免路徑錯誤
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': f'{self.download_dir}/%(id)s.%(ext)s',
            # 偽裝成 Windows Chrome，降低被 IG 偵測為 bot 的機率
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
            },
        }

        if not os.path.exists(self.cookies_path):
            print("[Downloader] 警告：未偵測到 cookies.txt，IG 扒取可能會被阻擋。")
        else:
            print("[Downloader] 已掛載 cookies.txt，執行高權限扒取...")

        print(f"[Downloader] 正在解析並下載遠端素材: {input_source}")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(input_source, download=True)
                video_path = ydl.prepare_filename(info)

                # IG 的音樂資訊可能存放於 track 或 alt_title 欄位
                music_info = info.get('track') or info.get('alt_title')
                if not music_info:
                    # 抓不到歌名代表是作者的原聲（Original Audio）
                    uploader = info.get('uploader') or info.get('channel') or "Unknown User"
                    music_info = f"Original Audio by {uploader}"

                return {
                    "video_path": video_path,
                    "music_metadata": music_info,
                    "original_url": input_source,
                }

        except Exception as e:
            print(f"[Downloader Error] 下載失敗，可能是網址錯誤或被平台阻擋: {e}")
            raise ValueError(f"無法獲取影片素材: {input_source}")

    def search_and_download_audio(self, search_query: str) -> str:
        """透過 YouTube 搜尋關鍵字並下載最佳音訊檔，回傳本地路徑。"""
        music_dir = os.path.join(self.download_dir, "music_cache")
        os.makedirs(music_dir, exist_ok=True)

        if os.path.exists(self.cookies_path):
            print(f"[Downloader] 成功找到並掛載 Cookie: {self.cookies_path}")
        else:
            print(f"[Downloader] 警告：找不到 Cookie 檔案於 {self.cookies_path}")

        print(f"[Downloader] 從 YouTube 搜尋: {search_query}")

        ydl_opts = {
            **self._base_ydl_opts(),
            'format': 'bestaudio/best',
            'outtmpl': f'{music_dir}/%(id)s.%(ext)s',
            'default_search': 'ytsearch1',
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=True)

                # 搜尋結果以 playlist 格式回傳；被 match_filter 拒絕的 entry 在 entries 中為 None
                if 'entries' in info:
                    valid = [e for e in info['entries'] if e is not None]
                    if not valid:
                        raise RuntimeError(f"YouTube 搜尋無結果: {search_query}")
                    info = valid[0]

                return ydl.prepare_filename(info)

        except Exception as e:
            print(f"[Downloader Error] YouTube 搜尋或下載失敗: {e}")
            raise
