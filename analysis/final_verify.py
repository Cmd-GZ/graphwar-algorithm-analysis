"""End-to-end check: text -> tokens -> points, model vs. the real .so."""
import sys, os, struct, random, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..'))
from gwemu import *
import graphwar_curve as gw

g = Gw()

def real_parse(s):
    b = s.encode(); n = len(b)
    mem = g.alloc(n + 1); g.wr(mem, b)
    st = g.alloc(24); g.wq(st, n); g.wq(st + 8, mem); g.wq(st + 16, n)
    out = g.alloc(24); g.wq(out, 0); g.wq(out + 8, 0); g.wq(out + 16, 0)
    g.call(0x4ed670, [out, st])
    ptr = g.rq(out + 8); ln = g.rq(out + 16)
    toks = []
    for i in range(ln):
        tag = struct.unpack('<Q', g.rd(ptr + i * 16, 8))[0]
        val = struct.unpack('<d', g.rd(ptr + i * 16 + 8, 8))[0]
        toks.append((tag, val) if tag == 17 else tag)
    return toks

def real_path(toks, x0, y0, step, flip, ode):
    return g.call_path(toks, x0, y0, step, int(flip), int(ode))

FUNCS = ['sin(x)', 'cos(2x)', 'x^2/10', 'sqrt(abs(x))', '1/x', 'exp(-x^2)',
         'sin(x)/x', 'tan(x/4)', 'x^3-x', 'ln(abs(x)+1)', 'sin(x)+cos(2x)',
         '2sin(x)^2', '-x^2+3', 'pi*x/10', 'x*y', "y'", 'y', 'sin(x*y)']
STARTS = [(0.0, 0.0), (5.0, 2.0), (-8.0, -3.0)]
STEPS = [0.05, 0.1, 0.5]
bad = 0; total = 0
for fs in FUNCS:
    mt = gw.parse_function(fs)
    rt = real_parse(fs)
    if [t if isinstance(t, tuple) else t for t in mt] != [t if isinstance(t, tuple) else t for t in rt]:
        print('PARSE DIFF', fs, mt, rt); bad += 1
    for (x0, y0) in STARTS:
        for st in STEPS:
            for flip in (False, True):
                for ode in (False, True):
                    a = real_path(rt, x0, y0, st, flip, ode)
                    b = gw.calculate_path(mt, x0, y0, st, flip, ode)
                    total += 1
                    if a != b:
                        bad += 1
                        print('PATH DIFF', fs, x0, y0, st, flip, ode, len(a), len(b))
                        if bad > 5: sys.exit(1)
print('checked', total, 'point sequences; mismatches:', bad, flush=True)

# correction term check
for fs in ['sin(x)', 'x', 'x^2', '2x', 'sqrt(x)']:
    for (x0, y0) in [(2.0, 1.5), (0.0, 0.0), (-3.0, 4.0), (7.25, -2.5)]:
        for flip in (0, 1):
            b = fs.encode(); n = len(b)
            mem = g.alloc(n + 1); g.wr(mem, b)
            xy = g.alloc(16); g.wr_f64(xy, x0); g.wr_f64(xy + 8, y0)
            out = g.alloc(24); g.wq(out, 0); g.wq(out + 8, 1); g.wq(out + 16, 0)
            g.call(0x3c5f70, [out, mem, n, xy, flip])
            ptr = g.rq(out + 8); ln = g.rq(out + 16)
            real = g.rd(ptr, ln).decode()
            model = gw.correction_text(gw.parse_function(fs), x0, y0, bool(flip))
            if real != model:
                print('CORR DIFF', fs, x0, y0, flip, repr(real), repr(model))
                bad += 1
print('correction terms OK' if bad == 0 else 'FAILURES: %d' % bad)
