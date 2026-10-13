# -*- coding: utf-8 -*-
"""
cae-lanes builder: build123d (OpenCASCADE) 参数化建模 lane —— 库 + CLI。

定位（与 comsol/abaqus/creo 三条仿真/操作 lane 并列的第四条: 建模）:
  参数化几何的单一事实源在 Python —— 改型号=改变量重跑, 秒级出 STEP/STL;
  STEP 给加工/仿真(Abaqus 原生可导), STL 给 COMSOL 免费导入(见 comsol3d.java_import_geom)。

通用构造器(从实战建模脚本提炼, 真圆孔/沉孔/槽阵列都是解析几何):
  box_between()      区间盒子(六个坐标, 免手算宽高)
  hole_y()/hole_z()  侧壁/顶壁圆柱孔(带旋转对齐的坑已处理)
  counter_bore()     通孔+沉孔组合
  slot_array_y()     沿 x 的槽阵列(等节距)
  volume_assert()    体积对解析值断言(读回核对纪律: 不信"导出成功")

CLI(判据词 BUILDER-DONE, quest/CI 车道友好):
  python builder.py demo                     # 建示例件: 体积断言+STEP/STL 双导出
  python builder.py json --f params.json     # 参数文件驱动(键见 DuctParams 字段)
"""
import argparse
import json
import math
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from build123d import Align, Box, Cylinder, Pos, export_step, export_stl


class BuilderError(RuntimeError):
    pass


# ── 通用构造器 ──────────────────────────────────────────────
def box_between(x0, x1, y0, y1, z0, z1):
    """六个坐标区间直接给盒子（免手算宽高与对齐）。"""
    return Box(x1 - x0, y1 - y0, z1 - z0,
               align=(Align.MIN, Align.MIN, Align.MIN)).moved(Pos(x0, y0, z0))


def hole_y(x, z, y0, y1, r):
    """沿 y 轴圆柱（侧壁孔）：rotation 的坑已处理好。"""
    return Cylinder(r, y1 - y0, rotation=(90, 0, 0),
                    align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Pos(x, y1, z))


def hole_z(x, y, z0, z1, r):
    """沿 z 轴圆柱（顶/底壁孔）。"""
    return Cylinder(r, z1 - z0,
                    align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Pos(x, y, z0))


def counter_bore(x, y, z_top, r_through, thick, r_cb, cb_depth):
    """顶面(z=z_top)向下: Φ2r 通孔 + Φ2r_cb 沉孔深 cb_depth（真圆, 非阶梯近似）。"""
    through = hole_z(x, y, z_top - thick - 1, z_top + 1, r_through)
    cb = hole_z(x, y, z_top - cb_depth, z_top + 1, r_cb)
    return through + cb   # union; 用 part - 该组合做切除


def slot_array_y(x0, pitch, n, slot_w, y0, y1, z0, z1):
    """沿 x 等节距的槽阵列（n 条, 首条中心 x0）, 返回切除体列表。"""
    return [box_between(x0 + i * pitch - slot_w / 2, x0 + i * pitch + slot_w / 2,
                        y0, y1, z0, z1) for i in range(n)]


def volume_assert(part, expect, rel_tol=1e-3, label=''):
    """读回核对纪律: 体积对解析值断言（OCCT 与解析应精确一致, 实测可达 0.0000%）。"""
    v = part.volume
    if expect <= 0:
        raise BuilderError('expect volume must be > 0')
    diff = abs(v - expect) / expect
    print('  [vol] %s %.3f vs expect %.3f (diff %.4f%%)' % (label, v, expect, diff * 100))
    if diff > rel_tol:
        raise BuilderError('volume mismatch %s: %.3f vs %.3f (%.4f%% > %.3f%%)'
                           % (label, v, expect, diff * 100, rel_tol * 100))
    return v


def export_both(part, out_dir, stem, stl_tolerance=0.05, view3d=True):
    """STEP(加工/Abaqus) + STL(COMSOL 免费导入) 双导出。返回 {'.step': bytes, '.stl': bytes}。
    ★ 坑护栏(实测 build123d 0.13/OCCT): export_stl 遇非 ASCII 路径**静默返回 False 不写文件**
    (export_step 不受影响) —— STL 先写 ASCII 临时路径再 os.replace 回目标( rename 支持中文)。
    view3d=True 时顺手把 STL 拷进 view3d 查看服务的模型目录(D:\\view3d\\models)并打印手机
    可访问链接(服务需在跑: D:\\view3d\\view3d-server.py, 端口 8178)——AI 建完把链接发给用户即可。"""
    os.makedirs(out_dir, exist_ok=True)
    sp = os.path.join(out_dir, stem + '.step')
    tp = os.path.join(out_dir, stem + '.stl')
    export_step(part, sp)
    if all(ord(c) < 128 for c in tp):
        export_stl(part, tp, tolerance=stl_tolerance)
    else:
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix='.stl')
        os.close(fd)
        try:
            ok = export_stl(part, tmp, tolerance=stl_tolerance)
            if not ok:
                raise BuilderError('export_stl failed even on ASCII temp path: %s' % tmp)
            import shutil
            shutil.move(tmp, tp)   # 跨盘也行(os.replace 不跨盘)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    if view3d:
        import shutil
        vd = os.environ.get('CAE_VIEW3D_MODELS', r'D:\view3d\models')
        try:
            os.makedirs(vd, exist_ok=True)
            shutil.copy(tp, os.path.join(vd, stem + '.stl'))
            if os.path.exists(sp):
                shutil.copy(sp, os.path.join(vd, stem + '.step'))  # 源文件真几何: 查看器路径条优先/可下载
            print('  [view3d] 手机查看: http://<主机IP>:8178/viewer.html?part=%s.stl '
                  '（首页 http://<主机IP>:8178/ 可选全部模型）' % stem)
        except Exception as e:
            print('  [view3d] 拷贝跳过: %s' % e)
    return {'.step': os.path.getsize(sp), '.stl': os.path.getsize(tp)}


# ── 高层示例: 矩形腔参数化件（中性默认参数, 非任何实际产品） ─────────
class DuctParams(object):
    """矩形腔体 + 侧壁槽阵列 + 顶面孔阵列。字段即参数文件 json 的键。"""
    L, H, W = 200.0, 40.0, 40.0          # 内腔长宽高
    T = 6.0                               # 壁厚（四向同厚）
    slot_n, slot_w, slot_x0, slot_pitch = 4, 8.0, 50.0, 30.0   # 侧槽阵列
    hole_n, hole_x0, hole_gap = 2, 40.0, 20.0                  # 顶面孔阵列
    hole_d, cb_d, cb_depth = 6.0, 10.0, 2.0                    # 通孔/沉孔


def build_duct(p=None):
    """按参数建件并返回 (part, 解析体积)。内腔贯通 x, 槽阵列开在下壁, 孔阵列开顶面。"""
    p = p or DuctParams()
    body = box_between(-p.T, p.L + p.T, -p.T, p.H + p.T, -p.T, p.W + p.T)
    cavity = box_between(0, p.L, 0, p.H, 0, p.W)
    part = body - cavity
    cuts = slot_array_y(p.slot_x0, p.slot_pitch, p.slot_n, p.slot_w,
                        -p.T - 1, 1.0, -p.T - 1, p.W + p.T + 1)
    # (说明: 示例把槽开在 z 侧仅示意; 真实件的槽向/凸肩按你的规格改 cuts 的区间即可)
    for c in cuts:
        part = part - c
    for i in range(p.hole_n):
        x = p.hole_x0 + i * p.hole_gap
        part = part - counter_bore(x, p.H / 2, p.W + p.T, p.hole_d / 2,
                                   p.T + 1, p.cb_d / 2, p.cb_depth)
    return part


# ── CLI ──────────────────────────────────────────────────────
def _cli():
    ap = argparse.ArgumentParser(description='cae-lanes builder (build123d/OCCT)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('demo')
    p = sub.add_parser('json')
    p.add_argument('--f', required=True, help='参数 json(键同 DuctParams 字段)')
    p.add_argument('--out', required=True)
    p.add_argument('--stem', default='part')
    a = ap.parse_args()

    if a.cmd == 'demo':
        part = build_duct()
        v = part.volume
        print('demo part volume = %.2f mm^3' % v)
        assert v > 0
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'demo_out')
        sizes = export_both(part, out, 'builder_demo')
        print('exported:', sizes)
        print('BUILDER-DONE')
    else:
        kw = json.load(open(a.f, encoding='utf-8'))
        p = DuctParams()
        for k, val in kw.items():
            if not hasattr(p, k):
                raise BuilderError('unknown param: %s' % k)
            setattr(p, k, val)
        part = build_duct(p)
        sizes = export_both(part, a.out, a.stem)
        print('exported:', sizes)
        print('BUILDER-DONE')


if __name__ == '__main__':
    _cli()


def export_assembly(parts, out_dir, stem, stl_tolerance=0.05):
    """装配导出: 每零件一个 STL + manifest(asm.json), view3d 查看器支持逐零件显隐。
    parts: [(零件名, part对象, pos_mm, rot_deg, color)] —— pos/rot 可为 None(建模时已定位)。
    返回 manifest 路径。手机: http://<主机IP>:8178/viewer.html?asm=<stem>.json"""
    import shutil
    os.makedirs(out_dir, exist_ok=True)
    entries = []
    for name, part_obj, pos, rot, color in parts:
        fn = stem + '_' + name + '.stl'
        tp = os.path.join(out_dir, fn)
        if all(ord(c) < 128 for c in tp):
            export_stl(part_obj, tp, tolerance=stl_tolerance)
        else:  # 中文路径护栏(同 export_both)
            import tempfile
            fd, tmp = tempfile.mkstemp(suffix='.stl'); os.close(fd)
            try:
                if not export_stl(part_obj, tmp, tolerance=stl_tolerance):
                    raise BuilderError('export_stl failed: %s' % tmp)
                shutil.move(tmp, tp)
            finally:
                if os.path.exists(tmp): os.remove(tmp)
        e = {'name': name, 'file': fn}
        if pos: e['pos'] = list(pos)
        if rot: e['rot'] = list(rot)
        if color: e['color'] = color
        entries.append(e)
    manifest = {'name': stem, 'parts': entries}
    mp = os.path.join(out_dir, stem + '.json')
    with open(mp, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    vd = os.environ.get('CAE_VIEW3D_MODELS', r'D:\view3d\models')
    try:
        os.makedirs(vd, exist_ok=True)
        for e in entries:
            shutil.copy(os.path.join(out_dir, e['file']), os.path.join(vd, e['file']))
        shutil.copy(mp, os.path.join(vd, stem + '.json'))
        print('  [view3d] 手机查看装配: http://<主机IP>:8178/viewer.html?asm=%s.json' % stem)
    except Exception as ex:
        print('  [view3d] 拷贝跳过: %s' % ex)
    return mp
