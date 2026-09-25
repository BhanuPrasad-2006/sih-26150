"""Long fuzz run:  python backend/tests/manual/fuzz_parsers.py [iterations_per_seed] [base_seed]
Prints every contract violation with the seed needed to reproduce it."""
import collections
import faulthandler
import sys
import time

sys.path.insert(0, ".")
faulthandler.dump_traceback_later(6 * 3600, exit=True)          # a hang aborts with a traceback

from backend.tests import fuzz_lib as F

n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
base = int(sys.argv[2]) if len(sys.argv) > 2 else 0
seeds = F.build_seeds()
t = time.time()
findings = F.fuzz(seeds, n, base)
print(f"{len(seeds) * n} mutated images in {time.time() - t:.0f}s; contract violations: {len(findings)}")
for k, v in collections.Counter((f.plugin, f.stage, f.problem.split(':')[0][:60]) for f in findings).most_common(20):
    print(v, k)
for f in findings[:20]:
    print(f)
sys.exit(1 if findings else 0)
