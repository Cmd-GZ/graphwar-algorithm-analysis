import struct, math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu, TRAP, TRAP_SZ, STACK, STACK_SZ, HEAP, MATH
from unicorn.x86_const import *

# token tags (from the enum variant strings + dispatch tables)
VAR_X, VAR_Y, VAR_DY = 0, 1, 2
ADD, SUB, UNARY_MINUS, MUL, DIVIDE, POW = 3, 4, 5, 6, 7, 8
SQRT, LOG, LN, EXP, ABS, SIN, COS, TAN = 9, 10, 11, 12, 13, 14, 15, 16
CONST, LBRACKET, RBRACKET = 17, 18, 19


def tokens_bytes(tokens):
    out = b''
    for t in tokens:
        if isinstance(t, tuple):
            tag, val = t
        else:
            tag, val = t, 0.0
        out += struct.pack('<Qd', tag, float(val))
    return out


class Gw(Emu):
    def __init__(self):
        super().__init__()
        self.hook(0x460c20, self.h_grow)
        self.hook(0x528070, self.h_dealloc)
        self.hook(0x460c90, self.h_grow)
        self.hook(0x94b340, self.h_panic)
        self.alloc_sizes = {}

    def h_panic(self, uc):
        raise RuntimeError('panic reached')

    def h_grow(self, uc):
        rdi = uc.reg_read(UC_X86_REG_RDI)
        cap = self.rq(rdi)
        newcap = max(cap * 2, 4)
        oldptr = self.rq(rdi + 8)
        ln = self.rq(rdi + 16)
        n = min(ln, cap)
        ptr = self.alloc(newcap * 16, 16)
        if oldptr and n:
            try:
                self.wr(ptr, self.rd(oldptr, n * 16))
            except Exception:
                pass
        self.wq(rdi, newcap)
        self.wq(rdi + 8, ptr)

    def h_dealloc(self, uc):
        pass

    # ---- import trap handling ----
    def _hook_code(self, uc, address, size, data):
        raise RuntimeError('unexpected trap %#x' % address)

    def make_vec(self, tokens):
        """create a Vec<Token> in emulated memory: layout {cap, ptr, len}"""
        n = len(tokens)
        dataptr = self.alloc(max(16 * n, 16))
        self.wr(dataptr, tokens_bytes(tokens))
        v = self.alloc(24)
        self.wq(v, n)          # cap
        self.wq(v + 8, dataptr)  # ptr
        self.wq(v + 16, n)     # len
        return v

    def read_vec_points(self, vec):
        cap = self.rq(vec)
        ptr = self.rq(vec + 8)
        ln = self.rq(vec + 16)
        pts = []
        for i in range(ln):
            x = self.rd_f64(ptr + i * 16)
            y = self.rd_f64(ptr + i * 16 + 8)
            pts.append((x, y))
        return pts

    def call_eval(self, toks, x, y, dy):
        v = self.make_vec(toks)
        idx = self.alloc(8)
        self.wq(idx, 0)
        # rdi=tokens ptr, rsi=&idx, xmm0=x, xmm1=y, xmm2=dy
        self.call(0x4eb9d0, [v, idx, None, None], [x, y, dy])
        raw = self.uc.reg_read(UC_X86_REG_XMM0)
        return struct.unpack('<d', struct.pack('<Q', raw))[0]

    def call_path(self, toks, x0, y0, step, flagA=0, flagB=0):
        v = self.make_vec(toks)
        out = self.alloc(24)
        self.wq(out, 0); self.wq(out + 8, 0); self.wq(out + 16, 0)
        self.call(0x3c2530, [out, v, flagA, flagB], [x0, y0, step])
        return self.read_vec_points(out)
