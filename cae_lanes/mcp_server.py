# -*- coding: utf-8 -*-
"""
simlib-mcp: COMSOL/ABAQUS 已验证通路的薄 MCP 壳(stdio, 纯标准库, 零依赖)
架构(2026-10-07 定稿): 轻操作直答, 重操作只造命令转派 quest 车道——不在本进程跑求解。

tools:
  comsol_k          波数(正分支)计算
  comsol_read_csv   解析 Data export csv, 逐频统计
  comsol_solve_cmd  生成 quest_run 命令(经 CLI, 重活不在此执行)
  comsol_eval_snippet  生成取数 Java 段(EvalGlobal+stdout, 手册 §8.2 唯一可用路径)
  comsol_eig        黏热特征值 → f/衰减/Q(§8.6 口径)
  comsol_health     取数前自检(§10.4 六条, A==1 病态/负 S11/频点数/单元数档位/OOM)
  abaqus_check      py2.7 静态检查(flush=/非 ASCII print)
  abaqus_disk       运行根磁盘护栏
  abaqus_cmd        四段式命令构建(gen/run/extract/analyze)
  judge_log         按日志文本判定(rc 不可信纪律)
  mesh_refine       PanaPara 并行四面体网格细化(plan/run/convert, 2026-10-25)
  mesh_check        .inp 节点/单元计数与 ×8^n 核对
"""
import json
import os
import sys
try:
    from . import config as _cfg
except ImportError:
    import config as _cfg
WS_FALLBACK = _cfg.ABAQUS_WS_ROOT or '.'

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stdin.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

PROTOCOL = '2024-11-05'
SERVER_INFO = {'name': 'simlib-mcp', 'version': '0.2.0'}

TOOLS = [
    {
        'name': 'comsol_k',
        'description': 'COMSOL 数据反推专用波数 k=2*pi*f/(c0*(1+i*eta))(正分支)。'
                       '不要用 FEM 侧的 k 拟合 COMSOL 数据(共轭分支事故)。',
        'inputSchema': {'type': 'object', 'properties': {
            'f': {'type': 'number', 'description': '频率 Hz'},
            'c0': {'type': 'number', 'default': 340.0},
            'eta': {'type': 'number', 'default': 0.05}},
            'required': ['f']},
    },
    {
        'name': 'comsol_read_csv',
        'description': '解析 COMSOL Data export csv(表头驱动, 2 参数列+每频点 4 列), '
                       '返回频序/行数/逐频 |p| 统计与 x,y 范围。',
        'inputSchema': {'type': 'object', 'properties': {
            'path': {'type': 'string'}}, 'required': ['path']},
    },
    {
        'name': 'comsol_solve_cmd',
        'description': '生成 2D 无支管求解的 quest_run 命令(重活转派 quest, 本工具不执行)。'
                       '返回 cmd/cwd/success 判据词。',
        'inputSchema': {'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'L': {'type': 'number', 'default': 0.75},
            'H': {'type': 'number', 'default': 0.15},
            'freqs': {'type': 'string', 'description': '逗号分隔', 'default': '150,450,900'},
            'mesh': {'type': 'integer', 'default': 1, 'description': 'N 越小越细'},
            'c0': {'type': 'number', 'default': 340.0},
            'eta': {'type': 'number', 'default': 0.05},
            'python': {'type': 'string', 'default': ''},
            'cwd': {'type': 'string', 'default': ''}},
            'required': ['name']},
    },
    {
        'name': 'comsol_eval_snippet',
        'description': '生成 COMSOL 结果取数 Java 段(手册 §8.2 唯一确认可用路径, '
                       'numerical().create(tag,"EvalGlobal") + getReal() + stdout)。'
                       '数值只走 stdout(SecurityManager 拒 Java 写盘); 每行<=20 个数'
                       '(quest 日志 ~300 字符截断会静默丢数据)。死路: numeric() 不存在/'
                       'mph 里不能 create("Table")/getEigenvalues 不存在。',
        'inputSchema': {'type': 'object', 'properties': {
            'exprs': {'type': 'array', 'items': {'type': 'string'},
                      'description': '表达式列表, 如 ["abs(ta.S11)"] — 物理场 tag 是 ta 不是 acpr'},
            'tag': {'type': 'string', 'default': 'ev1'},
            'data': {'type': 'string', 'default': 'dset1'}},
            'required': ['exprs']},
    },
    {
        'name': 'comsol_eig',
        'description': '黏热特征值口径换算(§8.6): f=|Im|/2pi(曾误用 |Im| 高估 2pi 倍), '
                       '衰减=-|Re|(1/s), Q=pi*f/|Re|。硬壁 TWA 无数值耗散, 可作零耗散基线。',
        'inputSchema': {'type': 'object', 'properties': {
            're': {'type': 'array', 'items': {'type': 'number'}},
            'im': {'type': 'array', 'items': {'type': 'number'}}},
            'required': ['re', 'im']},
    },
    {
        'name': 'comsol_health',
        'description': '取数前自检(§10.4 六条): A 恰为 1.0000=病态作废/|S11| 负值=无效/'
                       '频点数不足/单元数与 hmax 档位偏离/细网格(>17万)须一频点一进程。'
                       'SUSPECT 的数字不得作为物理结论引用; 报绝对 A 必标 hmax。',
        'inputSchema': {'type': 'object', 'properties': {
            'freqs_expected': {'type': 'integer'},
            'freqs_got': {'type': 'array', 'items': {'type': 'number'}},
            's11': {'type': 'array', 'items': {'type': 'number'},
                    'description': '各频点 |S11|'},
            'a': {'type': 'array', 'items': {'type': 'number'},
                  'description': '各频点 A=1-|S11|^2(或频均 A)'},
            'n_elems': {'type': 'integer'},
            'hmax': {'type': 'number'},
            'solve_ok': {'type': 'boolean', 'default': True},
            'one_proc_per_freq': {'type': 'boolean',
                                  'description': '细网格是否一频点一进程(未知可不传)'}},
            'required': ['freqs_expected', 'freqs_got']},
    },
    {
        'name': 'creo_cmd',
        'description': '构建 Creo 操作命令（重活转派 quest_run, 判据词已内置）。op∈ensure/smoke/open/'
                       'export-step/params-set/dims-set/mass。Creo 经 creoson(9056)+J-Link 连 GUI 实例; '
                       '参数化模板姿势: open→dims-set(改参+regen)→mass(体积断言)→export-step。'
                       '注意: 模板须预建尺寸参数; 导出主名≤31字符(库内置护栏)。',
        'inputSchema': {'type': 'object', 'properties': {
            'op': {'type': 'string', 'enum': ['ensure', 'smoke', 'open', 'export-step',
                                              'params-set', 'dims-set', 'mass']},
            'file': {'type': 'string', 'description': 'op=open: 纯文件名(x.prt)'},
            'dirname': {'type': 'string', 'description': 'op=open/export-step: 目录'},
            'stem': {'type': 'string', 'description': 'op=export-step: 导出主名(≤31字符)'},
            'kv': {'type': 'string', 'description': "op=params-set/dims-set: 'K=V,K=V' 形式"},
            'regen': {'type': 'boolean', 'default': True}},
            'required': ['op']},
    },
    {
        'name': 'creo_status',
        'description': '在线秒查 creoson(9056)/Creo 存活（不拉起、不改状态）。重操作用 creo_cmd 转派。',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'abaqus_check',
        'description': 'py2.7 静态检查: extract 侧脚本禁 flush= 与 print 内非 ASCII。',
        'inputSchema': {'type': 'object', 'properties': {
            'script': {'type': 'string', 'description': '绝对或相对 abaqus_batch 的脚本名'},
            'ws_root': {'type': 'string',
                        'default': ''}},
            'required': ['script']},
    },
    {
        'name': 'abaqus_disk',
        'description': '检查 ABAQUS 运行根(D:\\temp\\abaqus_batch 所在盘)可用空间。',
        'inputSchema': {'type': 'object', 'properties': {
            'min_free_gb': {'type': 'number', 'default': 20.0}}},
    },
    {
        'name': 'abaqus_cmd',
        'description': '构建四段式命令(gen/run/extract/analyze)。返回 RunSpec(cmd/cwd/'
                       'success_keywords/quest 提示); run 段必须经 quest 派发(沙箱 WMI 必死)。',
        'inputSchema': {'type': 'object', 'properties': {
            'stage': {'type': 'string', 'enum': ['gen', 'run', 'extract', 'analyze']},
            'runner': {'type': 'string', 'description': 'gen/run 段脚本名, 如 run_palm_geom.py'},
            'harness': {'type': 'string', 'description': 'analyze 段 ml/ 下的 harness 名'},
            'tags': {'type': 'string', 'description': '逗号分隔, 不要带引号'},
            'slots': {'type': 'integer'}, 'cpus': {'type': 'integer'},
            'mem_floor_gb': {'type': 'integer'},
            'extract_script': {'type': 'string', 'default': 'extract_fields.py'},
            'args': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['stage']},
    },
    {
        'name': 'view3d_drop',
        'description': '投递仿真产物到手机 3D 查看器（复制进 view3d/inbox, autodrop 自动转换, '
                       '手机刷新即看）。支持: .odb→动画包(分钟级, abaqus 后台导出) / .stp/.step→stl / '
                       '.vtk/.vtu 同名_N 序列→动画包(COMSOL 多时间步) / .bdf/.nas→stl / '
                       '.stl/.ply/.glb 直入。path 支持 glob 通配(序列传 demo_*.vtk)与目录; '
                       'alias 仅单文件时换名。在线执行(本地复制秒级); 服务须在跑(8178), '
                       'odb 类投完用 view3d_list 查进度。',
        'inputSchema': {'type': 'object', 'properties': {
            'path': {'type': 'string', 'description': '源文件/glob/目录 绝对路径'},
            'alias': {'type': 'string', 'description': '入库显示名(含扩展名, 仅单文件)'}},
            'required': ['path']},
    },
    {
        'name': 'view3d_list',
        'description': '查看器全景: 在途转换(inbox 未转出, 含 vtk 序列分组与帧数) / '
                       '已入库模型(大小/是否动画包/溯源源文件) / autodrop 最近失败。'
                       '返回手机访问 URL。pattern 对模型名做包含过滤。',
        'inputSchema': {'type': 'object', 'properties': {
            'pattern': {'type': 'string', 'default': ''}},
            'required': []},
    },
    {
        'name': 'view3d_clean',
        'description': '删除查看器条目: models 产物 + inbox 源 + 溯源记录一起删 '
                       '（只删一边 autodrop 会重新转出来）。confirm=false 干跑列清单, '
                       'true 执行。name 给 models 里的产物名或源文件 stem。',
        'inputSchema': {'type': 'object', 'properties': {
            'name': {'type': 'string'},
            'confirm': {'type': 'boolean', 'default': False}},
            'required': ['name']},
    },
    {
        'name': 'mesh_refine',
        'description': 'PanaParaMesher 并行四面体网格细化(parallel_tetmesh, 大连理工 LGPL): '
                       '粗网格 .inp → METIS 分区 + MS-MPI 并行 h-refinement(每级单元×8) → '
                       '分区 .inp(界面节点已同步, 无需合并)。粗网格用 HyperMesh/Gmsh/Patran 等导出。'
                       'mode=plan(默认): 校验+估规模+写 ctrl.json, 返回 quest_run 命令(重活转派); '
                       'mode=run: 小网格(输出≤200万单元)在线直跑含转换与校验; '
                       'mode=convert: quest 跑完后把分区二进制(*_rst_.refined_json)转可视化 part<i>.inp。'
                       '工作区强制 ASCII(默认 D:/panamesh/<stem>/), 中文路径源文件自动拷入。'
                       'numSubdivision 每加 1 单元×8; 64GB 单机建议输出≤1.5亿。',
        'inputSchema': {'type': 'object', 'properties': {
            'inp_file': {'type': 'string', 'description': '粗网格 .inp 绝对路径(C3D4 四面体)'},
            'mode': {'type': 'string', 'enum': ['plan', 'run', 'convert'], 'default': 'plan'},
            'out_dir': {'type': 'string', 'description': '工作区(ASCII); 缺省 D:/panamesh/<stem>/'},
            'num_subdivision': {'type': 'integer', 'default': 1, 'description': '细化级数, 单元×8^n'},
            'num_partition': {'type': 'integer', 'description': '分区数(≥numCore, 多分区降内存峰值)'},
            'num_core': {'type': 'integer', 'description': 'MPI 进程数; 缺省 min(8, cpu/2)'},
            'num_smooth': {'type': 'integer', 'default': 0, 'description': '光顺迭代次数'},
            'par_metis': {'type': 'integer', 'default': 0, 'description': '1=ParMETIS 并行分区(大规模)'},
            'output_int_type': {'type': 'integer', 'default': 0,
                                'description': '0=全局唯一节点ID(可视化友好); 1=分区局部ID(超大规模)'},
            'export_inp': {'type': 'integer', 'default': 1}},
            'required': ['inp_file']},
    },
    {
        'name': 'mesh_check',
        'description': '.inp 网格计数: 数 *NODE/*ELEMENT 行, 支持单文件/目录/glob 通配'
                       '(part*.inp 分区序列)。可选 expect_elements 对总量核对(±5%)——'
                       '细化后名义总量 = 粗网格单元数 × 8^numSubdivision。',
        'inputSchema': {'type': 'object', 'properties': {
            'paths': {'type': 'array', 'items': {'type': 'string'},
                      'description': '.inp 路径或 glob 列表'},
            'expect_elements': {'type': 'integer'}},
            'required': ['paths']},
    },
    {
        'name': 'judge_log',
        'description': '按日志文本判定成功/失败(abaqus rc 不可信纪律): 命中关键词=ok; '
                       '出现 Abaqus Error/Traceback/getWMI=failed; 其余 unknown。',
        'inputSchema': {'type': 'object', 'properties': {
            'text': {'type': 'string'},
            'keywords': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['text', 'keywords']},
    },
    {
        'name': 'tikz_flow',
        'description': '科研流程图(TikZ 学术印刷风): 论文场景首选——与 pdflatex/xelatex 正文同字体同排版。'
                       '调用方只描述结构(节点+边), 样式库模板承担全部审美(低饱和配色/衬线/圆角/回环虚线)。'
                       '竖排主链+回环/越级侧绕自动布局; 产出 tex+pdf(+png)。'
                       '流程图禁用 matplotlib 裸画(无设计系统必丑); 快图/讨论可走 mermaid, 精图走 HTML 截图。',
        'inputSchema': {'type': 'object', 'properties': {
            'nodes': {'type': 'array', 'description': '按主链顺序; 每项 {id:ASCII标识符, kind:data|model|proc|gate|done, title, desc?}',
                      'items': {'type': 'object'}},
            'edges': {'type': 'array', 'description': '每项 {from, to, label?, style?:flow|back|skip}; 相邻=直箭头, to在前=回环虚线, 越级=侧绕',
                      'items': {'type': 'object'}},
            'out_dir': {'type': 'string', 'description': '产物目录(绝对路径)'},
            'name': {'type': 'string', 'default': 'flow', 'description': '产物文件名 stem'}},
            'required': ['nodes', 'edges', 'out_dir']},
    },
    {
        'name': 'render_mermaid',
        'description': 'mermaid 源码直接渲染成 PNG(快图/结构讨论链): 本地 mermaid.min.js + '
                       'playwright(系统 Edge, CDP 通道, 不受 Edge 常驻进程劫持) + 按 svg 内容自适应截图(无白边)。'
                       '语法字符要转义: |R| 写 &#124;R&#124;(竖线是 mermaid 语法字符); '
                       '配色用源码内 classDef, 本工具不再改样式。宽度按内容自适应, width/height 只是画布上限。',
        'inputSchema': {'type': 'object', 'properties': {
            'code': {'type': 'string', 'description': 'mermaid 源码(flowchart/sequence/... 任意图型)'},
            'out_png': {'type': 'string', 'description': '输出 PNG 绝对路径'},
            'width': {'type': 'integer', 'default': 1600},
            'height': {'type': 'integer', 'default': 1000}},
            'required': ['code', 'out_png']},
    },
]


def _t(name, **kw):
    return {'name': name, **kw}


def handle_tool_call(name, args):
    if name == 'comsol_k':
        from comsol import k_comsol
        k = k_comsol(float(args['f']), float(args.get('c0', 340.0)), float(args.get('eta', 0.05)))
        return 'k = %.8f%+.8fj\n|k|=%.8f  Im(k)=%+.8f (Im<0, 衰减系数 alpha=-Im(k))' % (
            k.real, k.imag, abs(k), k.imag)
    if name == 'comsol_read_csv':
        from comsol import read_comsol_csv
        res = read_comsol_csv(args['path'])
        lines = ['freqs=%s rows=%d' % ([('%g' % f) for f in res.freqs], res.rows)]
        for f in res.freqs:
            data = res.field(f)
            ps = [abs(p) for _, _, p in data]
            xs = [x for x, _, _ in data]
            lines.append('f=%-8g |p| min/mean/max = %.6f/%.6f/%.6f  x∈[%.3f,%.3f]'
                         % (f, min(ps), sum(ps) / len(ps), max(ps), min(xs), max(xs)))
        return '\n'.join(lines)
    if name == 'comsol_solve_cmd':
        nm = str(args['name'])
        py = args.get('python') or _cfg.ABAQUS_PY3
        cwd = args.get('cwd') or WS_FALLBACK
        freqs = str(args.get('freqs', '150,450,900'))
        # 直接形态: 用 -m 调 CLI, 路径参数化(quest 预检只认 ASCII 相对路径)
        cli_arg = ('--name %s --L %.4f --H %.4f --freqs %s --mesh %d --c0 %.1f --eta %.4f'
                   % (nm, float(args.get('L', 0.75)), float(args.get('H', 0.15)),
                      freqs, int(args.get('mesh', 1)), float(args.get('c0', 340.0)),
                      float(args.get('eta', 0.05))))
        real_cmd = ('%s simlib_runner.py --module simlib.comsol -- %s' % (py, cli_arg))
        return json.dumps({
            'cmd': real_cmd, 'cwd': cwd,
            'success_keyword': 'SIMLIB_%s_DONE' % nm.upper(),
            'note': '经 quest_run 派发; simlib_runner.py 在工作区根(ASCII 相对路径, 预检友好)',
        }, ensure_ascii=False, indent=2)
    if name == 'comsol_eval_snippet':
        from comsol import java_eval_global
        return java_eval_global(list(args['exprs']),
                                tag=str(args.get('tag', 'ev1')),
                                data=str(args.get('data', 'dset1')))
    if name == 'comsol_eig':
        from comsol import eig_freq_q
        lams = [complex(r, i) for r, i in zip(args['re'], args['im'])]
        rows = eig_freq_q(lams)
        return '\n'.join('#%d  f=%12.2f Hz  decay=%10.4f 1/s  Q=%10.2f' % (n, *row)
                         for n, row in enumerate(rows))
    if name == 'comsol_health':
        from comsol import health_check
        verdict, issues = health_check(
            freqs_expected=int(args['freqs_expected']),
            freqs_got=args.get('freqs_got') or [],
            S11_abs=args.get('s11'), A=args.get('a'),
            n_elems=args.get('n_elems'), hmax=args.get('hmax'),
            solve_ok=bool(args.get('solve_ok', True)),
            one_proc_per_freq=args.get('one_proc_per_freq'))
        return ('%s%s' % (verdict, '' if not issues else '\n' + '\n'.join('- ' + i for i in issues)))
    if name == 'creo_cmd':
        op = str(args['op'])
        py = _cfg.ABAQUS_PY3
        base = py + ' simlib/creo.py'
        keywords = {'ensure': 'CREO-ENSURE-DONE', 'smoke': 'CREO-SMOKE-DONE',
                    'open': 'CREO-OPEN-DONE', 'export-step': 'CREO-EXPORT-DONE',
                    'params-set': 'CREO-SET-DONE', 'dims-set': 'CREO-SET-DONE',
                    'mass': 'CREO-MASS-DONE'}[op]
        extra = ''
        if op == 'open':
            extra = ' open --f %s --d %s' % (args['file'], args['dirname'])
        elif op == 'export-step':
            extra = ' export-step --n %s --d %s' % (args['stem'], args['dirname'])
        elif op in ('params-set', 'dims-set'):
            extra = ' %s --set "%s"%s' % ('params' if op == 'params-set' else 'dims',
                                          args['kv'], ' --regen' if args.get('regen', True) else '')
        elif op == 'mass':
            extra = ' mass'
        return json.dumps({
            'cmd': base + extra, 'cwd': WS_FALLBACK,
            'success_keyword': keywords,
            'note': '经 quest_run 派发; 重活不在线执行。CLI 相对路径预检友好。',
        }, ensure_ascii=False, indent=2)
    if name == 'creo_status':
        import socket as _s
        out = []
        sk = _s.socket(); sk.settimeout(1.5)
        try:
            sk.connect(('127.0.0.1', 9056)); out.append('creoson(9056): UP')
        except Exception:
            out.append('creoson(9056): DOWN（用 creo_cmd op=ensure 拉起）')
        finally:
            sk.close()
        return '\n'.join(out)
    if name == 'abaqus_check':
        from abaqus import AbaqusBatch
        ab = AbaqusBatch(ws_root=args.get('ws_root') or WS_FALLBACK)
        issues = ab.py27_static_check(args['script'])
        return ('PASS: 0 问题' if not issues
                else 'FAIL(%d):\n' % len(issues) + '\n'.join(issues[:20]))
    if name == 'abaqus_disk':
        from abaqus import AbaqusBatch
        ab = AbaqusBatch()
        ok, gb = ab.disk_ok(float(args.get('min_free_gb', 20.0)))
        return '可用 %.1f GB (门槛 %.1f): %s' % (gb, float(args.get('min_free_gb', 20.0)),
                                                 'OK' if ok else '不足, 先清理(odb 150-330MB/卡)')
    if name == 'abaqus_cmd':
        from abaqus import AbaqusBatch, RunSpec
        ab = AbaqusBatch()
        stage = args['stage']
        tags = args.get('tags') or None
        if stage == 'gen':
            spec = ab.build_gen(args.get('runner') or 'gen_palm_geom.py', args.get('args'))
        elif stage == 'run':
            spec = ab.build_run(args.get('runner') or 'run_palm_geom.py', tags=tags,
                                slots=args.get('slots'), cpus=args.get('cpus'),
                                mem_floor_gb=args.get('mem_floor_gb'))
        elif stage == 'extract':
            spec = ab.build_extract(tags=tags,
                                    script=args.get('extract_script', 'extract_fields.py'))
        else:
            spec = ab.build_analyze(args['harness'], args.get('args'))
        d = dict(spec)
        d['quest_hint'] = spec.quest_hint
        return json.dumps(d, ensure_ascii=False, indent=2)
    if name == 'view3d_drop':
        from view3d import drop
        return json.dumps(drop(args['path'], args.get('alias')),
                          ensure_ascii=False, indent=2)
    if name == 'view3d_list':
        from view3d import status
        return json.dumps(status(args.get('pattern') or None),
                          ensure_ascii=False, indent=2)
    if name == 'view3d_clean':
        from view3d import clean
        return json.dumps(clean(args['name'], bool(args.get('confirm', False))),
                          ensure_ascii=False, indent=2)
    if name == 'mesh_refine':
        from panamesh import plan_refine, run_refine, convert_results
        mode = str(args.get('mode', 'plan'))
        if mode == 'convert':
            parts = convert_results(args['out_dir'])
            return json.dumps({'ok': True, 'output_dir': args['out_dir'],
                               'partitions': len(parts),
                               'total_elements': sum(p['elements'] for p in parts),
                               'total_nodes': sum(p['nodes'] for p in parts),
                               'per_partition': parts},
                              ensure_ascii=False, indent=2)
        fn = run_refine if mode == 'run' else plan_refine
        r = fn(args['inp_file'], args.get('out_dir'),
               num_subdivision=int(args.get('num_subdivision', 1)),
               num_partition=args.get('num_partition'),
               num_core=args.get('num_core'),
               num_smooth=int(args.get('num_smooth', 0)),
               par_metis=int(args.get('par_metis', 0)),
               output_int_type=int(args.get('output_int_type', 0)),
               export_inp=int(args.get('export_inp', 1)))
        return json.dumps(r, ensure_ascii=False, indent=2)
    if name == 'mesh_check':
        from panamesh import check
        return json.dumps(check(args['paths'], args.get('expect_elements')),
                          ensure_ascii=False, indent=2)
    if name == 'judge_log':
        from abaqus import AbaqusBatch
        v, found = AbaqusBatch.judge_log(args['text'], args['keywords'])
        return 'verdict=%s keywords_found=%s' % (v, found or [])
    if name == 'tikz_flow':
        from flow_tikz import build_flow
        r = build_flow(args['nodes'], args['edges'], args['out_dir'],
                       args.get('name', 'flow'))
        return 'FLOW-OK ' + json.dumps(r, ensure_ascii=False)
    if name == 'render_mermaid':
        from mermaid_render import render_png
        p = render_png(args['code'], args['out_png'],
                       int(args.get('width', 1600)), int(args.get('height', 1000)))
        return 'MERMAID-PNG-OK %s' % p
    raise ValueError('unknown tool: %s' % name)


def rpc_result(rid, result):
    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': result},
                                ensure_ascii=False) + '\n')
    sys.stdout.flush()


def rpc_error(rid, code, message):
    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': rid,
                                 'error': {'code': code, 'message': message}},
                                ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get('method', '')
        rid = req.get('id')
        if method == 'initialize':
            rpc_result(rid, {'protocolVersion': PROTOCOL,
                             'capabilities': {'tools': {}},
                             'serverInfo': SERVER_INFO})
        elif method == 'notifications/initialized':
            pass
        elif method == 'ping':
            rpc_result(rid, {})
        elif method == 'tools/list':
            rpc_result(rid, {'tools': TOOLS})
        elif method == 'tools/call':
            try:
                out = handle_tool_call(req['params']['name'], req['params'].get('arguments') or {})
                rpc_result(rid, {'content': [{'type': 'text', 'text': str(out)}]})
            except Exception as e:
                rpc_result(rid, {'content': [{'type': 'text', 'text': 'ERROR: %s' % e}],
                                 'isError': True})
        elif rid is not None:
            rpc_error(rid, -32601, 'method not found: %s' % method)
        # 其余通知类: 忽略


if __name__ == '__main__':
    main()
