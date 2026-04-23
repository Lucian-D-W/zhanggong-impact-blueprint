# Mainstone

本文件根据本轮对话整理，记录 ZG Impact Blueprint 从 Stage1 到 Stage18 的核心里程碑。每个阶段只保留目标、关键交付与状态摘要。

更新时间：2026-04-20（Asia/Singapore）

## Stage 1

交付最小可复用工作流：`AGENTS.md`、repo-local skill、3 个核心脚本、SQLite schema、Python minimal fixture、README。跑通 `build -> report -> edit -> update -> test`，证明流程闭环，但只验证了 Python 首条示范链路。

## Stage 2

在不改坏 Stage1 的前提下加入 generic fallback、最小 TS/JS adapter、统一入口 `cig.py` 与 README 更新。Generic 支持 file-level 主流程，TS/JS 跑通最小 end-to-end，skill 开始具备复制到不同项目复用的基础形态。

## Stage 3

把“改前/改后体检器”推进为轻量过程记录器。新增 `task_runs`、`edit_rounds`、`file_diffs`、`symbol_diffs`，`after-edit` 自动写本轮变更摘要；补 `init`/`doctor` 与 parser backend/doc source 薄接口，增强接手与排障能力。

## Stage 4

把 TS/JS family 提升为第一等公民，引入 profile 概念和真实 V8 coverage 链路，支持 `js/ts/jsx/tsx`、React 组件、hook、基础类方法与更稳的测试识别。保住 Python/generic，不拆新 adapter 体系。

## Stage 5

从单 adapter 走向 `primary + supplemental`。保留 TS/JS 为主干，新增真实可用的 `sql_postgres` supplemental adapter，让 SQL routine、tests、rules、app->SQL hints 能进入同一份图谱与报告，实现混合仓库可用。

## Stage 6

进入“可分发、可恢复、agent-friendly”阶段。新增 `export-skill`、`status`、结构化 logs 与 errors、handoff、`TROUBLESHOOTING` 协议，区分开发仓库与 consumer 包，让 skill 可以被复制、初始化、排障和交接。

## Stage 7

正式支持“只复制单个 skill 文件夹”安装路径，并新增 `setup / analyze / finish` 三个高层命令。自动生成 `AGENTS.md`、config、schema、consumer 文档，自动复用最近 `task/seed`，上手路径收敛为 `setup -> analyze -> finish`。

## Stage 8

朝 daily-driver 打磨。加入智能 seed ranking、`brief/default/full` 报告模式、增量刷新与 stale 检测，强化 TS/JS + React + SQL 的日常价值；报告更短，JSON 更稳定，handoff/status 更适合长期开着用。

## Stage 9

引入自动 context inference 与 build trust policy。`analyze` 可从 patch、git diff、最近任务自动推断 `changed file/line/seed`，并输出 `context-resolution`、`build-decision`、`seed-candidates`、`next-action`。新增更真实的 benchmark 样本，提升日常仓库可信度。

## Stage 10

做规范化与信任修复：skill 目录调整为 `scripts/assets/references`，`SKILL.md` 改成命令式触发规范；修复 Python 类方法盲区、TS/JS brace 边界问题、stale graph 信任、recent task 偏置、`tests passed != safe`、无 git 空报告等漏洞，形成更可信的日常工具。

## Stage 11

时间：2026-04-18 至 2026-04-19

完成 Stage 11：先补 13 条回归测试，再做实现。新增 dependency fingerprint 与 trust 降级，修复 TS/JS 类型大括号、regex、multiline arrow、自调用污染，修正 `tests_run` 真实计数，补 frontmatter 严格解析、Python 实例方法解析、`health`/恢复命令与 build lock；Stage1-11 共 38 个测试通过。

## Stage 11 重要节点

- 2026-04-18：先新增 `tests/test_stage11_workflow.py`，锁定依赖变化降 trust、旧 manifest fingerprint unknown、parser 边界、frontmatter 重复 key、测试计数、恢复命令与实例方法解析等关键失败场景，确保先有红灯再改实现。
- 2026-04-18：完成核心实现，修改 `incremental_refresh.py`、`trust_policy.py`、`build_graph.py`、`parser_backends.py`、`after_edit_update.py`、`generate_report.py`、`runtime_support.py`、`cig.py`，并同步更新 `SKILL.md` 与 3 份模板文档。
- 2026-04-19：排查并修复 Stage4 的 `runCommand` 回归，补上 multiline arrow 回归测试；重新执行 `python -m unittest discover -s tests -p "test_stage*.py"`，最终 38/38 通过，确认 Stage11 没有破坏 Stage1-10。

## Stage 12

时间：2026-04-19

围绕外部 review 做“可信热修”。补上 delete-only diff 自动上下文、恢复命令 workspace/quoting、`parse_test_count` 的 `error/errors` 双计数，以及 `--full-rebuild` 把依赖 `unknown/changed` 误抬成 high trust 的漏洞；同时收紧 self-hosting 配置，避免维护仓库自身时 guard 失焦。

## Stage 12 重要节点

- 2026-04-19：通过临时仓库独立复现实例，先把 delete-only context inference 与 forced full rebuild trust override 锁成失败测试，再最小修改 `context_inference.py`、`build_graph.py` 与 `tests/test_stage11_workflow.py`，确保修复前红灯、修复后转绿。
- 2026-04-19：补了 self-hosting 相关整理，repo-local config 明确指向仓库根目录，`demo_phase1.py` 改为临时 demo config，`parser_backends.py` 避免嵌套 `dist` 副本混入源码集合，减轻“开发模板仓库却总分析 example” 的偏移。
- 2026-04-19：把 review bundle 当成独立交付物收口，补齐 `benchmark/` 与说明文档，明确“带 tests 就必须带全 fixture”的规则，并把打包约定写入 `AGENTS.md`，避免 reviewer 再遇到测试在、样本缺失的假失败。

## Stage 13

时间：2026-04-19

把“能分析”推进到“能给出下一步执行建议”。新增 `--test-scope targeted|configured|full`、`recommend-tests` 可执行测试命令、`.ai/codegraph/next-action.json`、多维 trust 结构，以及更高效的目录剪枝；报告与 machine output 开始区分请求测试范围、实际测试范围和不同来源的置信。

## Stage 13 重要节点

- 2026-04-19：补齐 `test scope` 分层与可执行测试推荐，`finish/after-edit` 能表达 targeted、configured、full 三种语义；direct test seed 可落成 unittest 或保守的文件级命令，减少“知道该测什么但不会跑”的最后一公里缺口。
- 2026-04-19：新增 `next-action` 机器输出与多维 trust，单独暴露 graph、parser、dependency、test_signal、coverage、context、overall 等维度，让 agent 不必只看一个 `graph_trust` 做过度简化判断。
- 2026-04-19：根据 Stage13 review 再做后续硬化，修复 `include_files` 被排除目录吞掉、显式空 `exclude_dirs` 不生效、点前缀路径归一化、失败/跳过测试仍给乐观 next-action、缺少 `coverage.py` 时回落到普通测试但诚实标记 `coverage_unavailable`。

## Stage 14

时间：2026-04-19

把“影响分析 + 测试分层”推进到“自适应验证编排”。新增 verification budget `B0-B4`、`--shadow-full` 校准、`test-history/calibration`、`install-integration-pack`、runtime contract graph 初版，以及统一的多维 trust 输出，让 agent 能按风险自动决定验证强度，而不是只在 targeted 与 full 之间硬切。

## Stage 14 重要节点

- 2026-04-19：落地 verification budget、shadow-full、history ranker 与 calibration ledger。系统开始根据 direct tests、dependency 状态、blast radius、miss history 自动把验证预算抬到 `B2/B3/B4`，核心价值从“告诉你影响了谁”扩展为“告诉你现在该怎么验”。
- 2026-04-19：加入 runtime integration pack 与 contract graph 初版。仓库内可生成 `AGENTS.md` 受管块、`.ai/codegraph/runtime/*` 会话契约文档，并开始识别 `env/config/ipc/sql/obsidian/playwright` 这些更接近真实产品链路的 contract，而不再只盯函数级关系。
- 2026-04-19：完成 Stage14 回归矩阵并补 helper 收尾。`test_stage14_workflow`、兼容测试与全量 workflow 回归通过；同时补了 `matches_any()` 点前缀路径最小回归与最小修复，避免 helper 层路径写法差异在后续新调用点里埋雷。

## Stage 15

时间：2026-04-19

把“所有文件一视同仁地走同一条主流程”和“同一个 bug 修不好却一直只补局部”这两个问题推进到可治理状态。新增 flow scope governance 与 repair loop escalation，让文档、规则、测试、配置、源码不再被同样对待，也让重复失败会逐步揭露更大的影响链。

## Stage 15 重要节点

- 2026-04-19：新增 change flow classifier。系统现在能把改动分成 `bypass`、`lightweight`、`guarded`、`risk_sensitive`、`mixed`，并据此决定 `skip / health_only / analyze_only / full_guardian`、`B0-B4` 与 `none / targeted / configured / full` 的验证建议。
- 2026-04-19：修掉 Stage14 的一个边界问题。纯文档 bypass 改动不会再被后续 `no_direct_tests` 逻辑误抬到 `B3`；普通归档/总结 markdown 能稳定停在 `B0`，不需要完整主流程，也不需要测试。
- 2026-04-19：新增 repair loop runtime。加入 `.ai/codegraph/repair-attempts.jsonl`、`.ai/codegraph/loop-breaker-report.json`、`loop-status`、`diagnose-loop` 与 `--escalation-level L0|L1|L2|L3|auto`，让 repeated failure 会从 `L0 -> L1 -> L2 -> L3` 逐步展开 chain，而不是继续只补同一块文件。
- 2026-04-19：把 loop escalation 接进 `next-action.json`。当失败重复出现时，next-action 会带上 `repair_loop`、`expanded_chain_summary`、升级后的 budget、以及“先读扩展链条，不要继续局部修补”的 agent instruction。
- 2026-04-19：新增 Stage15 测试矩阵并通过回归。`tests/test_stage15_workflow.py` 覆盖 docs bypass、rule docs guarded、README/AGENTS lightweight、mixed heaviest、risk-sensitive dependency、repair attempt 记录、`L0-L3` 升级与 loop breaker report；Stage15 单测、Stage13/14 回归、以及 Stage9/10/11/13/14/15 广义组合都保持通过。
- 2026-04-19：做了一轮独立暴力黑盒验证。在不改源码的前提下，用临时工作区和 subagent 并行验证 `classify-change`、`analyze`、`loop-status`、`diagnose-loop`、组合回归与重复失败升级；结果显示 bypass 不污染 loop，repeat_count 到 4 时会稳定进入 `L3/B4/full`，而 Stage9/10/11/13/14/15 组合回归连续两次都是 67/67 通过。

## 文档治理节点

时间：2026-04-19

对仓库文档做了一次结构化收口：更新 `README.md` 与阶段说明文档以反映当时能力；新增 `docs/README.md` 与 `docs/archive/README.md`；把 `background.md`、初始实现 prompt、历史 review 记录归档到 `docs/archive/`，让当前运行文档、兼容 review 文档和历史过程文档分层更清楚。

## 规则治理节点

时间：2026-04-19

补了一条删除安全规则到仓库级与全局级 agent 约定：删除动作默认只能移入回收站或 trash，不得直接永久删除；任何永久删除都必须先获得用户明确且严格的审批。这条规则已写入仓库 `AGENTS.md`、consumer 生成模板，以及全局 Codex `AGENTS.md`。

## Stage 15.1

时间：2026-04-19

把“流程轻重”和“危险动作保护”从同一套判断里拆开。Stage 15.1 的目标不是推翻 Stage 15，而是把 working note / 活跃工作记录这类文档放回轻流程，同时把 move/archive/delete/permanent delete 的风险单独治理，避免再出现“因为关键词误升重才碰巧挡住误操作”的假保护。

## Stage 15.1 重要节点

- 2026-04-19：给 change classifier 增加 `doc_roles`。系统现在除了看路径和扩展名，也会看文档角色；`working_note`、`guide_doc`、`archive_note`、`rule_doc` 会影响 flow 判断。`mainstone.md` 已通过 repo-local config 明确声明为 `working_note + protected_doc`。
- 2026-04-19：working note 不再因为写了 `verification budget`、`finish --test-scope` 这类关键词就自动被抬成 guarded。对于活跃工作记录，系统现在优先理解“这是工作记录”，而不是只看命令词。
- 2026-04-19：新增 `assess-mutation` CLI，用来单独判断 `edit / move / archive / delete / permanent_delete` 的动作风险。现在系统会把“这次改动要不要走完整主流程”与“这个动作会不会伤到用户文件”分开处理。
- 2026-04-19：把删除保护落成默认机制。普通删除默认只能 `recycle_only`，永久删除会落到 `never_delete_without_approval`，需要用户明确且严格审批；受保护工作文档在 move/archive 时也会要求先确认。
- 2026-04-19：新增 `tests/test_stage15_1_workflow.py`，覆盖 declared working note、heuristic working note、rule doc override、move/archive/delete/permanent delete 的 mutation guard 行为。Stage15.1 单测通过，同时 Stage15 与 Stage13/14/15/15.1 组合回归通过，确保没有把原 Stage 15 行为打坏。

## Stage 18

时间：2026-04-20

把产品身份从旧内部名迁移到统一的新主身份。Stage 18 的目标不是再扩 atlas 能力，而是把 skill、状态目录、导出包、公开文案和测试断言全部收成单一身份 `zhanggong-impact-blueprint`，避免“外面一个名字、里面另一个名字”的割裂。

## Stage 18 重要节点

- 2026-04-20：统一机器层标识为 `zhanggong-impact-blueprint`。skill 主目录迁移到 `.agents/skills/zhanggong-impact-blueprint/`，repo-local state 目录迁移到 `.zhanggong-impact-blueprint/`，consumer export 与 single-folder export 默认也全部切到新 slug。
- 2026-04-20：新增 `scripts/identity.py`，把 `SKILL_SLUG`、`DISPLAY_NAME`、`FORMAL_NAME`、`STATE_DIRNAME` 等身份常量集中管理；`cig.py`、`consumer_install.py`、`change_classifier.py` 等入口不再各自散落一套旧名字。
- 2026-04-20：更新 `README.md`、`AGENTS.md`、`.agents/skills/zhanggong-impact-blueprint/SKILL.md`、consumer templates、demo 文档与活跃测试面，让用户可见表面统一为 `张工的施工图 / ZhangGong Impact Blueprint` 与 `ZG Impact Blueprint`。
- 2026-04-20：把 Stage 17 过程文档和历史 Stage 13 review 文档统一归档到 `docs/archive/`；外部上传规则也进一步收紧为默认不上传整个 `docs/` 目录。
- 2026-04-20：新增 `tests/test_stage18_workflow.py`，覆盖 frontmatter/identity 常量、新 skill/state 路径、consumer export、single-folder export、active repo surface 无旧身份残留等迁移约束，保证以后不会把旧名偷偷带回来。
- 2026-04-20：完成分层回归与流程收尾。`tests.test_stage18_workflow`、`tests.test_stage17_workflow`、`tests.test_stage16_workflow`、`tests.test_stage15_workflow`、`tests.test_stage15_1_workflow`、`tests.test_stage14_workflow`、`tests.test_stage13_workflow` 关键回归通过；严格 `ResourceWarning` 模式通过；`release-check --skill-only` 通过；最后 `finish --test-scope configured` 与 `health` 都重新回到可工作状态。

## 当前状态

截至 2026-04-20，ZG Impact Blueprint 已推进到 Stage18，具备 repo-local、可复制、可分发、可恢复、支持 Python / TSJS / React / SQL / generic fallback 的完整主流程，并已经形成 verification budget、shadow calibration、contract graph、flow scope governance、repair loop escalation、doc-role-aware working-note handling、mutation safety、Stage 17 的最终 atlas 收口，以及 Stage 18 的单一身份迁移与发布面统一。产品边界也更明确：它首先是给 agents 用的工程图册与验证护栏，而不是平台型重智能系统。
