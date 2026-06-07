"""
shared 套件:跨層共用、不依賴任何專案模組的中性葉節點。

目前只放共用 value object(``SubjectBbox`` / ``FaceInfo``),供 media_processor 與 model
兩層共同 import,避免 model 層反向依賴 media_processor。
"""
from shared.value_objects import FaceInfo, SubjectBbox

__all__ = ["SubjectBbox", "FaceInfo"]
