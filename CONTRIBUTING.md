# 贡献者手册

Luo 落文还在造字中。v0.3 默认只发布 `starter` 子集，用来保证官网、纸面试读、内部打印样张、README 和核心锚字稳定；大范围扩字放到 v0.4 之后推进。

批量改字前请先读 [STYLE.md](STYLE.md)。它是当前唯一的风格规范，包含落文的字形气质、正向/反向提示、锚点字组和验收标准。

## 本地构建

```bash
python3 -m pip install -r requirements.txt
python3 scripts/fetch_base_font.py
python3 scripts/build.py
make release-check
```

源字体 `source/LXGWWenKaiScreen-Regular.ttf` 不提交到仓库，由 `scripts/fetch_base_font.py` 下载固定版本的 LXGW WenKai Screen，并校验 SHA256。默认构建 `starter` 字符集，并检查公开页面缺字；如果缺字，构建会失败。

输出字体：

- `dist/Luo-Regular.ttf`
- `dist/Luo-Regular.woff2`

## 构建模式

```bash
LUO_BUILD_CHARS=seed python3 scripts/build.py
LUO_BUILD_CHARS=site python3 scripts/build.py
LUO_BUILD_CHARS=starter python3 scripts/build.py
LUO_BUILD_CHARS=gb2312-level1 python3 scripts/build.py
LUO_BUILD_CHARS=gb2312-full python3 scripts/build.py
LUO_BUILD_CHARS=full python3 scripts/build.py
```

- `seed`：诊断锚字。
- `site`：官网页面用字。
- `starter`：v0.3 默认发布子集。
- `gb2312-level1`：v0.4-alpha 扩字实验，starter + GB2312 一级常用字。
- `gb2312-full`：完整 GB2312 实验构建，一级字稳定后再使用。
- `full`：保留源字体所有 glyph 的底盘实验模式，不作为 v0.3 发布默认。

## 校准页面

`proof/gb2312.html` 是扩字检查页，只显示 `已覆盖` / `待补字` 两种状态；结构优化分类属于内部调参信息，不在字表页区分。该文件 ~7000 行、由 `scripts/catalog_chinese_fonts.py` 生成、不随仓库提交，本地需要先跑一次 `make font-audit`，部署到 vercel 时由 `vercel.json` 的 `buildCommand` 自动重生成。

这些本地校准产物只用于发布前确认，不随仓库提交：

- `proof/gb2312.html`（CI/部署生成，本地手动重生成）
- `proof/*.pdf`
- `proof/*.png`
- `proof/*.json`（`proof/similarity_report.json` 例外，作为去源字体相似度的硬门提交）
- `proof/*.txt`
- `proof/*-preview.html`
- `proof/similarity_images/`

## 去源字体相似度

```bash
python3 scripts/compare_to_source.py
```

跑核心锚字（与 `STYLE.md` 的 `core_anchors` 同步），输出 `proof/similarity_report.json`。规则在 STYLE.md 已写明：普通字 raster IoU 目标不超过 `0.60`，极简字（`一二三十中木` 等）放宽到 `0.75`。如果分数是靠整字平移降的，centered IoU 仍会高，必须继续做结构、内白、主副笔和端点差异。

发布前至少跑：

```bash
.venv/bin/python scripts/build.py
PY=.venv/bin/python make font-audit
.venv/bin/python -m fontTools.ttx -l dist/Luo-Regular.ttf
hb-shape dist/Luo-Regular.ttf '落文归去来兮辞前赤壁赋常用字校准已覆盖待补字'
git diff --check
```
