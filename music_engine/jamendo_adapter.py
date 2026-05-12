import os
import requests

class JamendoAdapter:
    """
    Adapter Pattern：封裝 Jamendo REST API，提供與 MediaDownloader 一致的搜尋下載介面。
    Jamendo 提供 CC 授權的免費音樂，適用於不考慮版權的配樂策略 (search_free)。
    使用前需設定環境變數 JAMENDO_CLIENT_ID（至 developer.jamendo.com 免費申請）。
    """

    BASE_URL = "https://api.jamendo.com/v3.0/tracks/"
    _CHUNK_SIZE = 8192      # 串流下載的區塊大小（bytes）
    _REQUEST_TIMEOUT = 15   # API 查詢逾時（秒）
    _DOWNLOAD_TIMEOUT = 60  # 音訊下載逾時（秒）

    def __init__(self):
        # client_id 由環境變數注入，避免硬編碼敏感資訊
        self.client_id = os.getenv("JAMENDO_CLIENT_ID", "")

    def search_and_download(self, query: str, output_dir: str) -> str:
        """
        依關鍵字搜尋 Jamendo 並下載第一筆有效結果至 output_dir。
        :param query: 搜尋關鍵字（英文效果最佳，如 "chill summer tropical"）
        :param output_dir: 下載目的資料夾路徑
        :return: 下載完成的本地音訊檔絕對路徑
        :raises RuntimeError: client_id 未設定、無搜尋結果、或下載失敗時拋出
        """
        if not self.client_id:
            raise RuntimeError(
                "JAMENDO_CLIENT_ID 環境變數未設定，請至 developer.jamendo.com 免費申請"
            )

        print(f"[JamendoAdapter] 搜尋關鍵字: {query}")

        params = {
            "client_id": self.client_id,
            "search": query,
            "limit": 5,
            "format": "json",
            "audioformat": "mp31",  # 128kbps MP3，相容性最佳
        }

        response = requests.get(self.BASE_URL, params=params, timeout=self._REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        # Jamendo API 以 headers.code == 0 表示成功
        api_code = data.get("headers", {}).get("code", -1)
        if api_code != 0:
            error_msg = data.get("headers", {}).get("error_message", "未知 API 錯誤")
            raise RuntimeError(f"Jamendo API 錯誤 (code={api_code}): {error_msg}")

        results = data.get("results", [])
        if not results:
            raise RuntimeError(f"Jamendo 查無結果: '{query}'")

        # 取第一筆有可用下載連結的結果
        track, audio_url = None, None
        for candidate in results:
            url = candidate.get("audiodownload") or candidate.get("audio")
            if url:
                track, audio_url = candidate, url
                break

        if not audio_url:
            raise RuntimeError(f"Jamendo 搜尋結果中無可用的下載連結: '{query}'")

        track_id = track.get("id", "unknown")
        track_name = track.get("name", "Unknown")
        artist_name = track.get("artist_name", "Unknown")
        print(f"[JamendoAdapter] 找到: {artist_name} - {track_name} (id={track_id})")

        # 串流下載至 output_dir
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"jamendo_{track_id}.mp3")

        audio_resp = requests.get(audio_url, stream=True, timeout=self._DOWNLOAD_TIMEOUT)
        audio_resp.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in audio_resp.iter_content(chunk_size=self._CHUNK_SIZE):
                if chunk:
                    f.write(chunk)

        print(f"[JamendoAdapter] 下載完成: {output_path}")
        return output_path
