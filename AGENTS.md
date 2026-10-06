# Luo 落文

本文件是仓库的公共项目指南，`CLAUDE.md` 软链到这里，两种运行时共用同一份。落文是受卫夫人骨法影响的中文阅读与展示字体，使用 SIL OFL 1.1。

## 项目入口

- `STYLE.md` 是风格、批量改字、锚字和验收边界的唯一风格指南，不另建并行版本。
- `scripts/build.py` 保存当前参数默认值、处理顺序、分支保护及回滚原因。改字体参数前先读对应常量、调用路径、`STYLE.md` 和几何回归检查，不把历史版本参数表当作当前值。
- [字体工程档案](docs/font-engineering-history.md) 保存原有的参数表、冻结边界、Do NOT 和回滚原因，改参数前必读相关条目。`HANDOFF.md` 补充历史设计与验证背景；历史结果不等于当前构建证据，旧表与当前实现不一致时先查清生效版本，不自动恢复旧值。
- `index.html` 是当前官网展示入口，`proof/a4.html` 是打印样张。README 使用 `assets/images/specimen.png`；更新宣传截图时先确认实际取景页面和视口，再从当前页面截图，不假设图片对应一个独立 HTML 模板。
- `proof/gb2312.html` 由 `scripts/catalog_chinese_fonts.py` 生成，公开覆盖状态保持“已覆盖 / 待补字”，不把内部优化分类显示给读者。

## Verification

```bash
python3 -m pip install -r requirements.txt
python3 scripts/fetch_base_font.py
python3 scripts/build.py
LUO_BUILD_CHARS=starter python3 scripts/build.py
LUO_BUILD_CHARS=seed python3 scripts/build.py
LUO_BUILD_CHARS=gb2312-level1 python3 scripts/build.py
make ship
python3 scripts/render_refinement_sheet.py
python3 scripts/catalog_chinese_fonts.py --no-preview
```

- 默认构建模式是 `gb2312-full`，输出 `dist/Luo-Regular.ttf` 和 `dist/Luo-Regular.woff2`。`starter`、`seed` 和 `gb2312-level1` 用于受限验证，不能把诊断子集当成完整发布字体。
- `make ship` 构建后运行冻结字形、字体几何、相似度和分组检查，不会提交或发布。保持字体二进制与 `assets/styles/luo.css`、`assets/styles/print.css`、`index.html`、`assets/asset_version.txt` 来自同一次构建；验证完不要重新构建再提交旧报告。
- 完整本机构建会刷新已经安装的 macOS 落文字体并重新注册 CoreText。未安装字体的机器、CI 和诊断子集构建不安装或替换字体。需要验证安装结果时，对比文件字节并在独立进程检查 CoreText，已打开的应用可能仍缓存旧字体。
- 字形改动须检查大小字号、简单字、密字、点画、钩画、标点和运行文本；`scripts/test_font_geometry.py` 与 `scripts/check_frozen_glyphs.py` 通过不能代替视觉验收。
- `scripts/compare_to.py` 对比源字体，`scripts/measure_groups.py` 检查分组影响，`scripts/render_refinement_sheet.py` 生成对照图。私有参考通过 `LUO_PRIVATE_KAI_REF` 提供，W05 密度上限通过 `LUO_PRIVATE_KAI_REF_W05` 提供，缺少参考时明确说明未核验，不把源字体检查当成双向验证。
- 六维姿态、字面、灰度和笔画对比使用 `python3 scripts/audit_tsanger_style.py`，设置上述参考变量后运行，验收带见 `STYLE.md`。
- 私有参考与报告留在被忽略的 `local/`，不得公开参考轮廓、字体文件或本机路径。参考只用于抽象气质、结构关系与验收，不能复制商业字体轮廓。
- 文档修改只检查路径、命令及规则一致性，不触发字体构建或本机字体替换。网站部署通过 `vercel.json` 生成覆盖页，部署成功不代表字体重新构建或安装完成。

## 字形与修改边界

- 先把截图中的缺陷归类到具体字、笔画和处理分支，再调对应参数；不先追相似度数字，也不叠加新 pass 掩盖缺陷。
- raster IoU 会受字重、平移和栅格尺度影响，不能单独作为字形改善证据。同时看 bbox-centered IoU、几何测量和大小字号对照，分别报告源字体距离与可用私有参考结果。
- 参数历史中的冻结项仍需明确设计决策才能调整。保持 `BOLDEN_V=14` 与 1em CJK advance，不通过整体加粗、收窄或放大解决局部问题；字重、姿态和字面通道各有职责，不用平移制造独立字形的假象。
- `identity_core_v2` 按 frame、layer、diagonal 白名单分流，不扩成全覆盖 pass。已有专门处理的字保留对应 skip 与保护条件，不为增加覆盖而重复叠加通道。
- 点、钩、转折、多横、框形、密字、撇捺按类型处理。宽分布输入使用自适应限制，SOFT 点画通道只轻调角度与形态；不全局加长钩尾、压薄副横、堵塞内白或恢复已否决的叠加处理。
- `月` 的冻结验收由 `scripts/check_frozen_glyphs.py` 重放允许的全局变换，不凭历史“完全同点位”描述撤销已接受的变换。`纸面` 与 `魔鬣` 的选定方向和结构保护依 `STYLE.md` 与几何测试验收，不被通用 pass 再次覆盖。
- 保持现代、可打印的楷意，不添加石刻纹理、破损、飞白或手写连笔。外部参考不改变落文自身的定位，主版保持 CJK-only，Latin 走 fallback。
- 展示页标题、短标签和字形表格避免不必要的手动换行，按实际视口验收；普通正文保留自然排版。改正在作为视觉参考的页面前先保留当前截图。

## 众测与交付

- 覆盖页向 `api/feedback.js` 提交反馈，同一字的未关闭 issue 聚合后续报告。修复已进入用户可获取的交付物后再按本轮授权处理回复与关闭。
- 反馈图片使用 `feedback-assets` 分支，`vercel.json` 对它禁用部署。认证材料只留运行环境，不进入文档、截图或提交。
- 分开报告源码、字体生成物、网站、发布资产和本机安装状态，缺少哪层验证就明确说明，不以某一层成功代替其他层。
