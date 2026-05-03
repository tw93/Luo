<p align="center">
  <img src="assets/images/logo.svg" width="120" height="120" alt="Luo">
</p>
<h1 align="center">Luo 落文</h1>
<p align="center">适合纸面排版和长文阅读的建设中中文字体。</p>
<p align="center">
  <a href="https://github.com/tw93/luo"><img src="https://img.shields.io/github/license/tw93/luo?style=flat-square" alt="License"></a>
  <a href="https://github.com/tw93/luo/releases/latest"><img src="https://img.shields.io/github/release/tw93/luo?style=flat-square" alt="Release"></a>
</p>

---

## 这套字

Luo 落文是一套适合中文排版、纸面样张和长文阅读的开源字体。它取法卫夫人笔意，保留一点早期楷书的骨感，横轻竖重，端正含蓄，不做古风装饰，也不追求手写感。

我希望它落在文章、文档、封面和项目官网里时，安静、有秩序，读久了不腻。

关键词：有筋骨、纸面耐读、端正含蓄、现代可排版。

## 建设中

落文目前还是 v0.3 的 starter 子集，已经覆盖官网、README、打印样张、《兰亭集序》和一组常用校准字，但还不是完整 GB2312，也不是全量中文字体。

后续会继续扩字、校准部件和检查小字号灰度。字形、覆盖范围、文件大小和构建方式都可能继续调整，正式使用前建议先看样张和常用字校准页。

## 预览

- 网页样张：[index.html](index.html)
- GB2312 常用字校准：[proof/gb2312.html](proof/gb2312.html)
- A4 打印校准：[proof/a4.html](proof/a4.html)

## 使用

仓库会提交当前构建产物，可以直接下载：

- [dist/Luo-Regular.otf](dist/Luo-Regular.otf)
- [dist/Luo-Regular.ttf](dist/Luo-Regular.ttf)
- [dist/Luo-Regular.woff2](dist/Luo-Regular.woff2)

网页里可以这样引入：

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

## 构建

```bash
python3 -m pip install -r requirements.txt
python3 scripts/fetch_base_font.py
python3 scripts/build.py
make release-check
```

默认构建 `starter` 字符集，覆盖公开样张和一组优先校准字。构建会检查公开页面缺字；如果缺字，会直接失败。

源字体 `source/LXGWWenKaiScreen-Regular.ttf` 不提交到仓库，由 `scripts/fetch_base_font.py` 下载。`make release-check` 会重建字体、刷新 `proof/gb2312.html`、生成本地 A4 PDF 与 600dpi PNG，并确认 `dist/Luo-Regular.ttf` 能被 fontTools 读取。

这些校准产物只用于发布前确认，不随仓库提交：

- `proof/*.pdf`
- `proof/*.png`
- `proof/*.json`
- `proof/*.txt`
- `proof/*-preview.html`

可选构建模式：

```bash
LUO_BUILD_CHARS=seed python3 scripts/build.py
LUO_BUILD_CHARS=site python3 scripts/build.py
LUO_BUILD_CHARS=starter python3 scripts/build.py
LUO_BUILD_CHARS=full python3 scripts/build.py
```

## 授权与鸣谢

Luo 采用 [SIL Open Font License 1.1](https://openfontlicense.org) 授权。可以自由使用、分享、嵌入和改造；衍生字体也需要继续使用 SIL OFL 授权。

落文基于 [LXGW WenKai Screen](https://github.com/lxgw/LxgwWenKai-Screen) 构建，感谢 [LXGW / 落霞孤鹜](https://github.com/lxgw) 的开源字体工作，也感谢 [Kami](https://github.com/tw93/kami) 提供的纸面设计语境。

详细授权见 [OFL.txt](OFL.txt)。
