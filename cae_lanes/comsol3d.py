# -*- coding: utf-8 -*-
"""
simlib.comsol3d —— 3D 挤出管(W6 姿势): Port 入口 + S11 直读
规格: 手册 §9.1(run("wp1") 唯一必需条件 / dom3d 断言 / Extrude 默认 input) +
      §9.3(Port 参数名 p/kn/pamp, 缺 pamp=奇异矩阵, 没有 p_in)
姿势来源: aic_race/w6_3d.py(实测 dom3d=1+求解+S11) 与 ae1_geo3d.py(dom3d=2)
守卫: dom3d<1 拦截(§9.1: dom3d=0 仍可能"解出"垃圾)、上边界 x 单调(§5.11)、
      autoMeshSize 唯一旋钮(§5.8/§9.4)、唯一类名/文件名(§5.18)
"""
import os
import re
import subprocess
import sys
import time

from .comsol import (ComsolError, DEFAULT_WORKDIR, COMSOL_JAVAC, COMSOL_BATCH,
                     PLUGINS, _sanitize, _grep_int)

_JAVA_3D_TEMPLATE = r'''
import com.comsol.model.*;
import com.comsol.model.util.*;
class __CLASS__ {
  static void p(String s) { System.out.println("SL| " + s); }
  public static void main(String[] args) throws Exception {
    Model m = ModelUtil.create("__CLASS__");
    m.param().set("c0","__C0__[m/s]","c0");
    m.param().set("eta","__ETA__","eta");
    m.param().set("rho0","1.225[kg/m^3]","rho0");
    m.component().create("comp1", true);
    m.component("comp1").geom().create("geom1", 3);
    m.component("comp1").geom("geom1").create("wp1","WorkPlane");
    m.component("comp1").geom("geom1").feature("wp1").set("quickplane","xy");
    m.component("comp1").geom("geom1").feature("wp1").geom().create("pol","Polygon");
    m.component("comp1").geom("geom1").feature("wp1").geom().feature("pol").set("source","table");
    m.component("comp1").geom("geom1").feature("wp1").geom().feature("pol").set("type","solid");
    m.component("comp1").geom("geom1").feature("wp1").geom().feature("pol").set("table",
        new double[][]{
        __COORDS__
        });
    m.component("comp1").geom("geom1").run("wp1");
    p("wp1_ok");
    m.component("comp1").geom("geom1").create("ext1","Extrude");
    m.component("comp1").geom("geom1").feature("ext1").set("extrudefrom","workplane");
    m.component("comp1").geom("geom1").feature("ext1").set("workplane","wp1");
    m.component("comp1").geom("geom1").feature("ext1").set("distance", __DEPTH__);
    m.component("comp1").geom("geom1").run();
    int nd = m.component("comp1").geom("geom1").getNDomains();
    p("dom3d=" + nd);
    if (nd < 1) { p("SIMLIB_GEOM_EMPTY_3D"); return; }

    m.component("comp1").physics().create("acpr","PressureAcoustics","geom1");
    m.component("comp1").material().create("mat1","Common");
    m.component("comp1").material("mat1").materialType("nonSolid");
    m.component("comp1").material("mat1").propertyGroup("def").set("soundspeed","c0*(1+i*eta)");
    m.component("comp1").material("mat1").propertyGroup("def").set("density","rho0");
    m.component("comp1").material("mat1").selection().all();

    m.component("comp1").selection().create("selin","Box");
    m.component("comp1").selection("selin").geom("geom1",2);
    m.component("comp1").selection("selin").set("entitydim",2);
    m.component("comp1").selection("selin").set("xmin","-0.002");
    m.component("comp1").selection("selin").set("xmax","0.002");
    m.component("comp1").selection("selin").set("ymin","-0.001");
    m.component("comp1").selection("selin").set("ymax","1");
    m.component("comp1").selection("selin").set("zmin","-0.001");
    m.component("comp1").selection("selin").set("zmax","1");
    m.component("comp1").selection("selin").set("condition","inside");
    m.component("comp1").selection().create("rest","Complement");
    m.component("comp1").selection("rest").geom("geom1",2);
    m.component("comp1").selection("rest").set("entitydim",2);
    m.component("comp1").selection("rest").set("input", new String[]{"selin"});

    m.component("comp1").physics("acpr").create("port1","Port",2);
    m.component("comp1").physics("acpr").feature("port1").selection().named("selin");
    m.component("comp1").physics("acpr").feature("port1").set("PortType","UserDefined");
    m.component("comp1").physics("acpr").feature("port1").set("p","1");
    m.component("comp1").physics("acpr").feature("port1").set("kn","acpr.k");
    m.component("comp1").physics("acpr").feature("port1").set("pamp","1");
    m.component("comp1").physics("acpr").feature("port1").set("PortExcitation","on");
    m.component("comp1").physics("acpr").create("shd1","SoundHard",2);
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

    m.result().export().create("es11", "Data");
    m.result().export("es11").set("expr", new String[]{"acpr.S11"});
    m.result().export("es11").set("filename", "__S11__");
    m.result().export("es11").run();
    p("SL_CLASS_DONE");
  }
}
'''


class Comsol3DResult(object):
    freqs = []
    S11 = {}    # freq -> |S11|
    S11c = {}   # freq -> complex S11
    _meta = None


class Comsol3D(object):
    """3D 挤出管: xy 闭合轮廓沿 z 挤出; Port 入口直读 acpr.S11(§9.3)。
    profile=[(x,y),...] 闭合多边形(上边界沿 x 单调+平底); depth=挤出深度(m)。
    便捷: Comsol3D.straight(L,H,depth) / Comsol3D.stepped(segs,depth)。"""

    def __init__(self, name, profile, depth, workdir=DEFAULT_WORKDIR, srcdir=None):
        self.name = _sanitize(name)
        pts = [(float(x), float(y)) for x, y in profile]
        if len(pts) < 3:
            raise ComsolError('profile 至少 3 点')
        cl = [pts[0]]
        for pt in pts[1:]:
            if abs(pt[0] - cl[-1][0]) > 1e-12 or abs(pt[1] - cl[-1][1]) > 1e-12:
                cl.append(pt)
        if abs(cl[0][0] - cl[-1][0]) > 1e-9 or abs(cl[0][1] - cl[-1][1]) > 1e-9:
            cl.append(cl[0])
        top = [p for p in cl if p[1] > 1e-12]
        bad = [i for i in range(len(top) - 1) if top[i][0] > top[i + 1][0] + 1e-12]
        if bad:
            raise ComsolError('profile 上边界 x 必须单调不减(§5.11), 违反 i=%d' % bad[0])
        self.profile = cl
        self.depth = float(depth)
        if self.depth <= 0:
            raise ComsolError('depth 必须为正')
        self._mat = dict(c0=340.0, eta=0.05, rho0=1.225)
        self._freqs = []
        self._meshn = 2
        self.workdir = workdir
        self.srcdir = srcdir or os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'comsol')
        os.makedirs(self.workdir, exist_ok=True)
        os.makedirs(self.srcdir, exist_ok=True)

    @classmethod
    def straight(cls, name, L, H, depth, **kw):
        """直管(矩形轮廓)。已知答案: 刚性末端 |S11|=exp(-2*alpha*L)。"""
        return cls(name, [(0, 0), (0, float(H)), (float(L), float(H)), (float(L), 0)],
                   depth, **kw)

    @classmethod
    def stepped(cls, name, segs, depth, **kw):
        """阶梯轮廓: segs=[(dx,h),...](W6 构造法), 顶边界沿 x 单调。"""
        x = 0.0
        hmax = max(h for _, h in segs)
        pts = [(0.0, 0.0), (0.0, float(hmax))]
        for dx, h in segs:
            x += dx
            pts.append((x, float(h)))
        pts.append((x, 0.0))
        return cls(name, pts, depth, **kw)

    def material(self, c0=340.0, eta=0.05, rho0=1.225):
        self._mat = dict(c0=float(c0), eta=float(eta), rho0=float(rho0))
        return self

    def freqs(self, fs):
        fs = [float(f) for f in fs]
        if not fs or any(f <= 0 for f in fs):
            raise ComsolError('freqs 非空且为正')
        self._freqs = fs
        return self

    def mesh(self, auto_size=2):
        if not (-1 <= int(auto_size) <= 5):
            raise ComsolError('auto_size 建议 -1~5, N 越小越细(§5.9)')
        self._meshn = int(auto_size)
        return self

    def run(self, timeout_batch=7200, timeout_javac=300):
        if not self._freqs:
            raise ComsolError('先调 freqs()')
        runid = '%s_%s' % (self.name, time.strftime('%H%M%S'))
        cls = _sanitize(runid)
        s11_path = os.path.join(self.workdir, cls + '_s11.txt')
        jf = os.path.join(self.srcdir, cls + '.java')
        coords = ',\n        '.join('{%.6f, %.6f}' % (a, b) for a, b in self.profile)
        java = (_JAVA_3D_TEMPLATE
                .replace('__CLASS__', cls)
                .replace('__COORDS__', coords)
                .replace('__DEPTH__', '%.4f' % self.depth)
                .replace('__C0__', '%.1f' % self._mat['c0'])
                .replace('__ETA__', '%.4f' % self._mat['eta'])
                .replace('__MESHN__', str(self._meshn))
                .replace('__S11__', s11_path.replace('\\', '\\\\'))
                .replace('__PLIST__', ','.join(str(int(f)) if f == int(f) else str(f)
                                                for f in self._freqs)))
        with open(jf, 'w', encoding='utf-8') as fh:
            fh.write(java)
        t0 = time.time()
        pr = subprocess.run([COMSOL_JAVAC, '-proc:none', '-cp', PLUGINS,
                             '-d', self.workdir, jf],
                            capture_output=True, text=True,
                            encoding='utf-8', errors='replace',
                            timeout=timeout_javac, cwd=self.workdir)
        if pr.returncode != 0:
            raise ComsolError('javac 失败:\n' + '\n'.join(
                (pr.stderr or pr.stdout or '').splitlines()[-8:]))
        pr2 = subprocess.run([COMSOL_BATCH, '-inputfile',
                              os.path.join(self.workdir, cls + '.class'),
                              '-methodcall', 'main'],
                             capture_output=True, text=True,
                             encoding='utf-8', errors='replace',
                             timeout=timeout_batch, cwd=self.workdir)
        lines = [L.strip() for L in (pr2.stdout or '').splitlines() if 'SL|' in L]
        for L in lines:
            print('  ' + L, flush=True)
        if any('GEOM_EMPTY_3D' in L for L in lines):
            raise ComsolError('dom3d<1(§9.1: dom3d=0 仍可能"解出"垃圾, 已拦截)')
        if any('SIMLIB_MESH_EMPTY' in L for L in lines):
            raise ComsolError('网格 0 单元(§5.8)')
        if not any('SL_CLASS_DONE' in L for L in lines):
            raise ComsolError('comsolbatch 未到 SL_CLASS_DONE (rc=%s, %.0fs)\n%s'
                              % (pr2.returncode, time.time() - t0,
                                 '\n'.join((pr2.stderr or pr2.stdout or '').splitlines()[-12:])))
        if not os.path.exists(s11_path):
            raise ComsolError('S11 文本未生成: %s' % s11_path)
        res = Comsol3DResult()
        res._meta = dict(name=self.name, runid=runid, s11=s11_path,
                         elems=_grep_int(lines, r'mesh elems=(\d+)'),
                         seconds=time.time() - t0, model=self)
        with open(s11_path, encoding='utf-8', errors='replace') as fh:
            for L in fh:
                L = L.strip()
                if not L or L.startswith('%'):
                    continue
                pp = [q for q in L.split() if q]
                if len(pp) >= 3 + len(self._freqs):
                    for i, f in enumerate(self._freqs):
                        try:
                            c = complex(pp[3 + i].replace('i', 'j').replace(' ', ''))
                            res.S11c[f] = c
                            res.S11[f] = abs(c)
                        except Exception:
                            pass
                    break
        res.freqs = list(res.S11c.keys())
        if not res.freqs:
            raise ComsolError('S11 文本解析失败: %s' % s11_path)
        print('  [simlib3d] %s: %s' % (runid, {('%g' % f): round(v, 6)
                                               for f, v in res.S11.items()}), flush=True)
        print('SIMLIB3D_%s_DONE' % self.name.upper(), flush=True)
        return res


# == v1.3 (2026-10-12): import of external geometry (build123d/OCCT -> COMSOL) ==
def java_import_geom(mesh_file, geom='geom1', comp='comp1', unit='mm'):
    """Generate a Java code section for importing external geometry files (to be embedded into a custom template).
    License boundary (locally tested, 2026-10-12):
      - STEP/IGES -> requires CAD Import Module, not available on this machine (ImportCAD reports unknown operation)
      - STL/PLY/3MF -> Import feature, free and usable (tested: domains=1, mesh normal)
    => After building the model with build123d, use export_stl(tolerance<=0.05) to convert to STL then import.
    Note that STL is a triangular approximation: circular holes become polygonal facets, precision is controlled by tolerance;
    analytical geometry should still be built directly via API with priority.
    Tested examples: aic_race/step_imp_test_build.py + step_imp_test_comsol.py."""
    mf = str(mesh_file).replace(chr(92), chr(92) * 2)
    return (
        'm.component("%s").geom().create("%s", 3);' + chr(10) +
        'm.component("%s").geom("%s").lengthUnit("%s");' + chr(10) +
        'm.component("%s").geom("%s").create("imp1", "Import");' + chr(10) +
        'm.component("%s").geom("%s").feature("imp1").set("filename", "%s");' + chr(10) +
        'try { m.component("%s").geom("%s").feature("imp1").set("form", "solids"); } catch (Throwable t) {}' + chr(10) +
        'm.component("%s").geom("%s").run();' + chr(10)
    ) % (comp, geom, comp, geom, unit, comp, geom, comp, geom, mf, comp, geom, comp, geom)
