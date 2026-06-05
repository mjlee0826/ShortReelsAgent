"""
StageNode:依賴圖節點 —— 一個 Stage 加上它依賴的上游 Stage 名稱 (DAG Node)。

設計語意
--------
以「群組間 barrier」表達編排會過度約束:某些 Stage 其實只依賴前面的**其中一個** Stage
(例:Complex 影片的 ``SemanticVideo`` 只需要 ``Timecode`` 的產物,卻被迫等同群的
``AudioInference`` / ``FaceDetect``)。

改用真正的依賴圖:每個 ``StageNode`` 宣告自己依賴哪些上游 Stage,
由 :class:`~media_processor.pipeline.pipeline.Pipeline` 依「依賴全部完成才可執行」的拓樸順序排程,
讓彼此無依賴的 Stage 真正並行、不互相 block。

``deps`` 用「名稱字串」(``StageMeta.name``)而非 Stage 物件參照:Builder 以
``stage.meta.name`` 宣告即可,可讀、可在建構期驗證(名稱不存在 / 成環即 fail fast),
且與進度事件 / 日誌的 Stage 標示一致。
"""
from __future__ import annotations

from dataclasses import dataclass

from media_processor.pipeline.stage import Stage


@dataclass(frozen=True)
class StageNode:
    """
    依賴圖中的一個節點:待執行的 ``Stage`` + 它依賴的上游 Stage 名稱。

    ``deps`` 為空 tuple 表示無前置依賴(可立即執行,例如 Decode)。frozen 確保節點定義不可變、
    可安全在多個 asset 的 Pipeline 執行間共享(實際可變狀態都集中在 ``AssetContext``)。
    """

    stage: Stage
    # 依賴的上游 Stage 名稱(StageMeta.name);全部完成後本節點才可被排程執行
    deps: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """本節點 Stage 的名稱,供 Pipeline 排程與依賴解析使用。"""
        return self.stage.meta.name
