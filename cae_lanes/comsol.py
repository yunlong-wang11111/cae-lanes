# -*- coding: utf-8 -*-
"""
simlib.comsol —— COMSOL 6.4 自动化的"已验证通路"封装
规格来源: aic_race\\out\\COMSOL-AI使用手册.md (2026-10-07) + s20_selftest.py (实测模板)

v1 范围: 2D 无支管模型(主管矩形 + Pressure 入口 + PlaneWaveRadiation 出口 + SoundHard 补集)
  - 有支管 2D / 3D 待 v1.1 (需先提炼 s23_clean_full.py / s28_3d.py 的几何写法)

内置守卫(手册 §5 死路清单,库层强制):
  [x] SoundHard 只作用 Complement(入口∪出口), 绝不 selection().all()   (§5.2 零解)
  [x] 网格只用 autoMeshSize(N), 不暴露 hmax/Size                        (§5.8 静默0单元)
  [x] export 节点: 求解后创建、只 run 一次、回读 lastwrittenfile         (§5.1)
  [x] 每次运行唯一类名/唯一 csv 名 ⇒ 并发不互踩                          (§5.18)
  [x] 反推波数固定 COMSOL 正分支 k=2pi f/(c0*(1+i*eta))                  (§5.12)
  [x] stdout 全 ASCII 标记(GBK 车道), 判据词=SIMLIB_<NAME>_DONE          (§4.2/4.3)
"""
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

try:
    from . import config as _cfg  # package mode
except ImportError:
    import config as _cfg      # standalone MCP mode
COMSOL_ROOT = _cfg.COMSOL_ROOT
COMSOL_BATCH = _cfg.COMSOL_BATCH
COMSOL_JAVAC = _cfg.COMSOL_JAVAC
PLUGINS = _cfg.COMSOL_PLUGINS
DEFAULT_WORKDIR = _cfg.COMSOL_WORKDIR   # 必须 ASCII 且可写(手册 §2.1)


class ComsolError(RuntimeError):
    pass


def k_comsol(f, c0=340.0, eta=0.05):
    """COMSOL 数据反推专用波数(正分支)。
    COMSOL 材料 c=c0*(1+i*eta) 配 e^{+iwt} 约定 ⇒ k=2pi f/(c0*(1+i*eta))。
    !! 不要把 _rect_fem2d 的 k(FEM 侧 e^{-iwt} 约定)拿来拟合 COMSOL 数据(§5.12 共轭分支)。
    口径注记(手册 §8.7, 2026-10-10): 分析侧另一常见分支 k=w(1+i*eta)/c0 是同一物理的
    相位约定镜像(e^{+ikx} 衰减 vs 本库 e^{-ikx} 衰减), 自洽即正确; 两分支的数字不可直接
    并排——历史上混用曾整批作废(eta=0.05 体损耗口径 A 从 0.998 复算为 0.039)。
    """
    return 2.0 * 3.141592653589793 * f / (c0 * (1.0 + 1j * eta))


def _sanitize(name):
    s = re.sub(r'[^A-Za-z0-9_]', '_', str(name))
    if not re.match(r'^[A-Za-z_]', s):
        s = 'sl_' + s
    return s[:40]


# ── Java 模板: 逐字取自 s20_selftest.py(实测跑通), 仅替换类名/参数/文件名 ──
_JAVA_TEMPLATE = r'''
import com.comsol.model.*;
import com.comsol.model.util.*;

public class __CLASS__ {
  static void p(String s) { System.out.println("SL| " + s); }
  public static void main(String[] args) throws Exception {
    Model m = ModelUtil.create("__CLASS__");
    m.param().set("c0","__C0__[m/s]","c0");
    m.param().set("eta","__ETA__","eta");
    m.param().set("rho0","1.225[kg/m^3]","rho0");
    m.component().create("comp1", true);
    m.component("comp1").geom().create("geom1", 2);
    m.component("comp1").geom("geom1").create("main","Rectangle");
    m.component("comp1").geom("geom1").feature("main").set("size",
        new String[]{"__LM__","__HM__"});
    m.component("comp1").geom("geom1").feature("main").set("pos", new String[]{"0","0"});
__BRANCH__
    m.component("comp1").geom("geom1").run();
    int nd = m.component("comp1").geom("geom1").getNDomains();
    p("geom domains=" + nd);
    if (nd != __NDOM__) { p("SIMLIB_GEOM_BAD domains=" + nd); return; }

    m.component("comp1").physics().create("acpr","PressureAcoustics","geom1");
    m.component("comp1").material().create("mat1","Common");
    m.component("comp1").material("mat1").materialType("nonSolid");
    m.component("comp1").material("mat1").propertyGroup("def").set("soundspeed","c0*(1+i*eta)");
    m.component("comp1").material("mat1").propertyGroup("def").set("density","rho0");
    m.component("comp1").material("mat1").selection().all();

    m.component("comp1").selection().create("selin","Box");
    m.component("comp1").selection("selin").geom("geom1",1);
    m.component("comp1").selection("selin").set("entitydim",1);
    m.component("comp1").selection("selin").set("xmin","-0.002");
    m.component("comp1").selection("selin").set("xmax","0.002");
    m.component("comp1").selection("selin").set("ymin","-0.001");
    m.component("comp1").selection("selin").set("ymax","1");
    m.component("comp1").selection("selin").set("condition","inside");
    m.component("comp1").selection().create("selout","Box");
    m.component("comp1").selection("selout").geom("geom1",1);
    m.component("comp1").selection("selout").set("entitydim",1);
    m.component("comp1").selection("selout").set("xmin","__LO__");
    m.component("comp1").selection("selout").set("xmax","__HI__");
    m.component("comp1").selection("selout").set("ymin","-0.001");
    m.component("comp1").selection("selout").set("ymax","1");
    m.component("comp1").selection("selout").set("condition","inside");
    m.component("comp1").selection().create("unisel","Union");
    m.component("comp1").selection("unisel").geom("geom1",1);
    m.component("comp1").selection("unisel").set("entitydim",1);
    m.component("comp1").selection("unisel").set("input", new String[]{"selin","selout"});
    m.component("comp1").selection().create("rest","Complement");
    m.component("comp1").selection("rest").geom("geom1",1);
    m.component("comp1").selection("rest").set("entitydim",1);
    m.component("comp1").selection("rest").set("input", new String[]{"unisel"});

    m.component("comp1").physics("acpr").create("prs1","Pressure",1);
    m.component("comp1").physics("acpr").feature("prs1").selection().named("selin");
    m.component("comp1").physics("acpr").feature("prs1").set("p0", "1[Pa]");
    m.component("comp1").physics("acpr").create("pwr1","PlaneWaveRadiation",1);
    m.component("comp1").physics("acpr").feature("pwr1").selection().named("selout");
    m.component("comp1").physics("acpr").create("shd1","SoundHard",1);
    m.component("comp1").physics("acpr").feature("shd1").selection().named("rest");
    p("physics OK");

    m.study().create("std1");
    m.study("std1").create("freq","Frequency");
    m.study("std1").feature("freq").set("plist","__PLIST__");
    m.component("comp1").mesh().create("mesh1");
    m.component("comp1").mesh("mesh1").autoMeshSize(__MESHN__);
    m.component("comp1").mesh("mesh1").run();
    int ne = m.component("comp1").mesh("mesh1").getNumElem();
    p("mesh elems=" + ne);
    if (ne <= 0) { p("SIMLIB_MESH_EMPTY"); return; }
    m.study("std1").run();
    p("solved");

    m.result().export().create("ecsv", "Data");
    m.result().export("ecsv").set("expr",
        new String[]{"x","y","real(acpr.p_t)","imag(acpr.p_t)"});
    m.result().export("ecsv").set("filename", "__W__\\__CSV__");
    m.result().export("ecsv").run();
    String lw = "";
    try { lw = m.result().export("ecsv").getString("lastwrittenfile"); } catch (Throwable e) {}
    p("exported [" + lw + "]");
    p("SL_CLASS_DONE");
  }
}
'''


class Comsol2D(object):
    """2D 无支管声学管(手册 §7 最小 API 的 v1 实现)。
    用法:
        m = Comsol2D('mycase', L=0.75, H=0.15)
        m.material(c0=340.0, eta=0.05)
        m.freqs([150, 450, 900])
        m.mesh(auto_size=1)          # 唯一网格旋钮; N 越小越细(§5.9)
        res = m.run()                # 编译+求解+导出+解析, 打印 SIMLIB_MYCASE_DONE
    """

    def __init__(self, name, L, H, workdir=DEFAULT_WORKDIR, srcdir=None, branch=None):
        """branch: dict(upper=[(x,y),...], y_bottom=float) —— 支管"镜像多边形"(s23 口径):
        upper=上边界(贴主管下壁, 严格沿 x 单调不减, 左→右), y_bottom=下边界平直高度。
        便捷构造: Comsol2D.from_common_geom(combo, nfix, lead_mm, ...)"""
        self.name = _sanitize(name)
        self.L, self.H = float(L), float(H)
        self._branch = self._validate_branch(branch) if branch else None
        self._mat = dict(c0=340.0, eta=0.05, rho0=1.225)
        self._freqs = []
        self._meshn = 1
        self.workdir = workdir
        self.srcdir = srcdir or os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'comsol')
        os.makedirs(self.workdir, exist_ok=True)
        os.makedirs(self.srcdir, exist_ok=True)

    @staticmethod
    def _validate_branch(branch):
        upper = [(float(x), float(y)) for x, y in branch['upper']]
        if len(upper) < 3:
            raise ComsolError('branch.upper 至少 3 个点')
        bad = [i for i in range(len(upper) - 1) if upper[i][0] > upper[i + 1][0] + 1e-12]
        if bad:
            raise ComsolError('branch.upper 上边界 x 必须单调不减(§5.11 自相交防线), '
                              '违反处在 %s (如 i=%d: %.6f -> %.6f)'
                              % (bad[:5], bad[0], upper[bad[0]][0], upper[bad[0] + 1][0]))
        yb = float(branch['y_bottom'])
        if not all(y >= yb - 1e-12 for _, y in upper):
            raise ComsolError('branch.upper 有低于 y_bottom 的点, 多边形会翻转')
        raw = upper + [(upper[-1][0], yb), (upper[0][0], yb)]
        clean = [raw[0]]
        for pt in raw[1:]:
            if abs(pt[0] - clean[-1][0]) > 1e-12 or abs(pt[1] - clean[-1][1]) > 1e-12:
                clean.append(pt)
        return clean

    @classmethod
    def from_common_geom(cls, name, combo, nfix, lead_mm, L=0.75, H=0.15,
                         xoff_frac=0.35, **kw):
        """用 common_geom(唯一真源)构造 s23 同款支管几何。
        自带 §3.3 单位自检: make_H 第 3 参数是毫米, L_eff 错了直接拒跑。
        ⚠️ make_H(combo, nfix, lead_mm) 返回 **(高度剖面函数 Hf, L_eff)**, 不是高度数组;
        逐片高度取 G.heights(combo, nfix)。2026-10-07 冒烟首跑就是踩了这个(null 返回函数当下标)。"""
        import sys as _sys
        ag = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if ag not in _sys.path:
            _sys.path.insert(0, ag)
        import common_geom as G
        # 注意: make_H 返回 (Hf, L_eff) —— 第 1 项是**函数**(高度剖面), 不是逐片高度数组!
        # 逐片高度必须走 G.heights(combo, nfix)。(2026-10-07 修: 原写法把 Hf 当数组下标 ⇒ TypeError)
        _, L_eff = G.make_H(combo, nfix, lead_mm)
        hv = G.heights(combo, nfix)
        if callable(hv) or not hasattr(hv, '__len__'):
            raise ComsolError('common_geom.heights 未返回数组(hv=%r): 上游 API 变了, 拒跑' % type(hv))
        if len(hv) != G.N_RIB:
            raise ComsolError('heights 长度 %d != N_RIB %d' % (len(hv), G.N_RIB))
        expect = G.L_TOT + lead_mm * 1e-3
        if abs(L_eff - expect) > 1e-9:
            raise ComsolError('common_geom 单位自检失败: L_eff=%.6f != %.6f (lead 毫米/米混用?)'
                              % (L_eff, expect))
        XOFF = xoff_frac * L
        upper = [(XOFF, 0.0)]
        if lead_mm > 0:
            upper.append((XOFF + lead_mm * 1e-3, 0.0))
        for i in range(G.N_RIB):
            h_i = float(hv[i])
            a = XOFF + lead_mm * 1e-3 + i * (G.W_R + G.W_G)
            b = a + G.W_R
            upper.append((a, -float(G.H0) + h_i))
            upper.append((b, -float(G.H0) + h_i))
            upper.append((b, 0.0))
        upper.append((XOFF + L_eff, 0.0))
        return cls(name, L, H, branch=dict(upper=upper, y_bottom=-float(G.H0)), **kw)

    def material(self, c0=340.0, eta=0.05, rho0=1.225):
        if float(c0) <= 0 or not (0 <= float(eta) < 1):
            raise ComsolError('material 参数非法: c0=%r eta=%r' % (c0, eta))
        self._mat = dict(c0=float(c0), eta=float(eta), rho0=float(rho0))
        return self

    def freqs(self, fs):
        fs = [float(f) for f in fs]
        if not fs or any(f <= 0 for f in fs):
            raise ComsolError('freqs 不能为空且必须为正')
        self._freqs = fs
        return self

    def mesh(self, auto_size=1):
        """唯一旋钮。实测: N=-1/0/1 最细(本几何上限), N 越大越粗(§5.9)。"""
        n = int(auto_size)
        if not (-1 <= n <= 5):
            raise ComsolError('auto_size 建议取 -1~5 (N 越小越细)')
        self._meshn = n
        return self

    def k(self, f):
        return k_comsol(f, self._mat['c0'], self._mat['eta'])

    def run(self, timeout_batch=3600, timeout_javac=300):
        if not self._freqs:
            raise ComsolError('先调 freqs()')
        runid = '%s_%s' % (self.name, time.strftime('%H%M%S'))
        cls = _sanitize(runid)
        csv_name = cls + '.csv'   # 唯一文件名(§5.18 并发防互踩)
        jf = os.path.join(self.srcdir, cls + '.java')
        if self._branch:
            coords = ',\n        '.join('{%.6f, %.6f}' % (a, b) for a, b in self._branch)
            branch_java = (
                '    m.component("comp1").geom("geom1").create("brpol","Polygon");\n'
                '    m.component("comp1").geom("geom1").feature("brpol").set("source","table");\n'
                '    m.component("comp1").geom("geom1").feature("brpol").set("type","solid");\n'
                '    m.component("comp1").geom("geom1").feature("brpol").set("table",\n'
                '        new double[][]{\n'
                '        %s\n'
                '        });\n'
                '    m.component("comp1").geom("geom1").create("uni1","Union");\n'
                '    m.component("comp1").geom("geom1").feature("uni1").selection("input").set(\n'
                '        new String[]{"main","brpol"});' % coords)
            ndom = 2
        else:
            branch_java = ''
            ndom = 1
        java = (_JAVA_TEMPLATE
                .replace('__BRANCH__', branch_java)
                .replace('__NDOM__', str(ndom))
                .replace('__CLASS__', cls)
                .replace('__C0__', '%.1f' % self._mat['c0'])
                .replace('__ETA__', '%.4f' % self._mat['eta'])
                .replace('__LM__', '%.4f' % self.L)
                .replace('__HM__', '%.4f' % self.H)
                .replace('__LO__', '%.4f' % (self.L - 0.002))
                .replace('__HI__', '%.4f' % (self.L + 0.002))
                .replace('__W__', self.workdir.replace('\\', '\\\\'))
                .replace('__CSV__', csv_name)
                .replace('__PLIST__', ','.join(str(int(f)) if f == int(f) else str(f)
                                                for f in self._freqs))
                .replace('__MESHN__', str(self._meshn)))
        with open(jf, 'w', encoding='utf-8') as fh:
            fh.write(java)

        t0 = time.time()
        pr = subprocess.run([COMSOL_JAVAC, '-cp', PLUGINS, '-d', self.workdir, jf],
                            capture_output=True, text=True,
                            encoding='utf-8', errors='replace',
                            timeout=timeout_javac, cwd=self.workdir)
        if pr.returncode != 0:
            tail = '\n'.join((pr.stderr or '').splitlines()[-8:])
            raise ComsolError('javac 失败:\n%s' % tail)

        pr2 = subprocess.run([COMSOL_BATCH, '-inputfile',
                              os.path.join(self.workdir, cls + '.class'),
                              '-methodcall', 'main'],
                             capture_output=True, text=True,
                             encoding='utf-8', errors='replace',
                             timeout=timeout_batch, cwd=self.workdir)
        lines = [L.strip() for L in (pr2.stdout or '').splitlines() if 'SL|' in L]
        for L in lines:
            print('  ' + L, flush=True)
        if any('SIMLIB_GEOM_BAD' in L for L in lines):
            raise ComsolError('几何自检失败(见上行 SIMLIB_GEOM_BAD)')
        if any('SIMLIB_MESH_EMPTY' in L for L in lines):
            raise ComsolError('网格为 0 单元(手册 §5.8; 库已禁用显式 hmax, 检查 auto_size)')
        if not any('SL_CLASS_DONE' in L for L in lines):
            tail = '\n'.join((pr2.stderr or pr2.stdout or '').splitlines()[-15:])
            raise ComsolError('comsolbatch 未到 SL_CLASS_DONE (返回码 %s, 用时 %.0fs)\n%s'
                              % (pr2.returncode, time.time() - t0, tail))

        csv_path = os.path.join(self.workdir, csv_name)
        res = read_comsol_csv(csv_path)
        res._meta = dict(name=self.name, runid=runid, csv=csv_path,
                         elems=_grep_int(lines, r'mesh elems=(\d+)'),
                         seconds=time.time() - t0, model=self)
        print('  [simlib] %s: %d 频点 x %d 点, 网格 %s 单元, 用时 %.0fs'
              % (runid, len(res.freqs), res.rows, res._meta['elems'],
                 res._meta['seconds']), flush=True)
        print('SIMLIB_%s_DONE' % self.name.upper(), flush=True)
        return res


def _grep_int(lines, pat):
    for L in lines:
        m = re.search(pat, L)
        if m:
            return int(m.group(1))
    return None


def read_comsol_csv(path):
    """表头驱动解析 COMSOL Data export csv。
    约定(手册 §1.3#11/§1.7#33): 首列 2 列为参数列, 之后每频点一块(2D=4 列: x,y,re,im)。
    返回 ComsolResult(.freqs 顺序 / .rows 行数 / .field(f)->(x,y,p))。
    """
    rows, hdr = [], ''
    with open(path, encoding='utf-8', errors='replace') as fh:
        for L in fh:
            if L.startswith('%'):
                hdr += L
                continue
            L = L.strip()
            if not L:
                continue
            parts = [q for q in re.split(r'[,\t;]', L) if q.strip() != '']
            try:
                rows.append([float(q) for q in parts])
            except Exception:
                pass
    if not rows:
        raise ComsolError('csv 无数据行: %s' % path)
    order = []
    for mm in re.finditer(r'@ freq=(\d+(?:\.\d+)?)', hdr):
        ff = float(mm.group(1))
        if ff not in order:
            order.append(ff)
    if not order:
        raise ComsolError('csv 表头未找到 "@ freq=" 频序: %s' % path)
    ncols = len(rows[0])
    width, rem = divmod(ncols - 2, len(order))
    if rem != 0 or width < 4:
        raise ComsolError('csv 列数 %d 与 %d 个频点不匹配(首 2 列参数 + 每频点一块)'
                          % (ncols, len(order)))
    r = ComsolResult()
    r.freqs = order
    r.rows = len(rows)
    r._A = rows
    r._width = width
    return r


class ComsolResult(object):
    freqs = []
    rows = 0
    _A = None
    _width = 4
    _meta = None

    def field(self, f):
        """返回该频点 (x, y, p复数) 的列表(按 x 排序)。"""
        if f not in self.freqs:
            raise ComsolError('频点 %s 不在结果里: %s' % (f, self.freqs))
        k = self.freqs.index(f)
        w = self._width
        out = []
        for row in self._A:
            ci = 2 + w * k
            out.append((row[ci], row[ci + 1], complex(row[ci + 2], row[ci + 3])))
        out.sort(key=lambda t: t[0])
        return out

    def fit_R(self, f, y_band=None):
        """两波拟合 |R|(COMSOL 正分支 k_comsol, §5.12)。
        y_band=(ylo,yhi) 取中线附近条带做拟合, 默认中线 ±0.01H。"""
        import numpy as np
        data = self.field(f)
        xs = np.array([d[0] for d in data])
        ys = np.array([d[1] for d in data])
        ps = np.array([d[2] for d in data])
        if y_band is None:
            ymid = 0.5 * (ys.min() + ys.max())
            y_band = (ymid - 0.01, ymid + 0.01)
        m = (ys >= y_band[0]) & (ys <= y_band[1])
        xs, ps = xs[m], ps[m]
        kk = self._meta['model'].k(f) if self._meta and self._meta.get('model') \
            else k_comsol(f)
        em = np.exp(-1j * kk * xs)
        ep = np.exp(1j * kk * xs)
        sol, *_ = np.linalg.lstsq(np.vstack([em, ep]).T, ps, rcond=None)
        return sol[0], sol[1]


# ══ v1.2 (2026-10-10): 结果取数 + 解健康检查 —— 手册 §8/§10 定稿口径 ═══════════
# 背景: 一天内五次踩坑(litrep3→twofac→tworead→meshlad→细网格解不动)后, DSH 侧用反射
# dump 实测出唯一可用的取数路径与端口配方, simlib 固化如下。

# §8.5/§10.5 网格档(实测单元数为 D_sharp3 几何; A=1-|S11|^2):
#   ★ 报告任何绝对 A 值必须标 hmax; 未经"标准配方+至少两档网格"收敛确认不作物理结论。
#   ★ Q 随网格加密单调降(实测 29%) ⇒ 报 Q 必标网格档, 跨档数字不可并排。
MESH_TIERS = {
    2e-3: dict(elems=11412,   use='快速趋势',    trust='A 至少低估 1.8 倍(实测)'),
    1e-3: dict(elems=44510,   use='可信档(峰位)', trust='与特征频率/级联三套互证 10~25Hz'),
    1e-4: dict(elems=None,    use='求 alpha(等截面管)', trust='与解析差 0.4%'),
    5e-4: dict(elems=176660,  use='细档',        trust='旧配方给病态 A=1.0000, 须按 PORT_RECIPE_TA 重跑'),
    2e-4: dict(elems=1136216, use='极细档',      trust='同上; 且必须一频点一进程(OOM)'),
}

# §10.3 端口标准配方(ta 场, 病根: 端口边界条件不自洽 ⇒ 细网格解不动/A 差 1.5 倍):
PORT_RECIPE_TA = '''\
# 标准配方(手册 §10.3, 2026-10-10 判决探针定稿; sym0/slip0 结果逐位一致, 任选其一)
1 入口 Port 选择集只含入口端面: Box, entitydim=1, xmin=-1e-5, xmax=1e-5, condition=inside
2 ★ 入口段壁面必须从 Port 选择集排除, 并显式设为 对称(sym0) 或 滑移+绝热(slip0)
3 其余壁面: 无滑移(默认) + 等热(ThermoacousticsSinglePhysics 默认)
4 出口端(盲端): 刚性壁
5 禁止"不放 Port、改硬壁+点源"(实测 |S11|=-1 无效)
注意: AdiabaticWall/Pressure 特征名在本版本不存在(Unknown_feature_ID), 别按名硬拼。'''


def java_eval_global(exprs, tag='ev1', data='dset1', per_line=20):
    """生成取数 Java 段(手册 §8.2 唯一确认可用路径, 两处独立实证 sx_litx4/_tworead2)。
    exprs: 表达式列表, 如 ['abs(ta.S11)'] —— 物理场 tag 是 ta(热声), 不是 acpr。
    嵌进模板后: 求解完立即取数打 stdout。★ 数值只走 stdout(SecurityManager 拒 Java 写盘);
    ★ 每行 <=per_line 个数(quest 日志 ~300 字符截断, 超了静默丢数据)。
    死路(别再试): m.result().numeric() 不存在(是 numerical()); mph 加载的模型里
    create("Table") 不允许; getEigenvalues() 不存在(用 getPVals/getPValsImag)。"""
    items = ', '.join('"%s"' % e for e in exprs)
    return (
        'm.result().numerical().create("%s", "EvalGlobal");\n'
        'm.result("%s").set("expr", new String[]{%s});\n'
        'm.result("%s").set("data", "%s");\n'
        'double[][] d_%s = m.result("%s").getReal();\n'
        'for (int i = 0; i < d_%s.length; i++) {\n'
        '  for (int j0 = 0; j0 < d_%s[i].length; j0 += %d) {\n'
        '    StringBuilder sb_%s = new StringBuilder("EV| row " + i);\n'
        '    for (int j = j0; j < Math.min(j0 + %d, d_%s[i].length); j++)\n'
        '      sb_%s.append(" ").append(d_%s[i][j]);\n'
        '    System.out.println(sb_%s);\n'
        '  }\n'
        '}\n'
    ) % (tag, tag, items, tag, data, tag, tag, tag, tag, per_line,
         tag, per_line, tag, tag, tag, tag)


def parse_eval_stdout(text, marker='EV|'):
    """解析 java_eval_global 输出的 stdout 文本 → {row_index: [floats]}。
    行形如 'EV| row 0 1.23 4.56 ...'(每行 <=20 个数)。"""
    out = {}
    for L in str(text).splitlines():
        L = L.strip()
        if not L.startswith(marker):
            continue
        body = L[len(marker):].strip()
        m = re.match(r'row\s+(\d+)(.*)$', body)
        if not m:
            continue
        ri = int(m.group(1))
        vals = out.setdefault(ri, [])
        for tok in m.group(2).split():
            try:
                vals.append(float(tok))
            except ValueError:
                pass
    return out


def eig_freq_q(lams):
    """黏热特征值口径(手册 §8.6)。lams: 复特征值列表(rad/s, COMSOL 特征值)。
    返回 [(f_Hz, decay_1_s, Q)]。f=|Im|/2*pi(曾误用 |Im| 高估 2pi 倍); 衰减=-|Re|; Q=pi*f/|Re|。
    硬壁 TWA 不引入数值耗散(实测 alpha=0) ⇒ 可作零耗散基线。"""
    out = []
    for lam in lams:
        lam = complex(lam)
        f = abs(lam.imag) / (2.0 * 3.141592653589793)
        dec = -abs(lam.real)
        q = (3.141592653589793 * f / abs(lam.real)) if abs(lam.real) > 0 else float('inf')
        out.append((f, dec, q))
    return out


def health_check(freqs_expected, freqs_got, S11_abs=None, A=None, n_elems=None,
                 hmax=None, solve_ok=True, one_proc_per_freq=None):
    """取数前自检(手册 §10.4 六条, 第五次踩坑后定稿)。返回 (verdict, issues[])。
    verdict: 'PASS' / 'SUSPECT'(数字不可直接引用)。
    用法: 每次从 COMSOL 取到 S11/A 后、写进任何对照表之前先跑一遍。
    one_proc_per_freq: 细网格(>17 万单元)是否一频点一进程(单进程上限约 1.3GB,
    None=未知, 只提示不判死)。"""
    issues = []
    if not solve_ok:
        issues.append('有频点 solve_ok=false')
    if A is not None:
        A = [float(x) for x in (A if isinstance(A, (list, tuple)) else [A])]
        for i, a in enumerate(A):
            if round(a, 4) == 1.0:
                issues.append('A[%d]=%.4f 恰为 1.0000 ⇒ 病态解, 该档作废' % (i, a))
    if S11_abs is not None:
        S = [float(x) for x in (S11_abs if isinstance(S11_abs, (list, tuple)) else [S11_abs])]
        neg = [('%g' % s) for s in S if s < 0]
        if neg:
            issues.append('|S11| 出现负值(%s) ⇒ 无效(典型: 不放 Port 改点源)' % ','.join(neg[:4]))
    if freqs_expected is not None and len(freqs_got or []) != freqs_expected:
        issues.append('频点数 %d != 期望 %d(多次出现只取到 1/3 个点)'
                      % (len(freqs_got or []), freqs_expected))
    if n_elems is not None and hmax is not None:
        tier = MESH_TIERS.get(round(float(hmax), 6))
        if tier and tier['elems'] and not (0.3 * tier['elems'] <= n_elems <= 3.0 * tier['elems']):
            issues.append('单元数 %d 与 hmax=%g 的档位参考 %d 偏离超 3 倍'
                          % (n_elems, hmax, tier['elems']))
    if n_elems is not None and n_elems > 170000 and one_proc_per_freq is not True:
        issues.append('细网格(%d 单元 > 17 万): 须一频点一进程, 否则 OOM(单进程上限约 1.3GB)'
                      % n_elems)
    return ('PASS' if not issues else 'SUSPECT'), issues


# ── CLI(供 quest 车道调用;MCP 的重活转派就是拼这条命令) ──────────────
# 用法: python comsol.py --name mycase --L 0.75 --H 0.15 --freqs 150,450,900
#           [--mesh 1] [--c0 340] [--eta 0.05] [--csv-out 路径]
# 成功判据: stdout 出现 SIMLIB_<NAME 大写>_DONE
def _cli():
    import argparse
    ap = argparse.ArgumentParser(description='simlib COMSOL 2D runner (quest lane)')
    ap.add_argument('--name', required=True)
    ap.add_argument('--L', type=float, default=0.75)
    ap.add_argument('--H', type=float, default=0.15)
    ap.add_argument('--freqs', default='150,450,900')
    ap.add_argument('--mesh', type=int, default=1)
    ap.add_argument('--c0', type=float, default=340.0)
    ap.add_argument('--eta', type=float, default=0.05)
    a = ap.parse_args()
    m = Comsol2D(a.name, a.L, a.H)
    m.material(c0=a.c0, eta=a.eta)
    m.freqs([float(f) for f in a.freqs.split(',') if f.strip()])
    m.mesh(auto_size=a.mesh)
    res = m.run()
    for f in res.freqs:
        try:
            A, B = res.fit_R(f)
            print('  fit f=%-6.0f |A|=%.4f |B|=%.4f |R|=%.4f'
                  % (f, abs(A), abs(B), abs(B / A) if abs(A) > 1e-14 else float('nan')), flush=True)
        except Exception as e:
            print('  fit f=%s 跳过(%s)' % (f, e), flush=True)


if __name__ == '__main__':
    _cli()
