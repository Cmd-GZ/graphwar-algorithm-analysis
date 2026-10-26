"""Differential test: reference model vs. the real binary (unicorn)."""
import sys, os, math, random, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
from gwemu import *
import graphwar_curve as pc

g = Gw()


def run_real(tokens, x0, y0, step, flip, ode):
    return g.call_path(tokens, x0, y0, step, int(flip), int(ode))


def run_model(tokens, x0, y0, step, flip, ode):
    try:
        return pc.calculate_path(tokens, x0, y0, step, flip, ode)
    except Exception as e:
        return ('EXC', repr(e))


def cmp(name, tokens, x0, y0, step, flip=False, ode=False, verbose=False):
    a = run_real(tokens, x0, y0, step, flip, ode)
    b = run_model(tokens, x0, y0, step, flip, ode)
    if isinstance(b, tuple) and b and b[0] == 'EXC':
        print(f'FAIL(exc) {name}: {b[1]}')
        return False
    if len(a) != len(b):
        print(f'FAIL(len) {name}: real={len(a)} model={len(b)}')
        if verbose:
            print('  real head', a[:6])
            print('  model head', b[:6])
            for i in range(min(len(a), len(b))):
                if a[i] != b[i]:
                    print('  first diff at', i, a[i], b[i])
                    break
        return False
    for i, (p, q) in enumerate(zip(a, b)):
        if p != q:
            print(f'FAIL(val) {name}: idx {i} real={p} model={q}')
            return False
    return True


CASES = [
    ('const0', [(pc.CONST, 0.0)]),
    ('const3', [(pc.CONST, 3.0)]),
    ('x', [(pc.VAR_X, 0)]),
    ('-x', [(pc.UNARY_MINUS, 0), (pc.VAR_X, 0)]),
    ('sin x', [(pc.SIN, 0), (pc.VAR_X, 0)]),
    ('x^2', [(pc.POW, 0), (pc.VAR_X, 0), (pc.CONST, 2.0)]),
    ('sqrt x', [(pc.SQRT, 0), (pc.VAR_X, 0)]),
    ('log x', [(pc.LOG, 0), (pc.VAR_X, 0)]),
    ('exp x', [(pc.EXP, 0), (pc.VAR_X, 0)]),
    ('abs x', [(pc.ABS, 0), (pc.VAR_X, 0)]),
    ('x/2', [(pc.DIVIDE, 0), (pc.VAR_X, 0), (pc.CONST, 2.0)]),
]


def main():
    ok = 0
    bad = 0
    for name, toks in CASES:
        for (x0, y0) in [(0.0, 0.0), (-3.0, 1.0), (4.0, -2.0), (10.0, 5.0)]:
            for step in (0.1, 0.25, 0.5, 0.03):
                for flip in (False, True):
                    for ode in (False, True):
                        if cmp(name, toks, x0, y0, step, flip, ode):
                            ok += 1
                        else:
                            bad += 1
                            if bad > 12:
                                print('too many failures, stopping')
                                return
    print('ok', ok, 'bad', bad)


if __name__ == '__main__':
    main()
