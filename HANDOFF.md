# Luo 落文 v0.4 Handoff (print-kai pivot)

## v0.4.10 W04 follow-up: endpoint cleanup + P6 left/right queue (2026-05)

这轮按 TsangerJinKai02-W04 做主参考继续收口，但只学习开阔、干净端点、短钩和层级气质，不复制轮廓。W05 只作为黑度上限检查：当前 W05 已贴近 0.60，后续不应继续按 W05 追黑。

### 调整内容

- **`luo_horiz_cap_flatten`**：替代已关闭的长横末端顿笔签名，只清理长横右端 cap 微台阶，不制造新顿挫。当前目标队列是 `正晋章书世西二南`，本轮命中 19 个 cap。
- **`luo_diag_endpoint_clean`**：轻收长撇/捺尾部厚块，目标队列是 `从入人八为`。处理底部端点的横向厚块和下探感，但不把 body 尺寸拉细到掉笔。
- **`HOMEPAGE_P6_LEFT_RIGHT_GLYPHS` + `luo_homepage_p6_left_right`**：新增首页/starter 可见左右结构队列，处理 `抽独种技虾便雅柯携稚供堵朗难建邑仲快看腹距展更鹿鱼具皋值律其身`。共享 refiner 只做左旁降灰、中宫开白、右下尾轻收，不扩到 GB2312。
- **截图粗糙修补队列**：`失` 加入 `luo_diag_endpoint_clean`；`风气成` 走 `luo_curve_tail_polish`，只清右下曲尾 fishhook / chunky 感；`荒` 用 `_refine_problem_huang` 补中部 亡 组件连续性；`自` 用 `_refine_problem_self` 做单字 frame-grid 清理。
- 保持 `BOLDEN_H/V`、`STRAIGHTEN_H_BLEND`、底座字体和 `月` 冻结逻辑不动。

### 度量验收

- starter 覆盖仍为 `1128/1128`，`missing=0`。
- `scripts/check_frozen_glyphs.py`：`[frozen] ok: 月`。
- Tsanger W04：raw `0.577` / centered `0.570`，保持在 0.56-0.60 目标带内。
- Tsanger W05：raw `0.600` / centered `0.602`，作为上限信号，不再继续追 W05 黑度。
- 全站 vs LXGW：overall `0.8278 → 0.8274`，generic `0.8335 → 0.8331`，没有回升。
- `raw >= 0.87` 风险字：`52 → 40`；其中 generic 高风险 `39 → 30`。

### 视觉验证

- Roughness 单字：`local/ref/renders/v0410_rough_正.png`、`v0410_rough_晋.png`、`v0410_rough_书.png`、`v0410_rough_从.png`、`v0410_rough_魏.png`
- 截图缺陷单字：`失风气荒自成`，看 LXGW / Tsanger W04 / Luo v0.4.9 / current 四列对照。
- 综合精修样张：`local/ref/renders/v048_refinement_sheet.png`

后续仍应优先消化 starter / homepage 的可见普通字，不进入 `gb2312-level1` 扩字。剩余风险从“generic 高 IoU”拆成两类：左右结构仍像 LXGW 骨架，以及端点局部粗糙；不要再用全局黑度或 W05 方向解决。

## v0.4.10 Phase 1A follow-up + 1B + 1C: layer/diag extension (2026-05)

v0.4.10 把 v0.4.9 Phase 1A 留下的 `用` edge case 修复，并按计划扩展 IDENTITY_CORE_V2 的 layer / diag 白名单到 13 个新字符。沿用 v0.4.9 的 surgical 风格：**只动字符列表，不动 magnitude，不引入新 pass**。BOLDEN/HOOK/WEB_PRESENCE/DOT/TURN/STRAIGHTEN 全部不动。

### 调整内容

- **Phase 1A 续修（A）**：`HOMEPAGE_P0_GRID_GLYPHS` 加 `用`。v0.4.9 单独的 FRAME_RISK + core_v2 frame_posture 在 `用` 上 net 只产出 +4 单位 counter expand（IoU 几乎不动）；加进 P0_GRID 后吃 `_refine_homepage_p0_grid` 结构改写，IoU 0.874 → 0.835（−0.039）。
- **Phase 1B layer extension（B，保守路线）**：`IDENTITY_CORE_V2_CHARS` + `IDENTITY_CORE_LAYER_CHARS` 同时加 `重事算基真章第喜`；`IDENTITY_LAYER_RISK_CHARS` 同步加 `重事算第章`（喜/基/真已在），强制 `_identity_core_open_counters` / `_identity_core_lighten_secondary` skip，只跑 `_identity_core_layer_gap` 0.010em。原因：`重` 已在 TURN_FINAL_CHARS（priority displace 1.75）、`章` 已在 IDENTITY_MULTI_HORIZ_CHARS（multi_mid_contain 0.935）、`第` 已在 HOOK_FINAL_CHARS，再加 counter / secondary 会出现三叠风险。
- **Phase 1C diag extension（C）**：`IDENTITY_CORE_V2_CHARS` + `IDENTITY_CORE_DIAG_CHARS` 加 `大太夫又关` 5 字。`IDENTITY_DIAG_CHARS` 不动（仍只含 `文天玄`），所以只触发 `_identity_core_diag_tension`，不会触发 heavier 的 `_refine_identity_diagonal`。
- 不动任何 magnitude；不引入新 pass；不修改任何 skip 列表的其他位置。

### 度量结果

`scripts/measure_groups.py --baseline local/ref/baselines/Luo-v0.4.9.ttf`：

| bucket | v0.4.9 | v0.4.10 | Δ raw | 备注 |
|---|---:|---:|---:|---|
| frame / walk / heart / stack / roof / water / speech / side / hook / turn / generic | unchanged | unchanged | +0.0000 | ✓ skip 守住 |
| **core_v2** | **0.8175** | **0.8097** | **−0.0078** | 13 新字进桶，加 `用` 重写 |
| OVERALL | 0.8278 | 0.8274 | −0.0004 | |

累积 v0.4.8 → v0.4.10：core_v2 −0.0123，OVERALL −0.0006，frozen 桶 12/12 +0.0000。30 字 anchor LXGW raw 0.7486 → 0.7440（−0.005，因为 anchor 集含 大 章 等 v0.4.10 改字）。`月` 冻结字逐点匹配通过。

每字 raw IoU 跳变（v0.4.10 vs v0.4.9 same chars）：

| 字 | v0.4.9 raw | v0.4.10 raw | Δ | 通道 |
|---|---:|---:|---:|---|
| 用 | 0.874 | **0.835** | **−0.039** | A 续修，进 P0_GRID |
| 章 | ~0.87 | **0.623** | **−0.247** | B 三叠（multi_horiz + turn priority + core_v2 layer_gap） |
| 喜 | ~0.83 | **0.740** | **−0.090** | B layer + 已有 LAYER_RISK |
| 真 | ~0.86 | **0.831** | **−0.029** | B layer |
| 第 | 0.876 | **0.848** | **−0.028** | B layer，离开 hook 桶 |
| 基 | 0.879 | **0.862** | **−0.017** | B layer |
| 算 | 0.873 | **0.853** | **−0.020** | B layer |
| 太 | ~0.86 | **0.824** | **−0.036** | C diag |
| 又 | ~0.85 | **0.812** | **−0.038** | C diag |
| 大 | ~0.87 | **0.852** | **−0.018** | C diag |
| 关 | 0.874 | **0.868** | **−0.006** | C diag |
| 夫 | 0.875 | **0.865** | **−0.010** | C diag |
| 重 | 0.879 | **0.874** | **−0.005** | B layer，但已在 TURN_FINAL_PRIORITY，layer_gap 微动 |
| 事 | ~0.87 | **0.825** | **−0.045** | B layer |

### 视觉验证

- `local/ref/renders/v0410_phase1bc_check.png`：4 列 × 4 档字号（22/32/48/96px），覆盖 14 字
- `local/ref/renders/v0410_zhang_zoom.png`：`章` 单字 200/100/60/32px 大字号对照

`章` 是本轮 IoU 跳变最大的字（−0.247）。视觉验证：v0.4.10 的 `章` 立字头明显收紧、下 `早` 部上下层次分明、整体更挺更印楷感，**不是破坏，是真正的"不像 LXGW 了"**。32/60px body 阅读尺寸下笔画完整、结构清晰、无 chip。

### Roughness polish: kill v0.4.4 signatures + tighten H endpoint

落 Phase 1A/B/C 后实地浏览器看大字号 hero / heading，Tang 反馈 `正 / 晋 / 书 / 从 / 魏` 的折角和端点"粗糙、不好看"。STYLE.md "Screenshot-reported glyph defects" 流程：单字 280px 大对照 → 缺陷类分类 → 元凶 pass → 最小责任旋钮。

**元凶定位**：

1. `书 / 字 / 魏 横折钩根` knuckle —— 来自 v0.4.4 签名 `luo_hook_root_inward_handle` 0.002em，在 200px+ 读为内 kink
2. `正 / 晋 / 章 横画右 cap` 步进/凹陷 —— 一部分来自 v0.4.4 签名 `luo_horiz_end_emphasis` 0.005em 顿笔，更主要来自 **bolden + 残留 LXGW cap arc + straighten 拉平不彻底** 的几何残留（pt 30 被 bolden 抬 +28u，cap arc 被 straighten 压扁，cap 变成 pt 30 上 7u 的微凸读为"小步进"）
3. `从 / 入 撇尾 chunky` —— BOLDEN_DIAG + ENDPOINT_DIAG + STRAIGHTEN_DIAG 联动
4. Tang 直接指 Tsanger Print Kai："最好看，参考他的"。Tsanger Print Kai 的 horiz cap 是清晰角切落、hook 根无 knuckle、横画端点接近切角

**调整内容**（4 个参数，全是降幅度 / 关签名）：

- `LUO_HORIZ_END_EMPHASIS_PUSH_EM` 0.005 → **0**（彻底关。v0.4.4 签名当时为"sub-pixel 几何距离 LXGW"设计，但在 200px+ 实地变成可见 step。Phase 1A/B/C 后 90+ 高频字进 CORE_V2 结构改写，签名的距离贡献已可被 CORE_V2 + endpoint blend + straighten 共同承担）
- `LUO_HOOK_ROOT_HANDLE_PUSH_EM` 0.002 → **0**（彻底关。同样原因。Tsanger 钩根无 knuckle）
- `ENDPOINT_H_BLEND` 0.025 → **0.015**（横端更扁。Tsanger 几乎是切角，0.025 仍留 LXGW 软圆 DNA。0.015 不机械化但更靠 Tsanger 印楷 cap）
- 试过 `STRAIGHTEN_H_BLEND` 0.65 → 0.72 但 cap off-curves 被拉到 pt 30 之下产生 **inverted step**（更难看），回退 0.65。AGENTS.md 已写入 "do not push above 0.72" 教训

**度量验收**（vs Luo v0.4.9 baseline）：

| bucket | Δ raw | 备注 |
|---|---:|---|
| frame / walk / heart / stack / roof / side / water / speech / hook / turn / generic / core_v2 | ±0.0000 ~ ±0.0008 | 全局参数动 → 所有桶都有微动，但量级都在 ±0.001 内 |
| OVERALL | −0.0001 raw / +0.0000 centered | 视觉改善但 IoU 几乎不动（raster IoU 对 cap 形态不敏感） |

30 字 anchor LXGW raw 0.744 → 0.750（+0.006，因 Phase 1B 章/喜 的横画端点变扁后一些 anchor 字的 raster overlap 与 LXGW 略升，但**视觉上 cap 形态远离 LXGW、靠近 Tsanger**）。月 冻结字逐点匹配通过。

**视觉验收** [`local/ref/renders/v0410_rough_*.png`](local/ref/renders/) 5 字 280px 对照：

- ✅ **书 / 字 / 魏** 横折钩根 knuckle 实质消失，hook 根读为干净直接的几何切角
- ⚠️ **正 / 晋** 横画 cap 残余微步进仍存，但比 v0.4.9 减弱（HORIZ_END 0 比 0.005 改善）。要根治需要新 pass `luo_horiz_cap_flatten`，是 v0.4.11 候选
- ⚠️ **从 / 入** 撇尾 chunky 未改善，需要 v0.4.11 候选 `luo_diag_endpoint_clean`

### 章 over-spread 修复

落 Phase 1B 后 Tang 反馈"`章` 的上下间隔太开了"。诊断：`章` 同时吃了 `luo_top_bottom_separate` (v0.4.7) 的 17 单位 lift+settle 和 `_identity_core_layer_gap` (CORE_LAYER) 的 41 单位 spread，合计 58 单位多余分离。`luo_top_bottom_separate` 的 skip 列表写于 v0.4.7 时只有 10 个 Lanting-Xu CORE_LAYER 字，没考虑 v0.4.10 加进的 8 个 body-frequency 字。

两件修复一起落到 v0.4.10：

1. **`luo_top_bottom_separate` skip 加 `IDENTITY_CORE_LAYER_CHARS`**：mirror `luo_frame_inner_open` / `luo_inner_counter_open` 已有的 CORE_V2 skip 模式，让 CORE_LAYER 字独占 `layer_gap` 通道，避免 v0.4.7 + v0.4.10 双叠。
2. **`IDENTITY_CORE_LAYER_GAP_EM` 0.010 → 0.007**：原值是 v0.4.4 起为 10 个 Lanting-Xu 显示锚字 tuned，加 8 个 body 字后嫌过激。降 30% 让 18 字共用更柔和的量级。这是一次有意识的解冻（AGENTS.md "Frozen Parameters" 表移到"v0.4 Unfrozen Parameters"），原因写明在文档里。

修复后 `章` spread/bbox：LXGW 36.9% / Luo v0.4.9 36.5% / Luo v0.4.10 37.3%（v0.4.7+1B 双叠时 37.5%）。每字 IoU 小幅回升（章 0.66 → 0.68，喜 0.74 → 0.79，其余 7 字 +0.001-0.008），Phase 1B 主体收益保留。

### 后续方向

- v0.4.10 把首页 generic 桶 IoU ≥ 0.87 的字从 30 个砍到 11 个，"第一眼像 LXGW"的元凶字砍掉 60%+。
- 下一个杠杆：**新 pass `luo_balanced_left_right`**，处理 generic 桶里剩余 19 字左右结构 cluster（`抽 独 种 技 虾 便 雅 柯 ...`），这一类目前没有任何专门通道
- 或者：**新 pass `luo_horiz_start_emphasis`**，mirror `luo_horiz_end_emphasis` 给所有长横左 cap 加切角入笔签名，给 Luo 一个 LXGW 完全没有的 first-glance 几何特征
- **不要** 把 1A/1B/1C 的 19 字再回流到 `luo_frame_inner_open` / `luo_top_bottom_separate` / `luo_inner_counter_open` 通道。它们的 CORE_V2 skip 已经独占给 FRAME_RISK / CORE_LAYER / CORE_DIAG，回流会造成 v0.4.5 era 的双叠加风险。
- **不要** 把 1B 的 LAYER_RISK 加字（`重事算第章`）从 LAYER_RISK 移除以"开 counter"。`重 章 第` 已经在 TURN_FINAL_PRIORITY / MULTI_HORIZ / HOOK_FINAL 通道，再加 counter + secondary 会出现三叠让中宫挤碎。

## v0.4.9 Phase 1A: extend IDENTITY_CORE_V2 frame whitelist (2026-05)

v0.4.9 是一次**只扩字符列表、不动任何 magnitude** 的 surgical 扩展，目标是把首页 generic 桶里 raw IoU vs LXGW 最高的 7 个含框字（`由 自 田 曲 直 电 用`）从 guardrail-only 通道挪到 FRAME_RISK + core_v2 frame_posture 通道。BOLDEN/HOOK/WEB_PRESENCE/DOT 全部不动。

### 根因诊断

v0.4.8 site_grouped_iou.json 显示 generic 桶 797 字（首页 71%）avg raw IoU 0.834 vs LXGW，其中 IoU ≥ 0.87 的 30 字几乎全是高频含框/上下/撇捺字（`抽 单 由 虾 技 重 基 共 者 角 一 用 …`）。这些字没有任何专门 pass 通道，只吃 `_refine_identity_all_glyph` 全覆盖护栏（counter 1.012/1.008，幅度 ≤2%）。对比 IDENTITY_CORE_V2 的结构改写（counter 1.055-1.065、frame_posture stem 0.988、layer_gap 0.010em、secondary 0.960，幅度 5-7×），generic 桶字没有任何"被结构改写的机会"。30 字 anchor 报告均值 0.7486 因为 anchor 集严重偏向已专门化的 frame/layer/diag 字，**严重失真，不反映用户实际感知**。

### 调整内容

- **`IDENTITY_FRAME_RISK_CHARS`** `目日月且` → `目日月且由自田曲直电用`（+7 字）。upstream FRAME_RISK pass 用 1.065/1.040 开 inset counter，dispatch 逻辑 `if/elif` 保证 7 字不会同时触发 FRAME (1.050/1.025) 通道。
- **`IDENTITY_CORE_V2_CHARS`** 追加 `由自田曲直电`（用已在）。
- **`IDENTITY_CORE_FRAME_CHARS`** `国回日目用月团` → `国回日目用月团由自田曲直电`（+6 字）。core_v2 dispatch 中 `if char in CORE_FRAME_CHARS: frame_posture; if char not in FRAME_CHARS and not in FRAME_RISK_CHARS: open_counters` 的 skip 逻辑保证 7 字不会发生 counter 双叠加（FRAME_RISK 已开 counter，core_v2 只跑 frame_posture stem-narrow + waist contain）。
- **副作用**：`luo_frame_inner_open` 已经 skip CORE_V2_CHARS，加字后 7 字退出 v0.4.7 的 1.010/1.006 通道，转入 FRAME_RISK 1.065/1.040 + frame_posture 0.988 通道，结构幅度提升 5-7×。
- 不动任何 magnitude 参数；不引入新 pass；不动字符 skip 列表的其他位置。

### 度量结果

`scripts/measure_groups.py --baseline local/ref/baselines/Luo-v0.4.8.ttf`：

| bucket | v0.4.8 | v0.4.9 | Δ raw | 备注 |
|---|---:|---:|---:|---|
| frame | 0.7752 | 0.7752 | +0.0000 | ✓ skip 守住 |
| walk | 0.7155 | 0.7155 | +0.0000 | ✓ skip 守住 |
| heart | 0.7707 | 0.7707 | +0.0000 | ✓ skip 守住 |
| stack | 0.7864 | 0.7864 | +0.0000 | ✓ skip 守住 |
| roof | 0.8314 | 0.8314 | +0.0000 | ✓ skip 守住 |
| water / speech / side / hook / turn / generic | 同 v0.4.8 | 同 v0.4.8 | +0.0000 | ✓ 7 字本就不在这些桶 |
| **core_v2** | **0.8130** | **0.8071** | **−0.0059** | 7 字进桶，把均值拉低 |
| OVERALL | 0.8280 | 0.8278 | −0.0002 | 7 字 / 1119 ≈ 0.6% 体量 |

每一个 frozen 桶都 +0.0000，证明 skip 列表完全有效。OVERALL 移动量小是因为只动了 7 字，但单字层面的 IoU 跳变是显著的：

| 字 | v0.4.8 raw IoU | v0.4.9 raw IoU | Δ |
|---|---:|---:|---:|
| 田 | 0.871 | **0.801** | **−0.070** |
| 由 | 0.879 | **0.828** | **−0.051** |
| 自 | 0.860 | **0.811** | **−0.049** |
| 曲 | 0.874 | **0.833** | **−0.041** |
| 电 | 0.866 | **0.831** | **−0.035** |
| 直 | 0.866 | **0.832** | **−0.034** |
| 用 | 0.875 | 0.874 | −0.001 ❗ |

30 字 anchor LXGW raw 0.7486 → 0.7493（基本不动，anchor 集不含 7 字）。`月` 冻结字逐点匹配通过。

### 视觉验证

`local/ref/renders/v049_phase1a_frame_chars.png`：4 列（LXGW source / Tsanger W04 / Luo v0.4.8 / Luo v0.4.9）× 5 档字号（16/22/32/48/96px）覆盖 7 字。

- anchor 96px：田 / 由 / 自 / 曲 / 直 / 电 内白明显开大，外瘦内开的印楷格调出现，已不读为"LXGW 派生"。
- title 32px / display 48px：层级清晰，不机械。
- body 16px / 22px：灰度稳定无回退，没有 v0.4 → v0.4.1 早期"counter 双开反而更像源"的踩坑。

### 用 字 edge case（v0.4.10 follow-up）

`用` IoU 仅 −0.001，远低于其他 6 字。诊断：`refine_visible_problem_glyphs` 列表（visible problem glyphs pass，run after refine_identity_chars）覆盖 `田 自 由 曲 直`（连同首页 P0/P1 风险队列），但**不包含 `用`**。这导致：
- `用` 只吃裸 FRAME_RISK + core_v2 frame_posture + identity_all_glyph
- `_refine_identity_frame_risk` 在隔离测试中能给 `用` 内 counter 扩 +32 单位（482→514）
- 但实际 build pipeline 中 `_refine_identity_all_glyph` 的 inset 检测对 `用` 的 4 个分块小 counter 不全部触发，导致上游叠加链条"饿了一档"，net 只有 +4 单位

修复路径（v0.4.10 任选其一）：
1. 把 `用` 加进 `refine_visible_problem_glyphs` 列表（最小改动）
2. 调 `_refine_identity_all_glyph` 的 inset 阈值容纳分块小 counter（影响面更大，需 grouped audit）

不阻塞 Phase 1A ship。`电` 同样不在 visible_problem 列表但拓扑更简单（单 inset counter），FRAME_RISK 完整生效。

### 后续方向

- **Phase 1B**（next iteration）：扩 `IDENTITY_CORE_LAYER_CHARS` 8 字 `重 事 算 基 真 章 第 喜`（保守路线把 重/事/算/第 同步加进 `IDENTITY_LAYER_RISK_CHARS` 强制 skip counter / secondary，只跑 layer_gap）。预测每字 IoU 跳 0.03-0.04。
- **Phase 1C**：扩 `IDENTITY_CORE_DIAG_CHARS` 5 字 `大 太 夫 又 关`，吃 diag_tension。预测每字 IoU 跳 0.03-0.05。
- **Phase 1A follow-up**：把 `用` 加进 `refine_visible_problem_glyphs` 列表，预测 IoU 跳 0.03-0.04。
- 不要把 1A 的 7 字再回流到 luo_frame_inner_open 通道（CORE_V2 skip 已经把它们独占给了 FRAME_RISK + core_v2 frame_posture，回流会重现 v0.4.5 era 的 counter 双叠加风险）。

## v0.4.8 refinement pass: polish without global hardening (2026-05)

v0.4.8 是一次精修，不是继续扩 coverage 或继续硬拉 generic 桶。目标是保留 v0.4.7 已经获得的去 LXGW 距离，同时把用户反馈的“有些粗糙、不如之前精致”收回来。主私有参考固定为 `TsangerJinKai02-W04.ttf`；W05 只做上限检查，避免 Luo 追成更黑更重的状态。BOLDEN_H/V、DOT_ROTATE_DEG、WEB_PRESENCE 地板和底座 LXGW WenKai Screen 都不变。

### 调整内容

- **QA 工具**：`scripts/compare_to.py` / `scripts/measure_groups.py` 修复相对 `--report` / `--output` 打印崩溃；新增 `scripts/measure_refinement_baselines.py` 输出 v0.3 / v0.4.5 / current 的 LXGW、Tsanger W04 和首页 grouped baseline；新增 `scripts/render_refinement_sheet.py` 输出本地视觉对照 `local/ref/renders/v048_refinement_sheet.png`。
- **Topology 回收**：`top_bottom_separate` 从 0.005/0.004em + 0.988/0.992 收回到 0.004/0.003em + 0.992/0.995；`frame_inner_open` 从 1.014/1.008 收到 1.010/1.006。目的不是撤掉 v0.4.7，而是减少“上下层被机械拉开”和含框内白过撑。
- **钩根/转折软化**：`HOOK_FINAL_TIP_SHARPEN` 0.15→0.13，curved hook 0.10→0.08，`TURN_FINAL_PRIORITY_DISPLACE` 1.9→1.75，`LUO_HOOK_ROOT_HANDLE_PUSH_EM` 0.003→0.002。钩仍然短、准、收住，不回到 LXGW 的圆软长钩。
- **部件层级微调**：氵旁 0.950/0.945→0.945/0.942；言旁 secondary 0.945/0.960→0.940/0.958、counter 1.110/1.060→1.125/1.065；左右分体左旁 0.970/0.980→0.965/0.978 且 gap 回到 0；dense tier 1.018/1.010→1.020/1.012，同时 dense layer/upper 稍回 identity，避免密字碎。
- **月/答 visible fixes**：`月` 是本轮显式冻结例外，final pass 直接 point-lock 到 Luo v0.3 的 50 个坐标；`scripts/check_frozen_glyphs.py` 用来验证当前 `dist` 与 v0.3 baseline 一致。`答` 只补底部口框下边，不做全字加粗、不撑大内白。
- **首页/校验页风险队列**：当前首页剩余风险先收敛在 `曲重田首里 / 争色事第使 / 技盖准装输` 三组。扩展到全覆盖校验页后，P1 继续覆盖 `虽县单盘基算相官抽自堵盏革由吕审目 / 求角走种值快强支别战同也持联继服 / 者邑棹斗身蓄考难每再维植徊岫鱼查扁主轼复建理具郁 / 往轻给法浅 / 宙宇安定宿`。P2 source-risk 追加 `堆共皋其组 / 要稚携净直 / 粟独樽鹿古 / 耳真距型律 / 便更寓展虾 / 仲朗果免雅 / 暑腹窗柯蛟 / 着看郎槊`。P3 对最高 source-risk 的 `曲抽角重争 / 盘者岫虽盏 / 求种复基斗 / 色相革事再 / 棹堵难官县 / 每植堆` 改用结构型 refiner：内白相位偏移、外框上下张力、右下收束，替代原来的轻触叠加。P4 覆盖当前 `raw >= 0.87` 中仍有结构空间的 102 个残留高风险字，幅度低于 P3，只做内白轻开、部件小分层和外框轻张力。简单形态如 `一/十/乡` 不进主动优化队列，避免为 raw IoU 硬改自然设计空间很小的字。

### 度量结果

`scripts/measure_refinement_baselines.py`：

| font | LXGW 30 raw | Tsanger W04 raw | site LXGW raw | generic raw |
|---|---:|---:|---:|---:|
| Luo v0.3 | 0.7579 | 0.5686 | 0.8446 | 0.8504 |
| Luo v0.4.5 | 0.7531 | 0.5732 | 0.8345 | 0.8410 |
| Luo v0.4.8 | 0.7486 | 0.5745 | 0.8282 | 0.8342 |

验收线保持：30 字对 LXGW 没有回升到 0.753+，首页 overall 没有回升到 0.8345+，Tsanger W04 仍在 0.56-0.59 带内。W05 raw 约 0.595，仍接近上限，所以后续不要继续按 W05 追黑度。

### 后续方向

- 先看视觉样张，不要只看 IoU。`v048_refinement_sheet.png` 覆盖 core / hook / dense / frame / stack / generic / body 七组。
- 如果还觉得粗糙，优先继续按缺陷类缩小到具体字（钩根、言旁、水旁、密字、上下结构），不要加新的全局“短/利/清/收” pass。
- 如果要继续拉开 LXGW，相比扩大 v0.4.7 bands，优先扩 `identity_core_v2` 的结构白名单；这轮已经验证盲目扩大 generic topology 会牺牲精致度。
- 不要再用参数模拟 `月`。如果它回归，先跑 `python3 scripts/check_frozen_glyphs.py`，再检查是否有后续 pass 写在 visible-problem pass 之后。

## v0.4.7 generic-coverage extension: 2 more topology pass (2026-05)

v0.4.7 是 v0.4.5/v0.4.6 拓扑驱动 pass 系列的延续，目标从 P0/P1 密字队列转向 **首页全字集中尚未被任何专门 pass 触及的 generic 桶**。新增的两个 pass 依然是几何拓扑触发，没有字符白名单，并且严格 skip 已有专门 pass 的所有字组（frame / walk / heart / stack / roof / straighten-skip / core_v2 / inner_counter middle band），确保已经稳定的字不被二次叠加。BOLDEN_H/V、HOOK / TURN / WEB_PRESENCE 全部锁定。

### 站点全字 grouped IoU 审计：v0.4.7 发起的根因

新增 `scripts/measure_groups.py`，在首页 1,118 字上按 pass-specific 白名单分桶跑 raw IoU vs LXGW。v0.4.6 baseline 出来的画面是：

| bucket | count | avg raw IoU |
|---|---|---|
| walk | 19 | 0.7155 |
| heart | 24 | 0.7708 |
| frame | 8 | 0.7723 |
| stack | 7 | 0.7832 |
| core_v2 | 37 | 0.8116 |
| side | 11 | 0.8309 |
| roof | 16 | 0.8327 |
| water | 26 | 0.8187 |
| hook | 129 | 0.8377 |
| speech | 25 | 0.8396 |
| **generic** | **796** | **0.8411** |
| turn | 20 | 0.8447 |
| **OVERALL** | **1,118** | **0.8345** |

也就是说，过去四五次迭代把 frame/walk/heart/stack 等专门 pass 字组拉到了 0.71-0.78 区间，但占 71% 的 generic 桶（796 字，无任何专门 pass）仍坐在 0.84，是把整体 IoU 顶在 0.83 的主要原因。30 字锚字集（公开 report 用）则严重偏向分布底部（96% 字落在分布的下 15%），所以那个均值 0.7531 是"门面工作的成绩单"，不是首页全字的实际现状。

### 两个新 pass

- **C1 top_bottom_separate (上下层断隔)**: 找到 outer 轮廓中 cy 落在字面上方 38% 带 (`LUO_TOP_BOTTOM_TOP_BAND=0.62`) 且面积 ≥ 4% 字面的 "upper layer"，以及 cy 落在下方 38% 带 (`LUO_TOP_BOTTOM_BOT_BAND=0.38`) 且面积 ≥ 4% 字面的 "lower layer"。当字内还有 ≥2 个 middle band outer 且每个 ≥10% 字面时（三/王/重 一类堆叠拓扑），整体 skip。命中后对 upper 沿自身中心 X 收 0.992 + 上抬 `0.005em`，对 lower 沿自身中心 Y 收 0.988 + 下沉 `0.004em`。skip 框形 / KAI_BALANCE_ROOF / STACK / HEART / WALK / STRAIGHTEN_SKIP。typical starter build：512 upper + 558 lower contours / 385 glyphs。
- **C2 frame_inner_open (含框内白舒展)**: 找到最大 outer 轮廓 bbox 至少 55% × 55% 字面（自/曲/田/角/由/见/取 一类含框拓扑），对其内部 inner counter（signed area > 0）做小幅 1.014 × 1.008 放大，但 **跳过中段 [0.30, 0.70] X 带的 counter**（已被 v0.4.6 `luo_inner_counter_open` 覆盖）以避免双叠加。skip frame 白名单 / IDENTITY_CORE_V2 / STRAIGHTEN_SKIP。typical starter build：195 counters / 124 glyphs。

### 度量结果

`measure_groups.py --baseline luo_v046.ttf` 报告：

| bucket | v0.4.6 | v0.4.7 | Δ raw |
|---|---|---|---|
| frame | 0.7723 | 0.7723 | **+0.0000** ✓ skip 守住 |
| walk | 0.7155 | 0.7155 | **+0.0000** ✓ skip 守住 |
| heart | 0.7708 | 0.7708 | **+0.0000** ✓ skip 守住 |
| stack | 0.7832 | 0.7832 | **+0.0000** ✓ skip 守住 |
| roof | 0.8327 | 0.8327 | **+0.0000** ✓ skip 守住 |
| water | 0.8187 | 0.8081 | -0.0106 ↓ |
| speech | 0.8396 | 0.8281 | -0.0115 ↓ |
| side | 0.8309 | 0.8230 | -0.0079 ↓ |
| core_v2 | 0.8116 | 0.8027 | -0.0089 ↓ |
| hook | 0.8377 | 0.8333 | -0.0044 ↓ |
| turn | 0.8447 | 0.8286 | -0.0161 ↓ |
| **generic** | **0.8411** | **0.8339** | **-0.0072** ↓ |
| **OVERALL** | **0.8345** | **0.8277** | **-0.0068** ↓ |

每一个 frozen 桶都达到了 +0.0000 严格相等，证明 skip 列表完全有效。下降发生在没列入 v0.4.7 skip 列表的桶（water/speech/side/core_v2/hook/turn），也是预期内的：这些 pass 的下游字组在结构上确实可以受益于上下层断隔或含框内白舒展，没有理由强行排除。30 字锚字集均值 0.7531 → 0.7430（-0.0101），movement 主要来自 turn/water/core_v2 这三个 anchor 集中重叠的桶。

### 视觉验证

`local/ref/renders/v047_topology_check.png`：A/B/C 三组共 32 字三排（LXGW / Luo v0.4.6 / Luo v0.4.7）。
- A 组（心远月国实寒家字宇宙安帝头眷透道）— 全部 pixel-identical，skip 列表覆盖正确。
- B 组（孟答案共曾兴县章首）— 上下层之间能看到清晰的呼吸空间，符合"上下结构清晰断隔"设计意图。
- C 组（由田角自见取）— 内白轻微开放，肉眼能感觉到"内部更透气"，但骨架不变。

`local/ref/renders/v047_body_readability.png`：16/22/32/48px 四档正文渲染（v0.4.6 vs v0.4.7）。16/22px 灰度完全稳定无发虚，32/48px 上下结构字（孟/答/案）能看出层次改进。

### 不要做

- 不要把 `LUO_TOP_BOTTOM_LIFT_EM` / `SETTLE_EM` 推过 0.008，会出现 "上半部漂离" 的视觉问题，特别是上半较轻的字（答/案）。
- 不要把 `LUO_FRAME_INNER_X` 推过 1.025，会破坏含框紧凑字（角/田）的内白节奏。
- 不要从 v0.4.7 两个 pass 的 skip 列表里删字。每一个 skip 都对应一个已经在另一个 pass 里精调的字组；移除会出现 v0.4 → v0.4.1 同款的"几个 pass 各自看着 OK，叠在一起破坏正文"问题。
- 不要把白名单字 (frame/walk/heart/stack/roof) 从专门通道挪到 generic 通道企图"再做一次"。专门通道的几何是按字组拓扑独立校准的，二次叠加无意义。

### 后续方向

如果 v0.4.8+ 还要继续把 generic 桶往下拉：

1. **不要扩签名 push**（`LUO_HORIZ_END_EMPHASIS_PUSH_EM` / `LUO_HOOK_ROOT_HANDLE_PUSH_EM`），AGENTS.md 已硬约束。
2. **不要扩 BOLDEN 减重**，v0.4.2 验证过会重现 12-19px 发虚。
3. **优先方向：调小 `LUO_TOP_BOTTOM_TOP_BAND` 到 0.60 / `BOT_BAND` 到 0.40** 让 官-style（cy 边界附近）的字进入命中集；预计 +50-100 字命中。验证时必须重跑 `measure_groups.py --baseline` 确认 skip 桶仍然 +0.0000。
4. **更长线：扩 IDENTITY_CORE_V2_CHARS 到 ~80-100 字**（v0.4.5 HANDOFF 已写明的方向），把更多字带入 frame_posture / layered / diag 三类结构重写。

## v0.4.6 homepage dense-counter audit pass (2026-05)

v0.4.6 是一次首页样式队列驱动的小步修正，目标是 P0/P1 密字的内白和灰度层级。BOLDEN、HOOK、WEB_PRESENCE、v0.4.5 三个 generic pass 的原始幅度都不回退；新增的只是 `inner_counter_open` 内部的 **dense_counter_tier**，仍然是几何拓扑触发，不按字符名触发。

- **B4 dense_counter_tier (密字内白二阶)**: 当一个 CJK glyph 至少有 7 个 contours，且 `inner_counter_open` 已找到中段 eligible counter，同时满足 eligible counters ≥ 2 或 dot-like component contours ≥ 3，就对同一批 counter 追加 `LUO_DENSE_COUNTER_X/Y = 1.018 / 1.010`。这给 籍/赢/魔/麟 这类密字增加局部内白，但不做全字减重、不改外框、不碰 BOLDEN。
- 这个 tier 继承 `inner_counter_open` 的 frame / STRAIGHTEN skip 规则，所以不会叠到 `identity_core_v2` 已经专门处理的框形字，也不会碰走之底、忄旁和独立心字结构。
- 后续若 P0 仍未完全消失，优先继续分析具体 counter / layer topology。不要把 `LUO_DENSE_COUNTER_X` 推过 1.025，也不要用全局 lightening 解决密字发黑。

## v0.4.5 typographic-kai abstractions: 3 generic component refiners (2026-05)

v0.4.5 在 v0.4.4 稳定签名几何之上，加入三个**几何拓扑驱动**的部件级抽象 pass。每个 pass 都基于轮廓拓扑（signed area、centroid、aspect、area ratio）触发，**不依赖字符白名单**，自然推广到全 CJK 集；同时各 pass 都尊重已有的 presence-floor、`STRAIGHTEN_SKIP_CHARS`、frame/stack/roof 等专属通道，不与下游既有几何叠加冲突。BOLDEN 与 v0.4.3 的可读性参数（HOOK_FINAL_TIP_SHARPEN、WEB_PRESENCE 地板）全部锁定不动。

- **B1 bottom_anchor_settle (底盘下沉)**: 找到 outer 轮廓中 cy 落在字面下方 36% 带、面积在 [1.5%, 30%] 区间内、且 aspect ≥ 1.5 或 width ≥ 40% 字宽的"扁底"轮廓。当字内还有更高位的 outer 轮廓时（排除 一/乙 一类单笔字），把这条扁底沿自身中心 Y 收 0.945 并向上抬 0.008em，模拟阅读级楷意"底不沉"的层级感。skip 框形 / KAI_BALANCE 已专门处理的 stack/roof 字（实/寒/库/头 等）避免双压。typical starter build：约 220 contours / 190 glyphs。
- **B2 left_radical_contain (左旁内收)**: 把仅在字面左侧 46% 内、聚合面积落在 [4%, 22%] 字面区间的 outer 轮廓识别为左旁部件，按 0.94/0.975 收向各自中心、再向右推 0.006em 拉开与右部的间隙。skip 已有专门通道的 KAI_BALANCE_SIDE_SPLIT / SPEECH / WATER 字组与框形字。把 v0.4.3 的 11 字 SIDE_SPLIT 白名单泛化到所有同类拓扑的字（往/径/征/敛/松/孤/雄/状 等）。typical starter build：约 295 contours / 192 glyphs。
- **B3 inner_counter_open (内白舒展)**: 对 signed area > 0 的内部 counter 轮廓，若其重心 X 落在字面中段 [30%, 70%] 内、面积在 [0.5%, 15%] 区间内，沿轮廓自身中心横向放 1.040、纵向放 1.020。skip 框形字（已经有 identity_core_v2 的 frame_posture 处理）与 STRAIGHTEN_SKIP_CHARS。typical starter build：约 900 counters / 406 glyphs。

度量层面，30 字锚字 256px IoU 几乎不动（raw 0.7504 → 0.7522，centered 0.7215 → 0.7206），符合 AGENTS.md 已有的"raster IoU 对小幅几何调整不敏感"。结构距离上，本地私有评测的 top-30 字打分总和下降 ~3%，径/次 退出 top-30，径(-0.132) 茫(-0.098) 泽(-0.078) 剑(-0.072) 式(-0.064) 给(-0.042) 今(-0.038) 等是这一轮 visible 改善最显著的字。视觉上 left_radical 组（怡/往/径/征/给/缪）左旁明显更收，inner_counter 组（言/试/调/诸/皆/熹）中段更透气，bottom_anchor 组（实/库/头/寒/苦/茫）底盘更轻。

视觉对照与本地输出（不进公开仓库）：
- `local/ref/renders/deep_study_groups.png` 与 `deep_study_after.png`：4 组拓扑×6 字×before/after 对照（96px）。
- `local/ref/renders/homepage_anchor_v0.4.5.png`：12 个首页锚字 16/24/64px 三档可读性。
- `local/ref/metrics/site_private_queue.json`：全站私有队列 + 分组计数。

如果之后还想继续把 Luo 与底盘字拉开距离，禁止把 B1-B3 的 magnitude 再往上推（B1 scale_y < 0.93 会让字看着掉一截、B2 X < 0.92 会让左旁出现明显间断、B3 X > 1.05 会让 皆 一类紧凑字内白炸开）。优先方向是在保持现有 magnitude 的前提下，加第 4 个几何 pass（如顶横上提或字心上拉）或扩展 IDENTITY_CORE_V2 / FRAME 白名单到更多字。

## v0.4.4 widening: three Luo-only signature features (2026-05)

v0.4.4 拉开 Luo 与底盘字 LXGW WenKai Screen 的结构距离，但不动 v0.4.3 已经稳定的灰度参数（BOLDEN_H/V、HOOK_FINAL_TIP_SHARPEN、WEB_PRESENCE 地板、KAI_BALANCE 全部锁定）。三件几何签名 + 一项白名单微扩：

- **A1 横画末端微顿挫 (luo_horiz_end_emphasis)**：纯几何，无字符白名单。把每一条接近水平、长度 ≥ glyph max(w,h) × 0.25 的弦的右端 cap 之后的几个轮廓点向下推 ≤ `LUO_HORIZ_END_EMPHASIS_PUSH_EM = 0.005em`，按距离衰减，模拟印楷的"顿"。LXGW 的 cap 先向上、再向下，所以新算法先走过 cap top 再开始推，避免在 cap 顶端制造小尖刺。横折/钩根（next on-curve 下落 ≥ 20% glyph_h）跳过；STRAIGHTEN_SKIP_CHARS（心字底/忄旁/走之底）跳过；inner contours（counter holes）跳过。typical starter build：706 segments / 533 glyphs。
- **A2 钩根 inward handle (luo_hook_root_inward_handle)**：纯几何，无字符白名单。沿用 `refine_hooks_final` / `cap_hook_tail_widths` 的钩检测（60-130° + 不对称长度），找到钩根 on-curve 之前的 off-curve 句柄，沿字心方向推 ≤ `LUO_HOOK_ROOT_HANDLE_PUSH_EM = 0.003em`。LXGW 的钩根是直入直出，Luo 多了一个微小的内弯 "knuckle"。typical starter build：1238 hooks / 629 glyphs。
- **A3 点画转角 14° → 17°**：`DOT_ROTATE_DEG` bump，其他点参数不动，soft 通道（氵/讠）保持近似 identity 不受影响。Luo 的 xiaokai 楔形点比 LXGW 偏角更明显，方向感更强。
- **B 框形白名单微扩**：`IDENTITY_FRAME_CHARS` 加 `团`（+ 同步加进 `IDENTITY_CORE_V2_CHARS` / `IDENTITY_CORE_FRAME_CHARS`），让 v2 frame_posture 的稳定外框 + 开内白处理覆盖到 团；其他白名单（HEART_CHARS 已含 忘/必/忽，WALK_FINAL_CHARS 已含 遇/过/这）核查后无需改动。

度量层面，30 字锚字 384px raster IoU 几乎没有移动（baseline raw 0.7479 / centered 0.7159 → v0.4.4 raw 0.7476 / centered 0.7160）。三个签名特征单次推动量都在 5-6 units 量级，384 raster 上是 sub-pixel，落不到 IoU 上。这印证 AGENTS.md 已经记录的"raster IoU 对纯权重/微小几何变化不敏感"，结构距离是真的，但需要 bow distance + 视觉对照来读。

视觉对照与本地输出：
- `local/ref/renders/lxgw_widen_after.png`：30 字 LXGW vs Luo v0.4.4 192px 对照
- `local/ref/renders/widen_homepage_anchors.png`：homepage hero / sample / body 多档字号
- `local/ref/renders/widen_homepage_browser_top.png` / `widen_homepage_browser_long.png`：浏览器实地截图

如果未来需要更大 IoU 偏移，禁止把签名 push_em 上拔（heavy tail / fishhook 风险），优先选择扩展 IDENTITY_CORE_V2_CHARS 或 IDENTITY_LAYER_RISK 等白名单字组，让既有的结构 pass 触及更多字。

## v0.4.3 audit-driven 减法迭代 (2026-05)

v0.4.3 是一次纯参数放松的"减法迭代"，不引入任何新 pass、不动字符白名单、不改 BOLDEN/H/V。出发点是 v0.4.2 在浏览器实地审阅后发现的几类残留缺陷，每类都用一档参数往 identity 方向松一点：

- **钩根尖刺 / 折点钉头**：`HOOK_FINAL_TIP_SHARPEN` 0.18→0.15、`STRAIGHTEN_MAX_PERP_RATIO` 0.18→0.20、`TURN_FINAL_PRIORITY_DISPLACE` 2.2→1.9。三个 P0 一起把 priority 锚字（落/笔/书/览/无）的钩尾再钝化一点，让长横右端的角点保护带覆盖更多控制点，priority 字的骨节强度也回退到既能看到又不显刺。
- **小点存在感不足**：`WEB_PRESENCE_DOT_MIN_EM` 0.150→0.160、`KAI_BALANCE_WATER_X/Y_SCALE` 0.940/0.935→0.950/0.945、`KAI_BALANCE_SPEECH_DOT_X/Y` 0.860/0.840→0.880/0.860。氵旁三点与讠点都再放松一档，body size 不再丢点。
- **副横偏弱**：`WEB_PRESENCE_H_MIN_EM` 0.075→0.080、`MULTI_HORIZ_SECONDARY` 0.978→0.985、`IDENTITY_ALL_H_LAYER_X` 0.997→0.999。把副横最小可见底再抬一档，同时让 H_LAYER 接近 identity，避免与 MULTI_HORIZ_SECONDARY 叠乘。
- **左旁过弱 / 顶轻底碎**：`KAI_BALANCE_SIDE_LEFT_X/Y` 0.960/0.972→0.970/0.980；`KAI_BALANCE_ROOF_BOTTOM_X/Y` 0.925/0.925→0.945/0.945、`KAI_BALANCE_STACK_BOTTOM_X/Y` 0.910/0.885→0.930/0.910。split 字左旁、宝盖底、上下结构底都再松一档，让宇/宙/家/序/实/寒 的底部不再被压得太狠。

针对的缺陷类（class of defects）：钩尾尖刺、折点钉头、小点掉点、副横缺笔、左旁过瘦、宝盖与上下结构底碎。BOLDEN_H/V、DOT_SHORT_AXIS、HOOK_FINAL_SHORTEN、HOOK_FINAL_TAIL_CONTAIN、HOOK_FINAL_TIP_SHARPEN_CURVED、TURN_FINAL_DISPLACE 全部按 v0.4.2 锁定不动。资产版本随之升到 `0.4.3-xxxxxxxx`，方便区分缓存。

视觉对照写到 `local/ref/renders/audit_fix_after.png`（12 锚字 + 4 密字 / 4 档），不进公开仓库。

## v0.4.2 weight restore + 几何 corner protection (2026-05)

v0.4.1 系统性回退把 KAI_BALANCE / HOOK / IDENTITY 的过激参数撤掉，但没有动当时的 `BOLDEN_H=5` / `BOLDEN_V=13`。结果：减重 + 撤补偿叠加，所有字偏瘦，主笔骨架立不住，正文再次发虚；同时 `无` 的竖弯钩、`字` 宝盖右端、`子` 横折钩在大字号上能看到尖刺三角。

根因有两条，必须一起处理：

1. **重量缺一档**：v0.4 早期试过 4/11 太薄、5/13 还是欠，回到 v0.3 的 6/14 才稳。这次把 `BOLDEN_H/V` 一次性回补到 6/14，配合 v0.4.1 已经回调的 KAI_BALANCE / HOOK / IDENTITY，整体灰度回到可读区间。`BOLDEN_DIAG_BONUS` 维持 7.0，撇捺锚字 `文/之/来/兮/今/代/友/这` 在新基线下没有过粗。
2. **straighten_strokes 拉到了角点上**：H 通道的 BLEND=0.65 把宝盖右端、横折钩转角附近的 off-curve 控制点一起沿 chord 拉，结果是这些角点被往 chord 方向拽，渲染出明显的下三角尖刺。新增 `STRAIGHTEN_MAX_PERP_RATIO=0.18` 几何阈值：单个 off-curve 离 chord 的垂直距离若超过 chord 长度的 18%，判定为角点控制，跳过这次拉拽。bow 控制通常在 <5%；角点控制在 15%-30%，阈值能干净地区分。

另外 `refine_hooks_final` 之后新增 `cap_hook_tail_widths` pass，做几何钩尾约束，不依赖任何字符白名单：

- 用与 `refine_hooks_final` 一致的钩检测（60-130° + 不对称长度）找到所有 CJK 字的钩根 p1。
- 在 p1 点沿 d_in 的法线方向找最近的对边 outline 点，得到主笔局部 stroke 宽度（hook root width）。
- 沿 d_out 走 4 个采样点，每个点再次用同样的法线 ray 找对边，得到尾部局部 outline 宽度。
- 任何采样点的 tail width 超过 root width × (1 + tolerance) 时，对该点和对边点做对称的内推，超额的一半推回，最大 16 单位。
- 触发约束的 hook 数量在 starter 集（1100+ 字）大约 1500-1800 次，覆盖 380+ 字，不需要白名单。

资产版本随之升到 `0.4.2-xxxxxxxx`，方便区分缓存。

视觉对照写到 `local/ref/renders/web_glyph_weight_restore.png`（8 字 / 4 档），不进公开仓库。

## v0.4.1 web-body reduction (2026-05)

v0.4 启动后实地测网页正文，发现一组系统性可读性问题：弯钩/竖弯钩在大、中字号读为两段折线（笔/书/览/无），细点在 17-19px 正文断成碎片（地/发/亦/源 氵第三点），副横在叠加 pass 后掉到 ~0.96 而像缺笔（荒/无/东/起/代），左旁明显比右部轻（地/源/起/代）。

根因不是单条参数，而是 v0.4 同时叠加了多条"短/利/清/收"通道：`HOOK_FINAL_SHORTEN/TIP_SHARPEN` 增强、`TURN_FINAL_DISPLACE` 提升到 2.5 且全 CJK 跑、`MULTI_HORIZ_SECONDARY` 与 `IDENTITY_ALL_H_LAYER_X` 在同一字上叠乘、`KAI_BALANCE_SIDE_LEFT` 拉黑左旁、`DOT_SHORT_AXIS` 收得过狠。每条单看都符合 print-kai 方向，叠加却把网页正文打穿。

v0.4.1 的处理是回调与拆分，不是新增规则：

- 钩通道：`HOOK_FINAL_SHORTEN` 0.18→0.16，`HOOK_FINAL_TIP_SHARPEN` 0.24→0.18，新增 `HOOK_FINAL_TIP_SHARPEN_CURVED=0.10` 让弯钩 (≥80°) 只动 tip on-curve，off-curve 句柄保留连续曲线；`HOOK_FINAL_TAIL_CONTAIN` 0.055→0.045，弯钩再砍一半。`HOOK_FINAL_CHARS` 加上 `笔览无东亦起` 让用户报的字也走新通道。
- 转折通道：默认 `TURN_FINAL_DISPLACE` 2.5→1.6、`TURN_FINAL_INNER` 0.94→0.955；新增 `TURN_FINAL_PRIORITY_DISPLACE=2.2` 与 `TURN_FINAL_PRIORITY_INNER=0.94`，只在 `TURN_FINAL_CHARS` 锚字组保留 v0.4 强度。
- 点通道：`DOT_SHORT_AXIS` 0.50→0.55（回到 v0.3 上限不再追楔形），`WEB_PRESENCE_DOT_MIN_EM` 0.125→0.150 抬最小可见底，`WEB_PRESENCE_H_MIN_EM` 0.066→0.075。
- 氵旁：`KAI_BALANCE_WATER_X/Y_SCALE` 0.915/0.910→0.940/0.935，并删掉位置内嵌的 0.920/0.895 二次 cap，让第三点不再跨过最小可见底。
- 副横：`MULTI_HORIZ_SECONDARY` 0.965→0.978，`IDENTITY_ALL_H_LAYER_X` 0.994→0.997，`IDENTITY_SIMPLE_H_LAYER_X` 0.990→0.995，断掉 v0.4 的乘法堆叠。
- 左旁：`KAI_BALANCE_SIDE_LEFT_X/Y` 0.945/0.960→0.960/0.972，`KAI_BALANCE_SIDE_SPLIT_CHARS` 收窄到真正需要额外降灰的字组。
- 网页底字保护：`SITE_BODY_READABILITY_CHARS` 改为构建期从 `index.html`/`README.md`/`proof/a4.html`/`assets/styles/*.css` 加 12 个被报告字动态合并；构建日志会打 `[luo] body readability guard: N glyphs`。
- 视觉对照：`local/ref/renders/web_glyph_regression_after.png` 是本轮 12 字 B|A 12 字组合，覆盖 18/22/32/96/200 px。

度量层面 raster IoU 仍接近 v0.4 startup（0.747 vs 0.753），符合 AGENTS.md 的 "IoU 对纯权重不敏感"；这次靠视觉对照与 web 正文反馈兜底。AGENTS.md 与 STYLE.md 的相关条目已对齐 v0.4.1 数值并加了"不要重新堆叠"的硬约束。

## 当前状态

Luo v0.4 是一次主动的设计方向调整：从"LXGW 派生的软楷"挪到"私有印刷楷意参考抽象出的理性楷意 + 魏晋小楷骨法"。这不是 v0.3 final 的 hot-fix，而是基于 source IoU、本地 private reference IoU 与 bow distance 度量的整体重排。v0.4.2 在 v0.4.1 系统回退之后把基础重量回补到 v0.3 baseline（6/14），同时给 straighten 加几何角点保护，并在 hook refine 之后加几何尾宽 cap，三者一起补回 v0.4.1 撤掉补偿后欠的灰度。v0.4.4 在 v0.4.3 稳定灰度之上加三件 Luo-only 几何签名（横画末端微顿挫、钩根 inward handle、点画转 17°）+ 团 框白名单微扩，拉开与 LXGW 的结构距离，BOLDEN 与 readability 地板全部不动。

风格比例从 v0.3 的 50/40/10（魏晋小楷 / 当代舒展楷意 / 工程）调整到 v0.4 的 **60/30/10（私有印刷楷意参考抽象 / 魏晋小楷骨法 / 工程）**。底盘字 LXGW WenKai Screen v1.522 不变（OFL 友好），通过新增 `straighten_strokes` pass 加 ~15 个解冻参数重调来实现转向。

v0.3 的状态 / handoff 见 [HANDOFF.v0.3.md](HANDOFF.v0.3.md)，已打 tag `v0.3.0-final` 保留可回退。

## 本轮关键改动

- **新增 `straighten_strokes` pass** ([scripts/build.py](scripts/build.py))，插在 bolden 之后、narrow 之前。把每个 contour 上 on-curve 之间的 span 按角度分到 H / V / DIAG 三档，按 0.65 / 0.60 / 0.30 的 BLEND 把 in-between off-curve 点拉向 chord。`STRAIGHTEN_SKIP_CHARS` 只豁免「真正独立的心字结构」`心必忍`、忄旁字（左侧三笔精细几何）、走之底字（专门的 refine_walk_final）。复合 心字底（思/想/感/慎 等）不在豁免名单——一开始全豁免会让"心 维持 v0.3 软楷 + 上半部件被拉直"造成同字内不一致。
- **15 个参数解冻重调**（详见 AGENTS.md "v0.4 Unfrozen Parameters" 表）：
  - BOLDEN 减重 6/14 → 5/13（最初 4/11 让 12-19px body 发虚，回了一档）
  - HOOK_FINAL 更利落（SHORTEN 0.14→0.18, TIP_SHARPEN 0.18→0.24），同时保留小字号钩尾存在感
  - TURN_FINAL 更骨节（DISPLACE 1.2→2.5），且不再是 30 字白名单——所有 CJK 都跑骨节修整
  - DOT_SHORT_AXIS 0.55 → 0.50（更楔形，但保留网页正文点画存在感）
  - 端点 H/DIAG 更平直
  - IDENTITY 字面率更舒展
- **新增并扩展 `refine_kai_component_balance` pass**：这轮截图暴露出 `书/清/源/落/魔/代` 的问题不是单纯粗细，而是部件层级。新 pass 在 dot shaping 之后处理窄作用域结构：氵旁降灰并上提、密字正向开内白与层距、密集字上部轻收、`书` 右点收短、`言/讠` 点与副横层级、左右分体左旁降灰、宝盖/上下结构下盘收束、走之底更短更收，并对 `斗/考/兴/今` 一类宽字和斜势字做边缘/下尾 containment；网页小字号反馈后，点画、讠副横、氵旁与左侧小部件的压缩已回调，并加入最小可见尺寸 guard；同时把 `落` display anchor 从上部外扩改为上部收住、底部更收。
- **`compare_to_source.py` → `compare_to.py`**：泛化为支持 `--target source|private|both`。公开报告只写 source，private reference verdict 写到忽略的 `local/ref/metrics/`。
- **STYLE.md / AGENTS.md** 重写 design direction，列出 v0.4 解冻参数表与"do not"的 v0.4 边界。
- **bow distance 作为内部度量**：raster IoU 对纯权重变化不敏感（笔画变细时 IoU 反而升高），所以 v0.4 不再把 IoU 当硬门，改看 bow distance + 视觉对照。

## v0.3 → v0.4 度量对比

30 字核心锚字集上：

| 度量 | v0.3 final | v0.4 (P1+P2) | 参考 |
|---|---|---|---|
| Luo↔LXGW raw IoU | 0.758 | 0.753 | (target ≤ 0.55) |
| Luo↔private reference raw IoU | local-only | local-only | (target 0.50-0.60) |
| bow distance (font units) | 29.2 | 17.8 | LXGW=26.3, private reference tracked locally |
| stroke pixels (mean) | 16732 | 16198 | -3.2% (lighter) |

bow distance 是 v0.4 的真正信号：从 v0.3 的 29.2u（比 LXGW 26.3 还高，因为 bolden 加了曲度）降到 17.8u，更接近本地 private reference 的方向。本地视觉对照应写入 `local/ref/renders/`，不进入公开 proof。

raster IoU 反而轻微上升是预期的：BOLDEN 减重让 Luo 的总笔画面积变小，跟两个参考字体的 union 都缩小，IoU 数学上升高。这是 metric 的盲区，不是设计跑偏。

## 双向门

```bash
.venv/bin/python scripts/compare_to.py                 # source + optional private local report
.venv/bin/python scripts/compare_to.py --strict        # CI / release 用
.venv/bin/python scripts/compare_to.py --target source
LUO_PRIVATE_KAI_REF=/path/to/private.ttf .venv/bin/python scripts/compare_to.py --target private
```

公开写出：

- `proof/similarity_lxgw.json` — Luo↔LXGW

私有参考写入：

- `local/ref/metrics/similarity_private.json`
- `local/ref/metrics/similarity_private_dual.json`
- `local/ref/renders/`

`--strict` 行为：both 模式下 `lxgw_below_max` 与已配置的 `private_in_target_band` 同时通过才退出 0；single 模式下任何字超过 per-glyph 上限退出 1。

commercial print-kai reference 是本地私有输入，不进仓库 / CI；通过 `LUO_PRIVATE_KAI_REF` 指向本机字体文件。CI 未配置时 private 分支优雅跳过，只跑 LXGW。

## 仍需人工目测

按 STYLE.md 锚字组逐字看：

- 心字底独立结构：`心 必 忍` —— 在 STRAIGHTEN_SKIP_CHARS 豁免名单里，不能被拉直；hook 几何是字体本身
- 心字底复合：`思 意 念 想 感 悲` —— v0.4-fix 起 NOT 在豁免名单里，让上下整字一致拉直（早期版本豁免后会"心重上轻"）
- 忄旁：`快情怀性恼愉悄惯惜慢慎慨悟悬` —— 在豁免名单里，左侧三笔精细几何易被 STRAIGHTEN 误伤
- 走之底：`透 道 遇 述 远 近 过 这 还 进 通 达 选 送 逢 迁 连 运 遍 适 迹 造` —— 同样豁免
- 撇捺：`文 永 之 来 去 兮 辞` —— 中段不能像几何 Hei 一样硬直，DIAG_BLEND=0.30 的存在就是保留速度感
- 框形：`国 回 图 园 日 目 用 月 田 间 问 阅 品` —— 外框稳，内白透气，转折骨节明显
- 复杂字：`藏 霞 霜 露 馈 赢 耀 魔 籍 麟` —— 10pt 不能堵糊（BOLDEN 减了，要重点看）

## 打印检查

10pt 是 BOLDEN 减重之后的最大风险点。发布前必须跑：

```bash
make print-proof          # 生成 proof/a4.pdf 和 proof/a4-600dpi.png
```

重点看：

- 10pt body：`代黑点述游清流` 不能发虚
- 12pt body：复杂字不糊
- 16pt heading：横画不机械
- 24pt 大字：撇捺有速度
- 48pt 标题：骨节清晰

## 已知注意点

- v0.4 起 dist/ 只产出 `.ttf` 和 `.woff2`，不再产出名不副实的 `.otf`（v0.3 也已经是这样）。
- bow distance 只是内部 QA 度量，不是公开指标；private verdict 只保存在 `local/ref/metrics/`。
- private typographic-kai reference 的选择会影响灰度判断；如果 v0.4 减重过头看着发飘，先切换本地参考重新测。
- `straighten_strokes` 的 STRAIGHTEN_SKIP_CHARS 是手工列表，扩字时新发现的部件被误伤要加进去。

## v0.4 → v0.5 规划

下一步候选：

1. v0.4-beta GB2312 一级常用字扩张（之前 v0.4 plan 有），跑 `LUO_BUILD_CHARS=gb2312-level1` 看新字在新参数下的视觉
2. CFF / OTF 真正版本（v0.3 砍了，v0.5 可以做 cu2qu reverse + compreffor）
3. 字宽变体（Compressed / Wide），让 v0.4 的舒展字面有 condensed 版本对应

## 需要关注的文件

核心构建：

- [scripts/build.py](scripts/build.py)
- [scripts/compare_to.py](scripts/compare_to.py)
- [scripts/ci_health_check.py](scripts/ci_health_check.py)
- [requirements.txt](requirements.txt)
- [Makefile](Makefile)

文档：

- [STYLE.md](STYLE.md) — v0.4 风格规范
- [AGENTS.md](AGENTS.md) — v0.4 解冻参数 + 冻结参数表
- [CONTRIBUTING.md](CONTRIBUTING.md) — 双向门用法
- [HANDOFF.v0.3.md](HANDOFF.v0.3.md) — v0.3 历史
- [README.md](README.md)

页面与样张：

- [index.html](index.html)
- [proof/a4.html](proof/a4.html)

CI：

- [.github/workflows/build.yml](.github/workflows/build.yml)
