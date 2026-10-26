"""Faithful port of the numerical part of Graphwar 1's Function.processRange().

Source: https://github.com/Cmd-GZ/graphwar/blob/optimize/Function/src/Graphwar/Function.java
Constants from GraphServer/Constants.java.

LICENCE: GPL-3.0-or-later.
This file is a port of Graphwar 1 source code, which is
Copyright (C) 2011 Lucas Catabriga Rocha <catabriga90@gmail.com> and
distributed under the GNU General Public License v3 or later.
Source: https://github.com/Cmd-GZ/graphwar (branch `optimize`).
See NOTICE.md in the repository root.
"""
import math

PLANE_LENGTH = 770
PLANE_HEIGHT = 450
PLANE_GAME_LENGTH = 50
FUNC_MAX_STEPS = 20000
FUNC_MAX_STEP_DISTANCE_SQUARED = 0.001        # chord must be <= sqrt(0.001) = 0.0316
FUNC_MIN_X_STEP_DISTANCE = 0.00001
STEP_SIZE = 0.01
SOLDIER_RADIUS = 7
NORMAL_FUNC, FST_ODE, SND_ODE = 0, 1, 2


def game_to_px(x, y):
    """the game->Java2D conversion at the end of the loop body"""
    px = PLANE_LENGTH * x / PLANE_GAME_LENGTH + PLANE_LENGTH / 2
    py = -PLANE_LENGTH * y / PLANE_GAME_LENGTH + PLANE_HEIGHT / 2
    return px, py


def _rk4(f, x, y, step):
    k1 = f(x, y, 0)
    k2 = f(x + 0.5 * step, y + 0.5 * step * k1, 0)
    k3 = f(x + 0.5 * step, y + 0.5 * step * k2, 0)
    k4 = f(x + step, y + step * k3, 0)
    return y + (step / 6) * (k1 + 2 * k2 + 2 * k3 + k4)


def process_range(f, x0_game, y0_game, mode=NORMAL_FUNC):
    """returns (points_in_game_coords, stats)

    x0_game / y0_game are already converted to game coordinates the same way
    processRange() converts the soldier position (pixel input).
    """
    xs = [0.0] * FUNC_MAX_STEPS
    ys = [0.0] * FUNC_MAX_STEPS
    xs[0] = x0_game
    ys[0] = y0_game
    off = -f(xs[0], 0, 0) + ys[0]              # offSet
    num_steps = FUNC_MAX_STEPS
    endfunc_at = None
    bad = []
    for i in range(1, FUNC_MAX_STEPS):
        temp = STEP_SIZE

        def step_once(step):
            xi = xs[i - 1] + step
            if mode == NORMAL_FUNC:
                yi = f(xi, 0, 0) + off
            elif mode == FST_ODE:
                yi = _rk4(f, xs[i - 1], ys[i - 1], step)
            else:
                raise NotImplementedError
            return xi, yi

        xs[i], ys[i] = step_once(temp)
        end = False
        guard_hit = False
        nhalve = 0
        while (xs[i] - xs[i - 1]) ** 2 + (ys[i] - ys[i - 1]) ** 2 > FUNC_MAX_STEP_DISTANCE_SQUARED:
            if xs[i] - xs[i - 1] <= FUNC_MIN_X_STEP_DISTANCE:
                if mode == NORMAL_FUNC:
                    end = True
                guard_hit = True
                break
            temp /= 2
            nhalve += 1
            xs[i], ys[i] = step_once(temp)
        if end:
            num_steps = i
            endfunc_at = i
            break
        if guard_hit:
            bad.append(i)
        px, py = game_to_px(xs[i], ys[i])
        # GW1 would now do obstacle.collidePoint((int)px, (int)py)
        xi, yi = int(px), int(py)              # Java double->int narrowing (saturating)
        if yi < -2**31 or yi > 2**31 - 1:
            pass
        if math.isnan(py) or math.isinf(py):
            num_steps = i
            break
        if abs(xi) > 100000 or abs(yi) > 100000:   # would index far outside any obstacle grid
            num_steps = i
            break
    pts = list(zip(xs[:num_steps], ys[:num_steps]))
    return pts, dict(num_steps=num_steps, endfunc_at=endfunc_at, guard_hits=bad[:5],
                     n_guard=len(bad))


def chords(pts):
    return [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            for i in range(len(pts) - 1)]
