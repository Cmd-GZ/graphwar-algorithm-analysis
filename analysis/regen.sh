#!/usr/bin/env bash
# Regenerate every binary-derived artifact that is NOT committed to the repo.
#
#   ./analysis/regen.sh
#
# Requires: a copy of libgraphwarrust.so (and Graphwar.pck for step 5) in the
#           repository root, plus .venv with capstone/unicorn/zstandard.
# Optional: a Ghidra install under tools/ for the decompiler dumps (step 4).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-../.venv/bin/python}
[ -x "$PY" ] || PY=python3

[ -f ../libgraphwarrust.so ] || {
  echo "!! put your own libgraphwarrust.so in the repository root first"; exit 1; }

echo "== 1. disassembly + cross-reference index -> insns.pkl / xrefs.pkl / relocs.pkl =="
$PY build_index.py

echo "== 2. .eh_frame function table -> fdes.pkl / funcstarts.pkl =="
$PY - <<'PY'
import struct, pickle, sys
sys.path.insert(0, '.')
from elf import Elf
E = Elf('../libgraphwarrust.so')
eh = E.sec('.eh_frame'); d = E.data
pos, end, fdes = eh['offset'], eh['offset'] + eh['size'], []
while pos < end:
    length = struct.unpack_from('<I', d, pos)[0]
    if length == 0:
        break
    p = pos + 4
    if struct.unpack_from('<I', d, p)[0] == 0:      # CIE, skip
        pos = p + length
        continue
    pc_begin = struct.unpack_from('<i', d, p + 4)[0] + (p + 4)
    pc_range = struct.unpack_from('<I', d, p + 8)[0]
    fdes.append((pc_begin, pc_range))
    pos = p + length
fdes.sort()
pickle.dump(fdes, open('fdes.pkl', 'wb'))
pickle.dump([a for a, _ in fdes], open('funcstarts.pkl', 'wb'))
with open('funcstarts.txt', 'w') as fh:
    for a, _ in fdes:
        fh.write('%08x\n' % a)
print('   -> %d functions' % len(fdes))
PY

echo "== 3. rodata strings -> lib_strings.txt   (do NOT commit: leaks the developer's build paths) =="
if command -v strings >/dev/null; then
  strings -t x -n 5 ../libgraphwarrust.so > lib_strings.txt
  echo "   -> lib_strings.txt"
else
  echo "   (skipped: no 'strings' binary)"
fi

echo "== 4. Ghidra decompiler dumps (optional) -> decomp_*.c =="
if [ -d ../tools/ghidra_12.2_PUBLIC ]; then
  export JAVA_HOME_OVERRIDE=${JAVA_HOME_OVERRIDE:-/usr/lib/jvm/java-21-openjdk}
  export _JAVA_OPTIONS="-Duser.home=$PWD/../tools/home"
  HL=../tools/ghidra_12.2_PUBLIC/support/analyzeHeadless
  $HL ghidra_proj gw -import ../libgraphwarrust.so -overwrite >/dev/null
  # NOTE: Ghidra's image base is 0x100000, so file address 0x3c2530 == Ghidra 0x4c2530
  $HL ghidra_proj gw -process libgraphwarrust.so -noanalysis \
      -scriptPath ../tools/ghidra_scripts \
      -postScript DumpAt.java 0x4c2530 0x5eb9d0 0x5ed670 0x4c5f70 0x4c2bc0 decomp_key.c
  echo "   -> decomp_key.c"
else
  echo "   (skipped: no Ghidra under tools/)"
fi

echo "== 5. unpack Graphwar.pck -> pck/   (do NOT commit: game assets) =="
if [ -f ../Graphwar.pck ]; then
  $PY - <<'PY'
import struct, os, json
d = open('../Graphwar.pck', 'rb').read()
base = 0x70                                     # file_base for this build
dir_off = struct.unpack_from('<Q', d, 0x20)[0]  # directory offset (absolute)
pos = dir_off
n = struct.unpack_from('<I', d, pos)[0]; pos += 4
os.makedirs('pck', exist_ok=True)
index = []
for _ in range(n):
    ln = struct.unpack_from('<I', d, pos)[0]; pos += 4
    path = d[pos:pos + ln].decode('utf-8', 'replace').rstrip('\0'); pos += ln
    off, size = struct.unpack_from('<QQ', d, pos); pos += 16
    pos += 16                                    # md5
    flags = struct.unpack_from('<I', d, pos)[0]; pos += 4
    fp = os.path.join('pck', path)
    os.makedirs(os.path.dirname(fp) or '.', exist_ok=True)
    open(fp, 'wb').write(d[base + off: base + off + size])
    index.append({'path': path, 'off': off, 'size': size, 'flags': flags})
json.dump(index, open('pck_index.json', 'w'), indent=0)
print('   -> pck/ (%d files)' % len(index))
PY
else
  echo "   (skipped: no Graphwar.pck)"
fi

echo "== 6. sanity: the oracle must still agree with graphwar_curve.py =="
$PY difftest_parser.py | tail -2
$PY fuzz.py 25 3 | tail -1
