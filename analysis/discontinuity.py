"""断点 / 陡坡在两代引擎里的四种组合（对应 REPORT §5.7 ★★ 的表格）。

用法: python3 analysis/discontinuity.py
"""
import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..'))
import gw1_model as g1
import graphwar_curve as gw


def chords(p):
    return [math.hypot(p[i+1][0]-p[i][0], p[i+1][1]-p[i][1]) for i in range(len(p)-1)]


def jump(h):
    """f(x) = +-h/2, 在 x=0 处跳变 h"""
    half = h / 2.0
    return lambda x: (half * (1.0 if x > 0 else -1.0))


def main():
    print('=== (a) 普通模式：跳变高度阈值（起点 (-5,0)） ===')
    print(f'{"h":>8} {"GW1":>6} {"GW2":>6}')
    for h in [0.005, 0.009, 0.0105, 0.011, 0.012, 0.02, 0.031, 0.032, 0.04, 2.0]:
        f = jump(h)
        a = g1.process_range(lambda x, y, d, f=f: f(x), -5.0, 0.0, g1.NORMAL_FUNC)[0]
        b = gw.shot_points('x/abs(x)*%r' % (h / 2.0), -5.0, 0.0, 0.01)
        pa = any(p[0] > 0 for p in a)
        pb = any(p[0] > 0 for p in b)
        print(f'{h:8.4g} {("pass" if pa else "DIE"):>6} {("pass" if pb else "DIE"):>6}'
              f'      GW1 n={len(a):5d} last_x={a[-1][0]:.6g}   GW2 n={len(b):5d} last_x={b[-1][0]:.6g}')

    print()
    print('=== (b) ODE 模式：右端不连续（折角）两代都能过 ===')
    sign = lambda x: (x / abs(x)) if x else float('nan')
    pts1 = g1.process_range(lambda x, y, d: sign(x), -5.0, 0.0, g1.FST_ODE)[0]
    pts2 = gw.calculate_path(gw.parse_function('x/abs(x)'), -5.0, 0.0, 0.01, False, True)
    print(f'  GW1 dy/dx=sign(x): n={len(pts1)} last=({pts1[-1][0]:.4g},{pts1[-1][1]:.4g})')
    print(f'  GW2 dy/dx=sign(x): n={len(pts2)} last=({pts2[-1][0]:.4g},{pts2[-1][1]:.4g})')

    print()
    print('=== (c) ODE 模式：斜率很陡时 GW1 的“作弊通道” ===')
    print(f'{"dy/dx":>10} {"GW1 弦长":>16} {"GW2 弦长":>16}')
    for v in (1.0, 1e2, 1e3, 1e4, 1e6):
        p1 = g1.process_range(lambda x, y, d, v=v: v, 0.0, 0.0, g1.FST_ODE)[0]
        p2 = gw.calculate_path(gw.parse_function(repr(v)), 0.0, 0.0, 0.01, False, True)
        c1, c2 = chords(p1), chords(p2)
        print(f'{v:10.4g} {max(c1):16.4g} {max(c2):16.4g}')


# ---------------------------------------------------------------------------
# (e) floor 文章的 ε 阈值：两代的判据可以直接算出 ε 的下限
#     GW1:  dx = sqrt(0.001)/|f'| 必须 > MIN_X_STEP = 1e-5
#     GW2:  dx = tol/|f'|         必须 > ULP(x)
# ---------------------------------------------------------------------------
def _dec(eps):
    s = f'{eps:.20f}'.rstrip('0')
    return s + '0' if s.endswith('.') else s


def _floor_expr(eps):
    c = "pisin(2pix)/(1-cos(2pix)+%s)" % _dec(eps)
    return "x-0.5+(%s)/(4+sqrt(34+(2*%s)^2))" % (c, c)


def _floor(x, eps):
    t = 2 * math.pi * x
    c = math.pi * math.sin(t) / (1 - math.cos(t) + eps)
    return x - 0.5 + c / (4 + math.sqrt(34 + (2 * c) ** 2))


def epsilon_scan(x0=-13.5, eps_list=(1e-3, 7e-4, 6.5e-4, 6e-4, 1e-4, 1e-8, 1e-10, 3e-12, 1e-12)):
    print()
    print('=== (e) floor 的 ε 下限（普通模式，起点 %.1f） ===' % x0)
    print(f'{"eps":>9} {"max|f\'|":>10} {"GW1 需要dx":>12} {"GW1":>5}   {"GW2 需要dx":>12} {"GW2":>5}')
    for eps in eps_list:
        md, h = 0.0, 1e-15
        for i in range(6000):
            x = 5.0 - 3e-6 + i * 1e-9
            md = max(md, abs((_floor(x + h, eps) - _floor(x - h, eps)) / (2 * h)))
        a = g1.process_range(lambda x, y, d, e=eps: _floor(x, e), x0, _floor(x0, eps), g1.NORMAL_FUNC)[0]
        b = gw.shot_points(_floor_expr(eps), x0, _floor(x0, eps), 0.01)
        ok1 = 'pass' if a[-1][0] > x0 + 1 else 'DIE'
        ok2 = 'pass' if b[-1][0] > x0 + 1 else 'DIE'
        print(f'{eps:9g} {md:10.3g} {0.0316228/md:12.3g} {ok1:>5}   {0.001/md:12.3g} {ok2:>5}')


if __name__ == '__main__':
    main()
    epsilon_scan()
