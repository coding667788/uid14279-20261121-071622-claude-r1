# 离线盲巡检调度（Offline Blind Patrol Scheduling）

纯 Python 3.12 标准库实现的场地安保巡检证据分派求解器。支持两种工作模式：

- **单情景模式**：没有缺席情景，求解覆盖全部必须检查窗口的最优计划。
- **盲/多情景模式**：给出主计划（无人缺席）和在指定揭晓时隙确认的各缺席应急计划，
  保证揭晓前的移动、访问和见证归属在所有未揭晓分支上完全一致。

只依赖标准库，CPU 运行，无需安装第三方包。

---

## 1. 目录结构

```
solution/
  __main__.py     命令行入口（python -m solution ...）
  errors.py       可定位的错误码与异常类型
  model.py        输入解析、结构校验、Case 数据模型
  geometry.py     精确步数最短路（min-plus DP）与轨迹重建
  tree.py         情景树（共享段 / 分支段）构建与冻结-缺席冲突检测
  solver.py       精确树状 CSP 求解器（带完整剪枝的分支定界）
  orchestrate.py  可行/不可行编排、最小不可满足窗口集、输出组装
  checker.py      独立复核器（不调用求解器，重新实现全部约束）
  brute.py        独立穷举预言机（仅用于 4 人 5 时隙小案交叉验证）
  db.py           SQLite 持久化
examples/
  build_fixtures.py   生成全部本地虚构夹具
  fixture_factory.py  夹具定义（含全部陷阱场景）
  *.json              生成的夹具
tests/
  test_brute_crosscheck.py  穷举交叉验证
  test_traps.py             单情景约束陷阱
  test_scenarios.py         多情景盲揭晓
  test_validation_cli.py    结构校验、CLI、SQLite
```

---

## 2. 复现命令

```bash
# 1) 生成全部夹具（本地虚构数据）
python examples/build_fixtures.py

# 2) 求解（单情景）
python -m solution schedule examples/large_case.json

# 3) 求解（多情景盲揭晓）
python -m solution schedule examples/scenario_base.json

# 4) 独立复核一个完整计划
python -m solution check examples/tiny_case.json PLAN.json

# 5) 带 SQLite 持久化的求解与复核
python -m solution schedule examples/tiny_case.json --db store.sqlite
python -m solution check   examples/tiny_case.json --db store.sqlite
python -m solution list --db store.sqlite

# 6) 运行全部断言测试
python -m unittest discover -s tests -v
```

标准输出为 UTF-8 JSON。同一逻辑输入（忽略 JSON 键顺序）恒产生同一结果。

---

## 3. 输入定义

顶层 JSON 对象：

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 可选，案例标识 |
| `slot_count` | int ≥ 1 | 有序时隙总数 T，时隙编号 1..T |
| `inspectors` | array | 巡检员列表 |
| `checkpoints` | array | 检查点列表 |
| `edges` | array | 可达转移（移动成本非负） |
| `windows` | array | 必须被两名异班组人员见证的窗口 |
| `frozen_visits` | array | 可选，冻结的既有到访 |
| `scenarios` | array | 可选；出现即进入多情景模式，另有隐式无人缺席情景 `s0` |

**inspectors[]**

| 字段 | 说明 |
|---|---|
| `id` | 唯一字符串 |
| `team` | 班组标识；同班组两人不能为同一窗口互证 |
| `trainings` | 已完成训练字符串数组 |
| `initial` | 时隙 0 所在节点（可以是检查点之外的起点节点） |

**checkpoints[]**：`id`、`required_trainings`（到访者必须具备其全部训练）。

**edges[]**：`src`、`dst`、`cost`（int ≥ 0）。除显式边外，每个节点都有一条
隐式零成本自环，表示空闲并保留原位置。

**windows[]**

| 字段 | 说明 |
|---|---|
| `id` | 唯一窗口 ID |
| `checkpoint` | 目标检查点 |
| `start_slot` / `end_slot` | 连续窗口区间，满足 1 ≤ start ≤ end ≤ T |
| `min_gap` | 两次独立到访的最小时隙间隔（≥1） |

**frozen_visits[]**：`inspector`、`slot`、`checkpoint`，可选 `window`（提示归属）。
冻结到访必须保留、不计新访问；其见证归属允许重新分配。

**scenarios[]**（多情景）：`id`（保留 id `s0` 不可用）、`reveal_slot` ∈ [1, T+1]、
`absent`（从揭晓时隙起缺席的巡检员数组）。情景之间互斥。

### 约束语义

1. 只有具备检查点全部要求训练的人可到访该点。
2. 每人每时隙最多占一个点；连续时隙的移动必须在可达矩阵内存在对应步数的走法。
3. 空闲 = 零成本自环，保留原位置。
4. 每个窗口需要两名**不同班组**的人，在窗口区间内先后独立到访，时隙间隔 ≥ `min_gap`；
   同一时隙不能形成有先后的独立证据。
5. 同一检查点可同时分配给多人；但一名巡检员对同一检查点最多为一个窗口见证，
   一次访问也只能供给一个窗口。多窗口可以重叠。
6. 冻结到访永不可更改；若某缺席情景在揭晓后与冻结到访直接冲突，报告 `input_conflict`。

---

## 4. 输出定义

### 4.1 可行（`status="feasible"`）

单情景：

```json
{
  "status": "feasible",
  "case_id": "...",
  "mode": "single",
  "objective": {"new_visits": 3, "movement_cost": 7},
  "plan": {
    "scenario_id": "s0",
    "new_visits": 3,
    "movement_cost": 7,
    "evidence": [
      {"slot": 1, "inspector": "i2", "checkpoint": "P", "window": "w1"}
    ],
    "tracks": [
      {"inspector": "i1", "positions": ["H", "P", "Q", "Q", "Q"]}
    ]
  }
}
```

`tracks.positions[t]` 是该巡检员在时隙 t+1 所在节点，长度恰为 T，每一步都通过
单步可达性（含空闲自环）校验。

多情景：

```json
{
  "status": "feasible",
  "mode": "scenario",
  "objective": {"max_new_visits": 4, "sum_movement_cost": 10},
  "main_plan": { "...": "无人缺席情景 s0 的完整计划" },
  "contingencies": [
    {
      "scenario_id": "eA",
      "reveal_slot": 3,
      "absent": ["a2"],
      "new_visits": 4,
      "movement_cost": 6,
      "trigger_prefix": {"slots": [1, 2], "evidence": [ ... ]},
      "suffix": {"slots": [3, 5], "evidence": [ ... ], "tracks": [ ... ]}
    }
  ],
  "shared_prefix_groups": [
    {"reveal_slot": 3, "scenario_ids": ["eA", "eB"]}
  ]
}
```

- `main_plan` 是实际发布的主计划（无人缺席）。
- 每个 `contingencies[i]` 是在 `reveal_slot` 才能确认的应急分支；
  `trigger_prefix` 是揭晓前必须与主计划一致的部分，`suffix` 是揭晓后允许的重调度。
- 揭晓前的访问不允许事后改填到另一个窗口证据。

### 4.2 不可行（`status="infeasible"`）

```json
{
  "status": "infeasible",
  "minimum_unsatisfiable_windows": ["w3"],
  "feasible_witnesses": {
    "w3": {"evidence": [ ... ], "tracks": [ ... ]}
  }
}
```

`minimum_unsatisfiable_windows` 是**最小基数**的不可满足窗口集合，并列时按升序窗口 ID
决胜。对集合中每个窗口，给出删去该窗口后、在固定冻结到访与人员约束下的可行见证。

### 4.3 输入冲突（`status="input_conflict"`）

缺席情景与冻结到访直接冲突时返回，`errors[]` 给出 `E_FROZEN_ABSENT_CONFLICT` 及字段位置。

### 4.4 结构错误

任何结构/语义输入错误返回非零退出码与：

```json
{"status": "error", "error_code": "INPUT_STRUCTURE_ERROR",
 "errors": [{"code": "E_UNKNOWN_REF", "location": "$.windows[0].checkpoint",
             "message": "unknown checkpoint 'GHOST'"}]}
```

错误码包括 `E_REQUIRED`、`E_FIELD_TYPE`、`E_DUPLICATE_ID`、`E_UNKNOWN_REF`、
`E_VALUE_RANGE`、`E_INCONSISTENT`、`E_FROZEN_ABSENT_CONFLICT`、`E_PLAN_STRUCTURE`、
`E_PLAN_VIOLATION` 等，均带 `location` 字段路径。

---

## 5. 优化目标

- 单情景，按字典序最小化：
  1. 新到访次数（冻结到访不计）；
  2. 移动成本总和；
  3. 按时隙和人排序的 `(时隙, 人, 点, 窗口)` 证据序列。
- 多情景，按字典序最小化：
  1. 各情景新访问次数的**最大值**；
  2. 各情景移动成本之**和**；
  3. 按情景 ID 排序的计划列表。

---

## 6. 算法与剪枝完整性

### 6.1 精确步数可达性（geometry.py）

空闲建模为每个节点上的隐式零成本自环。用 min-plus DP 预算
`dist[d][a][b]`——从 a 到 b **恰好 d 次转移**的最小成本，O(1) 查询。
这正是“局部可达但连续转场不可能”能被发现的原因：边 S→P 和 P→R 各自存在，
但若窗口要求的航点之间没有对应精确步数的走法，`dist[d]` 为无穷大。
轨迹重建对每个航点段独立做前向 DP 并回溯前驱，保证输出的每个节点序列都合法。

### 6.2 情景树（tree.py）

把时间轴按各揭晓时隙切成树节点：共享节点被所有尚未揭晓的叶（情景）共用，
分支节点只属于一个已揭晓情景。由于节点内的决策只做一次，两个同样未揭晓的情景
在这些时隙上的决定天然一致，无需额外约束。共享节点上的候选到访按“在该时隙是否
已在某经过该节点的叶中缺席”逐时隙过滤。

### 6.3 为什么剪枝是完整的（solver.py）

搜索是对见证分配的深度优先分支定界，**所有剪枝都只使用下界或硬约束，不丢弃最优解**：

1. **MRV 只改变量顺序，从不删除候选值**。最小剩余域变量先赋值，纯排序优化。
2. **候选被拒仅当已违反硬约束**：时隙占用、同巡检员/检查点复用（在整条约会叶路径上
   跟踪）、训练资格、缺席、冻结航点、班组差异、最小间隔、精确步数可达性。
3. **分支定界只用单调下界**：已创建的新访问不可撤销，航点成本是剩余自由度下的精确
   最小成本；只有当某偏序目标的下界已严格差于当前最优 incumbent 时才剪枝，
   因此被剪掉的子树不可能含更优解。
4. **新访问前瞻下界**：对每个未覆盖窗口计算任何覆盖对至少要新增的访问数并按叶汇总，
   忽略未来窗口间的共享只会少算，故始终是合法下界；空域立即失败传播。
5. **两阶段字典序优化**：阶段一在从根下界起递增的新访问上限下做可行性搜索，找到最小
   可达上限；阶段二固定该上限做单次成本分支定界并以规范证据序列决胜。两阶段在各自
   上限下都穷尽枚举，组合结果即精确字典序最优。
6. **记忆化/支配**以约束相关占用（覆盖集、占用访问、巡检员-检查点复用）为签名；
   航点由占用访问加不可变冻结航点唯一确定，故签名等价的状态保留成本最低者不影响正确性。

因为不存在任何启发式截断，搜索枚举了全部可行分配，最小不可满足窗口集也按
（基数, 升序 ID 元组）顺序枚举，首个可覆盖的删除集即规定答案。

### 6.4 独立穷举交叉验证（brute.py）

`brute.py` 与求解器**不共享任何搜索代码**：它直接在 (巡检员, 时隙) 网格上枚举每个窗口
的见证对，拒绝违反硬规则的配对，再用精确步数表校验航点走法，穷举取最优。
其规模有硬性护栏（`BRUTE_LIMITS`），仅用于 4 人 5 时隙小案。
`tests/test_brute_crosscheck.py` 在多个小案变体（含不可行案、删窗、去冻结）上断言
生产求解器与穷举预言机的 `(新访问数, 移动成本, 证据序列)` 完全一致。

### 6.5 独立复核（checker.py）

`check` 不读取求解器内部状态，而是从零重新核验：轨迹长度与逐边可达、空闲自环、
冻结到访不可变、训练资格、缺席、窗口区间、班组差异、最小间隔、同时隙禁止独立证据、
一人一点一窗口、一次访问单一归属、全覆盖，以及多情景下的共享前缀一致性和
“揭晓前访问不得事后改填”。并重算目标值与声明值比对。

---

## 7. 夹具与覆盖的测试场景

| 夹具 | 覆盖点 |
|---|---|
| `tiny_case` / `tiny_infeasible_case` | 4 人 5 时隙，穷举交叉验证 |
| `large_case` | 10 人 / 12 时隙 / 12 窗口的小而非玩具规模 |
| `chain_trap_case` | 局部可达但精确步数连续转场不可能 |
| `frozen_contention_case` | 一个既有到访被两个窗口争用 |
| `same_team_trap_case` | 同组两人不能互证 |
| `equal_cost_tie_case` | 等成本下规范序列决胜与确定性 |
| `idle_position_case` | 空闲保留原位置、零成本 |
| `scenario_base` | 基础盲揭晓、共享前缀、无人缺席情景 |
| `scenario_no_common_prefix` | 各分支单独可排、共同存活集无跨组对 |
| `scenario_long_route` | 较远主路线使替补能完成连续转场 |
| `scenario_same_reveal` | 同一时刻揭晓的不同分支 |
| `scenario_frozen_conflict` | 缺席与冻结到访的输入冲突 |

测试还包含：篡改证据/重填揭晓前窗口被 `check` 拒绝、JSON 键顺序无关的确定性、
SQLite 存取、可定位错误码。
