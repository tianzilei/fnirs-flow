# fnirs-flow

GUI-enabled fNIRS analysis toolbox + reproducibility framework。用 Flow 编排预处理、验证、执行和复现，基于 MNE-NIRS 执行后端。

**v1.1.1** | 866 tests passing, 5 skipped | Python 3.10+

---

## 快速开始

### 安装

```bash
# 基础安装（仅核心模型和验证）
pip install -e .

# 完整安装（含 MNE-NIRS 执行、API、ML）
pip install -e ".[full]"

# 含 Cedalion 26.5.1 后端（需要 Python 3.11+ 和 Git）
pip install -e ".[full,cedalion]"

# 或用 conda
conda env create -f environment.yml
```

### 后端懒加载

fnirs-flow 采用**懒加载（lazy loading）**架构，后端按需加载：

| 场景 | 行为 |
|------|------|
| 导入库/浏览 MethodAtom | **不加载**任何后端（MNE/Cedalion） |
| 编译 Flow | **不加载**后端，仅读取元数据 |
| 执行 MNE MethodAtom | 按需加载 MNE-NIRS |
| 执行 Cedalion MethodAtom | 按需加载 Cedalion |
| Cedalion 未安装 | 返回结构化错误，**不回退**到 MNE，**不自动安装** |

**性能基准**：
- 启动时间（导入核心模块）：< 0.5s
- `describe()` / `is_available()` 调用：< 0.1ms（100 次 < 4ms）
- 内存开销：仅导入后端时增加

**检查后端状态**：
```bash
python cli.py backends
```

### 三步上手

```bash
# 1. 验证一个 flow 配置
python cli.py validate configs/demo_task_glm_real.json

# 2. 编译为可执行计划
python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo

# 3. 执行分析（需要 MNE-NIRS）
python cli.py run outputs/demo --outdir outputs/demo
```

### 启动 WebUI

```bash
# 方式一：生产模式（推荐）
python cli.py webui
# 首次运行会自动构建前端，之后直接从 FastAPI 提供静态文件
# 访问 http://127.0.0.1:8000

# 方式二：开发模式（前端热更新）
python cli.py webui --dev
# 同时启动 Vite 开发服务器 + 后端
# 前端: http://localhost:3000
# 后端: http://127.0.0.1:8000

# 方式三：分别启动前后端
python -m uvicorn fnirs_flow.api.app:app --reload   # 后端 :8000
cd webui && npm install && npm run dev               # 前端 :5173
```

**CLI 参数**:
- `--port PORT`：指定端口（默认 8000）
- `--host HOST`：指定绑定地址（默认 127.0.0.1）
- `--dev`：开发模式，启用前端热更新

---

## CLI 参考

| 命令 | 用途 | 示例 |
|---|---|---|
| `validate` | 验证 flow JSON 是否合法 | `python cli.py validate configs/demo_task_glm_real.json` |
| `compile` | 编译 flow → plan/dag/manifests | `python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo` |
| `discover` | 发现并注册公开数据集 | `python cli.py discover bids-nirs-tapping --outdir outputs/demo` |
| `dry-run` | 枚举所有 subject/session/run，不执行 | `python cli.py dry-run outputs/demo --outdir outputs/demo` |
| `run` | 真实执行分析（MNE-NIRS） | `python cli.py run outputs/demo --outdir outputs/demo` |
| `export` | 导出 reproducibility package | `python cli.py export outputs/demo --outdir outputs/demo` |
| `rerun` | 重新执行已导入的 package | `python cli.py rerun outputs/imported_package` |
| `import-homer3` | 导入 Homer3 配置 → fnirs-flow atoms | `python cli.py import-homer3 pipeline.cfg --outdir outputs/imported` |
| `import-analyzir` | 导入 AnalyzIR R 脚本 → fnirs-flow atoms | `python cli.py import-analyzir pipeline.R --outdir outputs/imported` |
| `export-homer3` | 导出 atoms → Homer3 配置 | `python cli.py export-homer3 atoms.json --outdir outputs/homer3` |
| `export-analyzir` | 导出 atoms → AnalyzIR R 脚本 | `python cli.py export-analyzir atoms.json --outdir outputs/analyzir` |
| `webui` | 启动 WebUI 服务器 | `python cli.py webui` 或 `python cli.py webui --dev` |
| `backends` | 显示后端状态和能力 | `python cli.py backends` |
| `verify-package` | 验证 .fnirsflow.zip 包完整性 | `python cli.py verify-package package.fnirsflow.zip` |

`run` 命令支持筛选：
```bash
python cli.py run outputs/demo --outdir outputs/demo \
  --participant-label sub-01 sub-02 \
  --session-label ses-01 \
  --run-label run-01
```

`export` 支持三种 profile：
```bash
python cli.py export outputs/demo --outdir outputs/demo --profile reproducibility_package
python cli.py export outputs/demo --outdir outputs/demo --profile submission_package
python cli.py export outputs/demo --outdir outputs/demo --profile reviewer_package
```

---

## 生成式 AI 接入

根目录的 `ai_flow_generation_guide.md` 是给 AI 系统的 prompt 上下文规范。把这份文档作为 model context 喂给 AI，它就能生成候选 `flow.json` 分析方案。

- AI 只输出候选 FlowGraph JSON，不生成可执行代码
- 定义了输入字段（研究目标、数据格式、条件、对比等）和输出 schema
- 包含 10 条硬性规则：不绕过验证、不编造文献、不包含 PHI/私有路径等
- 生成的 flow 仍需通过 `validate_flow()` 才能执行

**用法**：将本文档内容作为 system prompt 或 context 提供给 AI，附上你的研究描述，AI 输出 `flow.json`。

示例 AI draft：`configs/ai_draft_task_glm.json`（task GLM 分析方案，含 `ai_generation` 元数据和 `requires_user_confirmation` 待确认项）。

配套文档：
- 实施计划：`docs/implementation/generative_ai_prerelease_support_plan.md`
- Generative AI 声明：`docs/GENERATIVE_AI_DECLARATION.md`

---

## 项目结构索引

### 核心代码 — `fnirs_flow/`

| 子包 | 文件 | 用途 |
|---|---|---|
| **flow/** | `atoms.py` `models.py` `schemas.py` `snapshots.py` `migration.py` `migrations/` | Flow 核心数据模型：`FlowAtom`、`AtomPort`、`FlowEdge`、`FlowGraph`、`ExecutionPlan`、`AIGenerationMetadata`；schema 定义与版本迁移 |
| **compiler/** | `compiler.py` `execution_dag.py` `manifests.py` `hashing.py` | FlowGraph → `plan.json` + `execution_dag.json` + 各类 manifest 编译 |
| **execution/** | `engine.py` `service.py` `batch.py` `operations.py` `batch_adapter.py` `provenance.py` `artifacts.py` `failures.py` | 执行引擎：dry-run 枚举、MNE-NIRS 真实执行、批处理、provenance/artifact/failure 追踪 |
| **adapters/** | `mne_nirs_adapter.py` `mne_nirs_steps.py` `mne_nirs_io.py` `qc_metrics.py` `roi_mapping.py` `homer3_export.py` `homer3_import.py` `analyzir_export.py` `analyzir_import.py` `cedalion_adapter.py` `cedalion_steps.py` `cedalion_capabilities.py` `cedalion_io.py` | MNE-NIRS 完整链路 adapter；Cedalion 可选后端 adapter（26 个方法）；QC 指标；ROI 映射；Homer3/AnalyzIR 双向导入导出 |
| **validation/** | `api.py` `graph.py` `adapters.py` `models.py` `state.py` `error_codes.py` | 图验证、adapter 兼容性、状态验证、结构化 error codes |
| **registry/** | `atom_templates.py` `node_templates.py` `node_library.py` `scenarios.py` `evidence_store.py` `evidence_config.py` `risk_rules.py` `presets.py` `methods.py` `combat_diagnostics.py` | MethodAtom 模板库（113 个模板）、场景路由器、Evidence Store、风险规则、预设配置 |
| **security/** | `models.py` `validation.py` | 执行信任分级、capability manifest、import quarantine、readiness check |
| **exporters/** | `package_exporter.py` `package_importer.py` `outputs.py` `reports.py` `methods_report.py` `inclusion_audit.py` `reproducibility.py` `reportlets.py` | Reproducibility package 导出/导入、报告生成、纳入性审计 |
| **api/** | `app.py` `models.py` `projects.py` `__init__.py` | FastAPI 后端：项目 CRUD、验证/编译/发现/执行/导出 REST API、SSE 进度推送 |
| **data/** | `discovery.py` `manifest.py` `registry.py` | 公开数据集发现、data manifest、数据注册 |

### 前端 — `webui/`

React + Vite，通过 `src/api/client.ts` 调用后端 API。

| 路径 | 用途 |
|---|---|
| `src/components/AppShell.tsx` | 应用外壳：导航栏、工具栏、状态条 |
| `src/components/FlowCanvas.tsx` | Flow 画布主组件（React Flow） |
| `src/components/Sidebar.tsx` | 侧边栏：MethodAtom 库、配置面板 |
| `src/components/ParameterPanel.tsx` | 参数编辑面板 |
| `src/components/ValidationPanel.tsx` | 验证结果展示 |
| `src/components/DagLayerPreview.tsx` | DAG 层级预览 |
| `src/pages/ProjectWorkspace.tsx` | 项目工作区 |
| `src/pages/FlowBuilder.tsx` | Flow 构建器 |
| `src/pages/AtomLibrary.tsx` | MethodAtom 库浏览 |
| `src/pages/DataWorkspace.tsx` | 数据工作区 |
| `src/pages/ValidationDashboard.tsx` | 验证仪表板 |
| `src/pages/CompileSummary.tsx` | 编译摘要 |
| `src/pages/RunMonitor.tsx` | 执行监控（SSE 实时进度） |
| `src/pages/ResultsWorkspace.tsx` | 结果浏览（artifacts/QC/channel/ROI/group） |
| `src/pages/ExportPackage.tsx` | 导出 package（含 profile 选择） |
| `src/pages/ImportPackage.tsx` | 导入 package（含 quarantine 管理） |
| `src/pages/SystemDiagnostics.tsx` | 系统诊断 |

### 测试 — `tests/`

54 个测试模块，858 个测试，覆盖核心链路：

| 测试文件 | 覆盖范围 |
|---|---|
| `test_flow_models.py` `test_flow_atom_models.py` | Flow 数据模型 |
| `test_graph_validation.py` `test_adapter_validation.py` `test_validation_api.py` | 图验证、adapter 兼容性 |
| `test_compiler.py` `test_compile_gate.py` | Flow 编译 |
| `test_mne_adapter.py` `test_sprint_c_adapter.py` | MNE-NIRS adapter |
| `test_homer3_bidirectional.py` | Homer3 双向导入/导出 |
| `test_analyzir_bidirectional.py` | AnalyzIR 双向导入/导出 |
| `test_cross_backend_integration.py` | Homer3↔AnalyzIR 跨 backend 全链路集成 |
| `test_cli_adapters.py` | adapter CLI 命令端到端 |
| `test_batch_runner.py` `test_execution_service.py` `test_sprint_b_execution.py` | 批处理、执行引擎 |
| `test_api.py` `test_api_export.py` | REST API、导出 |
| `test_dataset_discovery.py` | 数据集发现 |
| `test_security_models.py` `test_security_validation.py` | 安全模型、quarantine |
| `test_state_validation.py` | 状态验证 |
| `test_golden_outputs.py` `test_enhanced_reports.py` `test_reports_package.py` | 输出产物、报告 |
| `test_project_persistence.py` `test_snapshots.py` | 项目持久化、快照 |
| `test_schema_migration.py` `test_migration_roundtrip.py` `test_migration_roundtrip_v2.py` | Schema 迁移 |
| `test_sprint_e_interop.py` `test_sprint_e_interop.py` | 互操作性 |
| `test_dryrun_report.py` `test_qc_roi_outputs.py` | Dry-run 报告、QC/ROI |
| `test_node_library.py` `test_atom_library.py` `test_registry.py` | 模板库、注册表 |
| `test_scenarios.py` | 场景路由 |
| `test_cli.py` | CLI 命令 |
| `test_smoke.py` | 冒烟测试 |

运行测试：
```bash
pytest                    # 全部
pytest tests/test_api.py  # 单个模块
pytest -k "mne"           # 按关键词
```

### 配置 — `configs/`

| 文件 | 用途 |
|---|---|
| `demo_task_glm_real.json` | 主 demo：任务态 GLM 完整 flow（推荐入门） |
| `ai_draft_task_glm.json` | AI 生成的 task GLM 候选 flow（含 ai_generation 元数据） |
| `demo_resting_state_flow.json` | 静息态 flow 示例 |
| `demo_ml_validation_flow.json` | 机器学习验证 flow 示例 |
| `demo_task_flow.json` | 基础任务态 flow |
| `demo_task_flow_v0_2_method_atoms.json` | MethodAtom 版任务态 flow |
| `evidence_backed_presets.json` | 基于文献证据的预设参数 |
| `example_task_study.json` | 简单任务态研究配置 |

### Schema — `schemas/`

| 文件 | 定义 |
|---|---|
| `fnirs_flow.schema.json` | Flow JSON 主 schema |
| `capability_manifest.schema.json` | 原子能力声明 schema |
| `risk_item.schema.json` | 风险项 schema |
| `action_attempt.schema.json` | 执行尝试记录 schema |
| `project_snapshot.schema.json` | 项目快照 schema |
| `readiness_result.schema.json` | 就绪检查结果 schema |
| `literature_flow_evidence.schema.json` | 文献→Flow 证据映射 schema |

### 文献数据与工具 — `outputs/`

| 子目录 | 内容 |
|---|---|
| `literature_extraction/` | 文献提取 CSV 主数据（studies, acquisition, preprocessing_methods, analysis_methods, risk_register 等） |
| `methodatom_library/` | 从文献生成的 MethodAtom 模板库（method_atoms, templates, adapter_definitions, risk_rule_candidates 等） |
| `skills/` | 可移植 skill 包（fnirs-literature-extractor.zip 等） |
| `local_tapping_analysis/` | 本地 BIDS-NIRS tapping 分析结果 |
| `acceptance/` | 验收测试编译产物 |
| `PDF2MD0708/` `PDF2MD0709/` | PDF 转 Markdown 的文献全文 |
| `organized/` | 整理后的文献元数据 |
| `precision_pubmed_searches/` | 精确 PubMed 检索结果 |

### 脚本 — `scripts/`

| 文件 | 用途 |
|---|---|
| `run_local_analysis.py` | 本地 BIDS-NIRS tapping 数据集完整分析 |
| `analysis_tapping.py` | tapping 分析兼容入口（调用 run_local_analysis） |
| `demo_full_pipeline.py` | 全流程 demo 脚本 |
| `run_task_glm_demo.py` | 任务态 GLM demo |
| `generate_flow_evidence.py` | 从文献生成 Flow 证据 |
| `generate_evidence_map.py` | 生成文献证据映射 |
| `batch_extract.py` `batch_flow_evidence.py` | 批量文献提取 |
| `deep_extract_core.py` | 深度核心文献提取 |
| `sync_public_release.py` | 公开版本同步 |
| `pubmed_precision_search.py` | PubMed 精确检索 |
| `validate_first80_extraction.py` `validate_first160_extraction.py` | 提取结果验证 |
| `audit_code_reconstruction_readiness.py` | 代码重建就绪审计 |
| `init_core_manual_screening_table.py` | 初始化人工筛选表 |
| `build_tier1_precision_candidates.py` | 构建 Tier1 精确候选集 |
| `extract_*.py` `inspect_*.py` | 各批次文献提取与检查 |
| `upgrade_schema_*.py` | Schema 升级脚本 |
| `auto_screen_core_records.py` | 自动筛选核心记录 |

### 文档 — `docs/`

| 子目录/文件 | 核心文件 | 用途 |
|---|---|---|
| **根** | `GENERATIVE_AI_DECLARATION.md` `README.md` | Generative AI 声明、文档索引 |
| **architecture/** | `architecture.md` `fnirs_flow_product_architecture.md` `fnirs_flow_design_decisions_v0_{2..7}.md`（6 个版本） `CURRENT_DOCUMENTATION_MAP.md` `reference_reuse_matrix.md` | 产品架构、设计决策演进（v0.2→v0.7）、文档地图、参考代码复用矩阵 |
| **implementation/** | `IMPLEMENTATION_HANDOFF.md` `FNIRS_FLOW_IMPLEMENTATION_ROADMAP.md` `fnirs_flow_v1_implementation_master_plan.md` `fnirs_flow_v1_backlog.md` `V1_WORKFLOW.md` | 实施交接、路线图、总方案、backlog、工作流 |
| | `fnirs_flow_webui_development_plan.md` `generative_ai_prerelease_support_plan.md` `public_dataset_demo_selection.md` | WebUI 开发计划、AI 支持计划、数据集选择 |
| | `current_issues_and_future_directions.md` `current_progress_and_next_plan.md` `next_optimization_plan.md` `project_optimization_plan_2026-07-11.md` | 当前问题、进度、优化计划 |
| | `execution_closure_detailed_plan.md` `controlled_flow_and_preset_node_execution_plan.md` `code_and_manuscript_improvement_plan.md` | 执行闭环、受控 flow、代码与论文改进 |
| **business/** | `fnirs_flow_business_logic_v0_1.md` `scenario_business_model.md` | 业务逻辑、场景模型 |
| **literature/** | `literature_extraction_plan.md` `literature_extraction_tables.md` `agent_extraction_protocol.md` | 文献提取方案、字段表、agent 协议 |
| | `literature_flow_evidence_schema.md` `code_reconstruction_evidence_guide.md` | 证据 schema、代码重建证据指南 |
| | `qc_threshold_recommendations.md` `ml_leakage_prevention_checklist.md` | QC 阈值建议、ML 防泄漏清单 |
| | `review_plan_precision_pubmed_redesign.md` `review_protocol_pubmed_precision_only.md` | 文献检索 review 方案 |
| | `pubmed_functional_near-infrared_spectroscopyTitleAbstract.csv` | PubMed 检索结果（1600+ 条） |
| | `code_reconstruction_readiness_summary.md` `extraction_status_report.md` `literature_structure_summary.md` | 提取状态报告 |
| **manuscript/** | `neuroimage_manuscript_methodatom_first.md` `neuroimage_manuscript_structure_methodatom_first.md` `neuroimage_manuscript_blueprint.md` | NeuroImage 论文稿件 |
| | `neuroimage_manuscript_review_suggestions.md` `neuroimage_submission_execution_plan.md` | 审稿意见、投稿执行计划 |
| | `guide_for_authors_neuroimage.md` | NeuroImage 作者指南 |
| | `evidence_map_tables/` | 论文证据映射表（CSV/JSON） |
| **methodatom/** | `method_atom_refactor_and_code_optimization_plan.md` `method_atom_refactor_inventory.md` | MethodAtom 重构计划与影响面盘点 |
| | `method_atom_library_design_recommendations.md` `method_atom_terminology_checklist.md` `evidence_to_atom_mapping.md` | 模板库设计、术语检查、证据→原子映射 |
| **specs/** | `fnirs_flow_public_api.md` `package_profile_spec.md` `generative_ai_analysis_script_builder.md` `mvp_task_glm_acceptance_checklist.md` | 公共 API、package profile、AI 分析脚本规范、验收清单 |
| **supplementary/** | `S1` – `S8` | 论文补充材料：检索策略、CSV schema、MethodAtom seed、风险规则、报告要求、demo flow、执行 DAG、reproducibility package |
| **reviews/** | `reference_repo_optimization_directions.md` `business_logic_review_recommendations.md` | 参考仓库优化方向、业务逻辑 review 建议 |

### 其他目录

| 目录 | 用途 |
|---|---|
| `legacy/fnirs_pipeline/` | 冻结的 v0 脚手架代码，不再添加新功能 |
| `References/` | 参考仓库源码（Langflow、LangChain、MNE-Python、Homer3、NIRS-KIT、SPM 等） |
| `Sample/` | BIDS-NIRS 示例数据集（BIDS-NIRS-Tapping、ds007738） |
| `schemas/` | JSON Schema 文件（见上方索引） |

### 根目录文件

| 文件 | 用途 |
|---|---|
| `cli.py` | CLI 入口点（`fnirs-flow` 命令） |
| `pyproject.toml` | Python 项目配置（依赖、ruff、mypy、pytest） |
| `environment.yml` | Conda 环境定义 |
| `ai_flow_generation_guide.md` | 生成式 AI flow 生成规范（prompt 上下文） |
| `CHANGELOG.md` | 版本变更记录 |
| `README.md` | 本文件 |

---

## 执行链路

```text
flow.json
  → validate（图验证 + adapter 兼容性 + 后端能力检查）
  → compile（plan.json + execution_dag.json + manifests + backend bindings）
  → discover（数据集发现 + data_manifest.json）
  → dry-run（枚举 subject/session/run）
  → run（MNE-NIRS 或 Cedalion 执行）
      read_run → optical_density → QC → motion_correction → filtering
      → MBLL → design_matrix → GLM → contrast → channel_output → roi_output
  → export（reproducibility package）
```

**后端选择**：
- **MNE-NIRS**（默认）：通道空间处理、GLM、连接分析
- **Cedalion**（可选）：DOT、头模型、信号分解、合成数据、ML 工具、摄影测量

**混合后端 Flow**：支持在同一个 Flow 中混合使用 MNE 和 Cedalion MethodAtom，系统会按 MethodAtom 级别自动切换后端，每个后端实例在运行期间复用。

---

## 核心概念

| 术语 | 含义 |
|---|---|
| `MethodAtom` | 最小可组合方法单元（文献/方法学粒度）。当前库包含 113 个模板 |
| `MethodAtomTemplate` | 可复用的 MethodAtom 蓝图 |
| `FlowAtom` | Flow 中的 MethodAtom 实例 |
| `AtomPort` | MethodAtom 的输入/输出端口 |
| `FlowGraph` | 由 FlowAtom + edge 组成的分析流程图 |
| `ExecutionPlan` | FlowGraph 编译后的可执行计划 |
| `Evidence Store` | 文献提取证据的结构化存储 |
| `Scenario` | 研究场景路由器（task/resting_state/real_world/hyperscanning/machine_learning） |
| `Adapter` | 连接前后 MethodAtom 的输入输出转换器 |
| `Cedalion Adapter` | Cedalion 可选后端 adapter，支持 DOT、信号分解、合成数据等独有功能 |
| `Reproducibility Package` | 可传递、可复现的分析包（不含原始数据） |

---

## 文献提取数据

从 1600+ 篇 fNIRS 文献中提取的结构化证据，存储在 `outputs/literature_extraction/`：

| 数据表 | 内容 |
|---|---|
| `studies.csv` | 研究基本信息 |
| `acquisition.csv` | 采集参数（设备、波长、采样率、源探距等） |
| `preprocessing_methods.csv` | 预处理方法（滤波、运动校正、MBLL 等） |
| `analysis_methods.csv` | 分析方法（GLM、连接、ML 等） |
| `risk_register.csv` | 风险项登记 |
| `samples.csv` | 被试信息 |
| `reporting_requirements.csv` | 报告要求 |
| `flow_slot_contracts.csv` | Flow 端口契约 |
| `method_atoms.csv` | 方法原子定义 |
| `parameter_candidates.csv` | 参数候选值 |

---

## 参考规范

- [NIRS-BIDS specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/near-infrared-spectroscopy.html)
- [BIDS Extended to fNIRS (Nature 2024)](https://www.nature.com/articles/s41597-024-04136-9)
- [fNIRS data standards (fNIRS.org)](https://fnirs.org/resources/data-analysis/standards/)
- [Best practices for fNIRS publications](https://www.spiedigitallibrary.org/journals/neurophotonics/volume-8/issue-01/012101/Best-practices-for-fNIRS-publications/10.1117/1.NPh.8.1.012101.full)
- [TDDR motion correction](https://pmc.ncbi.nlm.nih.gov/articles/PMC6230489/)
- [Short-channel regression](https://pmc.ncbi.nlm.nih.gov/articles/PMC7523733/)
- [Demographic reporting in fNIRS](https://pmc.ncbi.nlm.nih.gov/articles/PMC10203458/)
- [fNIRS reproducibility (Nature 2025)](https://www.nature.com/articles/s42003-025-08412-1)
- [MNE-NIRS preprocessing examples](https://mne.tools/stable/auto_examples/preprocessing/fnirs_artifact_removal.html)
