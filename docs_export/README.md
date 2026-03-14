# docs_export

此目录原用于存放导出的 `docx/pdf` 交付件。

为保证代码仓库可正常创建 Pull Request（避免二进制 diff/预览限制），仓库仅保留可审阅的 Markdown 源文档：

- `docs/PRD.md`
- `docs/Product_Design.md`
- `docs/API_Spec.md`
- `docs/Protocol_Spec.md`
- `docs/Deployment_Guide.md`
- `docs/User_Manual.md`
- `docs/Test_Plan.md`
- `docs/Security_Compliance.md`

如需生成 `docx/pdf`，请在本地执行导出流程（见 `scripts_render_docs.py`），生成物不纳入 Git 版本管理。
