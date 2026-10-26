"""Differential test of the parser model against the real parser in the .so."""
import sys, os, struct, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
from gwemu import *
import graphwar_curve as pm

g = Gw()


def real_parse(s):
    b = s.encode()
    n = len(b)
    mem = g.alloc(n + 1)
    g.wr(mem, b)
    st = g.alloc(24)
    g.wq(st, n); g.wq(st + 8, mem); g.wq(st + 16, n)
    out = g.alloc(24)
    g.wq(out, 0); g.wq(out + 8, 0); g.wq(out + 16, 0)
    g.call(0x4ed670, [out, st])
    ptr = g.rq(out + 8)
    ln = g.rq(out + 16)
    toks = []
    for i in range(min(ln, 80)):
        tag = struct.unpack('<Q', g.rd(ptr + i * 16, 8))[0]
        val = struct.unpack('<d', g.rd(ptr + i * 16 + 8, 8))[0]
        toks.append(('C', round(val, 6)) if tag == 17 else tag)
    return toks


def norm(toks):
    return [('C', round(t[1], 6)) if isinstance(t, tuple) else t for t in toks]


VALID = [
    'x', 'sin(x)', 'x^2', '2*x+1', '(x+1)*2', '-x', '2x', '2 sin(x)', 'x/2/3',
    '2^3^2', '-2^2', '2*-3', 'x--1', '1.5x', 'sinx', 'sin x', 'sqrt(4)',
    'log(100)', 'abs(-3)', 'ln(e)', 'tan(x)', '2x^2', '2^3x', '-x^2', '2^-3',
    'x^2^2', 'sin(x)^2', '2sin(x)^2', 'x^2x', '-x^2^2', 'x^2*3', '2+3*4',
    '2*3-4', '8/4/2', '2x3', '2(x)(3)', 'sin(x)cos(x)', 'pi', '2pi', 'n',
    '1/2x', 'x/2x', '2^n', 'y', "y'", "y'x", 'x y', 'e', 'sin(cos(x))',
    'sqrt(x^2+1)', 'exp(-x^2)', 'x/y*2', '3*x^2+2*x+1', 'x++1', 'x+-1',
    '-x+1', 'x*-1', 'x^2^-1', '2^-3^2', 'sin(2x)', 'sin(x)/x', 'x*sin(1/x)',
    '(x^2-4)/(x+2)', '0.5x^2-3x+1', 'sqrt(abs(x))+1', 'ln(abs(x))', 'tan(pi*x/4)',
    'e^x', 'n*x^2', 'sin(pi x)', 'cos x+sin x', 'x^0.5', '2^x',
]

BAD_OK = ['x+', '1+', 'x*', '(x', 'x)', '()', 'x-', 'x^', 'x/', '3-', '-',
          '*-', '^-', 'sin+', '2^', '^2', 'x^2^-1']


def run(cases, verbose=True):
    bad = []
    for s in cases:
        a = real_parse(s)
        b = norm(pm.parse_function(s))
        if a != b:
            bad.append((s, a, b))
    if verbose:
        for s, a, b in bad:
            print(f'  DIFF {s!r:16} real={a} model={b}')
    print(f'{len(cases)-len(bad)}/{len(cases)} match')
    return bad


if __name__ == '__main__':
    print('--- valid expressions ---')
    run(VALID)
    print('--- edge cases ---')
    run(BAD_OK)
