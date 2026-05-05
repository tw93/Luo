# Luo 落文 v0.3 Handoff (archived)

> **归档说明**：v0.3 final 的状态文档，留作 v0.4 之后的历史参考。当前活动 handoff 见 [HANDOFF.md](HANDOFF.md)。v0.3 状态在 git tag `v0.3.0-final` 上完整保留。

## 当前状态

Luo 落文已经推进到 v0.3 final refinement。当前方向成立，保持清爽、端正、有骨、可印的气质，没有重做风格，也没有继续做整体加粗、收窄或放大字面。

这轮主要做的是“受控上调”：落文主线调整为魏晋小楷式清骨 50% / 当代舒展楷意印刷字的开阔骨架 40% / 现代字体工程稳定性 10%。西湖石刻字只作为短、涩、利、收得住的局部提醒，不引入石刻纹理、行书连带或古风装饰。

工程上不再靠整体加粗、收窄或放大字面。新增 dot-aware bolden cap、白名单转折精修和 hook tail containment，同时只轻调复杂字内部白与多横副笔层级。

去源字体相似度已经开始作为 v0.3 之后的硬检查项。比较脚本目前保持为本地忽略的实验工具，不随仓库提交；检查时需要同时看 raster IoU 和 bbox-centered IoU，官网优先普通字目标不超过 `0.60`，极简字可放宽到 `0.75`。默认 `IDENTITY_SOURCE_SHIFT_*` 已关闭，如果 centered overlap 仍然高，必须继续做结构语法重写。

当前 `starter` 覆盖字只保留 guardrail 强度的 all-covered identity pass。一次强推参数曾把最高源字体 IoU 降到 `0.767`，但视觉明显跑偏，已经回滚。后续去源字体相似度不能靠全集硬参数推进，只能对白名单字分批做结构、内白、主副笔和端点语法重写。

覆盖策略已经明确：v0.3 继续以 `starter` 子集收口，不在 final 阶段启动大范围扩字。v0.4 才进入扩字，先跑 `gb2312-level1`，一级常用字稳定后再跑 `gb2312-full`。

## 本轮最终精修

- `scripts/build.py` 在 bolden 阶段识别点类 contour，并用 `DOT_BOLDEN_X_CAP_FACTOR=1.15` 只限制 x 位移，不缩放 y 位移，避免同类点拉成斜杠，同时保住斜笔厚度。
- 保留 adaptive dot lerp：`DOT_SHORT_AXIS=0.55`、`DOT_LONG_AXIS_SOFT=1.00`、`DOT_SHORT_AXIS_SOFT=0.95`、`DOT_RELAX_PIVOT=1.0`、`DOT_RELAX_GATE=1.8`。SOFT 通道定义为角度归一、轻碰形态。
- `refine_turns_final` 只作用于 endpoints / frames / multi_horiz 优先组，默认 `TURN_FINAL_DISPLACE=1.2`、`TURN_FINAL_INNER=0.96`、角度上限 `105°`，跳过点类和低点数 contour。
- `refine_hooks_final` 新增 `HOOK_FINAL_TAIL_CONTAIN=0.06`，只在白名单内沿轴线轻收钩尾，不恢复旧的全局 hook pass。
- 复杂字只开内部白：`DENSE_COMPLEX_INNER=0.970`、`MULTI_HORIZ_SECONDARY=0.965`。`NARROW_*`、`SCALE_Y`、`SPACING_*` 不动。
- 骨气与落纸感精修新增 `core_anchors` 回归组：`落文字书心清骨风纸印国回月雨霜藏魔赢道远家亭序集章兰永天玄黄`。
- 端点软切拆成横端、竖底、撇捺端三个 subtype：`ENDPOINT_H_BLEND=0.040`、`ENDPOINT_V_BOTTOM_BLEND=0.045`、`ENDPOINT_DIAG_BLEND=0.030`，避免端点形状模板化。
- 框形字转折使用 frame-only 参数：`TURN_FINAL_FRAME_DISPLACE=1.6`、`TURN_FINAL_FRAME_INNER=0.955`、`TURN_FINAL_FRAME_SEG_MAX=140`，只覆盖 `国回图园日目用月田间问阅品`。
- extra dense 组局部开白：`DENSE_COMPLEX_INNER_EXTRA=0.945`、`DENSE_TOP_REDUCE_EXTRA=0.955`，只压副笔灰度，不整体缩字或加粗。
- 全覆盖 identity pass 覆盖 `1115` 个已覆盖汉字，但默认值只作为护栏：`IDENTITY_ALL_TOP_RAISE_EM=0.010`、`IDENTITY_ALL_BOTTOM_SETTLE_EM=0.003`、`IDENTITY_ALL_WAIST_CONTAIN=0.994`、`IDENTITY_ALL_COUNTER_EXPAND_X/Y=1.012/1.008`、`IDENTITY_SIMPLE_FACE_X/Y=1.008/1.006`、`IDENTITY_REGULAR_FACE_X/Y=1.004/1.004`、`IDENTITY_COMPLEX_FACE_X/Y=1.002/1.002`、`IDENTITY_ALL_H_LAYER_X=0.994`、`IDENTITY_ALL_V_STEM_X/Y=0.994/1.004`、`IDENTITY_ALL_DIAG_EXPAND=1.004`。`IDENTITY_POSTURE_*` 只对白名单锚字生效，禁止再次全量套用。
- 本地版新增 `identity_core_v2` 核心结构白名单，覆盖官网、README 和纸面试读高频字，但只对三类结构真正下手：框形 `国回日目用月` 开内白并稳外框；多层 `春暮壁前墨黑兰亭集序` 拉开层距、开 counter、减副横；撇捺/长斜 `文永之来去归兮辞` 增加外展张力和尾部收束。其他 core 字只经过 guardrail，不再顺手改。
- 本轮 51 个核心样字对比：平均源字体 raster IoU 从 `0.807` 降到 `0.788`，`23` 个字下降，`0` 个字变得更像源字体；平均黑度从 `0.159` 降到 `0.158`。改善最明显的是 `国、兰、回、亭、日、集、月、暮、墨、壁、目、前、黑、用`。`赤、年` 试过结构硬改后没有稳定收益，已退回 guardrail。

## 调参经验沉淀

- fixed multiplier 是 input-blind 的；对输入差异大的属性要做自适应 lerp，而不是继续换常量。
- bolden 对点画的横向拉伸是非线性的；下游 dot pass 只能收窄差距，根因需要在 upstream bolden 里限制点类 contour。限制时只能 clamp x 位移，不能缩放整段 delta，否则会把斜向点/短撇的纵向厚度一起压薄。
- SOFT 通道语义是“归一化角度，轻碰形态”，不是“换一个小点的 carve 系数”。
- char list 只用于整字跳过或完全不同处理逻辑；形态分布差异要靠 generic 参数处理。
- 端点要有统一气质，但不能有统一形状；如果 subtype softening 出现尖刺或毛躁，第一回滚是退回单一 `SOFTEN_BLEND=0.05`。
- 如果 frame-specific turn 误伤框形字，第一回滚是把 frame 参数退回 base turn 参数，保留 core anchors 和复杂字开白。
- source-similarity gate 不能替代人工目测。普通字超过 `0.60` 时先看结构、内白、主副笔和端点差异；极简字超过 `0.75` 才算真正失败。
- 第一批白名单的验收看整组趋势，不要求每个字立刻过 `0.60`。若某个结构组变丑或更贴源字，先退回该组，不能为了分数扩大到全覆盖参数。

当前构建数据：

- 版本：`0.3.0`
- glyphs：`1140`（包含 .notdef 等控制 glyph）
- cmap：`1126`（cmap 表里所有 codepoint，含 space、CJK 标点、全角符号）
- CJK：`1116`（U+4E00-9FFF + U+3400-4DBF 范围内的汉字）
- starter 请求字符：`1125`（去重后从 SEED + LANTING + COMMON_STARTER + PRIORITY + 页面文件收集）
- 结构优化字：`398`（命中 CHAR_CATEGORIES 中某一类的汉字）
- 覆盖率：`100.0%`（starter 请求字 vs cmap 覆盖）
- GB2312 校准页：`1115 / 6763` 已覆盖，覆盖率 `16.5%`，`5648` 待补（`1115` = 真正能渲染的 GB2312 汉字数；和 `1116` 的差是落在 CJK 范围但不在 GB2312 内的字）。
- 相似度报告：本地忽略的比较脚本会输出 `proof/similarity_report.json` 和 `proof/similarity_identity.html`，这些产物默认不提交。当前修复版以视觉质量优先；核心字已经开始降低源字体重叠，但简单字和未进入结构白名单的字仍可能偏高，后续只能继续按白名单分组做结构重写，不能再用强全局参数硬压。

## 产物

已生成并验证的字体产物：

- `dist/Luo-Regular.ttf`
- `dist/Luo-Regular.woff2`

v0.3 起不再产出 `.otf`。之前的 `.otf` 只是 TrueType outline 套 OpenType sfnt，不是真正的 CFF 字体，会让识别器错误期待 PostScript 轮廓。如果未来需要真正的 CFF 版本，应该作为独立产物（cu2qu reverse + compreffor）打包发布，而不是顺手让 `.ttf` 改个后缀。

公开样张：

- `index.html`
- `proof/gb2312.html`
- `proof/a4.html`

本地校准产物，不随仓库提交：

- `proof/gb2312-preview.html`
- `proof/gb2312-preview.pdf`
- `proof/gb2312-preview.png`
- `proof/a4.pdf`
- `proof/a4-600dpi.png`
- `proof/page_chars.txt`
- `proof/optimized_chars.txt`
- `proof/unoptimized_chars.txt`
- `proof/missing_chars.txt`
- `proof/coverage_report.json`
- `proof/page_coverage_report.json`
- `proof/priority_groups.json`
- `proof/gb2312.json`

页面资源：

- `assets/styles/luo.css`
- `assets/styles/print.css`
- `assets/images/logo.svg`
- `assets/images/wei.jpeg`

## 已验证

已跑过的检查：

```bash
.venv/bin/python scripts/build.py
PY=.venv/bin/python make font-audit
.venv/bin/python -m fontTools.ttx -l dist/Luo-Regular.ttf
hb-shape dist/Luo-Regular.ttf '<priority glyph string>'
.venv/bin/weasyprint proof/a4.html proof/a4.pdf
magick -density 600 proof/a4.pdf -background white -alpha remove -alpha off proof/a4-600dpi.png
```

缺字检查结果：

公开检查集 0 missing，包含：

- `index.html`
- `proof/a4.html`
- `README.md`

字体表检查：

- `dist/Luo-Regular.ttf` 可被 `fontTools` 读取，版本 `0.3.0`
- `dist/Luo-Regular.woff2` 可被 `fontTools` 读取，版本 `0.3.0`
- 横向 overhang 检查：`0`
- `OS/2.achVendID`：`LUO `

打印输出：

- `proof/a4.pdf` 已生成
- `proof/a4-600dpi.png` 已生成
- PNG 尺寸：`4961x7016`
- PNG 密度：`600x600`

## 当前 CSS 规则

公开页面、样张和 debug 页面已统一引用 `assets/styles/luo.css`，打印页引用 `assets/styles/print.css`。官网和 README 的 CDN 使用方式仍为：

```css
@font-face {
  font-family: "Luo";
  src: url("https://cdn.jsdelivr.net/gh/tw93/luo@main/dist/Luo-Regular.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
  unicode-range: U+4E00-9FFF, U+3400-4DBF, U+3000-303F, U+FF00-FFEF;
}

body {
  font-family: "Luo", Seravek, Candara, Optima,
               "Iowan Old Style", Charter, Georgia,
               "Avenir Next", "Noto Sans CJK SC", sans-serif;
}
```

Luo 只承担中文、中文标点和全角符号。英文和数字走 Seravek-first humanist fallback。官网 Usage 代码展示也走这套英文栈，真实文档里的代码块仍可由渲染器使用 mono。当前页面和打印样张不引入外部 webfont 或新的字体文件。

Luo 是独立的纸面阅读中文字体。Kami 是纸面设计语境和鸣谢来源，不是 Luo 的定位边界；公开页面不再把 Luo 写成面向某个项目的附属字体。

v0.3 不做 `Luo Complete`、`Luo Latin` 或内置 ASCII glyph。未来如需内置 Latin，应作为可选独立版本发布，不覆盖 `Luo Regular` 主版。

## 优先字分组

优先字组已写入 `proof/priority_groups.json`。当前全部覆盖，missing 为空。

点画：`清润源落读说语社视意念终寒露霜霞`

钩画：`字书亭序家设计排版印旅妙馈成式透远道遇`

端点：`落纸风骨短版排印集章源雅舒服规则`

多横：`章言书骨兰量重墨春青善美黄宇宙寒暑律吕`

框架：`国回图园日目田间阅品亭曾会`

复杂字：`落藏霞霜露馈赢耀魔读题额锦继续源族章集端筋群贤禊觞湍幽怀籍麟`

心部：`心必思意念想感悲惠慨悟志怀愿恩愁惊慎忠忽怠忍`

首页展示字：覆盖首页大字、长文、字形一览、部件校准和官网说明里的高频字符。

页面控制字：覆盖首页、常用字校准入口、打印输出和真实页面说明文字。

## 仍需人工目测的部件

没有构建阻塞项。发布前建议人工看以下部件：

- 三点水、雨字头点、心字点：看短促方向和散不散。
- 走之和短钩：看钩根是否肿，钩尖是否钝。
- `国回园间阅`：看框架是否黑体化，内白是否够。
- `籍麟赢耀魔`：看 10pt 和 12pt 是否堵。
- 反白样张：看端点和钩尖是否发糊。

## 打印测试方案

当前 A4 样张已经包含：

- 10pt、12pt、14pt、16pt、24pt、48pt
- 标题短句
- 字形一览
- 复杂字压力测试
- 长文段落
- 反白测试
- 600dpi 导出图

继续检查时优先看：

- 10pt / 12pt：不糊、不堵、不发虚。
- 16pt：长文是否安静，重复字是否跳。
- 24pt / 48pt：标题是否有骨、有气质。
- 复杂字：`藏、露、霜、霞、馈、赢、耀、魔、籍、麟、禊、觞、湍、幽、怀`。

## 首页部件校准方案

`index.html` 已合并 01 样张和部件校准。部件校准按以下顺序看：

1. `Core`：30 个核心锚字先立住语法，再扩散到全字集。
2. `Point marks`：点画短促、不圆、不水滴。
3. `Slants`：`代黑点述游清流` 的斜向点和短撇要有分量，不发虚。
4. `Hooks`：钩短、准、有力，不拖不肿。
5. `Endpoints`：端点软切，不圆头、不尖刺。
6. `Multi horizontal`：主横稳，副横轻，中部不堆黑。
7. `Frames`：框架稳但透气，转折有骨节。
8. `Dense complex`：复杂字内部白打开，小字号不糊。

`index.html` 已合并 01 样张，用来做首屏、字号阶梯、字形一览和长文阅读检查。

`proof/gb2312.html` 用来做长期扩字检查。当前按 GB2312 6763 常用汉字生成田字格，并标记：

- 深框：已覆盖。
- 浅底：当前构建待补字。

页面不再区分内部结构分类和覆盖状态。结构优化分类只留给工程回归，公开校准页只表达覆盖状态，避免把内部调参状态误读成用户可用性层级。

`proof/gb2312-preview.png` 使用 Kami 走法生成：`WeasyPrint -> PDF -> pdftoppm -> PNG`，不依赖 Playwright。它是本地产物，默认被 `.gitignore` 忽略。

## 需要关注的文件

核心构建：

- `scripts/build.py`
- `scripts/fetch_base_font.py`
- `requirements.txt`
- `Makefile`

页面与样张：

- `index.html`
- `proof/gb2312.html`
- `proof/a4.html`

文档：

- `README.md`
- `STYLE.md`
- `CLAUDE.md`
- `OFL.txt`

产物：

- `dist/Luo-Regular.ttf`
- `dist/Luo-Regular.woff2`

资源：

- `assets/styles/luo.css`
- `assets/styles/print.css`
- `assets/images/logo.svg`
- `assets/images/wei.jpeg`

## 已知注意点

- v0.3 起 `dist/` 只产出 `.ttf` 和 `.woff2`，不再产出名不副实的 `.otf`；如果旧机器残留 `dist/Luo-Regular.otf`，构建时会自动清除。
- Playwright CLI 可用，但本机 Playwright Chromium 缓存缺失。这轮 PDF 用 `weasyprint` 生成。
- 截图预览不要走 Playwright。当前按 Kami 方式用 `weasyprint` 生成 PDF，再用 `pdftoppm` 输出 PNG。
- `.venv/bin/ttx` 是旧虚拟环境的 shebang，可能指向不同的路径，所以表检查用 `python3 -m fontTools.ttx`。
- 当前工作目录是 `/Users/tw93/www/luo`；路径说明以本仓库实际位置为准。
- `scripts/catalog_chinese_fonts.py --include-local-fonts` 默认用 `LUO_FONT_SCAN_ROOT` 环境变量或仓库父目录作为扫描根；可以通过 `--root` 显式覆盖。

## v0.3 发布前 checklist

- [ ] 打开 `index.html`，检查首屏品牌感、首页样张、字形一览、Usage CSS 和 Footer 文案。
- [ ] 打开 `proof/gb2312.html`，检查 GB2312 6763 字田字格状态。
- [ ] 打开 `proof/a4.pdf` 或 `proof/a4-600dpi.png`，看 10pt、12pt、复杂字和反白。
- [ ] 跑 `.venv/bin/python scripts/build.py`，确认缺字门禁通过。
- [ ] 跑 `PY=.venv/bin/python make font-audit`，刷新 GB2312 6763 字校准页和预览图。
- [ ] 跑 `.venv/bin/weasyprint proof/a4.html proof/a4.pdf` 和 `magick -density 600 proof/a4.pdf -background white -alpha remove -alpha off proof/a4-600dpi.png`，刷新 A4 PDF 和 600dpi 打印图。
- [ ] 跑 `.venv/bin/python -m fontTools.ttx -l dist/Luo-Regular.ttf`，确认表能读。
- [ ] 跑一次 `hb-shape` 优先字组，确认无 `gid0`。
- [ ] 确认 README 只保留必要授权和鸣谢，不在官网展开底盘字体历史。
- [ ] 确认 release assets 包含 `ttf`、`woff2`、`OFL.txt`。

## 建议下一步

如果继续做 v0.3 final，不要再调整体风格参数。只做人工目测后的小范围部件修正，最多针对 10 到 20 个具体字补分类或微调局部规则。

如果进入 v0.4，优先使用 `LUO_BUILD_CHARS=gb2312-level1` 扩 GB2312 一级常用字，再考虑 `LUO_BUILD_CHARS=gb2312-full`。不要在 v0.3 final 里启动大范围扩字和参数重标定。

构建模式边界：

- `starter`：v0.3 默认发布子集。
- `gb2312-level1`：v0.4-alpha 扩字实验，starter + GB2312 一级常用字。
- `gb2312-full`：完整 GB2312 实验构建，一级字稳定后再使用。
- `full`：保留源字体所有 glyph 的底盘实验模式，不作为 GB2312 发布路径。

如果需要把落文交给其他 AI 学习或批量改所有字，先使用 `STYLE.md`。它是当前唯一的风格抽象规范，包含正向/反向提示、批量改字规则、锚点字组和验收标准；不要从旧截图或旧参数重新推导风格。
