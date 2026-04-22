# 临时工作区清理建议

Last updated: `2026-04-22`

## 目标

这份文档只解决“当前工作区太乱”的短期问题，不做大规模重构。

原则：

- 先清理明显的发布残留和临时文件
- 不动当前已经接通的 `ukumog-engine` 主链路
- 不在这一轮直接删除可能仍有参考价值的规划文档，而是先归档或搬家
- 保留当前 Docker 内测交付所需的最新产物

## 当前主要杂乱来源

从当前工作区看，主要有四类：

1. 根目录堆放了多份旧 tar 包
2. 根目录残留了多组 `tmp_*.log`
3. `release/` 目录里同时存在 Docker 交付物和旧的 Electron 打包产物
4. 一些说明类 Markdown 还散落在仓库根目录，没有收进 `docs/`

## 建议分三批做

## 第一批：可以直接清

这批文件属于“明显的历史产物或临时文件”，清掉风险最低。

建议删除：

- `anti-gomoku-room-server.tar`
- `anti-gomoku-room-server_2026-04-20.tar`
- `anti-gomoku-room-server_2026-04-20-v2.tar`
- `anti-gomoku-room-server_2026-04-20-r2.tar`
- `hd-app_1.0.tar`
- `tmp_history_server.err.log`
- `tmp_history_server.out.log`
- `tmp_http_server.err.log`
- `tmp_http_server.out.log`
- `tmp_node_proxy.err.log`
- `tmp_node_proxy.out.log`
- `tmp_smoke_server.err.log`
- `tmp_smoke_server.out.log`
- `.tmp-docker-config/`

原因：

- 这些文件都不应该长期停留在仓库根目录
- 当前正式保留的 Docker 交付物已经在 `release/` 内
- 日志文件都是可再生成物，没有长期保存价值

## 第二批：建议搬家，不建议直接删

这批文件更适合做“归档整理”。

建议从仓库根目录迁入 `docs/notes/` 或 `docs/archive/`：

- `MODEL_SERVER_OPTIMIZATION.md`
- `TRAINING_SERVER_AGENT.md`

建议保留在 `docs/` 体系内的当前有效文档：

- `docs/DOCKER_RELEASE_RUNBOOK_LINUX_X86_64.md`
- `docs/DOCKER_SERVER_UPLOAD_CHECKLIST_LINUX_X86_64.md`
- `model-server/docs/UKUMOG_ENGINE_BACKEND_INTEGRATION_PATH.md`
- `model-server/docs/UKUMOG_ENGINE_BACKEND_TASK_LIST.md`
- `model-server/docs/ENGINE_TUNING_AND_MULTIBOARD_PLAN.md`

原因：

- 这些文档仍有参考价值，但放在根目录会干扰主开发视野
- 当前最重要的是把“发布文档”和“引擎接入文档”留下，其余辅助手册都应该下沉

## 第三批：需要先统一规则，再动

这批不建议现在直接删，而是等下一轮定结构后处理。

### `release/` 目录混放问题

当前 `release/` 里同时有：

- Docker tar 交付物
- Electron `win-unpacked`
- Windows 安装包 `.exe`
- `.blockmap`

建议下一轮改成二选一：

方案 A：

- `release/docker/`
- `release/electron/`

方案 B：

- `release/` 只保留当前要交付的一类产物
- 另一类产物转移到 `dist/` 或 `artifacts/`

短期建议：

- 如果当前主目标是服务器 Docker 交付，就把 Electron 旧产物移出 `release/`
- 至少不要让 Docker tar 和 Electron 安装包继续混在同一级

### 根目录说明文件规范

建议把根目录控制到“只保留入口文件和必要配置”：

- `README.md`
- `package.json`
- `package-lock.json`
- `Dockerfile`
- `docker-compose.yml`
- 核心运行源码

其余说明文档统一收进 `docs/`

## 当前不建议动的内容

这批现在已经和新链路对齐，不建议为了“看起来干净”而误删。

- `engine/`
- `scripts/`
- `model-server/src/serving/`
- `ukumog-engine/`
- `docs/DOCKER_RELEASE_RUNBOOK_LINUX_X86_64.md`
- `docs/DOCKER_SERVER_UPLOAD_CHECKLIST_LINUX_X86_64.md`
- `release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar`
- `release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256`
- `release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.manifest.json`
- `release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.runbook.md`
- `release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.checklist.md`

## 推荐的临时清理顺序

1. 先删根目录旧 tar 和 `tmp_*.log`
2. 清掉 `.tmp-docker-config/`
3. 把根目录辅助 Markdown 搬进 `docs/notes/` 或 `docs/archive/`
4. 单独整理 `release/`，把 Docker 与 Electron 产物拆开

## 可选后续改进

如果下一轮要顺手收一版结构，我建议再补两个小规则：

- 扩充 `.dockerignore`，把所有 `tmp_*.log` 一并排除
- 给 `docs/` 建最小层级，例如 `docs/release/`、`docs/engine/`、`docs/archive/`

## 一句话结论

这轮最值得先清的是“根目录旧 tar + tmp 日志 + `.tmp-docker-config/`”；最值得随后整理的是“根目录散落文档”和“`release/` 中 Docker/Electron 产物混放”。
