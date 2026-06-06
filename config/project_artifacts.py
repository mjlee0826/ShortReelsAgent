"""
專案資料夾產物檔名集中管理 (Configuration Object Pattern)。

每個 project 資料夾根目錄下的各階段 JSON 產物檔名(``project_meta`` 與 Phase 1~4 的狀態 / DNA /
藍圖檔)是橫跨 backend(``director_service`` 寫檔、``projects`` / ``asset_repository`` /
``project_cover_service`` 讀檔)與 ingestion_engine(雲端同步讀寫 ``project_meta``)的共同契約。
原本散落各檔:``project_meta.json`` 被 ``project_meta_store`` / ``cloud_ingestion_service`` /
``poller`` 各自硬編一份、Phase 2~4 檔名在 ``director_service`` 直接寫成裸字串。集中於此最底層
config 作為唯一事實來源:

- backend 與 ingestion_engine 受「不得互相 import」的反循環依賴約束(見 ``project_meta_store``
  與 ``cloud_ingestion_service`` 的 docstring),唯有放在最底層的 config 才能讓兩邊共用同一組
  檔名常數。
- 杜絕 magic string:新增 / 改名階段產物只需改這一處。
"""
from __future__ import annotations

# 專案中繼資料檔:雲端來源 / 同步狀態 / 逐檔策略 / 最後修改時間等折進此單一檔,不另建註冊檔。
PROJECT_META_FILENAME = "project_meta.json"

# Phase 1 全狀態落地檔(含 success / rejected / error,鍵為素材 relpath),供前端素材列表 join 狀態。
# 與下方 success-only 的 metadata 檔區分。
PHASE1_STATUS_FILENAME = "phase1_asset_status.json"

# Phase 1 success-only 完整感知結果落地檔(list,每筆含 file + metadata,metadata 內有 aesthetic_score):
# 供 Phase 4 取用,亦供專案總覽挑「美學最高素材」當封面。
PHASE1_METADATA_FILENAME = "phase1_assets_metadata.json"

# Phase 2 範本 DNA 落地檔(範本結構 / 節奏分析結果)。
PHASE2_TEMPLATE_DNA_FILENAME = "phase2_template_dna.json"

# Phase 3 音訊 DNA 落地檔(配樂節拍 / 能量分析結果)。
PHASE3_AUDIO_DNA_FILENAME = "phase3_audio_dna.json"

# Phase 4 最終剪輯藍圖落地檔(供 Remotion 算圖;其存在與否即「專案是否已生成藍圖」旗標)。
PHASE4_BLUEPRINT_FILENAME = "phase4_blueprint.json"
