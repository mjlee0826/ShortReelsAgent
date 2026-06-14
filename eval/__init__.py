"""ShortReels 評測 Dataset 建置工具。

本套件把「讀 spec → 抓素材 → 半自動策展 → 生 prompt → 打包凍結」拆成數個可單獨重跑的
pipeline 階段，所有程式碼自成一體（standalone），不依賴專案其他目錄。詳見 ``eval/docs.md``
與 ``eval/README.md``。
"""

# 套件版本（與 dataset_version 無關，純標示工具本身版本）
__version__ = "0.1.0"
