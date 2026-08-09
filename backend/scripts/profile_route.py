import sys, time, cProfile, pstats, io
sys.path.insert(0, '/app/backend')
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
from core.routing import compute_route
from core.seamarks import get_seamarks
get_seamarks()
t0 = time.time()
pr = cProfile.Profile(); pr.enable()
r = compute_route(47.63713, -2.76147, 47.54153, -2.90018, 1.0, 0.5, 10.0, tide_m=2.19)
pr.disable()
print("total", round(time.time() - t0, 1), "s wp:", len(r["waypoints"]))
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(20)
print(s.getvalue())
