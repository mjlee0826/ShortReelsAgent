"""
導演 agentic loop 的工具集（Command Pattern）+ 註冊表（Registry）。

每個工具一個 Command 物件（:class:`base_tool.BaseTool` 子類），由 :class:`tool_registry.ToolRegistry`
集中註冊、供 loop 取定義（給模型）與分派執行。延遲載入，避免 import 時序耦合。
"""
