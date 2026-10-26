"""Minimal ELF64 loader (used by the analysis scripts).

The game binary itself is NOT part of this repository -- drop your own copy of
`libgraphwarrust.so` into the repository root (see ../README.md).
"""
import os, struct, bisect
from capstone import Cs, CS_ARCH_X86, CS_MODE_64, CS_OPT_SYNTAX_INTEL
from capstone.x86 import X86_OP_MEM, X86_OP_IMM, X86_REG_RIP


class Elf:
    def __init__(self, path):
        if not os.path.exists(path):
            raise SystemExit(
                "missing binary: %s\n"
                "This repository does not ship the game files. Copy your own\n"
                "libgraphwarrust.so / Graphwar.pck / Graphwar.x86_64 into the\n"
                "repository root first (see README.md)." % os.path.abspath(path))
        self.data = open(path, 'rb').read()
        d = self.data
        assert d[:4] == b'\x7fELF' and d[4] == 2
        (self.e_shoff,) = struct.unpack_from('<Q', d, 0x28)
        (self.e_shentsize, self.e_shnum, self.e_shstrndx) = struct.unpack_from('<HHH', d, 0x3a)
        self.sections = []
        for i in range(self.e_shnum):
            off = self.e_shoff + i * self.e_shentsize
            name, typ, flags, addr, offset, size = struct.unpack_from('<IIQQQQ', d, off)
            self.sections.append(dict(name=name, type=typ, flags=flags, addr=addr,
                                      offset=offset, size=size))
        strtab = self.sections[self.e_shstrndx]
        base = strtab['offset']
        for s in self.sections:
            end = d.index(b'\0', base + s['name'])
            s['sname'] = d[base + s['name']:end].decode()
        self.by_name = {s['sname']: s for s in self.sections}
        # program headers for memsz
        self.segments = []

    def sec(self, name):
        return self.by_name[name]

    def sec_data(self, name):
        s = self.by_name[name]
        return self.data[s['offset']:s['offset'] + s['size']]

    def addr_to_off(self, addr):
        for s in self.sections:
            if s['type'] != 8 and s['addr'] <= addr < s['addr'] + s['size']:
                return s['offset'] + (addr - s['addr'])
        return None

    def read(self, addr, n):
        o = self.addr_to_off(addr)
        if o is None:
            return None
        return self.data[o:o + n]

    def sec_of(self, addr):
        for s in self.sections:
            if s['addr'] <= addr < s['addr'] + s['size'] and s['size']:
                return s['sname']
        return None

    def cstr(self, addr, maxlen=200):
        b = self.read(addr, maxlen)
        if b is None:
            return None
        return b.split(b'\0')[0].decode('utf-8', 'replace')

    def find_bytes(self, pat, secname):
        s = self.by_name[secname]
        blob = self.data[s['offset']:s['offset'] + s['size']]
        out = []
        i = blob.find(pat)
        while i >= 0:
            out.append(s['addr'] + i)
            i = blob.find(pat, i + 1)
        return out
