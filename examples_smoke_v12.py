# -*- coding: utf-8 -*-
"""simlib v1.2 冒烟: 手册 §8/§10 新接口(不跑 COMSOL, 纯函数级验证)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comsol import java_eval_global, parse_eval_stdout, eig_freq_q, health_check, MESH_TIERS, PORT_RECIPE_TA

ok = True
def chk(cond, label):
    global ok
    print('%s %s' % ('PASS' if cond else 'FAIL', label))
    if not cond: ok = False

# 1. java_eval_global 生成的 Java 段: 关键 API 形态正确(§8.2)
j = java_eval_global(['abs(ta.S11)', 'abs(ta.S21)'])
chk('m.result().numerical().create("ev1", "EvalGlobal");' in j, 'java: numerical()+EvalGlobal')
chk('m.result("ev1").set("expr", new String[]{"abs(ta.S11)", "abs(ta.S21)"});' in j, 'java: expr 数组')
chk('m.result("ev1").set("data", "dset1");' in j, 'java: data=dset1')
chk('getReal()' in j and 'j0 += 20' in j, 'java: getReal + 每行20个')
chk('numeric()' not in j, 'java: 不含死路 numeric()')

# 2. parse_eval_stdout 往返: 25 个数跨 2 行, 无丢失
lines = ['EV| row 0 ' + ' '.join('%.6g' % (0.5 * i) for i in range(20)),
         'EV| row 0 ' + ' '.join('%.6g' % (0.5 * i) for i in range(20, 25)),
         'EV| row 1 3.25']
got = parse_eval_stdout('\n'.join(lines))
chk(len(got.get(0, [])) == 25 and got.get(1) == [3.25], 'parse 往返 25+1 值')

# 3. eig_freq_q 口径(§8.6): f=|Im|/2pi
rows = eig_freq_q([complex(-12.0, 3612.0)])
f, dec, q = rows[0]
chk(abs(f - 3612.0 / (2 * 3.141592653589793)) < 1e-9, 'eig: f=|Im|/2pi')
chk(abs(dec - (-12.0)) < 1e-12 or abs(dec - 12.0) < 1e-12, 'eig: decay=-|Re|')
chk(abs(q - 3.141592653589793 * f / 12.0) < 1e-6, 'eig: Q=pi*f/|Re|')

# 4. health_check 六条分支
v1, _ = health_check(3, [300, 310, 320], S11_abs=[0.93, 0.89, 0.78], A=[0.13, 0.20, 0.39],
                     n_elems=11412, hmax=2e-3, one_proc_per_freq=False)
chk(v1 == 'PASS', 'health: 正常数据 PASS')
v2, i2 = health_check(3, [300], A=[1.0000])
chk(v2 == 'SUSPECT' and any('1.0000' in x for x in i2), 'health: A==1 病态')
v3, i3 = health_check(3, [300, 310, 320], S11_abs=[-1.0, 0.9, 0.8])
chk(v3 == 'SUSPECT' and any('负值' in x for x in i3), 'health: 负 |S11|')
v4, i4 = health_check(91, [300.0], n_elems=1136216, hmax=2e-4, one_proc_per_freq=None)
chk(v4 == 'SUSPECT' and any('OOM' in x or '一频点一进程' in x for x in i4), 'health: 细网格 OOM 提示')
v5, i5 = health_check(3, [300, 310, 320], n_elems=999999, hmax=2e-3, one_proc_per_freq=False)
chk(v5 == 'SUSPECT' and any('偏离' in x for x in i5), 'health: 单元数偏离档位')
v6, i6 = health_check(3, [300, 310, 320], n_elems=176660, hmax=5e-4, one_proc_per_freq=True)
chk(v6 == 'PASS', 'health: 细网格但已一频点一进程 PASS')

# 5. 常量在位
chk(2e-3 in MESH_TIERS and '低估 1.8' in MESH_TIERS[2e-3]['trust'], 'MESH_TIERS 档表')
chk('sym0' in PORT_RECIPE_TA and 'entitydim=1' in PORT_RECIPE_TA, 'PORT_RECIPE_TA 配方')

# 6. MCP 工具直调
import importlib, mcp_server
importlib.reload(mcp_server)
r1 = mcp_server.handle_tool_call('comsol_eval_snippet', {'exprs': ['abs(ta.S11)']})
chk('EvalGlobal' in r1, 'mcp: eval_snippet')
r2 = mcp_server.handle_tool_call('comsol_eig', {'re': [-12.0], 'im': [3612.0]})
chk('Q=' in r2 and 'f=' in r2, 'mcp: eig')
r3 = mcp_server.handle_tool_call('comsol_health',
    {'freqs_expected': 3, 'freqs_got': [300, 310, 320], 'a': [1.0, 0.2, 0.3]})
chk(r3.startswith('SUSPECT'), 'mcp: health SUSPECT')

print('\nSMOKE-V12-%s' % ('DONE' if ok else 'FAILED'))
