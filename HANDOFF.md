# Luo 落文 v0.4 Handoff (print-kai pivot)

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
