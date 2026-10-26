#!/usr/bin/env python3
"""
graphwar_curve -- faithful reimplementation of Graphwar II's function-curve
point generator.

Reverse engineered from the Linux build (libgraphwarrust.so, Godot 4.7
GDExtension, Rust).  Everything in here was recovered from the binary and
verified bit-exactly against it (see analysis/ and REPORT.md).

Pipeline used by the game when a player fires a shot:

    typed text  --(graphwar_function_input.rs)-->  prefix token list
                --(shot calculator)-->             corrected token list
                --(graphwar_path_calculator.rs)--> point sequence

The three implemented stages:

  * parse_function(text)   text  -> prefix token list      (@0x4ed670)
  * evaluate(tokens,x,y,d) token list -> f64              (@0x4eb9d0)
  * calculate_path(...)    token list -> [(x,y), ...]     (@0x3c2530)

Usage:
    python3 graphwar_curve.py "sin(x)" --start 5 2 --step 0.01
    python3 graphwar_curve.py "y'" --ode --start 0 1 --step 0.1
"""

import math
import sys

# --------------------------------------------------------------------------
# Token ids.  These are the discriminants of the game's `enum Function`
# (its variant names appear verbatim in .rodata:
#  VAR_X VAR_Y VAR_DY ADD ... UNARY_MINUS ... DIVIDE POW LOG LN EXP ABS SIN
#  COS TAN CONST LEFT_BRACKET RIGHT_BRACKET)
# --------------------------------------------------------------------------
VAR_X, VAR_Y, VAR_DY = 0, 1, 2
ADD, SUB, UNARY_MINUS, MUL, DIVIDE, POW = 3, 4, 5, 6, 7, 8
SQRT, LOG, LN, EXP, ABS, SIN, COS, TAN = 9, 10, 11, 12, 13, 14, 15, 16
CONST, LEFT_BRACKET, RIGHT_BRACKET = 17, 18, 19

TOKEN_NAMES = {
    VAR_X: 'x', VAR_Y: 'y', VAR_DY: "y'", ADD: '+', SUB: '-',
    UNARY_MINUS: 'neg', MUL: '*', DIVIDE: '/', POW: '^', SQRT: 'sqrt',
    LOG: 'log', LN: 'ln', EXP: 'exp', ABS: 'abs', SIN: 'sin', COS: 'cos',
    TAN: 'tan', CONST: 'const', LEFT_BRACKET: '(', RIGHT_BRACKET: ')',
}

# ---- tuning constants, read out of .rodata at the given file offsets ------
MAX_ABS_X = 25.0        # 0x19fbc8 -- |x| bound of the plane
MAX_ABS_Y = 15.0        # 0x19fd40 -- |y| bound of the plane
LENGTH_TOL = 0.001      # 0x19fc78 -- bisection tolerance on the arc length
TOTAL_LEN = 200.0       # 0x19f8c0 -- point-count budget: n = (200/step) as i32
HALF = 0.5              # 0x19f6d0
SIXTH = 6.0             # 0x19f098 (RK4 h/6)
STEP_DEFAULT = 0.01     # 0x3f847ae147ae147b, the step the game server uses

PI = 3.14159265358979323846
E = 2.71828182845904523536

# ==========================================================================
# 1. parser  (src/graphwar_function_input.rs, function @0x4ed670)
# ==========================================================================
_TOKEN_RE = None


def _token_re():
    global _TOKEN_RE
    if _TOKEN_RE is None:
        import re
        # the literal regex string found at 0x1c4347
        _TOKEN_RE = re.compile(
            r"[0-9]*\.?[0-9]+|\(|\)|x|y'|y|\+|-|\*|/|\^|sqrt|log|abs|sin|cos|tan|ln|n|exp|e")
    return _TOKEN_RE


_FUNCS = {'sqrt': SQRT, 'log': LOG, 'abs': ABS, 'sin': SIN, 'cos': COS,
          'tan': TAN, 'ln': LN, 'exp': EXP}
_BINOPS = {'+': ADD, '-': SUB, '*': MUL, '/': DIVIDE, '^': POW}


def _tag(t):
    return t if isinstance(t, int) else t[0]


def lex(text):
    """lowercase -> 'pi'/'P'->'n' -> regex tokenise (the game does exactly this)"""
    s = text.lower().replace('pi', 'n').replace('\u03c0', 'n')
    out = []
    for m in _token_re().finditer(s):
        t = m.group(0)
        if t == '(':
            out.append(LEFT_BRACKET)
        elif t == ')':
            out.append(RIGHT_BRACKET)
        elif t == 'x':
            out.append(VAR_X)
        elif t == "y'":
            out.append(VAR_DY)
        elif t == 'y':
            out.append(VAR_Y)
        elif t == 'n':                      # 'n' is pi
            out.append((CONST, PI))
        elif t == 'e':
            out.append((CONST, E))
        elif t in _FUNCS:
            out.append(_FUNCS[t])
        elif t in _BINOPS:
            out.append(_BINOPS[t])
        else:
            out.append((CONST, float(t)))
    return out


class _Node:
    __slots__ = ('op', 'kids')

    def __init__(self, op, *kids):
        self.op = op
        self.kids = kids


class _Parser:
    """Recursive descent -> prefix tree.

    expr     := term { ('+'|'-') term }
    term     := unary { ('*'|'/'|implicit) unary }
    unary    := '-' unary | power
    power    := primary { '^' prefixed }        (LEFT associative!)
    prefixed := '-' prefixed | primary
    primary  := number | x | y | y' | e | n | '(' expr ')' | func primary

    Missing operands: '+' fills in CONST 0 on both sides, '-' on the right
    side, and a '-' with no left operand becomes UNARY_MINUS.  Other ops just
    drop the missing child (the evaluator then reports 0.0).
    """

    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        t = self.peek()
        if t is not None:
            self.i += 1
        return t

    def _starts_operand(self, t):
        if t is None:
            return False
        tag = _tag(t)
        return tag in (VAR_X, VAR_Y, VAR_DY, CONST, LEFT_BRACKET, SQRT, LOG,
                       ABS, SIN, COS, TAN, LN, EXP)

    def expr(self):
        left = self.term()
        while True:
            t = self.peek()
            if t is None or _tag(t) not in (ADD, SUB):
                break
            op = _tag(self.take())
            right = self.term()
            if op == ADD:
                left = _Node(ADD,
                             left if left is not None else _Node(CONST, 0.0),
                             right if right is not None else _Node(CONST, 0.0))
            elif left is None:
                left = _Node(UNARY_MINUS, right)
            else:
                left = _Node(SUB, left,
                             right if right is not None else _Node(CONST, 0.0))
        return left

    def term(self):
        left = self.unary()
        while True:
            t = self.peek()
            if t is None:
                break
            tag = _tag(t)
            if tag in (MUL, DIVIDE):
                self.take()
                left = _Node(tag, left, self.unary())
            elif self._starts_operand(t):
                left = _Node(MUL, left, self.unary())
            else:
                break
        return left

    def unary(self):
        t = self.peek()
        if t is not None and _tag(t) in (SUB, UNARY_MINUS):
            self.take()
            return _Node(UNARY_MINUS, self.unary())
        return self.power()

    def power(self):
        left = self.primary()
        while True:
            t = self.peek()
            if t is None or _tag(t) != POW:
                break
            self.take()
            left = _Node(POW, left, self.prefixed())
        return left

    def prefixed(self):
        t = self.peek()
        if t is not None and _tag(t) in (SUB, UNARY_MINUS):
            self.take()
            return _Node(UNARY_MINUS, self.prefixed())
        return self.primary()

    def primary(self):
        t = self.peek()
        if t is None:
            return None
        tag = _tag(t)
        if tag in (VAR_X, VAR_Y, VAR_DY, CONST):
            self.take()
            return _Node(t)
        if tag == LEFT_BRACKET:
            self.take()
            node = self.expr()
            if self.peek() is not None and _tag(self.peek()) == RIGHT_BRACKET:
                self.take()
            return node
        if tag in (SQRT, LOG, ABS, SIN, COS, TAN, LN, EXP):
            self.take()
            return _Node(t, self.primary())
        return None


def _flatten(node, out=None):
    if out is None:
        out = []
    if node is None:
        return out
    if node.op == CONST and len(node.kids) == 1 and isinstance(node.kids[0], float):
        out.append((CONST, node.kids[0]))
        return out
    out.append(node.op)
    for k in node.kids:
        _flatten(k, out)
    return out


def parse_function(text):
    """Graphwar function text -> prefix token list.

    >>> parse_function('2*x+1')
    [3, 6, (17, 2.0), 0, (17, 1.0)]
    """
    toks = lex(text)
    if not toks:
        return []
    return _flatten(_Parser(toks).expr())


# ==========================================================================
# 2. evaluator  (function @0x4eb9d0)
# ==========================================================================
def _nan(x):
    return x != x


def _sqrt(x):
    return math.sqrt(x) if x >= 0.0 else float('nan')


def _pow(a, b):
    try:
        r = a ** b
        return float('nan') if isinstance(r, complex) else r
    except OverflowError:
        return float('inf')
    except ZeroDivisionError:
        return float('inf')
    except ValueError:
        return float('nan')


def _div(a, b):
    if b == 0.0:
        if a == 0.0 or _nan(a):
            return float('nan')
        return math.copysign(float('inf'), a) * math.copysign(1.0, b)
    return a / b


def _log10(v):
    if _nan(v):
        return v
    if v < 0.0:
        return float('nan')
    if v == 0.0:
        return float('-inf')
    return math.log10(v)


def _log(v):
    if _nan(v):
        return v
    if v < 0.0:
        return float('nan')
    if v == 0.0:
        return float('-inf')
    return math.log(v)


def _hypot(a, b):
    """the game calls sqrt(a*a + b*b), *not* a real hypot()"""
    return _sqrt(a * a + b * b)


class Evaluator:
    """Walks the prefix token list recursively (VAR_DY is the third variable)."""

    def __init__(self, tokens):
        self.t = [(t, 0.0) if isinstance(t, int) else t for t in tokens]
        self.i = 0

    def eval(self, x=0.0, y=0.0, dy=0.0):
        self.i = 0
        return self._ev(x, y, dy)

    def _ev(self, x, y, dy):
        i = self.i
        if i >= len(self.t):
            return 0.0                      # the game returns 0 for a short list
        tag, val = self.t[i]
        self.i = i + 1
        if tag == VAR_X:
            return x
        if tag == VAR_Y:
            return y
        if tag == VAR_DY:
            return dy
        if tag == CONST:
            return val
        if tag == UNARY_MINUS:
            return -self._ev(x, y, dy)
        if tag == SQRT:
            return _sqrt(self._ev(x, y, dy))
        if tag == LOG:
            return _log10(self._ev(x, y, dy))
        if tag == LN:
            return _log(self._ev(x, y, dy))
        if tag == EXP:
            v = self._ev(x, y, dy)
            try:
                return math.exp(v)
            except OverflowError:
                return float('inf')
        if tag == ABS:
            return abs(self._ev(x, y, dy))
        if tag == SIN:
            return math.sin(self._ev(x, y, dy))
        if tag == COS:
            return math.cos(self._ev(x, y, dy))
        if tag == TAN:
            return math.tan(self._ev(x, y, dy))
        a = self._ev(x, y, dy)
        b = self._ev(x, y, dy)
        if tag == ADD:
            return a + b
        if tag == SUB:
            return a - b
        if tag == MUL:
            return a * b
        if tag == DIVIDE:
            return _div(a, b)
        if tag == POW:
            return _pow(a, b)
        raise ValueError('bad token %r' % (tag,))


def evaluate(tokens, x=0.0, y=0.0, dy=0.0):
    return Evaluator(tokens).eval(x, y, dy)


# ==========================================================================
# 3. curve / point sequence  (src/graphwar_path_calculator.rs @0x3c2530)
# ==========================================================================
def point_budget(step):
    """(200.0 / step) as i32 with the game's saturation rules, min 1."""
    raw = TOTAL_LEN / step
    if _nan(raw):
        n = 0
    elif raw >= 2147483647.0:
        n = 2147483647
    elif raw <= -2147483648.0:
        n = -2147483648
    else:
        n = int(raw)                       # trunc toward zero
    return n if n >= 2 else 1


def calculate_path(tokens, x0, y0, step=STEP_DEFAULT, flip=False, ode=False):
    """The game's `calculate_path`, point for point.

    tokens : prefix token list (see parse_function)
    x0,y0  : the firing soldier's position; it is also the first point
    step   : wanted *chord length* between consecutive points
    flip   : True when firing to the left (mirrors the x axis)
    ode    : True  -> tokens are dy/dx = f(x, y)  (differential-equation mode)
             False -> tokens are           y = f(x)
    Returns [(x, y), ...] in plane coordinates.
    """
    ev = Evaluator(tokens)

    def f(x, y=0.0, dy=0.0):
        return ev.eval(x, y, dy)

    pts = [(x0, y0)]
    x = -x0 if flip else x0
    y = y0
    n = point_budget(step)

    if ode:
        # ---- differential-equation mode: RK4 + bisection on the step -----
        count = 0
        while True:
            lo, hi = x, x + step
            accepted = False
            for _ in range(100):
                mid = (lo + hi) * HALF
                h = mid - x
                k1 = f(x, y)
                k2 = f(x + h * HALF, y + k1 * h * HALF)
                k3 = f(x + h * HALF, y + k2 * h * HALF)
                k4 = f(x + h, y + k3 * h)
                yn = y + (h / SIXTH) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
                ln = _hypot(h, yn - y)
                if not (LENGTH_TOL > abs(ln - step)):
                    if ln > step or _nan(ln):
                        hi = mid
                    else:
                        lo = mid
                    continue
                px = -mid if flip else mid
                if _nan(yn) or _nan(px):
                    return pts
                if abs(mid) > MAX_ABS_X or abs(yn) > MAX_ABS_Y:
                    return pts
                pts.append((px, yn))
                count += 1
                x, y = mid, yn
                accepted = True
                break
            if not accepted or count == n:
                return pts
    else:
        # ---- plain-function mode: bisection on the step ------------------
        count = 0
        while True:
            lo, hi = x, x + step
            accepted = False
            for _ in range(100):
                mid = (lo + hi) * HALF
                fm = f(mid)
                ln = _hypot(mid - x, fm - y)
                if not (LENGTH_TOL > abs(ln - step)):
                    if ln > step or _nan(ln):
                        hi = mid
                    else:
                        lo = mid
                    continue
                # the game double-checks with a half step before accepting
                mid2 = (x + mid) * HALF
                fm2 = f(mid2)
                ln2 = _hypot(mid2 - x, fm2 - y)
                if ln <= ln2:
                    lo = x
                    continue
                px = -mid if flip else mid
                if _nan(fm) or _nan(px):
                    return pts
                if abs(mid) > MAX_ABS_X or abs(fm) > MAX_ABS_Y:
                    return pts
                pts.append((px, fm))
                count += 1
                x, y = mid, fm
                accepted = True
                break
            if not accepted or count == n:
                return pts


# ==========================================================================
# 4. the constant the game adds so the curve passes through the soldier
#    (function @0x3c5f70 -- also what the UI shows in the bottom-right corner)
# ==========================================================================
def correction(tokens, x0, y0, flip=False):
    """c = y0 - f(+-x0); the shot then uses f(x) + c."""
    return y0 - evaluate(tokens, -x0 if flip else x0, 0.0, 0.0)


def correction_text(tokens, x0, y0, flip=False):
    """Exactly what the game prints, e.g. ' + 0.591' / ' - 1.000' / ' + NaN'."""
    c = correction(tokens, x0, y0, flip)
    if _nan(c):
        return ' + NaN'          # Rust: branch on `c < 0.0`, NaN takes the '+' path
    return ' + %.3f' % c if c >= 0.0 else ' - %.3f' % -c


def shifted_tokens(tokens, c):
    """f(x)+c expressed as a prefix token list."""
    return [ADD, (CONST, c)] + list(tokens)


def shot_points(text, x0, y0, step=STEP_DEFAULT, flip=False, ode=False,
                apply_correction=True):
    """End-to-end: the exact point sequence a shot from (x0,y0) produces."""
    toks = parse_function(text)
    if not toks:
        return []
    if apply_correction and not ode:
        toks = shifted_tokens(toks, correction(toks, x0, y0, flip))
    return calculate_path(toks, x0, y0, step, flip, ode)


# ==========================================================================
# CLI
# ==========================================================================
def main(argv):
    import argparse
    ap = argparse.ArgumentParser(
        description='Graphwar II curve point generator (reverse engineered)')
    ap.add_argument('function', help='e.g. "sin(x)" or "x^2/10"')
    ap.add_argument('--start', nargs=2, type=float, default=[0.0, 0.0],
                    metavar=('X', 'Y'), help='soldier position (default 0 0)')
    ap.add_argument('--step', type=float, default=STEP_DEFAULT)
    ap.add_argument('--flip', action='store_true', help='fire to the left')
    ap.add_argument('--ode', action='store_true',
                    help='treat the input as dy/dx = f(x,y)')
    ap.add_argument('--no-correction', action='store_true',
                    help='do not add the constant that pins the curve to the soldier')
    ap.add_argument('--limit', type=int, default=20, help='points to print')
    ap.add_argument('--csv', metavar='FILE', help='write all points to a csv file')
    a = ap.parse_args(argv)

    toks = parse_function(a.function)
    print('tokens    :', toks)
    if a.no_correction or a.ode:
        t2 = toks
    else:
        c = correction(toks, a.start[0], a.start[1], a.flip)
        print('correction:', correction_text(toks, a.start[0], a.start[1], a.flip),
              '  f(x)%+.3f' % c)
        t2 = shifted_tokens(toks, c)
    pts = calculate_path(t2, a.start[0], a.start[1], a.step, a.flip, a.ode)
    print('points    :', len(pts))
    for p in pts[:a.limit]:
        print('  %12.6f %12.6f' % p)
    if len(pts) > a.limit:
        print('  ...')
    if a.csv:
        with open(a.csv, 'w') as fh:
            fh.write('x,y\n')
            for p in pts:
                fh.write('%.17g,%.17g\n' % p)
        print('wrote', a.csv)


if __name__ == '__main__':
    main(sys.argv[1:])
