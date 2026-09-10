import requests, time
s = requests.Session()
for i in range(5):
    t = time.time()
    try:
        r = s.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=(10, 30))
        print(i, r.status_code, f"{time.time()-t:.2f}s")
    except Exception as e:
        print(i, "FAIL", repr(e), f"{time.time()-t:.2f}s") 