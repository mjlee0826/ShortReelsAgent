"""
GPU 偵測工具:ExecutorRegistry 與 ModelPoolRegistry 的單一 GPU 來源 (DRY)。

把「有幾張 GPU」這個唯一事實集中在一處,避免兩個 Registry 各寫一份偵測邏輯而走偏。
偵測結果自動反映 ``CUDA_VISIBLE_DEVICES``(torch 啟動時即套用),故單卡 / 多卡 / 共用 GPU
三種環境皆自適應,Worker 數不寫死。
"""
from __future__ import annotations


def detect_gpu_ids() -> list[int]:
    """
    偵測可用的 CUDA device id 列表(例如 ``[0, 1]``)。

    自動吃 ``CUDA_VISIBLE_DEVICES``;torch 未安裝或無 CUDA 時回傳空列表,
    由呼叫端決定 CPU 後備策略(避免在此處硬塞 device 0 造成誤解)。
    """
    try:
        import torch
        if torch.cuda.is_available():
            return list(range(torch.cuda.device_count()))
    except ImportError:
        # 無 torch(理論上不會發生於本專案)→ 視為無 GPU
        pass
    return []


def detect_gpu_count() -> int:
    """回傳偵測到的 GPU 數量;無 GPU 時為 0。"""
    return len(detect_gpu_ids())
