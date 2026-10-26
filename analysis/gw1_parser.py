"""Port of Graphwar 1's PolishNotationFunction (parser + evaluator).

Source: https://github.com/Cmd-GZ/graphwar/blob/optimize/Function/src/Graphwar/PolishNotationFunction.java
Token ids from FunctionToken.java.

LICENCE: GPL-3.0-or-later.
This file is a port of Graphwar 1 source code, which is
Copyright (C) 2011 Lucas Catabriga Rocha <catabriga90@gmail.com> and
distributed under the GNU General Public License v3 or later.
Source: https://github.com/Cmd-GZ/graphwar (branch `optimize`).
See NOTICE.md in the repository root.
"""
import math
import re

ADD, SUBTRACT, MULTIPLY, DIVIDE, POW = 1, 2, 3, 4, 5
SQRT, LOG, ABS, SIN, COS, TAN, LN = 6, 7, 8, 9, 10, 11, 12
VAR1, VAR2, VAR3, VALUE, LBRACKET, RBRACKET = 13, 14, 15, 16, 17, 18

NPARAM = {ADD: 2, SUBTRACT: 1, MULTIPLY: 2, DIVIDE: 2, POW: 2,
          SQRT: 1, LOG: 1, ABS: 1, SIN: 1, COS: 1, TAN: 1, LN: 1,
          VAR1: 0, VAR2: 0, VAR3: 0, VALUE: 0, LBRACKET: 0, RBRACKET: 0}

PATTERN = re.compile(r"[0-9]*\.?[0-9]+|\(|\)|x|y'|y|\+|\*|/|\^|sqrt|log|abs|sin|sen|cos|tan|tg|-|ln|e|pi")

NAMES = {'x': VAR1, 'y': VAR2, "y'": VAR3, '+': ADD, '-': SUBTRACT,
         '*': MULTIPLY, '/': DIVIDE, '^': POW, 'sqrt': SQRT, 'log': LOG,
         'abs': ABS, 'sin': SIN, 'sen': SIN, 'cos': COS, 'tan': TAN,
         'tg': TAN, 'ln': LN, '(': LBRACKET, ')': RBRACKET}


class MalformedFunction(Exception):
    pass


def _is_implicit(t1, t2):
    if t1 in (VALUE, VAR1, VAR2, VAR3, RBRACKET):
        if t2 in (VALUE, VAR1, VAR2, VAR3, LBRACKET) or NPARAM.get(t2, 0) == 1:
            return True
    return False


def lex(s):
    s = s.lower().replace('-', '+-').replace('exp', 'e^').replace(',', '.')
    toks = []
    for m in PATTERN.finditer(s):
        t = m.group(0)
        try:
            toks.append((VALUE, float(t)))
            continue
        except ValueError:
            pass
        if t == 'e':
            toks.append((VALUE, math.e))
        elif t == 'pi':
            toks.append((VALUE, math.pi))
        elif t in NAMES:
            toks.append((NAMES[t], 0.0))
    # implicit multiplication
    out = []
    for i, tk in enumerate(toks):
        if i and _is_implicit(toks[i - 1][0], tk[0]):
            out.append((MULTIPLY, 0.0))
        out.append(tk)
    return out


def _precedes(t0, t1):
    return t0 < t1


def reorder(tokens):
    polish = []

    def rec(start, end):
        if start > end or start >= len(tokens):
            return False
        nxt = -1
        next_nest = 2 ** 31 - 1
        nest = 0
        for i in range(start, end + 1):
            t = tokens[i][0]
            if t == LBRACKET:
                nest += 1
            elif t == RBRACKET:
                nest -= 1
            elif nest < next_nest or (nest == next_nest and (nxt == -1 or _precedes(t, tokens[nxt][0]))):
                nxt = i
                next_nest = nest
        if nxt == -1:
            return False
        n = NPARAM[tokens[nxt][0]]
        if n == 0:
            polish.append(tokens[nxt])
        elif n == 1:
            polish.append(tokens[nxt])
            rec(nxt + 1, end)
        else:
            polish.append(tokens[nxt])
            left = rec(start, nxt - 1)
            if tokens[nxt][0] == ADD and not left:
                polish.append((VALUE, 0.0))     # "Add function may have only one operand"
            rec(nxt + 1, end)
        return True

    rec(0, len(tokens) - 1)
    return polish


def _values_needed(polish):
    need = 1
    for i, (t, _) in enumerate(polish):
        need += NPARAM[t] - 1
        if need == 0 and i + 1 < len(polish):
            return -1
    return need


def parse(s):
    toks = lex(s)
    if not toks:
        return []
    pol = reorder(toks)
    if _values_needed(pol) != 0:
        raise MalformedFunction()
    return pol


def evaluate(polish, x=0.0, y=0.0, dy=0.0):
    pos = [0]
    vars_ = (x, y, dy)

    def ev():
        t, v = polish[pos[0]]
        pos[0] += 1
        if t == VAR1:
            return vars_[0]
        if t == VAR2:
            return vars_[1]
        if t == VAR3:
            return vars_[2]
        if t == VALUE:
            return v
        if t == SUBTRACT:
            return -ev()
        if t == ADD:
            return ev() + ev()
        if t == MULTIPLY:
            return ev() * ev()
        if t == DIVIDE:
            a = ev(); b = ev()
            try:
                return a / b
            except ZeroDivisionError:
                return math.copysign(float('inf'), a) * math.copysign(1, b)
        if t == POW:
            a = ev(); b = ev()
            try:
                r = a ** b
                return float('nan') if isinstance(r, complex) else r
            except OverflowError:
                return float('inf')
        if t == SQRT:
            a = ev()
            return math.sqrt(a) if a >= 0 else float('nan')
        if t == LOG:
            a = ev()
            return math.log10(a) if a > 0 else (float('-inf') if a == 0 else float('nan'))
        if t == LN:
            a = ev()
            return math.log(a) if a > 0 else (float('-inf') if a == 0 else float('nan'))
        if t == ABS:
            return abs(ev())
        if t == SIN:
            return math.sin(ev())
        if t == COS:
            return math.cos(ev())
        if t == TAN:
            return math.tan(ev())
        raise ValueError(t)

    return ev()
