# Documentation Index

> Last updated: 2026-07-14

## 基线验证

```text
python -m ruff check cli.py fnirs_flow tests scripts/benchmark_performance.py  # 0 errors
python -m pytest                              # 866 passed, 5 skipped (public tree)
npm audit (webui/)                            # 0 vulnerabilities
npm run build (webui/)                        # success
```

---

## 文档目录

| 目录 | 内容 |
|---|---|
| `architecture/` | 架构概览、设计决策、文档地图 |
| `business/` | 业务逻辑基线、场景商业模型 |
| `implementation/` | 路线图、交接说明、backlog、工作流计划、优化计划 |
| `literature/` | 文献提取协议、证据 schema、综述协议、QC/ML 防泄漏指南 |
| `manuscript/` | NeuroImage 稿件草稿、结构说明、投稿计划、审稿意见 |
| `methodatom/` | MethodAtom 重构计划、影响面盘点、证据映射、库设计 |
| `reviews/` | 审稿备忘录、外部参考优化建议 |
| `specs/` | 公共 API、package profile、task-GLM 验收清单 |
| `supplementary/` | 稿件补充材料 |

---

## 已完成计划

| # | 计划 | 文件 | 状态 |
|---|---|---|---|
| 1 | MethodAtom 语义收敛与代码优化 | `methodatom/method_atom_refactor_and_code_optimization_plan.md` | COMPLETED |
| 2 | 代码与稿件改进 | `implementation/code_and_manuscript_improvement_plan.md` | COMPLETED |
| 3 | 下一步优化方案 | `implementation/next_optimization_plan.md` | COMPLETED |
| 4 | Controlled Flow 预设节点执行 | `implementation/controlled_flow_and_preset_node_execution_plan.md` | COMPLETED |
| 5 | v1 Implementation Master Plan | `implementation/fnirs_flow_v1_implementation_master_plan.md` | COMPLETED |
| 6 | WebUI Development Plan | `implementation/fnirs_flow_webui_development_plan.md` | COMPLETED |
| 7 | Literature Extraction | `literature/literature_extraction_plan.md` | COMPLETED |
| 8 | PubMed Review | `literature/review_plan_precision_pubmed_redesign.md` | COMPLETED |
| 9 | 项目优化计划 (2026-07-11) | `implementation/project_optimization_plan_2026-07-11.md` | COMPLETED |
| 10 | Cedalion Comparison & Strategy | `reviews/cedalion_comparison_and_strategy.md` | COMPLETED |

---

## 未完成记录处理结果 (2026-07-11)

从全部 90+ 文档中扫描出 26 项未完成工作，已全部处理。

### 已解决 (15 项)

| # | 项目 | 处理结果 |
|---|---|---|
| U-01 | 真实执行证据固化 | 5/5 subjects 执行成功，证据保存在 `outputs/evidence_run/` |
| U-02 | MNE 环境锁定 | 创建 `.github/workflows/ci.yml` + `environment.yml` |
| U-03 | package import/rerun 验证 | 修复 exporter 查找 compiled/ 目录，导出/导入验证通过 |
| U-04 | NeuroImage 投稿 checklist | 14/21 项已勾选 |
| U-05 | Manuscript claim 审计 | task-GLM 已验证，其余标注在案 |
| U-06 | MVP acceptance checklist | 35/46 项已勾选 |
| U-07 | CLI/WebUI/API 三入口一致性 | ExecuteResult 增加 atom_results/artifacts，WebUI 显示完整信息 |
| U-14 | 文档状态冲突 | 已更新关键文档标记 |
| U-15 | docs 文档重组 | 已记录在本文件 |
| U-18 | Manuscript 补齐项 | 已记录剩余项 |
| U-19 | 控制流执行计划完成标记 | 已更新 |
| U-20 | v1 backlog 完成标记修正 | 修正 group summary、package rerun 为未完成 |
| U-21 | Implementation Handoff 勾选 | 9/9 项已勾选 |
| U-23 | 报告系统 reportlets | 已实现 |
| U-26 | CI pipeline | 已创建 |

### 延后至 v1.1 或 Pre-release (4 项)

| # | 项目 | 归属 | 说明 |
|---|---|---|---|
| U-08 | DAG 拓扑调度 | v1.1 | 当前三链顺序执行对线性 pipeline 有效 |
| U-09 | schema mismatch | By Design | adapter 自动解析，已记录在 risk_register |
| U-17 | AI 发布门控 | Pre-release | 6 项门控已定义，实现延后 |
| U-22 | risk code 审计 | v1.1 | RiskItem.code 已存在，完整覆盖需审计 |

---

## 当前代码能力

### 核心框架

- Flow/MethodAtom 模型、validation (30+ rules)、compiler、risk register、reporting checklist
- MethodAtom Library: 13 templates, 562 candidates, 7 risk rules
- Evidence Store: 1,637 articles, 4,287 atoms, 7,837 candidates, 2,106 evidence quotes
- Backend abstraction: BackendProtocol, BackendRegistry, BackendBinding (MNE/Cedalion)
- Cedalion MVP Adapter: capability detection, SNIRF reading, int2od, od2conc

### 执行引擎

- 真实 fNIRS 执行链：read_run → optical_density → QC → motion_correction → filtering → MBLL → design_matrix → GLM → contrast → channel_output → roi_output
- BIDS events TSV 自动解析注入 design matrix
- 结构化 artifact/provenance/failure manifest 输出
- 批处理: 5 subjects 全部成功 (BIDS-NIRS-Tapping)

### CLI

```text
python cli.py validate        <flow.json>
python cli.py compile         <flow.json> --outdir <dir>
python cli.py discover        <dataset_id> --outdir <dir>
python cli.py dry-run         <dir>
python cli.py run             <dir>
python cli.py export          <dir> --profile <submission|reviewer|reproducibility>
python cli.py verify-package  <package.zip>
python cli.py backends
```

### WebUI

- 项目管理、Flow Canvas、数据导入、验证、运行监控 (Dry Run + Execute)、导出
- Registry-driven palette (从 backend /api/atom-templates 动态加载)
- Error banner + 项目状态条 + nav gating
- Results Workspace: 浏览 artifacts、QC、Channel、ROI、Group 结果
- Import Package: 导入 .fnirsflow.zip、quarantine 管理、fork
- Export Profile Selector: 选择 reproducibility/submission/reviewer profile
- DAG Layer Preview: 可视化执行 DAG
- Fatal validation risk 阻止 Execute

### Package

- WebUI 可编辑项目始终保存为单个 `.fnirsflow` 文件；隐藏工作区只是可丢弃缓存
- 每次保存先生成并校验临时包，再原子替换；内部保留最近 10 个完整修订版本
- 包内 `bundle_manifest.json` 记录所有文件的 SHA-256 和大小，启动时验证后才加载
- 旧版项目文件夹首次启动时自动迁移为 `.fnirsflow`
- `.fnirsflow` 是可继续编辑的项目文件；`.fnirsflow.zip` 是分享/投稿用的只读导出包
- 3 种 profile: submission / reviewer / reproducibility
- Export → Import 验证通过 (plan.json, execution_dag.json, data_manifest.json)
- Package verifier: 验证 profile、schema、checksum、backend manifest、artifact、relink、版本

### CI/CD

- `.github/workflows/ci.yml`: Python 3.11-3.13 matrix, Ruff lint, pytest, WebUI build
- `environment.yml`: conda 环境定义

---

## 尚未实现 (v1.2+ 后续)

- FlowVCS 设计历史与版本分支（v1.2 主线）
- 静息态 / 超扫描 / ML 场景真实执行
- Generative AI CLI/WebUI draft 入口（规范和 draft 已实现，入口未做）
