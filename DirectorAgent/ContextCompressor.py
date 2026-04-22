class ContextCompressor:
    """
    Strategy Pattern: 負責素材的特徵降維與防禦性過濾。
    實作「寬容過濾邏輯」：確保 ComplexVideo 不會因為缺乏技術分數而被誤刪。
    """
    def compress(self, raw_assets: list) -> list:
        compressed_list = []
        
        for asset in raw_assets:
            metadata = asset.get("metadata", {})
            
            # --- 1. 防禦性快篩 (作法 B) ---
            # 使用 get 取值，若為 None 或不存在則給予 100.0 (強迫放行)
            tech_score = metadata.get("technical_score")
            if tech_score is None:
                tech_score = 100.0
                
            if tech_score < 40.0:
                print(f"[Compressor] 剔除畫質過低素材: {asset.get('file')}")
                continue

            # --- 2. 特徵降維 (Dimensionality Reduction) ---
            # 僅保留導演決策所需的精華資訊，移除路徑與冗餘資料
            base_info = {
                "id": asset.get("file"), # 使用檔名作為唯一 ID
                "type": asset.get("type"),
                "res": {"w": metadata.get("width"), "h": metadata.get("height")},
                "aes": metadata.get("aesthetic_score", 60.0),
                "cap": metadata.get("caption", ""),
                "focus": metadata.get("subject_focus", {"x_percent": 50, "y_percent": 50})
            }

            # 根據素材類型補強聲音或事件資訊
            if asset.get("type") == "video":
                base_info["dur"] = metadata.get("duration", 0)
                
                # 若為一般影片，濃縮聲音描述
                if not metadata.get("is_dense_indexed"):
                    base_info["audio"] = {
                        "vocal": metadata.get("audio_transcript", {}).get("text", ""),
                        "env": metadata.get("environmental_sounds", "")
                    }
                # 若為 Complex 影片，僅保留事件索引
                else:
                    base_info["is_complex"] = True
                    base_info["events"] = metadata.get("multimodal_event_index", [])

            compressed_list.append(base_info)
            
        return compressed_list