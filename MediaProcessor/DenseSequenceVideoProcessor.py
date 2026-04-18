import os
import numpy as np
import tempfile
import subprocess
from MediaProcessor.AbstractVideoProcessor import AbstractVideoProcessor
from Model.QwenModelManager import QwenModelManager
from PromptManager.TaskMode import TaskMode

class DenseSequenceVideoProcessor(AbstractVideoProcessor):
    """
    具體策略 B：針對 15 秒以上的長影音或跳舞影片。
    邏輯：放棄全局美學評分，將影片每 3 秒切割為一個物理片段，
    密集呼叫 Qwen 建立「絕對時間動作索引 (Action Index)」，為精準對齊音樂重拍做準備。
    """
    def __init__(self):
        super().__init__()
        # 只載入 Qwen，不載入單張打分大腦，節省 VRAM
        self.vision_engine = QwenModelManager()
        self.chunk_duration = 3.0 # 每 3 秒一個切片

    def analyze_visual_semantics(self, file_path: str, duration: float) -> dict:
        action_index = []
        
        # 迴圈依序切割並分析
        for start_time in np.arange(0, duration, self.chunk_duration):
            end_time = min(start_time + self.chunk_duration, duration)
            if end_time - start_time < 1.0: # 忽略結尾不到 1 秒的碎段
                continue
                
            temp_chunk = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            chunk_path = temp_chunk.name
            temp_chunk.close()

            try:
                # 使用 FFmpeg 無損且極速地切出 3 秒的影片區段給 Qwen
                # -ss 放在 -i 前面可大幅加快切割速度
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(start_time), "-t", str(end_time - start_time), 
                        "-i", file_path, "-c", "copy", chunk_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )

                # 詢問：「這 3 秒內發生了什麼關鍵動作？」
                vlm_result = self.vision_engine.analyze_media(chunk_path, media_type=TaskMode.ACTION_INDEX)
                
                action_index.append({
                    "start_time": round(start_time, 2),
                    "end_time": round(end_time, 2),
                    "action_description": vlm_result.get("caption", "Unknown action")
                })
            finally:
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)

        return {
            "is_dense_indexed": True,
            "action_index": action_index,
            # 長影片難以用單一張定生死，故給予預設值或跳過
            "technical_score": None, 
            "aesthetic_score": None
        }