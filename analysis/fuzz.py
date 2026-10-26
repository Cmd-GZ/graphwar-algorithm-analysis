"""Randomised differential test of the reference model against the binary."""
import sys, os, random, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
from gwemu import *
import graphwar_curve as pc

g = Gw()
UN = [pc.SQRT, pc.LOG, pc.LN, pc.EXP, pc.ABS, pc.SIN, pc.COS, pc.TAN, pc.UNARY_MINUS]
BIN = [pc.ADD, pc.SUB, pc.MUL, pc.DIVIDE, pc.POW]
LEAF = [pc.VAR_X, pc.VAR_Y, pc.VAR_DY]


def rand_expr(depth):
    r = random.random()
    if depth <= 0 or r < 0.3:
        if random.random() < 0.5:
            return ([(pc.CONST, round(random.uniform(-5, 5), 3))], 0)
        v = random.choice(LEAF)
        return ([v], 0)
    if r < 0.55:
        sub, _ = rand_expr(depth - 1)
        return ([random.choice(UN)] + sub), 0
    a, _ = rand_expr(depth - 1)
    b, _ = rand_expr(depth - 1)
    return ([random.choice(BIN)] + a + b), 0


def main(n=300, seed=1):
    random.seed(seed)
    bad = 0
    for k in range(n):
        toks, _ = rand_expr(random.randint(1, 3))
        x0 = round(random.uniform(-20, 20), 2)
        y0 = round(random.uniform(-10, 10), 2)
        step = random.choice([0.01, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 1.0])
        flip = random.random() < 0.5
        ode = random.random() < 0.5
        try:
            a = g.call_path(toks, x0, y0, step, int(flip), int(ode))
        except Exception as e:
            print('EMU FAIL', e, toks, x0, y0, step, flip, ode)
            bad += 1
            continue
        try:
            b = pc.calculate_path(toks, x0, y0, step, flip, ode)
        except Exception as e:
            print('MODEL EXC', repr(e), toks, x0, y0, step, flip, ode)
            bad += 1
            continue
        if a != b:
            bad += 1
            print('MISMATCH case', k, 'toks', toks, 'x0', x0, 'y0', y0, 'step', step,
                  'flip', flip, 'ode', ode)
            print('  len real', len(a), 'len model', len(b))
            for i in range(min(len(a), len(b))):
                if a[i] != b[i]:
                    print('  first diff at', i, a[i], b[i])
                    break
            if bad > 5:
                break
    print('done, mismatches:', bad, 'of', n)


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300,
         int(sys.argv[2]) if len(sys.argv) > 2 else 1)
