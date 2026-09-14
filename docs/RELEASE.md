# 手动发布 Release

Release 工作流仅接受 `workflow_dispatch`，使用 GitHub 官方 Ubuntu 构建机。
推送分支或版本标签不会触发此 Release 工作流。日常 CI 和独立 Flatpak
工作流保持各自的触发规则；Flatpak 的标签构建不创建 GitHub Release。

## 操作步骤

1. 将工作流变更合入并推送默认分支 `master`，使 GitHub 显示手动运行入口。
2. 确认待发布代码，按仓库 Git 操作登记规则创建并推送版本标签，格式为
   `vMAJOR.MINOR.PATCH`（例如 `v3.4.0`）。标签必须已经存在；本工作流不负责创建版本标签。
3. 打开 GitHub **Actions → Release → Run workflow**，选择包含本配置的分支，
   在 `tag` 输入待发布标签。
4. `draft` 默认勾选，构建完成后生成草稿。取消勾选表示本次手动运行完成后直接公开发布。
5. 检查运行结果、附件和发布说明；草稿可在 Releases 页面审核后发布。

## 源码与产物约定

手动运行所选分支提供工作流定义，`tag` 决定待构建源码。`prepare` 校验版本格式，
将轻量或附注标签解析为 commit SHA，两个构建任务都 checkout 同一 SHA。
版本写入该构建目录的 `version.h.in`，不提交回仓库，也不修改 CLI 的独立版本常量。
发布时明确使用输入标签及解析的 SHA，避免误把手动运行分支当作发布源码。

两个构建任务都成功且附件存在后才执行发布，同一标签的发布串行运行。
只有发布任务具有 `contents: write` 权限。重复运行已有 Release 可能更新附件，
并按本次 `draft` 输入改变发布状态，因此重复运行前应核对已有版本。

当前附件仅为 Linux `.deb` 和 AppImage，保留原有打包内容；不代表完整的
Windows CLI/PDF 便携包。Windows 构建、Python 打包及其集成测试流水线仍需另行接入。
本配置的本地静态验证不能替代 GitHub 构建机上的实际编译验证。

GitHub 官方说明：
[手动运行工作流](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)。
