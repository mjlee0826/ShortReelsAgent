from scenedetect import detect, ContentDetector

class SceneCutExtractor:
    """
    Adapter Pattern: 封裝 PySceneDetect。
    找出影片中所有物理切點的時間戳記。
    """
    def get_cuts(self, video_path: str) -> list:
        print(f"[Analyzer] 正在計算物理分鏡切點 (Visual Cuts)...")
        # 使用 ContentDetector 偵測像素劇烈變化
        scene_list = detect(video_path, ContentDetector(threshold=27.0))
        
        # 取得每一場景結束的時間點 (即切點)
        cuts = [float(scene[1].get_seconds()) for scene in scene_list]
        return sorted(list(set(cuts))) # 確保唯一且排序