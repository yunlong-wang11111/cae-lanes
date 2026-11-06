# -*- coding: utf-8 -*-
"""flow_tikz —— TikZ 科研流程图生成器（2026-10-25，审美升级三链路之论文风）。

治什么：AI 用 matplotlib 裸画流程图（手算坐标、无设计系统）很丑；论文场景的正确
渲染器是 TikZ——与 pdflatex/xelatex 正文同字体同排版引擎。本模块把「样式库 preamble」
固化下来：调用方只描述结构（节点+边），风格全部由模板承担。

用法（AI 侧）：
    from cae_lanes.flow_tikz import build_flow
    build_flow(
        nodes=[{"id":"truth","kind":"data","title":"COMSOL 真值库","desc":"229 构型"}, ...],
        edges=[{"from":"audit","to":"proxy","label":"不通过","style":"back"}, ...],
        out_dir=r"D:\\temp", name="flow") -> {"tex","pdf","png"}
布局：竖排主链（按 nodes 顺序）；相邻边=直箭头；回环(to 在 from 之前)=西/东侧绕行；
越级前进(to 在 from 之后但不相邻)=东侧绕行。kind: data/model/proc/gate/done。

宏包约束：只用本模板 preamble 里的宏包（ctex/tikz 标配，本机 MiKTeX 已验证齐全）——
禁止调用方引入新宏包（缺包会触发 MiKTeX 联网拉取挂死，AGENTS.md 红线）。
"""
import subprocess
from pathlib import Path

HEADER = r'''\documentclass[border=10pt]{standalone}
\usepackage[UTF8]{ctex}
\usepackage{tikz}
\usetikzlibrary{arrows.meta, positioning, shapes.geometric}
\tikzset{
  data/.style={rectangle, rounded corners=3pt, draw=blue!45, fill=blue!6,
    font=\small, align=center, inner sep=7pt, minimum width=5.2cm, minimum height=1.05cm},
  model/.style={data, draw=teal!50, fill=teal!8},
  proc/.style={data, draw=black!35, fill=black!4},
  done/.style={data, draw=green!45!black, fill=green!8},
  gate/.style={diamond, aspect=2.4, draw=orange!70!black, fill=orange!9,
    font=\small, align=center, inner sep=2pt},
  flow/.style={-{Latex[length=2.6mm, width=2mm]}, semithick, draw=black!60},
  back/.style={-{Latex[length=2.6mm, width=2mm]}, semithick, dashed, draw=red!65},
  skip/.style={-{Latex[length=2.6mm, width=2mm]}, semithick, draw=black!60},
  lab/.style={font=\scriptsize, text=black!60, fill=white, inner sep=1.5pt},
}
\begin{document}
\begin{tikzpicture}[node distance=9mm and 16mm]
'''

KIND_SET = {"data", "model", "proc", "gate", "done"}


def _tex_escape(s: str) -> str:
    for ch, rep in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                    ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"),
                    ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")]:
        s = s.replace(ch, rep)
    return s


def build_flow(nodes, edges, out_dir, name="flow"):
    """生成 tex → xelatex 编译 → PDF；有 fitz 则顺手出 PNG。返回产物路径 dict。"""
    if not nodes:
        raise ValueError("nodes 不能为空")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    idx = {}
    lines = [HEADER]
    prev = None
    for n in nodes:
        nid = str(n.get("id") or "").strip()
        if not nid or not nid.isascii() or not nid.replace("_", "a").isalnum():
            raise ValueError(f"节点 id 必须是 ASCII 标识符: {n.get('id')!r}")
        if nid in idx:
            raise ValueError(f"节点 id 重复: {nid}")
        kind = str(n.get("kind") or "proc")
        if kind not in KIND_SET:
            raise ValueError(f"kind 必须是 {sorted(KIND_SET)}，得到 {kind!r}")
        idx[nid] = len(idx)
        pos = "" if prev is None else f", below={'13mm' if kind == 'gate' or prev_kind == 'gate' else '9mm'}=of {prev}"
        prev, prev_kind = nid, kind
        title = _tex_escape(str(n.get("title") or nid))
        desc = n.get("desc")
        body = (f"\\textbf{{{title}}}" +
                (f"\\\\{_tex_escape(str(desc))}" if desc else ""))
        lines.append(f"\\node[{kind}{pos}] ({nid}) {{{body}}};")
    for e in edges:
        f, t = str(e.get("from")), str(e.get("to"))
        if f not in idx or t not in idx:
            raise ValueError(f"边引用了不存在的节点: {e}")
        style = str(e.get("style") or "flow")
        label = e.get("label")
        lab = f" node[lab, {'left' if style == 'back' else 'right'}=2pt, pos=0.25] {{ {_tex_escape(str(label))} }}" if label else ""
        if idx[t] == idx[f] + 1:                      # 主链相邻：直箭头
            lines.append(f"\\draw[{style}] ({f}) --{lab if label else ''} ({t});")
        elif idx[t] < idx[f]:                          # 回环：侧边绕行（按索引奇偶分侧防重叠）
            side = "west" if (idx[f] + idx[t]) % 2 == 0 else "east"
            dx = "-2.2" if side == "west" else "2.2"
            lines.append(f"\\draw[{'back' if style == 'flow' else style}] "
                         f"({f}.{side}) --{lab if label else ''} ++({dx},0) |- ({t}.{side});")
        else:                                          # 越级前进：东侧绕行
            lines.append(f"\\draw[{style}] ({f}.east) --{lab if label else ''} ++(2.2,0) |- ({t}.east);")
    lines.append("\\end{tikzpicture}\n\\end{document}")
    tex = out / f"{name}.tex"
    tex.write_text("\n".join(lines), encoding="utf-8")

    r = subprocess.run(["xelatex", "-interaction=nonstopmode", f"-output-directory={out}", str(tex)],
                       capture_output=True, text=True, timeout=150, cwd=str(out))
    pdf = out / f"{name}.pdf"
    if r.returncode != 0 or not pdf.exists():
        tail = (r.stdout or r.stderr or "")[-1200:]
        raise RuntimeError(f"xelatex 编译失败（禁止引入新宏包——缺包会触发联网拉取挂死）。日志尾:\n{tail}")
    result = {"tex": str(tex), "pdf": str(pdf)}
    try:
        import fitz
        doc = fitz.open(str(pdf))
        doc[0].get_pixmap(dpi=200).save(str(out / f"{name}.png"))
        doc.close()
        result["png"] = str(out / f"{name}.png")
    except ImportError:
        pass                                          # 无 fitz 时只出 PDF（论文场景主形态）
    return result


if __name__ == "__main__":
    # 自测：与 D:/temp/flow_demo/flow.tikz.tex 同款结构
    r = build_flow(
        nodes=[
            {"id": "truth", "kind": "data", "title": "COMSOL 真值库", "desc": "229 构型 · 热黏真值"},
            {"id": "proxy", "kind": "model", "title": "Torch 级联代理", "desc": "快速近似（毫秒级）"},
            {"id": "opt", "kind": "proc", "title": "双路优化", "desc": "强化学习 / 进化算法"},
            {"id": "audit", "kind": "gate", "title": "独立复算审核", "desc": "C1--C5 复核"},
            {"id": "final", "kind": "done", "title": "结论定稿", "desc": "移入 verified/ 登记 INDEX"},
        ],
        edges=[
            {"from": "truth", "to": "proxy"}, {"from": "proxy", "to": "opt"}, {"from": "opt", "to": "audit"},
            {"from": "audit", "to": "final", "label": "通过"},
            {"from": "audit", "to": "proxy", "label": "不通过", "style": "back"},
            {"from": "audit", "to": "opt", "label": "参数回炉", "style": "back"},
        ],
        out_dir=r"D:\temp\flow_demo", name="flow_auto")
    print("FLOW_TIKZ_OK", r)
