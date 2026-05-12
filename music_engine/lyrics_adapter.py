import re
import requests


class LyricsAdapter:
    """
    Adapter Pattern: 封裝 LRClib REST API。
    將「artist + title 查詢字串」轉成 Whisper 風格的 lyrics chunks 結構，
    讓下游 Director Agent 用同一份介面處理 DB 歌詞與 ASR 轉錄結果，
    不必感知歌詞來源差異。
    """

    _SEARCH_ENDPOINT = "https://lrclib.net/api/search"
    # LRC 行格式：[mm:ss.xx]文字 或 [mm:ss]文字
    _LRC_LINE_RE = re.compile(r'^\[(\d+):(\d+(?:\.\d+)?)\](.*)$')

    def fetch_synced_lyrics(self, query: str):
        """
        以查詢字串拿同步歌詞。
        - 命中且有 syncedLyrics → 回 {"chunks", "text", "source": "lrclib_synced"}
        - 命中但只有 plainLyrics → 回 {"chunks": [單一 chunk], "text", "source": "lrclib_plain"}
        - 未命中 / 連線失敗 → 回 None，讓 caller 走 fallback
        """
        try:
            response = requests.get(
                self._SEARCH_ENDPOINT,
                params={"q": query},
                timeout=10,
                headers={"User-Agent": "ShortReelsAgent/1.0"},
            )
            response.raise_for_status()
            results = response.json()
        except requests.RequestException as e:
            print(f"[Lyrics] LRClib 連線失敗：{e}")
            return None
        except ValueError as e:
            print(f"[Lyrics] LRClib 回傳非 JSON：{e}")
            return None

        if not results:
            print(f"[Lyrics] LRClib 查無 '{query}'")
            return None

        # 偏好策略：先找有 syncedLyrics（含時間戳）的第一筆，
        # 全部都只有純文字才退而求其次拿第一筆
        for entry in results:
            if entry.get("syncedLyrics"):
                return self._parse_synced(entry)

        first = results[0]
        if first.get("plainLyrics"):
            return self._wrap_plain(first)

        return None

    def _parse_synced(self, entry: dict) -> dict:
        """把 LRC 格式 [mm:ss.xx]text 解析成 Whisper-compatible chunks 列表。"""
        synced = entry["syncedLyrics"]
        raw_lines = []
        for line in synced.splitlines():
            match = self._LRC_LINE_RE.match(line.strip())
            if not match:
                # 跳過 [ti:...] / [ar:...] 等 metadata 行
                continue
            mm, ss, text = match.groups()
            timestamp = int(mm) * 60 + float(ss)
            text = text.strip()
            if text:
                raw_lines.append((timestamp, text))

        if not raw_lines:
            # syncedLyrics 雖有但全是 metadata，退回 plain 路線
            return self._wrap_plain(entry)

        # 每行的 end_time = 下一行的 start_time；最後一行用 LRClib 提供的 duration 補
        track_duration = float(entry.get("duration") or (raw_lines[-1][0] + 5.0))
        chunks = []
        for i, (start, text) in enumerate(raw_lines):
            end = raw_lines[i + 1][0] if i + 1 < len(raw_lines) else track_duration
            chunks.append({"timestamp": [start, end], "text": text})

        full_text = " ".join(c["text"] for c in chunks)
        print(
            f"[Lyrics] LRClib 命中（同步）：{entry.get('artistName')} - "
            f"{entry.get('trackName')} ({len(chunks)} 行)"
        )
        return {"chunks": chunks, "text": full_text, "source": "lrclib_synced"}

    def _wrap_plain(self, entry: dict) -> dict:
        """純文字歌詞無時間戳，包成單一 chunk 撐滿整首歌長度。"""
        plain = entry["plainLyrics"].strip()
        duration = float(entry.get("duration") or 0)
        chunk = {"timestamp": [0.0, duration], "text": plain}
        print(
            f"[Lyrics] LRClib 命中（純文字）：{entry.get('artistName')} - "
            f"{entry.get('trackName')}"
        )
        return {"chunks": [chunk], "text": plain, "source": "lrclib_plain"}
