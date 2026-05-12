class BaseModelManager:
    """
    Singleton Base (Template Method Pattern):
    提供統一的單例建構流程，各 ModelManager 只需繼承並實作 _initialize()。
    若初始化失敗，_instance 不會被鎖定在損壞狀態，下次呼叫仍可重試。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            try:
                cls._instance._initialize()
            except Exception:
                cls._instance = None
                raise
        return cls._instance

    def _initialize(self):
        raise NotImplementedError(f"{self.__class__.__name__} 必須實作 _initialize()")
