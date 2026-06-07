"""
model.infra 套件:GPU 資源管理與併發控制的基礎設施層(與具體模型無關)。

包含 Singleton/鎖階層基底(``base_model_manager``)、L2 GPU 容量閘門(``gpu_gate``)、
啟動容量規劃(``gpu_capacity_manager``)、Object Pool(``model_pool``)、
等待時間量測(``resource_wait_clock``)。

公開介面集中由上層 ``model/__init__`` 對外曝露(``BaseModelManager`` / ``ModelPool``);
此處不做 eager re-export,呼叫端一律以子模組路徑 import,維持各基礎設施的延遲載入特性。
"""
