import os
import json
import uuid
import shutil
from backend.services.RemotionAdapter import RemotionAdapter

class RenderWorkspace:
    """
    Resource Management: 負責管理算圖任務的暫存生命週期。
    提供建立與無情銷毀機制，防止伺服器硬碟塞爆。
    """
    def __init__(self, base_dir: str):
        self.task_id = str(uuid.uuid4())
        self.workspace_dir = os.path.join(base_dir, f"render_{self.task_id}")
        self.props_path = os.path.join(self.workspace_dir, "props.json")
        self.output_path = os.path.join(self.workspace_dir, "output.mp4")

    def setup(self):
        os.makedirs(self.workspace_dir, exist_ok=True)
        return self

    def cleanup(self):
        """資源回收 (Garbage Collection)：將整個暫存資料夾刪除"""
        if os.path.exists(self.workspace_dir):
            shutil.rmtree(self.workspace_dir)
            print(f"🧹 [Workspace] 暫存資源已清除: {self.task_id}")

class RenderService:
    """
    Service Pattern: 統籌 SSR 算圖的商業邏輯流程。
    """
    def __init__(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.workspace_base = os.path.join(self.project_root, "temp_workspaces")
        self.adapter = RemotionAdapter()

    def create_workspace(self) -> RenderWorkspace:
        return RenderWorkspace(self.workspace_base).setup()

    def execute_render(self, workspace: RenderWorkspace, blueprint: dict, assets_root_url: str) -> str:
        # 1. 準備施工圖紙 (寫入 props.json)
        props_data = {
            "blueprint": blueprint,
            "assetsRootUrl": assets_root_url
        }
        with open(workspace.props_path, 'w', encoding='utf-8') as f:
            json.dump(props_data, f, ensure_ascii=False)

        # 2. 呼叫 Adapter 啟動 Node.js 算圖
        # 畫布 ID 指定為 "MainVideo" (需與前端註冊名稱一致)
        self.adapter.render_video(
            composition_id="MainVideo",
            props_path=workspace.props_path,
            output_path=workspace.output_path
        )

        return workspace.output_path