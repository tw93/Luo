# Luo 落文 v0.3 Handoff

## 当前状态

Luo 落文已经推进到 v0.3 release candidate。当前方向成立，保持清爽、端正、有骨、可印的气质，没有重做风格，也没有继续做整体加粗、收窄或放大字面。

这轮主要做的是工程收口和覆盖补齐：扩展 starter 字符集，补齐优先部件组，合并首页样张和部件校准，生成常用字校准页、A4 PDF 和 600dpi 打印图，统一 CSS 使用方式，并把公开页面和打印样张都纳入缺字检查。

当前构建数据：

- 版本：`0.3.0`
- glyphs：`828`
- cmap：`816`
- CJK：`807`
- starter 请求字符：`815`
- 结构优化字：`387`
- 覆盖率：`100.0%`

## 产物

已生成并验证的字体产物：

- `dist/Luo-Regular.otf`
- `dist/Luo-Regular.ttf`
- `dist/Luo-Regular.woff2`

注意：`Luo-Regular.otf` 当前是 TrueType outline 的 OpenType sfnt 兼容产物，和 `.ttf` 数据一致。这样做是为了满足分发清单，同时避免 CFF 转换带来新的轮廓风险。

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
python3 scripts/build.py
make font-audit
make print-proof
python3 -m fontTools.ttx -l dist/Luo-Regular.ttf
hb-shape dist/Luo-Regular.ttf '<priority glyph string>'
weasyprint proof/a4.html proof/a4.pdf
magick -density 600 proof/a4.pdf -background white -alpha remove -alpha off proof/a4-600dpi.png
```

缺字检查结果：

公开检查集 0 missing，包含：

- `index.html`
- `proof/a4.html`
- `README.md`

字体表检查：

- `dist/Luo-Regular.otf` 可被 `fontTools` 读取，版本 `0.3.0`
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
  font-family: "Luo", "Avenir Next", Inter,
               "SF Pro Text", "Noto Sans CJK SC", sans-serif;
}
```

Luo 只承担中文、中文标点和全角符号。英文、数字、代码走 fallback。

## 优先字分组

优先字组已写入 `proof/priority_groups.json`。当前全部覆盖，missing 为空。

点画：`清润源落读说语社视意念终寒露霜霞`

钩画：`字书亭序家设计排版印旅妙馈成式透远道遇`

端点：`落纸风骨短版排印集章源雅舒服规则`

多横：`章言书骨兰量重墨春青善美黄宇宙寒暑律吕`

框架：`国回图园日目田间阅品亭曾会`

复杂字：`落藏霞霜露馈赢耀魔读题额锦继续源族章集端筋群贤禊觞湍幽怀籍麟`

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

1. `Point marks`：点画短促、不圆、不水滴。
2. `Hooks`：钩短、准、有力，不拖不肿。
3. `Endpoints`：端点软切，不圆头、不尖刺。
4. `Multi horizontal`：主横稳，副横轻，中部不堆黑。
5. `Frames`：框架稳但透气，不黑体化。
6. `Dense complex`：复杂字内部白打开，小字号不糊。

`index.html` 已合并 01 样张，用来做首屏、字号阶梯、字形一览和长文阅读检查。

`proof/gb2312.html` 用来做长期扩字检查。当前按 GB2312 6763 常用汉字生成田字格，并标记：

- 绿色：已覆盖且已归入结构优化。
- 棕色：已覆盖但尚未归入结构优化。
- 灰色：当前 starter 构建未覆盖。

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
- `CLAUDE.md`
- `OFL.txt`

产物：

- `dist/Luo-Regular.otf`
- `dist/Luo-Regular.ttf`
- `dist/Luo-Regular.woff2`

资源：

- `assets/styles/luo.css`
- `assets/styles/print.css`
- `assets/images/logo.svg`
- `assets/images/wei.jpeg`

## 已知注意点

- `dist/Luo-Regular.otf` 不是 CFF OTF，而是 TrueType outline 的 OpenType sfnt。不要在 release 文案里说成 CFF。
- Playwright CLI 可用，但本机 Playwright Chromium 缓存缺失。这轮 PDF 用 `weasyprint` 生成。
- 截图预览不要走 Playwright。当前按 Kami 方式用 `weasyprint` 生成 PDF，再用 `pdftoppm` 输出 PNG。
- 项目目录已经从 `fumi` 改为 `/Users/tang/www/Luo`。
- `.venv/bin/ttx` 仍指向旧路径 `/Users/tang/www/fumi`，所以表检查用 `python3 -m fontTools.ttx`。

## v0.3 发布前 checklist

- [ ] 打开 `index.html`，检查首屏品牌感、首页样张、字形一览、Usage CSS 和 Footer 文案。
- [ ] 打开 `proof/gb2312.html`，检查 GB2312 6763 字田字格状态。
- [ ] 打开 `proof/a4.pdf` 或 `proof/a4-600dpi.png`，看 10pt、12pt、复杂字和反白。
- [ ] 跑 `python3 scripts/build.py`，确认缺字门禁通过。
- [ ] 跑 `make font-audit`，刷新 GB2312 6763 字校准页和预览图。
- [ ] 跑 `make print-proof`，刷新 A4 PDF 和 600dpi 打印图。
- [ ] 跑 `python3 -m fontTools.ttx -l dist/Luo-Regular.ttf`，确认表能读。
- [ ] 跑一次 `hb-shape` 优先字组，确认无 `gid0`。
- [ ] 确认 README 只保留必要授权和鸣谢，不在官网展开底盘字体历史。
- [ ] 确认 release assets 包含 `otf`、`ttf`、`woff2`、`OFL.txt`。

## 建议下一步

如果继续做 v0.3 final，不要再调整体风格参数。只做人工目测后的小范围部件修正，最多针对 10 到 20 个具体字补分类或微调局部规则。

如果进入 v0.4，优先扩 GB2312 一级常用字，再考虑 Text / Display 分包。不要在 v0.3 final 里启动大范围扩字和参数重标定。
