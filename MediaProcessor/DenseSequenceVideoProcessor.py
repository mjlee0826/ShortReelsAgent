import os
import cv2
import numpy as np
import tempfile
import subprocess
from PIL import Image
from MediaProcessor.AbstractVideoProcessor import AbstractVideoProcessor
from Model.QwenModelManager import QwenModelManager
from PromptManager.TaskMode import TaskMode

class DenseSequenceVideoProcessor(AbstractVideoProcessor):
    """具體策略 B：針對 15 秒以上的長影音。"""
    def __init__(self):
        super().__init__()
        self.vision_engine = QwenModelManager()
        self.chunk_duration = 4.0 

    def analyze_visual_semantics(self, file_path: str, duration: float) -> dict:
        action_index = []
        
        for start_time in np.arange(0, duration, self.chunk_duration):
            end_time = min(start_time + self.chunk_duration, duration)
            if end_time - start_time < 1.0:
                continue
                
            temp_chunk = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            chunk_path = temp_chunk.name
            temp_chunk.close()

            try:
                # 視覺推理：Qwen 分析動作
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(start_time), "-t", str(end_time - start_time), 
                        "-i", file_path, "-c", "copy", chunk_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                vlm_result = self.vision_engine.analyze_media(chunk_path, media_type="video", mode=TaskMode.ACTION_INDEX)
                
                # 物理重心分析：抽取該切片的中間幀計算重心
                cap = cv2.VideoCapture(file_path)
                # 定位到該切片的中央時間點
                mid_time = start_time + (end_time - start_time) / 2
                cap.set(cv2.CAP_PROP_POS_MSEC, mid_time * 1000)
                ret, frame = cap.read()
                cap.release()
                
                chunk_focus = {"x_percent": 50.0, "y_percent": 50.0}
                if ret:
                    pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    chunk_focus = self._calculate_saliency_focus(pil_image)

                action_index.append({
                    "start_time": round(start_time, 2),
                    "end_time": round(end_time, 2),
                    "action_description": vlm_result.get("caption", "Unknown action"),
                    "subject_focus": chunk_focus # 為長影片提供分段重心 [cite: 28]
                })
            finally:
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)

        return {
            "is_dense_indexed": True,
            "action_index": action_index,
            "technical_score": None, 
            "aesthetic_score": None
        }