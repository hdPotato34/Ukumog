# 模型端目录规划（训练与推理）

Last updated: 2026-04-15

## 目标

在当前仓库内预留一个可独立演进的模型端工作区，用于：

- 训练数据处理
- 模型训练与评估
- 模型导出与注册
- 推理服务代码

该目录先做结构与规范，不与线上对局服务强耦合。

---

## 目录结构

```text
model-server/
  src/
  configs/
  scripts/
  data/
    raw/
    processed/
    features/
  artifacts/
    checkpoints/
    eval/
    exports/
    runs/
  registry/
  docs/
```

---

## 各目录放什么

### src/

放模型端源码（建议按模块继续拆分）：

- data_pipeline（清洗与编码）
- training（训练主循环）
- selfplay（自博弈）
- evaluation（对战评测与战术题）
- serving（推理接口）

### configs/

放所有可复现配置：

- 训练配置（模型结构、超参、batch、lr）
- 自博弈配置（MCTS sims、温度、噪声）
- 评测配置（对手、局数、门禁阈值）
- 推理配置（超时、回退策略）

### scripts/

放运维和流水线脚本：

- 数据同步脚本（从线上拉取 finished games）
- 启动训练脚本
- 批量评测脚本
- 导出和注册脚本

### data/raw/

放从线上同步来的原始对局数据。

要求：

- 只追加，不覆盖
- 保留同步批次信息
- 原则上只读

### data/processed/

放训练样本（由 raw 生成）：

- 状态编码
- policy/value 标签
- train/val 划分后的数据分片

### data/features/

放可复用特征缓存：

- 局面哈希
- 预计算合法手 mask
- 其它中间特征

### artifacts/checkpoints/

放训练过程中的权重文件：

- 按 run_id 和 step 管理
- 禁止覆盖历史 checkpoint

### artifacts/eval/

放评测输出：

- 对战胜率报告
- 战术题报告
- 推理时延/超时统计

### artifacts/exports/

放可部署模型导出物：

- onnx 或 torchscript
- 对应 inference_config
- 版本说明

### artifacts/runs/

放实验运行日志：

- 控制台日志
- loss 曲线
- 关键指标快照

### registry/

放模型注册表：

- 当前生产模型
- 候选模型
- 回滚模型
- 门禁阈值

### docs/

放模型端内部文档：

- 训练流程说明
- 上线与回滚手册
- 故障排查清单

---

## 命名与版本建议

- run_id: ag_train_YYYYMMDD_HHMM_<shortgit>
- model_version: ag-az-YYYYMMDD-rN
- dataset_version: ds-YYYYMMDD-batchN

---

## 入库与不入库建议

建议入库：

- src/
- configs/
- scripts/
- docs/
- registry/（可只入模板）

建议不入库（或只保留占位文件）：

- data/raw/
- data/processed/
- data/features/
- artifacts/checkpoints/
- artifacts/runs/

可按后续需要补充 model-server/.gitignore。

---

## 下一步

1. 在 src/ 下初始化最小训练骨架（data -> train -> eval -> export）。
2. 在 scripts/ 下补齐一键训练与一键评测脚本。
3. 将 model_registry 与训练配置模板迁入 model-server 目录并统一引用路径。
