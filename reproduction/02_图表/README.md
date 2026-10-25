# 六图生成入口

从本目录运行 `python build_all.py`，生成六张图至 ../LaTeX/figures。依赖安装、论文编译与完整目录说明见上级 README.md。

图1、图2：generate_drawio.py 继承用户提供的 draw.io 包；refine_drawio.py 应用论文术语；optimize_reference.py 应用本轮视觉细化；render_drawio.py 读取实际 .drawio 原生图元导出。可编辑双页文件为 drawio/BEST_Skill_图1图2_可编辑.drawio。

图3—图6：make_charts.py、chartkit.py、svgkit.py 继承用户提供的渐变柱图源码；render.py 通过本地 Edge 导出。数据来自 source_data.json；CSV 是便于核对的统计值视图。

PNG、PDF、SVG 都可重新生成。不要把参考截图用作底图。源码中保留的旧版本函数用于来源追溯，最终生成以 build_all.py 调用链为准。
